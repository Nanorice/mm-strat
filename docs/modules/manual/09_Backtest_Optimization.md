# 09 - Backtest Parameter Optimization

**Strategy:** SEPA Hybrid V1 Parameter Tuning
**Method:** Grid Search with Walk-Forward Validation
**Stack:** DuckDB (Data), BackTrader (Simulation), Matplotlib (Analysis)

---

## Overview

The optimization framework systematically tests strategy parameters to find robust configurations that perform well out-of-sample. It uses **walk-forward validation** to measure stability and prevent overfitting.

**Key Concepts**:
- **Grid Search**: Test all combinations of parameter values
- **Walk-Forward**: Train on one period, test on next period
- **Stability Score**: Ratio of test/train performance (1.0 = perfect stability)
- **Robust Zone**: Configs with low degradation and acceptable out-of-sample performance

---

## Quick Start

### 1. Run Optimization

```bash
# Default setup (train 2023, test 2024)
python scripts/backtest_optimization.py

# Custom periods
python scripts/backtest_optimization.py \
  --train-start 2022-01-01 \
  --train-end 2022-12-31 \
  --test-start 2023-01-01 \
  --test-end 2023-12-31

# Custom output directory
python scripts/backtest_optimization.py --output-dir data/experiments/run1
```

**Runtime**: ~40-75 minutes (75 parameter combinations, sequential execution)

**Outputs**:
- `data/backtest/optimization_results.csv` - Full results (75 rows)
- `data/backtest/best_params.json` - Top 10 stable configs

### 2. Analyze Results

```bash
# Open Jupyter notebook
jupyter notebook notebooks/backtest_results.ipynb

# Run all cells (generates 6 plots + recommendation)
```

**Outputs**:
- `data/backtest/sharpe_heatmaps.png` - Performance grid
- `data/backtest/stability_plot.png` - Train vs test scatter
- `data/backtest/degradation_histogram.png` - Overfitting distribution
- `data/backtest/parameter_sensitivity.png` - Boxplots
- `data/backtest/recommended_params.json` - Production parameters

### 3. Apply Recommended Parameters

```python
# Load recommendation
import json
with open('data/backtest/recommended_params.json') as f:
    rec = json.load(f)

params = rec['recommended_parameters']
# Output: {'entry_percentile_min': 0.70, 'exit_percentile_max': 0.40, ...}

# Use in backtest
from src.backtest.runner import BacktestRunner
runner = BacktestRunner(strategy_params=params)
```

---

## Parameter Grid

### Parameters Under Test

**1. Entry Percentile (`entry_percentile_min`)**
- **Range**: [0.0, 0.50, 0.60, 0.70, 0.80]
- **Description**: Minimum percentile rank required to enter position
- **Default**: 0.0 (no threshold, enter all SEPA candidates)
- **Effect**: Higher values = more selective (fewer, higher-quality trades)

**2. Exit Percentile (`exit_percentile_max`)**
- **Range**: [0.20, 0.30, 0.40, 0.50, 0.60]
- **Description**: Maximum percentile rank before exiting position
- **Default**: 0.40 (exit if rank falls below 40th percentile)
- **Effect**: Higher values = more tolerant (hold longer despite rank deterioration)

**3. Sizing Mode (`sizing_mode`)**
- **Values**: ['regime', 'equal_weight', 'rank_weighted']
- **Default**: 'regime'
- **Modes**:
  - `regime`: Size based on M03 regime category (bullish = 100%, neutral = 50%, bearish = 0%)
  - `equal_weight`: Fixed size (1.0 / max_positions)
  - `rank_weighted`: Scale by percentile rank (0.5 + rank * 1.5 multiplier)

### Grid Size

**Total Combinations**: 5 × 5 × 3 = **75 configs**

**Example Combinations**:
```python
# Conservative (high entry, low exit)
{'entry_percentile_min': 0.80, 'exit_percentile_max': 0.20, 'sizing_mode': 'regime'}

# Moderate (balanced)
{'entry_percentile_min': 0.60, 'exit_percentile_max': 0.40, 'sizing_mode': 'rank_weighted'}

# Aggressive (low entry, high exit)
{'entry_percentile_min': 0.50, 'exit_percentile_max': 0.60, 'sizing_mode': 'equal_weight'}
```

