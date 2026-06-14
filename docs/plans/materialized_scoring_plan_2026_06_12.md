# Plan: Materialized Model Scoring for the Dashboard (2026-06-12)

## Problem

The remote dashboard tries to score tickers live (loads the model file in the
request path) → `FileNotFoundError` on the Streamlit Cloud host. Scores should
be computed once in the daily pipeline, materialized to `daily_predictions`, and
read read-only by the dashboard (local and remote).

## Root-cause analysis (3 structural flaws)

1. **Phase ordering** (`daily_pipeline_orchestrator.py:277-300`): the slim DB is
   built (Phase 7.5) and uploaded to R2 (7.6) *before* predictions are written
   (Phase 8). The synced DB is structurally always one day stale. This is the
   core of "model output not available in dashboard".
2. **Cohort gap**: only the breakout cohort (`v_d3_deployment`,
   `breakout_ok=TRUE`) is scored nightly. The pre-breakout cohort
   (`trend_ok=TRUE AND breakout_ok=FALSE`) is never scored nightly, so
   `render_pre_breakout` scores live.
3. **Live-scoring coupling**: the dashboard imports model-loading code
   (`load_prod_model`, `score_features_df`, `xgb`) that should not run on a
   read-only serving host.

## Decisions (confirmed with user)

- **Audit trail**: keep ALL `model_version_id` rows in `daily_predictions`
  (no wipe on model switch). Dashboard filters to current prod version. This
  preserves cross-model score history per ticker.
- **Pre-breakout**: score & materialize nightly (both cohorts written under the
  prod `model_version_id`). Dashboard reads both via SQL join. No model file
  needed on the serving host.

---

## Phase A — Fix pipeline scoring (local correctness)  [STATUS: DONE ✅]

- **A1. Reorder phases** ✅: prediction logging moved out of Phase 8 into a new
  Phase 7.4 (`_run_phase_7_4_scoring`), running BEFORE 7.5 (build) and 7.6
  (upload). New order:
  `Phase 7 (cache) → 7.4 (score) → 7.5 (build slim DB) → 7.6 (upload R2) → 8 (monitoring)`.
- **A2. Score both cohorts** ✅: `_log_prod_model_predictions` now loops over
  `('breakout', v_d3_deployment)` and `('pre_breakout', v_d3_prebreakout)`,
  refactored into `_fetch_breakout_candidates` / `_fetch_pre_breakout_candidates`
  / `_score_and_log_cohort`. `cohort` column added to `daily_predictions`.
- **A3. Idempotency** ✅: `cohort` folded into the composite PK; re-running a
  date overwrites both cohorts (INSERT OR REPLACE). Legacy rows backfilled to
  `'breakout'` via `_migrate_add_cohort` (rename → recreate → copy → drop).

### Key finding during A2 (structural, not a band-aid)
The pre-breakout cohort could NOT be scored from raw `t3_sepa_features` — that
table lacks the model's **fundamental features** (`revenue_growth_yoy`, `roe`,
`pe_ratio`, …) and **delta features** (`rs_delta`, `natr_delta`, `*_delta`).
Those are added downstream by `v_d2_features` (fundamentals as-of join) and
`v_d1_candidates` (delta renames from `*_pct_chg`) — but only for breakout
*entries*. Fix: new view **`v_d3_prebreakout`** in `view_manager.py` that
hydrates the pre-breakout cohort with the IDENTICAL feature contract
(deltas + fundamentals + price ratios), windowed to 252d like `v_d3_deployment`.
One model feature list scores both cohorts.

### Bug fixed in passing
`_migrate_add_cohort` originally read `PRAGMA table_info` column **0** (the cid),
not **1** (the name) — the cohort-present check was always false, so the rebuild
would re-fire on every call. Corrected to index 1.

### Verification (real DB, 2026-06-11)
`_log_prod_model_predictions('2026-06-11')` → 25 breakout + 394 pre-breakout =
419 rows, each ranked 1..N within cohort, no feature mismatch. Migration
preserved all 109 legacy rows (→ `'breakout'`). Tests: 19 passed
(prediction_logger + calibration), incl. new cohort coexistence / invalid-cohort
/ legacy-migration cases.

### Files touched (Phase A)
- `scripts/migrations/2026_06_12_add_cohort_to_daily_predictions.sql` (new)
- `src/evaluation/prediction_logger.py` (cohort param, PK, idempotent rebuild)
- `src/orchestrators/daily_pipeline_orchestrator.py` (Phase 7.4 + cohort scoring)
- `src/managers/view_manager.py` (new `v_d3_prebreakout` view)
- `tests/test_prediction_logger.py` (3 new tests)

