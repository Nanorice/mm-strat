# Session Log: 2026-02-15 (Session 3) - Fundamental Features Implementation

## 🎯 Objective
Create `fundamental_features` table to store derived fundamental metrics (growth, safety, operating ratios) computed from FMP parquet files, enabling SQL-native D2 feature views for the M01 model.

## ✅ Accomplishments

### 1. Database Schema
**Created `fundamental_features` table** with 41 columns:
- **Primary Keys**: ticker, filing_date, fiscal_period
- **16 Source Columns**: revenue, net_income, eps_diluted, total_assets, total_equity, total_debt, operating_cash_flow, free_cash_flow, gross_profit, operating_income, total_current_assets, total_current_liabilities, inventory, fiscal_date, fiscal_year, period_type
- **7 Growth Metrics**: revenue_growth_yoy, eps_growth_yoy, net_income_growth_yoy, eps_accel, revenue_accel, revenue_cagr_3y, eps_stability_score
- **3 Safety Ratios**: debt_to_equity, current_ratio, quick_ratio
- **11 Operating Metrics**: gross_margin, operating_margin, net_margin, roe, roa, fcf_margin, earnings_quality_score, inventory_growth_yoy, inventory_vs_sales_spread, gross_margin_trend
- **2 Metadata**: feature_version ('v1.0'), updated_at (TIMESTAMP)

