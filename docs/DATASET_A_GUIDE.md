# Dataset A Construction - Usage Guide

## Overview

Dataset A is the **Feature Store** for meta-labeling ML model training. It contains daily snapshots of technical indicators and alpha factors for all tickers, providing the features (X) that will be merged with Dataset B labels (y) for model training.

## Quick Start

### Basic Usage

```bash
# Generate Dataset A for 2024 (lightweight mode - 12 features)
python build_dataset_a.py \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --mode lightweight \
  --output data/ml/dataset_a_2024.parquet

# Generate Dataset A with alpha factors (full mode - 17 features)
python build_dataset_a.py \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --mode full \
  --output data/ml/dataset_a_2024_full.parquet
```

### Arguments

- `--start`: Start date for feature snapshots (YYYY-MM-DD) **[Required]**
- `--end`: End date for feature snapshots (YYYY-MM-DD) **[Required]**
- `--mode`: Feature mode - `lightweight` (fast, 12 features) or `full` (includes 5 alphas, 17 features) (default: `lightweight`)
- `--output`: Output file path (default: `data/ml/dataset_a.parquet`)
- `--format`: Output format - `parquet`, `csv`, or `both` (default: `parquet`)
- `--tickers`: Specific tickers to process (default: uses tickers from Dataset B)
- `--use-universe`: Use entire S&P 500 universe instead of Dataset B tickers
- `--from-dataset-b`: Path to Dataset B file to extract tickers from
- `--no-validate`: Skip temporal validation checks
- `--include-fundamentals`: **NEW** Include fundamental data enrichment (growth, ratios, P/E, etc.) ✨

## Default Behavior

**By default, Dataset A uses only tickers from Dataset B** (not the full 500-ticker universe):
- Automatically finds `data/ml/dataset_b_2025.parquet` or `data/ml/dataset_b.parquet`
- Extracts unique tickers from Dataset B
- Generates features only for those ~274 tickers (not 500)
- **This is more efficient** since we only need features for stocks that actually had trades

## Examples

### Example 1: Generate for Dataset B Tickers (Recommended)

```bash
# Automatically uses tickers from Dataset B
python build_dataset_a.py \
  --start 2025-01-01 \
  --end 2025-11-30 \
  --mode full \
  --output data/ml/dataset_a_2025.parquet
```

### Example 2: Generate for Specific Tickers

```bash
# Only FAANG+ stocks
python build_dataset_a.py \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --mode full \
  --tickers AAPL MSFT GOOGL NVDA META AMZN TSLA \
  --output data/ml/dataset_a_faang.parquet
```

### Example 3: Generate for Entire Universe

```bash
# Use full S&P 500 universe (slower, larger file)
python build_dataset_a.py \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --mode lightweight \
  --use-universe \
  --output data/ml/dataset_a_full_universe.parquet
```

### Example 4: Use Custom Dataset B Path

```bash
python build_dataset_a.py \
  --start 2023-01-01 \
  --end 2023-12-31 \
  --from-dataset-b data/ml/dataset_b_2023.parquet \
  --mode full \
  --output data/ml/dataset_a_2023.parquet
```

### Example 5: Include Fundamental Data (Complete Feature Set)

```bash
# Generate Dataset A with fundamentals enrichment
python build_dataset_a.py \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --mode full \
  --include-fundamentals \
  --output data/ml/dataset_a_2024_with_fundamentals.parquet
```

**Expected Output**:
- ~165 total features (25 technical + ~30 fundamental)
- ~20% missing values (expected from fundamentals)
- Additional fundamental features:
  - **Metadata**: filing_date_matched, days_since_report, is_stale, has_fundamentals
  - **Raw**: revenue, eps, netIncome, totalAssets, totalDebt, etc.
  - **Growth**: revenue_growth_yoy, eps_growth_yoy (YoY %)
  - **Ratios**: debt_to_equity, current_ratio, quick_ratio
  - **Margins**: gross_margin, operating_margin, roe, roa
  - **Hybrid**: pe_ratio, pb_ratio (price × fundamentals)

## Dataset A Schema

### Core Columns
| Column | Type | Description |
|--------|------|-------------|
| `date` | date | Trading date (scan date) |
| `ticker` | str | Stock symbol |
| `Close` | float | Close price |
| `Volume` | int | Trading volume |

