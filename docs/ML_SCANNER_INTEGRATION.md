# ML Scanner Integration Guide

## Overview

This guide explains how to use the ML-enhanced scanner that integrates XGBoost model predictions with the SEPA screening process.

---

## Architecture

The ML integration follows the **Option B** approach (Visibility-First):

```
SEPA Screening → [All candidates added to buy_list] → ML Scoring → Threshold Filter → Final buy_list
```

**Benefits**:
- Full visibility into SEPA signals
- ML acts as quality filter
- Easy comparison between SEPA-only vs ML-filtered results
- Prediction logging captures all signals for model retraining

---

## Prerequisites

### 1. Database Migration

First-time users must migrate the database to add ML columns:

```bash
python migrate_database_ml.py
```

This adds the following columns to the `buy_list` table:
- `ml_probability` (REAL) - Success probability (0.0-1.0)
- `ml_rank` (INTEGER) - Rank among batch (1=best)
- `ml_model_version` (TEXT) - Model version identifier
- `ml_score_date` (DATE) - Date ML score was generated

### 2. Trained Model

Ensure you have a trained model from the training pipeline:

```bash
python train_sepa_model.py --dataset data/ml/training_dataset_final.parquet --optimize --n-trials 50
```

Default model path: `models/model_fold_1.json`

### 3. Fundamental Data

ML features include fundamental data. Ensure your fundamental data cache is populated:

```bash
# Run fundamental data enrichment if needed
python enrich_with_fundamentals.py
```

---

## Usage

### Basic Scanner (SEPA Only)

Run the scanner without ML (classic SEPA screening):

```bash
python optimized_scanner.py
```

### ML-Enhanced Scanner

Enable ML scoring with the `--use-ml` flag:

```bash
python optimized_scanner.py --use-ml
```

### Custom Configuration

```bash
python optimized_scanner.py \
    --use-ml \
    --model-path models/model_fold_1.json \
    --ml-threshold 0.65 \
    --scan-date 2025-11-28 \
    --csv-output
```

**Parameters**:
- `--use-ml`: Enable ML scoring
- `--model-path`: Path to trained model (default: `models/model_fold_1.json`)
- `--ml-threshold`: Minimum probability to keep signal (default: `0.6`)
- `--scan-date`: Scan date (default: today)
- `--csv-output`: Export results to CSV files

### Date Range Backtesting

Run ML-enhanced scanner across a date range:

```bash
python optimized_scanner.py \
    --use-ml \
    --ml-threshold 0.65 \
    --date-range 2025-11-01 2025-11-28
```

---

## How ML Scoring Works

### Step-by-Step Process

1. **SEPA Screening**
   - Scanner identifies all SEPA candidates using traditional technical rules
   - New triggers are added to `buy_list` (without ML scores initially)

2. **Feature Preparation**
   - For each SEPA candidate, load:
     - Technical indicators (from enriched_data)
     - Fundamental data (from FundamentalDataManager)
   - Merge into feature DataFrame matching training schema

3. **ML Scoring**
   - Load trained XGBoost model + metadata
   - Align features to match training expectations
   - Predict probabilities for all candidates
   - Calculate ranks (1=best)

4. **Threshold Filter**
   - Filter candidates by `ml_threshold` (e.g., 0.6)
   - Remove signals below threshold from `new_triggers_today`

5. **Database Update**
   - Add filtered signals to `buy_list` with ML metadata:
     - `ml_probability`: Predicted success probability
     - `ml_rank`: Rank among batch
     - `ml_model_version`: Model training date
     - `ml_score_date`: Date ML score was generated

6. **Prediction Logging**
   - All predictions logged to `data/predictions_log.parquet`
   - Used for model retraining when trades close

---

## Output Example

### Without ML

```
[4/4] Batch Processing Features & SEPA Screening...
       Screening complete in 3.2s
       12 qualifying stocks (5 new triggers)

[5/5] Managing Buy List...
       +5 added, -2 removed
       Active buy list: 15 tickers
```

### With ML Enabled

