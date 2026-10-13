import re
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

FIELDS = ("id", "description", "value", "unit", "quote", "source_url", "verified_on")


@dataclass(frozen=True)
class Rule:
    id: str
    description: str
    value: int
    unit: str
    quote: str  # exact text from the source that states the value
    source_url: str
    verified_on: date


def load_rules(path: str | Path) -> dict[str, Rule]:
    """Load rules keyed by id. A rule without a source, quote or verification date, or whose value is not in its quote, is rejected."""
    with open(path, "rb") as f:
        entries = tomllib.load(f).get("rule", [])
    rules: dict[str, Rule] = {}
    for entry in entries:
        missing = [k for k in FIELDS if not entry.get(k) and entry.get(k) != 0]
        if missing:
            raise ValueError(f"rule {entry.get('id', '?')!r} missing {missing}")
        rule = Rule(**{k: entry[k] for k in FIELDS})
        # Whole-number match so value 9 cannot pass on a quote saying "90".
        # Catches typos only; a rule mapped to the wrong number in the quote still needs PR review.
        if not re.search(rf"\b{rule.value}\b", rule.quote):
            raise ValueError(f"rule {rule.id!r}: value {rule.value} not found in quote")
        if rule.id in rules:
            raise ValueError(f"duplicate rule id {rule.id!r}")
        rules[rule.id] = rule
    return rules
