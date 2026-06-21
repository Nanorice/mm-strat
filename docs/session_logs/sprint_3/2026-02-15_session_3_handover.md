# Session Handover: 2026-02-15 (Session 3)

## 🎯 Goal
Create `fundamental_features` table to store derived fundamental metrics (growth, safety, operating ratios) and build `v_d2_features` view for M01 model consumption.

## ✅ Accomplished
- **Created `fundamental_features` table** (41 columns): Primary keys (ticker, filing_date, fiscal_period) + 16 source columns + 21 derived metrics (YoY growth, acceleration, CAGR, margins, ratios, quality scores)
- **Implemented `_compute_fundamental_features()` method** in `DuckDBDataCurator`: Reads FMP parquet files, applies `FundamentalProcessor` logic, batch writes to DuckDB with ON CONFLICT upsert
- **Integrated into pipeline as Phase 4**: Modified `run_update()` to include fundamental feature computation after daily_features (Phase 3) and before views (Phase 5)
- **Created `v_d2_features` view** (173 columns, 13.5K rows): Joins `v_d1_candidates` + `fundamental_features` + `company_profiles` with point-in-time correct logic (most recent filing_date ≤ trading date)
- **Tested with 5 tickers** (AAPL, MSFT, GOOGL, AMZN, TSLA): 612 quarters processed, all metrics computed correctly, view join validated
- **Fixed emoji encoding issues**: Changed all status messages from Unicode (✅❌⚠️) to ASCII ([OK][ERROR][WARN]) for Windows console compatibility

## 📝 Files Changed
- `data_curator_duckdb.py`:
  - Added `_compute_fundamental_features()` method (lines 1066-1238): Reads parquet, applies FundamentalProcessor, writes to fundamental_features table
  - Modified `run_update()` Phase 3→4→5 sequencing (lines 293-318): Added Phase 4 for fundamental computation
  - Modified `_create_views()` to add `v_d2_features` view (lines 1428-1480): D1 + fundamentals + company LEFT JOIN with point-in-time logic
  - Changed phase numbering: [3/4]→[3/5], [4/4]→[5/5]
  - Fixed emoji encoding: ✅→[OK], ❌→[ERROR], ⚠️→[WARN]
- `data/market_data.duckdb`:
  - Created `fundamental_features` table (41 columns, PRIMARY KEY on ticker, filing_date, fiscal_period, DEFAULT 'v1.0' feature_version)
  - Created `v_d2_features` view (173 columns: 120 D1 + 30 fundamentals + company metadata)
  - **Current state**: Only 5 test tickers have data (612 rows), view has 13.5K rows total
- `scripts/test_fundamental_features.py` (NEW): Validation script for fundamental computation (tests 5 tickers, checks row counts, data quality, NULL percentages)
- `docs/fundamental_features_design.md` (NEW): Schema design, column definitions, SQL vs Python trade-offs, implementation strategy
- `docs/session_logs/2026-02-15_session_3_fundamental_features.md` (NEW): Detailed session log with technical decisions, data quality observations, metrics

## 🚧 Work in Progress (CRITICAL)
- **`fundamental_features` is mostly empty**: Only 5 test tickers (AAPL, MSFT, GOOGL, AMZN, TSLA) have data. Need to run full computation for all ~1800 tickers with: `python data_curator_duckdb.py --update-fundamentals --update-features`
- **`v_d2_features` fundamental coverage is incomplete**: Latest D1 date (2026-02-13) has 24 signals but 0% fundamental coverage because test tickers don't overlap with current D1 candidates. Full backfill will resolve this.
- **Scanner still uses Python screening**: `daily_scanner_duckdb.py` calls `VectorizedSEPAScreener.batch_scan_universe()` for C1-C8 filtering instead of querying `v_d1_candidates` directly (10-20s overhead). This was deferred from Session 2 and is now ready to be updated.
- **D2R view not created**: `v_d2r_hydrated` (D2 + forward returns for backtesting) requires LEAD() window functions and was deferred to future session. Needed for M01 backtesting.

