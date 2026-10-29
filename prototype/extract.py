import json
import os
import re

from scoring import FOUND

STATUSES = {"found", "not_stated", "ambiguous"}
MAX_ATTEMPTS = 3

SCREEN_PATTERNS = [
    r"automated (review|evaluation|scoring|assessment)",
    r"(note|message|instruction)s? (to|for) (the )?(ai|llm|model|reviewer|review system|evaluator)",
    r"ignore (all |any )?(previous|prior|above) (instructions|criteria)",
    r"rank (it|this|us|this proposal) (first|number one|#1|highest)",
    r"(full|maximum|top) (marks|score|points) (on|for) all",
    r"pre-?approved by",
]


class ExtractionError(Exception):
    pass


def normalise(text):
    cleaned = text.replace("\u2019", "'").replace("\u2018", "'")
    cleaned = cleaned.replace("\u201c", '"').replace("\u201d", '"')
    return " ".join(cleaned.split()).lower()


def build_prompts(system_template, user_template, config, proposal_id, proposal_text):
    facts = [
        {"id": fact["id"], "type": fact["type"], "definition": fact["description"]}
        for fact in config["facts"]
    ]
    safe_text = proposal_text.replace("</proposal>", "[/proposal]")
    user = (
        user_template.replace("[[PROPOSAL_ID]]", proposal_id)
        .replace("[[FACTS_JSON]]", json.dumps(facts, indent=2))
        .replace("[[PROPOSAL_TEXT]]", safe_text)
    )
    return system_template, user


def screen_text(proposal_text):
    hits = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", proposal_text):
        if any(re.search(pattern, sentence, re.IGNORECASE) for pattern in SCREEN_PATTERNS):
            hits.append({"quote": sentence.strip(), "location": "", "source": "rule"})
    return hits


def type_matches(expected, value):
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, str)


def parse_response(raw):
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise ExtractionError(f"response is not valid JSON: {error}") from error


def validate(config, proposal_id, extraction):
    if not isinstance(extraction, dict):
        raise ExtractionError("response is not a JSON object")
    if extraction.get("proposal_id") != proposal_id:
        raise ExtractionError("proposal_id does not match the request")
    facts = extraction.get("facts")
    if not isinstance(facts, dict):
        raise ExtractionError("missing facts object")
    for fact in config["facts"]:
        entry = facts.get(fact["id"])
        if not isinstance(entry, dict):
            raise ExtractionError(f"missing fact {fact['id']}")
        status = entry.get("status")
        if status not in STATUSES:
            raise ExtractionError(f"bad status for {fact['id']}")
        value = entry.get("value")
        if status == FOUND and not type_matches(fact["type"], value):
            raise ExtractionError(f"wrong value type for {fact['id']}")
        if status == "not_stated" and value is not None:
            raise ExtractionError(f"{fact['id']} is not_stated but has a value")
    if not isinstance(extraction.get("directed_instructions", []), list):
        raise ExtractionError("directed_instructions must be a list")
    extraction.setdefault("directed_instructions", [])


def verify_evidence(extraction, proposal_text):
    source = normalise(proposal_text)
    for entry in extraction["facts"].values():
        quote = entry.get("evidence", "")
        entry["evidence_verified"] = True
        if entry["status"] == "not_stated" or not quote:
            continue
        if normalise(quote) not in source:
            entry["evidence_verified"] = False
            entry["status"] = "ambiguous"
            entry["note"] = (entry.get("note", "") + " Quote not found in source.").strip()
    for item in extraction["directed_instructions"]:
        item["evidence_verified"] = normalise(item.get("quote", "")) in source


def merge_screen_hits(extraction, hits):
    known = {normalise(item.get("quote", "")) for item in extraction["directed_instructions"]}
    for hit in hits:
        if normalise(hit["quote"]) not in known:
            extraction["directed_instructions"].append({**hit, "evidence_verified": True})


def call_model(client, model, system, user):
    response = client.messages.create(
        model=model,
        max_tokens=2500,
        temperature=0,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


def extract_proposal(client, model, config, templates, proposal_id, proposal_text):
    system, user = build_prompts(
        templates["system"], templates["user"], config, proposal_id, proposal_text
    )
    last_error = None
    for _ in range(MAX_ATTEMPTS):
        prompt = user if last_error is None else (
            f"{user}\n\nYour previous reply was rejected: {last_error}. Return corrected JSON only."
        )
        raw = call_model(client, model, system, prompt)
        try:
            extraction = parse_response(raw)
            validate(config, proposal_id, extraction)
        except ExtractionError as error:
            last_error = str(error)
            continue
        verify_evidence(extraction, proposal_text)
        merge_screen_hits(extraction, screen_text(proposal_text))
        return extraction
    raise ExtractionError(f"no valid extraction after {MAX_ATTEMPTS} attempts: {last_error}")


def make_client():
    try:
        from anthropic import Anthropic
    except ImportError as error:
        raise ExtractionError("the anthropic package is not installed") from error

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ExtractionError("ANTHROPIC_API_KEY is not set")
    return Anthropic(api_key=key)
