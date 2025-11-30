# SEPA Model Training Guide

## Overview

This guide covers the complete model training pipeline for the SEPA (Specific Entry Point Analysis) ML system. The pipeline implements walk-forward validation with proper temporal integrity to prevent look-ahead bias.

## Architecture

The training system consists of three core modules:

1. **`src/model_preparation.py`** - Temporal splitting and feature selection
2. **`src/train_model.py`** - XGBoost training with Precision@k optimization
3. **`src/evaluate_model.py`** - Comprehensive evaluation and reporting

## Key Principles

### 1. Temporal Integrity (The "Time Trap")

**Problem**: Standard `train_test_split(shuffle=True)` causes look-ahead bias in time-series data.

**Solution**: Walk-Forward Validation with Expanding Window

```
Fold 1: Train 2021-2022 (2y) → [60-day purge] → Test 2023 (1y)
Fold 2: Train 2021-2023 (3y) → [60-day purge] → Test 2024-2025 (1.9y)
```

**Purge Gap**: 60 days between train and test to prevent trade overlap
- Average trade duration: 47.5 days
- Purge gap formula: `max(14 days, avg_trade_duration * 1.25) ≈ 60 days`
- Prevents "active trades" from leaking information across the boundary

### 2. Feature Selection Strategy

**Step 1**: Drop features with >99% missing values
- Automatic removal of: `entry_vol_ratio`, `current_ratio`, `quick_ratio`, `ps_ratio`

**Step 2**: Correlation filter at 0.95 threshold
- Removes redundant features (e.g., `SMA_50` and `SMA_150` at 99.8% correlation)
- Keeps simpler/standard features (SMA_50 over SMA_48)

**Step 3**: SHAP-based importance ranking (optional)
- `keep_top_n` parameter to limit features (prevents overfitting)
- Uses TreeExplainer for fast computation

### 3. Class Imbalance Handling

**Dataset**: 9:1 imbalance (1,527 failures : 167 successes)

**Strategy**: `scale_pos_weight=9` in XGBoost
- No data loss (unlike undersampling)
- No synthetic samples (unlike SMOTE)
- Tells model to pay 9x more attention to minority class

### 4. Evaluation Metric: Precision@Top-20%

**Why not Accuracy?**
- Accuracy optimizes for the 90% of boring days
- SEPA cares about "When we say Buy, is it actually a winner?"

**Precision@Top-20%**:
- Rank all predictions by probability
- Take top 20% (simulates buying 3-5 stocks daily)
- Calculate precision on this subset

**Formula**:
```python
k = int(n_samples * 0.2)
top_k_indices = np.argsort(probabilities)[-k:]
precision = true_labels[top_k_indices].mean()
```

## Installation

### 1. Install ML Dependencies

```bash
# Install required packages
pip install -r requirements_ml.txt

# Or install individually
pip install xgboost optuna shap
```

### 2. Verify Setup

```bash
python test_training_setup.py
```

Expected output:
```
✅ Dataset loaded: 1,694 rows × 162 columns
✅ Found 150 feature columns
✅ Valid folds created
✅ All modules present
✅ All ML dependencies installed
```

## Usage

### Quick Training (Default Parameters)

```bash
python train_sepa_model.py --dataset data/ml/training_dataset_final.parquet
```

**Configuration**:
- Purge gap: 60 days
- Correlation threshold: 0.95
- No hyperparameter optimization (uses defaults)
- Precision metric: Top 20%

**Training time**: ~5-10 minutes

### Full Optimization (Recommended)

```bash
python train_sepa_model.py \
    --dataset data/ml/training_dataset_final.parquet \
    --optimize \
    --n-trials 50
```

**Configuration**:
- Bayesian optimization with Optuna (50 trials)
- Optimizes hyperparameters on Fold 1
- Reuses best parameters for Fold 2

**Training time**: ~30-60 minutes (depending on hardware)

### Custom Configuration

```bash
python train_sepa_model.py \
    --dataset data/ml/training_dataset_final.parquet \
    --purge-gap 60 \
    --correlation 0.85 \
    --top-n 50 \
    --optimize \
    --n-trials 100 \
    --precision-k 0.15
```