---

## Walk-Forward Validation

### Methodology

**Training Period**: Optimize parameters on historical data (e.g., 2023)
**Test Period**: Validate on out-of-sample data (e.g., 2024)

**Process**:
1. Run backtest with parameter set on training period
2. Run same parameters on test period (no re-optimization)
3. Compare train vs test performance
4. Calculate degradation ratio (test/train Sharpe)

### Stability Metrics

**Degradation Ratio**:
```python
degradation = test_sharpe / train_sharpe
# 1.0 = perfect stability (test = train)
# 0.8 = 20% performance drop (acceptable)
# 0.5 = 50% performance drop (overfitting)
```

**Stability Score**:
```python
stability_score = min(1.0, max(0.0, degradation))
# Clamps degradation to [0.0, 1.0] range
# Used as primary sorting metric
```

**Robust Zone Criteria**:
- Degradation >= 0.8 (max 20% performance drop)
- Test Sharpe >= 1.0 (acceptable out-of-sample performance)

---

## Output Files

### 1. Full Results CSV

**File**: `data/backtest/optimization_results.csv`
**Rows**: 75 (one per parameter combination)
**Columns**: 20

| Column | Description | Example |
|--------|-------------|---------|
| `entry_percentile` | Entry threshold | 0.70 |
| `exit_percentile` | Exit threshold | 0.40 |
| `sizing_mode` | Position sizing mode | 'regime' |
| `train_sharpe` | Training Sharpe ratio | 2.01 |
| `test_sharpe` | Test Sharpe ratio | 1.85 |
| `train_calmar` | Training Calmar ratio | 2.15 |
| `test_calmar` | Test Calmar ratio | 1.95 |
| `train_max_dd` | Training max drawdown (%) | -15.2 |
| `test_max_dd` | Test max drawdown (%) | -12.8 |
| `train_return` | Training total return (%) | 32.5 |
| `test_return` | Test total return (%) | 28.3 |
| `train_trades` | Training trade count | 45 |
| `test_trades` | Test trade count | 42 |
| `train_win_rate` | Training win rate (%) | 65.2 |
| `test_win_rate` | Test win rate (%) | 62.5 |
| `degradation` | Test/train Sharpe ratio | 0.92 |
| `stability_score` | Clamped degradation | 0.92 |
| `train_error` | Training error message | null |
| `test_error` | Test error message | null |

### 2. Best Params JSON

**File**: `data/backtest/best_params.json`
**Content**: Top 10 stable configs + metadata

```json
{
  "timestamp": "2026-03-15T22:15:00",
  "train_period": "2023-01-01 to 2023-12-31",
  "test_period": "2024-01-01 to 2024-12-31",
  "universe_size": 1746,
  "total_combinations": 75,
  "top_10_configs": [
    {
      "entry_percentile": 0.70,
      "exit_percentile": 0.40,
      "sizing_mode": "regime",
      "train_sharpe": 2.01,
      "test_sharpe": 1.85,
      "degradation": 0.92,
      "stability_score": 0.92,
      "test_trades": 42
    },
    ...
  ]
}
```

### 3. Recommended Params JSON

**File**: `data/backtest/recommended_params.json`
**Content**: Single best config (rank 1)

```json
{
  "recommended_parameters": {
    "entry_percentile_min": 0.70,
    "exit_percentile_max": 0.40,
    "exit_use_percentile": true,
    "sizing_mode": "regime"
  },
  "expected_performance": {
    "test_sharpe": 1.85,
    "test_calmar": 1.95,
    "test_max_dd": -12.8,
    "test_return": 28.3,
    "test_win_rate": 62.5,
    "test_trades": 42
  },
  "stability": {
    "degradation": 0.92,
    "stability_score": 0.92
  },
  "metadata": {
    "analysis_date": "2026-03-15T22:15:00",
    "train_period": "2023-01-01 to 2023-12-31",
    "test_period": "2024-01-01 to 2024-12-31"
  }
}
```

