from dataclasses import dataclass
from datetime import date, timedelta

from optwise.rules import Rule


@dataclass(frozen=True)
class Step:
    label: str
    earliest: date
    latest: date
    cites: tuple[str, ...]  # rule ids, so every date is traceable to a source


def _days(rule: Rule) -> timedelta:
    if rule.unit != "days":
        raise ValueError(f"rule {rule.id!r} has unit {rule.unit!r}, planner expects 'days'")
    return timedelta(days=rule.value)


def backward_plan(program_end: date, rules: dict[str, Rule]) -> list[Step]:
    """Dated plan worked backward/forward from the program end date. Raises KeyError if a rule is not loaded, ValueError on a unit mismatch."""
    before = rules["opt_file_before_end"]
    after = rules["opt_file_after_end"]
    return [
        Step(
            label="File the OPT application",
            earliest=program_end - _days(before),
            latest=program_end + _days(after),
            cites=(before.id, after.id),
        )
    ]
