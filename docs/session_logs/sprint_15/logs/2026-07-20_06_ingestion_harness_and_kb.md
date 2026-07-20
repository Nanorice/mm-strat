# Session Handover: 2026-07-20 (session 06)

## 🎯 Goal
Before re-running GLW, understand what harness keeps the *other* producer nodes
consistent — then close the loop: measure the post-fix structured rate, persist
`quote_verified`, document the layer, and take the knowledge base one step past a
single company toward the industry-study end state the user is aiming at.

## ✅ Accomplished

**The node-harness question, answered: there is none, because the originals can't fail.**
- The original analysts (market/news/fundamentals, researchers, risk) are **free
  text** — `chain.invoke → result.content`, no schema, no validator. "Consistent"
  means "always returns a string." That is a category difference from the business
  analyst, not an infrastructure gap.
- The structured harness is one shared function (`agents/utils/structured.py`):
  two attempts, then a **silent** drop to free text. Five nodes use it identically;
  the business analyst is just the only one whose schema is large enough for the
  fallback to be load-bearing.
- Everything else labelled "retry" is at the wrong layer: `llm_max_retries` is SDK
  transport, `recursion_limit` is loop-runaway, the SQLite checkpointer is
  crash-resume (a fallback is a *successful* node, so a resume preserves the
  degraded output — it never re-runs to recover a lost profile).
- **The real gap:** no degradation signal at all. Structured nodes emit `null`
  (inferable); free-text nodes emit `""` (invisible — `write_report_tree` omits an
  empty section, so a run that lost three analysts looks identical to a clean one).

