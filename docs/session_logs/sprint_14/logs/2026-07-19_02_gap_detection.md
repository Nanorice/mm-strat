# Session Handover: 2026-07-19 (session 02 — sh019 gap detection + commit sweep)

## 🎯 Goal
Review the sh019 catch-up items, work out which of them the pipeline *should* have
detected itself, build the missing detectors, and commit the carried-over work sitting
uncommitted in the tree from earlier sessions.

## ✅ Accomplished

### 1. Exploration — corrected the catch-up list
Traced every sh019 item against code before touching anything. Two of the four items in
the handover's list turned out to be **wrong**:

- **`create_duckdb_views.py` is redundant** on a box whose pipeline runs. It's a 3-line
  wrapper over `ViewManager.create_all()`, which Phase 6 runs nightly, and
  `_create_screener_watchlist_view` carries a self-migration (`BASE TABLE` → drop →
  VIEW). Proven on a synthetic pre-merge DB: table→view, `cooldown_end` gone, idempotent
  on the second call.
- **`backfill_sepa_watchlist.py` IS still required** — but for the *source table*, which
  nothing self-heals. Phase 4b only appends today's events.

Classified the rest: code pull + backups are correctly manual (self-updating code is a
footgun; a backup driven by the process it protects dies with it), and
`clean_dirty_shares_price.py` is a deliberate detect/remediate split (corrupt LOWs were
kept on purpose as real flash crashes).

### 2. Four detectors built for the layers that had none
The user's post-tier-0 steer ("the pipeline should DETECT gaps") was **half-built**: T1
price, T2 and T3 each got a detector; macro, watchlist history and model-promotion state
never did — and those are exactly the three that bit sh019.

| Gap | Fix | Phase |
|---|---|---|
| Stale prod model scoring silently | `_check_prod_model_identity()` | 8 |
| Watchlist history never re-examined | `_check_watchlist_status_vocab()` | 4b |
| t1_macro interior holes permanent | `_heal_t1_macro_gaps()` | 1 |
| No general gap detection | `tools/audit_date_coverage.py` | 8 battery |

Only #3 repairs; the rest detect only. Verified end-to-end on a **scratch copy** (main DB
never written): audit finds 5 holes → heal closes them → audit reports 0.

### 3. sh019 catch-up checklist
`plans/sh019_catchup_checklist.md` — measured target state, pre-flight verification
section, correct ordering, and the cone decision (§6).

### 4. Committed the carried-over work (3 commits)
Read every diff before staging — 11 files from other sessions were uncommitted:
- `9e3606b` gap detection (this session)
- `3a8700f` model-card static SVG (earlier session): Plotly→matplotlib SVG, killing a
  CDN dependency and JS-sizing clip inside the Streamlit iframe
- `db939b0` dashboard cone fan + `use_container_width`→`width='stretch'` migration

## 📝 Files Changed
- `src/orchestrators/daily_pipeline_orchestrator.py`: 3 detectors (+156 lines)
- `tools/audit_date_coverage.py`: NEW — interior-gap audit, tolerance 0
- `tools/run_all_audits.py`: registered the 6th audit (skip key `coverage`)
- `tests/test_{prod_model_identity_alert,watchlist_status_canary,t1_macro_gap_heal,audit_date_coverage}.py`: NEW, 21 tests
- `docs/modules/orchestrator.md`: 3 phase-table rows + a subsection each
- `docs/architecture/{comprehensive_methodology,manual_for_me}.md`: audit count 5→6
- `docs/session_logs/sprint_14/plans/sh019_catchup_checklist.md`: NEW
- (carried over) `src/evaluation/model_card/report.py`, `tools/rerender_model_cards.py`,
  `scripts/dashboard.py`, `scripts/pages/*`, `src/viz_library.py`

## 🚧 Work in Progress (CRITICAL)
**Nothing half-finished.** Tree is clean, suite **439 passed** (from a 406 baseline).
The `3 failed / 26 errors` are pre-existing and unchanged: stale EDGAR-placeholder stubs
(`NotImplementedError`) + a `test_phase1_backfill` tmpfile fixture bug ("not a valid
DuckDB database file"). Neither touches the orchestrator.

⚠️ **`tests/test_cone_cells_render.py` reads the LIVE cone cache**, so it will FAIL on
any box without sweep sources (sh019). That is expected, not a regression — see §6 of the
checklist. Noted in that commit's message.

⚠️ **Nothing has been run on sh019 yet.** The checklist is written but unexecuted.

## ⏭️ Next Steps
1. **Execute the sh019 checklist** (`plans/sh019_catchup_checklist.md`). Pre-flight
   first — if its `price_data` shows ~172 dates rather than ~9,184, STOP: that's a
   destroyed DB, not a stale one, and a different problem.
2. **Backup story** — weekly file-copy of `market_data.duckdb`, OS-scheduled and
   independent of Prefect. Still the biggest open ops risk.
3. Confirm the Streamlit Cloud app sets `DASHBOARD_PULL_FROM_R2=1`, or the remote
   silently stops refreshing.
4. Standing audit FAILs (t1_macro NULL vix row, 4 gap tickers) — pre-existing triage.

## 💡 Context/Memory

**Gap detection was incident-driven, not designed.** T2/T3 have detectors because T2/T3
had incidents. The asymmetry isn't architecture, it's sequence — and sh019 was already
the incident for the three uncovered layers. `audit_date_coverage.py` generalises it so
the *next* table to develop a hole is found by a check rather than by a human months later.

**Failure shaped like success is the recurring pattern here.** `backfill_t1_macro.py`
prints `[OK] Done … Rows written: 0` on a yfinance rate-limit. Phase 7.4 logged "no prod
model registered" at INFO and returned 0. Both look like healthy runs. That's why #3
heals from *local* data (no network → no silent no-op) and why #2 alerts rather than logs.

**Three bugs caught by tests before shipping**, worth recording because two were mine:
1. The identity alert first compared against "newest date scored by any *other* model" —
   one stale row would have alerted **every night forever**, training the user to ignore it.
2. The macro heal read `macro_data.value` for VIX, which is NULL — it would have written
   NULL `vix_close` over a *visible* gap. `macro_data` stores quotes in `close`, FRED
   series in `value`.
3. A stale "5 audits" count in the meta doc.

**Ordering on the watchlist backfill is load-bearing** (user caught this). It defaults
`end_date` to `MAX(t2.date)`, so on a stale box it rebuilds authoritatively (`DROP TABLE`)
only to that date; T3 then filters its universe from the truncated watchlist, and
`v_d1_candidates` INNER-JOINs entry rows → **trades silently vanish from the training
population**. `_t3_holed_dates` repairs only the trailing 30 days.

**Cones must NOT be rebuilt on sh019.** No orchestrator phase builds them; their inputs
(24 sweep summaries + a 3.3 GB score cache) are dev-box-local and not in git; and two
boxes rebuilding the honest-Sharpe gate from divergent sweep state is how you get two
answers to "did this champion pass?". `_cone_staleness` already treats a sourceless box
as INFO. **Implication**: the slim DB must keep being built on the research box, or the
remote loses its cones — if sh019 ever becomes the publisher, that's a deliberate call.

**Memory corrected**: `project_watchlist_merge` now records the views/backfill asymmetry
(the earlier "sh019 needs both" was half-wrong) plus the Phase-4b detector gap.
