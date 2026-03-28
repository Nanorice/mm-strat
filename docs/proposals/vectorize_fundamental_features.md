# Plan: Vectorize `_compute_fundamental_features()` via DuckDB SQL

## Context

`_compute_fundamental_features()` in `data_curator_duckdb.py` (lines 789-949) loops through **5000+ parquet files** one ticker at a time, runs Python's `FundamentalProcessor`, then writes to the `fundamental_features` DuckDB table. This takes ~60s and **completely bypasses the DuckDB `fundamentals` table** — contradicting the DuckDB migration goal.

**Root cause**: The `fundamentals` table only stores 6 raw metrics (revenue, net_income, eps_diluted, total_assets, total_equity, operating_cash_flow). The 7 columns needed for derived metric computation (total_debt, free_cash_flow, gross_profit, operating_income, total_current_assets, total_current_liabilities, inventory) are missing.

**Worse**: The `fundamentals` table has a **statement merge bug** — the 3 FMP statement types (income, balance_sheet, cash_flow) are written as separate rows that share the same PK `(ticker, report_date, period_type)`, so the last INSERT wins and overwrites earlier columns with NULL. Empirically confirmed: `has_both (revenue AND total_assets)` = **0 rows** out of 341K.

**Goal**: Fix the merge, expand the schema, replace Python loop with SQL window functions. Expected: ~2s vs ~60s.

---

## Implementation Steps

### Step 1: Expand `fundamentals` table schema

**File**: `scripts/migrate_to_duckdb.py` (line 119-136)

Add 7 columns to the CREATE TABLE definition:
```sql
total_debt DOUBLE,
free_cash_flow DOUBLE,
gross_profit DOUBLE,
operating_income DOUBLE,
total_current_assets DOUBLE,
total_current_liabilities DOUBLE,
inventory DOUBLE,
```

Add a migration function for existing databases:
```sql
ALTER TABLE fundamentals ADD COLUMN IF NOT EXISTS total_debt DOUBLE;
-- (repeat for all 7)
```

### Step 2: Fix statement merge in `_fetch_fundamentals()`

**File**: `data_curator_duckdb.py` (lines 534-563)

**Problem**: `fund_engine.get_ticker_fundamentals()` returns 3 rows per quarter (one per statement_type). Currently these go straight to `ON CONFLICT` which overwrites.

**Fix**: Add `_merge_statement_types()` method (~20 lines):
1. Group by `(ticker, fiscal_date, fiscal_period)`
2. Aggregate with `first()` — each metric is non-null in only one statement type, so first-non-null correctly consolidates 3 rows → 1 row
3. Call this **before** the rename/column-selection step

Update `duckdb_columns` list (line 551-553) to include the 7 new columns:
```python
duckdb_columns = [
    'ticker', 'report_date', 'filing_date', 'period_type', 'fiscal_year',
    'revenue', 'net_income', 'eps_diluted', 'total_assets', 'total_equity',
    'operating_cash_flow',
    # NEW: columns needed for vectorized feature computation
    'total_debt', 'free_cash_flow', 'gross_profit', 'operating_income',
    'total_current_assets', 'total_current_liabilities', 'inventory'
]
```

Update the rename mapping (line 539-548) to include:
```python
'totalDebt': 'total_debt',
'freeCashFlow': 'free_cash_flow',
'grossProfit': 'gross_profit',
'operatingIncome': 'operating_income',
'totalCurrentAssets': 'total_current_assets',
'totalCurrentLiabilities': 'total_current_liabilities',
```

### Step 3: Replace `_compute_fundamental_features()` with SQL

**File**: `data_curator_duckdb.py` (lines 789-949)

Replace the 160-line Python method with ~30 lines that execute a SQL CTE chain:

