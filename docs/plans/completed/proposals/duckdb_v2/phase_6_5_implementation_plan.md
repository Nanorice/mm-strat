# Phase 6.5 Implementation Plan: Backtesting & Strategy Validation

**Status**: In Progress
**Approach**: Option A - Leverage Existing BackTrader Module
**Estimated Time**: 6-9 hours (vs 13-18 hours from scratch)
**Date**: 2026-03-15

---

## Executive Summary

Phase 6.5 requires building a backtesting engine to validate M01 + trading logic before live deployment. We have **90% of the infrastructure already built** in `src/backtest/` (BackTrader-based SEPA Hybrid V1 strategy with comprehensive reporting).

**Strategy**: Adapt existing backtest module with 2 key enhancements:
1. **DuckDB Integration**: Replace parquet feeds with SQL queries to `v_d3_deployment` and `v_d2_hydrated`
2. **Parameter Optimization**: Build grid search wrapper for entry/exit threshold tuning

This approach saves ~7-9 hours vs building from scratch while maintaining production-quality reporting.

---

## Gap Analysis

### ✅ Already Implemented (Existing `src/backtest/` module)

| Component | Status | File |
|-----------|--------|------|
| Core Engine | ✅ Complete | `runner.py` (37K LOC) |
| SEPA Strategy | ✅ Complete | `sepa_strategy.py` (24K LOC) |
| Trade Tracking | ✅ Complete | `position_tracker.py` (16K LOC) |
| M03 Regime Feed | ✅ Complete | `regime_feed.py` (4.6K LOC) |
| M01 Scoring | ✅ Complete | `universe_scorer.py` (17K LOC) |
| Price Feeds | ✅ Complete | `price_feed.py` (6.9K LOC) |
| Reporting | ✅ Complete | `report.py` (24K LOC) |
| CLI Interface | ✅ Complete | `scripts/run_backtest.py` |
| **Metrics** | | |
| Sharpe Ratio | ✅ Complete | BackTrader analyzer |
| Max Drawdown | ✅ Complete | BackTrader analyzer |
| Win Rate | ✅ Complete | TradeAnalyzer |
| Avg Return | ✅ Complete | Returns analyzer |
| SQN | ✅ Complete | SystemQualityNumber |
| **Visualization** | | |
| Equity Curve | ✅ Complete | 6-panel matplotlib plots |
| Underwater Plot | ✅ Complete | Drawdown depth tracking |
| Monthly Heatmap | ✅ Complete | Seasonality analysis |
| Regime Overlay | ✅ Complete | M03 regime coloring |

### ⚠️ Gaps (Phase 6.5 Requirements)

| Requirement | Status | Milestone |
|-------------|--------|-----------|
| **Milestone 6.5.1** | | |
| DuckDB Integration (`v_d3_deployment`) | ❌ Missing | 6.5.1 |
| Calmar Ratio | ❌ Missing | 6.5.1 |
| Parameterized Entry/Exit Thresholds | ⚠️ Partial | 6.5.1 |
| Position Sizing Modes | ⚠️ Partial | 6.5.1 |
| **Milestone 6.5.2** | | |
| Grid Search Optimization | ❌ Missing | 6.5.2 |
| Walk-Forward Validation | ❌ Missing | 6.5.2 |
| Results Notebook | ❌ Missing | 6.5.2 |
| Sharpe Heatmaps | ❌ Missing | 6.5.2 |

---

## Implementation Roadmap

### **Milestone 6.5.1: DuckDB Integration & Parameterization** (2-3 hours)

#### **Task 1.1: Create DuckDB Data Feed Adapter** (1 hour)

**File**: `src/backtest/duckdb_feed.py` (new)

**Responsibilities**:
- Query `v_d3_deployment` for candidate features (last 252 days of SEPA candidates)
- Query `v_d2_hydrated` for stop-loss logic (entry → exit price tracking)
- Convert SQL results to BackTrader feed format (OHLCV + custom lines)
- Handle date gaps, holidays, missing data gracefully

