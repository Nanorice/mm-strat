# Scripts Directory

**Operational scripts for regular use**

This folder contains scripts you'll run regularly for data management, viewing results, and system maintenance.

---

## Data Initialization

### `init_fundamentals.py`
**Purpose**: Download fundamental data (financial statements) from FMP API

```bash
# Download fundamentals for S&P 500
python scripts/init_fundamentals.py

# Download for specific tickers
python scripts/init_fundamentals.py --tickers AAPL MSFT NVDA
```

**When to run**:
- Initial setup
- Monthly updates (new earnings reports)

---

### `initialise_price_data.py`
**Purpose**: Download historical OHLCV price data for tickers

```bash
# Download S&P 500 price data
python scripts/initialise_price_data.py

# Force refresh (ignore cache)
python scripts/initialise_price_data.py --force
```

**When to run**:
- Initial setup
- When adding new tickers
- When cache is stale

---

### `initialise_dataset_b.py`
**Purpose**: Initialize empty Dataset B table in database

```bash
python scripts/initialise_dataset_b.py
```

**When to run**:
- Initial setup (one-time)
- After database reset

---

## Viewing Results

### `view_buy_list.py`
**Purpose**: Display current buy list from database

```bash
# View active signals
python scripts/view_buy_list.py
```

**Output**: Table of active buy signals with prices, dates, and ML scores

---

### `view_buy_list_db.py`
**Purpose**: Alternative buy list viewer with database details

```bash
python scripts/view_buy_list_db.py
```

**Output**: Detailed database view including activity log

---

### `view_fundamentals.py`
**Purpose**: Inspect fundamental data coverage and quality

```bash
# View fundamentals for specific ticker
python scripts/view_fundamentals.py AAPL

# View all tickers
python scripts/view_fundamentals.py
```

**Output**: Shows available fundamental metrics, date ranges, missing data

---

### `show_buy_list.py`
**Purpose**: Legacy buy list viewer (use `view_buy_list.py` instead)

```bash
python scripts/show_buy_list.py
```

---

## Maintenance

### `clear_buy_list.py`
**Purpose**: Clear all signals from buy list database

```bash
# Clear buy list (requires confirmation)
python scripts/clear_buy_list.py
```

**When to run**:
- Starting fresh with new strategy parameters
- Testing/debugging

**Warning**: This deletes all active signals!

---

### `rebuild_ml_scores.py`
**Purpose**: Recalculate ML scores for existing buy list with new model

```bash
# Rebuild scores with new model
python scripts/rebuild_ml_scores.py --model-path models/model_fold_2.json
```

**When to run**:
- After retraining ML model
- When switching model versions

**What it does**:
1. Loads active buy list
2. Loads fundamental data
3. Recalculates ML probabilities
4. Updates database with new scores

---

## Usage Notes

- All scripts assume you're in the project root directory
- Most scripts require `.env` file with `FMP_API_KEY` for fundamental data
- Price data works without API key (uses yfinance)
- Scripts are safe to run multiple times (idempotent)

---

## Dependencies

These scripts depend on:
- `src/data_engine.py` - Data loading
- `src/fundamental_engine.py` - Fundamental data
- `src/database.py` - Database operations
- `config.py` - Global configuration

---

## Common Workflows

### Initial Setup
```bash
# 1. Download price data
python scripts/initialise_price_data.py

# 2. Download fundamentals
python scripts/init_fundamentals.py

# 3. Ready to run scanner
python optimized_scanner.py
```

### Monthly Maintenance
```bash
# Update fundamentals (new earnings)
python scripts/init_fundamentals.py --force

# Update price cache
python scripts/initialise_price_data.py --force
```

### After Model Retraining
```bash
# Rebuild ML scores for existing buy list
python scripts/rebuild_ml_scores.py --model-path models/model_fold_new.json
```
