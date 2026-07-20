# Session Handover: 2026-07-20 (session 03)

## 🎯 Goal
Implement steps 1–2 of the report-ingestion build order (`research_reports` landing table +
engine, and the quote-fidelity checker), then run the pipeline for MRVL/GLW/NOK — which
surfaced that the business analyst's typed output was being silently discarded.

## ✅ Accomplished

**Step 1 — `research_report_engine.py`** (engine shape, per `edgar_engine.py`)
- Two tables. `research_reports` PK `(ticker, report_date, source)` stays the one-row-per-day
  human-readable record; `research_report_runs` keyed on `run_id` keeps *every* run so
  corroboration (step 4) has raw material. This was the "child table" decision, taken over
  adding `run_id` to the PK.
- `report_date` from `manifest.trade_date`, never the folder's wall-clock stamp.
- Idempotent by `run_id`: re-running the drop dir returns `(0, n)`.
- Version gate: absent `schema_version` → baseline `1.0`; major mismatch → `SchemaVersionError`
  naming both versions.

**Step 2 — `research_quote_fidelity.py`** (ported from the TradingAgents prototype)
- Pure functions, no DB and no network. Both hard-won details kept: edge-punctuation stripping
  (the 8.7pp false-negative) and the negative controls.
- `quote_verified` per claim, not a summary number.
- **RKLB reproduces the known figure exactly: 100.0% (23/23).**

**Ran the pipeline: MRVL + GLW ingested, NOK rejected pre-flight**
- NOK is a 20-F foreign private issuer, no 10-K under CIK 924613 — the ARM case from
  `verdicts/edgar_section_slicing_proofread.md`. Caught *before* spending; nothing burned.
- MRVL $0.133 / GLW $0.087. Both landed, both `conviction` populated.
- Both new sidecars carry `schema_version: "1.0"` (producer-side change landed between the
  RKLB run and these), so the version gate ran against live data for the first time.

**Found and fixed two producer bugs that were discarding typed profiles** (TradingAgents repo)
- Both MRVL and GLW ingested with `business_analyst: null` — the fidelity gate had nothing to
  score. Root-caused by replaying the single node against the cached filing (~1 LLM call).
- **Bug 1 — one bad relation destroyed the whole profile.** `Relation._check_identifiable`
  rejects a relation with neither counterparty nor `pct_revenue`; pydantic then fails the entire
  `BusinessProfile` on that one list element, the node drops to free text, and every other
  relation, field and verified quote goes with it. Deterministic on GLW (`relations.9` in the
  batch run, `relations.0` on replay). Fixed with a `mode="before"` filter on
  `BusinessProfile.relations`. GLW now yields **9 relations** where it produced zero.
- **Bug 2 — a transient miss was never retried.** MRVL replayed clean (5 relations); its batch
  failure was a blip. But `invoke_structured_or_freetext` conceded after one attempt — the log
  read "retrying once as free text", and that is literally what it did. Now two structured
  attempts before falling back; the extra call only happens on the failure path.
- TradingAgents suite after both: **613 passed, 2 skipped** (skips unrelated — no `langchain_aws`,
  no `DEEPSEEK_API_KEY`).

## 📝 Files Changed

**mm-strat** — all five already committed as `2bb82b6`
*"feat(research): report ingestion engine + quote fidelity checker"* (824 insertions), committed
from a parallel window mid-session; ancestor of HEAD, nothing outstanding.
- `config.py`: `TRADINGAGENTS_HOME` / `RESEARCH_REPORTS_DIR` / `EDGAR_CACHE_DIR`, env-overridable.
- `src/research_report_engine.py`: **new** — the ingest engine.
- `src/research_quote_fidelity.py`: **new** — the fidelity checker.
- `tests/test_research_report_engine.py`: **new** — 13 tests (PK, idempotency, version gate,
  null-vs-absent, same-day re-run).
- `tests/test_research_quote_fidelity.py`: **new** — 9 tests incl. the three negative controls.
- **DB (live, `data/market_data.duckdb`)**: created `research_reports` + `research_report_runs`;
  3 rows (RKLB 07-19, MRVL 07-20, GLW 07-20). Additive; both tables drop cleanly.

**TradingAgents** (separate checkout, **uncommitted**)
- `tradingagents/agents/schemas.py`: `BusinessProfile._drop_uninformative` validator.
- `tradingagents/agents/utils/structured.py`: two structured attempts before free-text fallback.

