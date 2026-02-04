# 07 - Backtest Infrastructure

**Strategy:** SEPA Hybrid V1 (Selection + Regime + Multi-Tranche Exit)
**Stack:** Python, Pandas (Data Eng), BackTrader (Simulation)

---

## Overview

The backtesting system implements an event-driven backtest for the **SEPA Hybrid V1** strategy, combining:

1. **M01 (Selection):** Technical ranking model identifies high-quality trade candidates
2. **M03 (Regime):** Macro regime filter gates exposure and sizes positions
3. **Execution:** 3-tranche scale-out with trailing stops

---

## Architecture

### Three-Phase Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│ PHASE 1: DATA PREPARATION                                       │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────────┐  ┌──────────────────┐  ┌───────────────┐  │
│  │ M03 Regime Feed  │  │ Universe Scores  │  │ Price Feeds   │  │
│  │ regime_feed.py   │  │ universe_scorer  │  │ price_feed.py │  │
│  └────────┬─────────┘  └────────┬─────────┘  └───────┬───────┘  │
│           │                     │                    │          │
│           ▼                     ▼                    ▼          │
│    m03_feed.parquet    universe_scores.parquet   prices/*.pqt   │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ PHASE 2: BACKTEST EXECUTION                                     │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌─────────────────┐  ┌─────────────────────┐ │
│  │ M03RegimeFeed│  │ SEPAStockFeed   │  │ ScoreLookup         │ │
│  │ (BackTrader) │  │ (BackTrader)    │  │ (In-Memory Index)   │ │
│  └──────┬───────┘  └────────┬────────┘  └──────────┬──────────┘ │
│         │                   │                      │            │
│         └─────────┬─────────┴──────────────────────┘            │
│                   ▼                                             │
│         ┌─────────────────────────────────┐                     │
│         │     SEPAHybridV1 Strategy       │                     │
│         │  ┌─────────────────────────┐    │                     │
│         │  │   PositionTracker       │    │                     │
│         │  │   (State Management)    │    │                     │
│         │  └─────────────────────────┘    │                     │
│         └─────────────────────────────────┘                     │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ PHASE 3: REPORTING                                              │
├─────────────────────────────────────────────────────────────────┤
│  ┌────────────────┐  ┌────────────────┐  ┌─────────────────┐    │
│  │ Metrics        │  │ Trade Log      │  │ Equity Curve    │    │
│  │ (Sharpe, DD)   │  │ (CSV/DataFrame)│  │ (PNG Plot)      │    │
│  └────────────────┘  └────────────────┘  └─────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

---

## File Structure

```
src/backtest/
├── __init__.py           # Package exports
├── runner.py             # Main orchestrator (SEPABacktestRunner)
├── sepa_strategy.py      # BackTrader strategy (SEPAHybridV1)
├── feeds.py              # Custom data feeds (SEPAStockFeed, M03RegimeFeed)
├── position_tracker.py   # Position state management (PositionTracker, SEPAPosition)
├── score_lookup.py       # O(1) candidate lookup (ScoreLookup)
├── regime_feed.py        # M03 regime data preparation
├── universe_scorer.py    # M01 vectorized scoring (UniverseScorer)
├── price_feed.py         # OHLCV + ATR preparation
├── trade_logger.py       # Trade record logging (TradeLogger, TradeLog)
└── report.py             # Markdown report generation

scripts/
└── run_backtest.py       # CLI entry point

data/backtest/            # Generated backtest data
├── m03_feed.parquet      # Daily regime states
├── universe_scores.parquet # Scored candidates
├── prices/               # Per-ticker OHLCV + ATR
│   ├── AAPL.parquet
│   ├── MSFT.parquet
│   └── ...
└── reports/              # Generated reports
```

---

## Strategy Definition

**Location:** `src/backtest/sepa_strategy.py`

### Entry Logic (Top N Competition)

The strategy uses **Top N Competition** instead of a percentile hard gate:

| Filter | Condition | Purpose |
|--------|-----------|---------|
| **Score Floor** | M01 score >= 30.0 | Absolute floor (very permissive) |
| **Regime Gate** | M03 regime > 0 | No entries in Strong Bear |
| **Cooldown** | 3 days after stop-out | Prevent whipsaw re-entries |
| **Liquidity** | Volume > $10M, Price > $5 | Avoid illiquid stocks |

**Selection:** Candidates are ranked by **10-day trailing percentile** and slots are filled with the best-ranked candidates. No percentile hard gate—regime controls exposure.

### Exit Logic (3-Tranche Scale-Out)

| Tranche | Trigger | Action | New Stop |
|---------|---------|--------|----------|
| **T1** | `Close >= Entry + MAX(3*ATR, 15%)` | Sell 33% | `Target1 - MAX(1*ATR, 5%)` |
| **T2** | `Close >= Target1 + 2*ATR` | Sell 33% | `Target2 - 1*ATR` |
| **T3** | `Close < SMA(50)` | Sell remaining | N/A |

**Additional Exits:**
- **Hard Stop:** `Entry - MAX(2*ATR, 10%)`
- **Regime Liquidation:** Sell all if regime drops to 0 (Strong Bear)
- **Trailing Logic:** Stops move UP only (high-water mark)

### Position Sizing (Regime-Based)

| Regime | Code | Position Size | Max Positions |
|--------|------|---------------|---------------|
| Strong Bear | 0 | 0% (No entries) | 0 |
| Bear | 1 | 2.5% | 4 |
| Neutral | 2 | 5.0% | 8 |
| Bull | 3 | 7.5% | 10 |
| Strong Bull | 4 | 10.0% | 12 |

---

## CLI Commands

### Full Syntax

```bash
python scripts/run_backtest.py [MODE] [OPTIONS]
```

### Modes (mutually exclusive)

| Mode | Description |
|------|-------------|
| `--full` | Prepare data + run backtest |
| `--prepare-data` | Prepare data only |
| `--run` | Run backtest only (default) |

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--start DATE` | 2020-01-01 | Start date (YYYY-MM-DD) |
| `--end DATE` | 2025-01-01 | End date (YYYY-MM-DD) |
| `--capital AMOUNT` | 100000 | Initial capital |
| `--max-tickers N` | None | Limit tickers (for testing) |
| `--no-plot` | False | Skip plot generation |
| `--save-plot PATH` | auto | Custom plot path (default: `data/backtest/plots/`) |
| `--verbose, -v` | False | Enable debug logging |
| `--no-report` | False | Skip markdown report |

**Note:** Plot is auto-saved by default to `data/backtest/plots/backtest_plot_TIMESTAMP.png`

### Examples

```bash
# Quick 50-ticker test (plot auto-saved)
python scripts/run_backtest.py --run --max-tickers 50

# Full pipeline with custom dates
python scripts/run_backtest.py --full --start 2021-01-01 --end 2023-12-31

# Data prep only (with 1-year warm-up buffer auto-added)
python scripts/run_backtest.py --prepare-data --start 2020-01-01

# Run without plot (faster)
python scripts/run_backtest.py --run --no-plot

# Save plot to custom location
python scripts/run_backtest.py --run --save-plot results/my_backtest.png

# Verbose mode for debugging
python scripts/run_backtest.py --run --max-tickers 10 -v
```

### Programmatic API

```python
from src.backtest import SEPABacktestRunner

runner = SEPABacktestRunner(
    start_date='2020-01-01',
    end_date='2025-01-01',
    initial_cash=100_000,
)
runner.setup(max_tickers=None)
metrics = runner.run()
runner.print_results(metrics)
runner.save_report(metrics)
runner.plot(save_path='results.png')
```

---

## Key Components

### 1. Data Feeds

**M03RegimeFeed** (`feeds.py`)
- Synthetic feed with daily regime state
- Lines: `regime_cat` (0-4), `composite_score`, `trend_pillar`, `liq_pillar`, `risk_pillar`
- T+1 lag applied (FRED publication delay)

**SEPAStockFeed** (`feeds.py`)
- Standard OHLCV + custom `atr` line
- 14-period exponential ATR pre-calculated

### 2. Score Lookup

**ScoreLookup** (`score_lookup.py`)
- In-memory index for O(1) date-based queries
- Builds: `date → {ticker: (score, pct_rank)}` mapping
- Gracefully handles holidays/gaps

### 3. Position Tracker

**PositionTracker** (`position_tracker.py`)
- READ-MODEL: state mutates only via order notifications
- Tracks: entry → partial exits → closure lifecycle
- Manages: cooldowns, trailing stops, tranche progression

**SEPAPosition** (dataclass)
- Entry details: price, shares, date, ATR
- Tranche state: `tranche1_sold`, `tranche2_sold`
- Stop tracking: `current_stop`, `high_water_mark`
- Exit tracking: `max_target_hit`, `effective_exit_reason`

### 4. Analyzers

Attached via BackTrader:
- **SharpeRatio** (annualized)
- **DrawDown** (max %, max length)
- **TradeAnalyzer** (won/lost/pnl)
- **Returns** (average return)
- **SQN** (System Quality Number)

---

## Design Patterns

### READ-MODEL Synchronization

```
Strategy.next()                     PositionTracker
     │                                    │
     ├─── submit_order() ───────────────► │ register_intent()
     │                                    │
     │    [BackTrader processes order]    │
     │                                    │
     └─── notify_order(Completed) ──────► │ confirm_entry()
                                          │ record_partial_exit()
```

State changes happen ONLY when orders are **Completed**, not Submitted.

### High-Water Mark Stop Logic

```
Entry ────► Stop = Entry - MAX(2*ATR, 10%)
           │
           ▼
T1 Hit ───► Stop = MAX(current_stop, T1 - MAX(1*ATR, 5%))
           │
           ▼
T2 Hit ───► Stop = MAX(current_stop, T2 - 1*ATR)
```

Stops only move UP, never down.

### Effective Exit Reason

Positions may hit targets then exit via stop (trailing profit):

| Exit Reason | Meaning |
|-------------|---------|
| `target1` | Exited at T1 |
| `target2` | Exited at T2 |
| `target1_then_stop` | Hit T1, later stopped |
| `target2_then_stop` | Hit T2, later stopped |
| `stop` | Pure stop-out |
| `trend` | SMA(50) breakdown |

---

## Data Schema

### m03_feed.parquet

| Column | Type | Description |
|--------|------|-------------|
| date (index) | datetime | Trading date |
| regime_cat | int | 0-4 (strong_bear to strong_bull) |
| composite_score | float | 0-100 |
| trend_pillar | float | 0-100 |
| liq_pillar | float | 0-100 |
| risk_pillar | float | 0-100 |

### universe_scores.parquet

| Column | Type | Description |
|--------|------|-------------|
| date | datetime | Trading date |
| ticker | str | Stock symbol |
| normalized_score | float | 0-100 (linear-scaled calibrated score) |
| daily_pct_rank | float | 0-1 (rank within day's universe) |
| trailing_10d_pct | float | 0-1 (rank vs past 10 trading days' cohort) |

### prices/*.parquet

| Column | Type | Description |
|--------|------|-------------|
| date (index) | datetime | Trading date |
| open, high, low, close | float | OHLC prices |
| volume | int | Daily volume |
| atr_14 | float | 14-period EMA of True Range |

---

## Modifying the Strategy

The strategy is parameterized for easy customization. Below are common modifications.

### Example 1: Tighten Entry Filter (Top 10% Only)

```python
# In runner.py or when creating strategy
cerebro.addstrategy(
    SEPAHybridV1,
    min_percentile=0.90,  # Require top 10% trailing rank
)
```

### Example 2: Use Daily Ranking Instead of Trailing

```python
cerebro.addstrategy(
    SEPAHybridV1,
    rank_by='daily',  # Single-day cross-sectional rank
)
```

### Example 3: More Aggressive Position Sizing

```python
cerebro.addstrategy(
    SEPAHybridV1,
    regime_sizes={0: 0.0, 1: 0.05, 2: 0.075, 3: 0.10, 4: 0.125},
    regime_max_pos={0: 0, 1: 6, 2: 10, 3: 12, 4: 15},
)
```

### Example 4: Tighter Stops, Earlier Profit Taking

```python
cerebro.addstrategy(
    SEPAHybridV1,
    atr_stop_mult=1.5,      # Tighter initial stop (1.5*ATR vs 2.0)
    max_stop_pct=0.08,      # Max 8% stop (vs 10%)
    atr_target1_mult=2.0,   # T1 at 2*ATR (vs 3*ATR)
    min_target1_pct=0.10,   # T1 min 10% (vs 15%)
)
```

### Example 5: Disable Cooldown

```python
cerebro.addstrategy(
    SEPAHybridV1,
    cooldown_days=0,  # No cooldown after stop-out
)
```

### Example 6: Change Trend Exit Period

```python
cerebro.addstrategy(
    SEPAHybridV1,
    sma_exit_period=20,  # Use SMA(20) for trend exit (vs SMA(50))
)
```

### Parameter Reference

| Parameter | Default | Description |
|-----------|---------|-------------|
| `min_score` | 30.0 | Absolute score floor (0-100) |
| `min_percentile` | 0.0 | Percentile gate (0.0 = no gate) |
| `rank_by` | 'trailing' | 'trailing' or 'daily' |
| `cooldown_days` | 3 | Days to wait after stop-out |
| `atr_stop_mult` | 2.0 | ATR multiplier for initial stop |
| `max_stop_pct` | 0.10 | Maximum stop loss % |
| `atr_target1_mult` | 3.0 | ATR multiplier for T1 |
| `min_target1_pct` | 0.15 | Minimum T1 % |
| `atr_target2_add` | 2.0 | ATR to add for T2 |
| `sma_exit_period` | 50 | SMA period for trend exit |

---

## Report & Diagnostics

### Markdown Report Sections

The auto-generated report (`data/backtest/reports/`) includes:

1. **Overview**: Period, capital, total return
2. **Performance Metrics**: Sharpe, SQN, drawdown
3. **Trade Statistics**: Win rate, won/lost counts
4. **Trade Analysis**:
   - Exit reasons breakdown
   - Performance by entry regime
   - Holding period stats
   - Win/Loss analysis with profit factor
5. **Forensic Logs**:
   - **Worst 5 Trades**: Diagnose outlier losses (e.g., -27% gap downs)
   - **Best 5 Trades**: Identify what worked
   - **Transaction Costs**: Commission + fee drag estimate
6. **Exposure & Efficiency**:
   - Avg/Max Exposure %
   - Time Invested %
   - Avg Position Count
   - Cash drag warnings
7. **Rolling Metrics**:
   - Rolling 6-month Sharpe (current, avg, min, max)
   - Consistency % (periods with negative Sharpe)
8. **Signal Rejection Analysis**:
   - Total rejections by reason (no_slots, cooldown, already_holding, low_liquidity, etc.)
   - Capacity constraint warnings
9. **Methodology**: Strategy parameters documented

### Plot Panels (3x2 Grid)

1. **Equity Curve with Regime Overlay**: Background colors show M03 regime
2. **Underwater Plot**: Drawdown depth over time (V-shape vs U-shape recovery)
3. **Monthly Returns Heatmap**: Year x Month grid for seasonality
4. **Individual Trade PnL**: Bar chart with 10% stop line
5. **Performance by Regime**: Avg PnL per entry regime
6. **Exit Reasons**: Pie chart breakdown

### Diagnosing Outlier Losses

If you see a loss exceeding 10% (the hard stop):

1. Check **Worst Trades** section in report
2. Likely causes:
   - **Gap Down**: Earnings disaster, stock opened -20% below stop
   - **Regime Liquidation**: M03 flipped to Strong Bear, forced market sell into crash
   - **Bug**: Stop not properly enforced (check `position_tracker.py`)

---

## Implementation Status

### Completed

- [x] Data preparation pipeline (regime, scores, prices)
- [x] BackTrader integration & custom feeds
- [x] 3-tranche exit logic with trailing stops
- [x] Regime-based position sizing & gating
- [x] PositionTracker state management
- [x] Order notification synchronization
- [x] Markdown report generation
- [x] CLI interface with flexible options
- [x] Analyzer suite (Sharpe, SQN, drawdown, trades)
- [x] Matplotlib visualization
- [x] 10-day trailing percentile (cohort ranking)
- [x] Top N Competition entry mode (no percentile hard gate)
- [x] Forensic logs (worst/best trades, fee totals)
- [x] Visual diagnostics (underwater, monthly heatmap, regime overlay)
- [x] Auto-save plot to `data/backtest/plots/`
- [x] Exposure metrics (avg/max exposure, time invested, position count)
- [x] Rolling 6-month Sharpe ratio
- [x] Signal rejection tracking & analysis

### Not Yet Implemented

- [ ] Walk-forward optimization
- [ ] Parameter sensitivity analysis
- [ ] Monte Carlo simulation
- [ ] Benchmark comparison (SPY buy-and-hold)
- [ ] Transaction cost optimization
- [ ] Multi-period regime switching analysis
- [ ] Export to QuantStats reports

---

## Original Plan vs Execution

### Phase 1: Data Engineering

| Planned | Status | Notes |
|---------|--------|-------|
| M03 macro feed with T+1 lag | ✅ | `regime_feed.py` |
| M01 candidate hydration | ✅ | `universe_scorer.py` (vectorized) |
| 250-day warm-up buffer | ✅ | Auto-added in CLI |
| OHLCV + ATR preparation | ✅ | `price_feed.py` |

### Phase 2: BackTrader Infrastructure

| Planned | Status | Notes |
|---------|--------|-------|
| Custom M03_MacroFeed | ✅ | `M03RegimeFeed` in `feeds.py` |
| Custom SEPA_StockFeed | ✅ | `SEPAStockFeed` in `feeds.py` |
| 3-tranche exit logic | ✅ | `sepa_strategy.py` |
| Regime-based sizing | ✅ | Dynamic based on `regime_cat` |
| Trailing stops | ✅ | High-water mark logic |
| Cooldown logic | ✅ | 3-day wait after stop-out |

### Strategy Spec vs Implementation

| Spec | Implemented | Delta |
|------|-------------|-------|
| Hard floor score > 70 | score >= 30 | Relaxed for more signals |
| Top 5th percentile | Top N Competition | Changed to ranking metric (no hard gate) |
| Daily percentile | 10-day trailing | Rolling cohort for persistent strength |
| Hard stop: 2*ATR or 10% | MAX(2*ATR, 10%) | Matches spec |
| T1: 3*ATR or 15% | MAX(3*ATR, 15%) | Matches spec |
| T2: T1 + 2*ATR | T1 + 2*ATR | Matches spec |
| T3: Close < SMA(50) | Close < SMA(50) | Matches spec |
| Regime 0 liquidation | All positions sold | Matches spec |

---

## Broker Configuration

| Setting | Value |
|---------|-------|
| Commission | $0.005 per share |
| Slippage | 0.1% (percentage-based) |
| Execution | Next Open (no lookahead) |
| Data Resolution | Daily |
| Warm-Up Period | 250 days (auto-buffered) |

---

## References

- Strategy Spec: [[SEPA_strategy_v1.md]]
- Infrastructure Plan: [[SEPA_backtest_infra_plan.md]]
- M01 Model: [[03_M01_Trainer.md]]
- M03 Regime: [[06_M03_Regime.md]]
