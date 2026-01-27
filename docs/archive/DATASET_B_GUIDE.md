# Dataset B Construction - Usage Guide

## Overview

Dataset B is the **Events Log** for meta-labeling ML model training. It contains one row per completed trade, capturing entry/exit information and labels based on trade outcomes.

## Quick Start

### Basic Usage

```bash
# Generate Dataset B for a specific date range
python build_dataset_b.py \
  --start 2023-01-01 \
  --end 2023-12-31 \
  --threshold 15.0 \
  --output data/ml/dataset_b_2023.parquet
```

### Arguments

- `--start`: Simulation start date (YYYY-MM-DD) **[Required]**
- `--end`: Simulation end date (YYYY-MM-DD) **[Required]**
- `--threshold`: Return threshold for success label (default: 15.0%)
- `--output`: Output file path (default: `data/ml/dataset_b.parquet`)
- `--format`: Output format - `parquet`, `csv`, or `both` (default: `parquet`)
- `--save-to-db`: Save trades to database `ml_training_trades` table
- `--clear-existing`: Clear existing ML training data before saving

## Examples

### Example 1: Generate 1-Year Dataset

```bash
python build_dataset_b.py \
  --start 2023-01-01 \
  --end 2023-12-31 \
  --threshold 15.0 \
  --output data/ml/dataset_b_2023.parquet \
  --save-to-db
```

### Example 2: Generate Dataset with Different Threshold

```bash
# Conservative threshold (10%)
python build_dataset_b.py \
  --start 2022-01-01 \
  --end 2023-12-31 \
  --threshold 10.0 \
  --output data/ml/dataset_b_conservative.parquet

# Aggressive threshold (20% for superperformers)
python build_dataset_b.py \
  --start 2022-01-01 \
  --end 2023-12-31 \
  --threshold 20.0 \
  --output data/ml/dataset_b_aggressive.parquet
```

### Example 3: Export Both Formats

```bash
python build_dataset_b.py \
  --start 2023-01-01 \
  --end 2023-12-31 \
  --format both \
  --output data/ml/dataset_b_2023.parquet
```

This will generate both:
- `data/ml/dataset_b_2023.parquet`
- `data/ml/dataset_b_2023.csv`

## Dataset B Schema

| Column | Type | Description |
|--------|------|-------------|
| `trade_id` | int | Unique trade identifier |
| `ticker` | str | Stock symbol |
| `entry_date` | date | Date trade was entered |
| `entry_price` | float | Entry price |
| `exit_date` | date | Date trade was exited |
| `exit_price` | float | Exit price |
| `return_pct` | float | Total return percentage |
| `days_held` | int | Duration of trade in days |
| `exit_reason` | str | Reason for exit (trend_break, end_of_period) |
| **`label`** | **int** | **1 = Success, 0 = Failure** |
| `entry_ma50` | float | 50-day MA at entry |
| `entry_ma150` | float | 150-day MA at entry |
| `entry_ma200` | float | 200-day MA at entry |
| `entry_rs` | float | Relative strength at entry |
| `entry_vol_ratio` | float | Volume ratio at entry |
| `entry_high_52w` | float | 52-week high at entry |
| `entry_low_52w` | float | 52-week low at entry |
| `simulation_start` | date | Simulation period start |
| `simulation_end` | date | Simulation period end |
| `success_threshold_pct` | float | Threshold used for labeling |

## Programmatic Usage

### Using TradeSimulator Directly

```python
from src.data_engine import DataRepository
from src.strategy import SEPAStrategy
from src.features import FeatureEngineer
from src.trade_simulator import TradeSimulator
from src.trading_config import TradingConfig

# Initialize components
data_repo = DataRepository()
benchmark_data = data_repo.get_benchmark_data()
strategy = SEPAStrategy(benchmark_data=benchmark_data)
feature_engine = FeatureEngineer(benchmark_data=benchmark_data)

# Configure strategy
config = TradingConfig(
    success_threshold_pct=15.0,
    exit_on_trend_break=True,
    exit_on_stop_loss=False,
    allow_reentry=True
)

# Run simulation
simulator = TradeSimulator(
    data_repo=data_repo,
    strategy=strategy,
    feature_engine=feature_engine,
    start_date='2023-01-01',
    end_date='2023-12-31',
    config=config
)

dataset_b = simulator.run_simulation()

# Get statistics
stats = simulator.get_summary_statistics()
print(f"Total Trades: {stats['total_trades']}")
print(f"Win Rate: {stats['win_rate']*100:.1f}%")
```

### Using TradingConfig Presets

```python
from src.trading_config import TradingConfig

# Default SEPA configuration
config = TradingConfig.default()

# Conservative configuration
config = TradingConfig.conservative()

# Aggressive configuration  
config = TradingConfig.aggressive()

# Custom configuration
config = TradingConfig(
    success_threshold_pct=12.0,
    exit_on_trend_break=True,
    exit_on_stop_loss=True,
    stop_loss_pct=8.0,
    max_positions=10
)
```

## Output Statistics

The builder generates a summary report showing:

- **Trade Statistics**: Total trades, wins, losses, win rate
- **Returns**: Average return, average win/loss, max win/loss
- **Duration**: Average days held
- **Label Distribution**: Success vs failure counts
- **Exit Reasons**: Breakdown of why trades closed

Example output:
```
📊 Trade Statistics:
   Total Trades: 247
   Winning Trades: 132 (53.4%)
   Losing Trades: 115 (46.6%)

💰 Returns:
   Average Return: 8.35%
   Average Win: 22.17%
   Average Loss: -7.42%
   Max Win: 87.30%
   Max Loss: -15.20%

⏱️  Duration:
   Average Days Held: 18.3 days

🏷️  Label Distribution:
   Success (1): 132 trades (53.4%)
   Failure (0): 115 trades (46.6%)
```

## Next Steps: Dataset A

After generating Dataset B, you'll need Dataset A (Feature Store) to train the model:

1. **Dataset A** = Daily time series with indicators for all tickers
2. **Merge Logic** = For each trade in Dataset B, extract the feature vector from Dataset A on `entry_date`
3. **Training Matrix** = Features (X) from Dataset A + Labels (y) from Dataset B

## Tips

1. **Start Small**: Test with a short date range (1-3 months) first to verify everything works
2. **Multiple Thresholds**: Generate multiple datasets with different thresholds to experiment
3. **Database Storage**: Use `--save-to-db` to keep trades in database for later analysis
4. **Survivorship Bias**: Be aware that using current S&P 500 list introduces survivorship bias

## Troubleshooting

**Issue**: No trades generated
- **Solution**: Extend the date range. SEPA signals are rare (5-15 per day max).

**Issue**: All trades labeled as failures
- **Solution**: Lower the success threshold or extend holding period.

**Issue**: Memory error on large date ranges
- **Solution**: Process in smaller batches (e.g., 6-month chunks).