## 🚧 Work in Progress (CRITICAL)

- **MRVL and GLW rows are stored unscoreable.** They hold `business_analyst: null` from the
  *pre-fix* runs. Re-running both (~$0.22) would land typed profiles and real fidelity numbers —
  and exercises the replace-parent-keep-both-children path. Not done; deliberately not spent unasked.
- **The two TradingAgents fixes are uncommitted.** That tree was already dirty on arrival
  (`reporting.py`, `cli/*`, several tests — someone else's in-flight work), so the fixes were left
  alongside rather than bundled into it. They are verified but not landed.
- **`pytest tests/` is NOT green in mm-strat** — 8 failures + 26 errors, all **pre-existing**
  (verified by stashing this session's only tracked edit and reproducing identically). Two causes:
  a temp-file fixture handing DuckDB a zero-byte file on Windows (26 errors, `test_phase1_backfill`
  + `test_feature_pipeline`), and `CatalogException` in `test_cone_cells_render` (5). Spawned as a
  separate task. The 22 new tests all pass.
- **The payload-version split is implemented but inert.** The engine reads an optional
  `report.json["agent_schema_versions"]` and rejects per-agent major mismatches, but the producer
  does not emit that key yet. A renamed `BusinessProfile` field is still invisible until it does.
- **Two windows were committing to this repo concurrently.** `2bb82b6` (this session's src) and
  `be944c2` / `aac88a4` landed from a parallel session while this one ran. Nothing was lost, but
  a `git status` taken mid-session is not a reliable picture of what is outstanding — re-check
  before assuming a file is uncommitted.

## ⏭️ Next Steps

1. **Commit the two TradingAgents fixes** (coordinate with whoever owns that dirty tree), then
   **re-run MRVL + GLW** and confirm both score. This is the gate for step 3.
2. **Measure the real structured-output success rate post-fix** — 3–4 more names. The old 1-in-3
   was two bugs, not model quality; the post-fix number is unknown and step 3 rests on it.
3. **Decide how TradingAgents work is tracked** (see Context) — it is now a load-bearing upstream
   with no session-log presence.
4. Emit `agent_schema_versions` producer-side so the payload gate stops being inert.
5. Only then: step 3 (`research_signals` + `comprehend_reports` phase).

## 💡 Context/Memory

- **The spec was wrong about the ground truth, in two places.** The design doc and the
  next-session prompt both assert `report.json`/`manifest.json` carry `schema_version: "1.0"`.
  The RKLB run on disk carried neither — the producer constant was added in *uncommitted* code
  after that run. Verify artifacts against disk before building a gate on a documented field.
- **`NVDA_20260714_135243` has no sidecars at all** (no `report.json` *and* no `manifest.json`).
  The spec covers a missing `report.json` but sources `report_date` from `manifest.trade_date`
  with an explicit never-use-the-folder-stamp rule, so that run is un-ingestable by design.
  Decided: skip loudly rather than fall back to the folder stamp.
- **The design doc's `thesis` mapping looks wrong.** It maps `thesis` ←
  `research_manager.recommendation`, so `thesis` now stores `"Underweight"` — identical to
  `conviction`, and not a thesis. `portfolio_manager.investment_thesis` is almost certainly
  intended. Implemented per spec (instruction was not to re-derive the schema); one-line fix.
- **"Extraction varies run to run" is worse than the doc records.** The doc notes 14 vs 7
  relations. The real variance was whether a typed profile appeared *at all* — and the cause was
  not the model. Replaying one node against a cached filing costs ~1 LLM call and is the cheapest
  diagnostic available; use it before assuming model quality.
- **Cross-machine transport is a non-question now.** `market_data.duckdb` (88 GB) and the agent
  drop dir are both on `sh019`. The design doc's premise ("the DB lives with the research box")
  is stale. Engine takes the drop root as a config-defaulted param, so a synced folder later
  needs no code change.
- **Tracking TradingAgents work — the open problem.** This session changed behaviour in a second
  repo with no session log, no sprint, and a permanently dirty tree, and those changes are what
  make this repo's verification gate work at all. mm-strat's docs currently have no place to
  record "we changed the producer". Left as Next Step 3 rather than invented unilaterally.
