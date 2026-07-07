# Session Handover: 2026-02-15 (Session 2)

## 🎯 Goal
Create SQL-native SEPA screening views (`v_sepa_candidates` and `v_d1_candidates`) to replace Python screening in the scanner pipeline, enabling sub-second candidate filtering directly from DuckDB.

## ✅ Accomplished
- **Rewrote `v_sepa_candidates` view**: Full C1-C9 SEPA trend template enforcement (was only 3 conditions). Now uses v3.0 column names (`rs_rating`, `sma_200_lag20`, `price_vs_spy`, `price_vs_spy_ma63`). Returns 31 columns including RS, volatility, momentum metrics.
- **Created `v_d1_candidates` view**: Full SEPA signal (C1-C11) with breakout (C10) and volume spike (C11). Includes 18 lag features (`LAG() OVER`) and 18 delta features for M01/M02 consumption. Computes `is_new_trigger` flag for 0→1 transition detection. 120 columns total.
- **Auto-refresh infrastructure**: Added `_create_views()` method to `DuckDBDataCurator`, called as Phase 4 after every feature recompute. Views are now always in sync with `daily_features` schema.
- **Fixed data loader**: Updated `get_sepa_candidates()` and `get_sepa_stats()` in `data_loader_duckdb.py` — removed references to non-existent `relative_strength_20d` column (replaced with `rs_rating`).
- **Validation**: Cross-checked view logic against database — D1 is strict subset of SEPA (24 vs 251 on latest date), new trigger counts are reasonable (0-2 per day).

## 📝 Files Changed
- `data_curator_duckdb.py`:
  - Added `_create_views()` method (lines 1066-1269) with SQL for `v_sepa_candidates` and `v_d1_candidates`
  - Modified `run_update()` to call `_create_views()` as Phase 4 after feature computation
  - Updated phase numbering (3/3 → 3/4, added 4/4 for views)
- `src/data_loader_duckdb.py`:
  - Fixed `get_sepa_candidates()`: Changed `ORDER BY relative_strength_20d` → `rs_rating` (line 146)
  - Fixed `get_sepa_stats()`: Changed `AVG(relative_strength_20d)` → `AVG(rs_rating)` (line 442)
  - Updated inline SEPA filter to use v3.0 columns (lines 161-163)
- `data/market_data.duckdb`: Created two views:
  - `v_sepa_candidates`: 251 tickers on 2026-02-13 (C1-C9 trend template)
  - `v_d1_candidates`: 24 tickers on 2026-02-13 (C1-C11 full SEPA signals)

## 🚧 Work in Progress (CRITICAL)
- **Views validated but not yet integrated into scanner**: The `daily_scanner_duckdb.py` still calls Python `VectorizedSEPAScreener.batch_scan_universe()` for C1-C8 filtering. It should be updated to query `v_d1_candidates` directly instead of loading all candidates and screening in Python. This would eliminate the 10-20s screening step.
- **D2/D2R views deferred**: Building `v_d2_features` and `v_d2r_hydrated` requires pre-computing derived fundamental metrics (eps_growth_yoy, operating_margin, pe_ratio, etc.) which currently only exist in Python `FundamentalProcessor`. The `fundamentals` DuckDB table only has raw fields (revenue, net_income, eps_diluted) + earnings calendar JSON — full income/balance/cash flow data from FMP API is still in parquet files. Need a separate session to:
  1. Migrate parquet fundamental data into DuckDB with richer schema
  2. Create `fundamental_features` table via `_compute_fundamental_features()` method
  3. Build D2 view joining D1 + fundamentals + company + log transforms
  4. Build D2R view adding forward returns via `LEAD()` for backtesting

## ⏭️ Next Steps
1. **Update `daily_scanner_duckdb.py`** to use `v_d1_candidates` view instead of Python screening:
   - Replace `loader.get_sepa_candidates() + VectorizedSEPAScreener.batch_scan_universe()` with `SELECT * FROM v_d1_candidates WHERE date = ?`
   - Parse `is_new_trigger` flag instead of detecting transitions in Python
   - Test end-to-end to verify ML scoring still works
2. **Create `fundamental_features` table** (separate session):
   - Add `_write_fundamentals_enriched()` method to `data_curator_duckdb.py` to migrate parquet → DuckDB with full FMP schema
   - Implement `_compute_fundamental_features()` to replicate Python `FundamentalProcessor` logic in SQL
   - Create `v_d2_features` and `v_d2r_hydrated` views

## 💡 Context/Memory
- **SEPA conditions (C1-C11 refresher)**:
  - C1-C8: Trend template (price vs SMAs, 52W bounds, SMA200 trending up)
  - C9: RS line uptrend (benchmark-based: `price_vs_spy > price_vs_spy_ma63`)
  - C10: Breakout (close > 20d prior close high — stored as `breakout` flag in `daily_features`)
  - C11: Volume spike (`vol_ratio_50 > 1.3`)
- **Column naming convention**: `daily_features` uses `snake_case` (sma_50, rs_rating), Python `VectorizedSEPAScreener` expects `PascalCase` (SMA_50, RS). The views use DB column names directly.
- **Lag/Delta pattern**: M01/M02 models need lag features (T-1) and delta features (% change). The D1 view computes these inline using `LAG() OVER (PARTITION BY ticker ORDER BY date)` and percentage change formula `(curr - lag) / |lag|`.
- **Pre-computed columns are trusted**: `sma_200_lag20`, `breakout`, `vol_ratio_50` are all pre-computed in the SQL feature pipeline and correctly match Python logic. No need to recompute in views.
- **Cross-sectional RS ranking**: Python `VectorizedSEPAScreener.batch_screen_universe()` applies C9 as "top 30% rs_rating per date" (cross-sectional). The SQL view uses single-ticker C9 (`price_vs_spy > ma63`) since cross-sectional ranking requires loading full universe first. Scanner can apply cross-sectional filter post-query if needed.
- **View performance**: Views are virtual (not materialized) — they recompute on each query. For daily scanner use (single date query), this is fast (<1s). For historical backtesting across date ranges, consider materializing or using CTEs.