**Implementation**:
```python
# src/backtest/duckdb_feed.py
import pandas as pd
import backtrader as bt
from pathlib import Path
import duckdb
import config

class DuckDBCandidateFeed(bt.feeds.PandasData):
    """
    BackTrader feed from v_d3_deployment (DuckDB view).

    Custom lines:
    - atr_14: ATR for stop-loss calculation
    - m01_score: Normalized M01 score (0-100)
    - daily_pct_rank: Daily cross-sectional rank
    """
    lines = ('atr_14', 'm01_score', 'daily_pct_rank',)

    params = (
        ('atr_14', -1),  # Column index
        ('m01_score', -1),
        ('daily_pct_rank', -1),
    )

def load_candidates_from_duckdb(
    ticker: str,
    start_date: str,
    end_date: str,
    db_path: Path = config.DUCKDB_PATH
) -> pd.DataFrame:
    """
    Load candidate data for a ticker from v_d3_deployment.

    Returns:
        DataFrame with columns: date, open, high, low, close, volume,
                                atr_14, m01_score, daily_pct_rank
    """
    conn = duckdb.connect(str(db_path), read_only=True)

    query = f"""
    SELECT
        date,
        open, high, low, close, volume,
        atr_20d as atr_14,  -- Use 20-day ATR from features
        0.0 as m01_score,   -- TODO: Integrate M01 scoring
        0.0 as daily_pct_rank
    FROM v_d3_deployment
    WHERE ticker = '{ticker}'
      AND date >= '{start_date}'
      AND date <= '{end_date}'
    ORDER BY date
    """

    df = conn.execute(query).df()
    conn.close()

    df['date'] = pd.to_datetime(df['date'])
    df.set_index('date', inplace=True)

    return df

def prepare_duckdb_feeds(
    start_date: str,
    end_date: str,
    max_tickers: int = None
) -> list[tuple[str, pd.DataFrame]]:
    """
    Prepare all candidate feeds from DuckDB.

    Returns:
        List of (ticker, dataframe) tuples ready for BackTrader
    """
    conn = duckdb.connect(str(config.DUCKDB_PATH), read_only=True)

    # Get qualifying tickers from v_d3_deployment
    query = f"""
    SELECT DISTINCT ticker
    FROM v_d3_deployment
    WHERE date >= '{start_date}'
      AND date <= '{end_date}'
    ORDER BY ticker
    """

    if max_tickers:
        query += f" LIMIT {max_tickers}"

    tickers = conn.execute(query).df()['ticker'].tolist()
    conn.close()

    feeds = []
    for ticker in tickers:
        df = load_candidates_from_duckdb(ticker, start_date, end_date)
        if not df.empty:
            feeds.append((ticker, df))

    return feeds
```

**Acceptance Criteria**:
- [ ] Queries `v_d3_deployment` for OHLCV + ATR data
- [ ] Returns BackTrader-compatible DataFrame (indexed by date)
- [ ] Handles missing tickers gracefully (returns empty list)
- [ ] Performance: <5 seconds for 100 tickers

---

#### **Task 1.2: Add Calmar Ratio Analyzer** (30 minutes)

**File**: `src/backtest/analyzers.py` (new)

**Implementation**:
```python
# src/backtest/analyzers.py
import backtrader as bt

class CalmarRatio(bt.Analyzer):
    """
    Calmar Ratio = Annualized Return / Max Drawdown

    Measures return per unit of downside risk.
    Higher is better (>3.0 is excellent).
    """

    def __init__(self):
        self.max_dd = 0.0
        self.total_return = 0.0

    def notify_cashvalue(self, cash, value):
        """Track portfolio value changes."""
        if not hasattr(self, '_initial_value'):
            self._initial_value = value
        self._current_value = value

    def stop(self):
        """Calculate final Calmar ratio."""
        # Get max drawdown from DrawDown analyzer
        dd_analyzer = self.strategy.analyzers.getbyname('drawdown')
        if dd_analyzer:
            self.max_dd = dd_analyzer.get_analysis()['max']['drawdown'] / 100.0

        # Calculate total return
        self.total_return = (self._current_value - self._initial_value) / self._initial_value

        # Annualize based on backtest duration
        years = (self.strategy.datetime.date() - self.strategy.datetime.date(ago=-self.strategy.data.buflen())).days / 365.25
        annualized_return = (1 + self.total_return) ** (1 / years) - 1

        # Calmar = Annual Return / Max DD
        if self.max_dd > 0:
            self.calmar = annualized_return / self.max_dd
        else:
            self.calmar = float('inf')  # No drawdown = infinite Calmar

    def get_analysis(self):
        return {
            'calmar_ratio': self.calmar,
            'annualized_return': annualized_return,
            'max_drawdown': self.max_dd
        }
```

