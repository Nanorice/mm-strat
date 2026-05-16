# Module Passport: Daily Scanner

## 1. Overview
**Responsibility:**  
The `daily_scanner` module is the core operational engine for the trading system. It is responsible for scanning the stock universe daily (or over a date range) to identify buy signals based on the SEPA strategy, scoring them with Machine Learning models (M01/M02), and managing the "Buy List" via database interaction. It acts as the bridge between raw data, strategy logic, and actionable trade signals.

**Key Dependencies:**
*   **`src.strategy.SEPAStrategy`**: Core SEPA logic for single-day scanning.
*   **`src.vectorized_screening`**: High-performance vectorized SEPA logic for 2D date-range scanning.
*   **`src.pipeline`**: Provides `ProductionScorer` (ML) and `M03RegimeCalculator`.
*   **`src.data_engine`**: Handles data retrieval and caching.
*   **`src.database`**: Manages persistence of the Buy List.
*   **`data_curator`**: External script used for data updates (fundamentals/macro).

## 2. File Structure

| File Path | Purpose |
| :--- | :--- |
| `daily_scanner.py` | **Entry Point**. CLI orchestrator. Handles daily workflow: Universe -> Cache -> Scan -> ML Score -> DB Update. |
| `src/vectorized_screening.py` | **Core Logic**. Implements vectorized SEPA screening (C1-C11) using numpy/pandas for finding signals across valid date ranges efficiently. |

## 3. Data Schemas

### Buy List Database Columns (Updated)
The module updates the `buy_list` table with the following key columns:

| Column | Type | Description |
| :--- | :--- | :--- |
| `signal_price` | `REAL` | Entry price (Close or calculated entry). |
| `m01_expected_return` | `REAL` | M01 Model Output (Regression). |
| `m02_loser_proba` | `REAL` | M02 Model Output (Probability of being a loser). |
| `m02_survival` | `REAL` | `1 - m02_loser_proba`. |
| `final_score` | `REAL` | **Primary Ranking Metric**. Formula: `M01_Adj * M02_Survival`. |
| `final_score_rank` | `INTEGER` | Rank within the active buy list based on `final_score`. |
| `m03_regime_score` | `REAL` | M03 Market Regime Score (0-100). |
| `m03_regime_category` | `TEXT` | Regime Category (e.g., 'Risk On', 'Neutral'). |

### ML Candidates DataFrame
DataFrame prepared for `ProductionScorer`:
*   **Identification**: `ticker`, `date`.
*   **Features**: OHLCV data, `alpha001`...`alpha101` (from AlphaEngine), fundamental columns (merged via `FundamentalMerger`).

## 4. Implementation Rules ("The Secret Sauce")

### Stop Loss & Take Profit
*   **Stop Loss**: `Close - (config.BARRIER_K_SL * ATR)`
*   **Take Profit**: `Close * (1 + MAX(config.BARRIER_MIN_TP, config.BARRIER_K_TP * ATR_PCT))`

### ML Scoring Logic (M02 Integration)
*   **Formula**: `Final_Score = M01_Vol_Adj × (1 - P(loser))`
    *   `M01_Vol_Adj`: M01 expected return adjusted for volatility.
    *   `P(loser)`: Probability from M02 Loser Detector.
*   **Goal**: Maximize return while minimizing the probability of a "loser" trade.

### Market Regime Gating (M03)
*   **Longs Blocked**: If `m03_score < config.M03_LONG_ALLOW_MIN`.
*   **Reduced Sizing**: If `m03_score < config.M03_LONG_REDUCED_MIN`.
*   **Behavior**: If gating is active (`allow_longs=False`), new signals are **discarded** before being added to the database.

### Scanner Workflow
1.  **Backward Scan Protection**: Detects if `scan_date` is earlier than existing signals. If so, clears future signals to maintain temporal consistency.
2.  **Vectorized SEPA (Date Range Mode)**:
    *   **Trend Conditions (C1-C8)**: SMA alignments (50>150>200), Price > SMAs, 52W High/Low proximity.
    *   **Breakout Conditions (C9-C11)**:
        *   Price > Max High of `consolidation_period`.
        *   Volume > 50-day SMA.
        *   RS > 63-day SMA.
    *   **Transitions**: Detects `0 -> 1` transitions (False to True) to define "New Triggers".

## 5. Public Interface

### `daily_scanner.py` (CLI)
*   `--scan-date YYYY-MM-DD`: Run for a specific single date.
*   `--date-range START END`: Run vectorized scan over a range.
*   `--use-ml`: Enable M01/M02 scoring.
*   `--csv-output`: Export results to CSV.

### `src.vectorized_screening.VectorizedSEPAScreener`
| Method | Description |
| :--- | :--- |
| `screen_single_ticker(df)` | Returns boolean Series (True=SEPA Qualified) for entire history. |
| `batch_screen_universe(data, date)` | Returns lists: `trend_ok`, `breakout`, `new_triggers`. |
| `build_2d_matrix(data, start, end)` | Constructs the master 2D DataFrame for vectorized operations. |
