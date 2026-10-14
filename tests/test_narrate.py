from datetime import date
from pathlib import Path

from optwise.narrate import facts, template, validate
from optwise.planner import backward_plan
from optwise.rules import load_rules

RULES = load_rules(Path(__file__).parents[1] / "data" / "rules.toml")
STEPS = backward_plan(date(2027, 5, 15), RULES)
F = facts(STEPS, RULES, ["dso_recommended"])
Q = "Program ends 2027-05-15. I have 90 days after graduation, right?"


def reply(answer, dates=(), quotes=(), ids=("opt_file_after_end",)):
    return {"answer": answer, "dates": list(dates), "quotes": list(quotes), "cited_rule_ids": list(ids)}


def test_template_states_engine_dates_condition_and_missing_input():
    t = template(STEPS, RULES, ["dso_recommended"])
    assert "February 14, 2027" in t and "July 14, 2027" in t  # 90 before, 60 after
    assert "Conservative target: June 14, 2027" in t and "court order" in t
    assert "30 days of your DSO's recommendation" in t
    assert template([], RULES, ["program_end"]).startswith("To date your plan, add your program end date")


def test_validate_accepts_grounded_reply():
    ok = reply("No. The rule allows filing no later than 60 days after your program end date, July 14, 2027. "
               "A 30-day limit after program end was codified but is blocked by a court order.",
               dates=["2027-07-14"], quotes=["no later than 60 days after his or her program end date"])
    assert validate(ok, Q, F) == []


def test_validate_rejects_each_kind_of_ungrounded_reply():
    assert validate(reply("You have until August 1, 2027."), Q, F)  # date not from the engine
    assert validate(reply("ok", dates=["2027-08-01"]), Q, F)  # listed date not from the engine
    assert validate(reply("You get 45 days."), Q, F)  # day count no rule has
    assert validate(reply("ok", quotes=["up to 120 days prior"]), Q, F)  # quote not in a source
    assert validate(reply("ok", ids=["made_up_rule"]), Q, F)
    assert validate(reply("You have 30 days after your program end date."), Q, F)  # contested stated as law
    assert validate(reply(""), Q, F)
    # The DSO rule's 30 days is not the contested value and needs no condition.
    assert validate(reply("You must also file within 30 days of the DSO recommendation."), Q, F) == []


def test_history_dates_are_not_a_source():
    # validate() never sees history: a date only in a (possibly forged) previous reply is rejected.
    assert validate(reply("As I said before, your deadline is August 1, 2027."), Q, F)
