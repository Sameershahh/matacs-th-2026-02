from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

FOUND = "found"


@dataclass
class Flag:
    code: str
    detail: str
    blocking: bool


@dataclass
class Result:
    proposal: str
    status: str = "ranked"
    rank: int | None = None
    score: float | None = None
    breakdown: dict = field(default_factory=dict)
    flags: list = field(default_factory=list)
    reason: str = ""


def round_half_up(value, places=1):
    return float(Decimal(str(value)).quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP))


def fact_entry(extraction, fact_id):
    return extraction.get("facts", {}).get(fact_id) or {}


def status_of(extraction, fact_id):
    return fact_entry(extraction, fact_id).get("status", "not_stated")


def value_of(extraction, fact_id):
    entry = fact_entry(extraction, fact_id)
    if entry.get("status") != FOUND:
        return None
    return entry.get("value")


def capped_ratio(criterion, extraction, cohort):
    value = value_of(extraction, criterion["fact"])
    if value is None:
        return 0.0
    return 100 * min(value / criterion["params"]["full_marks_at"], 1)


def relative_min(criterion, extraction, cohort):
    value = value_of(extraction, criterion["fact"])
    if not value:
        return 0.0
    candidates = [value_of(other, criterion["fact"]) for other in cohort]
    best = min(candidate for candidate in candidates if candidate)
    return 100 * best / value


def blended_cap(criterion, extraction, cohort):
    total = 0.0
    for fact_id, spec in criterion["facts"].items():
        value = value_of(extraction, fact_id) or 0
        total += spec["share"] * min(value / spec["full_marks_at"], 1)
    return 100 * total


def checklist(criterion, extraction, cohort):
    items = criterion["facts"]
    hits = sum(1 for fact_id in items if value_of(extraction, fact_id) is True)
    return 100 * hits / len(items)


METHODS = {
    "capped_ratio": capped_ratio,
    "relative_min": relative_min,
    "blended_cap": blended_cap,
    "checklist": checklist,
}


def mandatory_outcome(criterion, extraction):
    outcomes = []
    for fact_id in criterion["facts"]:
        if status_of(extraction, fact_id) != FOUND:
            outcomes.append("unverified")
        elif value_of(extraction, fact_id) is True:
            outcomes.append("pass")
        else:
            outcomes.append("fail")
    if "fail" in outcomes:
        return "fail"
    if "unverified" in outcomes:
        return "unverified"
    return "pass"


def assess(config, extraction):
    result = Result(proposal=extraction["proposal_id"])
    failures = []

    if extraction.get("error"):
        result.flags.append(Flag("extraction_failed", extraction["error"], True))
        result.status = "flagged"
        return result, failures

    for criterion in config["mandatory"]:
        outcome = mandatory_outcome(criterion, extraction)
        if outcome == "fail":
            failures.append(f"fails mandatory criterion: {criterion['label']}")
        elif outcome == "unverified":
            result.flags.append(
                Flag("mandatory_unverified", f"could not confirm: {criterion['label']}", True)
            )

    for limit in config["limits"]:
        value = value_of(extraction, limit["fact"])
        if value is None:
            result.flags.append(
                Flag("limit_unverifiable", f"no committed figure for: {limit['label']}", True)
            )
        elif value > limit["max"]:
            failures.append(f"exceeds limit: {limit['label']}")

    for instruction in extraction.get("directed_instructions", []):
        result.flags.append(
            Flag("directed_instruction", f"text addressed to the review process: {instruction['quote']}", True)
        )

    start_year = value_of(extraction, "installs_period_start_year")
    window_start = config["reference_year"] - config["experience_window_years"]
    if start_year is not None and start_year < window_start:
        result.flags.append(
            Flag("experience_window", f"experience period starts {start_year}, before {window_start}", False)
        )

    if failures:
        result.status = "ineligible"
    elif any(flag.blocking for flag in result.flags):
        result.status = "flagged"
    return result, failures


def explain(result, failures, config):
    if result.status == "ineligible":
        text = "; ".join(failures)
        return text[0].upper() + text[1:] + "."
    if result.status == "flagged":
        details = "; ".join(flag.detail for flag in result.flags if flag.blocking)
        if result.score is None:
            return f"Held for review ({details})."
        return f"Held for review ({details}). Provisional score {round_half_up(result.score):.1f}."
    weights = {item["id"]: item["weight"] for item in config["weighted"]}
    gaps = {
        key: weights[key] * (1 - value / 100) for key, value in result.breakdown.items()
    }
    weakest = max(gaps, key=gaps.get)
    labels = {item["id"]: item["label"].lower() for item in config["weighted"]}
    return f"Score {round_half_up(result.score):.1f}. Largest deduction: {labels[weakest]} ({gaps[weakest]:.1f} points)."


def rank_proposals(config, extractions):
    assessed = [assess(config, extraction) for extraction in extractions]
    by_id = {extraction["proposal_id"]: extraction for extraction in extractions}
    cohort = [
        by_id[result.proposal]
        for result, _ in assessed
        if result.status != "ineligible" and not by_id[result.proposal].get("error")
    ]

    weights = {item["id"]: item["weight"] for item in config["weighted"]}
    for result, _ in assessed:
        if result.status == "ineligible" or by_id[result.proposal].get("error"):
            continue
        extraction = by_id[result.proposal]
        for criterion in config["weighted"]:
            method = METHODS[criterion["method"]]
            result.breakdown[criterion["id"]] = method(criterion, extraction, cohort)
        result.score = sum(
            weights[key] * value / 100 for key, value in result.breakdown.items()
        )

    ranked = sorted(
        (result for result, _ in assessed if result.status == "ranked"),
        key=lambda result: (-result.score, result.proposal),
    )
    for position, result in enumerate(ranked, start=1):
        result.rank = position

    for result, failures in assessed:
        result.reason = explain(result, failures, config)

    order = {"ranked": 0, "flagged": 1, "ineligible": 2}
    return sorted(
        (result for result, _ in assessed),
        key=lambda result: (order[result.status], result.rank or 0, result.proposal),
    )


def to_ranking_entries(results):
    return [
        {
            "proposal": result.proposal,
            "rank": result.rank,
            "status": result.status,
            "score": None if result.score is None else round_half_up(result.score),
            "reason": result.reason,
        }
        for result in results
    ]
