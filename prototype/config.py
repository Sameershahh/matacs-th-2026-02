import hashlib
import json
from pathlib import Path

FACT_TYPES = {"boolean", "integer", "number", "string"}
METHODS = {"capped_ratio", "relative_min", "blended_cap", "checklist"}


class ConfigError(ValueError):
    pass


def load_config(path):
    raw = Path(path).read_bytes()
    config = json.loads(raw)
    validate_config(config)
    return config, hashlib.sha256(raw).hexdigest()


def referenced_facts(criterion):
    if "fact" in criterion:
        return [criterion["fact"]]
    return list(criterion["facts"])


def validate_config(config):
    fact_ids = [fact["id"] for fact in config["facts"]]
    if len(set(fact_ids)) != len(fact_ids):
        raise ConfigError("duplicate fact ids")
    for fact in config["facts"]:
        if fact["type"] not in FACT_TYPES:
            raise ConfigError(f"unknown fact type for {fact['id']}")

    total_weight = sum(item["weight"] for item in config["weighted"])
    if abs(total_weight - 100) > 1e-9:
        raise ConfigError(f"weights add up to {total_weight}, expected 100")

    for item in config["weighted"]:
        if item["method"] not in METHODS:
            raise ConfigError(f"unknown scoring method {item['method']}")

    for group in ("mandatory", "limits", "weighted"):
        for item in config[group]:
            for fact_id in referenced_facts(item):
                if fact_id not in fact_ids:
                    raise ConfigError(f"{group}/{item['id']} uses unknown fact {fact_id}")
