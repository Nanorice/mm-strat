# Proposal (v2): Dynamic Point-in-Time Universe Architecture

## 1. Context & Motivation
The current "Universe" is static (defined by files in `data/price/`) and biased (survivorship bias). Features like `RS_Universe_Rank` are calculated against *current* survivors, not the historical set. This leads to look-ahead bias and inaccurate backtests.

We need a system that reconstructs the **Set of Active Candidate Tickers** for any given month in history ($U_{t}$), ensuring that failed/delisted companies are included historically but filtered out after failure.

## 2. Architecture Overview

### A. New Components

#### 1. `UniverseDiscovery` (Python Module)
A standalone module responsible for identifying candidate tickers.
- **Function:** `fetch_candidates(date)` -> List[str]
- **Sources:**
    - **Backfill (2000-2024):** FMP Delisted Companies Endpoint + FMP Historical Market Cap (or proxy).
    - **Ongoing (Monthly):** FMP Screener API (Market Cap > $50M, Price > $2, Vol > $500k).
- **Output:** Writes to DuckDB `universe_constituents` table.

#### 2. `universe_constituents` (DuckDB Table)
The single source of truth for universe membership.

```sql
CREATE TABLE universe_constituents (
    ticker VARCHAR,
    month_start_date DATE,     -- The month for which this ticker is valid
    reason_included VARCHAR,   -- e.g. 'top_3000_mktcap', 'index_constituent'
    is_active BOOLEAN,         -- Flag to handle mid-month delistings (optional)
    rank_score DOUBLE,         -- For creating "Top N" universes
    PRIMARY KEY (ticker, month_start_date)
);
```

### B. Modified Pipeline Flow

**Current Flow:**
`DataCurator` -> `price_data` -> `FeatureEngineer` calculates features for ALL rows.

**New Flow:**
1.  **Discovery (Monthly):** `UniverseDiscovery` runs, populates `universe_constituents`.
2.  **Ingestion:** `DataCurator` downloads price/fundamentals for *newly discovered* tickers (including delisted ones).
3.  **Feature Computation (`feature_pipeline.py`):**
    - **Step 1:** Calculate *Lightweight Features* (Price, Volume, SMA) for *all* data.
    - **Step 2:** Join with `universe_constituents` to filter down to the "Active Universe" for that month.
    - **Step 3:** Calculate *Heavy Features* (Alphas, Relative Strength Ranks) *only* for the Active Universe.

## 3. Implementation Plan

### Phase 1: Foundation (Sprint 4)
1.  **Database Schema:** Create `universe_constituents` table.
2.  **`UniverseDiscovery` Class:**
    -   Implement `backfill_from_delisted()`: Use FMP Delisted endpoint to find tickers.
    -   Implement `fetch_live_candidates()`: Use FMP Screener.
3.  **Backfill Script:** Run `UniverseDiscovery` to populate 2000-2024 history.
    -   *Constraint:* We may not have perfect historical market cap. We will use "Price > $1 and Dollar Volume > $100k" as a proxy for the backfill if Market Cap is unavailable.

### Phase 2: Pipeline Integration (Sprint 5)
1.  **Refactor `feature_pipeline.py`:**
    -   Modify `compute_base_features` to accept a `universe_filter` flag.
    -   Ensure `rs_rating` is calculated against the *historical* universe (including delisted), not just the current survivor set.
2.  **Optimization:** Ensure DuckDB can handle the join efficiently (Partition by month?).

## 4. Verification
- **Survivorship Check:** Verify that known delisted companies (e.g., BBBY, SVB) are present in `universe_constituents` for their active periods and absent after.
- **Count Check:** Plot "Universe Size vs Time". It should be relatively stable (e.g., 2000-4000 tickers), not growing linearly with time (which would indicate accumulation of dead tickers).

## 5. Risk Assessment
- **FMP Data Quality:** Delisted data might be sparse. We will cross-reference with "Price > $0" checks.
- **Performance:** Joining `price_data` (20M rows) with `universe_constituents` (1M rows) needs to be optimized in DuckDB.