### NOTE for Phase B/C
- `v_d3_prebreakout` is registered in `ViewManager.create_all()` but was created
  ad-hoc on the live DB for testing. A full `create_all()` run (or the next
  Phase 6) will formally (re)create it — confirm it persists.
- `build_dashboard_db.py` does NOT yet materialize `v_d3_prebreakout`. Phase C
  must decide whether the dashboard reads pre-breakout scores purely from
  `daily_predictions` (cohort='pre_breakout') — likely YES, so NO manifest change
  needed (daily_predictions is already a full copy). The dashboard's
  `load_pre_breakout` join may still need the feature columns for display, though.

## Phase B — Decouple the dashboard from the model  [STATUS: DONE ✅]

- **B1** ✅: new `load_scored_pre_breakout(model_version_id, limit)` — reads
  `v_d3_prebreakout` LEFT JOIN `daily_predictions` (cohort='pre_breakout', latest
  scored date). `render_pre_breakout` now takes pre-scored data (no live call).
- **B2** ✅: deleted `load_prod_model`, `score_features_df`, `score_active_trades`,
  and the orphaned `load_pre_breakout` / `load_deployment_features`. Removed
  `json` / `numpy` / `xgboost` imports from `dashboard_utils.py` and `os` /
  `_DB_PATH` from `dashboard.py`. No model-loading code left in the dashboard.
- **B3** ✅: removed the `st.write` / `st.warning` debug output in
  `dashboard_utils.py` and the `st.caption("DB: …")` banner in `dashboard.py`.

### Shared translator (the real reconciliation)
`load_scored_watchlist` returned `prob_class_*` / `predicted_class`, but the
renderers read `p_<label>` / `m01_class`. That mismatch meant the watchlist
scores were silently NOT rendering (the `if "m01_class" in columns` branch never
fired) — a latent bug from the handover's watchlist "fix". Added
`_attach_class_labels()` in `dashboard_utils.py` that maps prob/predicted →
`p_<label>` / `m01_class` / `m01_class_id`, applied in BOTH scored loaders. Now
the materialized scores conform to the exact contract the renderers expect — one
translator, both cohorts, zero live scoring.

### Verification
- `py_compile` clean on both files; grep confirms no live-scoring symbols remain
  (only a comment reference).
- Pre-breakout loader SQL on real DB: 100 rows, all scored, ranked by P(Home Run),
  with company_name + days_in_setup populated.
- `_attach_class_labels` unit-exercised: emits `p_<label>`, `m01_class`,
  `m01_class_id`, and `P_HR_COL` present for sorting.
- Tests: 11 prediction_logger pass.

### Files touched (Phase B)
- `scripts/dashboard_utils.py` (new loader + translator; deletions; debug removed)
- `scripts/dashboard.py` (use new loader; import cleanup; debug removed)

## Phase C — Sync completeness  [STATUS: DONE ✅]

### Audit result (dashboard read-set vs slim-DB manifest)
Every table the dashboard + the 4 multipage files read is in the MANIFEST,
EXCEPT the new `v_d3_prebreakout` view → **added to the manifest** as a
`materialize_view` entry. `daily_predictions` is a full copy, so both cohorts
ride along automatically (no manifest change there).

- **C1** ✅: `v_d3_prebreakout` added to `build_dashboard_db.py` MANIFEST.
  Verified build: materializes 72,943 rows; `daily_predictions` carries both
  cohorts (109 breakout + 394 pre_breakout).
- **C2** ✅: the **Model Lab page reads model-card files from disk**
  (`model_cards/*.html` + the artifact dirs). DB-only sync left those absent on
  cloud. Fix (user-approved): `sync_dashboard_db.py` now also uploads
  `model_cards/*.{html,json}` (~709 KB) to `latest/model_cards/`, and
  `dashboard_utils._ensure_model_cards()` pulls them on cloud boot (best-effort,
  degrades gracefully). Large model artifact dirs (plots) are NOT synced — the
  Model Lab degrades gracefully (`_resolve_artifacts_dir` → None → warning).
- **C3** ✅: ordering fix from A1 means 7.4 (score) → 7.5 (build) → 7.6 (upload)
  carries today's scores automatically. No new sync machinery for scores.

### Refactor (DRY)
`_ensure_local_db` and the new `_ensure_model_cards` shared boto3 client setup →
extracted `_on_cloud()` + `_r2_client()` helpers in `dashboard_utils.py`. The
sync script's `upload` / `upload_model_cards` share one client too.

### Verification
- Sync dry-run lists both targets: 782 MB DB + 15 card files (709 KB).
- Slim `dashboard.duckdb` rebuilt (781 MB): pre-breakout loader returns 394
  scored rows reading the materialized view-as-table; both cohorts in
  `daily_predictions`; NO model file touched.
- `py_compile` clean on all Phase C files; 11 prediction_logger tests pass.

