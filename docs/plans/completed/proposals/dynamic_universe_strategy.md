# Universe Management Strategy: Dynamic Point-in-Time Proposal

## 1. Problem Statement
The current universe system is **Static**, defined by the set of files present in `data/price/*.parquet`. This leads to:
*   **Survivorship Bias**: Failed companies are excluded from historical backtests.
*   **Market Drift**: The universe does not automatically add new listings (IPOs) or adapt to changing market caps.
*   **Look-Ahead Bias**: Filtering historical data based on *today's* market cap uses future information.

## 2. Proposed Solution: Dynamic Point-in-Time Universe
Transition to a system where the "Tradable Universe" is a function of time ($U_t$), defined by historical data available at that moment.

### A. Core Components

#### 1. Universe Discovery Module (`universe_discovery.py`)
Run on a monthly schedule (e.g., 1st of each month).
*   **Source**: FMP Screener API.
*   **Criteria (Tiered Approach)**:
    *   **Tier 1 (Core)**: Market Cap > $300M, Price > $5, Dollar Vol > $5M/day.
    *   **Tier 2 (Growth)**: Market Cap > $50M, Price > $2, Dollar Vol > $1M/day.
*   **Action**:
    *   Identify *new* tickers not in `PRICE_FOLDER`.
    *   Backfill full price history for these new tickers.
    *   Add them to `PRICE_FOLDER`, effectively adding them to the "Master Universe".

#### 2. Universe Construction (Point-in-Time)
A DuckDB-based dynamic view that reconstructs the valid universe for any date $T$.
```sql
CREATE VIEW v_tradable_universe AS
SELECT 
    date,
    ticker
FROM daily_features
WHERE 
    market_cap > 300000000  -- $300M cap at time T
    AND close > 5           -- Price > $5 at time T
    AND dollar_vol_20d > 2000000 -- Liquidity check at time T
```

#### 3. Handling Delisting
*   **Policy**: Never delete data for delisted/bankrupt companies.
*   **Implementation**: Mark them as `Active=False` in a metadata table but keep their price files.
*   **Backtesting**: Strategies will trade them until they fail the criteria (or price hits zero), accurately reflecting the risk.

### B. Implementation Plan (Next Sprint)

1.  **Create `UniverseDiscovery` Class**:
    *   Implement `fetch_candidates(criteria)` using FMP API.
    *   Implement `sync_to_storage()` to download missing history.
2.  **Backfill Historical Universe**:
    *   Use FMP's "Delisted Companies" endpoint to recover major failures from 2020-2024.
    *   Reconstruct the "Tradable Universe" for each month in the backtest period.
3.  **Update `data_curator`**:
    *   Integrate `UniverseDiscovery` as a monthly task.
    *   Add a `--discovery` flag to the CLI.

### C. Resource Considerations
*   **API Usage**: FMP (Paid) is required for bulk/historical data. Alpha Vantage/YFinance are insufficient due to rate limits.
*   **Storage**: DuckDB + Parquet handles the increased data volume (including delisted stocks) efficiently.

---
**Status**: Proposal Drafted
**Target**: Sprint 4 Implementation
