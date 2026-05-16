# Proposal: Historical Shares Tracking

## Problem
Currently, our `company_profiles` table stores only the *latest* `shares_outstanding` and `float_shares`. This "point-in-time" snapshot is insufficient for accurate backtesting, as share counts change over time (buybacks, dilution, splits). Using the latest share count for historical dates leads to incorrect market cap calculations and valuation ratios.

## Solution
Implement a dedicated `shares_history` table in DuckDB to track changes in share counts over time. Use `yfinance`'s `get_shares_full()` method, which provides a time series of share counts, to populate this table.

## Schema Design

### New Table: `shares_history`
| Column | Type | Description |
| :--- | :--- | :--- |
| `ticker` | VARCHAR | Stick symbol (FK) |
| `date` | DATE | Date of the share count record |
| `shares_outstanding` | BIGINT | Total shares outstanding |
| `updated_at` | TIMESTAMP | Record processing timestamp |

**Primary Key**: `(ticker, date)`

## Implementation Details

### 1. Data Source
- **Source**: Yahoo Finance (`yfinance`)
- **Method**: `ticker.get_shares_full(start="1990-01-01")`
- **Data**: Returns a Series indexed by Date.

### 2. Fetching Strategy
- **Batching**: While `yfinance` has a `Tickers` batch class, `get_shares_full` is an instance method. We will use `ThreadPoolExecutor` (as demonstrated in the prototype) to fetch efficiently in parallel.
- **Frequency**: Share counts change infrequently (quarterly/annually). We can run this update weekly or monthly.
- **Logic**:
    1.  Fetch history for ticker.
    2.  Deduplicate dates (keep last).
    3.  Upsert into `shares_history`.

### 3. Integration
- **Script**: Create a new engine/method `SharesEngine.update_shares_history()` or extend `CompanyProfileEngine`.
- **Curator**: Add `--update-shares` flag to `data_curator_duckdb.py`.
- **Views**: Update `v_d2_features` (or a new view) to join `price_data` with `shares_history` using an `ASOF JOIN` (or window function `LAST_VALUE`) to get the correct share count for each trading day.

## Comparison: yfinance vs FMP
- **yfinance**: Free, easy time-series access, demonstrated speed (0.36s / 4 tickers).
- **FMP**: Has `historical-number-of-shares` ($), `enterprise-values` ($) endpoints. Good backup if YF fails.

## Next Steps
1.  Approve this proposal.
2.  Create `shares_history` table.
3.  Implement fetch logic in `src/shares_engine.py` (new).
4.  Integrate into curator and pipeline.
