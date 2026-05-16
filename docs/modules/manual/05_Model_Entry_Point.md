---
title: Model Entry Point - CLI Reference
type: reference
layer: model_runner
status: stable
created: 2026-01-27
updated: 2026-01-29
tags:
  - cli
  - usage
  - commands
  - model-runner
  - workflow
dependencies:
  - "[[02_Data_Pipeline]]"
  - "[[03_M01_Trainer]]"
  - "[[04_M02_Trainer]]"
---

# Model Entry Point: CLI Reference

**File:** [model_runner.py](../../model_runner.py)

← [[01_Model_Runner_Suite|Back to Suite Overview]]

---

## Purpose

Command-line interface for running model training workflows. Provides end-to-end automation for:
- Data generation (D1 → D2 → D3)
- Model training (M01, M02)
- Hyperparameter tuning
- Report generation
- **Automated workflow** with EDA screening and feature selection

---

## Usage Pattern

```bash
python model_runner.py <command> [options]
```

**Commands:**
- `m01` - Return predictor (regression)
- `m02` - Loser detector (classification)
- `workflow` - Automated M01 pipeline with EDA + feature selection

---

## M01 Training

### Full Pipeline

```bash
python model_runner.py m01 --start 2018-01-01 --end 2023-12-31 --report
```

**What It Does:**
1. Run SEPA scan (2018-2023) → `data/ml/d1.parquet`
2. Extract features → `data/ml/d2.parquet`
3. Train M01 model → `models/m01.json`
4. Generate report → `models/model_report_M01_*.md`

---

### Step-by-Step Execution

**Data Generation Only:**
```bash
python model_runner.py m01 --steps scan features
```

**Training Only (Data Exists):**
```bash
python model_runner.py m01 --steps train --report
```

**Custom Date Range:**
```bash
python model_runner.py m01 \
    --start 2015-01-01 \
    --end 2024-12-31 \
    --threshold 15.0 \
    --report
```

---

### With Hyperparameter Tuning

```bash
python model_runner.py m01 --steps train --tune --report
```

Uses Optuna with 50 trials (default). For more trials:
```bash
python model_runner.py m01 --steps train --tune --tune-trials 100 --report
```

---

### Survivor Model

```bash
python model_runner.py m01 --steps train --survivor --target y_max --report
```

**Note:** Requires D2R dataset with MAE/MFE calculations. Run `hydrate` step first if needed.

---

## M02 Training

### Full Pipeline

```bash
python model_runner.py m02 --start 2018-01-01 --end 2023-12-31 --report
```

**What It Does:**
1. Run SEPA scan → `data/ml/d1.parquet`
2. Rehydrate trajectories (120-day horizon) → `data/ml/d2r_120d.parquet`
3. Apply triple barriers → `data/ml/d3_120d.parquet`
4. Train M02 model → `models/m02.json`
5. Generate report → `models/model_report_M02_*.md`

---

### Step-by-Step Execution

**Data Generation Only:**
```bash
python model_runner.py m02 --steps scan hydrate label
```

**Training Only (Data Exists):**
```bash
python model_runner.py m02 --steps train --report
```

**Custom Horizon:**
```bash
python model_runner.py m02 \
    --start 2018-01-01 \
    --end 2023-12-31 \
    --horizon 90 \
    --report
```

---

### Custom Barriers

Test different barrier configurations:

```bash
# Tighter stop, larger target
python model_runner.py m02 --steps label train \
    --k-sl 0.8 \
    --k-tp 5.0 \
    --min-tp 0.25 \
    --max-time 20 \
    --report
```

---

## Workflow Command (NEW)

Automated M01 pipeline that handles EDA screening, feature selection, training, and reporting.

### Full Workflow

```bash
python model_runner.py workflow --start 2018-01-01 --end 2023-12-31
```

**What It Does:**
1. Load D2 dataset (or generate if missing)
2. Run EDA screening on `M01_CANDIDATE_FEATURES`
3. Auto-select features passing KS threshold
4. Train M01 with selected features
5. Generate report

---

### Workflow Steps

Control which steps to execute:

