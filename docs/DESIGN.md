# Design decisions

1. **The LLM is a router and narrator, never a calculator.**
   Dates and counts come from code: same input gives the same output, it is unit-testable and auditable, and it costs no tokens or latency. Anything that produces an actionable real-world deadline must be tested against hard code, not covered by prompt instructions.

2. **Rules are data.**
   Each rule in `data/rules.toml` carries `id, description, value, unit, quote, source_url, verified_on`. The loader rejects a rule whose value is not in its quote. Values live in data; shapes (anchor date, direction, how rules combine) live in code, because values change more often than shapes. The engine reads rules and every plan cites rule ids. Rules live in git, and a change is a reviewed PR showing the old and new source quote.

   **Source of truth is 8 CFR 214.2(f), pinned to a version.** DHS writes the regulation; USCIS, ICE/SEVP and schools only restate or apply it, so they are cross-checks and never cited. `source_url` is a point-in-time eCFR link (`/on/<date>/`), never `/current/`, so the quote cannot drift from the page. Codified text is not always the law in force: when they differ (e.g. a court injunction), the rule must also cite why. Example: the D/S final rule changed the post-completion filing limit from 60 to 30 days after program end in eCFR on 2026-09-15, but a nationwide preliminary injunction (D. Mass., 2026-09-14) blocked it, so 60 days stays in force.

3. **Retrieval starts with keywords.**
   The corpus is small. Add embeddings only if recall@k on the gold set shows misses caused by paraphrase or vocabulary mismatch, and try cheaper fixes first (query expansion, chunking).

4. **Guardrails are enforced, not just prompted.**
   Out-of-scope questions go to a router step with a fixed refusal. Validators reject an answer if a cited id is not in the retrieved set, if the quoted span is not in the cited passage, or if a date differs from the engine's output.

5. **Models are config.**
   The OpenRouter model id is configuration. The eval harness runs the same gold set across several open models and the README reports accuracy, refusal correctness and cost. Escalate a single step to a closed model only if its metric falls below a stated threshold.

6. **Eval before UI.**
   Gold set and engine tests come first. CI fails on regression. Keep a held-out split so prompts are not overfit to the eval.

   Gold set: `evals/gold.jsonl` (60 examples, every third held out as `test`), written synthetically from paraphrased real phrasing (forums, school FAQs; no usernames, no copied posts), deliberately messy: typos, vague dates, false premises, multi-part, adversarial. Labels name the expected route, rule ids, inputs and what must be asked; expected dates are not stored, the engine computes them, and a test cross-checks hand labels against the engine. Each metric runs per example, belongs to one stage, and has a release gate:

   | Stage | Metric | Gate |
   |---|---|---|
   | Router | out-of-scope recall / false-refusal rate | >= 95% / <= 5% |
   | Router | expected rule ids retrieved | >= 90% |
   | Extraction | input dates correct | >= 95% |
   | Narration | dates in answer equal engine output | 100% |
   | Narration | contested condition mentioned / contested value stated as law | 100% / 0 |
   | Narration | cited quote exists in its source | 100% |
   | Narration | asks for a missing input instead of inventing it | 100% |

   **No LLM judge (for now).** The narrator returns structured output (dates, cited rule ids, quotes, contested note, asked-for inputs, then free `text`), so every metric above is checked in code: free, exact and repeatable at the budget of $0.10 or less per run. Schema compliance is itself a metric (malformed output = fail). Wording quality (no advice tone, readable) is reviewed by a human on a fixed sample per release, against a short rubric, with verdicts recorded so it is a tracked number rather than an impression. A disclaimer labels advice-like wording but does not excuse it. Add an LLM judge only when review volume outgrows one person, and validate it against the human verdicts first.

7. **Corpus freshness has a human gate.**
   Watch two signals: the eCFR versions API for 8 CFR 214.2 (structured, and the cheapest way to see an amendment) and SEVP announcements (where status changes such as injunctions show up). A change in either opens a review (diff report plus a proposed rule edit). It never writes a rule. Until reviewed, rules are unchanged and the UI shows a staleness notice.

8. **Stateless.**
   Dates are sent per request, nothing is stored, and request bodies are not logged. Send the provider only what is needed.

9. **A public demo is a cost surface.**
   Per-IP rate limit, input length cap, max output tokens, a global daily spend ceiling, and the API key server-side only.