### 2. Computation Method
**Added `_compute_fundamental_features()` method** to `data_curator_duckdb.py`:
- Reads fundamentals from parquet files (`data/fundamentals/*.parquet`)
- Uses existing `FundamentalProcessor` class to apply proven Python logic
- Maps FMP schema columns to database schema
- Batch writes to DuckDB with ON CONFLICT upsert
- Location: [data_curator_duckdb.py:1066-1238](data_curator_duckdb.py#L1066-L1238)

### 3. Pipeline Integration
**Modified `run_update()` to include Phase 4** (fundamental features):
```
Phase 1: Fetch raw data (API calls)
Phase 2: Write to DuckDB
Phase 3: Compute daily_features (technical indicators)
Phase 4: Compute fundamental_features (quarterly metrics) ← NEW
Phase 5: Create/refresh views
```
- Triggered when `--update-fundamentals` or `--update-features` flags are used
- Processes all tickers with available parquet files
- Location: [data_curator_duckdb.py:310-316](data_curator_duckdb.py#L310-L316)

### 4. D2 View Creation
**Created `v_d2_features` view** for M01 model consumption:
- **Joins**: v_d1_candidates + fundamental_features + company_profiles
- **Point-in-time correctness**: Uses most recent `filing_date <= d1.date` to prevent look-ahead bias
- **173 total columns**: 120 from D1 + ~30 fundamental features + company metadata
- **13,496 rows** (all D1 signals since 2020-01-01)
- Location: [data_curator_duckdb.py:1428-1480](data_curator_duckdb.py#L1428-L1480)

### 5. Testing & Validation
**Tested with 5 tickers** (AAPL, MSFT, GOOGL, AMZN, TSLA):
```
✅ 612 fundamental feature records written
✅ AAPL: 162 quarters of data (1985-2025)
✅ Growth metrics computed correctly (YoY, acceleration, CAGR)
✅ Margins and ratios computed correctly
✅ View join works with point-in-time logic
```

Sample AAPL latest quarter (v_d2_features):
```
ticker: AAPL
date: 2026-02-04
revenue_growth_yoy: 15.65%
eps_growth_yoy: 18.26%
gross_margin: 48.16%
roe: 47.73%
fundamental_filing_date: 2026-01-30
fiscal_period: Q1
```

## 📝 Files Modified

### Core Infrastructure
1. **data_curator_duckdb.py**:
   - Added `_compute_fundamental_features()` method (173 lines)
   - Modified `run_update()` to include Phase 4 (7 lines)
   - Modified `_create_views()` to add v_d2_features (53 lines)
   - Changed phase numbering from [3/4] → [3/5], [4/4] → [5/5]

### Database
2. **data/market_data.duckdb**:
   - Created `fundamental_features` table (41 columns, PRIMARY KEY on ticker, filing_date, fiscal_period)
   - Created `v_d2_features` view (173 columns, LEFT JOIN logic)

### Documentation
3. **docs/fundamental_features_design.md** (NEW):
   - Schema design rationale
   - Column definitions
   - Implementation strategy
   - SQL vs Python trade-offs

### Testing
4. **scripts/test_fundamental_features.py** (NEW):
   - Validates computation with 5 sample tickers
   - Checks row counts, data quality, NULL percentages
   - Displays sample data for AAPL

## 🔧 Technical Decisions

### 1. Python vs SQL for Feature Computation
**Decision**: Use Python (FundamentalProcessor)
**Rationale**:
- FundamentalProcessor already tested and handles edge cases (YoY growth, rolling windows, duplicates)
- SQL window functions can be complex for multi-period calculations (LAG(4) for YoY)
- Fundamental data is quarterly (low volume) — Python overhead is negligible
- Can optimize to SQL later if needed

### 2. Point-in-Time Join Logic
**Challenge**: How to join daily price data with quarterly fundamental data without look-ahead bias?
**Solution**: Subquery with MAX(filing_date) WHERE filing_date <= d1.date
```sql
LEFT JOIN fundamental_features ff
    ON d1.ticker = ff.ticker
    AND ff.filing_date = (
        SELECT MAX(filing_date)
        FROM fundamental_features
        WHERE ticker = d1.ticker
        AND filing_date <= d1.date
    )
```
This ensures we only use fundamental data that was **publicly available** as of the trading date.

### 3. Column Mapping Strategy
FMP parquet files use camelCase (e.g., `totalAssets`, `epsDiluted`). Database uses snake_case (e.g., `total_assets`, `eps_diluted`). Mapping is handled in `_compute_fundamental_features()` via explicit dictionary.

### 4. Emoji Encoding Fix
Windows console (cp1252) doesn't support Unicode emojis. Changed all status messages:
- ✅ → `[OK]`
- ❌ → `[ERROR]`
- ⚠️ → `[WARN]`

## 📊 Data Quality Observations

### Coverage
- AAPL has 162 quarters (40+ years of data)
- Some early periods have NULL growth metrics (expected — need 4 quarters back for YoY)
- ~5% NULL in roe (expected for companies with negative equity)

### Point-in-Time Join
- Latest D1 date (2026-02-13) has 24 signals
- AAPL's most recent fundamental data is from 2026-01-30 (Q1 filing)
- Join correctly matches this filing to all trading dates from 2026-01-30 onwards

## 🚧 Known Limitations

1. **Fundamental Coverage**: Only 5 tickers have fundamental_features populated (test data). Need to run full computation for all ~1800 tickers.

2. **Parquet Dependency**: Method assumes fundamentals exist as parquet files. If parquet is deleted, fundamental_features becomes stale.

3. **No Incremental Update**: Currently rebuilds all fundamental features on each run. Could optimize to only process tickers with new parquet data.

4. **D2R View Deferred**: The handover mentioned `v_d2r_hydrated` (D2 + forward returns for backtesting). This requires LEAD() window functions and is deferred to a future session.

## ⏭️ Next Steps

### Immediate (Current Session)
- ✅ Create fundamental_features table
- ✅ Implement _compute_fundamental_features()
- ✅ Integrate into pipeline
- ✅ Test with sample tickers
- ✅ Create v_d2_features view

### Future Sessions
1. **Run Full Fundamental Computation**:
   ```bash
   python data_curator_duckdb.py --update-fundamentals --update-features
   ```
   This will populate fundamental_features for all ~1800 tickers.

2. **Update Scanner to Use v_d1_candidates**:
   - Modify `daily_scanner_duckdb.py` to query `v_d1_candidates` directly instead of Python screening
   - Eliminate the 10-20s VectorizedSEPAScreener step
   - Parse `is_new_trigger` flag instead of detecting transitions in Python

3. **Create v_d2r_hydrated View** (for backtesting):
   ```sql
   CREATE VIEW v_d2r_hydrated AS
   SELECT
       d2.*,
       LEAD(close, 5) OVER (PARTITION BY ticker ORDER BY date) as forward_close_5d,
       LEAD(close, 20) OVER (PARTITION BY ticker ORDER BY date) as forward_close_20d,
       -- ... forward return calculations
   FROM v_d2_features d2
   ```

4. **Model Retraining**:
   - M01 can now query `v_d2_features` for training data (includes all fundamental features)
   - M02 continues to use `v_d1_candidates` (no fundamentals needed)

## 💡 Key Learnings

### 1. DuckDB ON CONFLICT Quirks
- `DEFAULT CURRENT_TIMESTAMP` columns should NOT be in the INSERT column list
- `updated_at = CURRENT_TIMESTAMP` in UPDATE SET clause is treated as column reference (not function) — just omit it and let the DEFAULT trigger

### 2. FMP Parquet Schema
- FMP stores 3 statement types in one file: income, balance_sheet, cash_flow
- Merged statements can have duplicate columns (e.g., `operatingCashFlow` in both income and cash_flow)
- FundamentalProcessor handles this with suffix-based deduplication

### 3. View Performance
- Views are virtual (not materialized) — they recompute on each query
- For daily scanner (single date query), this is fast (<1s)
- For historical backtesting (date ranges), consider materializing or using CTEs

## 🔗 Related Documents
- [Handover from Session 2](2026-02-15_session_2_d1_views.md)
- [Fundamental Features Design](../fundamental_features_design.md)
- [Feature Gap Analysis](../feature_gap_analysis.md)
- [Architecture Overview](../architecture/)

## 📈 Metrics
- **Lines of code added**: ~250
- **Database objects created**: 1 table + 1 view
- **Test data processed**: 5 tickers, 612 quarters
- **View row count**: 13,496 (D1 signals since 2020)
- **Session duration**: ~45 minutes
