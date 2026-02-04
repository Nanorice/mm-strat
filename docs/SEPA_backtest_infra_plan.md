# SEPA Hybrid Backtesting Implementation Plan

**Goal:** robust, event-driven backtest of the M01 (Selection) + M03 (Regime) strategy with complex 3-tranche exits.
**Stack:** Python, Pandas (Data Eng), Backtrader (Simulation).

---

## Phase 1: Data Engineering (The "Feeder")

Before initializing the backtester, we must prepare the efficient "Feed" datasets from your raw Parquets.

### Step 1: M03 Macro Feed Preparation
Create a unified timeline of the "Market State" that the strategy will consult daily.
* **Input:** Macro Parquets (VIX, Liquidity, Spreads).
* **Processing:**
    1.  Calculate M03 Score and Regime (0-4) for every date.
    2.  Shift data by 1 day (T+1) to prevent lookahead bias (Strategy on Tuesday sees Monday's macro).
* **Output:** `data/processed/m03_feed.csv`
    * Columns: `Date`, `Regime_Cat` (0-4), `Score`, `Risk_Pillar`, `Liq_Pillar`.

### Step 2: M01 Candidate Generation (The "Hydration")
Filter the universe to only relevant stocks to keep the backtest fast.
* **Input:** Stock Price Parquets + M01 Model (`.pkl`).
* **Processing:**
    1.  **Scoring:** Apply M01 Model to the entire universe for the backtest period.
    2.  **Filtering:** Identify every unique `(Ticker, Date)` tuple where `Score >= 70` in the simulated SEPA trades list.
    3.  **Expansion (Warm-up):** For every identified Ticker, pull OHLCV data for:
        * The Signal Date.
        * Plus the **future duration** of the trade (until exit).
        * Plus **250 days of history** prior to the signal (for SMA200/ATR calc).
* **Output:** A dictionary of DataFrames or a Multi-Index Parquet `data/processed/candidates_hydrated.parquet`.
    * Columns: `Date`, `Open`, `High`, `Low`, `Close`, `Volume`, `M01_Score`.

---

## Phase 2: Backtrader Infrastructure

### 1. Custom Data Classes
Define how Backtrader reads your specific column structures.

```python
class M03_MacroFeed(bt.feeds.PandasData):
    """
    Feeds the Regime State to the Strategy.
    """
    lines = ('regime', 'score', 'risk_pillar',)
    params = (
        ('regime', -1), # Column index for Regime (0-4)
        ('score', -1),  # Column index for M01 Score
        ('risk_pillar', -1),
    )

class SEPA_StockFeed(bt.feeds.PandasData):
    """
    Feeds Stock OHLCV + M01 Score.
    """
    lines = ('m01_score',)
    params = (
        ('m01_score', -1), # Column containing the pre-calc score
        ('ohlc', True),    # Standard OHLC columns
        ('volume', True),
    )