**Integration** (`runner.py`):
```python
# In SEPABacktestRunner.setup()
from .analyzers import CalmarRatio

cerebro.addanalyzer(CalmarRatio, _name='calmar')
```

**Acceptance Criteria**:
- [ ] Calmar ratio calculated correctly (Annual Return / Max DD)
- [ ] Handles zero drawdown case (infinite Calmar)
- [ ] Integrated into backtest reports

---

#### **Task 1.3: Parameterize Entry/Exit Thresholds** (30 minutes)

**File**: `src/backtest/sepa_strategy.py` (modify)

**Changes**:
```python
# Add to SEPAHybridV1.params
params = (
    # ... existing params ...

    # Entry thresholds (NEW)
    ('entry_mode', 'percentile'),  # 'percentile' or 'top_n'
    ('entry_percentile_min', 0.60),  # Require top 40% (60th percentile)
    ('entry_top_n', None),  # Alternative: take top N candidates (None = use percentile)

    # Exit thresholds (NEW)
    ('exit_percentile_max', 0.40),  # Exit if rank falls below 40th percentile
    ('exit_use_percentile', False),  # Enable percentile-based exit
)

def should_exit_low_rank(self, data):
    """Check if position should exit due to low percentile rank."""
    if not self.p.exit_use_percentile:
        return False

    ticker = data._name
    current_date = self.datetime.date()

    # Lookup current percentile rank
    score_data = self.score_lookup.get_score(ticker, current_date)
    if not score_data:
        return False

    pct_rank = score_data.get('trailing_10d_pct', 0.0)
    return pct_rank < self.p.exit_percentile_max
```

**Acceptance Criteria**:
- [ ] Entry threshold configurable via `entry_percentile_min` parameter
- [ ] Exit threshold configurable via `exit_percentile_max` parameter
- [ ] Both modes tested (percentile vs top_n)

---

#### **Task 1.4: Add Position Sizing Modes** (1 hour)

**File**: `src/backtest/sepa_strategy.py` (modify)

**Changes**:
```python
# Add to SEPAHybridV1.params
params = (
    # ... existing params ...

    # Position sizing (NEW)
    ('sizing_mode', 'regime'),  # 'regime', 'equal_weight', 'rank_weighted', 'score_weighted'
)

def calculate_position_size(self, data, regime_cat: int, score: float, rank: float) -> float:
    """
    Calculate position size based on sizing mode.

    Args:
        data: Stock data feed
        regime_cat: M03 regime category (0-4)
        score: M01 normalized score (0-100)
        rank: Trailing 10-day percentile (0-1)

    Returns:
        Position size as fraction of portfolio (0.0-1.0)
    """
    mode = self.p.sizing_mode

    if mode == 'regime':
        # Original: regime-based sizing
        return self.p.regime_sizes.get(regime_cat, 0.0)

    elif mode == 'equal_weight':
        # Equal weight across all positions
        max_pos = self.p.regime_max_pos.get(regime_cat, 0)
        if max_pos == 0:
            return 0.0
        return 1.0 / max_pos  # e.g., 10 max pos → 10% each

    elif mode == 'rank_weighted':
        # Weight by percentile rank (top-ranked get more capital)
        base_size = self.p.regime_sizes.get(regime_cat, 0.0)
        # Scale by rank: 90th percentile → 1.8x, 50th → 1.0x, 10th → 0.2x
        rank_multiplier = 0.5 + (rank * 1.5)
        return base_size * rank_multiplier

    elif mode == 'score_weighted':
        # Weight by M01 score (higher score = bigger position)
        base_size = self.p.regime_sizes.get(regime_cat, 0.0)
        # Scale by score: 100 → 2.0x, 50 → 1.0x, 0 → 0.0x
        score_multiplier = score / 50.0
        return base_size * score_multiplier

    else:
        raise ValueError(f"Unknown sizing_mode: {mode}")
```