---

## Visualization Guide

### 1. Sharpe Heatmaps

**File**: `data/backtest/sharpe_heatmaps.png`

**Interpretation**:
- **Green cells**: High test Sharpe (good out-of-sample performance)
- **Red cells**: Low/negative test Sharpe (poor performance)
- **Hot zones**: Contiguous green regions (robust parameter ranges)
- **Compare facets**: Which sizing mode performs best overall?

**Example Insights**:
- "Entry 0.60-0.70 + Exit 0.30-0.40 = consistently high Sharpe across sizing modes"
- "Regime sizing outperforms equal weight by ~0.3 Sharpe points"

### 2. Stability Plot

**File**: `data/backtest/stability_plot.png`

**Interpretation**:
- **Points near diagonal**: Stable (test ≈ train)
- **Points below diagonal**: Overfitting (test << train)
- **Points above diagonal**: Lucky or different regime (test > train)

**Reference Lines**:
- Black dashed (1:1): Perfect stability
- Red dashed (80%): Acceptable degradation threshold
- Orange dashed (60%): Warning threshold

**Example Insights**:
- "Most configs cluster around 0.85-0.95 degradation (acceptable)"
- "2 outliers with degradation <0.5 (severe overfitting, avoid)"

### 3. Degradation Histogram

**File**: `data/backtest/degradation_histogram.png`

**Interpretation**:
- **Median line**: Typical degradation across all configs
- **Right tail (> 1.0)**: Configs that improved OOS (investigate why)
- **Left tail (< 0.5)**: Overfitted configs (avoid)

**Example Insights**:
- "Median degradation: 0.75 (25% typical performance drop)"
- "20% of configs in robust zone (degradation >= 0.8)"

### 4. Parameter Sensitivity

**File**: `data/backtest/parameter_sensitivity.png`

**Interpretation**:
- **High median**: Parameter value produces good performance
- **Narrow IQR**: Consistent performance (low variance)
- **Wide IQR**: High interaction effects (performance depends on other params)

**Example Insights**:
- "Entry 0.70 has highest median Sharpe (1.80) with tight IQR (0.15)"
- "Exit percentile has wide variance (strong interaction with entry)"
- "Regime sizing has narrower IQR than rank_weighted (more stable)"

---

## Common Pitfalls

### 1. Overfitting Red Flags

**Symptoms**:
- Train Sharpe > 3.0 but test Sharpe < 1.0
- Degradation < 0.5 (50% performance drop)
- Very few trades in test period (<10)

**Causes**:
- Over-optimized to training period noise
- Regime shift between train/test periods
- Insufficient training data

**Solutions**:
- Choose configs from robust zone (degradation >= 0.8)
- Test on multiple walk-forward windows
- Avoid configs with extreme parameter values (e.g., entry = 0.95)

### 2. Data Snooping Bias

**Risk**: Testing on same period multiple times (e.g., re-running optimization with tweaks)

**Mitigation**:
- Reserve final validation period (e.g., 2025) - DO NOT use until final validation
- Document all optimization runs (timestamp, parameters, results)
- Use nested walk-forward (train 2021-2022, validate 2023, test 2024)

### 3. Regime Shifts

**Risk**: Train period (2023 bull) != Test period (2024 bear)

**Detection**:
- Compare M03 regime distribution (train vs test)
- Check SPY returns (train vs test)
- Look for consistent degradation across all configs (not just outliers)

**Mitigation**:
- Use longer training periods (2+ years)
- Weight recent data more (not implemented yet)
- Test on multiple regime combinations

### 4. Small Sample Size

**Risk**: Test period has <20 trades (high variance in metrics)

**Detection**:
- Check `test_trades` column in CSV
- Calculate confidence intervals (bootstrap)

**Mitigation**:
- Use longer test period (2+ years)
- Focus on trade count stability (not just Sharpe)
- Consider regime-conditioned metrics

---

## Advanced Workflows

### 1. Multi-Window Validation

Test stability across 3 train/test windows:

