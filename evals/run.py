"""Run the gold set through the built stages and compare each metric with its gate (DESIGN #6).

Usage: python evals/run.py [dev|test]   (default dev; look at test rarely, it is the held-out split)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from optwise.router import route  # noqa: E402

GOLD = Path(__file__).parent / "gold.jsonl"


def rate(passes: list[bool]) -> float:
    return sum(passes) / len(passes) if passes else float("nan")


def main(split: str = "dev") -> int:
    gold = [g for g in map(json.loads, GOLD.read_text().splitlines()) if g["split"] == split]
    results = [(g, route(g["question"])) for g in gold]

    oos = [r.route == "out_of_scope" for g, r in results if g["expected_route"] == "out_of_scope"]
    false_refusal = [r.route == "out_of_scope" for g, r in results if g["expected_route"] != "out_of_scope"]
    in_scope = [(g, r) for g, r in results if g["expected_route"] != "out_of_scope"]
    route_ok = [g["expected_route"] == r.route for g, r in in_scope]
    rules_ok = [set(g["expected_rule_ids"]) <= set(r.rule_ids) for g, r in in_scope]

    metrics = [  # name, value, gate, higher is better
        ("router: out-of-scope recall", rate(oos), 0.95, True),
        ("router: false-refusal rate", rate(false_refusal), 0.05, False),
        ("router: deadline/policy route accuracy", rate(route_ok), 0.90, True),
        ("router: expected rule ids retrieved", rate(rules_ok), 0.90, True),
    ]
    print(f"split={split} n={len(gold)}")
    failed = 0
    for name, value, gate, higher in metrics:
        ok = value >= gate if higher else value <= gate
        failed += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {value:.0%} (gate {'>=' if higher else '<='} {gate:.0%})")
    print("  not built yet: extraction, narration (dates, quotes, contested, missing input)")

    print("\nmisses:")
    for g, r in results:
        expected = set(g["expected_rule_ids"])
        if g["expected_route"] != r.route or not expected <= set(r.rule_ids):
            print(f"  {g['id']} want {g['expected_route']} {sorted(expected)} got {r.route} {sorted(r.rule_ids)}: {g['question'][:70]}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
