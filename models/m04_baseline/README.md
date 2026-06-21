# M04 MFE Classifier - Model Documentation

**Model ID**: M04
**Version**: baseline
**Status**: ⚠️ Development (Class imbalance - not production ready)
**Training Date**: 2026-03-15
**Feature Version**: v3.1

---

## Quick Links

- **[Feature Set](FEATURE_SET.md)** - 105 features grouped by category
- **[Leakage Audit](LEAKAGE_AUDIT.md)** - Data leakage verification (✅ CLEAN)
- **[Evaluation Framework Plan](EVALUATION_FRAMEWORK_SUMMARY.md)** - Next implementation steps
- **[Full Design Spec](../../docs/proposals/classification_evaluation_framework.md)** - Complete technical design

---

## Model Overview

### Task
Predict Maximum Favorable Excursion (MFE) category for SEPA candidate entries.

### Classes
- **Class 0**: Noise (0-2% MFE) - Early failures
- **Class 1**: Moderate (2-10% MFE) - Small wins
- **Class 2**: Strong (10-30% MFE) - Solid performers
- **Class 3**: Home Run (>30% MFE) - Outliers

### Algorithm
XGBoost Multi-Class Classifier (`multi:softprob`)

### Features
- **Total**: 105 features (8 groups)
- **Groups**: Moving Averages, Momentum/RS, Volume, Volatility, Oscillators, Fundamentals, Alphas, M03 Regime
- **Missing**: 1 feature (`atr_delta` - not in database)

---

## Performance Summary

### Test Set Metrics (352 samples)
- **Accuracy**: 66.5%
- **Weighted F1**: 0.571
- **Macro F1**: 0.232 (poor - class imbalance)

### Per-Class Performance
| Class | Name | Support | Precision | Recall | F1 |
|-------|------|---------|-----------|--------|-----|
| 0 | Noise | 15 | 0.00 | 0.00 | 0.00 |
| 1 | Moderate | 36 | 0.00 | 0.00 | 0.00 |
| 2 | Strong | 65 | 0.18 | 0.08 | 0.11 |
| 3 | Home Run | 236 | 0.71 | 0.97 | 0.82 |

### Confusion Matrix
```
              Predicted
           0    1    2    3
Actual 0   0    0    6    9    ← All misclassified
       1   0    0   11   25    ← All misclassified
       2   1    1    5   58    ← 89% misclassified
       3   0    1    6  229    ← 97% correct
```

**Interpretation**: Model defaults to predicting Class 3 (home runs) due to extreme training imbalance (79.4% Class 3).

---

## Key Findings

### ✅ Strengths
1. **Excellent Class 3 recall** (97%) - Catches most home runs
2. **Clean feature set** - No data leakage detected
3. **Temporal split enforced** - No future information in training

### ❌ Weaknesses
1. **Extreme class imbalance** (79.4% Class 3 in training)
2. **Cannot predict failures** (0% precision on Class 0-1)
3. **Significant overfitting** (95% train accuracy → 67% test accuracy)

### ⚠️ Known Issues
1. **Class imbalance drives bias** - Model learns "predict everything is a home run"
2. **Poor calibration** - Overconfident at low probabilities
3. **Missing minority class patterns** - Insufficient failure examples (28 samples)

---

## Data Leakage Audit

**Status**: ✅ **CLEAN - No leakage detected**

### Verified
- ✅ MAE/MFE excluded from features (used only for target labels)
- ✅ Exit dates/prices excluded from features
- ✅ Holding period excluded from features
- ✅ Return features are lagged (T vs T-N), not forward-looking
- ✅ Temporal split enforced (train → val → test chronologically)

### Excluded Columns (Future Outcomes)
```
mae_pct, mfe_pct, return_at_exit, exit_date, exit_price,
holding_days, mae_date, mfe_date, sepa_exit_date, sl_exit_date
```

See [LEAKAGE_AUDIT.md](LEAKAGE_AUDIT.md) for full verification.

---

## Training Details

### Dataset
- **Source**: `v_d2_training` view (DuckDB)
- **Date Range**: 2020-01-02 to 2026-02-12
- **Total Samples**: 1,754
- **Train/Val/Test Split**: 60% / 20% / 20% (chronological)

### Train Split
- **Samples**: 1,052
- **Date Range**: 2020-01-02 to ~2022-12-31
- **Class Distribution**: 0:28 (1.6%), 1:92 (5.2%), 2:242 (13.8%), 3:1,392 (79.4%)

