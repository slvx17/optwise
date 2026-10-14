"""Narration: a code template is always shown; an LLM reply is added only if it passes validators (DESIGN #12).

The template states the plan from the engine. The reply answers what the template cannot: false premises,
multi-part questions, "why". A reply that fails any validator is dropped (not retried); the student still
gets the template. If the LLM is unavailable, the template alone is the answer.
"""
import json
import re
from dataclasses import dataclass, field
from datetime import date

from optwise import llm
from optwise.extract import ANY_DATE, parse_span
from optwise.planner import Step
from optwise.rules import Rule

MODELS = llm.models("OPTWISE_NARRATOR_MODELS", "deepseek/deepseek-v4.1-flash")

WHERE_TO_FIND = {
    "program_end": "your program end date (on your I-20, page 1, \"Program End Date\")",
    "dso_recommended": "the date your DSO entered the OPT recommendation in SEVIS (your DSO can tell you)",
    "ead_expiry": "your current OPT EAD expiry date (on the card)",
}
CONDITION_WORDS = re.compile(r"\b(injunction|court|blocked|contested|not in (force|effect)|lifted|litigation)\b", re.I)


def _d(d: date) -> str:
    return f"{d:%B} {d.day}, {d.year}"


def template(steps: list[Step], rules: dict[str, Rule], missing: list[str]) -> str:
    """Deterministic answer from the engine. Every date and number here comes from code or rule data."""
    lines = []
    for s in steps:
        lines.append(f"{s.label}: no earlier than {_d(s.earliest)} and no later than {_d(s.latest)}. [{', '.join(s.cites)}]")
        if s.conservative_latest:
            c = rules["opt_file_after_end"].contested
            lines.append(f"Conservative target: {_d(s.conservative_latest)}. This is the limit if the court order "
                         f"blocking the {c.value}-day rule is lifted; the {rules['opt_file_after_end'].value}-day limit is in force today.")
        if "dso_recommended" in s.open_inputs:
            dso = rules["opt_file_after_dso_recommendation"]
            lines.append(f"You must also file within {dso.value} days of your DSO's recommendation, which can make "
                         f"your deadline earlier. Add that date to see it.")
    for role in missing:
        if not any(role in s.open_inputs for s in steps):
            lines.append(f"To date your plan, add {WHERE_TO_FIND[role]}.")
    return "\n".join(lines)


PROMPT = """You answer a student's question about US F-1 OPT / STEM OPT using ONLY the facts given.
Facts: rules (each with an exact quote from 8 CFR 214.2(f)) and, if present, a plan computed by code.
The plan is already shown to the student above your reply, so do not repeat it; answer what the question
actually asks: correct a false premise, answer each part, or explain why a date is what it is.
Hard rules:
- Never calculate: no adding or subtracting days, no remaining counts. Use only dates and numbers that
  appear in the facts or the question; if the answer needs a calculation the plan does not contain, say
  the planner does not compute it yet.
- Never complete a date: if the question gives a date without a year, or one like 05/06/2027 that can be
  read two ways, do not restate it as a full date; ask for the exact date instead.
- In `answer`, write dates like "May 20, 2027". List every date you mention in `dates` as YYYY-MM-DD.
- Cite the rule ids you rely on. Each entry in `quotes` must be copied exactly from a rule's quote.
- A rule's `contested` value is NOT in force; if you mention it, say it is blocked by a court order.
- If an input is missing, do not guess it; say what is needed.
- Not legal advice: state what the rules say, do not tell the student what to do. At most 90 words."""

SCHEMA = {
    "name": "reply",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "cited_rule_ids": {"type": "array", "items": {"type": "string"}},
            "quotes": {"type": "array", "items": {"type": "string"}},
            "dates": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["answer", "cited_rule_ids", "quotes", "dates"],
        "additionalProperties": False,
    },
}


