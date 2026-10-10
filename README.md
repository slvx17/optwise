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
- [ ] Verify rules from official sources (each needs a quote and `verified_on`)
- [ ] Gold eval set and metrics (citation correctness, refusal precision/recall)
- [ ] Retrieval over official sources (keyword first, measured)
- [ ] Router, validators and the LLM narrator (open models via OpenRouter)
- [ ] Web demo with rate limits and a spend ceiling
- [ ] Corpus refresh job with a human review gate

## Development

```bash
python -m pytest
```