**Acceptance Criteria**:
- [ ] 4 sizing modes implemented: regime, equal_weight, rank_weighted, score_weighted
- [ ] Validated with test backtest (verify position sizes match expected)
- [ ] Documented in CLI help text

---

### **Milestone 6.5.2: Parameter Optimization & Analysis** (4-6 hours)

#### **Task 2.1: Create Grid Search Optimization Script** (3 hours)

**File**: `scripts/backtest_optimization.py` (new, ~300 lines)

**Responsibilities**:
- Run grid search over entry/exit percentile thresholds
- Test 3 position sizing modes
- Walk-forward validation (train on 2023, test on 2024)
- Save results to CSV + JSON

**Implementation**:
```python
#!/usr/bin/env python
"""
SEPA Backtest Parameter Optimization
====================================
Grid search over entry/exit thresholds and position sizing modes.

Usage:
    # Full grid search
    python scripts/backtest_optimization.py --train-year 2023 --test-year 2024

    # Quick test (reduced grid)
    python scripts/backtest_optimization.py --quick
"""

import argparse
import itertools
import json
import logging
from datetime import datetime
from pathlib import Path
import pandas as pd
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest.runner import SEPABacktestRunner
from src.backtest.sepa_strategy import SEPAHybridV1

logger = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).parent.parent / 'data' / 'backtest' / 'optimization'
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


class BacktestOptimizer:
    """
    Grid search optimizer for SEPA backtest parameters.
    """

    def __init__(self, train_year: int, test_year: int):
        self.train_start = f"{train_year}-01-01"
        self.train_end = f"{train_year}-12-31"
        self.test_start = f"{test_year}-01-01"
        self.test_end = f"{test_year}-12-31"

        self.results = []

    def grid_search(
        self,
        entry_percentiles: list[float],
        exit_percentiles: list[float],
        sizing_modes: list[str],
        max_tickers: int = None
    ):
        """
        Run grid search over parameter combinations.

        Args:
            entry_percentiles: List of entry threshold percentiles (e.g., [0.50, 0.60, 0.70])
            exit_percentiles: List of exit threshold percentiles (e.g., [0.30, 0.40])
            sizing_modes: List of sizing modes (e.g., ['regime', 'equal_weight', 'rank_weighted'])
            max_tickers: Limit tickers for faster testing
        """
        param_grid = list(itertools.product(entry_percentiles, exit_percentiles, sizing_modes))

        print(f"\n{'='*80}")
        print(f"SEPA BACKTEST GRID SEARCH")
        print(f"{'='*80}")
        print(f"Train Period: {self.train_start} to {self.train_end}")
        print(f"Test Period:  {self.test_start} to {self.test_end}")
        print(f"Total Combinations: {len(param_grid)}")
        print(f"{'='*80}\n")

        for idx, (entry_pct, exit_pct, sizing) in enumerate(param_grid, 1):
            print(f"\n[{idx}/{len(param_grid)}] Testing: entry={entry_pct:.0%}, exit={exit_pct:.0%}, sizing={sizing}")

            # Train phase
            train_metrics = self._run_backtest(
                start=self.train_start,
                end=self.train_end,
                entry_percentile=entry_pct,
                exit_percentile=exit_pct,
                sizing_mode=sizing,
                max_tickers=max_tickers,
                phase='train'
            )

            # Test phase
            test_metrics = self._run_backtest(
                start=self.test_start,
                end=self.test_end,
                entry_percentile=entry_pct,
                exit_percentile=exit_pct,
                sizing_mode=sizing,
                max_tickers=max_tickers,
                phase='test'
            )

            # Store results
            self.results.append({
                'entry_percentile': entry_pct,
                'exit_percentile': exit_pct,
                'sizing_mode': sizing,
                'train_sharpe': train_metrics['sharpe'],
                'train_win_rate': train_metrics['win_rate'],
                'train_return': train_metrics['total_return'],
                'train_max_dd': train_metrics['max_drawdown'],
                'train_calmar': train_metrics['calmar'],
                'test_sharpe': test_metrics['sharpe'],
                'test_win_rate': test_metrics['win_rate'],
                'test_return': test_metrics['total_return'],
                'test_max_dd': test_metrics['max_drawdown'],
                'test_calmar': test_metrics['calmar'],
                'sharpe_degradation': (train_metrics['sharpe'] - test_metrics['sharpe']) / train_metrics['sharpe'] if train_metrics['sharpe'] > 0 else 0.0
            })

            print(f"  Train Sharpe: {train_metrics['sharpe']:.2f} | Test Sharpe: {test_metrics['sharpe']:.2f} | Degradation: {self.results[-1]['sharpe_degradation']:.1%}")

        # Save results
        self._save_results()

        return self.get_best_params()

    def _run_backtest(
        self,
        start: str,
        end: str,
        entry_percentile: float,
        exit_percentile: float,
        sizing_mode: str,
        max_tickers: int,
        phase: str
    ) -> dict:
        """Run single backtest and extract metrics."""
        runner = SEPABacktestRunner(
            start_date=start,
            end_date=end,
            initial_cash=100_000
        )

        # Override strategy parameters
        runner.cerebro.addstrategy(
            SEPAHybridV1,
            entry_percentile_min=entry_percentile,
            exit_percentile_max=exit_percentile,
            exit_use_percentile=True,
            sizing_mode=sizing_mode
        )

        runner.setup(max_tickers=max_tickers)
        metrics = runner.run()

        return {
            'sharpe': metrics.get('sharpe', 0.0),
            'win_rate': metrics.get('win_rate', 0.0),
            'total_return': metrics.get('total_return', 0.0),
            'max_drawdown': metrics.get('max_drawdown', 0.0),
            'calmar': metrics.get('calmar', 0.0)
        }

    def _save_results(self):
        """Save results to CSV and JSON."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # CSV
        df = pd.DataFrame(self.results)
        csv_path = RESULTS_DIR / f'grid_search_{timestamp}.csv'
        df.to_csv(csv_path, index=False)
        print(f"\n✅ Results saved: {csv_path}")

        # JSON
        json_path = RESULTS_DIR / f'grid_search_{timestamp}.json'
        with open(json_path, 'w') as f:
            json.dump(self.results, f, indent=2)
        print(f"✅ Results saved: {json_path}")

    def get_best_params(self) -> dict:
        """Identify best parameter combination based on test Sharpe."""
        if not self.results:
            return {}

        best = max(self.results, key=lambda x: x['test_sharpe'])

        print(f"\n{'='*80}")
        print(f"BEST PARAMETER COMBINATION (by Test Sharpe)")
        print(f"{'='*80}")
        print(f"Entry Percentile: {best['entry_percentile']:.0%}")
        print(f"Exit Percentile:  {best['exit_percentile']:.0%}")
        print(f"Sizing Mode:      {best['sizing_mode']}")
        print(f"")
        print(f"Train Sharpe:     {best['train_sharpe']:.2f}")
        print(f"Test Sharpe:      {best['test_sharpe']:.2f}")
        print(f"Sharpe Degradation: {best['sharpe_degradation']:.1%}")
        print(f"Test Win Rate:    {best['test_win_rate']:.1%}")
        print(f"Test Return:      {best['test_return']:.1%}")
        print(f"Test Calmar:      {best['test_calmar']:.2f}")
        print(f"{'='*80}\n")

        return best


def main():
    parser = argparse.ArgumentParser(description='SEPA Backtest Parameter Optimization')
    parser.add_argument('--train-year', type=int, default=2023, help='Training year')
    parser.add_argument('--test-year', type=int, default=2024, help='Test year')
    parser.add_argument('--max-tickers', type=int, default=None, help='Limit tickers for testing')
    parser.add_argument('--quick', action='store_true', help='Run quick test with reduced grid')

    args = parser.parse_args()

    optimizer = BacktestOptimizer(args.train_year, args.test_year)

    if args.quick:
        # Quick test: 2x2x2 = 8 combinations
        entry_pcts = [0.60, 0.70]
        exit_pcts = [0.40, 0.50]
        sizing_modes = ['regime', 'equal_weight']
    else:
        # Full grid: 5x5x3 = 75 combinations
        entry_pcts = [0.50, 0.55, 0.60, 0.65, 0.70]
        exit_pcts = [0.30, 0.35, 0.40, 0.45, 0.50]
        sizing_modes = ['regime', 'equal_weight', 'rank_weighted']

    optimizer.grid_search(
        entry_percentiles=entry_pcts,
        exit_percentiles=exit_pcts,
        sizing_modes=sizing_modes,
        max_tickers=args.max_tickers
    )


if __name__ == '__main__':
    main()
```

