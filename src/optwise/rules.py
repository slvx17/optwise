import re
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

FIELDS = ("id", "description", "value", "unit", "quote", "source_url", "verified_on")
CONTESTED_FIELDS = ("value", "quote", "source_url", "status", "status_url")


@dataclass(frozen=True)
class Contested:
    """A codified value that is not in force (e.g. blocked by a court), shown beside the rule as a conservative option."""
    value: int
    quote: str
    source_url: str
    status: str  # why it is not in force
    status_url: str


@dataclass(frozen=True)
class Rule:
    id: str
    description: str
    value: int
    unit: str
    quote: str  # exact text from the source that states the value
    source_url: str
    verified_on: date
    contested: Contested | None = None


def _require(entry: dict, fields: tuple[str, ...], where: str) -> None:
    missing = [k for k in fields if not entry.get(k) and entry.get(k) != 0]
    if missing:
        raise ValueError(f"{where} missing {missing}")


def _check_quote(value: int, quote: str, where: str) -> None:
    # Whole-number match so value 9 cannot pass on a quote saying "90".
    # Catches typos only; a rule mapped to the wrong number in the quote still needs PR review.
    if not re.search(rf"\b{value}\b", quote):
        raise ValueError(f"{where}: value {value} not found in quote")


def load_rules(path: str | Path) -> dict[str, Rule]:
    """Load rules keyed by id. A rule without a source, quote or verification date, or whose value is not in its quote, is rejected."""
    with open(path, "rb") as f:
        entries = tomllib.load(f).get("rule", [])
    rules: dict[str, Rule] = {}
    for entry in entries:
        where = f"rule {entry.get('id', '?')!r}"
        _require(entry, FIELDS, where)
        _check_quote(entry["value"], entry["quote"], where)
        contested = None
        if "contested" in entry:
            c = entry["contested"]
            _require(c, CONTESTED_FIELDS, f"{where} contested")
            _check_quote(c["value"], c["quote"], f"{where} contested")
            contested = Contested(**{k: c[k] for k in CONTESTED_FIELDS})
        rule = Rule(**{k: entry[k] for k in FIELDS}, contested=contested)
        if rule.id in rules:
            raise ValueError(f"duplicate rule id {rule.id!r}")
        rules[rule.id] = rule
    return rules
