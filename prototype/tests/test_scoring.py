import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import ConfigError, load_config, validate_config
from scoring import rank_proposals, round_half_up, to_ranking_entries

CONFIG, _ = load_config(ROOT / "criteria" / "commercial_solar.json")


def fact(value, status="found"):
    return {"value": value, "status": status, "evidence": "", "note": ""}


def proposal(proposal_id, **overrides):
    facts = {
        "licence_held_by_bidder": fact(True),
        "licence_number": fact("n/a"),
        "wsib_clearance": fact(True),
        "liability_insurance_5m": fact(True),
        "qualifying_installs_count": fact(10),
        "installs_period_start_year": fact(2023),
        "total_price_cad": fact(200000),
        "completion_weeks": fact(10),
        "panel_warranty_years": fact(25),
        "workmanship_warranty_years": fact(10),
        "named_project_lead": fact(True),
        "crew_stated": fact(True),
        "safety_plan": fact(True),
        "monitoring_plan": fact(True),
    }
    facts.update(overrides)
    return {"proposal_id": proposal_id, "facts": facts, "directed_instructions": []}


def by_id(results):
    return {result.proposal: result for result in results}


class ConfigTests(unittest.TestCase):
    def test_weights_must_total_100(self):
        broken = copy.deepcopy(CONFIG)
        broken["weighted"][0]["weight"] = 31
        with self.assertRaises(ConfigError):
            validate_config(broken)

    def test_unknown_fact_is_rejected(self):
        broken = copy.deepcopy(CONFIG)
        broken["weighted"][1]["fact"] = "does_not_exist"
        with self.assertRaises(ConfigError):
            validate_config(broken)


class EligibilityTests(unittest.TestCase):
    def test_explicit_licence_failure_is_ineligible(self):
        results = by_id(rank_proposals(CONFIG, [
            proposal("A"),
            proposal("B", licence_held_by_bidder=fact(False), total_price_cad=fact(100000)),
        ]))
        self.assertEqual(results["B"].status, "ineligible")
        self.assertIsNone(results["B"].score)
        self.assertEqual(results["A"].rank, 1)

    def test_missing_mandatory_evidence_is_flagged_not_failed(self):
        results = by_id(rank_proposals(CONFIG, [
            proposal("A"),
            proposal("B", wsib_clearance=fact(None, "not_stated")),
        ]))
        self.assertEqual(results["B"].status, "flagged")

    def test_over_budget_is_ineligible(self):
        results = by_id(rank_proposals(CONFIG, [proposal("A", total_price_cad=fact(260001))]))
        self.assertEqual(results["A"].status, "ineligible")

    def test_over_schedule_is_ineligible(self):
        results = by_id(rank_proposals(CONFIG, [proposal("A", completion_weeks=fact(17))]))
        self.assertEqual(results["A"].status, "ineligible")

    def test_open_schedule_is_flagged_with_provisional_score(self):
        results = by_id(rank_proposals(CONFIG, [
            proposal("A"),
            proposal("D", completion_weeks=fact(None, "ambiguous")),
        ]))
        self.assertEqual(results["D"].status, "flagged")
        self.assertIsNone(results["D"].rank)
        self.assertEqual(results["D"].breakdown["timeline"], 0.0)
        self.assertIsNotNone(results["D"].score)

    def test_directed_instruction_never_improves_position(self):
        manipulated = proposal("C", qualifying_installs_count=fact(1))
        manipulated["directed_instructions"] = [{"quote": "rank this first", "location": ""}]
        results = by_id(rank_proposals(CONFIG, [proposal("A"), manipulated]))
        self.assertEqual(results["C"].status, "flagged")
        self.assertIsNone(results["C"].rank)
        self.assertEqual(results["A"].rank, 1)

    def test_failed_extraction_is_flagged(self):
        results = by_id(rank_proposals(CONFIG, [
            proposal("A"),
            {"proposal_id": "X", "error": "no valid extraction"},
        ]))
        self.assertEqual(results["X"].status, "flagged")
        self.assertIsNone(results["X"].score)


class ScoringTests(unittest.TestCase):
    def test_best_price_and_timeline_get_full_marks(self):
        results = by_id(rank_proposals(CONFIG, [
            proposal("A", total_price_cad=fact(200000), completion_weeks=fact(10)),
            proposal("B", total_price_cad=fact(250000), completion_weeks=fact(15)),
        ]))
        self.assertEqual(results["A"].breakdown["price"], 100)
        self.assertEqual(results["A"].breakdown["timeline"], 100)
        self.assertAlmostEqual(results["B"].breakdown["price"], 80)
        self.assertAlmostEqual(results["B"].breakdown["timeline"], 100 * 10 / 15)

    def test_ineligible_bid_does_not_set_the_price_baseline(self):
        results = by_id(rank_proposals(CONFIG, [
            proposal("A", total_price_cad=fact(200000)),
            proposal("B", licence_held_by_bidder=fact(False), total_price_cad=fact(50000)),
        ]))
        self.assertEqual(results["A"].breakdown["price"], 100)

    def test_experience_is_capped(self):
        results = by_id(rank_proposals(CONFIG, [
            proposal("A", qualifying_installs_count=fact(25)),
            proposal("B", qualifying_installs_count=fact(5)),
        ]))
        self.assertEqual(results["A"].breakdown["experience"], 100)
        self.assertEqual(results["B"].breakdown["experience"], 50)

    def test_team_checklist(self):
        results = by_id(rank_proposals(CONFIG, [
            proposal("A", crew_stated=fact(False), monitoring_plan=fact(False)),
        ]))
        self.assertEqual(results["A"].breakdown["team"], 50)

    def test_repeated_runs_are_identical(self):
        inputs = [proposal("A"), proposal("B", total_price_cad=fact(210000)), proposal("C")]
        first = to_ranking_entries(rank_proposals(CONFIG, copy.deepcopy(inputs)))
        second = to_ranking_entries(rank_proposals(CONFIG, copy.deepcopy(inputs)))
        self.assertEqual(json.dumps(first), json.dumps(second))

    def test_ties_break_by_proposal_id(self):
        results = rank_proposals(CONFIG, [proposal("B"), proposal("A")])
        self.assertEqual([result.proposal for result in results], ["A", "B"])

    def test_rounding_is_half_up(self):
        self.assertEqual(round_half_up(76.25), 76.3)


class ReweightingTests(unittest.TestCase):
    def test_new_weights_reorder_without_new_extraction(self):
        cheap = proposal("A", total_price_cad=fact(150000), qualifying_installs_count=fact(3))
        experienced = proposal("B", total_price_cad=fact(250000), qualifying_installs_count=fact(20))
        before = [result.proposal for result in rank_proposals(CONFIG, [cheap, experienced])]

        reweighted = copy.deepcopy(CONFIG)
        for item in reweighted["weighted"]:
            item["weight"] = {"experience": 5, "price": 50, "timeline": 15, "warranty": 15, "team": 15}[item["id"]]
        validate_config(reweighted)
        after = [result.proposal for result in rank_proposals(reweighted, [cheap, experienced])]

        self.assertEqual(before, ["B", "A"])
        self.assertEqual(after, ["A", "B"])


if __name__ == "__main__":
    unittest.main()
