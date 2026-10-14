"""Run the gold set through the built stages and compare each metric with its gate (DESIGN #6).

Usage: python evals/run.py [dev|test]   (default dev; look at test rarely, it is the held-out split)
"""
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from optwise import extract as ex  # noqa: E402
from optwise.router import route  # noqa: E402

GOLD = Path(__file__).parent / "gold.jsonl"


def rate(passes: list[bool]) -> float:
    return sum(passes) / len(passes) if passes else float("nan")


def has_key() -> bool:
    try:
        return bool(ex._api_key())
    except RuntimeError:
        return False


def run_extraction(gold: list[dict]) -> tuple[list, list[str]]:
    """Live LLM call per example. Returns (metrics, misses). Skipped without a key (CI has none)."""
    def one(g):
        t = time.time()
        try:
            mentions, usage = ex.llm_label(g["question"])
        except Exception as e:  # malformed output or HTTP error counts as a failed example
            return g, None, {"error": repr(e)[:80]}, time.time() - t
        return g, ex.extract(g["question"], mentions), usage, time.time() - t

    with ThreadPoolExecutor(8) as pool:
        rows = list(pool.map(one, gold))
    correct, silent_wrong, flagged, misses = [], [], [], []
    for g, x, usage, _ in rows:
        if x is None:
            correct.append(False); silent_wrong.append(False)
            misses.append(f"{g['id']} ERROR {usage['error']}")
            continue
        got = {k: v.isoformat() for k, v in x.exact().items()}
        want = g["inputs"]
        correct.append(got == want)
        # Dangerous: a date given with confidence that is not the true one (wrong value or wrong role).
        silent_wrong.append(any(want.get(role) != d for role, d in got.items()))
        flagged += [role not in got for role in g["must_ask_for"]]
        if got != want:
            seen = [(e.role, e.span, e.parsed.status) for e in x.inputs]
            misses.append(f"{g['id']} want {want} got {got} | {seen} | unlabelled {list(x.unlabelled)}: {g['question'][:60]}")
    ok_rows = [r for r in rows if r[1] is not None]
    cost = sum(r[2].get("cost", 0) for r in ok_rows)
    p50 = statistics.median(r[3] for r in rows)
    print(f"  extraction model={ex.MODEL} cost=${cost:.4f} for {len(rows)} calls, p50 latency {p50:.1f}s, "
          f"errors {len(rows) - len(ok_rows)}, spans not in question {sum(len(r[1].rejected) for r in ok_rows)}")
    metrics = [
        ("extraction: input dates correct", rate(correct), 0.95, True),
        ("extraction: confident wrong date (dangerous)", rate(silent_wrong), 0.0, False),
        ("extraction: missing/vague input left open, not guessed", rate(flagged), 1.0, True),
    ]
    return metrics, misses


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
    extraction_misses = []
    if has_key():
        extraction_metrics, extraction_misses = run_extraction(gold)
        metrics += extraction_metrics
    else:
        print("  extraction: skipped (no OPENROUTER_API_KEY; CI runs router gates only)")
    failed = 0
    for name, value, gate, higher in metrics:
        ok = value >= gate if higher else value <= gate
        failed += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {value:.0%} (gate {'>=' if higher else '<='} {gate:.0%})")
    print("  not built yet: narration (dates, quotes, contested, missing input)")

    print("\nmisses:")
    for g, r in results:
        expected = set(g["expected_rule_ids"])
        if g["expected_route"] != r.route or not expected <= set(r.rule_ids):
            print(f"  {g['id']} want {g['expected_route']} {sorted(expected)} got {r.route} {sorted(r.rule_ids)}: {g['question'][:70]}")
    if extraction_misses:
        print("\nextraction misses:")
        print("\n".join(f"  {m}" for m in extraction_misses))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
