import json
from datetime import date
from pathlib import Path

from optwise.planner import backward_plan
from optwise.rules import load_rules

ROOT = Path(__file__).parents[1]
GOLD = [json.loads(line) for line in (ROOT / "evals" / "gold.jsonl").read_text().splitlines()]
RULES = load_rules(ROOT / "data" / "rules.toml")
ROUTES = {"deadline", "policy", "out_of_scope"}


def test_labels_are_well_formed():
    assert len({g["id"] for g in GOLD}) == len(GOLD)
    for g in GOLD:
        assert g["split"] in {"dev", "test"}, g["id"]
        assert g["expected_route"] in ROUTES, g["id"]
        assert set(g["expected_rule_ids"]) <= RULES.keys(), g["id"]
        if g["expected_route"] == "out_of_scope":
            assert not g["expected_rule_ids"] and not g["must_mention_contested"], g["id"]


def test_contested_label_matches_engine():
    # Hand labels drift; where the engine can decide, it decides.
    for g in GOLD:
        inputs = g["inputs"]
        if g["expected_route"] != "deadline" or "program_end" not in inputs or "opt_file_after_end" not in g["expected_rule_ids"]:
            continue
        dso = inputs.get("dso_recommended")
        (step,) = backward_plan(date.fromisoformat(inputs["program_end"]), RULES, dso and date.fromisoformat(dso))
        assert g["must_mention_contested"] == (step.conservative_latest is not None), g["id"]