### Files touched (Phase C)
- `scripts/build_dashboard_db.py` (manifest += v_d3_prebreakout)
- `scripts/sync_dashboard_db.py` (model_cards upload)
- `scripts/dashboard_utils.py` (_ensure_model_cards + _on_cloud/_r2_client refactor)

## Phase D — Post-deploy fixes (2026-06-13, after first remote run)  [STATUS: DONE ✅]

Five issues surfaced on the live remote dashboard:

1. **Watchlist crash** (`StreamlitAPIException`: 383,810 cells > 262,144 Styler
   limit) — ROOT CAUSE: the "ACTIVE" status branch did `display = scored.copy()`
   but `scored` is the FULL watchlist (38,392 rows, all statuses) — the status
   filter was never applied. Fixed: filter `scored` by `status` in every branch.
   Also added a 2,000-row pre-style cap (protects EXITED/All views). Also fixed a
   latent `NameError`: `render_analytics(scored, watchlist)` referenced an
   undefined `watchlist` in `page_today` → now `render_analytics(scored, scored)`.
2. **Dataset EDA** / **5. Pipeline Health** — needed `docs/reports/` (52 MB) and
   `data/audit_reports/` (0.3 MB). Both already guard with `.exists()` → were
   showing clean warnings, not crashing. Fixed by syncing the dirs.
3. **Model Lab** — model artifact plots not on cloud + registry `artifacts_path`
   is often a Windows-absolute dev-box path. Fixed: sync `models/` plot/report
   files (PNG/HTML/CSV/TXT — NOT model.json), and `_resolve_artifacts_dir`
   re-anchors any path to ROOT from its first `models/` segment.
4. **Backtest Studio** — hard-crashed: `BACKTEST_DIR.iterdir()` raises when the
   dir is absent. Fixed with an `.exists()` guard returning an empty frame (the
   page already handles empty → warning). `data/backtest/` (112 MB, WIP) is
   intentionally NOT synced yet — sync after local-space cleanup.

### Generalized asset sync (the structural fix)
Replaced the cards-specific upload with a declarative `ASSET_DIRS` list in
`sync_dashboard_db.py` (local_dir, r2_prefix, allowed_suffixes) + a mirror
`_ASSET_DIRS` + `_ensure_asset_dirs()` pull-on-boot in `dashboard_utils.py`.
Adding a dir to sync is now a one-line config change. Suffix allow-lists keep
`model.json` (weights) and raw data off R2. Dry-run total ~886 MB (DB 790 +
docs_reports 52.5 + model_artifacts 42.7 + cards 0.7 + audit 0.3) — within the
10 GB free tier.

### Files touched (Phase D)
- `scripts/dashboard.py` (watchlist status filter, row cap, analytics arg fix)
- `scripts/sync_dashboard_db.py` (ASSET_DIRS + generic upload_asset_dir)
- `scripts/dashboard_utils.py` (_ensure_asset_dirs generic pull)
- `scripts/pages/3_Model_Lab.py` (_resolve_artifacts_dir re-anchor)
- `scripts/pages/4_Backtest_Studio.py` (.exists() guard)

### Redeploy steps
1. `python scripts/build_dashboard_db.py` (already has v_d3_prebreakout)
2. `python scripts/sync_dashboard_db.py` (ships DB + 4 asset dirs)
3. Cloud app re-pulls on next cold start (23h freshness gate per dir).

## Outstanding (not blocking — for the next session)
- **Merge `infra_uplift` → `main`** (handover item — unchanged by this work).
- **S4 Task Scheduler runbook** for the nightly job (handover item).
- **Verify from phone** end-to-end once R2 has the new DB + cards.
- A clean `ViewManager.create_all()` will (re)create `v_d3_prebreakout` formally;
  it was created ad-hoc on the live DB during A2 testing. Confirm it survives the
  next Phase 6 view refresh.

## Verification

- Run pipeline for one date locally; assert `daily_predictions` has both cohorts
  for that date under prod `model_version_id`.
- Open dashboard locally against `dashboard.duckdb` with the model dir RENAMED —
  confirm watchlist + pre-breakout both render scores with no model file.
- Confirm `build_dashboard_db.py` output carries the fresh scores.

## Files touched

- `scripts/migrations/2026_06_12_add_cohort_to_daily_predictions.sql` (new)
- `src/evaluation/prediction_logger.py` (cohort param + PK)
- `src/orchestrators/daily_pipeline_orchestrator.py` (reorder + generalize scoring)
- `scripts/dashboard_utils.py` (new loader; delete live-scoring)
- `scripts/dashboard.py` (use new loader; remove debug)
- `scripts/build_dashboard_db.py` (no change expected — full copy already covers it)
