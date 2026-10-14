"""Web app: one page, two JSON endpoints. Stateless: nothing stored, request bodies not logged (DESIGN #8).

POST /api/plan {program_end, dso_recommended}  -> plan from code only, no LLM, free
POST /api/ask  {question}                       -> route, extract (LLM), plan, narrate (LLM)

Run: PYTHONPATH=src python3 -m optwise.web   (PORT env, default 8000)
"""
import hashlib
import json
import os
import threading
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from optwise import llm
from optwise.extract import ROLES, extract, llm_label
from optwise.narrate import WHERE_TO_FIND, narrate
from optwise.planner import backward_plan
from optwise.router import route
from optwise.rules import load_rules

ROOT = Path(__file__).parents[2]
RULES_PATH = ROOT / "data" / "rules.toml"
RULES = load_rules(RULES_PATH)
RULES_VERSION = hashlib.sha256(RULES_PATH.read_bytes()).hexdigest()[:12]
PAGE = (Path(__file__).parent / "static" / "index.html").read_bytes()
OPT_ROLES = ("program_end", "dso_recommended")


class Budget:
    """Global LLM spend ceilings in real dollars (usage.cost), reset daily and weekly, UTC (DESIGN #14).

    ponytail: in memory, one instance; a restart resets the counters. The OpenRouter key's monthly
    limit is the hard floor under that. Move to a shared store if we run more than one instance.
    """

    def __init__(self, daily_usd: float, weekly_usd: float):
        self.daily, self.weekly = daily_usd, weekly_usd
        self.lock = threading.Lock()
        self.day = self.week = None
        self.spent_day = self.spent_week = 0.0

    def _roll(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self.day:
            self.day, self.spent_day = today, 0.0
        if today.isocalendar()[:2] != self.week:
            self.week, self.spent_week = today.isocalendar()[:2], 0.0

    def open(self) -> bool:
        # ponytail: check-then-spend, so parallel asks can overshoot by at most MAX_ASKS calls (~$0.003).
        with self.lock:
            self._roll()
            return self.spent_day < self.daily and self.spent_week < self.weekly

    def add(self, usd: float) -> None:
        with self.lock:
            self._roll()
            self.spent_day += usd
            self.spent_week += usd


BUDGET = Budget(float(os.environ.get("OPTWISE_DAILY_USD", 1)), float(os.environ.get("OPTWISE_WEEKLY_USD", 5)))
ASK_SLOTS = threading.BoundedSemaphore(int(os.environ.get("OPTWISE_MAX_ASKS", 8)))  # LLM asks in flight at once
class PerIP:
    """Fixed hourly window per client IP. A speed bump, not a wall: campus NAT shares one IP, and an
    attacker can rotate IPs, so it is set loose (100/h) and the global Budget is the real ceiling."""

    def __init__(self, per_hour: int):
        self.per_hour, self.lock, self.hour, self.counts = per_hour, threading.Lock(), None, {}

    def allow(self, ip: str) -> bool:
        with self.lock:
            hour = datetime.now(timezone.utc).strftime("%Y%m%d%H")
            if hour != self.hour:
                self.hour, self.counts = hour, {}  # dropping the dict each hour also bounds memory
            self.counts[ip] = self.counts.get(ip, 0) + 1
            return self.counts[ip] <= self.per_hour


PER_IP = PerIP(int(os.environ.get("OPTWISE_ASKS_PER_IP_HOUR", 100)))
TRUST_PROXY = os.environ.get("OPTWISE_TRUST_PROXY") == "1"  # set only behind a proxy that appends X-Forwarded-For
RESTING = "Written answers are resting ({why}). Your plan below is computed without them; enter or edit your dates."


def _date(v) -> date | None:
    return date.fromisoformat(v) if v else None


def plan_json(program_end: date | None, dso: date | None) -> dict:
    """Structured plan for the screen. Every date here comes from the engine."""
    out = {"rules_version": RULES_VERSION, "steps": [], "missing": [], "where": WHERE_TO_FIND}
    if program_end is None:
        out["missing"] = ["program_end"]
        return out
    for s in backward_plan(program_end, RULES, dso):
        out["steps"].append({
            "label": s.label, "earliest": s.earliest.isoformat(), "latest": s.latest.isoformat(),
            "conservative_latest": s.conservative_latest and s.conservative_latest.isoformat(),
            "open_inputs": list(s.open_inputs),
            "cites": [{"id": c, "description": RULES[c].description, "quote": RULES[c].quote,
                       "source_url": RULES[c].source_url, "verified_on": RULES[c].verified_on.isoformat()} for c in s.cites],
        })
    contested = RULES["opt_file_after_end"].contested
    out["contested"] = {"value": contested.value, "in_force": RULES["opt_file_after_end"].value,
                        "status": contested.status, "status_url": contested.status_url}
    out["missing"] = [r for r in OPT_ROLES if r in out["steps"][0]["open_inputs"]] if out["steps"] else []
    return out


def _d(d: date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def _field(role: str, entries: list, exact: dict) -> dict | None:
    """What the screen shows for one input: a value to confirm, or choices that block until picked."""
    entries = [e for e in entries if e.parsed.note != "no date in span"]  # "graduation" alone must not clear a typed date
    if not entries:
        return None
    if role in exact:
        return {"value": exact[role].isoformat(), "from": entries[0].span}
    vals = sorted({e.parsed.value for e in entries if e.parsed.status == "exact"})
    if len(vals) > 1:
        return {"choices": [v.isoformat() for v in vals], "note": "Two different dates were given. Pick the one on your I-20."}
    for e in entries:
        if e.parsed.status == "ambiguous":
            return {"choices": [c.isoformat() for c in e.parsed.candidates], "note": f'"{e.span}" can be read two ways. Which one?'}
        if e.parsed.status == "partial" and e.parsed.candidates:
            first, last = e.parsed.candidates
            return {"note": f'"{e.span}" means somewhere between {_d(first)} and {_d(last)}. Enter the exact date.'}
        if e.parsed.status in ("partial", "missing"):
            return {"note": f'"{e.span}": {e.parsed.note or "not an exact date"}. Enter the exact date.'}
    return None


def ask(question: str, known: dict[str, date], ip: str = "local") -> dict:
    """known: dates already in the fields; a date in the question replaces them."""
    r = route(question, any(known.values()))
    if r.route == "out_of_scope":
        return {"route": "out_of_scope", "reply": "optwise only answers post-completion OPT and STEM OPT timing "
                "questions from 8 CFR 214.2(f). It cannot predict approvals or give legal advice; please ask your DSO."}
    if not PER_IP.allow(ip):
        return _plan_only(r.route, known, RESTING.format(why="this connection asked a lot this hour; try again later"))
    if not BUDGET.open():
        return _plan_only(r.route, known, RESTING.format(why="this free demo's daily limit is reached; back tomorrow, UTC"))
    if not ASK_SLOTS.acquire(blocking=False):
        return _plan_only(r.route, known, RESTING.format(why="many people are asking right now; try again in a minute"))
    try:
        return _ask(question, known, r)
    finally:
        ASK_SLOTS.release()


def _plan_only(route_name: str, known: dict[str, date], note: str) -> dict:
    """The free path: no LLM, the plan from the fields. Every limit degrades to this, never to an error."""
    return {"route": route_name, "fields": {}, "note": note,
            "plan": plan_json(known.get("program_end"), known.get("dso_recommended")), "reply": None}


def _ask(question: str, known: dict[str, date], r) -> dict:
    fields, note, cost = {}, None, 0.0
    try:
        mentions, usage = llm_label(question)
        cost += usage.get("cost", 0)
        x = extract(question, mentions)
        exact = x.exact()
        fields = {role: _field(role, [e for e in x.inputs if e.role == role], exact) for role in ROLES}
        fields = {k: v for k, v in fields.items() if v}
        if x.unlabelled:
            note = f"Also saw {', '.join(x.unlabelled)}: enter it below if it is one of your dates."
    except llm.LLMUnavailable:
        exact, note = {}, "Could not read dates from your question; enter them below."

    exact = {**{k: v for k, v in known.items() if v and k not in fields}, **exact}
    plan = plan_json(exact.get("program_end"), exact.get("dso_recommended"))
    steps = backward_plan(exact["program_end"], RULES, exact.get("dso_recommended")) if "program_end" in exact else []
    ids = set(r.rule_ids) | {c for s in steps for c in s.cites}
    missing = plan["missing"] if r.route == "deadline" and "stem_file_before_ead_expiry" not in ids else []
    a = narrate(question, steps, {i: RULES[i] for i in sorted(ids)}, missing)
    BUDGET.add(cost + a.usage.get("cost", 0))
    return {"route": r.route, "fields": fields, "note": note, "plan": plan, "reply": a.reply}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj).encode())

    def _ip(self) -> str:
        # Behind a proxy every request comes from the proxy. Its appended entry is the rightmost one;
        # anything left of it is client-supplied and spoofable.
        fwd = self.headers.get("X-Forwarded-For") if TRUST_PROXY else None
        return fwd.split(",")[-1].strip() if fwd else self.client_address[0]

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, PAGE, "text/html; charset=utf-8")
        self._json(404, {"error": "not found"})

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if self.path == "/api/plan":
                return self._json(200, plan_json(_date(body.get("program_end")), _date(body.get("dso_recommended"))))
            if self.path == "/api/ask":
                q = str(body.get("question", "")).strip()
                if not q:
                    return self._json(400, {"error": "empty question"})
                return self._json(200, ask(q[:500], {r: _date(body.get(r)) for r in OPT_ROLES}, self._ip()))
            self._json(404, {"error": "not found"})
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"error": "bad input"})

    def log_message(self, fmt, *args):  # method + path + status only; never bodies (DESIGN #8)
        print(f"{self.command} {self.path} {args[1] if len(args) > 1 else ''}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"optwise on http://localhost:{port}")
    ThreadingHTTPServer(("", port), Handler).serve_forever()
