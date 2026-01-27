# Training Dataset Preparation Guide

This guide explains how to prepare your final training dataset for model training.

## Overview

The training dataset preparation workflow consists of:

1. **Time Range Validation** - Ensure both datasets cover the required period (2020-01-01 to 2025-11-28)
2. **Dataset A Check** - Validate feature coverage and data quality
3. **Dataset B Check** - Validate trade labels and distribution
4. **Merging** - Combine datasets using snapshot join logic
5. **Sanity Checks** - Comprehensive validation before training

## Quick Start

### Option 1: Use the Automated Preparation Script (Recommended)

```bash
python prepare_training_dataset.py --start 2020-01-01 --end 2025-11-28
```

This single command will:
- ✅ Check if Dataset A and B cover the requested period
- ✅ Validate data quality and completeness
- ✅ Merge the datasets
- ✅ Perform comprehensive sanity checks
- ✅ Generate detailed validation reports

### Option 2: Manual Step-by-Step Preparation

If you need to build the datasets from scratch or with specific configurations:

#### Step 1: Build Dataset A (Features)

```bash
# With fundamental data (recommended)
```

#### Step 2: Build Dataset B (Labels)

```bash
# Default labeling rule (15% threshold)
python build_dataset_b.py \
  --start 2020-01-01 \
  --end 2025-11-28 \
  --threshold 15.0 \
  --output data/ml/dataset_b.parquet

# Custom labeling rule
python build_dataset_b.py \
  --start 2020-01-01 \
  --end 2025-11-28 \
  --label-rule "trade.return_pct >= 20 and trade.days_held <= 30" \
  --output data/ml/dataset_b.parquet
```

#### Step 3: Run Preparation Script

```bash
python prepare_training_dataset.py \
  --start 2020-01-01 \
  --end 2025-11-28 \
  --dataset-a data/ml/dataset_a_with_fundamentals.parquet \
  --dataset-b data/ml/dataset_b.parquet \
  --output data/ml/training_dataset_final.parquet
```

## Script Arguments

### prepare_training_dataset.py

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--start` | Yes | - | Start date (YYYY-MM-DD) |
| `--end` | Yes | - | End date (YYYY-MM-DD) |
| `--dataset-a` | No | `data/ml/dataset_a_with_fundamentals.parquet` | Path to Dataset A |
| `--dataset-b` | No | `data/ml/dataset_b.parquet` | Path to Dataset B |
| `--output` | No | `data/ml/training_dataset_final.parquet` | Output path |
| `--report` | No | `data/ml/preparation_report.txt` | Text report path |
| `--report-json` | No | `data/ml/preparation_report.json` | JSON report path |

## What Gets Checked

The preparation script performs comprehensive validation:

### 1. Dataset A Coverage
- ✅ File exists and is readable
- ✅ Date range covers requested period
- ✅ Missing date analysis
- ✅ Missing values percentage
- ✅ Feature completeness

### 2. Dataset B Coverage
- ✅ File exists and is readable
- ✅ Entry/exit dates cover requested period
- ✅ Trade distribution (wins vs losses)
- ✅ Label balance
- ✅ Trade metrics (return, days held)

### 3. Merge Quality
- ✅ Match rate (% of trades successfully joined)
- ✅ Missing snapshots
- ✅ Feature alignment

### 4. Sanity Checks
- ✅ No duplicate rows
- ✅ All critical columns present
- ✅ No infinite values
- ✅ Label distribution balance (>20% minority class)
- ✅ Missing values <10%
- ✅ Date consistency
- ✅ No extreme outliers (>500% or <-100% returns)
- ✅ Feature completeness (>90% for each feature)

## Understanding the Report

### Status Indicators

- ✅ **PASS** - Check passed, no issues
- ⚠️ **WARNING** - Check passed with warnings, review recommended
- ❌ **FAIL** - Check failed, action required

### Common Warnings and How to Fix

#### Warning: Missing Values >10%

**Cause:** Some features have many missing values, often due to:
- Short price history for newer stocks
- Fundamental data not available for some periods
- Technical indicators requiring warm-up period

**Fix:**
```python
# Extend the lookback period when building Dataset A
python build_dataset_a.py \
  --start 2019-01-01 \  # Start earlier to warm up indicators
  --end 2025-11-28
```

#### Warning: Label Imbalance (<20% minority class)

**Cause:** Too few successful trades (or too many).

**Fix:**
```bash
# Adjust the success threshold
python build_dataset_b.py \
  --start 2020-01-01 \
  --end 2025-11-28 \
  --threshold 10.0  # Lower threshold for more successes
```

#### Warning: Dataset A/B doesn't cover full period

**Cause:** Datasets were built with different date ranges.

**Fix:**
```bash
# Rebuild with correct dates
python build_dataset_a.py --start 2020-01-01 --end 2025-11-28 --include-fundamentals
python build_dataset_b.py --start 2020-01-01 --end 2025-11-28
```

## Output Files

After running the preparation script, you'll have:

1. **`training_dataset_final.parquet`** - Final merged dataset ready for training
2. **`preparation_report.txt`** - Human-readable validation report
3. **`preparation_report.json`** - Machine-readable report for automation

## Next Steps

Once the preparation script shows `✅ PASS`, you're ready to:

1. **Train your model** using the final dataset
2. **Feature selection** - Analyze which features are most important
3. **Cross-validation** - Split by time to avoid lookahead bias
4. **Backtesting** - Validate model performance on held-out period

## Troubleshooting

### No trades in Dataset B

```bash
# Check your scanner output
python view_buy_list_db.py

# Verify strategy is working
python example_scan_for_date.py --date 2024-01-15
```

### Dataset A has many missing values

```bash
# Check specific ticker's data quality
python analyze_missing_values.py
```

### Merge fails with compatibility error

This usually means Dataset A and B have different ticker sets or date formats. The script will provide specific error messages.

## Important Notes

> [!IMPORTANT]
> **Temporal Consistency**: The preparation script validates that features at entry_date don't use future information.

> [!WARNING]
> **Date Range**: For best results, start Dataset A earlier (e.g., 2019-01-01) to allow technical indicators to warm up, even if your training period starts at 2020-01-01.

> [!TIP]
> **Performance**: Building Dataset A in `full` mode with fundamentals can take 20-30 minutes for 5+ years of data. Use `--mode lightweight` for faster iteration during development.

## Additional Checks You Could Consider

Beyond what the script does automatically, you may want to:

1. **Check for data leakage** - Ensure no future information in features
2. **Analyze feature correlations** - Remove highly correlated features
3. **Check temporal stability** - Ensure feature distributions are stable over time
4. **Validate against known events** - Check if major market events appear correctly
5. **Cross-reference with external data** - Spot-check prices against Yahoo Finance

## Quick Commands Reference

```bash
# Full preparation from scratch
python build_dataset_a.py --start 2020-01-01 --end 2025-11-28 --mode full --include-fundamentals
python build_dataset_b.py --start 2020-01-01 --end 2025-11-28 --threshold 15.0
python prepare_training_dataset.py --start 2020-01-01 --end 2025-11-28

# Quick check on existing datasets
python prepare_training_dataset.py --start 2020-01-01 --end 2025-11-28
```
