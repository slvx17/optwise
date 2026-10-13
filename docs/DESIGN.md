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

7. **Corpus freshness has a human gate.**
   Watch two signals: the eCFR versions API for 8 CFR 214.2 (structured, and the cheapest way to see an amendment) and SEVP announcements (where status changes such as injunctions show up). A change in either opens a review (diff report plus a proposed rule edit). It never writes a rule. Until reviewed, rules are unchanged and the UI shows a staleness notice.

8. **Stateless.**
   Dates are sent per request, nothing is stored, and request bodies are not logged. Send the provider only what is needed.

9. **A public demo is a cost surface.**
   Per-IP rate limit, input length cap, max output tokens, a global daily spend ceiling, and the API key server-side only.

10. **Facts and conditions are shown apart; uncertainty is never guessed away.**
    A plan shows the legal limit in force first. A contested rule (`[rule.contested]`) adds a second, labelled line ("conservative target: day 30, the limit if the injunction is lifted"), stating the condition rather than advising. Every date, including the conservative one, is computed in code; the LLM only phrases it. A missing input (e.g. the DSO recommendation date) is reported in `open_inputs` and shown as a relative rule ("within 30 days of your DSO's recommendation"), never filled with a guess; a what-if editor may offer a default only if it is the earliest plausible date and labelled as an assumption. Since we store nothing, change reaches returning users by pull: each rule shows when it last changed. Assumption to test: students learn of rule changes from school broadcasts and come back. If returns are low, add an `.ics` export with a recheck reminder (still stateless) before anything that stores contact details.