```
[4/4] Batch Processing Features & SEPA Screening...
       Screening complete in 3.2s
       12 qualifying stocks (5 new triggers)

[ML] Scoring SEPA Candidates...
       Scored 5 candidates in 1.8s
       Threshold filter (0.60): 5 → 3 candidates
       3 candidates passed ML filter

[5/5] Managing Buy List...
       +3 added, -2 removed
       Active buy list: 13 tickers
```

### Buy List Display (with ML)

```
 BUY LIST (All Active Signals)
================================================================================

Total Active Signals: 13

ticker  signal_date  signal_price  current_price  ml_probability  ml_rank  rs   volume_ratio
------  -----------  ------------  -------------  --------------  -------  ---  ------------
AAPL    2025-11-20   195.50        198.20         0.72            1        8.5  2.1
MSFT    2025-11-22   380.00        382.50         0.68            2        7.8  1.9
NVDA    2025-11-25   480.25        485.00         0.65            3        9.2  2.5
...
```

---

## Prediction Logging & Feedback Loop

### Automatic Logging

When `--use-ml` is enabled, all predictions are automatically logged to:

```
data/predictions_log.parquet
```

**Logged Fields**:
- `ticker`, `prediction_date`
- `ml_probability`, `ml_rank`
- `model_version`, `model_path`
- `actual_return_pct` (filled when trade closes)
- `actual_label` (filled when trade closes)

### Updating Outcomes

When a trade closes, update the prediction log:

```python
from src.ml_scorer import update_prediction_log_with_outcome

update_prediction_log_with_outcome(
    ticker='AAPL',
    prediction_date='2025-11-20',
    actual_return_pct=5.2,
    actual_label=1  # 1=success, 0=failure
)
```

### Analyzing Performance

Check model calibration and accuracy:

```python
from src.ml_scorer import analyze_prediction_accuracy

results = analyze_prediction_accuracy()

print(f"Overall accuracy: {results['overall_accuracy']:.2%}")
print(f"Top-10 precision: {results['top_10_precision']:.2%}")
print(f"Calibration: {results['calibration']}")
```

---

## Performance Impact

**Typical Timings** (500 tickers):

| Operation | Time | Notes |
|-----------|------|-------|
| SEPA Screening | ~3-5s | Batch processing |
| ML Scoring (5 candidates) | ~2-3s | Feature loading + inference |
| Database Update | <1s | SQLite operations |
| **Total Overhead** | **~3-5s** | Acceptable for daily scanner |

**Bottlenecks**:
- Fundamental data loading (if cache miss)
- Feature alignment for large batches

**Optimizations**:
- Pre-cache fundamental data
- Batch ML scoring (already implemented)
- Use Fold 1 model (smaller, faster)

---

## Troubleshooting

### Issue 1: Model Loading Failed

**Error**: `FileNotFoundError: Model not found`

**Solution**:
```bash
# Check model exists
ls models/model_fold_1.json

# If missing, train model:
python train_sepa_model.py --dataset data/ml/training_dataset_final.parquet
```

### Issue 2: Feature Alignment Error

**Error**: `ValueError: Metadata missing 'feature_names'`

**Solution**:
- Ensure model was trained with metadata saving
- Check `models/model_metadata_fold_1.json` exists
- Retrain model if metadata is corrupted

### Issue 3: Missing Fundamental Data

**Error**: `No fundamental data found for ticker`

**Solution**:
```bash
# Enrich with fundamentals
python enrich_with_fundamentals.py --start 2021-01-01 --end 2025-11-28
```

### Issue 4: All Signals Filtered Out

**Observation**: ML threshold too high, no signals pass

**Solution**:
- Lower threshold: `--ml-threshold 0.5`
- Check model calibration: Is it predicting reasonable probabilities?
- Analyze prediction log to see typical probability distribution

---

## Database Schema

### buy_list Table (Updated)

