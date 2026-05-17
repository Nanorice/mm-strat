# Session Handover: 2026-03-24

## 🎯 Goal
Complete Phase 3 of the feature table redesign: eliminate `daily_features`, migrate XS alphas + ranks to t2, rebuild t3 directly from t2 + price_data, and clean up all artifacts.

## ✅ Accomplished

- **Steps 3-5 complete** (continued from prior session):
  - `compute_all()` rewritten — calls `compute_t2_screener_features()` -> `compute_t3_features()` -> `_refresh_training_cache()`
  - Dead methods deleted: `_compute_full_rebuild`, `_compute_incremental`, `compute_base_features`, `compute_m03_features`, `compute_m03_derived`
  - Orchestrator collapsed from 9 to 8 phases: old Phase 5 (daily_features) + Phase 6 (t3 lazy copy) replaced by single Phase 5 calling `compute_t3_features()` directly
  - ViewManager: stale `MAX(date) FROM daily_features` reference fixed to `t3_sepa_features`

- **TS alpha warmup fix**: `compute_alpha_features()` gained `warmup_table` param. T3 TS alphas now load rolling history from `t2_screener_features` (continuous coverage), not t3 (sparse candidate dates). Prevents silent NULLs on rolling windows for tickers new to t3.

- **Checkpoint test PASSED**: `compute_t3_features('2024-01-16')` — 13 rows, all key cols non-null (`mom_21d`, `rsi_14`, `sma_50_slope`, `m03_score`, `alpha006`). TS alpha compute: 9 alphas in 7s via multiprocessing.

- **T3 migration** (Step 6):
  - Added `alpha008`, `alpha019` columns to `t3_sepa_features`
  - Bulk UPDATE: copied all XS alphas + 7 rank cols from t2 into all 33,562 existing t3 rows (single SQL UPDATE)
  - Backfilled 518 new rows for 2026-02-19 to 2026-03-23
  - Views recreated: `v_d2_training` 1,733 rows, all 10 views healthy

- **Schema cleanup**: Dropped 22 artifact/unused cols from t3 via CTAS rename (DuckDB ALTER blocked by internal dependency bug):
  - 19 `*_pct_chg_1` migration artifact duplicates
  - `price_vs_spy_ma20`, `price_vs_spy_ma50`, `price_vs_spy_ma200` (in `EXCLUDE_BENCHMARK_RS`, never used)
  - t3 now: **130 columns**, 34,080 rows, 2020-01-02 to 2026-03-20

- **`daily_features` DROPPED** — table is gone from DB

- **Deleted superseded scripts**: `scripts/backfill_t3_sepa_features.py`, `scripts/migrate_to_v3_1.py`

- **Manual updated** (`docs/proposals/duckdb_v2/manual_for_me.md`): pipeline diagram, Phase 3 alpha split doc, new Phase 5 (T3) with backfill snippets + XS alpha copy recipe, Phase 6-8 renumbered, Key Tables updated, TODOs/Resolved updated

- **Redesign plan updated** (`docs/proposals/duckdb_v2/phase_3_feature_table_redesign.md`): all 6 steps marked complete

- **M01 model audit**:
  - `M01_FEATURES` in `feature_config.py` is **stale** (72 features, 27 log-transformed) — not used by trained model
  - Actual production model `M01_baseline_20260315_133129` uses **105 raw features, zero log transforms**, defined as `FEATURE_GROUPS` dict in `scripts/train_mfe_classifier.py`
  - Feature set stored in model registry `specs_json.features` — that is the source of truth for inference

## 📝 Files Changed

- `src/feature_pipeline.py`: `compute_alpha_features()` + `warmup_table` param; `_load_data_for_alphas` simplified; T3 TS alpha call uses `warmup_table='t2_screener_features'`
- `src/orchestrators/daily_pipeline_orchestrator.py`: 8-phase design, Phase 5 calls `compute_t3_features()` directly
- `src/managers/view_manager.py`: stale `daily_features` reference fixed
- `data_curator_duckdb.py`: stale `force_full`/`incremental` params removed
- `docs/proposals/duckdb_v2/manual_for_me.md`: major update — 8-phase pipeline, Phase 3 XS/TS split, new Phase 5 T3 section
- `docs/proposals/duckdb_v2/phase_3_feature_table_redesign.md`: all steps marked complete
- `scripts/backfill_t3_sepa_features.py`: **DELETED** (superseded)
- `scripts/migrate_to_v3_1.py`: **DELETED** (superseded)

## 🚧 Work in Progress (CRITICAL)

- **`M01_FEATURES` in `feature_config.py` is stale** — any inference code importing this will use the wrong 72-feature log-transformed set instead of the trained 105-feature set. Any scoring pipeline must read features from the model registry `specs_json.features`, not from `feature_config.py`.

- **`log_alpha008`, `log_alpha019`** not yet added to `v_d2_training` or `M01_FEATURES` — deferred until next retrain.

- **`screener_members` view** — kept for backward compat but was briefly CASCADE-dropped during this session and recreated. Should be formally deprecated and dropped once all join code migrated to `screener_membership` directly.

## ⏭️ Next Steps

1. **Fix `M01_FEATURES` in `feature_config.py`**: Replace the stale 72-feature log-transformed list with the 105-feature log-free set from `FEATURE_GROUPS` in `train_mfe_classifier.py`. Have the training script import from `feature_config.py` instead of defining its own local dict — single source of truth.

2. **Remove log transforms from `v_d2_training`**: 33 `SIGN(f.x) * LN(1 + ABS(f.x))` expressions in ViewManager are now dead code (model doesn't use them). Delete all log transform SQL from the view + remove from any feature lists.

3. **Retrain M01** on new t3 data (34,080 rows vs 1,754 at last training — 19x more data). Use `feature_config.py` as canonical source after fix above.

4. **`rename_tickers.py`** still references `daily_features` in cross-table merge logic — update to `t3_sepa_features` + `t2_screener_features`.

## 💡 Context/Memory

- **DuckDB ALTER TABLE blocked by internal dependency**: Even after dropping all user views, `ALTER TABLE t3_sepa_features DROP COLUMN` fails with "entries that depend on it." `pg_depend` shows no dependencies. Workaround: CTAS (`CREATE TABLE t3_sepa_features_new AS SELECT keep_cols FROM t3_sepa_features`) then rename. Budget ~30s extra any time you need to drop t3 columns.

- **TS alpha warmup bug (fixed)**: The original `_load_data_for_alphas` for t3 joined `price_data INNER JOIN t3_sepa_features ON ticker AND date` — since t3 only has SEPA candidate dates (sparse per ticker), rolling windows (e.g. alpha006 needs 20-day corr) had almost no history. Fix: join against `t2_screener_features` (which has daily continuous coverage per ticker) to get full rolling history, then UPDATE back into t3 rows only.

- **alpha019 zero pre-2024**: Expected behavior. alpha019 = `-1*sign(close-delay(close,7)) * (1 + rank(1+sum(returns,250)))` requires 250-day return history. t2 data starts 2020-01-02; the 250-day window isn't satisfied until ~late 2020. Values before that are legitimately 0.

- **`M01_FEATURES` vs trained model**: The training script `train_mfe_classifier.py` built its own `FEATURE_GROUPS` dict independently of `feature_config.py`. The trained model (`M01_baseline_20260315_133129`) is a multi-class XGBoost classifier (4-class MFE: Noise/Moderate/Strong/Home Run) with 105 raw features. `M01_FEATURES` in `feature_config.py` is a dead legacy artifact from earlier regression-style experiments — it has never been used by the current classifier.