**Parameters**:
- `--purge-gap`: Gap between train/test (default: 60 days)
- `--correlation`: Correlation threshold for feature removal (default: 0.95)
- `--top-n`: Keep top N features by SHAP importance (default: None)
- `--optimize`: Enable Optuna hyperparameter optimization
- `--n-trials`: Number of Optuna trials (default: 50)
- `--precision-k`: Top-k% for Precision@k metric (default: 0.2)

## Hyperparameter Search Space

When `--optimize` is enabled, the following parameters are tuned:

| Parameter | Range | Constraint |
|-----------|-------|------------|
| `max_depth` | [2, 3, 4] | **Limited to 4** (prevents overfitting) |
| `learning_rate` | [0.01, 0.1] | Log-uniform |
| `n_estimators` | [100, 500] | Step 100 |
| `subsample` | [0.6, 1.0] | Uniform |
| `colsample_bytree` | [0.6, 1.0] | Uniform |
| `min_child_weight` | [1, 10] | Integer |

**Why max_depth ≤ 4?**

With only 1,694 samples, deeper trees memorize the dataset. Shallow trees generalize better in finance.

## Output

### Models

Saved to `models/` directory:

```
models/
├── model_fold_1.json              # XGBoost model (Fold 1)
├── model_metadata_fold_1.json     # Hyperparameters, features, stats
├── model_fold_2.json              # XGBoost model (Fold 2)
└── model_metadata_fold_2.json
```

**Metadata includes**:
- Feature names (for prediction)
- Best hyperparameters
- Positive class weight
- Training date
- Best iteration (early stopping)

### Evaluation Reports

Saved to `evaluation/` directory:

```
evaluation/
├── evaluation_report.json         # Comprehensive metrics
├── roc_curve_fold_1.png           # ROC curve
├── roc_curve_fold_2.png
├── pr_curve_fold_1.png            # Precision-Recall curve
├── pr_curve_fold_2.png
├── feature_importance_fold_1.png  # SHAP importance
└── feature_importance_fold_2.png
```

### Training Log

Saved to `training.log`:

```
2025-11-30 12:00:00 - INFO - Starting data preparation...
2025-11-30 12:01:30 - INFO - Feature selection complete: 85 features selected
2025-11-30 12:05:45 - INFO - Fold 1 training complete
2025-11-30 12:10:20 - INFO - Fold 2 training complete
```

## Evaluation Metrics

### Per-Fold Metrics

```json
{
  "fold_id": 1,
  "precision_at_k": {
    "precision@top10%": 0.2500,
    "precision@top20%": 0.2105,
    "precision@top30%": 0.1831
  },
  "classification_metrics": {
    "roc_auc": 0.6234,
    "pr_auc": 0.1987,
    "precision": 0.2105,
    "recall": 0.4500,
    "f1_score": 0.2857
  },
  "trading_simulation": {
    "n_trades": 47,
    "avg_return": 3.45,
    "win_rate": 0.2105,
    "sharpe_ratio": 0.42
  },
  "baseline_comparison": {
    "baseline_win_rate": 0.097,
    "model_win_rate": 0.2105,
    "win_rate_lift": 1.17
  }
}
```

### Summary Statistics (All Folds)

```json
{
  "avg_precision@top20%": 0.2103,
  "avg_roc_auc": 0.6189,
  "avg_trading_return": 3.21,
  "avg_win_rate_lift": 1.15
}
```

**Interpretation**:
- **Precision@Top-20%**: 21% (vs 9.7% baseline) → **2.2x improvement**
- **Win Rate Lift**: 117% improvement over unfiltered SEPA
- **Trading Return**: 3.21% average return on top-20% picks

## Baseline Comparison

The model is compared against the **unfiltered SEPA baseline**:

- **Baseline**: All trades that passed SEPA criteria (buy everything)
- **Model**: Top 20% by ML probability score (selective buying)

**Win**: Model Win Rate > Baseline Win Rate

## Feature Importance

Top features are determined by **SHAP values** (mean absolute SHAP value per feature):