## ⏭️ Next Steps
1. **Backfill fundamental_features from 2018-01-01** (PRIORITY):
   - Run: `python data_curator_duckdb.py --update-fundamentals --update-features --start-date 2018-01-01`
   - **CRITICAL**: Need warmup period for YoY growth (4 quarters back) — must fetch data from 2017-Q1 onwards to compute 2018-Q1 growth metrics
   - Expect ~1800 tickers × ~30 quarters = ~54K rows
   - This will populate `v_d2_features` with full fundamental coverage for M01 training
2. **Update `daily_scanner_duckdb.py` to use `v_d1_candidates` view**:
   - Replace `loader.get_sepa_candidates() + VectorizedSEPAScreener.batch_scan_universe()` with `SELECT * FROM v_d1_candidates WHERE date = ?`
   - Parse `is_new_trigger` flag instead of detecting 0→1 transitions in Python
   - Eliminate 10-20s screening overhead
   - Test end-to-end to verify ML scoring still works
3. **Optimize alpha factor calculation using DuckDB** (NEW):
   - Current: Python `alpha_factors.py` computes 16 WorldQuant alphas per-ticker via pandas
   - Goal: Migrate alpha logic to SQL window functions in `_compute_features_incremental()` Phase A
   - Expected speedup: 10-20x (DuckDB vectorized ops vs Python loops)
   - Challenge: WorldQuant alphas use rank(), ts_rank(), correlation() — need DuckDB equivalents
4. **Create `v_d2r_hydrated` view** (for backtesting):
   - Add forward return columns using LEAD() window functions: forward_close_5d, forward_close_20d, forward_return_5d, forward_return_20d
   - This view is required for M01 backtesting (training requires forward returns)
5. **Model retraining with v_d2_features**:
   - M01 can now query `v_d2_features` for training data (includes all 21 fundamental features)
   - Expect improved performance vs parquet-based pipeline (faster query, consistent schema)

## 💡 Context/Memory
- **Point-in-time join pattern**: `v_d2_features` uses subquery `MAX(filing_date) WHERE filing_date <= d1.date` to prevent look-ahead bias. This ensures fundamental data used for a trading date was publicly available on that date (not filed after).
- **FMP parquet schema quirk**: Each ticker's parquet has 3 statement types (income, balance_sheet, cash_flow) with potential duplicate columns (e.g., `operatingCashFlow` in multiple statements). `FundamentalProcessor._merge_statements()` handles this with suffix-based deduplication (_income, _balance, _cashflow) then coalesces with fillna().
- **Why Python for fundamentals, not SQL**: YoY growth requires LAG(4), acceleration requires diff(), CAGR requires power functions, stability score requires rolling std(). While technically possible in SQL, FundamentalProcessor has 600+ lines of tested logic handling edge cases (negative equity, zero division, missing periods). Python overhead is negligible for quarterly data (~54K rows total).
- **DuckDB ON CONFLICT gotcha**: When using DEFAULT CURRENT_TIMESTAMP on a column, do NOT include it in INSERT column list or UPDATE SET clause. Let the default trigger automatically. Trying to set `updated_at = CURRENT_TIMESTAMP` in UPDATE SET causes "column not found" error because DuckDB treats it as column reference.
- **Warmup period math**: To compute 2018-Q1 revenue_growth_yoy (requires 2017-Q1 data), eps_stability_score (8Q rolling std → needs 2016-Q1), revenue_cagr_3y (12Q back → needs 2015-Q1), must fetch fundamentals from **2015-Q1 onwards** to backfill 2018-01-01 features without NULLs.
- **View vs materialized table trade-off**: Views are virtual (recompute on query). For daily scanner (single date WHERE clause), this is <1s. For backtesting (date range queries), views can be slow. Consider `CREATE TABLE AS SELECT` for frequently-used historical ranges.
- **Fundamental coverage will be sparse for new IPOs**: Companies with <4 quarters of data will have NULL YoY growth. Companies with <8 quarters have NULL stability scores. This is expected and handled by model training (NaN imputation or dropna).

## 📊 Session Metrics
- **Database objects created**: 1 table (`fundamental_features`, 41 columns) + 1 view (`v_d2_features`, 173 columns)
- **Test data processed**: 5 tickers, 612 quarters, 0 errors
- **Code added**: ~250 lines (1 method + pipeline integration + view SQL)
- **Views in production**: 3 (v_sepa_candidates, v_d1_candidates, v_d2_features)
- **Session duration**: ~60 minutes
