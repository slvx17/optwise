from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from optwise.planner import backward_plan
from optwise.rules import load_rules

FIXTURE = Path(__file__).parent / "fixtures" / "rules.toml"


def test_window_and_citations():
    (step,) = backward_plan(date(2027, 5, 15), load_rules(FIXTURE))
    assert step.earliest == date(2027, 2, 14)
    assert step.latest == date(2027, 7, 14)
    assert step.cites == ("opt_file_before_end", "opt_file_after_end")


def test_window_crosses_year_boundary():
    (step,) = backward_plan(date(2027, 1, 10), load_rules(FIXTURE))
    assert step.earliest == date(2026, 10, 12)


def test_rule_without_source_is_rejected(tmp_path):
    bad = tmp_path / "rules.toml"
    bad.write_text('[[rule]]\nid = "x"\ndescription = "d"\nvalue = 1\nunit = "days"\nverified_on = 2026-01-01\n')
    with pytest.raises(ValueError, match="source_url"):
        load_rules(bad)


def test_unloaded_rule_fails_loudly():
    with pytest.raises(KeyError):
        backward_plan(date(2027, 5, 15), {})


def test_shipped_rules_file_loads():
    load_rules(Path(__file__).parents[1] / "data" / "rules.toml")


def test_value_must_appear_in_quote(tmp_path):
    bad = tmp_path / "rules.toml"
    bad.write_text('[[rule]]\nid = "x"\ndescription = "d"\nvalue = 9\nunit = "days"\n'
                   'quote = "up to 90 days prior"\nsource_url = "u"\nverified_on = 2026-01-01\n')
    with pytest.raises(ValueError, match="not found in quote"):
        load_rules(bad)


def test_planner_rejects_unit_mismatch():
    rules = load_rules(FIXTURE)
    rules["opt_file_before_end"] = replace(rules["opt_file_before_end"], unit="months")
    with pytest.raises(ValueError, match="expects 'days'"):
        backward_plan(date(2027, 5, 15), rules)