```bash
# Window 1: Train 2021-2022, Test 2023
python scripts/backtest_optimization.py \
  --train-start 2021-01-01 --train-end 2022-12-31 \
  --test-start 2023-01-01 --test-end 2023-12-31 \
  --output-dir data/backtest/window1

# Window 2: Train 2022-2023, Test 2024
python scripts/backtest_optimization.py \
  --train-start 2022-01-01 --train-end 2023-12-31 \
  --test-start 2024-01-01 --test-end 2024-12-31 \
  --output-dir data/backtest/window2

# Window 3: Train 2023-2024, Test 2025
python scripts/backtest_optimization.py \
  --train-start 2023-01-01 --train-end 2024-12-31 \
  --test-start 2025-01-01 --test-end 2025-12-31 \
  --output-dir data/backtest/window3
```

Then average degradation across windows:
```python
import pandas as pd

w1 = pd.read_csv('data/backtest/window1/optimization_results.csv')
w2 = pd.read_csv('data/backtest/window2/optimization_results.csv')
w3 = pd.read_csv('data/backtest/window3/optimization_results.csv')

# Merge on parameter columns
merged = w1.merge(w2, on=['entry_percentile', 'exit_percentile', 'sizing_mode'], suffixes=('_w1', '_w2'))
merged = merged.merge(w3, on=['entry_percentile', 'exit_percentile', 'sizing_mode'])

# Average degradation
merged['avg_degradation'] = (merged['degradation_w1'] + merged['degradation_w2'] + merged['degradation']) / 3

# Sort by average stability
best = merged.sort_values('avg_degradation', ascending=False).head(10)
```

### 2. Bayesian Optimization (Future)

Replace grid search with smarter sampling:

```python
# Example with scikit-optimize (not implemented yet)
from skopt import gp_minimize
from skopt.space import Real, Categorical

# Define search space
space = [
    Real(0.0, 0.9, name='entry_percentile'),
    Real(0.1, 0.7, name='exit_percentile'),
    Categorical(['regime', 'equal_weight', 'rank_weighted'], name='sizing_mode')
]

# Objective: maximize test Sharpe (minimize negative)
def objective(params):
    result = run_backtest(params, train_period, test_period)
    return -result['test_sharpe']  # Negate for minimization

# Run Bayesian optimization (20 iterations instead of 75)
result = gp_minimize(objective, space, n_calls=20, random_state=42)
```

**Benefits**: 60% fewer backtests, smarter sampling
**Drawbacks**: Complex setup, harder to interpret

---

## Troubleshooting

### Error: "No data feeds loaded"

**Cause**: `t3_sepa_features` table is empty or missing for train/test period

**Fix**:
```bash
# Check data availability
python -c "
import duckdb
conn = duckdb.connect('data/market_data.duckdb', read_only=True)
print(conn.execute('SELECT MIN(date), MAX(date), COUNT(*) FROM t3_sepa_features WHERE feature_version=\"v3.1\"').fetchall())
conn.close()
"

# If empty, run feature pipeline + T3 backfill
python data_curator_duckdb.py --update-prices
python scripts/backfill_t3_sepa_features.py --start 2020-01-01
```

### Error: "Calmar ratio is NaN"

**Cause**: Max drawdown is 0% (no trades or no losses)

**Expected**: Calmar = Annualized Return / Max DD, undefined if DD = 0

**Fix**: Not an error - inspect trade log to confirm no drawdowns

### Slow Performance (>2 hours for 75 combos)

**Causes**:
- Large universe (>2000 tickers)
- Long test period (>3 years)
- Complex strategy logic (many orders/rebalances)

**Fixes**:
- Filter universe (top 500 by liquidity)
- Shorten test period (1 year instead of 2)
- Use `--parallel` flag (future feature, not implemented yet)

---

## References

- Backtest User Guide: `docs/manual/07_Backtest.md`
- Technical Reference: `docs/manual/08_Backtest_Technical_Reference.md`
- Implementation Plan: `docs/proposals/duckdb_v2/phase_6_5_implementation_plan.md`
- Task Completion Reports: `docs/proposals/duckdb_v2/task_2_*.md`

---

**Last Updated**: 2026-03-15
**Version**: 1.0 (Initial Release)
