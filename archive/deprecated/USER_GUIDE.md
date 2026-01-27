# QSS User Guide

**Quick Start for Practitioners**

This guide shows you how to use the Quantamental SEPA System (QSS) for daily stock screening and ML-enhanced trading signal generation.

For architectural details, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Workflow Overview](#workflow-overview)
3. [Data Sourcing](#data-sourcing)
4. [Building Scanning Database](#building-scanning-database)
5. [Model Training](#model-training)
6. [Running the Scanner](#running-the-scanner)
7. [Common Tasks](#common-tasks)
8. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Installation

```bash
# Clone repository
git clone <repo-url>
cd quantamental

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### API Keys

Create a `.env` file in the project root:

```bash
FMP_API_KEY=your_fmp_api_key_here
```

Get your FMP API key from: https://site.financialmodelingprep.com/developer/docs

---

## Workflow Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    QSS WORKFLOW                             │
└─────────────────────────────────────────────────────────────┘

1. DATA SOURCING
   ├── Price Data     → yfinance / FMP API
   └── Fundamental    → FMP Financial Statements API

2. SCANNING DATABASE
   ├── Historical Prices → data/price/*.parquet (cached)
   ├── Fundamentals      → data/fundamental_cache/*.parquet
   └── Buy List          → database/qss_scanner.db (SQLite)

3. MODEL TRAINING (Optional, improves scanner)
   ├── Generate Dataset A (features)
   ├── Generate Dataset B (labels from simulation)
   ├── Merge A + B
   ├── Train XGBoost model
   └── Evaluate performance

4. DAILY SCANNER
   ├── Load universe (~1730 tickers)
   ├── Calculate features
   ├── Screen for SEPA signals
   ├── [Optional] ML scoring & filtering
   └── Update buy list database
```

---

## Data Sourcing

### Price Data

**Script**: `scripts/initialise_price_data.py`

**Purpose**: Download historical OHLCV data for your universe

```bash
# Download S&P 500 price data
python scripts/initialise_price_data.py

# Download custom ticker list
python scripts/initialise_price_data.py --tickers AAPL MSFT NVDA TSLA

# Force refresh (ignore cache)
python scripts/initialise_price_data.py --force
```

**What it does**:
- Fetches OHLCV data from yfinance (default) or FMP
- Caches to `data/price/*.parquet` for fast reuse
- Downloads 2+ years of history (needed for 200-day SMA)

**Output**: `data/price/{ticker}.parquet` for each stock

---

### Fundamental Data

**Script**: `scripts/init_fundamentals.py`

**Purpose**: Download quarterly financial statements from FMP

```bash
# Download fundamentals for S&P 500
python scripts/init_fundamentals.py

# Download for specific tickers
python scripts/init_fundamentals.py --tickers AAPL MSFT NVDA

# Check coverage
python scripts/view_fundamentals.py
```

**What it does**:
- Downloads income statements, balance sheets, cash flow statements
- Calculates growth metrics (YoY revenue, EPS, margins)
- Caches to `data/fundamental_cache/*.parquet`

**Output**: `data/fundamental_cache/{ticker}.parquet` for each stock

**Note**: Fundamentals are optional for basic SEPA scanning, but **required for ML models**.

---

## Building Scanning Database

The scanning database stores buy signals, tracks active positions, and logs all changes.

**Database**: `database/qss_scanner.db` (SQLite)

**Tables**:
- `buy_list`: Active buy signals with entry prices, stops, targets
- `buy_list_activity`: Audit trail of all adds/removes
- `trades`: Historical trade log (future use)

**Initialization**:
The database is created automatically on first scanner run. No manual setup needed.

**Viewing Buy List**:

```bash
# View current buy list
python scripts/view_buy_list.py

# Export to CSV
python optimized_scanner.py --csv-output
# Output: data/scanner_output/buy_list_YYYY-MM-DD.csv
```

---

## Model Training

ML model training is **optional**. The scanner works fine without ML, but ML improves signal quality by filtering out low-probability setups.

### Overview

```
Dataset A (features) + Dataset B (labels) → Merged Dataset → Train Model → Evaluate
```

### Step 1: Generate Dataset B (Trade Labels)

**Script**: `build_dataset_b.py`

**Purpose**: Simulate historical SEPA trades to create labeled training data

```bash
# Generate trade history for 2023-2024
python build_dataset_b.py \
  --start 2023-01-01 \
  --end 2024-12-31 \
  --threshold 15.0 \
  --output data/ml/dataset_b_2023_2024.parquet
```

**Parameters**:
- `--start`: Start date for simulation
- `--end`: End date for simulation
- `--threshold`: Success threshold (default: 15.0% return)
- `--output`: Output file path
- `--config`: Trading config preset (`default`, `conservative`, `aggressive`)

**What it does**:
1. Loads universe and price data
2. Simulates SEPA trades day-by-day
3. Tracks entry/exit prices, returns, drawdowns
4. Labels trades: 1 = success (≥15% return), 0 = failure

**Output**: Parquet file with columns:
```
ticker, entry_date, exit_date, entry_price, exit_price, return_pct,
days_held, max_drawdown_pct, label, ... (~25 columns)
```

**Time**: ~10-20 minutes for 2 years of data

---

### Step 2: Generate Dataset A (Feature Snapshots)

**Script**: `build_dataset_a.py`

**Purpose**: Calculate daily technical + fundamental features for all tickers

```bash
# Generate features for 2023-2024
python build_dataset_a.py \
  --start 2023-01-01 \
  --end 2024-12-31 \
  --mode full \
  --output data/ml/dataset_a_2023_2024.parquet
```

**Parameters**:
- `--start`: Start date
- `--end`: End date
- `--mode`: `full` (all features) or `lightweight` (fast features only)
- `--output`: Output file path
- `--tickers`: Optional ticker list (default: from Dataset B)

**What it does**:
1. Loads tickers from Dataset B (or custom list)
2. Downloads price + fundamental data
3. Calculates 130+ features per stock per day
4. Exports daily snapshots

**Output**: Parquet file with columns:
```
ticker, date, Close, SMA_50, SMA_150, ATR, RS, alpha001, alpha006,
pe_ratio, revenue_growth_yoy, ... (~130 features)
```

**Time**: ~30-60 minutes for 2 years of data

---

### Step 3: Merge Datasets

**Script**: `merge_datasets.py`

**Purpose**: Join features (A) with labels (B) on (ticker, entry_date)

```bash
# Merge Dataset A + B
python merge_datasets.py \
  --dataset-a data/ml/dataset_a_2023_2024.parquet \
  --dataset-b data/ml/dataset_b_2023_2024.parquet \
  --output data/ml/training_dataset_final.parquet
```

**What it does**:
1. Loads both datasets
2. Extracts feature snapshot for each trade entry date
3. Joins features with labels
4. Validates temporal alignment (no future data leakage)

**Output**: Merged dataset ready for model training

**Quality Check**:
```bash
# Inspect merged dataset
python tools/inspect_merged.py data/ml/training_dataset_final.parquet
```

---

### Step 4: Train Model

**Script**: `train_sepa_model.py`

**Purpose**: Train XGBoost model with walk-forward validation

```bash
# Train model with default settings
python train_sepa_model.py \
  --input data/ml/training_dataset_final.parquet

# Train with hyperparameter optimization (slower, better)
python train_sepa_model.py \
  --input data/ml/training_dataset_final.parquet \
  --optimize \
  --n-trials 50
```

**Parameters**:
- `--input`: Merged dataset path
- `--optimize`: Enable Optuna hyperparameter tuning
- `--n-trials`: Number of optimization trials (default: 50)
- `--output-dir`: Model output directory (default: `models/`)

**What it does**:
1. Loads merged dataset
2. Creates temporal folds (e.g., train on 2023, test on 2024)
3. Removes high-correlation features (>0.95)
4. Trains XGBoost with custom Precision@k metric
5. Evaluates on test set
6. Saves model + metadata

**Output**:
```
models/
├── model_fold_1.json              # XGBoost model
├── model_metadata_fold_1.json     # Feature names, hyperparams
├── model_fold_2.json
└── model_metadata_fold_2.json

evaluation/
├── evaluation_report.json         # Metrics (Precision@k, AUC, etc.)
├── roc_curve_fold_1.png
├── pr_curve_fold_1.png
└── feature_importance_fold_1.png
```

**Time**: 5-30 minutes depending on optimization

---

### Step 5: Evaluate Model

**Automated**: Evaluation runs automatically during training.

**Manual Inspection**:

```bash
# View evaluation report
cat evaluation/evaluation_report.json

# Key metrics to look for:
# - precision_at_20: Should be >0.20 (vs 0.10 baseline)
# - roc_auc: Should be >0.60
# - test_accuracy: Overall accuracy
```

**What to check**:
1. **Precision@Top 20%**: Are top-ranked predictions better than random?
2. **ROC-AUC**: Can model separate winners from losers?
3. **Calibration**: Are probabilities accurate?
4. **Feature Importance**: Which features matter most?

---

## Running the Scanner

### Basic Scanner (SEPA Only)

```bash
# Scan today
python optimized_scanner.py

# Scan specific date
python optimized_scanner.py --scan-date 2024-11-15

# Export to CSV
python optimized_scanner.py --csv-output
```

**What it does**:
1. Loads ~1730 ticker universe
2. Updates price cache
3. Calculates features
4. Screens for SEPA signals
5. Updates buy_list database (add/update/remove)

**Output**: Database updated, buy_list printed to console

---

### ML-Enhanced Scanner

```bash
# Scan with ML filtering (recommended)
python optimized_scanner.py --use-ml

# Custom ML threshold (higher = more selective)
python optimized_scanner.py \
  --use-ml \
  --ml-threshold 0.65 \
  --model-path models/model_fold_1.json

# Scan date range (backtesting)
python optimized_scanner.py \
  --use-ml \
  --date-range 2024-11-01 2024-11-28
```

**Parameters**:
- `--use-ml`: Enable ML scoring
- `--ml-threshold`: Minimum probability (0.0-1.0, default: 0.6)
- `--model-path`: Path to trained model (default: `models/model_fold_1.json`)
- `--scan-date`: Specific date to scan
- `--date-range`: Start and end dates for multi-day scan
- `--csv-output`: Export results to CSV

**What it does (additional steps)**:
1. Loads fundamental data for SEPA candidates
2. Scores candidates with XGBoost model
3. Filters by ML probability threshold
4. Calculates ranks (1 = best)
5. Stores ML metadata in database (probability, rank, model version)
6. Logs predictions to `data/predictions_log.parquet`

**ML Workflow**:
```
500 tickers → 15 SEPA signals → 8 pass ML filter (>0.6) → Buy List
```

**Performance**: ~7-8 seconds for 500 tickers

---

## Common Tasks

### View Current Buy List

```bash
# Quick view
python scripts/view_buy_list.py

# Database query
sqlite3 database/qss_scanner.db "SELECT ticker, signal_date, ml_probability FROM buy_list WHERE status='active' ORDER BY ml_rank"
```

---

### Clear Buy List

```bash
# Clear all signals (start fresh)
python scripts/clear_buy_list.py
```

---

### Update Universe

Edit `config.py`:

```python
# Use FMP screener (~1730 tickers, default)
UNIVERSE_SOURCE = 'FMP_SCREENER'

# Or use S&P 500 only (~500 tickers)
UNIVERSE_SOURCE = 'SSGA'
```

---

### Rebuild ML Scores

If you retrained the model, rebuild scores for existing buy list:

```bash
python rebuild_ml_scores.py --model-path models/model_fold_2.json
```

---

### Export Scanner Output

```bash
# Export to CSV
python optimized_scanner.py --csv-output

# Output files:
# - data/scanner_output/buy_list_YYYY-MM-DD.csv
# - data/scanner_output/buy_list_activity_YYYY-MM-DD.csv
```

---

### Historical Backtest

```bash
# Scan a past date
python optimized_scanner.py --scan-date 2024-01-15

# Note: Database automatically handles temporal consistency
# (clears "future" signals when scanning backward)
```

---

## Troubleshooting

### Price Data Issues

**Problem**: "No data found for ticker XYZ"

**Solution**:
```bash
# Force refresh cache
python scripts/initialise_price_data.py --force --tickers XYZ
```

---

### Fundamental Data Missing

**Problem**: "Missing fundamental data for 50% of tickers"

**Solution**:
```bash
# Download fundamentals
python scripts/init_fundamentals.py

# Check coverage
python scripts/view_fundamentals.py
```

**Note**: Not all tickers have fundamentals (e.g., new IPOs, small caps). This is expected.

---

### Model Training Fails

**Problem**: "ValueError: All features are NaN"

**Solution**:
```bash
# Check dataset quality
python tools/inspect_merged.py data/ml/training_dataset_final.parquet

# Rebuild Dataset A with fundamentals
python build_dataset_a.py --mode full --start 2023-01-01 --end 2024-12-31
```

---

### Scanner Too Slow

**Problem**: Scanner takes >30 seconds

**Solution**:
```bash
# Use smaller universe
# Edit config.py: UNIVERSE_SOURCE = 'SSGA'  # S&P 500 only

# Or disable ML scoring
python optimized_scanner.py  # No --use-ml flag
```

---

### Database Locked

**Problem**: "database is locked"

**Solution**:
```bash
# Close any open SQLite connections
# Kill any running scanner processes
pkill -f optimized_scanner.py

# Restart scanner
python optimized_scanner.py
```

---

## Configuration

### Global Settings

Edit `config.py`:

```python
# Universe selection
UNIVERSE_SOURCE = 'FMP_SCREENER'  # or 'SSGA'

# Feature parameters
SMA_FAST = 50
SMA_MEDIUM = 150
SMA_SLOW = 200

# SEPA strategy
VOL_SPIKE_THRESHOLD = 1.3  # Volume spike multiplier
CONSOLIDATION_PERIOD = 20  # Days

# Caching
DATA_CACHE_DAYS = 1  # Re-download if older than N days
```

---

### Trading Configuration

Edit `src/trading_config.py` or use CLI arguments:

```python
# Success threshold
--threshold 15.0  # Default: 15% return

# Labeling presets
--config default       # 15% threshold
--config conservative  # 10% threshold
--config aggressive    # 20% threshold
```

---

## Next Steps

1. **Run Daily Scanner**: Set up cron job to run scanner daily
   ```bash
   # Linux/Mac crontab
   0 17 * * 1-5 cd /path/to/quantamental && python optimized_scanner.py --use-ml
   ```

2. **Monitor Model Performance**: Check `data/predictions_log.parquet` monthly
   ```bash
   python -c "import pandas as pd; print(pd.read_parquet('data/predictions_log.parquet').describe())"
   ```

3. **Retrain Models**: Retrain quarterly with new data
   ```bash
   # Update Dataset B, A, merge, retrain
   # See "Model Training" section
   ```

4. **Integrate with Broker**: Build execution layer (future development)

---

## File Reference

| Script | Purpose | Frequency |
|--------|---------|-----------|
| `optimized_scanner.py` | Daily stock scanner | Daily |
| `build_dataset_b.py` | Generate trade labels | Quarterly |
| `build_dataset_a.py` | Generate features | Quarterly |
| `merge_datasets.py` | Merge A + B | Quarterly |
| `train_sepa_model.py` | Train ML model | Quarterly |
| `scripts/view_buy_list.py` | View buy list | As needed |
| `scripts/init_fundamentals.py` | Download fundamentals | Monthly |
| `scripts/initialise_price_data.py` | Download prices | As needed |

---

## Support

- **Documentation**: See `docs/` folder
- **Architecture**: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Issues**: Check GitHub issues or create new one
- **Configuration**: See `config.py` and `src/trading_config.py`
