# Backtest Engine Architecture

The quantamental backtest infrastructure is designed to bridge machine learning model outputs (from `d2/t3` duckdb pipelines) with a rigorous historical trading simulation. 

It implements a two-tier architectural pattern:
1. **Vectorized Engine (`VectorizedSEPABacktest`)**: A pure Pandas/NumPy engine designed for extremely fast parameter sweeps and optimization.
2. **Event-Driven Engine (`SEPABacktestRunner` & `SEPAHybridV1`)**: A heavy, tick-by-tick Backtrader engine for production-grade validation, capital constraints, and complex position sizing.

---

## 1. Core Components

The architecture is modularized into `src/backtest/`:

### A. Data & Scoring Layer
- **`universe_scorer.py`**: The bridge to the ML pipeline. It queries the DuckDB feature store (`t3_sepa_features`), loads the production models (`m01` / `m02`), applies isotonic calibration, and outputs a flat dataframe of daily scores (`prob_elite`, percentile ranks) for all active SEPA candidates.
- **`score_lookup.py`**: A specialized lookup cache used by the Event-Driven engine to fetch the daily score of a ticker in $O(1)$ time during the Backtrader `next()` loop without querying the database.
- **`feeds.py`**: Custom data feed adapters for injecting DuckDB-sourced OHLCV data into Backtrader.

### B. Vectorized Engine (`vectorized_backtest.py`)
- **Purpose**: Rapid prototyping and Grid/Optuna optimization.
- **Mechanism**: Takes precomputed scores and precomputed prices, filters entries via vectorized masks (`prob_elite >= threshold`), ranks candidates daily to respect position caps, and then simulates holding periods via Pandas `merge` and `groupby` operations.
- **Exits Simulated**: 
  1. `stop_loss`: Intraday low breaches entry price * (1 - SL%).
  2. `trend_break`: Daily close drops below a trailing SMA (e.g. SMA50).
  3. `max_hold`: Timeout after $N$ days.
- **Tradeoffs**: Approx. 10x-100x faster than Backtrader. Ignores strict available capital (assumes you can always fill the slot) and complex multi-tranche exits.

### C. Event-Driven Engine (Backtrader)
- **`runner.py` (`SEPABacktestRunner`)**: The orchestration layer. It instantiates the Cerebro engine, loads data feeds, injects the `UniverseScorer` output, configures the strategy, and executes the run. It also handles artifact persistence (trades, equity curves, tearsheets).
- **`sepa_strategy.py` (`SEPAHybridV1`)**: The actual trading logic implementing the Minervini SEPA ruleset inside Backtrader's event loop.
  - **Entry Logic**: Validates model scores, enforces regime-based position caps (e.g. max 2 trades during Bear regime vs. 10 in Bull), and handles capital allocation.
  - **Exit Logic**: Tick-by-tick stop loss monitoring, moving average trailing stops, and scaling out of winners.
- **`position_tracker.py`**: Tracks active portfolio slots, margin, and exposure at the sector/industry level.

### D. Reporting Layer
- **`trade_logger.py`**: Emits standardized JSON logs for every trade entry/exit, facilitating debug tracebacks.
- **`analyzers.py`**: Custom Backtrader analyzers for computing SQN, Drawdowns, and custom risk metrics.
- **`report.py`**: Connects the output to `QuantStats` for rich HTML tearsheets and summary markdown files.

---

## 2. Execution Workflow

When running a backtest (e.g. via `scripts/run_strategy_array.py` or the future `scripts/run_strategy_optimizer.py`), the typical workflow is:

1. **Pre-computation**: `UniverseScorer` scans the DuckDB views and ML models for the specified date window to pre-calculate all candidate probabilities.
2. **Simulation**: 
   - *If optimizing*: `VectorizedSEPABacktest` is instantiated with the cache and rapidly tests parameter combinations (using Optuna).
   - *If evaluating*: `SEPABacktestRunner` injects the cache into `SEPAHybridV1` and simulates the time-series with full accounting constraints.
3. **Artifact Generation**: The output trades and daily equity arrays are pushed through the Reporting Layer to produce `trades.parquet`, `comparison.md`, and `tearsheet.html`.

---

## 3. Key Design Decisions & Future Scalability

* **Separation of Signal and Execution**: The ML models *never* trade. They only produce a calibrated probability score via `universe_scorer.py`. The strategy (`sepa_strategy.py`) is entirely responsible for deciding *if* that score warrants an entry based on current portfolio heat and regime.
* **Dual Engines**: The vectorized engine enables practical ML hyperparameter sweeps (Goal 5) which would be computationally impossible if forced to run through the Backtrader event loop.
* **DuckDB Centric**: All data is pulled from the local `.duckdb` cache, ensuring the backtest is completely decoupled from web APIs and network latency.