### Lightweight Features (19 total)
| Column | Description | Category |
|--------|-------------|----------|
| `SMA_50` | 50-day simple moving average (raw price) | Trend |
| `SMA_150` | 150-day simple moving average (raw price) | Trend |
| `SMA_200` | 200-day simple moving average (raw price) | Trend |
| `Price_vs_SMA_50` | **ML FEATURE** (Close - SMA_50) / SMA_50 × 100 | Trend |
| `Price_vs_SMA_150` | **ML FEATURE** (Close - SMA_150) / SMA_150 × 100 | Trend |
| `Price_vs_SMA_200` | **ML FEATURE** (Close - SMA_200) / SMA_200 × 100 | Trend |
| `ATR` | Average True Range (14-day) | Volatility |
| `nATR` | **Normalized ATR** (ATR/Close × 100) | Volatility |
| `VCP_Ratio` | ATR_10 / ATR_50 (squeeze detector) | VCP |
| `Consolidation_Width` | (High_20D - Low_20D) / Close | VCP |
| `RS` | Relative strength vs SPY | Momentum |
| `RS_MA` | Moving average of RS | Momentum |
| `Vol_MA` | 50-day volume moving average | Volume |
| `Vol_Ratio` | Current volume / Vol_MA | Volume |
| `Dry_Up_Volume` | Vol_5D / Vol_50D (seller exhaustion) | VCP |
| `High_52W` | 52-week high price | Range |
| `Low_52W` | 52-week low price | Range |
| `High_20D` | 20-day high (breakout detection) | Breakout |
| `Breakout` | Boolean breakout signal | Breakout |

> **💡 Pro Tip**: The `Price_vs_SMA_*` features are normalized (%) and price-agnostic - perfect for ML. Raw `SMA_*` values are kept for strategy logic (e.g., checking if SMA_50 > SMA_150).

### Heavyweight Features (6 alphas, only in `--mode full`)
| Column | Description | Formula |
|--------|-------------|---------|
| `alpha001` | Signed power of volatility-adjusted close | See WorldQuant |
| `alpha006` | -1 × correlation(open, volume, 10) | Time series |
| `alpha009` | **NEW** Trend sustainability (consistent momentum) | Time series |
| `alpha012` | sign(Δvolume) × (-1 × Δclose) | Momentum |
| `alpha041` | √(high × low) - vwap | Intraday strength |
| `alpha101` | (close - open) / (high - low + 0.001) | Intraday momentum |

**Note**: All 6 alphas are time-series only (no cross-sectional ranking) for Sprint 1.

## Temporal Alignment

**Critical**: Dataset A features for Day T are calculated from data **up to and including Day T**.

```
Timeline:
- Day T: Market closes at 4pm
- SEPA scan runs after close using Day T data
- Dataset A row(date=T) contains features from prices up to Day T
- Trade entry happens (in simulation) at Day T close
- Trade entry (real-world) would be Day T+1 open

Temporal Rule:
- Features from Day T → Entry on Day T+1
- No future leakage: Features never use Day T+1 data
```

## Merging with Dataset B

Dataset A and B are designed to merge seamlessly:

```python
import pandas as pd

# Load datasets
dataset_a = pd.read_parquet('data/ml/dataset_a_2024.parquet')
dataset_b = pd.read_parquet('data/ml/dataset_b_2024.parquet')

# Merge: For each trade entry_date, get features from that date
merged = dataset_b.merge(
    dataset_a,
    left_on=['ticker', 'entry_date'],
    right_on=['ticker', 'date'],
    how='left'
)

# Create training matrix
feature_cols = [col for col in merged.columns if col.startswith(('SMA_', 'alpha', 'ATR', 'RS', 'Vol'))]
X = merged[feature_cols]
y = merged['label']
```

## Programmatic Usage

### Using DataRepository and FeatureEngineer

```python
from src.data_engine import DataRepository
from src.features import FeatureEngineer
from src.alpha_factors import AlphaEngine
import pandas as pd

# Initialize components
data_repo = DataRepository()
benchmark_data = data_repo.get_benchmark_data()
feature_engine = FeatureEngineer(benchmark_data=benchmark_data)

# Load tickers from Dataset B
dataset_b = pd.read_parquet('data/ml/dataset_b_2025.parquet')
tickers = dataset_b['ticker'].unique().tolist()

# Update cache and load data
data_repo.update_cache(tickers, force=False)
ticker_data = data_repo.get_batch_data(tickers)

# Calculate features for each ticker
enriched_data = {}
for ticker, df in ticker_data.items():
    # Lightweight features
    df = feature_engine.calculate_lightweight_features(df)
    
    # Heavyweight features (alphas)
    df = feature_engine.calculate_heavyweight_features(df, ticker)
    
    enriched_data[ticker] = df

# Extract daily snapshots
rows = []
for ticker, df in enriched_data.items():
    for date in df.index:
        row = {
            'date': date,
            'ticker': ticker,
            **df.loc[date].to_dict()
        }
        rows.append(row)

dataset_a = pd.DataFrame(rows)
```

### Calculating Alpha Factors Directly

```python
from src.alpha_factors import AlphaEngine

# Initialize with specific alphas
engine = AlphaEngine(alpha_list=[1, 6, 12, 41, 101])

# Calculate alphas for a ticker
price_data = data_repo.get_ticker_data('AAPL')
enriched = engine.calculate_alphas(price_data)

# Check alpha columns
print(enriched[['Close', 'alpha001', 'alpha006', 'alpha101']].tail())
```

