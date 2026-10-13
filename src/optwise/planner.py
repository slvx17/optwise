from dataclasses import dataclass
from datetime import date, timedelta

from optwise.rules import Rule


@dataclass(frozen=True)
class Step:
    label: str
    earliest: date
    latest: date  # legal limit under the rules in force
    cites: tuple[str, ...]  # rule ids, so every date is traceable to a source
    conservative_latest: date | None = None  # limit if a contested rule takes effect; shown beside, never instead of, latest
    open_inputs: tuple[str, ...] = ()  # inputs not given, so latest is only an upper bound; never guessed


def _days(rule: Rule, value: int | None = None) -> timedelta:
    if rule.unit != "days":
        raise ValueError(f"rule {rule.id!r} has unit {rule.unit!r}, planner expects 'days'")
    return timedelta(days=rule.value if value is None else value)


def backward_plan(program_end: date, rules: dict[str, Rule], dso_recommended: date | None = None) -> list[Step]:
    """Dated plan worked backward/forward from the program end date.

    Without dso_recommended the 30-day-from-recommendation limit cannot be dated, so it is
    listed in open_inputs instead of assumed. Raises KeyError if a rule is not loaded,
    ValueError on a unit mismatch.
    """
    before = rules["opt_file_before_end"]
    after = rules["opt_file_after_end"]
    dso = rules["opt_file_after_dso_recommendation"]

    earliest = program_end - _days(before)
    latest = program_end + _days(after)
    conservative = program_end + _days(after, after.contested.value) if after.contested else None
    open_inputs: tuple[str, ...] = ()
    if dso_recommended is None:
        open_inputs = ("dso_recommended",)
    else:
        earliest = max(earliest, dso_recommended)  # cannot file before the recommendation exists
        dso_limit = dso_recommended + _days(dso)
        latest = min(latest, dso_limit)
        if conservative:
            conservative = min(conservative, dso_limit)
    if conservative == latest:
        conservative = None  # contested value does not change this plan

    return [
        Step(
            label="File the OPT application",
            earliest=earliest,
            latest=latest,
            cites=(before.id, after.id, dso.id),
            conservative_latest=conservative,
            open_inputs=open_inputs,
        )
    ]