Example output:
```
Top 20 Features by SHAP Importance:
  1. entry_rs: 0.0234
  2. SMA_50: 0.0198
  3. alpha006: 0.0176
  4. nATR: 0.0145
  5. Vol_Ratio: 0.0132
  ...
```

**Interpretation**:
- `entry_rs` (Relative Strength) has the highest predictive power
- Price relative to SMA_50 is critical
- Alpha factors (WorldQuant) contribute
- Volatility (nATR) and volume matter

## Troubleshooting

### Issue: "No positive samples in training data"

**Cause**: Fold has no successful trades (label=1)

**Solution**: Adjust fold dates or check data quality

### Issue: "SHAP not installed"

**Cause**: SHAP package not installed

**Solution**:
```bash
pip install shap
```

**Fallback**: Model will use XGBoost gain importance instead

### Issue: "Optuna not installed"

**Cause**: Optuna package not installed

**Solution**:
```bash
pip install optuna
```

**Fallback**: Model will use default hyperparameters (still works, but not optimized)

### Issue: "Training very slow"

**Solutions**:
1. Reduce `--n-trials` (e.g., 20 instead of 50)
2. Skip optimization: remove `--optimize` flag
3. Reduce `--top-n` features (e.g., 50)

### Issue: "Model overfitting (test performance << train performance)"

**Solutions**:
1. Reduce `max_depth` (edit hyperparameter range)
2. Increase `min_child_weight`
3. Reduce `--top-n` features
4. Check for data leakage in feature engineering

## Next Steps

### 1. Review Evaluation Report

```bash
# View JSON report
cat evaluation/evaluation_report.json

# View plots
# Open evaluation/roc_curve_fold_*.png
# Open evaluation/feature_importance_fold_*.png
```

### 2. Deploy Best Model

```python
import xgboost as xgb
import json

# Load model
model = xgb.Booster()
model.load_model('models/model_fold_2.json')

# Load metadata
with open('models/model_metadata_fold_2.json', 'r') as f:
    metadata = json.load(f)

feature_names = metadata['feature_names']

# Predict on new data
import pandas as pd
new_data = pd.DataFrame(...)  # Your new SEPA candidates
dtest = xgb.DMatrix(new_data[feature_names])
probabilities = model.predict(dtest)

# Rank by probability
ranked = new_data.copy()
ranked['probability'] = probabilities
ranked = ranked.sort_values('probability', ascending=False)

# Buy top 5
top_5 = ranked.head(5)
```

### 3. Integrate with Scanner

Add ML filtering to `scanner_v0.py`:

```python
# After SEPA screening
qualified_stocks = strategy.batch_scan_universe(...)

# Load ML model
model = load_sepa_model('models/model_fold_2.json')

# Score candidates
scores = model.predict_proba(qualified_stocks)

# Filter: Only buy if probability > threshold
buy_list = qualified_stocks[scores > 0.6]
```

### 4. Monitor Performance

Track actual trade outcomes vs predictions:

```python
# Log predictions
predictions_log = {
    'date': trade_date,
    'ticker': ticker,
    'probability': predicted_prob,
    'actual_outcome': None  # Fill in later
}

# After trade closes, update
predictions_log['actual_outcome'] = trade.label

# Retrain quarterly with new data
```

## Best Practices

1. **Always run `test_training_setup.py` first**
   - Catches data issues before expensive training

2. **Start with quick training, then optimize**
   - Quick run (5 min) → Review results → Full optimization (1 hour)

3. **Monitor temporal stability**
   - Compare Fold 1 vs Fold 2 performance
   - If Fold 2 << Fold 1, model is regime-specific

4. **Retrain quarterly**
   - Markets change, retrain with fresh data every 3-6 months

5. **Never skip the purge gap**
   - 60-day purge is critical for temporal integrity

## References

- **XGBoost**: https://xgboost.readthedocs.io/
- **Optuna**: https://optuna.readthedocs.io/
- **SHAP**: https://shap.readthedocs.io/
- **Walk-Forward Validation**: Prado, M. L. (2018). *Advances in Financial Machine Learning*

## Support

For issues or questions:
1. Check `training.log` for detailed error messages
2. Run `test_training_setup.py` to diagnose
3. Review evaluation report for performance insights