```sql
CREATE OR REPLACE TABLE fundamental_features AS
WITH base AS (
    SELECT ticker, report_date, filing_date,
           period_type AS fiscal_period, fiscal_year,
           report_date AS fiscal_date,
           revenue, net_income, eps_diluted, total_assets, total_equity,
           total_debt, operating_cash_flow, free_cash_flow, gross_profit,
           operating_income, total_current_assets, total_current_liabilities, inventory
    FROM fundamentals
    WHERE period_type IN ('Q1','Q2','Q3','Q4')  -- exclude earnings-only 'Q' rows
),
growth AS (
    -- YoY growth (LAG 4 quarters), CAGR, inventory growth
    SELECT *,
        (revenue / NULLIF(LAG(revenue, 4) OVER w, 0) - 1) * 100 AS revenue_growth_yoy,
        (eps_diluted / NULLIF(LAG(eps_diluted, 4) OVER w, 0) - 1) * 100 AS eps_growth_yoy,
        (net_income / NULLIF(LAG(net_income, 4) OVER w, 0) - 1) * 100 AS net_income_growth_yoy,
        CASE WHEN LAG(revenue, 12) OVER w > 0 AND revenue > 0
             THEN (POWER(revenue / LAG(revenue, 12) OVER w, 1.0/3) - 1) * 100 END AS revenue_cagr_3y,
        (inventory / NULLIF(LAG(inventory, 4) OVER w, 0) - 1) * 100 AS inventory_growth_yoy
    FROM base
    WINDOW w AS (PARTITION BY ticker ORDER BY fiscal_date)
),
accel AS (
    -- Acceleration + stability + spread
    SELECT *,
        eps_growth_yoy - LAG(eps_growth_yoy, 1) OVER w AS eps_accel,
        revenue_growth_yoy - LAG(revenue_growth_yoy, 1) OVER w AS revenue_accel,
        inventory_growth_yoy - revenue_growth_yoy AS inventory_vs_sales_spread,
        STDDEV(eps_growth_yoy) OVER (PARTITION BY ticker ORDER BY fiscal_date
            ROWS BETWEEN 7 PRECEDING AND CURRENT ROW) AS eps_stability_score
    FROM growth
    WINDOW w AS (PARTITION BY ticker ORDER BY fiscal_date)
),
metrics AS (
    -- Point-in-time ratios + margins + trend
    SELECT *,
        total_debt / NULLIF(total_equity, 0) AS debt_to_equity,
        total_current_assets / NULLIF(total_current_liabilities, 0) AS current_ratio,
        (total_current_assets - COALESCE(inventory, 0)) / NULLIF(total_current_liabilities, 0) AS quick_ratio,
        (gross_profit / NULLIF(revenue, 0)) * 100 AS gross_margin,
        (operating_income / NULLIF(revenue, 0)) * 100 AS operating_margin,
        (net_income / NULLIF(revenue, 0)) * 100 AS net_margin,
        (net_income / NULLIF(total_equity, 0)) * 100 AS roe,
        (net_income / NULLIF(total_assets, 0)) * 100 AS roa,
        (free_cash_flow / NULLIF(revenue, 0)) * 100 AS fcf_margin,
        operating_cash_flow / NULLIF(net_income, 0) AS earnings_quality_score
    FROM accel
)
SELECT *,
    gross_margin - AVG(gross_margin) OVER (PARTITION BY ticker ORDER BY fiscal_date
        ROWS BETWEEN 4 PRECEDING AND 1 PRECEDING) AS gross_margin_trend,
    'v2.0' AS feature_version
FROM metrics
```

**Key filter**: `WHERE period_type IN ('Q1','Q2','Q3','Q4')` excludes the 174K earnings-only `'Q'` rows (which lack financial statement data).

### Step 4: Backfill existing `fundamentals` data

**File**: New script `scripts/backfill_fundamentals_columns.py`

One-time migration to populate the 7 new columns for existing data:
1. `ALTER TABLE` to add columns
2. Read all parquet files via `duckdb.read_parquet('data/fundamentals/*.parquet')`
3. Merge statement types in SQL (GROUP BY + COALESCE/FIRST)
4. UPDATE fundamentals SET total_debt=..., gross_profit=... matching on PK
5. Re-run the SQL feature computation to rebuild `fundamental_features`