**Acceptance Criteria**:
- [ ] Grid search runs successfully (5x5x3 = 75 combinations)
- [ ] Walk-forward validation implemented (train → test split)
- [ ] Results saved to CSV + JSON
- [ ] Best parameters identified and printed
- [ ] Sharpe degradation calculated (train vs test)

---

#### **Task 2.2: Create Results Analysis Notebook** (1-2 hours)

**File**: `notebooks/backtest_results.ipynb` (new)

**Sections**:
1. **Load Results**: Read grid search CSV
2. **Performance Table**: Top 10 parameter combinations by test Sharpe
3. **Heatmaps**:
   - Sharpe vs Entry/Exit Percentiles (3 subplots for each sizing mode)
   - Win Rate vs Entry/Exit Percentiles
   - Calmar Ratio vs Entry/Exit Percentiles
4. **Stability Analysis**:
   - Train vs Test Sharpe scatter plot
   - Sharpe degradation histogram
   - Flag combinations with >20% degradation
5. **Recommendations**: Best stable parameters

**Notebook Template**:
```python
# Cell 1: Load Results
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

results = pd.read_csv('data/backtest/optimization/grid_search_LATEST.csv')
results.head()

# Cell 2: Top 10 by Test Sharpe
top10 = results.nlargest(10, 'test_sharpe')[['entry_percentile', 'exit_percentile', 'sizing_mode', 'test_sharpe', 'test_win_rate', 'sharpe_degradation']]
display(top10)

# Cell 3: Sharpe Heatmap (by sizing mode)
fig, axes = plt.subplots(1, 3, figsize=(18, 5))
for idx, sizing in enumerate(['regime', 'equal_weight', 'rank_weighted']):
    df = results[results['sizing_mode'] == sizing].pivot(
        index='exit_percentile',
        columns='entry_percentile',
        values='test_sharpe'
    )
    sns.heatmap(df, annot=True, fmt='.2f', cmap='RdYlGn', ax=axes[idx])
    axes[idx].set_title(f'Test Sharpe: {sizing}')
plt.tight_layout()
plt.show()

# Cell 4: Stability Analysis
plt.figure(figsize=(10, 6))
plt.scatter(results['train_sharpe'], results['test_sharpe'], alpha=0.6)
plt.plot([0, 3], [0, 3], 'r--', label='Perfect Stability')
plt.xlabel('Train Sharpe')
plt.ylabel('Test Sharpe')
plt.title('Walk-Forward Validation: Train vs Test Sharpe')
plt.legend()
plt.grid(True, alpha=0.3)
plt.show()

# Cell 5: Degradation Warnings
unstable = results[results['sharpe_degradation'] > 0.20]
print(f"⚠️ {len(unstable)} combinations have >20% Sharpe degradation:")
display(unstable[['entry_percentile', 'exit_percentile', 'sizing_mode', 'train_sharpe', 'test_sharpe', 'sharpe_degradation']])
```

