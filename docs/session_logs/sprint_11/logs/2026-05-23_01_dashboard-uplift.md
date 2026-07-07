# Session Handover: 2026-05-23

## 🎯 Goal
Land the multi-page Streamlit dashboard MVP — corrected design plan first, then
infra fixes (pretrain HTML rendering, backtest manifest schema), then build
Pages 1 / 3 / 4 / 5 against the existing DuckDB tables and registered models.

## ✅ Accomplished
- **Plan review + correction.** Audited
  `docs/plans/dashboard_implementation_plan_2026_05_23.md` against actual repo
  state. Five factual errors fixed (HTML path, 5F-already-wired,
  manifest_version filter, audit-history single-point, missing model artifacts).
  Page 3 pivoted to static-HTML iframe; Page 3's promote-to-prod removed
  (CLI-only); diff tab demoted to placeholder.
- **Pretrain HTML rendering proven.** Ran `scripts/run_pretrain_audit.py
  --mode trades` → produced `docs/reports/pretrain_audit_trades_20260523_005407.html`
  (5.2 MB, 35,673 rows, 187 features, quality=PASS). Confirms the
  "render static HTML offline, iframe in Streamlit" approach.
- **Backtest manifest schema v1.** Enriched `_build_manifest` in
  `src/backtest/runner.py` with `manifest_version: "v1"` + `model: {name,
  version_id, path}` block. Added `_lookup_model_version_id` that queries the
  registry by `artifacts_path` and falls back to `<name>/<version-dir>` (the
  v1 directory isn't registered yet). Wired `--model` through case1/case2
  scripts. Re-ran both — case1 +201% / case2 +65% reproduced identically.
- **Page 1 (Today).** Replaced legacy single-page layout. New components:
  - 5F regime card next to M03 card (target_exposure → band label, worst
    factor, weighted z, expander with all z-scores).
  - Default sort = Entry Date desc (latest first). P(HR)-sorted available
    behind selectbox.
  - Pre-breakout cohort table — `trend_ok=TRUE AND breakout_ok=FALSE` joined
    to t3 features and live-scored by prod M01.
  - Sector heat with 1d / 5d / 20d window selector, y-axis floor=150,
    `cliponaxis=False` so top labels stop being clipped.
  - Analytics: trade-age bar replaced with days_held × pct_return scatter
    (4 quadrants: Hot / Mature / Young / Aging) + expander listing tickers
    filterable by quadrant.
  - Sector concentration: single color, no gradient.
  - Filters wrapped in `st.form` — typing in the search box no longer
    retriggers a whole-page rerun (which was retriggering live M01 scoring).
- **Page 3 (Model Lab).** Registry list with status/feature-version filters
  → 6 tabs per model: Overview, Pretrain Report (HTML iframe), Plots (PNG),
  Report (MD), Specs (JSON), Diff (placeholder + CLI hint). Read-only — no
  promote/archive UI.
- **Page 4 (Backtest Studio).** Filters `data/backtest/*/manifest.json` to
  `manifest_version == "v1"` only — stale runs invisible. Per run: equity
  curve, drawdown chart, per-year breakdown, per-regime breakdown, trade
  table (outcome / sector / exit_reason filters), 2-run compare overlay.
- **Page 5 (Pipeline Health).** Runs heatmap (last 30d, status × phase × date,
  hover with runtime/error), data freshness table with tolerance bands per
  table, universe + breakout trend (60d), audit history (renders single
  point with "history accumulating" badge), storage sizes.
- **`scripts/dashboard_utils.py` created.** Centralized loaders + constants:
  `load_regime`, `load_risk_5f`, `load_watchlist`, `load_deployment_features`,
  `load_pipeline_status`, `load_pipeline_runs_window`, `load_data_freshness`,
  `load_universe_trend`, `load_pre_breakout`, `load_sector_heat(window_days)`,
  `load_models_table`, `load_prod_model`, `score_features_df`,
  `EXPOSURE_BANDS`, `CLASS_LABELS`, `classify_regime`, `exposure_band_label`.
- **Live smoke test.** Streamlit booted on 127.0.0.1:8765, all four pages
  imported under a mock harness without runtime errors. Killed cleanly.

## 📝 Files Changed
- `docs/plans/dashboard_implementation_plan_2026_05_23.md` — revised header,
  build-philosophy (static-HTML for graph-heavy pages), §1.3 inventory, §3
  fully rewritten (3.1 dashboard_snapshot deferred but documented; 3.2 done;
  3.3 already wired; 3.4 audit-write hook proposed), Pages 3/4/5 updated,
  build sequence re-ordered (Model Lab ahead of Pipeline Health), Open
  Questions updated.
- `src/backtest/runner.py` — added `model_path` / `model_version_id` to
  `__init__`, `_derive_model_name`, `_lookup_model_version_id`, enriched
  `_build_manifest` with `manifest_version` + `model` block.
- `scripts/run_case1_prototype_standalone.py` — passes `model_path=args.model`
  to runner.
- `scripts/run_case2_prototype_plus_rank.py` — same.
- `data/backtest/case1_prototype_standalone/manifest.json` — regenerated.
- `data/backtest/case2_prototype_plus_rank/manifest.json` — regenerated.
- `scripts/dashboard.py` — full rewrite as Page 1 (Today) + navigation entry.
- `scripts/dashboard_utils.py` — NEW; shared loaders + constants.
- `scripts/pages/3_Model_Lab.py` — NEW.
- `scripts/pages/4_Backtest_Studio.py` — NEW.
- `scripts/pages/5_Pipeline_Health.py` — NEW.
- `docs/reports/pretrain_audit_trades_20260523_005407.html` — NEW (5.2 MB).
- `docs/manual_for_me.md` — Dashboard section rewritten.

## 🚧 Work in Progress (CRITICAL)
- **No live browser eyeball test.** The pages imported under a mock and
  Streamlit booted, but I never opened the URL in a real browser. The
  user/Hang's UI feedback (covered in this session for Page 1 specifically)
  was the first real exercise. Pages 3 / 4 / 5 have NOT been visually
  inspected end-to-end.
- **`dashboard_snapshot` table NOT built.** Page 1's pre-breakout cohort
  runs `predict_proba` live on every load (~50 tickers). The plan documents
  this as the snapshot table's job; user explicitly deferred ("MVP, worry
  about data later"). If load time becomes painful, this is the lever.
- **Audit-write hook NOT added** to the daily orchestrator. Page 5 will
  keep showing the single 2026-03-28 audit point until somebody invokes
  `tools/run_all_audits.py` again. Deferred by user.
- **Pretrain HTML is NOT version-pinned to models.** Page 3's "Pretrain
  Report (HTML)" tab shows the most-recent `docs/reports/pretrain_audit_*.html`
  by mtime, regardless of which model the user selected. Badged in the UI
  as "Not version-pinned" — see plan Open Q #5.
- **Page 3 Plots tab is mostly empty.** Only the prod model
  (`m01_prototype_2003_2026_20260514_233125` → `models/m01_prototype_2003_2026/v2/`)
  has populated `evaluation/` PNGs. All older registry rows point at empty
  `models/artifacts/<version_id>/` directories. The page renders a "no
  artifacts" warning for those — by design, not a bug.

## ⏭️ Next Steps
1. **Open the URL in a browser** and walk through Pages 3 / 4 / 5. Apply
   the same UX critique pass the user did for Page 1.
2. **Build Page 2 (Ticker Deep Dive)** — explicitly skipped in this session
   per user scoping. The spec is in
   `docs/plans/dashboard_implementation_plan_2026_05_23.md` §Page 2:
   diagnostic matrix (C1-C9 / B1-B2), score trajectory, fundamentals +
   earnings snapshot, per-ticker trade history. Extends the existing
   `1_Feature_Time_Series.py`.
3. **Wire daily audit-write** if Page 5's audit-history chart becomes
   anything you'd act on. Phase-9 hook in
   `src/orchestrators/daily_pipeline_orchestrator.py` calling
   `tools/run_all_audits.py`.
4. **Version-pin pretrain HTML** — change the pretrain audit CLI to write
   to `docs/reports/pretrain_<version_id>.html` and store the path on the
   registry row, so Page 3 stops showing the wrong report when the user
   selects an older model.

## 💡 Context/Memory
- **Streamlit reruns are whole-page, not component-local.** Page 1's search
  box felt laggy because every keystroke triggered a full rerun, which
  included `predict_proba` on the pre-breakout cohort. Fix was to wrap the
  filter controls in `st.form` so the rerun only fires on Apply / Enter.
  This pattern applies anywhere a filter sits above an expensive widget.
- **Manifest schema versioning.** Page 4 filters on `manifest_version == "v1"`
  rather than maintaining a registry of "real" runs. Stale on-disk runs
  (`baseline`, `prototype_test_1`, `20260214_174034`, etc.) keep existing
  but stay invisible to the UI. This is the cleanest way to draw a line
  between current-pipeline output and archive.
- **`load_sector_heat(window_days=N)` uses `ORDER BY date DESC LIMIT N`**
  on the distinct-dates CTE, NOT `INTERVAL N DAY`. The interval approach
  counts calendar days (including weekends), so `INTERVAL 1 DAY` returns
  TWO trading days when MAX(date) is a Monday. LIMIT-N gives exactly N
  trading days.
- **Registry `artifacts_path` is heterogeneous.** Most rows point at empty
  `models/artifacts/<version_id>/` directories; only the latest prod model
  (`...20260514_233125`) points at the populated `models/m01_prototype_2003_2026/v2/`.
  Page 3's plot tab handles both shapes by searching `<artifacts_path>/evaluation/`
  first then falling back to `<artifacts_path>/` directly.
- **5F mirrored constants.** `EXPOSURE_BANDS` is duplicated between
  `src/pipeline/risk_5_factor.py` and `scripts/dashboard_utils.py` rather
  than imported. Reason: avoiding a `src.*` import chain inside Streamlit's
  hot reload path. If the bands change, update both.
- **The `score_features_df` helper now lives in `dashboard_utils.py`.**
  Page 1 (active trades + pre-breakout) and Page 2 (when built) both use
  it. The legacy `score_active_trades` function in `dashboard.py` is a thin
  watchlist-shaped wrapper around it.
