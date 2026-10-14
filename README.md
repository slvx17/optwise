# optwise

An OPT / STEM OPT planner that works backward from your graduation date, cites official sources, computes deadlines in plain code, and refuses to guess.

> **Status: early scaffold.** Nothing here is legal advice, and no rule in `data/rules.toml` is verified yet. Always confirm with your DSO.

## Why

International students get conflicting answers about OPT and STEM OPT timing from the DSO, forums and friends. A wrong deadline can cost someone their status. optwise answers "when must I have an offer, file, and prep?" from official sources only, and shows its work.

## How it works

```
question / dates
      |
   [router] --out of scope--> fixed refusal
      |
      +-- deadline / counting --> [rule engine] (plain code, rules are data)
      |
      +-- policy question ------> [retrieval] --> cited answer
      |
 [validators]: cited ids exist, quoted span exists, dates match the engine
      |
   plain-language answer (LLM narrates; it never calculates)
```

Design decisions and the reasoning behind them: [docs/DESIGN.md](docs/DESIGN.md).

## Flows (v1: post-completion OPT and STEM OPT)

1. **Planner** - give a program end date, get a dated backward plan (offer-by, file-by, DSO-by).
2. **Ask** - cited Q&A over official sources.
3. **Report checklist** - what to report, to whom, and by when.

## What it will not do

- Predict whether an application will be approved.
- Give legal advice or interpret your individual case.
- Answer from sources that are not official (no forums).
- Store anything about you. It is stateless, with no accounts.

## Roadmap

- [x] Rule schema, loader and backward planner with tests
- [x] Verify rules from official sources (5 rules from 8 CFR 214.2(f), pinned; contested 30-day limit recorded)
- [x] Gold eval set, per-stage metrics and release gates (`python evals/run.py`)
- [x] Keyword router (route + rule ids), measured against the gates
- [x] Input extraction (LLM labels roles, code parses dates), measured: 98% correct, 0 confident wrong dates
- [x] LLM narrator: code template always, LLM reply only if validators pass, retry transient only (dev 100% / test 94% replies shown)
- [ ] Retrieval over pinned 8 CFR 214.2(f) paragraphs for policy questions (keyword first, recall@k on the gold set)
- [x] Web app: free-text ask box, editable date fields, plan from code (no LLM), validated reply
- [ ] Public demo guards: per-IP rate limit, input cap, max output tokens, daily spend ceiling, key server-side
- [ ] Deploy (free tier) and freshness check for new eCFR versions
- [ ] Results write-up: metrics per stage, cost per run, what failed

## Development

```bash
python -m pytest
python evals/run.py        # dev split; `test` is held out, run it rarely
PYTHONPATH=src python3 -m optwise.web   # http://localhost:8000
```