```bash
# EDA only (test new features without training)
python model_runner.py workflow --steps load eda select --ks-threshold 0.10

# Full workflow with tuning
python model_runner.py workflow --tune

# Skip auto-selection (use existing M01_FEATURES)
python model_runner.py workflow --no-auto-select
```

---

### Workflow-Specific Options

```bash
--ks-threshold FLOAT     # KS test threshold for feature screening (default: 0.15)
--no-auto-select         # Skip feature auto-selection, use M01_FEATURES
--steps STEPS            # Which steps to run: load, eda, select, train, report
```

**KS Threshold Guidelines:**
| Threshold | Strictness | Description |
|-----------|------------|-------------|
| 0.15 | Industry standard | Conservative, only top features |
| **0.10** | Recommended | Balance of coverage and quality |
| 0.05 | Permissive | Exploratory analysis |

---

## Common Options

### Date Range Options

```bash
--start YYYY-MM-DD       # Scan start date (default: 2018-01-01)
--end YYYY-MM-DD         # Scan end date (default: 2023-12-31)
--threshold FLOAT        # Success threshold % (default: 15.0)
```

**Example:**
```bash
python model_runner.py m01 --start 2015-01-01 --end 2024-12-31 --threshold 20.0
```

---

### Training Options

```bash
--tune                   # Enable Optuna hyperparameter tuning
--tune-trials INT        # Number of tuning trials (default: 50)
--train-years INT        # Training window size (default: 3)
--test-years INT         # Test window size (default: 1)
```

**Example:**
```bash
python model_runner.py m01 --tune --tune-trials 100 --train-years 4
```

---

### M01-Specific Options

```bash
--survivor               # Enable survivor model (filter crashed trades)
--stop-mult FLOAT        # Survivor stop multiplier (default: 2.0)
--target STR             # Target variable: 'return_pct' or 'y_max' (default: 'return_pct')
```

**Example:**
```bash
python model_runner.py m01 --survivor --stop-mult 2.5 --target y_max --report
```

---

### M02-Specific Options

```bash
--horizon INT            # Fixed horizon in days (default: 120)
--k-sl FLOAT             # Stop loss ATR multiplier (default: 1.0)
--k-tp FLOAT             # Profit target ATR multiplier (default: 4.0)
--min-tp FLOAT           # Minimum profit target (default: 0.20 = 20%)
--max-time INT           # Time barrier in days (default: 30)
```

**Example:**
```bash
python model_runner.py m02 \
    --horizon 90 \
    --k-sl 1.0 \
    --k-tp 5.0 \
    --min-tp 0.25 \
    --max-time 25 \
    --report
```

---

### Output Options

```bash
--report                 # Generate markdown training report
--jobs INT               # Parallel workers (default: -1 = all CPUs)
```

---

## Common Workflows

### Daily Model Refresh

```bash
# Regenerate D1/D2 with latest data
python model_runner.py m01 --steps scan features

# Retrain M01 with new data
python model_runner.py m01 --steps train --report
```

---

### Barrier Optimization

Test different barrier configs for M02:

```bash
# Baseline (4:1 reward/risk)
python model_runner.py m02 --steps label train --k-tp 4.0 --report

# Aggressive (5:1 reward/risk)
python model_runner.py m02 --steps label train --k-tp 5.0 --report

# Conservative (3:1 reward/risk)
python model_runner.py m02 --steps label train --k-tp 3.0 --report
```

Compare selection edge and precision across configs.

---

### Full System Rebuild

```bash
# M01
python model_runner.py m01 \
    --start 2015-01-01 \
    --end 2024-12-31 \
    --steps scan features train \
    --tune \
    --report

# M02
python model_runner.py m02 \
    --start 2015-01-01 \
    --end 2024-12-31 \
    --steps scan hydrate label train \
    --tune \
    --report
```

---

## Output Files

### M01 Outputs

**Data:**
- `data/ml/d1.parquet` - Trade candidates (14K trades)
- `data/ml/d2.parquet` - Features dataset (14K × 158 columns)

**Model:**
- `models/m01.json` - Trained XGBoost model (~2 MB)
- `models/m01_config.json` - Configuration + metrics
- `models/feature_importance_m01.csv` - Feature rankings
- `models/model_report_M01_*.md` - Training report

**Analysis:**
- `models/d1_analysis.json` - Trade physics (MAE/MFE, E-Ratio, crash rate)

