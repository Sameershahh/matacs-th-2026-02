import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from config import load_config
from extract import ExtractionError, extract_proposal, make_client
from scoring import rank_proposals, to_ranking_entries

ROOT = Path(__file__).parent
DEFAULT_MODEL = "claude-sonnet-5-5"


def read_templates():
    system = (ROOT / "prompts" / "extraction_system.txt").read_text()
    user = (ROOT / "prompts" / "extraction_user.txt").read_text()
    return {"system": system, "user": user}


def sha256_text(*parts):
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode())
    return digest.hexdigest()


def write_atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(handle, "w") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")
    os.replace(temp_name, path)


def load_extractions(directory):
    return [json.loads(path.read_text()) for path in sorted(Path(directory).glob("*.json"))]


def run_extraction(config, templates, proposals_dir, model):
    client = make_client()
    extractions = []
    for path in sorted(Path(proposals_dir).glob("*.txt")):
        proposal_id = path.stem
        try:
            extraction = extract_proposal(
                client, model, config, templates, proposal_id, path.read_text()
            )
        except ExtractionError as error:
            extraction = {"proposal_id": proposal_id, "error": str(error)}
        extractions.append(extraction)
    return extractions


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Rank proposals against a criteria file.")
    parser.add_argument("--criteria", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--proposals", help="directory of <id>.txt files; calls the model")
    source.add_argument("--extractions", help="directory of saved extraction JSON; no model call")
    parser.add_argument("--out", default=str(ROOT / "runs"))
    parser.add_argument("--model", default=os.environ.get("MODEL", DEFAULT_MODEL))
    parser.add_argument("--dry-run", action="store_true", help="print the plan and exit without writing")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    config, criteria_hash = load_config(args.criteria)
    templates = read_templates()
    prompt_hash = sha256_text(templates["system"], templates["user"])

    source_dir = args.proposals or args.extractions
    if not Path(source_dir).is_dir():
        print(f"not a directory: {source_dir}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(json.dumps({
            "mode": "extract" if args.proposals else "replay",
            "inputs": sorted(path.name for path in Path(source_dir).iterdir()),
            "criteria_sha256": criteria_hash,
            "prompt_sha256": prompt_hash,
            "model": args.model if args.proposals else None,
            "writes": None,
        }, indent=2))
        return 0

    if args.proposals:
        try:
            extractions = run_extraction(config, templates, args.proposals, args.model)
        except ExtractionError as error:
            print(str(error), file=sys.stderr)
            return 2
    else:
        extractions = load_extractions(args.extractions)

    results = rank_proposals(config, extractions)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(args.out) / stamp
    if run_dir.exists():
        print(f"refusing to overwrite {run_dir}", file=sys.stderr)
        return 1

    for extraction in extractions:
        write_atomic(run_dir / "extractions" / f"{extraction['proposal_id']}.json", extraction)
    write_atomic(run_dir / "ranking.json", to_ranking_entries(results))
    write_atomic(run_dir / "breakdown.json", [
        {
            "proposal": result.proposal,
            "status": result.status,
            "criteria": result.breakdown,
            "flags": [flag.__dict__ for flag in result.flags],
        }
        for result in results
    ])
    write_atomic(run_dir / "run.json", {
        "timestamp": stamp,
        "mode": "extract" if args.proposals else "replay",
        "model": args.model if args.proposals else None,
        "temperature": 0 if args.proposals else None,
        "criteria_category": config["category"],
        "criteria_version": config["version"],
        "criteria_sha256": criteria_hash,
        "prompt_sha256": prompt_hash,
    })
    print(json.dumps(to_ranking_entries(results), indent=2))
    print(f"\nrun saved to {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
