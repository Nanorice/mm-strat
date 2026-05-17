# Session Handover: 2026-03-24

## 🎯 Goal
Implement Phase 3 of the feature table redesign: eliminate `daily_features`, migrate cross-sectional alphas + ranks to t2, rebuild t3 directly from t2 + price_data.

## ✅ Accomplished

- **Alpha correctness audit & fix**: Identified 7 alphas (001,002,004,011,013,015,060) where `rank()` was implemented as per-ticker time-series rank instead of cross-sectional rank across tickers on each date. Fixed all 7 to use `groupby('date').rank(pct=True)`.

- **Alpha split into XS vs TS**:
  - `ALPHA_COLS_XS` = [001,002,004,008,011,013,015,019,060] — cross-sectional, need full universe population
  - `ALPHA_COLS_TS` = [006,009,012,041,046,049,051,054,101] — pure per-ticker time-series

- **Two new alphas added**:
  - `alpha008`: `-1 * rank((sum(open,5)*sum(returns,5)) - delay(...,10))` — 5-day open×return momentum rank
  - `alpha019`: `-1*sign(close-delay(close,7)) * (1 + rank(1+sum(returns,250)))` — 250-day return momentum rank

- **Vectorisation**: Converted alpha006,009,011,013,015 from `groupby.apply` to `transform`-based ops. alpha001,004,060 remain `rolling().apply` (inherent — ts_argmax/ts_rank need custom Python per window).

- **`compute_alpha_features()` made table-agnostic**: new `target_table` + `alpha_cols` params. `_load_data_for_alphas`, `_ensure_alpha_columns_exist`, `_write_alpha_columns` all updated.

- **`compute_cross_sectional_ranks()` made table-agnostic**: `target_table` param added.

- **Step 1 complete — t2 extended**:
  - DDL: added `price_vs_spy`, `price_vs_spy_ma63`, `pct_above_low_52w`, 7 rank cols, 9 XS alpha cols
  - `compute_t2_screener_features()` now calls XS alphas then cross-sectional ranks after SQL INSERT

- **Step 2 complete — t3 rebuilt**:
  - `_create_t3_table()`: drops old t3, creates clean schema (no `_1` migration artifacts)
  - `compute_t3_features()`: fully rewritten with no `daily_features` dependency. SQL CTEs compute all per-ticker window features (momentum, RSI, volume depth, ATR14, returns, pattern flags, velocity, pct_chg deltas). XS alphas + ranks carried from t2. M03 joined from t2_regime_scores. TS alphas computed via Python after SQL insert.

## 📝 Files Changed

- `src/feature_pipeline.py`: Major changes — alpha correctness fixes, XS/TS split, new alpha008/019, table-agnostic helpers, t2 DDL/SELECT extended, new `_create_t3_table()`, `compute_t3_features()` rewritten

- `docs/proposals/duckdb_v2/phase_3_feature_table_redesign.md`: Steps 1+2 marked complete with detail, Steps 3-6 updated with current state

## 🚧 Work in Progress (CRITICAL)

- **Nothing has been run/tested yet.** All changes are code-only. The new `compute_t3_features()` SQL is complex — the `with_velocity` CTE uses `WINDOW w_tk` but references `pt.ticker` and `pt.date` which need to be available in that scope. Verify DuckDB accepts the window definition in that CTE.

- **`_create_t3_table()` is not yet called anywhere.** It needs to be wired into `compute_all()` or called manually before first run.

- **`compute_all()` not yet updated** — still calls old `_compute_full_rebuild()` which targets `daily_features`.

- **`_load_data_for_alphas` for t2 path**: the INNER JOIN restricts to screener members correctly, but the query no longer fetches `return_1d` / `vol_avg_20` (removed to simplify). Alpha implementations don't use these columns directly (they use `wq_returns` derived from `close`), so this should be fine — but needs verification.

- **pct_chg deltas in t3 CTE**: computed via `LAG(t2.col, 1) OVER w_tk` where `w_tk` is partitioned by `pt.ticker`. This works only if the ticker appeared in t2 on the previous day too (i.e., was a screener member). For tickers that enter the screener for the first time, the first row's delta will be NULL — expected, same as before.

## ⏭️ Next Steps

1. **Step 3**: Clean up `FeaturePipeline` — delete `compute_base_features()`, `_compute_full_rebuild()`. Wire `_create_t3_table()` into `compute_all()`. Update `compute_all()` to call `compute_t2_screener_features()` → `compute_t3_features()`.

2. **Step 4**: Update orchestrator — delete Phase 6, update Phase 5 to call new t3 method directly.

3. **Step 5**: Audit ViewManager — remove `*_pct_chg_1` references, verify all column names against new t3 schema. Consider adding `log_alpha008`, `log_alpha019` to `v_d2_training` and `M01_FEATURES`.

4. **Checkpoint test**: After Steps 3-5, run `compute_t2_screener_features('2024-01-01')` for a single date, then `compute_t3_features('2024-01-16', '2024-01-19')` and verify row counts + spot-check 3 tickers.

5. **Step 6** (last): Full t3 backfill from 2020-01-01, validate v_d2_training row count, DROP TABLE daily_features.

## 💡 Context/Memory

- **Why XS alphas on t2**: Cross-sectional `rank()` across 50-200 SEPA candidates gives distorted percentiles. Needs full ~2400 screener population to be statistically valid. TS alphas (rolling window ops) are population-independent so can safely run on the smaller t3 set.

- **alpha019 is the key new momentum signal**: `rank(1 + sum(returns, 250))` = 1-year cross-sectional return momentum rank. This is the WQ101 equivalent of RS Rating — ranks tickers by trailing 1-year return. Highly relevant to SEPA.

- **WQ101 `rank()` is always cross-sectional** (line 125-132 in WorldQuant_101.py: `df.rank(pct=True)` — intended to rank across columns/tickers on each date). Our old implementation was calling `.rank(pct=True)` inside `_per_ticker` which ranked within each ticker's own history — semantically wrong.

- **`daily_features` still exists** — nothing has been dropped. Steps 3-6 are required before it can be removed. The old path (full rebuild) still works unchanged.

- **t2_regime_scores table**: t3 joins this for M03 columns. Verify this table exists and has `(ticker, date)` as key before running t3 compute.