## Output Statistics

The builder displays:
- **Total rows**: Date × ticker combinations
- **Date range**: First and last trading day
- **Tickers**: Number of unique symbols
- **Features**: Feature count (12 or 17)
- **Missing values**: Percentage of NaN values
- **Source**: Where tickers came from (Dataset B, manual, or universe)

Example output:
```
================================================================================
 DATASET A BUILDER - Daily Feature Snapshots
================================================================================

📅 Date Range: 2025-01-01 to 2025-11-30
⚙️  Mode: full
💾 Output: data/ml/dataset_a_2025.parquet
🎯 Using 274 tickers from data/ml/dataset_b_2025.parquet

🚀 Starting dataset generation...

Building Dataset A: 100%|████████| 5480/5480 [02:34<00:00, 35.4 rows/s]

Dataset A Summary:
  Total rows: 5,480
  Date range: 2025-01-01 to 2025-11-26
  Tickers: 274
  Features: 22
  Missing values: 180 (0.15%)

💾 Saving Dataset A...
   ✅ Saved to: data/ml/dataset_a_2025.parquet
   📊 File size: 3.2 MB

📋 Feature Summary:
   Total features: 22
   Lightweight: 16 features
      SMA_50, SMA_150, SMA_200, ATR, nATR, VCP_Ratio,
      Consolidation_Width, RS, Vol_Ratio, Dry_Up_Volume ...
   Heavyweight (Alphas): 6 features
      alpha001, alpha006, alpha009, alpha012, alpha041, alpha101

================================================================================
✅ Dataset A generation complete!
   5,480 rows | 25 features | 274 tickers
   Source: Tickers from Dataset B (data/ml/dataset_b_2025.parquet)
================================================================================
```

## Performance

- **Lightweight mode** (~19 features):
  - 274 tickers × 252 days = ~69,000 rows
  - Generation time: ~7-13 minutes
  - File size: ~5-7 MB (Parquet)

- **Full mode** (~25 features with alphas):
  - Same rows, more features
  - Generation time: ~13-20 minutes (alphas add ~50% overhead)
  - File size: ~6-9 MB (Parquet)

## Temporal Validation

Dataset A includes built-in temporal validation to prevent data leakage:

### Perturbation Test
Injects future data spike and verifies features remain unchanged:

```python
from src.temporal_validator import TemporalValidator

validator = TemporalValidator()

def calc_features(df):
    fe = FeatureEngineer()
    return fe.calculate_lightweight_features(df)

# Test for data leakage
passed = validator.perturbation_test(
    calculate_features_fn=calc_features,
    ticker='NVDA',
    entry_date=pd.Timestamp('2024-11-05'),
    feature_name='SMA_50',
    spike_magnitude=100.0
)

assert passed, "Data leakage detected!"
```

### Manual Audit
Compare against TradingView values for specific dates:

```python
# From TradingView for NVDA on 2024-11-04
expected_values = {
    'SMA_50': 142.35,
    'SMA_200': 118.72,
    'ATR': 5.23
}

passed = validator.manual_audit(
    df=features_df,
    ticker='NVDA',
    entry_date=pd.Timestamp('2024-11-05'),
    feature_values=calculated_values,
    expected_values=expected_values,
    tolerance=0.5  # 0.5% tolerance
)
```

## Next Steps: Model Training

After generating Dataset A and B:

1. **Merge datasets**: Join on `(ticker, date)` where Dataset B `entry_date` = Dataset A `date`
2. **Feature selection**: Remove highly correlated features (>0.95 correlation)
3. **Train/test split**: Use temporal split (not random!) - e.g., train on 2023, test on 2024
4. **Model training**: Random Forest or XGBoost with class imbalance handling
5. **Evaluation**: AUC-ROC, precision-recall curves

## Tips

1. **Start with lightweight mode** first to verify everything works
2. **Match date ranges** with Dataset B for seamless merging
3. **Use Dataset B tickers** (default) to reduce computation and storage
4. **Full mode for training** once you're ready for final model
5. **Monitor feature quality**: Check for excessive NaN values (should be <1%)

## Troubleshooting

**Issue**: Missing values in alpha columns
- **Solution**: This is normal for early dates (alphas need warmup period). Filter rows with `df.dropna()`.

**Issue**: Very slow generation
- **Solution**: Use `--mode lightweight` or specify fewer tickers with `--tickers`.

**Issue**: "Dataset B not found"
- **Solution**: Specify path explicitly with `--from-dataset-b` or use `--use-universe` as fallback.

**Issue**: Out of memory
- **Solution**: Process in date chunks or use `--tickers` to limit scope.