**Producer: `degraded_agents` in the manifest** (`aa627e1`, pushed to `mm-strat-report`)
- `find_degraded_agents` walks all 13 sections, returns `{agent: "empty"|"unstructured"}`,
  derived in `write_report_tree` (the one place that reads every report key) and
  keyed to `report.json`'s names so a consumer can join. Sidecar schema 1.0 → 1.1
  (additive; mm-strat's gate compares major only). +7 tests, `620 passed`.

**GLW re-run — clean, and it exposed the first real fabrication**
- 9 relations (the count that failed deterministically pre-fix), `degraded_agents: {}`,
  ingested, parent replaced / both children kept.
- Fidelity 90.3% on three flags. **Two were checker bugs of one family** (sliced
  text loses block boundaries: `core rate.To offset`, `including: •The loss`) —
  `normalize()` now strips whitespace + list glyphs outright. GLW 90.3 → 96.8%,
  MRVL/RKLB unchanged. **The third flag is a true positive:** the model grafted
  *"...to achieve our goals, through 2026 and beyond."* — every word in the filing,
  the sentence not. First fabrication the checker has caught; negative control added.

**`research_relations` — `quote_verified` is finally persisted** (`3e1fc1e`)
- `src/research_comprehension.py`, per KB-schema §2.1. One row per relation per run,
  append-only, idempotent on `run_id`. `force=True` re-scores (a checker fix is the
  one reason). `quote_verified` is **NULL not False** when the filing isn't cached.
  Real DB: 5 runs → 22 relations, all verified. `supply_chain_edges` deliberately
  NOT built (needs `n_runs_total > 1`).

**`thesis` fixed + backfilled** (`ffd1fd8`)
- Mapped `research_manager.recommendation` (a rating), so `thesis == conviction` on
  every row — two agents *appearing* to agree was one field printed twice. Now
  `portfolio_manager.investment_thesis` (prose). Added `force=True` to
  `ingest_run_dir`/`ingest_drop_dir` (the run_id gate blocks a plain re-ingest);
  all three live rows backfilled.

**Corroboration harness run — 3 names × 3 runs** (`ffd1fd8` + live DB)
- `scripts/run_corroboration.py`. 6 new producer runs, $0.60, all clean.
- **Post-fix structured rate: 8/9 (89%), and the one miss is GLW** — a new GLW run
  fell back to free text. Exactly `business-analyst-schema-surface`: 9 relations,
  fails more often than smaller schemas. First time seen as a *rate*.
- **GLW extraction is bimodal** (perfect 9/9 or nothing); **MRVL is high-variance**
  (2/4/6 relations across 3 runs); **RKLB has a stable core** (4 counterparties in
  all 3).

**Docs**
- `docs/modules/research_layer.md` (`ae4ca3d`) — the layer's passport; answers "why
  no LLM here" (producer already emitted validated Pydantic) and "where one belongs"
  (dst_ticker resolution, fallback recovery). Indexed from the methodology.
- `plans/industry_study_direction.md` (`ffd1fd8`) — analysis of the user's SpaceX
  supply-chain report as the target state. Eleven structural gaps; see Context.

## 📝 Files Changed

**Producer (`mm-strat-report`)** — `aa627e1`, pushed:
- `tradingagents/reporting.py`: `find_degraded_agents`, schema 1.1.
- `tests/test_reporting.py`: +7 tests.

**mm-strat:**
- `src/research_comprehension.py`: **new** — the observation log + fidelity roll-up.
- `src/research_report_engine.py`: `thesis` → `investment_thesis`; `force=` on ingest.
- `src/research_quote_fidelity.py`: `_LAYOUT` fold in `normalize()`.
- `scripts/run_corroboration.py`: **new** — n runs vs the same filing + agreement report.
- `scripts/dashboard_utils.py`: strip one trailing heading per section (stranded `## II.`).
- `tests/`: `test_research_comprehension.py` (**new**), + `report_sections`, `quote_fidelity`,
  `report_engine` regressions.
- `docs/modules/research_layer.md`, `plans/industry_study_direction.md`: **new**.

**DB (live):** `research_reports` thesis backfilled; `research_report_runs` 5 → 11;
`research_relations` **new**, 29 relations across 8 runs.

## 🚧 Work in Progress (CRITICAL)

- **`counterparty_key` is too weak — corroboration proved it, fix verified but NOT applied.**
  RKLB logged `"Space Development Agency"` (2/3) and `"Space Development Agency (SDA)"`
  (1/3) as **different** counterparties; same for NRO. The key strips legal suffixes
  but not a trailing `(...)`. Confirmed a one-line strip (`re.sub(r'\s*\([^)]*\)\s*$','')`)
  collapses both. **After applying, `comprehend_runs(force=True)` to rewrite the keys.**
  Until then RKLB's agreement table undercounts.
- **GLW's grafted quote is in the DB, ungated.** It's a `watch_item`, and
  `research_relations` logs *relation* evidence only. No table persists non-relation
  claims, so the one fabrication we've found is unverified in prod.
- **`__unnamed_customer__` merges distinct parties.** MRVL's two separate unnamed
  10% customers share one key (`ponytail:` marker in `research_comprehension.py`).

## ⏭️ Next Steps (triaged)

**P0 — do first**
1. **Apply the `counterparty_key` parenthetical strip** + `comprehend_runs(force=True)`.
   One line, verified, unblocks a trustworthy agreement table. Reprint corroboration.
2. **`supply_chain_edges`** — now unblocked (`n_runs_total > 1` exists). A `GROUP BY`
   projection over `research_relations`, PK `(src_ticker, counterparty_key, direction)`.
   **Must follow #1** or it bakes the SDA/NRO split into the graph. Build it
   **segment-grained**, not company-grained (industry-study §2.3 — RKLB is competitor
   *and* supplier on different lines).

**P1 — the layer's missing plumbing**
3. **`research_claims`** — persist non-relation evidence (watch items, risks, moat) with
   `quote_verified`, so the GLW graft is gated. ~40 lines, same shape as `research_relations`.
4. **`research_report_sections`** at ingest — the producer already writes 13 standalone
   `.md`; persisting them deletes `split_report_sections` + 12 tests (net negative diff).
5. **`ingest_reports` / `comprehend_reports` orchestrator phases** — `phase_registry.py`
   has zero research entries; both run only when a human calls them.
6. **R2 transport** — sync the **EDGAR cache** with the reports (or the gate silently
   stops gating) and upload `manifest.json` **last**.

**P2 — depends on breadth / later**
7. **Materiality is a cross-company join** (industry-study §2.1): counterparty-side
   revenue share lives in the *counterparty's* filing → prioritise **breadth of names**
   over depth. But a producer run is **~15 min** (measured this session), so 10 names ×
   n=3 ≈ 7.5h — batch overnight, not interactively.
8. `dst_ticker` resolution (the real LLM job); node-type schema (`input`/`technology_route`,
   foreign-listed as resolved-not-US); direction-distribution DQ check; consume
   `degraded_agents`; `__unnamed_customer__` split; `raw_md` retention window.

**P3 / separate**
9. `NVDA_20260714_135243` un-ingestable (no manifest) — re-run or delete.
10. `test_backtest_matches_prod_predictions` failing — pre-existing, unrelated to research,
    smells like `promotion-orphans-daily-predictions`.

## 💡 Context/Memory

- **The industry-study end state needs eleven things the schema can't express.** The
  user's SpaceX report (`plans/industry_study_direction.md`) is the target *content*.
  The load-bearing gaps: (a) **materiality points the wrong way** — we have "% of the
  subject's revenue", the thesis needs "% of the *counterparty's* revenue", which is a
  join across two filings, not a field; (b) **one company is several counterparties**
  (RKLB competitor + supplier), so edges must be segment-grained; (c) **absence is a
  finding** — insourced layers and reasoned exclusions (OSS: ruggedised ≠ rad-hard)
  have no representation; (d) **bottlenecks carry arithmetic** (the MOCVD capacity gap
  revises a probability); (e) **the levered names aren't US-listed**. The hard problem
  the direction contains: extending past EDGAR (contract announcements, trade press)
  means the verification gate needs a **second design** — a news article is not immutable.
- **A single run is not a reliable extraction.** MRVL gave 2/4/6 relations from identical
  input. This retroactively justifies the whole append-only + corroboration-counted design;
  a confidence number on n=1 would have been fiction.
- **Diagnose fidelity divergence, don't report it.** Three checker false negatives now
  (trailing stop, quote-style swap, lost block boundary) and one true positive. Rule:
  bisect the longest matching prefix; a *layout* difference at the divergence point is the
  checker's bug, a *different continuation* is the model's. Updated in
  `quote-fidelity-false-negatives` memory.
- **The dashboard splitter is a symptom.** It splits a concatenated blob only because
  ingestion persists `complete_report.md` and not the per-agent files the producer already
  wrote (#4 above deletes it).