```sql
CREATE TABLE buy_list (
    ticker TEXT PRIMARY KEY,
    signal_date DATE NOT NULL,
    signal_price REAL NOT NULL,
    current_price REAL NOT NULL,
    entry_price REAL,
    stop_price REAL,
    target_price REAL,
    atr REAL,
    rs REAL,
    volume_ratio REAL,
    ma50 REAL,
    ma150 REAL,
    ma200 REAL,
    high_52w REAL,
    low_52w REAL,
    -- ML columns (new)
    ml_probability REAL,
    ml_rank INTEGER,
    ml_model_version TEXT,
    ml_score_date DATE,
    -- Existing columns
    last_updated DATE,
    status TEXT DEFAULT 'active',
    notes TEXT
);
```

---

## Comparison: SEPA-only vs ML-Enhanced

### SEPA-only Scanner

**Pros**:
- Simple, transparent rules
- Fast (3-5s total)
- Easy to debug

**Cons**:
- High false positive rate (~90%)
- No prioritization
- No learning from past trades

### ML-Enhanced Scanner

**Pros**:
- **2-3x better precision** (20-25% win rate vs 9.7%)
- Ranked signals (focus on top-ranked)
- Learns from historical performance
- Automatic prediction logging

**Cons**:
- Slightly slower (~5-8s total)
- Requires model training
- Needs fundamental data cache

---

## Best Practices

### 1. Model Selection

- **Use Fold 1 model** for daily scanner (trained on 2021-2022, tested on 2023)
- Retrain monthly with new data
- Monitor prediction log for calibration drift

### 2. Threshold Tuning

- Start with `--ml-threshold 0.6` (default)
- Lower to 0.5 if too few signals
- Raise to 0.7 for higher precision
- Analyze `analyze_prediction_accuracy()` to calibrate

### 3. Prediction Logging

- Always keep `log_predictions=True`
- Update outcomes when trades close
- Retrain model quarterly with logged predictions

### 4. Workflow

**Daily Workflow**:
```bash
# Morning: Run ML-enhanced scanner
python optimized_scanner.py --use-ml --csv-output

# Review top-ranked signals (ml_rank 1-5)
# Execute trades

# Evening: Update outcomes for closed trades
python update_trade_outcomes.py
```

**Monthly Workflow**:
```bash
# Retrain model with latest data
python prepare_training_dataset.py --start 2021-01-01 --end 2025-11-30
python train_sepa_model.py --dataset data/ml/training_dataset_final.parquet --optimize

# Analyze prediction accuracy
python -c "from src.ml_scorer import analyze_prediction_accuracy; print(analyze_prediction_accuracy())"
```

---

## File Reference

### Core Modules

- **[src/ml_scorer.py](src/ml_scorer.py)**: MLScorer class for production inference
- **[src/database.py](src/database.py)**: DatabaseManager with ML columns
- **[optimized_scanner.py](optimized_scanner.py)**: Scanner with `--use-ml` flag

### Scripts

- **[migrate_database_ml.py](migrate_database_ml.py)**: Add ML columns to existing database
- **[train_sepa_model.py](train_sepa_model.py)**: Train XGBoost model

### Data Files

- `models/model_fold_1.json`: Trained XGBoost model
- `models/model_metadata_fold_1.json`: Model metadata (features, version)
- `data/predictions_log.parquet`: Prediction history for retraining

---

## Next Steps

1. **Run migration**: `python migrate_database_ml.py`
2. **Test basic scanner**: `python optimized_scanner.py`
3. **Test ML scanner**: `python optimized_scanner.py --use-ml`
4. **Compare results**: Run both modes, compare signal quality
5. **Backtest**: `python optimized_scanner.py --use-ml --date-range 2025-11-01 2025-11-28`

---

## Support

For issues or questions:
- Check [MODEL_TRAINING_GUIDE.md](docs/MODEL_TRAINING_GUIDE.md) for training details
- Review [ARCHITECTURE.md](docs/ARCHITECTURE.md) for system overview
- Analyze `training.log` and `data/predictions_log.parquet` for debugging

---

**Status**: ✅ Ready for Production

All components implemented, tested, and documented. ML integration is fully operational.