### Validation Split
- **Samples**: 350
- **Date Range**: ~2023-01-01 to ~2023-12-31
- **Class Distribution**: 0:12 (3.4%), 1:28 (8.0%), 2:58 (16.6%), 3:252 (72.0%)

### Test Split
- **Samples**: 352
- **Date Range**: ~2024-01-01 to 2026-02-12
- **Class Distribution**: 0:15 (4.3%), 1:36 (10.2%), 2:65 (18.5%), 3:236 (67.0%)

### Hyperparameters
```python
{
    'objective': 'multi:softprob',
    'num_class': 4,
    'max_depth': 4,
    'learning_rate': 0.05,
    'n_estimators': 100,
    'subsample': 0.8,
    'colsample_bytree': 0.8,
    'random_state': 42,
    'tree_method': 'hist'
}
```

### Class Weights (Balanced)
```python
Class 0: 37.57x
Class 1: 12.52x
Class 2: 2.41x
Class 3: 0.29x
```

---

## Files in This Directory

```
models/m04_baseline/
├── README.md                      ← This file
├── FEATURE_SET.md                 ← Feature breakdown by group
├── LEAKAGE_AUDIT.md               ← Data leakage verification
├── EVALUATION_FRAMEWORK_SUMMARY.md ← Next implementation steps
│
├── model.json                     ← XGBoost booster (509 KB)
├── metadata.json                  ← Training config
├── evaluation_results.json        ← Basic metrics (accuracy, F1, CM)
│
└── evaluation/                    ← FUTURE: Full evaluation outputs
    ├── results.json               ← Comprehensive metrics
    ├── report.md                  ← Markdown scorecard
    ├── plots/                     ← Visualizations (PNG)
    └── artifacts/                 ← SHAP values, predictions CSV
```

---

## Recommendations

### Before Production
1. **Address class imbalance** ⚠️ CRITICAL
   - Re-label with balanced thresholds (0-10%, 10-30%, 30-75%, >75%)
   - Use SMOTE to oversample minority classes
   - Consider binary classifier: Home Run (>30%) vs Not (≤30%)

2. **Regularization**
   - Reduce `max_depth` from 4 to 3
   - Increase `min_child_weight` to 3
   - Add dropout (`colsample_bytree=0.6`)

3. **Feature engineering**
   - Add fundamental red flags (EPS deceleration)
   - Add sector rotation signals
   - Investigate consolidation_duration → failure correlation

### Next Iteration
1. **Ensemble approach**
   - Binary Stage 1: Home Run (>30%) vs Not (≤30%)
   - Regression Stage 2: Predict MFE% for winners

2. **Feature selection**
   - Remove low-importance features (<1% gain)
   - Test without fundamentals (only 9% importance)

3. **Alternative targets**
   - Predict P(MFE > 30%) as binary classification
   - Use ordinal regression (respects class ordering)

---

## Usage

### Load Model
```python
import xgboost as xgb
from pathlib import Path

model_path = Path("models/m04_baseline/model.json")
model = xgb.Booster()
model.load_model(str(model_path))
```

### Predict
```python
import pandas as pd
import numpy as np

# Prepare features (105 features from metadata.json)
X = df[valid_features].replace([np.inf, -np.inf], np.nan)
dmatrix = xgb.DMatrix(X)

# Get probabilities
proba = model.predict(dmatrix)  # Shape: (n_samples, 4)

# Get class predictions
predictions = np.argmax(proba, axis=1)

# Use Class 3 probability for ranking
home_run_prob = proba[:, 3]
df['mfe_score'] = home_run_prob
```

### Deployment Constraints

**Usable Scenarios**:
- ✅ Candidate filtering (Class 3 prob > 80%)
- ✅ Portfolio ranking (sort by Class 3 prob)

**NOT Usable**:
- ❌ Stop-loss sizing (cannot predict failures)
- ❌ Position sizing by expected MFE (poor calibration)
- ❌ Risk assessment (overconfident)

---

## Next Steps

### Immediate (This Session)
- [x] Feature set inspection
- [x] Leakage audit
- [x] Evaluation framework design

### Next Session (4-5 hours)
- [ ] Implement `ClassificationEvaluator` class
- [ ] Implement `EvaluationPlotter` class
- [ ] Generate full evaluation report
- [ ] Review SHAP analysis
- [ ] Decide on re-training approach

---

## Change Log

### 2026-03-15 - Baseline Version
- Initial training with 105 features
- Test accuracy: 66.5%
- Identified extreme class imbalance (79.4% Class 3)
- Verified no data leakage (✅ CLEAN)
- Designed evaluation framework (pending implementation)

---

**Contact**: See [project README](../../README.md) for contribution guidelines.