10. **Facts and conditions are shown apart; uncertainty is never guessed away.**
    A plan shows the legal limit in force first. A contested rule (`[rule.contested]`) adds a second, labelled line ("conservative target: day 30, the limit if the injunction is lifted"), stating the condition rather than advising. Every date, including the conservative one, is computed in code; the LLM only phrases it. A missing input (e.g. the DSO recommendation date) is reported in `open_inputs` and shown as a relative rule ("within 30 days of your DSO's recommendation"), never filled with a guess; a what-if editor may offer a default only if it is the earliest plausible date and labelled as an assumption. Since we store nothing, change reaches returning users by pull: each rule shows when it last changed. Assumption to test: students learn of rule changes from school broadcasts and come back. If returns are low, add an `.ics` export with a recheck reminder (still stateless) before anything that stores contact details.

11. **Extraction: the model reads, code decides, and when neither can, ask.**
    The LLM only labels date mentions with a role (`program_end`, `dso_recommended`, `ead_expiry`, `other`) and a verbatim span. Code parses the span. A span not in the question is dropped, so no date can be invented. A span code cannot pin to one day stays open: `05/06/2027` is ambiguous (both readings are shown), "may 20" lacks a year, "summer 2027" becomes a range computed in code, and two dates for one role are a conflict. None of these is guessed. A regex pass flags dates the LLM did not label. The student confirms every extracted date, shown with its role, before a plan is computed. For a vague date we point them to where the true value lives (I-20, page 1, "Program End Date") rather than infer it.

    Errors are not equal, so the gates split them: **input dates correct** (>= 95%; asking when we did not need to is a safe miss), **confident wrong date** (0; a wrong value or a wrong role, e.g. a degree-conferral date taken as program end) and **missing or vague input left open** (100%). Dev split, first runs (41 questions):

    | Model | Correct | Confident wrong | Left open | Errors | Cost / 41 | p50 |
    |---|---|---|---|---|---|---|
    | deepseek/deepseek-v4.1-flash | 98% | 0% | 100% | 1 (empty response) | $0.0084 | 1.5 s |
    | openai/gpt-oss-20b | 78% | 5% (2 role swaps) | 93% | 7 | $0.0010 | 2.6 s |

12. **Narration: the LLM can only add, never break.**
    A code template always states the plan (dates, conservative target with its condition, what input is missing and where to find it). The LLM adds a reply only for what a template cannot do: correct a false premise, answer each part, explain why. The reply is structured (`answer, cited_rule_ids, quotes, dates`) and code validators drop it if it cites an unknown rule, quotes text not in a source, states a date or day count that is in neither the facts nor the question, or mentions the contested value without its condition. A dropped reply is not retried (at temperature 0 it would fail again); the student gets the template. Only transient failures (HTTP 429/5xx, network, empty or non-JSON content) are retried, once. Models are an ordered list in config (`OPTWISE_NARRATOR_MODELS`), run with one model until evals show its reply failing too often, because every model in the list must pass the promotion gate: all release gates on dev and test, no regression on dangerous metrics. Pin exact versions, never `~...-latest` aliases. If every model fails, or OpenRouter is down, the template is the answer.

    First runs (DeepSeek v4.1 flash): validators dropped 8 of 33 dev replies. 5 were real: the model computed end + 60 when the DSO limit binds earlier, completed "may 20" with a year, picked a reading of `05/06/2027`, and computed 150 - 80 unemployment days. 3 were validators too strict (numbers the student or the source wrote, echoed back). After fixing those and stating the 5 in the prompt: dev 100% shown, held-out test 94% (one reply restated "Dec 20" with a year). About $0.0003 and 2 s per reply. Seen once in four dev runs: one confident wrong extraction date, not reproduced; the confirmation step is the guard. q047 ("will I get approved?") gets an empty extraction response on both attempts, so it is not transient; the form is the fallback.

13. **Plan screen: free text first, date fields always there, confirmation inline.**
    The primary entry is one free-text box with example chips (what a recruiter tries first). Extraction fills date fields shown right under it; the fields are also typed into directly, so the screen works with no LLM (outage, or a question the model returns nothing for). The plan is computed at once from the fields, which sit above it as "Based on (edit any)"; editing a field recomputes in code with no LLM call. Only inputs code cannot pin block the plan: an ambiguous date shows its readings as buttons, a partial date shows its range and where the exact one lives. A blocking confirm step was rejected: students learn to click through it, and calculation is free. Visual priority goes to the latest filing date in force with how far today is from it; the opening date, the conservative target (with its condition) and the undated DSO limit sit below, because mistaking one of them for the deadline is the costly misread. Dates are kept in the browser (localStorage) only; on return the plan is recomputed with current rules and a notice shows if the rules changed since the last visit.
