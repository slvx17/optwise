"""Keyword router: question -> route + candidate rule ids.

ponytail: keyword baseline, free and deterministic. Swap in (or add) an LLM classifier only for
the cases evals/run.py shows this missing its gates.
"""
import re
from dataclasses import dataclass

MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
DATE = re.compile(
    rf"\b\d{{4}}-\d{{2}}-\d{{2}}\b|\b\d{{1,2}}[/.]\d{{1,2}}[/.]\d{{2,4}}\b|\b{MONTH}\s+\d{{1,2}}\b|\b\d{{1,2}}\s+{MONTH}\b",
    re.I,
)
ASKS_WHEN = re.compile(r"\b(when'?s?|deadline|last day|earliest|how long|plan my|by when|right now|why does the tool)\b", re.I)
IN_SCOPE = re.compile(r"\b(opt|stem|i-?765|ead|dso|sevis|sevp|i-?983|unemploy\w*|program end\w*|duration of status|injunction|court ruling|filing window)\b", re.I)
OUT_OF_SCOPE = re.compile(
    r"\b(h-?1b|lottery|green card|cpt|pre-completion|fica|tax(es)?|lawyer|attorney|cover letter|j-1|"
    r"approve|chances|backdate|ignore your rules|cap-exempt|is that legal)\b",
    re.I,
)


@dataclass(frozen=True)
class Route:
    route: str  # deadline | policy | out_of_scope
    rule_ids: tuple[str, ...]


def route(question: str) -> Route:
    q = question.lower()
    asks_date = bool(ASKS_WHEN.search(q)) or bool(DATE.search(q)) and "which date" not in q
    if OUT_OF_SCOPE.search(q) and not asks_date:
        return Route("out_of_scope", ())
    if not IN_SCOPE.search(q) and not re.search(r"\b(graduat\w*|file|filing|apply|apl?y)\b", q):
        return Route("out_of_scope", ())
    return Route("deadline" if asks_date else "policy", _rule_ids(q, asks_date))


def _rule_ids(q: str, asks_date: bool) -> tuple[str, ...]:
    ids = []
    stem = "stem" in q
    if "unemploy" in q:
        ids.append("stem_unemployment_cap")
    if stem and re.search(r"\b(file|filing|when|process|ead|card)\b", q):
        ids.append("stem_file_before_ead_expiry")
    if stem or (ids and not re.search(r"\b(file|apply|deadline)\b", q)):
        return tuple(ids)
    # "when should I file" / "plan my filing" asks for the whole window, both ends.
    whole_window = bool(re.search(r"\b(plan|when \w+ i (file|apply)|when \w+ i \w+ (file|apply))\b", q))
    if whole_window or re.search(r"\b(earliest|before|prior|start filing|months|plan|window|right now)\b", q):
        ids.append("opt_file_before_end")
    if re.search(r"\b(after|last day|deadline|latest|must i be done|how long|by|window|days|injunction|court|"
                 r"duration of status|rule|rejects?|cooked|deadline)\b", q) or "when" in q and "earliest" not in q:
        ids.append("opt_file_after_end")
    if whole_window and "opt_file_after_end" not in ids:
        ids.append("opt_file_after_end")
    # Any dated filing deadline is also capped by 30 days from the DSO recommendation.
    if "dso" in q or "recommend" in q or "earliest" in q or asks_date and "opt_file_after_end" in ids:
        ids.append("opt_file_after_dso_recommendation")
    return tuple(dict.fromkeys(ids))
