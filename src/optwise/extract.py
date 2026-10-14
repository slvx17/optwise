"""Input extraction: the model reads, code decides (DESIGN #11).

The LLM only labels which span of the question is which input (role + verbatim span). Code parses
the span into a date. A span not found in the question is dropped, so no date can be invented;
a span code cannot pin to one day is returned unresolved (ambiguous / partial / missing), never guessed.
"""
import calendar
import json
import os
import re
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROLES = ("program_end", "dso_recommended", "ead_expiry")
MODEL = os.environ.get("OPTWISE_EXTRACT_MODEL", "deepseek/deepseek-v4.1-flash")

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
SEASONS = {"spring": (3, 6), "summer": (6, 8), "fall": (9, 12), "autumn": (9, 12), "winter": (12, 2)}
ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
NUMERIC = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b")
MONTH_DAY = re.compile(rf"\b{MONTH}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?", re.I)
DAY_MONTH = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{MONTH}(?:,?\s+(\d{{4}}))?", re.I)
MONTH_YEAR = re.compile(rf"\b{MONTH}\s+(\d{{4}})\b", re.I)
SEASON_YEAR = re.compile(r"\b(spring|summer|fall|autumn|winter)\s+(\d{4})\b", re.I)
# Anything that looks like a date, for the cross-check against the LLM's spans.
ANY_DATE = re.compile("|".join(p.pattern for p in (ISO, NUMERIC, MONTH_DAY, DAY_MONTH, MONTH_YEAR, SEASON_YEAR)), re.I)


@dataclass(frozen=True)
class Parsed:
    status: str  # exact | ambiguous | partial | missing
    value: date | None = None  # set only when status == "exact"
    candidates: tuple[date, ...] = ()  # ambiguous: every valid reading; partial: (first, last) day of the range
    note: str = ""


@dataclass(frozen=True)
class Extracted:
    role: str  # one of ROLES, or "other" (a date that is not a planner input, e.g. commencement)
    span: str
    parsed: Parsed


@dataclass(frozen=True)
class Extraction:
    inputs: tuple[Extracted, ...]
    unlabelled: tuple[str, ...] = ()  # date-like spans the LLM did not label: ask the student
    rejected: tuple[str, ...] = ()  # LLM spans not in the question: dropped, counted in evals

    def exact(self) -> dict[str, date]:
        """Inputs safe to compute with. A role given twice with different dates is a conflict, not a pick."""
        out: dict[str, set[date]] = {}
        for e in self.inputs:
            if e.role in ROLES and e.parsed.status == "exact":
                out.setdefault(e.role, set()).add(e.parsed.value)
        return {role: ds.pop() for role, ds in out.items() if len(ds) == 1}


def _safe(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _month(name: str) -> int:
    return MONTHS[name.lower().rstrip(".")[:3]]


def parse_span(span: str) -> Parsed:
    """Pin a span to one day, or say why it cannot be. Never assumes a missing year or day."""
    s = span.strip()
    if m := ISO.search(s):
        d = _safe(*map(int, m.groups()))
        return Parsed("exact", d) if d else Parsed("missing", note="not a real date")
    if m := NUMERIC.search(s):
        a, b, y = map(int, m.groups())
        readings = tuple(dict.fromkeys(d for d in (_safe(y, a, b), _safe(y, b, a)) if d))  # US m/d, then d/m
        if len(readings) == 1:
            return Parsed("exact", readings[0])
        if readings:
            return Parsed("ambiguous", candidates=readings, note="day/month order unclear")
        return Parsed("missing", note="not a real date")
    for rx, order in ((MONTH_DAY, "md"), (DAY_MONTH, "dm")):
        if m := rx.search(s):
            g = m.groups()  # (month, day, year) or (day, month, year); the MONTH group is captured too
            mon, day, year = (g[0], g[1], g[2]) if order == "md" else (g[1], g[0], g[2])
            if not year:
                return Parsed("partial", note="year missing")
            d = _safe(int(year), _month(mon), int(day))
            return Parsed("exact", d) if d else Parsed("missing", note="not a real date")
    if m := MONTH_YEAR.search(s):
        y, mo = int(m.group(2)), _month(m.group(1))
        return Parsed("partial", candidates=(date(y, mo, 1), date(y, mo, calendar.monthrange(y, mo)[1])), note="day missing")
    if m := SEASON_YEAR.search(s):
        y = int(m.group(2))
        first, last = SEASONS[m.group(1).lower()]
        end_year = y + 1 if last < first else y
        return Parsed("partial", candidates=(date(y, first, 1), date(end_year, last, calendar.monthrange(end_year, last)[1])),
                      note="season only")
    return Parsed("missing", note="no date in span")


PROMPT = """You label dates in a student's question about US F-1 OPT / STEM OPT.
Return every date mention, copying its text EXACTLY as written in the question (the span), with a role:
- program_end: the program end date on the I-20 (also "graduate", "finish", "program ends")
- dso_recommended: when the DSO recommended OPT / entered it in SEVIS
- ead_expiry: when the current OPT EAD card expires
- other: any other date (commencement, finals, degree conferral, today)
Do not convert, complete or correct dates. Vague mentions ("this spring", "summer 2027") are spans too.
If the question has no date mention, return an empty list."""

SCHEMA = {
    "name": "date_mentions",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {"mentions": {"type": "array", "items": {
            "type": "object",
            "properties": {"role": {"type": "string", "enum": [*ROLES, "other"]}, "span": {"type": "string"}},
            "required": ["role", "span"], "additionalProperties": False}}},
        "required": ["mentions"],
        "additionalProperties": False,
    },
}


def _api_key() -> str:
    if key := os.environ.get("OPENROUTER_API_KEY"):
        return key
    env = Path(__file__).parents[2] / ".env"
    for line in env.read_text().splitlines() if env.exists() else ():
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("OPENROUTER_API_KEY not set (env or .env)")


def llm_label(question: str, model: str = MODEL) -> tuple[list[dict], dict]:
    """Ask the model for {role, span} mentions. Returns (mentions, usage). Raises on HTTP or schema errors."""
    body = {
        "model": model,
        "messages": [{"role": "system", "content": PROMPT}, {"role": "user", "content": question}],
        "response_format": {"type": "json_schema", "json_schema": SCHEMA},
        "temperature": 0,
        "max_tokens": 2000,  # reasoning models spend tokens before the JSON
        "usage": {"include": True},
    }
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.load(r)
    mentions = json.loads(resp["choices"][0]["message"]["content"])["mentions"]
    return mentions, resp.get("usage", {})


def extract(question: str, mentions: list[dict]) -> Extraction:
    """Combine the LLM's labelled spans with code parsing and a regex cross-check."""
    q = question.lower()
    inputs, rejected = [], []
    for m in mentions:
        span, role = m["span"].strip(), m["role"]
        if not span or span.lower() not in q:
            rejected.append(span)
            continue
        inputs.append(Extracted(role if role in ROLES else "other", span, parse_span(span)))
    covered = " ".join(e.span.lower() for e in inputs)
    unlabelled = tuple(m.group(0) for m in ANY_DATE.finditer(question) if m.group(0).lower() not in covered)
    return Extraction(tuple(inputs), unlabelled, tuple(rejected))