**After backfill**: The normal pipeline (`--update-fundamentals`) handles future data correctly via the fixed `_fetch_fundamentals()`.

### Step 5: Update `fundamental_features` ON CONFLICT clause

The current `_compute_fundamental_features()` uses `INSERT ... ON CONFLICT` (lines 935-939). The new SQL approach uses `CREATE OR REPLACE TABLE` (full rebuild, same pattern as `daily_features` Phase A). This is simpler and avoids the ON CONFLICT `updated_at` issue.

Add `updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP` to the final SELECT if needed to preserve the column.

---

## Files Modified

| File | Change |
|------|--------|
| `data_curator_duckdb.py` | Fix `_fetch_fundamentals()` merge; replace `_compute_fundamental_features()` with SQL |
| `scripts/migrate_to_duckdb.py` | Add 7 columns to `fundamentals` CREATE TABLE |
| `scripts/backfill_fundamentals_columns.py` | **NEW** — one-time migration script |

## Files NOT Modified (downstream OK)

| File | Why |
|------|-----|
| `src/view_manager.py` | Reads from `fundamental_features` — schema unchanged (same 41 columns) |
| `src/fundamental_processor.py` | Kept as reference/validation — not deleted |
| `src/feature_pipeline.py` | Only handles `daily_features` — no dependency |

---

## Verification

1. **Parity check**: For 5 tickers (AAPL, MSFT, NVDA, AMZN, TSLA), compare old Python output vs new SQL output for all 20 derived metrics. Tolerance: atol=0.01 for percentages, rtol=0.001 for ratios.
2. **Row count**: `fundamental_features` should have ~166K rows (matching current, only Q1-Q4 financial statement rows).
3. **Null check**: `revenue AND total_assets` should coexist in most rows (currently 0 in `fundamentals` — should be ~156K after merge fix).
4. **Performance**: Time the SQL computation (expect ~2-3s vs ~60s).

---

## Known Divergences from Python

| Area | Python | SQL | Impact |
|------|--------|-----|--------|
| Division by zero | `np.where(x!=0, ..., NaN)` → could produce `inf` then replace | `NULLIF(x,0)` → NULL directly | None (both = missing) |
| STDDEV | `rolling(8, min_periods=4).std()` | `STDDEV OVER ROWS 7 PRECEDING` (min_periods=1) | Slightly more NULLs in Python for first few quarters |
| eps column | Python uses `eps` (basic) | SQL uses `eps_diluted` | Minor — `eps_diluted` is what's in the table |
| `period_type` mapping | `fiscal_period` in parquet | `period_type` in fundamentals table (Q1-Q4) | Handled by alias in SQL |

---

## Data Integrity Findings

### Current State Analysis

- **fundamentals table**: 341K rows, but severely fragmented:
  - 174K earnings-only rows (period_type='Q', have revenue only)
  - 167K financial statement rows (period_type=Q1-Q4, scattered across statement types)
  - `has_both (revenue AND total_assets)`: **0 rows** (should be ~156K after fix)

- **fundamental_features table**: 166K rows (correctly computed from parquet where merge is done properly)

### Root Cause

The `_fetch_fundamentals()` method reads from `FundamentalEngine.get_ticker_fundamentals()`, which returns 3 rows per quarter:
- Row 1: income statement (revenue, net_income, eps_diluted non-null)
- Row 2: balance_sheet (total_assets, total_equity non-null)
- Row 3: cash_flow (operating_cash_flow non-null)

These 3 rows share the same `(ticker, report_date, period_type)` PK, so the `ON CONFLICT DO UPDATE` causes overwrites. The last statement type to be inserted wins and overwrites with NULL values from the other statement types.

### Solution

The `_merge_statement_types()` method will consolidate the 3 statement rows into 1 row before INSERT, preventing the data loss. This mirrors what `FundamentalProcessor._merge_statements()` does but at the buffer/ingestion layer instead of at computation time.