@dataclass
class Answer:
    template: str
    reply: str | None = None  # None when unavailable or rejected
    rejected: list[str] = field(default_factory=list)  # validator failures, for evals and logs (no request text)
    usage: dict = field(default_factory=dict)


def facts(steps: list[Step], rules: dict[str, Rule], missing: list[str]) -> dict:
    return {
        "rules": [{"id": r.id, "description": r.description, "value": r.value, "unit": r.unit, "quote": r.quote,
                   **({"contested": {"value": r.contested.value, "quote": r.contested.quote, "status": r.contested.status}}
                      if r.contested else {})} for r in rules.values()],
        "plan": [{"label": s.label, "earliest": s.earliest.isoformat(), "latest": s.latest.isoformat(),
                  "conservative_latest": s.conservative_latest and s.conservative_latest.isoformat(),
                  "open_inputs": list(s.open_inputs), "cites": list(s.cites)} for s in steps],
        "missing_inputs": missing,
    }


def validate(reply: dict, question: str, f: dict) -> list[str]:
    """Reasons to drop the reply; empty means show it. Checks are code, so they are exact and free."""
    errors = []
    rule_ids = {r["id"] for r in f["rules"]}
    quotes = [r["quote"] for r in f["rules"]] + [r["contested"]["quote"] for r in f["rules"] if "contested" in r]
    allowed_dates = {v for s in f["plan"] for k, v in s.items() if k in ("earliest", "latest", "conservative_latest") and v}
    # Dates and numbers the student or the sources wrote may be repeated ("not 90, but 150"); new ones may not.
    source_text = question + " " + json.dumps(f)
    allowed_dates |= {p.value.isoformat() for m in ANY_DATE.finditer(source_text) if (p := parse_span(m.group(0))).value}
    numbers = {int(n) for n in re.findall(r"\b\d+\b", source_text)}
    text = reply["answer"]

    if not text.strip():
        errors.append("empty answer")
    if bad := set(reply["cited_rule_ids"]) - rule_ids:
        errors.append(f"cites unknown rule ids {sorted(bad)}")
    if any(q.strip() not in " ".join(quotes) for q in reply["quotes"]):
        errors.append("quote not in any rule source")
    if bad := set(reply["dates"]) - allowed_dates:
        errors.append(f"lists a date the engine did not compute {sorted(bad)}")
    in_text = {p.value.isoformat() for m in ANY_DATE.finditer(text) if (p := parse_span(m.group(0))).value}
    if bad := in_text - allowed_dates:
        errors.append(f"text states a date the engine did not compute {sorted(bad)}")
    if bad := {int(n) for n in re.findall(r"\b(\d+)[- ]days?\b", text)} - numbers:
        errors.append(f"states a day count no rule has {sorted(bad)}")
    # ponytail: keyword check that a contested value comes with its condition; a model could still
    # word around it. Human wording review per release covers the rest (DESIGN #6).
    contested = [r["contested"]["value"] for r in f["rules"] if "contested" in r]
    after_end = r"[- ]days? (after|following|from) (your |the )?(program end|graduat|complet|end of)"
    if any(re.search(rf"\b{v}{after_end}", text, re.I) for v in contested) and not CONDITION_WORDS.search(text):
        errors.append("mentions a contested value without its condition")
    return errors


def narrate(question: str, steps: list[Step], rules: dict[str, Rule], missing: list[str]) -> Answer:
    """Template always; reply only when the LLM answers and every validator passes."""
    ans = Answer(template(steps, rules, missing))
    f = facts(steps, rules, missing)
    try:
        reply, ans.usage = llm.chat_json(MODELS, PROMPT, f"Facts:\n{json.dumps(f)}\n\nQuestion: {question}", SCHEMA)
    except llm.LLMUnavailable as e:
        ans.rejected = [f"unavailable: {e}"]
        return ans
    ans.rejected = validate(reply, question, f)
    if not ans.rejected:
        ans.reply = reply["answer"]
    return ans
