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
from datetime import date  # noqa: E402

from optwise import extract as ex  # noqa: E402
from optwise import llm  # noqa: E402
from optwise.narrate import CONDITION_WORDS, narrate  # noqa: E402
from optwise.planner import backward_plan  # noqa: E402
from optwise.rules import load_rules  # noqa: E402
from optwise.router import route  # noqa: E402

GOLD = Path(__file__).parent / "gold.jsonl"
RULES = load_rules(Path(__file__).parents[1] / "data" / "rules.toml")


def rate(passes: list[bool]) -> float:
    return sum(passes) / len(passes) if passes else float("nan")


def has_key() -> bool:
    try:
        return bool(llm.api_key())
    except llm.LLMUnavailable:
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
            tag = "DANGEROUS " if silent_wrong[-1] else ""
            misses.append(f"{tag}{g['id']} want {want} got {got} | {seen} | unlabelled {list(x.unlabelled)}: {g['question'][:60]}")
    ok_rows = [r for r in rows if r[1] is not None]
    cost = sum(r[2].get("cost", 0) for r in ok_rows)
    p50 = statistics.median(r[3] for r in rows)
    print(f"  extraction models={ex.MODELS} cost=${cost:.4f} for {len(rows)} calls, p50 latency {p50:.1f}s, "
          f"errors {len(rows) - len(ok_rows)}, spans not in question {sum(len(r[1].rejected) for r in ok_rows)}")
    metrics = [
        ("extraction: input dates correct", rate(correct), 0.95, True),
        ("extraction: confident wrong date (dangerous)", rate(silent_wrong), 0.0, False),
        ("extraction: missing/vague input left open, not guessed", rate(flagged), 1.0, True),
    ]
    return metrics, misses


def run_narration(gold: list[dict]) -> tuple[list, list[str]]:
    """Narration alone: gold inputs and gold rule ids in, so routing/extraction errors do not leak in."""
    def one(g):
        # Follow-ups: dates already in the fields (known), replaced by any the question states.
        inputs = {k: date.fromisoformat(v) for k, v in {**g.get("known", {}), **g["inputs"]}.items()}
        ids = set(g["expected_rule_ids"])
        steps = []
        if "program_end" in inputs and "opt_file_after_end" in ids:
            steps = backward_plan(inputs["program_end"], RULES, inputs.get("dso_recommended"))
            ids |= {c for s in steps for c in s.cites}
        t = time.time()
        a = narrate(g["question"], steps, {i: RULES[i] for i in sorted(ids)}, g["must_ask_for"])
        return g, a, time.time() - t

    with ThreadPoolExecutor(8) as pool:
        rows = list(pool.map(one, [g for g in gold if g["expected_route"] != "out_of_scope"]))
    shown = [a.reply is not None for _, a, _ in rows]
    unavailable = [any(r.startswith("unavailable") for r in a.rejected) for _, a, _ in rows]
    contested = [bool(CONDITION_WORDS.search(a.template + (a.reply or ""))) for g, a, _ in rows if g["must_mention_contested"]]
    cost = sum(a.usage.get("cost", 0) for _, a, _ in rows)
    retried = sum(a.usage.get("attempts", 1) > 1 for _, a, _ in rows)
    print(f"  narration models={rows[0][1].usage.get('model', '?')} cost=${cost:.4f} for {len(rows)} questions, "
          f"p50 latency {statistics.median(r[2] for r in rows):.1f}s, retried {retried}, unavailable {sum(unavailable)}")
    metrics = [
        ("narration: reply passed validators (else template only)", rate(shown), 0.80, True),
        ("narration: contested condition mentioned", rate(contested), 1.0, True),
    ]
    misses = [f"{g['id']} {a.rejected}: {g['question'][:60]}" for g, a, _ in rows if a.reply is None]
    return metrics, misses


def main(split: str = "dev") -> int:
    gold = [g for g in map(json.loads, GOLD.read_text().splitlines()) if g["split"] == split]
    results = [(g, route(g["question"], bool(g.get("known")))) for g in gold]

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
    extraction_misses, narration_misses = [], []
    if has_key():
        extraction_metrics, extraction_misses = run_extraction(gold)
        metrics += extraction_metrics
        narration_metrics, narration_misses = run_narration(gold)
        metrics += narration_metrics
    else:
        print("  extraction: skipped (no OPENROUTER_API_KEY; CI runs router gates only)")
    failed = 0
    for name, value, gate, higher in metrics:
        ok = value >= gate if higher else value <= gate
        failed += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {value:.0%} (gate {'>=' if higher else '<='} {gate:.0%})")
    print("  dates/quotes/ids/day counts in shown replies: enforced by validators (tests/test_narrate.py)")

    print("\nmisses:")
    for g, r in results:
        expected = set(g["expected_rule_ids"])
        if g["expected_route"] != r.route or not expected <= set(r.rule_ids):
            print(f"  {g['id']} want {g['expected_route']} {sorted(expected)} got {r.route} {sorted(r.rule_ids)}: {g['question'][:70]}")
    if extraction_misses:
        print("\nextraction misses:")
        print("\n".join(f"  {m}" for m in extraction_misses))
    if narration_misses:
        print("\nnarration: reply dropped, template only:")
        print("\n".join(f"  {m}" for m in narration_misses))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