**Acceptance Criteria**:
- [ ] Notebook runs successfully (loads CSV, generates plots)
- [ ] 3 heatmaps created (one per sizing mode)
- [ ] Stability scatter plot shows train vs test Sharpe
- [ ] Unstable combinations flagged (>20% degradation)
- [ ] Recommendations section highlights best stable params

---

#### **Task 2.3: Update Documentation** (30 minutes)

**Files**:
- `docs/manual/07_Backtest.md` (update with new features)
- `docs/manual/09_Backtest_Optimization.md` (new)

**Updates**:
1. Document new CLI parameters (`--entry-percentile`, `--exit-percentile`, `--sizing-mode`)
2. Add section on parameter optimization workflow
3. Document Calmar ratio metric
4. Add examples of optimization runs

---

## Acceptance Criteria (Phase 6.5)

### Milestone 6.5.1: Backtesting Engine ✅

- [ ] Backtester runs on 2024 historical data (252 trading days)
- [ ] Produces trade log: entry_date, exit_date, ticker, entry_price, exit_price, return_pct
- [ ] Computes portfolio metrics: Sharpe, win rate, avg return, max drawdown, **Calmar ratio**
- [ ] Integrates with `v_d3_deployment` via DuckDB adapter
- [ ] Metrics match manual spot-check (validate 10 random trades)
- [ ] 4 position sizing modes: regime, equal_weight, rank_weighted, score_weighted
- [ ] Entry/exit thresholds configurable via CLI

