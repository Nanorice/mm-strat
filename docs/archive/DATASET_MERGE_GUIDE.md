# Dataset Merge Module - Usage Guide

## Overview

The Dataset Merge Module combines Dataset A (daily feature snapshots) and Dataset B (trade labels) using **snapshot join** logic to create a training-ready dataset for machine learning.

### What It Does

For each trade in Dataset B:
1. Extracts the trade's `ticker` and `entry_date`
2. Looks up the exact feature vector from Dataset A for that (ticker, date) pair
3. Combines trade metadata + features into a single row

The result is a dataset where each row contains:
- Trade metadata (entry_date, exit_date, return_pct, days_held, etc.)
- Features available at entry (SMA_50, ATR, RS, revenue_growth_yoy, pe_ratio, etc.)
- Label (success/failure)

## Quick Start

### Basic Merge

```bash
# Merge with fundamentals
.venv\Scripts\python.exe merge_datasets.py \
  --dataset-a data/ml/dataset_a_with_fundamentals.parquet \
  --dataset-b data/ml/dataset_b.parquet \
  --output data/ml/merged_dataset.parquet
```

### Inspect Results

```bash
# View merge quality and statistics
.venv\Scripts\python.exe inspect_merged.py data/ml/merged_dataset.parquet
```

## CLI Reference

### merge_datasets.py

**Purpose**: Merge Dataset A and Dataset B

**Arguments**:
- `--dataset-a` (required): Path to Dataset A (Parquet or CSV)
- `--dataset-b` (required): Path to Dataset B (Parquet or CSV)
- `--output` (required): Output path for merged dataset
- `--format`: Output format (`parquet`, `csv`, or `both`) [default: parquet]
- `--export-report`: Export merge statistics to JSON file
- `--no-validate`: Skip temporal validation checks

## Next Steps: Model Training

After successfully merging datasets, use temporal split and train your model with the merged dataset.

For complete usage examples, troubleshooting, and API reference, see the full documentation.
