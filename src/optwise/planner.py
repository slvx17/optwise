from dataclasses import dataclass
from datetime import date, timedelta

from optwise.rules import Rule


@dataclass(frozen=True)
class Step:
    label: str
    earliest: date
    latest: date
    cites: tuple[str, ...]  # rule ids, so every date is traceable to a source


def backward_plan(program_end: date, rules: dict[str, Rule]) -> list[Step]:
    """Dated plan worked backward/forward from the program end date. Raises KeyError if a rule is not loaded."""
    before = rules["opt_file_before_end"]
    after = rules["opt_file_after_end"]
    return [
        Step(
            label="File the OPT application",
            earliest=program_end - timedelta(days=before.value),
            latest=program_end + timedelta(days=after.value),
            cites=(before.id, after.id),
        )
    ]