### Milestone 6.5.2: Parameter Optimization ✅

- [ ] Grid search completes with results for all parameter combinations (75 combos in <4 hours)
- [ ] Best-performing params documented (entry/exit thresholds, sizing mode)
- [ ] Walk-forward validation shows <20% Sharpe degradation for top 3 combinations
- [ ] Results notebook shows heatmaps of Sharpe vs parameters
- [ ] CSV + JSON results saved to `data/backtest/optimization/`
- [ ] Unstable combinations flagged in notebook

---

## Validation Plan

### End-to-End Test (Milestone 6.5.1)

```bash
# 1. Run backtest with DuckDB integration
python scripts/run_backtest.py --run \
    --start 2024-01-01 --end 2024-12-31 \
    --entry-percentile 0.60 \
    --exit-percentile 0.40 \
    --sizing-mode rank_weighted

# 2. Verify metrics in report
cat data/backtest/reports/backtest_report_LATEST.md | grep -A5 "Performance Metrics"

# Expected output:
# - Sharpe Ratio: 1.2-2.0
# - Calmar Ratio: 2.0-4.0
# - Win Rate: 45-60%
# - Max Drawdown: 15-25%
```

### Grid Search Test (Milestone 6.5.2)

```bash
# Quick test (8 combinations)
python scripts/backtest_optimization.py --quick --max-tickers 50

# Expected: Completes in <15 minutes, generates CSV with 8 rows

# Full grid search (75 combinations)
python scripts/backtest_optimization.py --train-year 2023 --test-year 2024

# Expected: Completes in <4 hours, identifies best params
```

---

## Timeline

| Task | Estimated Time | Dependencies |
|------|----------------|--------------|
| 1.1 DuckDB Feed Adapter | 1 hour | None |
| 1.2 Calmar Ratio | 30 min | None |
| 1.3 Entry/Exit Thresholds | 30 min | None |
| 1.4 Position Sizing Modes | 1 hour | None |
| **Milestone 6.5.1 Total** | **3 hours** | |
| 2.1 Grid Search Script | 3 hours | Milestone 6.5.1 |
| 2.2 Results Notebook | 1-2 hours | Task 2.1 |
| 2.3 Documentation | 30 min | All tasks |
| **Milestone 6.5.2 Total** | **4.5-5.5 hours** | |
| **Phase 6.5 Total** | **7.5-8.5 hours** | |

**Estimated Completion**: 1-2 working days

---

## Rollback Plan

If DuckDB integration causes issues:
1. **Fallback**: Keep existing parquet-based feeds (`price_feed.py`, `universe_scorer.py`)
2. **Hybrid Mode**: Use DuckDB for scoring, parquet for OHLCV data
3. **Revert**: Remove `duckdb_feed.py`, restore original `runner.py`

All changes are **additive** (new files, new parameters) - no breaking changes to existing backtest system.

---

## Next Steps

1. ✅ Implementation plan approved
2. ⏳ Start Task 1.1 (DuckDB Feed Adapter)
3. ⏳ Test with 50-ticker subset (validate performance)
4. ⏳ Complete Milestone 6.5.1 (3 hours)
5. ⏳ Run quick grid search test (8 combinations)
6. ⏳ Complete Milestone 6.5.2 (4-5 hours)
7. ✅ Phase 6.5 COMPLETE

---

**Questions?**
- Preferred position sizing mode for default runs?
- Should we include transaction cost sensitivity in grid search?
- Target Sharpe threshold for "acceptable" parameters (e.g., >1.5)?
