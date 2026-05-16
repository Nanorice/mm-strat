# Backtest Module Technical Reference

## 1. Overview
The **Backtest Module** (`src.backtest`) simulates the **SEPA Hybrid V1** strategy against historical market data. It handles data preparation, execution, and reporting.

### Responsibility
- **Data Engineering**: Transforms M01 scores, M03 regime signals, and price data into BackTrader feeds.
- **Simulation**: Runs SEPA Hybrid V1 strategy with event-driven logic (slippage, commission, regime gating).
- **State Management**: Tracks multi-tranche positions and trailing stops via a "Read-Model" architecture.
- **Reporting**: Generates performance metrics, plots, and trade logs.

### Key Dependencies
- **BackTrader**: Simulation engine.
- **Pandas/Parquet**: Data storage and manipulation.
- **M01 & M03 Modules**: Signal sources.

---

## 2. File Structure

Functional layers within `src/backtest/`:

| Component | File | Description |
|-----------|------|-------------|
| **Core** | `runner.py` | `SEPABacktestRunner` orchestrates execution. |
| | `sepa_strategy.py` | `SEPAHybridV1` BackTrader strategy class. |
| **Logic** | `position_tracker.py` | Manages position state (stops, tranches, targets). |
| | `score_lookup.py` | `ScoreLookup` index for daily M01 scores. |
| **Data** | `feeds.py` | `bt.feeds.PandasData` classes for Stock and Regime. |
| | `regime_feed.py` | Prepares M03 daily regime feed. |
| | `universe_scorer.py` | Batch-processes M01 scores. |
| | `price_feed.py` | Prepares OHLCV + ATR data for qualifying tickers. |
| **Reporting** | `report.py` | Generates text reports and plots. |
| | `trade_logger.py` | Logs trade events (`TradeLog`). |

---

## 3. Public Interface

### CLI Utility
Entry point: `scripts/run_backtest.py`.

```bash
# 1. Full Pipeline (Data Prep + Run)
python scripts/run_backtest.py --full --start 2020-01-01 --end 2025-01-01

# 2. Data Preparation Only
python scripts/run_backtest.py --prepare-data

# 3. Execution Only
python scripts/run_backtest.py --run --capital 100000

# 4. Quick Testing (50 tickers, no plot)
python scripts/run_backtest.py --run --max-tickers 50 --no-plot

# 5. Specific Tickers
python scripts/run_backtest.py --run --tickers NVDA,AMD,MSFT
```

### Python API

```python
from src.backtest import SEPABacktestRunner, prepare_regime_feed

# Data Prep
prepare_regime_feed(start_date="2020-01-01", end_date="2025-01-01")

# Execution
runner = SEPABacktestRunner(
    start_date='2020-01-01', 
    end_date='2025-01-01',
    initial_cash=100_000
)

# Setup
runner.setup(max_tickers=100) 

# Run
metrics = runner.run()

# Output
runner.print_results(metrics)
runner.save_report(metrics)
runner.plot(save_path='results/test_run.png')
```

---

## 4. Roadmap & Status

### Implemented
- **Data Pipeline**: Automated generation of `m03_feed`, `universe_scores`, and `prices/*.parquet`.
- **Hybrid Strategy**: M01 Selection + M03 Regime Gating.
- **Complex Exits**: 3-tranche scale-out with trailing stops.
- **Reporting**: Markdown reports and regime overlays.
- **State Safety**: "Read-Model" pattern for position management.

### Planned
- **Walk-Forward Optimization**: Parameter stability tests.
- **Monte Carlo Simulation**: Variance testing.
- **Transaction Cost Analysis**: Volume-weighted slippage models.
- **Comparison Benchmarks**: SPY buy-and-hold plots.

---

## 5. Implementation Rules

### Rule 1: "Read-Model" Pattern
**Do not mutate position state on Order Submission.**
`PositionTracker` must reflect **executed** orders only.
- Update state in `notify_order()` when `order.status == Completed`.
- Use `register_intent()` to store targets, but do not activate until confirmation.

### Rule 2: Regime-Gating
M03 Regime signal determines exposure.
- `Strong Bear (0)` triggers liquidation of all positions.
- New entries are gated by `regime_max_pos` limits.

### Rule 3: High-Water Mark Stops
Trailing stops do not move down.
- `current_stop = max(current_stop, calculated_new_stop, initial_hard_stop)`

### Rule 4: Data Isolation
- `universe_scorer.py`: No lookahead during standardization.
- `ScoreLookup`: Handle missing data/holidays without error.
