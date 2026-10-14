# The LLM can only add: evals and guardrails for a deadline tool

International students on F-1 visas get one chance to file for OPT, the work authorization after graduation. The filing window is set by regulation (8 CFR 214.2(f)): no earlier than 90 days before the program end date, no later than 60 days after it, and within 30 days of the school official's recommendation, whichever comes first. A late application is denied. Students piece the answer together from forums, friends and a busy international office.

[optwise](https://github.com/slvx17/optwise) answers "when do I file?" from the regulation, shows its sources, and does not guess. This post is about the part that took most of the work: making an LLM useful in a domain where a confident wrong answer can cost someone their status, and measuring whether it is.

## The design rule: the model reads and explains, code decides

```
question ──> router (keywords + context) ──> out of scope: fixed refusal
   │
   ├─> extraction: LLM labels which text is which date; CODE parses it
   │
   ├─> planner: CODE computes every date from rules stored as data
   │
   └─> narrator: CODE template always shown; LLM reply added only if validators pass
```

Every date a student sees is computed in plain code from rules stored as data, each rule carrying an exact quote from a pinned version of the regulation. The LLM does two narrow jobs: it reads messy questions ("graduating may 2027 whens the last day i can aply??") and it explains the plan in words. It never produces a date that reaches the student unchecked.

## Four layers of guardrails

**1. A deterministic floor.** The plan and a code-written template are always shown. The LLM's reply sits on top and is optional. If OpenRouter is down, the model returns nothing, or a spend limit trips, the student still gets the full plan. I tested the outage path with an invalid key: same plan, no reply, no error.

**2. The model reads, code decides.** Extraction asks the LLM only for `{role, verbatim span}`. Code parses the span. A span that is not in the question is dropped, so a date cannot be invented. A span that code cannot pin to one day stays open: `05/06/2027` (May 6 or 5 June? half the users are international) comes back as two buttons; "may 20" without a year is not completed; "summer 2027" becomes a range and a pointer to where the exact date lives (the I-20, page 1).

**3. Validators on every reply.** The reply is structured output (`answer, cited_rule_ids, quotes, dates`) and code drops it if it cites an unknown rule, quotes text not in the source, states a date or day count that appears in neither the engine's facts nor the student's question, or mentions the blocked 30-day rule without saying it is blocked. A dropped reply is not retried (at temperature 0 it would fail again); only transient failures are. Follow-ups send the previous exchange for context, but that history is client-supplied and therefore untrusted: the validators never see it, so a date that exists only in a forged history is rejected.

**4. Cost guards that degrade instead of failing.** Only the ask path costs money (about $0.0004 per question). Spend is capped in real dollars at $1 a day and $5 a week, read from the provider's own counters so a free host restarting the process cannot reset them; per IP at 100 questions an hour (loose, because a lecture hall on campus wifi shares one IP); and at 8 in flight. Any tripped limit returns the plan without a reply.

## The evals

A gold set of 67 synthetic questions written from paraphrased real phrasing: typos, vague dates, false premises ("I have 90 days after graduation, right?"), multi-part questions, follow-ups, prompt injection. A third is held out and run rarely. Labels hold the expected route, rule ids, input dates and what must be asked for; expected deadlines are not stored, the engine computes them, and a test cross-checks the labels against the engine.

Each metric belongs to one stage and has a release gate, and narration is evaluated with gold inputs so upstream errors do not leak in. Everything is checked in code: no LLM judge, so a full run is exact, repeatable and costs about $0.02. Wording quality is the one thing left to a human review.

The most useful decision was **splitting errors by who gets hurt**. "Input dates correct" (gate 95%) lets the system ask when it did not need to; that costs the student a click. "Confident wrong date" (gate 0%) is the one that costs them their status: a real date in the wrong slot, stated with confidence. Without that split, two models that differ in safety look like they differ by a few points of accuracy.

| Stage | Metric | Gate | Dev | Held-out |
|---|---|---|---|---|
| Router | out-of-scope recall / false refusals | ≥95% / ≤5% | 100% / 0% | 100% / 0% |
| Extraction | input dates correct | ≥95% | 100% | 100% |
| Extraction | confident wrong date | 0% | 0% | 0% |
| Extraction | vague or missing input left open | 100% | 100% | 100% |
| Narration | reply passed validators | ≥80% | 95–100% | 100% |
| Narration | blocked rule mentioned with its condition | 100% | 100% | 100% |

## What the evals caught

**A cheaper model was more dangerous, not just less accurate.** gpt-oss-20b cost a tenth of DeepSeek v4.1 flash but had 5% confident wrong dates: it read "degree conferred 5/15/2027" as the program end date and filed "end 2027-12-18" under EAD expiry. DeepSeek: 0%. The headline accuracy gap (78% vs 98%) hid the real difference.

**The validators earned their place, and so did auditing them.** On the first run they dropped 8 of 33 replies. Five were real: the model computed program end + 60 when the recommendation limit bound earlier, completed "may 20" with a year, picked a reading of `05/06/2027`, and did 150 − 80 unemployment days. In each case the student would still have seen the correct template. Three were my validators being too strict: rejecting numbers the student had written ("not 90, but 150"). A guardrail that blocks good answers has a cost too, and you only see it if you read the rejections.

**A dangerous error that appeared once in four runs.** One run showed a single confident wrong date that I could not reproduce. I tagged dangerous misses in the eval output, and a later run named it: on "What's my OPT deadline (end 2027-12-18) and will I get approved?" the model sometimes labelled "end" as the EAD expiry. The fix was in code, not the prompt: an EAD-expiry label is accepted only when the question mentions the EAD, card, STEM or expiry. Otherwise the date is not used and the student is asked.

**Shortening the prompt broke a 100% gate.** Capping replies at 60 words made them readable and made the model drop the clause about the court order on 12% of contested questions. The gate caught it the same minute; the clause is now mandatory.

**The router failed follow-ups, not the LLM.** Six follow-up examples ("and the earliest?") showed the keyword router refusing questions about a plan already on screen. Extraction and narration handled them; the router lacked context. With dates present, an in-scope follow-up now routes to the plan. A question that points back at earlier text ("the second one you mentioned") stayed below the held-out gate until the previous exchange was sent, as untrusted context.

**The freshness check's first alarm was false.** A weekly job compares every rule's quote with the latest regulation text. Its first run flagged the 150-day unemployment rule as changed. It had not: eCFR's XML italicises the "2" in "(C)(2)", which breaks exact matching. Monitoring needs its own tests.

## What it does not do yet

- No LLM judge. Wording (no advice tone, readable) is a human review on a fixed sample. I would add a judge only when review volume outgrows one person, and validate it against the human verdicts first.
- One model in production. The client takes an ordered model list, but every model in it must pass every gate, so it runs with one.
- The gold set is 67 synthetic questions. Real questions will be messier, and since nothing is logged, the only route to them is students sending feedback.
- Policy questions are answered from the router's rule ids; retrieval over the full regulation text is next.

## Three things I would do again

1. **Put the deterministic path under the model, not beside it.** Then every failure (timeout, validator, spend cap) degrades to something correct instead of an error.
2. **Name the error that hurts people and give it its own gate at zero.** Accuracy averages away the failure you care about.
3. **Read the rejections.** Both kinds of guardrail mistake, letting bad answers through and blocking good ones, only show up there.
