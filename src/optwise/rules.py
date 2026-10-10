import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

FIELDS = ("id", "description", "value", "unit", "source_url", "verified_on")


@dataclass(frozen=True)
class Rule:
    id: str
    description: str
    value: int
    unit: str
    source_url: str
    verified_on: date


def load_rules(path: str | Path) -> dict[str, Rule]:
    """Load rules keyed by id. A rule without a source or verification date is rejected."""
    with open(path, "rb") as f:
        entries = tomllib.load(f).get("rule", [])
    rules: dict[str, Rule] = {}
    for entry in entries:
        missing = [k for k in FIELDS if not entry.get(k) and entry.get(k) != 0]
        if missing:
            raise ValueError(f"rule {entry.get('id', '?')!r} missing {missing}")
        rule = Rule(**{k: entry[k] for k in FIELDS})
        if rule.id in rules:
            raise ValueError(f"duplicate rule id {rule.id!r}")
        rules[rule.id] = rule
    return rules
