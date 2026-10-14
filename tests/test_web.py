from datetime import date

from optwise import web


def test_budget_closes_at_ceiling_and_reopens_next_day():
    b = web.Budget(daily_usd=0.01, weekly_usd=1)
    assert b.open()
    b.add(0.01)
    assert not b.open()
    b.day = date(2000, 1, 1)  # simulate the UTC day rolling over
    assert b.open()


def test_weekly_ceiling_binds_across_days():
    b = web.Budget(daily_usd=1, weekly_usd=0.01)
    b.add(0.01)
    b.day = date(2000, 1, 1)
    assert not b.open()


def test_limit_degrades_to_plan_without_llm(monkeypatch):
    monkeypatch.setattr(web, "BUDGET", web.Budget(daily_usd=0, weekly_usd=0))
    monkeypatch.setattr(web, "llm_label", lambda q: (_ for _ in ()).throw(AssertionError("LLM called")))
    out = web.ask("When is my OPT deadline?", {"program_end": date(2027, 5, 15), "dso_recommended": None})
    assert out["reply"] is None and "resting" in out["note"]
    assert out["plan"]["steps"][0]["latest"] == "2027-07-14"


def test_per_ip_limit_degrades_to_plan(monkeypatch):
    monkeypatch.setattr(web, "PER_IP", web.PerIP(per_hour=0))
    out = web.ask("When is my OPT deadline?", {"program_end": date(2027, 5, 15), "dso_recommended": None}, "1.2.3.4")
    assert out["reply"] is None and "this hour" in out["note"] and out["plan"]["steps"]


def test_suggestions_follow_plan_state():
    assert web.plan_json(None, None)["suggestions"] == web.STARTERS
    s = web.plan_json(date(2027, 5, 15), None)["suggestions"]
    assert s[0] == "What if my DSO recommends on Apr 15, 2027?" and "court order" in s[1]
    assert web.plan_json(date(2027, 5, 15), date(2027, 4, 20))["suggestions"][0] == "Why is my deadline May 20, 2027?"