---

### M02 Outputs

**Data:**
- `data/ml/d1.parquet` - Trade candidates
- `data/ml/d2r_120d.parquet` - Rehydrated trajectories (1.2M rows, 245 MB)
- `data/ml/d3_120d.parquet` - Labeled dataset (12K trades)
- `data/ml/d3_summary.json` - Label statistics (TP rate, expectancy)

**Model:**
- `models/m02.json` - Trained XGBoost classifier (~3 MB)
- `models/m02_config.json` - Configuration + metrics
- `models/feature_importance_m02.csv` - Feature rankings
- `models/model_report_M02_*.md` - Training report

---

## Example Session

### Train Both Models

```bash
# Step 1: M01 (Return Predictor)
python model_runner.py m01 \
    --start 2018-01-01 \
    --end 2023-12-31 \
    --steps scan features train \
    --report

# Output:
# D1: 14,523 trades (38.2% win rate)
# D2: 14,240 trades, 152 features
# M01: Mean RMSE=12.1%, Edge=+6.5%
# Report: models/model_report_M01_20260127_105632.md

# Step 2: M02 (Ignition Classifier)
python model_runner.py m02 \
    --start 2018-01-01 \
    --end 2023-12-31 \
    --steps scan hydrate label train \
    --report

# Output:
# D1: 14,523 trades
# D2R: 1,187,520 rows (83 days/trade avg)
# D3: 12,456 trades, TP rate: 5.6%
# M02: Accuracy=94.8%, Precision=11.2%, AUC=0.683
# Report: models/model_report_M02_20260127_112045.md
```

---

## Troubleshooting

### "D1 not found" Error

**Problem:** Trying to run `features` or `train` step without D1.

**Solution:**
```bash
# Generate D1 first
python model_runner.py m01 --steps scan
```

---

### "D2R not found" for Survivor Model

**Problem:** M01 survivor model requires D2R dataset.

**Solution:**
```bash
# Generate D2R first (use SEPA exits, not fixed horizon)
python model_runner.py m02 --steps scan hydrate --horizon 0
```

---

### Memory Issues with Large D2R

**Problem:** D2R file too large (>500 MB).

**Solution:**
1. Reduce horizon: `--horizon 90` instead of 120
2. Reduce date range: Use shorter time period
3. Use more workers: `--jobs 4` instead of `-1`

---

## Related Documentation

- For data pipeline details: [[02_Data_Pipeline|Data Pipeline]]
- For M01 training: [[03_M01_Trainer|M01 Trainer]]
- For M02 training: [[04_M02_Trainer|M02 Trainer]]
- For feature config: [[06_Feature_Config|Feature Config]]

---

## Quick Reference Card

| Task | Command |
|------|---------|
| Full M01 training | `python model_runner.py m01 --report` |
| Full M02 training | `python model_runner.py m02 --report` |
| M01 with tuning | `python model_runner.py m01 --tune --report` |
| M02 with tuning | `python model_runner.py m02 --tune --report` |
| M01 survivor model | `python model_runner.py m01 --survivor --report` |
| Custom barriers | `python model_runner.py m02 --k-tp 5.0 --report` |
| Data generation only | `python model_runner.py m01 --steps scan features` |
| Training only | `python model_runner.py m01 --steps train --report` |
| **Full workflow** | `python model_runner.py workflow --report` |
| **EDA screening only** | `python model_runner.py workflow --steps load eda select` |
| **Workflow with tuning** | `python model_runner.py workflow --tune` |

---

## Daily Scanner with ML

The daily scanner integrates both M01 and M02 for production scoring.

```bash
# Run with M02 Loser Detector
python daily_scanner.py --use-ml
```

**Output Columns:**
| Column | Description |
|--------|-------------|
| `final_score` | Combined M01 × M02 survival |
| `m02_loser_proba` | P(stop-loss hit) |
| `m02_survival` | 1 - P(loser) |
| `final_score_rank` | Rank by final_score (1=best) |

**Sorting Options in Dashboard:**
1. Final Score (M01 × Survival) - recommended
2. M01 Rank (Expected Return)
3. M02 Survival (1 - Loser Prob)

---

*Last updated: 2026-01-29*
