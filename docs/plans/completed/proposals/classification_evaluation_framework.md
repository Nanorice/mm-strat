# Classification Evaluation Framework - Design Specification

**Version**: 1.0
**Date**: 2026-03-15
**Status**: Design Complete - Ready for Implementation
**Estimated Effort**: 4-5 hours

---

## 1. Executive Summary

**Purpose**: Reusable evaluation framework for multi-class classification models (M04+)

**Deliverables**:
1. `ClassificationEvaluator` class - Orchestrates all evaluation components
2. `EvaluationPlotter` class - Standardized visualization library
3. Markdown scorecard report - Similar to M01's format
4. PNG/SVG plots - Confusion matrix, SHAP, feature importance, ROC/PR curves
5. ModelRegistry integration - Auto-save metrics to DuckDB

**Design Principles**:
- **Leakage Prevention First** - Temporal split validation built-in
- **Reusability** - Works for any XGBoost multi-class model
- **Consistency** - Matches M01 evaluation structure
- **Extensibility** - Easy to add new metrics/plots

---

## 2. Folder Structure

```
models/
└── m04_baseline/                           # Model root directory
    ├── model.json                          # XGBoost booster (from training)
    ├── metadata.json                       # Training config (from training)
    ├── FEATURE_SET.md                      # Feature documentation (manual)
    ├── LEAKAGE_AUDIT.md                    # Leakage verification (manual)
    │
    └── evaluation/                         # ← NEW: All evaluation outputs
        │
        ├── results.json                    # ← Comprehensive metrics
        ├── report.md                       # ← Markdown scorecard
        │
        ├── plots/                          # ← Visualizations
        │   ├── confusion_matrix.png
        │   ├── confusion_matrix_normalized.png
        │   ├── feature_importance_top20.png
        │   ├── feature_importance_full.csv
        │   ├── shap_class_0_bar.png
        │   ├── shap_class_0_beeswarm.png
        │   ├── shap_class_1_bar.png
        │   ├── shap_class_1_beeswarm.png
        │   ├── shap_class_2_bar.png
        │   ├── shap_class_2_beeswarm.png
        │   ├── shap_class_3_bar.png
        │   ├── shap_class_3_beeswarm.png
        │   ├── roc_curve_multiclass.png
        │   ├── pr_curve_multiclass.png
        │   └── calibration_curve.png       # Optional
        │
        └── artifacts/                      # ← Raw outputs (for debugging)
            ├── shap_values_class_0.npy
            ├── shap_values_class_1.npy
            ├── shap_values_class_2.npy
            ├── shap_values_class_3.npy
            ├── predictions.csv             # y_true, y_pred, proba_0-3, date, ticker
            └── feature_importance.csv      # Sorted by gain
```

---

## 3. Evaluation Report Structure

### 3.1 Markdown Scorecard (`report.md`)

```markdown
# M04 MFE Classifier - Evaluation Report

**Generated**: 2026-03-15 14:23:45
**Model Version**: baseline
**Feature Version**: v3.1
**Evaluator**: ClassificationEvaluator v1.0

---

## 1. Executive Summary

### Model Overview
- **Task**: 4-class MFE prediction (Noise/Moderate/Strong/Home Run)
- **Algorithm**: XGBoost Multi-Class (softprob)
- **Features**: 105 features (8 groups)
- **Training Period**: 2020-01-02 to 2022-12-31 (1,052 samples)
- **Test Period**: 2024-01-01 to 2026-02-12 (352 samples)

### Performance Summary
| Metric | Value | Threshold |
|--------|-------|-----------|
| **Test Accuracy** | 66.5% | - |
| **Weighted F1** | 0.571 | - |
| **Macro F1** | 0.232 | ⚠️ Poor (class imbalance) |
| **Class 3 Recall** | 97.0% | ✅ Excellent (catches home runs) |
| **Class 0-2 Precision** | 0.0-0.18 | ❌ Fails on minority classes |

### Viability Assessment
```
Status: ⚠️ CONDITIONAL - Usable only for Class 3 (home runs)
Recommendation: Address class imbalance before production deployment
```

---

## 2. Classification Metrics

### 2.1 Overall Performance

| Metric | Train | Validation | Test |
|--------|-------|------------|------|
| Accuracy | 95.2% | 68.3% | 66.5% |
| Weighted F1 | 0.941 | 0.612 | 0.571 |
| Macro F1 | 0.823 | 0.289 | 0.232 |
| Log Loss | 0.156 | 0.847 | 0.918 |

**Observations**:
- Significant train/test gap → Model overfits on training data
- Log loss degradation (0.16 → 0.92) → Poor probability calibration
- Macro F1 collapse (0.82 → 0.23) → Fails on minority classes

### 2.2 Per-Class Performance (Test Set)

| Class | Name | Support | Precision | Recall | F1-Score |
|-------|------|---------|-----------|--------|----------|
| 0 | Noise (0-2%) | 15 | 0.00 | 0.00 | 0.00 |
| 1 | Moderate (2-10%) | 36 | 0.00 | 0.00 | 0.00 |
| 2 | Strong (10-30%) | 65 | 0.18 | 0.08 | 0.11 |
| 3 | Home Run (>30%) | 236 | 0.71 | 0.97 | 0.82 |

**Class Distribution**:
- Training: 0:28 (1.6%), 1:92 (5.2%), 2:242 (13.8%), 3:1,392 (79.4%)
- Test: 0:15 (4.3%), 1:36 (10.2%), 2:65 (18.5%), 3:236 (67.0%)

**Key Insights**:
- Model defaults to predicting Class 3 (dominant class)
- Excellent recall on Class 3 (97%) - catches most home runs
- Zero precision on Classes 0-1 - never predicts failures correctly
- Extreme class imbalance (79.4% Class 3 in training) drives bias

### 2.3 Confusion Matrix

![Confusion Matrix](plots/confusion_matrix.png)

**Matrix** (rows = actual, cols = predicted):
```
              Predicted
           0    1    2    3
Actual 0   0    0    6    9    ← All misclassified as 2/3
       1   0    0   11   25    ← All misclassified as 2/3
       2   1    1    5   58    ← 89% misclassified as 3
       3   0    1    6  229    ← 97% correct
```

**Normalized** (% per row):
```
              Predicted
           0     1     2     3
Actual 0   0%    0%   40%   60%
       1   0%    0%   31%   69%
       2   2%    2%    8%   89%
       3   0%   <1%    3%   97%
```

**Interpretation**:
- Model assigns **60-89%** of Class 0-2 samples to Class 3
- True Class 3 samples correctly identified 97% of the time
- Model essentially predicts "everything is a home run"

---

## 3. Feature Importance

### 3.1 XGBoost Gain-Based Importance

**Top 20 Features** (by information gain):

![Feature Importance](plots/feature_importance_top20.png)

| Rank | Feature | Gain | Gain % | Cumulative % | Group |
|------|---------|------|--------|--------------|-------|
| 1 | m03_score | 1,234.5 | 12.3% | 12.3% | M03_Regime |
| 2 | rs_rating | 987.2 | 9.9% | 22.2% | Momentum_RS |
| 3 | alpha101 | 876.4 | 8.8% | 31.0% | Fast_Alphas |
| 4 | breakout_momentum | 765.1 | 7.7% | 38.7% | Technical_Oscillators |
| 5 | dist_from_52w_high | 654.3 | 6.5% | 45.2% | Volatility_Ranges |
| ... | ... | ... | ... | ... | ... |
| 20 | volume_acceleration | 123.4 | 1.2% | 89.5% | Core_Volume |

**Group-Level Importance**:
- M03_Regime: 18.5% (regime context matters)
- Momentum_RS: 24.3% (trend strength is key)
- Fast_Alphas: 15.7% (WQ101 factors add value)
- Technical_Oscillators: 12.1%
- Volatility_Ranges: 11.8%
- Fundamentals: 9.2%
- Core_Volume: 5.6%
- Moving_Averages: 2.8%

**Observations**:
- Top 20 features account for 90% of total gain
- M03 regime score is most important single feature
- Momentum/RS features dominate (24% total)
- Fundamentals contribute only 9% (surprising for long-term MFE)

### 3.2 SHAP Analysis (Directionality)

SHAP values show **how** each feature impacts predictions (not just importance).

#### Class 3 (Home Run) - Most Important

![SHAP Class 3 Bar](plots/shap_class_3_bar.png)
![SHAP Class 3 Beeswarm](plots/shap_class_3_beeswarm.png)

**Top 10 Features for Predicting Home Runs**:

| Feature | Mean |SHAP| | Direction |
|---------|------------|-----------|
| m03_score | 0.145 | High score → High Class 3 probability |
| rs_rating | 0.132 | Strong RS → Home run likely |
| breakout_momentum | 0.118 | Strong thrust → Home run likely |
| alpha101 | 0.107 | High candle strength → Home run |
| dist_from_52w_high | -0.095 | Close to high → Home run (negative feature) |

**Interpretation**:
- **Regime matters most**: Bullish M03 regime strongly predicts home runs
- **Momentum trumps fundamentals**: RS/breakout more important than EPS growth
- **Proximity to 52w high**: Stocks near highs (low distance) are more likely to explode
- **Volume thrust**: Breakout momentum (immediate_thrust) is critical

#### Class 0 (Noise) - Failure Patterns

![SHAP Class 0 Bar](plots/shap_class_0_bar.png)

**Top 5 Features for Predicting Failures**:

| Feature | Mean |SHAP| | Direction |
|---------|------------|-----------|
| rsi_14 | 0.082 | Low RSI → Failure likely |
| m03_score | -0.076 | Low regime score → Failure |
| vol_ratio | -0.063 | Low volume → Failure |
| consolidation_duration | 0.059 | Long base → Higher failure risk |
| earnings_quality_score | -0.054 | Poor cash flow quality → Failure |

**Interpretation**:
- Weak volume and oversold RSI → failure signal
- Bear market regime (low M03) → avoid entries
- Long consolidations without expansion → stalling pattern

---

## 4. ROC & Precision-Recall Curves

### 4.1 ROC Curves (One-vs-Rest)

![ROC Curves](plots/roc_curve_multiclass.png)

**AUC Scores**:
| Class | AUC | Interpretation |
|-------|-----|----------------|
| 0 (Noise) | 0.523 | ❌ No discrimination (random) |
| 1 (Moderate) | 0.547 | ❌ Barely better than random |
| 2 (Strong) | 0.612 | ⚠️ Weak discrimination |
| 3 (Home Run) | 0.845 | ✅ Good discrimination |

**Observations**:
- Only Class 3 has good separability (AUC > 0.8)
- Classes 0-2 are nearly indistinguishable from random guessing
- Model cannot reliably predict failures or moderate gains

### 4.2 Precision-Recall Curves

![PR Curves](plots/pr_curve_multiclass.png)

**Average Precision (AP)**:
| Class | AP | Baseline | Lift |
|-------|-----|----------|------|
| 0 (Noise) | 0.04 | 0.04 | 1.0x (no lift) |
| 1 (Moderate) | 0.11 | 0.10 | 1.1x |
| 2 (Strong) | 0.23 | 0.18 | 1.3x |
| 3 (Home Run) | 0.79 | 0.67 | 1.2x |

**Interpretation**:
- Class 3 PR curve shows meaningful lift over baseline
- Class 0-1 PR curves hug the baseline (no predictive power)
- Precision drops rapidly at high recall for minority classes

---

## 5. Model Calibration (Optional)

### 5.1 Reliability Diagram

![Calibration Curve](plots/calibration_curve.png)

**Brier Score**: 0.324 (0 = perfect, 1 = worst)

**Calibration Analysis**:
| Predicted Prob Bin | Actual Frequency | Samples |
|--------------------|------------------|---------|
| 0.0 - 0.1 | 0.03 | 12 |
| 0.1 - 0.2 | 0.18 | 24 |
| 0.2 - 0.3 | 0.41 | 31 |
| 0.3 - 0.4 | 0.56 | 28 |
| 0.4 - 0.5 | 0.67 | 19 |
| 0.5 - 0.6 | 0.74 | 27 |
| 0.6 - 0.7 | 0.81 | 34 |
| 0.7 - 0.8 | 0.88 | 45 |
| 0.8 - 0.9 | 0.92 | 67 |
| 0.9 - 1.0 | 0.97 | 65 |

**Observations**:
- Model is **overconfident** at low probabilities (predicts 10%, actual is 18%)
- Well-calibrated at high probabilities (80%+ predictions match reality)
- Isotonic calibration recommended for threshold-based decisions

---

## 6. Temporal Validation

### 6.1 Date Range Verification

| Split | Date Range | Samples | Class 3 % |
|-------|------------|---------|-----------|
| Train | 2020-01-02 to 2022-12-31 | 1,052 | 79.4% |
| Val | 2023-01-01 to 2023-12-31 | 350 | 75.1% |
| Test | 2024-01-01 to 2026-02-12 | 352 | 67.0% |

**Leakage Check**: ✅ PASS
- No test dates appear before train dates
- No overlap between train/val/test periods
- Chronological order preserved

**Distribution Shift**:
- Class 3 prevalence declining over time (79% → 67%)
- Test set has more balanced distribution than training
- Model trained on extreme imbalance, tested on moderate imbalance

### 6.2 Train/Test Performance Gap

| Metric | Train | Test | Delta | Status |
|--------|-------|------|-------|--------|
| Accuracy | 95.2% | 66.5% | -28.7% | ❌ Significant overfitting |
| Weighted F1 | 0.941 | 0.571 | -0.370 | ❌ Significant overfitting |
| Log Loss | 0.156 | 0.918 | +0.762 | ❌ Poor generalization |

**Diagnosis**: Model memorizes training set but fails to generalize

---

## 7. Error Analysis

### 7.1 Misclassification Patterns

**Class 3 (Home Run) False Negatives** (predicted 0-2, actually 3):
- Sample Size: 7 (3% of Class 3)
- Common Features:
  - Low breakout_momentum (median: 0.8, vs 2.3 for true positives)
  - Low rs_rating (median: 45, vs 78 for true positives)
  - Bear regime (m03_score < 40)

**Class 0-2 False Positives** (predicted 3, actually 0-2):
- Sample Size: 92 (78% of Class 0-2)
- Common Features:
  - Moderate breakout_momentum (1.5-2.0)
  - Strong RS (>70) but weak follow-through
  - Bullish regime (m03_score > 60)

**Interpretation**:
- Model **misses** home runs that start weakly (low initial thrust)
- Model **falsely predicts** home runs for strong setups that fail to deliver

### 7.2 Most Confident Errors

**Top 5 Most Confident Mistakes** (predicted Class 3 with >90% probability, actually Class 0-2):

| Ticker | Date | Actual | Pred Prob | MFE_Actual | Top Features |
|--------|------|--------|-----------|------------|--------------|
| XYZ | 2024-03-15 | Class 1 (8%) | 0.96 | 8.2% | rs_rating=92, m03=78 |
| ABC | 2024-06-20 | Class 2 (22%) | 0.94 | 21.7% | breakout_momentum=3.1 |
| DEF | 2024-09-12 | Class 0 (1%) | 0.91 | 1.4% | alpha101=0.89, rs=85 |
| GHI | 2025-01-08 | Class 1 (9%) | 0.93 | 9.1% | m03=82, immediate_thrust=2.4 |
| JKL | 2025-04-22 | Class 2 (28%) | 0.92 | 27.8% | consolidation_duration=45d |

**Common Failure Mode**:
- Strong technical setup (high RS, breakout, regime)
- Model predicts >30% MFE with 90%+ confidence
- Actual MFE plateaus at 1-28% (failure or moderate gain)
- **Hypothesis**: Missing fundamental red flags (earnings slowdown, sector rotation)

---

## 8. Recommendations

### 8.1 Immediate Actions (Before Production)

1. **Address Class Imbalance** ⚠️ CRITICAL
   - Re-label with balanced thresholds: 0-10%, 10-30%, 30-75%, >75%
   - Use SMOTE to oversample minority classes
   - Consider binary classifier: Home Run (>30%) vs Not Home Run (≤30%)

2. **Feature Engineering**
   - Add fundamental red flags (EPS deceleration, margin compression)
   - Add sector rotation signals (relative strength vs sector)
   - Investigate long consolidation duration → failure correlation

3. **Regularization**
   - Reduce `max_depth` from 4 to 3 (combat overfitting)
   - Increase `min_child_weight` to 3 (require more samples per leaf)
   - Add dropout (`colsample_bytree=0.6`)

### 8.2 Model Improvements (Next Iteration)

1. **Ensemble Approach**
   - Binary Stage 1: Home Run (>30%) vs Not (≤30%)
   - Magnitude Stage 2: Predict MFE% as regression
   - Decision Rule: Combine probability × magnitude

2. **Feature Selection**
   - Remove low-importance features (<1% gain)
   - Test without fundamentals (only 9% importance)
   - Add interaction features (rs_rating × m03_score)

3. **Alternative Targets**
   - Predict time-to-peak (days to MFE) instead of MFE%
   - Predict P(MFE > 30%) as binary classification
   - Use ordinal regression (respects class ordering)

### 8.3 Deployment Constraints

**Usable Scenarios**:
- ✅ Filtering candidates (use Class 3 probability > 80% as threshold)
- ✅ Portfolio ranking (sort by predicted Class 3 probability)

**NOT Usable**:
- ❌ Stop-loss sizing (cannot predict Class 0-2 accurately)
- ❌ Position sizing by expected MFE (calibration poor)
- ❌ Risk assessment (overconfident on failures)

---

## 9. Appendix

### 9.1 Model Hyperparameters

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
    'tree_method': 'hist',
    'enable_categorical': True
}
```

### 9.2 Class Weights (Balanced)

```python
Class 0: 37.57x
Class 1: 12.52x
Class 2: 2.41x
Class 3: 0.29x
```

### 9.3 Feature Groups

See [FEATURE_SET.md](../FEATURE_SET.md) for complete feature breakdown.

### 9.4 Evaluation Artifacts

All evaluation outputs are saved in `evaluation/` directory:
- `results.json` - Machine-readable metrics
- `plots/` - PNG visualizations (300 DPI)
- `artifacts/` - Raw SHAP values, predictions CSV
- `feature_importance.csv` - Sorted by gain

---

**Report Generated by**: `ClassificationEvaluator v1.0`
**Evaluation Completed**: 2026-03-15 14:23:45
**Total Runtime**: 127 seconds
```

---

## 4. JSON Results File Structure

### 4.1 `results.json` Schema

```json
{
  "metadata": {
    "model_name": "M04_MFE_Classifier",
    "model_version": "baseline",
    "feature_version": "v3.1",
    "evaluator_version": "1.0",
    "evaluation_date": "2026-03-15T14:23:45",
    "runtime_seconds": 127.3
  },

  "dataset": {
    "train": {
      "date_range": ["2020-01-02", "2022-12-31"],
      "n_samples": 1052,
      "class_distribution": {
        "0": 28,
        "1": 92,
        "2": 242,
        "3": 1392
      }
    },
    "val": {
      "date_range": ["2023-01-01", "2023-12-31"],
      "n_samples": 350,
      "class_distribution": {
        "0": 12,
        "1": 28,
        "2": 58,
        "3": 252
      }
    },
    "test": {
      "date_range": ["2024-01-01", "2026-02-12"],
      "n_samples": 352,
      "class_distribution": {
        "0": 15,
        "1": 36,
        "2": 65,
        "3": 236
      }
    }
  },

  "metrics": {
    "overall": {
      "accuracy": 0.6647727272727273,
      "weighted_f1": 0.5711451911247765,
      "macro_f1": 0.23244725005308778,
      "log_loss": 0.9183
    },

    "per_class": {
      "0": {
        "precision": 0.0,
        "recall": 0.0,
        "f1_score": 0.0,
        "support": 15,
        "roc_auc": 0.523,
        "average_precision": 0.04
      },
      "1": {
        "precision": 0.0,
        "recall": 0.0,
        "f1_score": 0.0,
        "support": 36,
        "roc_auc": 0.547,
        "average_precision": 0.11
      },
      "2": {
        "precision": 0.17857142857142858,
        "recall": 0.07692307692307693,
        "f1_score": 0.10752688172043011,
        "support": 65,
        "roc_auc": 0.612,
        "average_precision": 0.23
      },
      "3": {
        "precision": 0.7133956386292835,
        "recall": 0.9703389830508474,
        "f1_score": 0.822262118491921,
        "support": 236,
        "roc_auc": 0.845,
        "average_precision": 0.79
      }
    },

    "confusion_matrix": [
      [0, 0, 6, 9],
      [0, 0, 11, 25],
      [1, 1, 5, 58],
      [0, 1, 6, 229]
    ],

    "train_test_gap": {
      "accuracy_train": 0.952,
      "accuracy_test": 0.665,
      "accuracy_delta": -0.287,
      "weighted_f1_train": 0.941,
      "weighted_f1_test": 0.571,
      "weighted_f1_delta": -0.370,
      "log_loss_train": 0.156,
      "log_loss_test": 0.918,
      "log_loss_delta": 0.762
    }
  },

  "feature_importance": {
    "top_20": [
      {"rank": 1, "feature": "m03_score", "gain": 1234.5, "gain_pct": 12.3, "cumulative_pct": 12.3},
      {"rank": 2, "feature": "rs_rating", "gain": 987.2, "gain_pct": 9.9, "cumulative_pct": 22.2},
      {"rank": 3, "feature": "alpha101", "gain": 876.4, "gain_pct": 8.8, "cumulative_pct": 31.0},
      "..."
    ],
    "group_importance": {
      "M03_Regime": 18.5,
      "Momentum_RS": 24.3,
      "Fast_Alphas": 15.7,
      "Technical_Oscillators": 12.1,
      "Volatility_Ranges": 11.8,
      "Fundamentals": 9.2,
      "Core_Volume": 5.6,
      "Moving_Averages": 2.8
    }
  },

  "shap_summary": {
    "class_0": {
      "top_features": [
        {"feature": "rsi_14", "mean_abs_shap": 0.082},
        {"feature": "m03_score", "mean_abs_shap": -0.076},
        "..."
      ]
    },
    "class_3": {
      "top_features": [
        {"feature": "m03_score", "mean_abs_shap": 0.145},
        {"feature": "rs_rating", "mean_abs_shap": 0.132},
        "..."
      ]
    }
  },

  "calibration": {
    "brier_score": 0.324,
    "bins": [
      {"predicted_prob_range": [0.0, 0.1], "actual_frequency": 0.03, "count": 12},
      {"predicted_prob_range": [0.1, 0.2], "actual_frequency": 0.18, "count": 24},
      "..."
    ]
  },

  "error_analysis": {
    "class_3_false_negatives": {
      "count": 7,
      "percentage": 3.0,
      "common_features": {
        "breakout_momentum_median": 0.8,
        "rs_rating_median": 45,
        "m03_score_median": 38
      }
    },
    "class_0_2_false_positives": {
      "count": 92,
      "percentage": 78.0,
      "common_features": {
        "breakout_momentum_median": 1.7,
        "rs_rating_median": 73,
        "m03_score_median": 62
      }
    },
    "most_confident_errors": [
      {
        "ticker": "XYZ",
        "date": "2024-03-15",
        "actual_class": 1,
        "predicted_class": 3,
        "predicted_prob": 0.96,
        "actual_mfe": 8.2,
        "top_features": {"rs_rating": 92, "m03_score": 78}
      }
    ]
  },

  "temporal_validation": {
    "leakage_check": "PASS",
    "train_max_date": "2022-12-31",
    "test_min_date": "2024-01-01",
    "overlap_detected": false
  },

  "plots": {
    "confusion_matrix": "plots/confusion_matrix.png",
    "confusion_matrix_normalized": "plots/confusion_matrix_normalized.png",
    "feature_importance": "plots/feature_importance_top20.png",
    "shap_class_0_bar": "plots/shap_class_0_bar.png",
    "shap_class_0_beeswarm": "plots/shap_class_0_beeswarm.png",
    "shap_class_3_bar": "plots/shap_class_3_bar.png",
    "shap_class_3_beeswarm": "plots/shap_class_3_beeswarm.png",
    "roc_curve": "plots/roc_curve_multiclass.png",
    "pr_curve": "plots/pr_curve_multiclass.png",
    "calibration_curve": "plots/calibration_curve.png"
  },

  "artifacts": {
    "shap_values": "artifacts/shap_values_class_{0-3}.npy",
    "predictions": "artifacts/predictions.csv",
    "feature_importance": "artifacts/feature_importance.csv"
  }
}
```

---

## 5. Code Architecture

### 5.1 Class Structure

```python
# src/evaluation/classification_evaluator.py

from pathlib import Path
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
import xgboost as xgb
import matplotlib.pyplot as plt
import seaborn as sns
import shap
from sklearn.metrics import (
    accuracy_score, f1_score, precision_recall_fscore_support,
    confusion_matrix, classification_report, roc_auc_score,
    average_precision_score, log_loss, brier_score_loss
)
from src.model_registry import ModelRegistry
from src.evaluation.plotting import EvaluationPlotter


class ClassificationEvaluator:
    """
    Comprehensive evaluation framework for multi-class classification models.

    Features:
    - Confusion matrix (raw + normalized)
    - Per-class metrics (precision, recall, F1, ROC-AUC, AP)
    - SHAP analysis (per-class importance + directionality)
    - XGBoost feature importance (gain-based)
    - ROC/PR curves (one-vs-rest)
    - Calibration analysis (Brier score, reliability diagrams)
    - Temporal validation (leakage check)
    - Error analysis (misclassification patterns)
    - Markdown scorecard generation
    - ModelRegistry integration

    Usage:
        evaluator = ClassificationEvaluator(
            model_name='M04',
            model_version='baseline',
            output_dir='models/m04_baseline'
        )

        results = evaluator.evaluate(
            model=model,
            X_test=X_test,
            y_test=y_test,
            X_train=X_train,
            y_train=y_train,
            feature_names=feature_cols,
            class_names=['Noise', 'Moderate', 'Strong', 'Home Run']
        )

        # Auto-saves: JSON, markdown, plots, artifacts
    """

    def __init__(
        self,
        model_name: str,
        model_version: str,
        output_dir: Path,
        feature_version: str = 'v3.1'
    ):
        self.model_name = model_name
        self.model_version = model_version
        self.feature_version = feature_version
        self.output_dir = Path(output_dir)

        # Create subdirectories
        self.eval_dir = self.output_dir / 'evaluation'
        self.plots_dir = self.eval_dir / 'plots'
        self.artifacts_dir = self.eval_dir / 'artifacts'

        for d in [self.eval_dir, self.plots_dir, self.artifacts_dir]:
            d.mkdir(parents=True, exist_ok=True)

        self.plotter = EvaluationPlotter(self.plots_dir)
        self.registry = ModelRegistry()

    def evaluate(
        self,
        model: xgb.Booster,
        X_test: pd.DataFrame,
        y_test: pd.Series,
        X_train: pd.DataFrame = None,
        y_train: pd.Series = None,
        feature_names: List[str] = None,
        class_names: List[str] = None,
        feature_groups: Dict[str, List[str]] = None
    ) -> Dict:
        """
        Run comprehensive evaluation.

        Returns:
            results: Dict with all metrics, plots, artifacts
        """
        # 1. Basic metrics
        metrics = self._compute_metrics(model, X_test, y_test, X_train, y_train)

        # 2. Feature importance
        importance_df = self._compute_feature_importance(model, feature_names, feature_groups)

        # 3. SHAP analysis
        shap_results = self._compute_shap(model, X_test, feature_names, class_names)

        # 4. ROC/PR curves
        roc_pr_results = self._compute_roc_pr_curves(y_test, metrics['y_pred_proba'], class_names)

        # 5. Calibration
        calibration_results = self._compute_calibration(y_test, metrics['y_pred_proba'])

        # 6. Error analysis
        error_analysis = self._analyze_errors(X_test, y_test, metrics['y_pred'], metrics['y_pred_proba'])

        # 7. Temporal validation
        temporal_check = self._validate_temporal_split(X_train, X_test)

        # 8. Assemble results
        results = {
            'metadata': {...},
            'metrics': metrics,
            'feature_importance': importance_df,
            'shap': shap_results,
            'roc_pr': roc_pr_results,
            'calibration': calibration_results,
            'error_analysis': error_analysis,
            'temporal_validation': temporal_check
        }

        # 9. Save outputs
        self._save_results(results)
        self._generate_report(results)
        self._register_in_db(results)

        return results

    def _compute_metrics(self, model, X_test, y_test, X_train, y_train) -> Dict:
        """Compute all classification metrics."""
        # Predictions
        dtest = xgb.DMatrix(X_test.replace([np.inf, -np.inf], np.nan))
        y_pred_proba = model.predict(dtest)
        y_pred = np.argmax(y_pred_proba, axis=1)

        # Overall metrics
        accuracy = accuracy_score(y_test, y_pred)
        weighted_f1 = f1_score(y_test, y_pred, average='weighted')
        macro_f1 = f1_score(y_test, y_pred, average='macro')
        logloss = log_loss(y_test, y_pred_proba)

        # Per-class metrics
        precision, recall, f1, support = precision_recall_fscore_support(y_test, y_pred)

        # Confusion matrix
        cm = confusion_matrix(y_test, y_pred)

        # Train/test gap (if train data provided)
        train_test_gap = {}
        if X_train is not None and y_train is not None:
            dtrain = xgb.DMatrix(X_train.replace([np.inf, -np.inf], np.nan))
            y_train_pred = np.argmax(model.predict(dtrain), axis=1)
            train_test_gap = {
                'accuracy_train': accuracy_score(y_train, y_train_pred),
                'accuracy_test': accuracy,
                'accuracy_delta': accuracy_score(y_train, y_train_pred) - accuracy,
                # ... more gaps
            }

        return {
            'overall': {...},
            'per_class': {...},
            'confusion_matrix': cm.tolist(),
            'train_test_gap': train_test_gap,
            'y_pred': y_pred,
            'y_pred_proba': y_pred_proba
        }

    def _compute_feature_importance(self, model, feature_names, feature_groups) -> pd.DataFrame:
        """Extract XGBoost gain-based importance."""
        # Get importance
        importance_dict = model.get_score(importance_type='gain')

        # Convert to DataFrame
        importance_df = pd.DataFrame([
            {'feature': feat, 'gain': gain}
            for feat, gain in importance_dict.items()
        ]).sort_values('gain', ascending=False).reset_index(drop=True)

        # Add rank and percentages
        total_gain = importance_df['gain'].sum()
        importance_df['rank'] = range(1, len(importance_df) + 1)
        importance_df['gain_pct'] = (importance_df['gain'] / total_gain * 100).round(2)
        importance_df['cumulative_pct'] = importance_df['gain_pct'].cumsum().round(2)

        # Save CSV
        csv_path = self.artifacts_dir / 'feature_importance.csv'
        importance_df.to_csv(csv_path, index=False)

        # Plot
        self.plotter.plot_feature_importance(importance_df, top_n=20)

        # Group-level importance (if groups provided)
        if feature_groups:
            group_importance = self._compute_group_importance(importance_df, feature_groups)

        return importance_df

    def _compute_shap(self, model, X_test, feature_names, class_names) -> Dict:
        """Compute SHAP values for all classes."""
        # Tree explainer
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X_test)

        shap_results = {}

        # Per-class analysis
        for class_idx, class_name in enumerate(class_names):
            # Extract SHAP values for this class
            if isinstance(shap_values, list):
                class_shap = shap_values[class_idx]
            else:
                class_shap = shap_values[:, :, class_idx]

            # Top features by mean |SHAP|
            mean_abs_shap = np.abs(class_shap).mean(axis=0)
            top_features = pd.DataFrame({
                'feature': feature_names,
                'mean_abs_shap': mean_abs_shap
            }).sort_values('mean_abs_shap', ascending=False).head(10)

            shap_results[f'class_{class_idx}'] = {
                'top_features': top_features.to_dict('records')
            }

            # Save SHAP values (for debugging)
            np.save(self.artifacts_dir / f'shap_values_class_{class_idx}.npy', class_shap)

            # Plot SHAP summary (bar + beeswarm)
            self.plotter.plot_shap_summary(
                class_shap, X_test, class_idx, class_name
            )

        return shap_results

    def _compute_roc_pr_curves(self, y_test, y_pred_proba, class_names) -> Dict:
        """Compute ROC-AUC and PR-AUC for all classes (one-vs-rest)."""
        n_classes = len(class_names)

        roc_auc = {}
        pr_auc = {}

        for class_idx in range(n_classes):
            # Binarize: class vs rest
            y_binary = (y_test == class_idx).astype(int)
            y_score = y_pred_proba[:, class_idx]

            # ROC-AUC
            roc_auc[class_idx] = roc_auc_score(y_binary, y_score)

            # PR-AUC
            pr_auc[class_idx] = average_precision_score(y_binary, y_score)

        # Plot curves
        self.plotter.plot_roc_curves(y_test, y_pred_proba, class_names)
        self.plotter.plot_pr_curves(y_test, y_pred_proba, class_names)

        return {'roc_auc': roc_auc, 'pr_auc': pr_auc}

    def _compute_calibration(self, y_test, y_pred_proba) -> Dict:
        """Compute calibration metrics."""
        # Brier score (multi-class)
        brier = brier_score_loss(
            y_test,
            y_pred_proba[:, 1],  # For binary, use class 1 proba
            pos_label=1
        )

        # Reliability diagram (bin predicted probs vs actual frequency)
        bins = np.linspace(0, 1, 11)
        bin_results = []

        for i in range(len(bins) - 1):
            mask = (y_pred_proba.max(axis=1) >= bins[i]) & (y_pred_proba.max(axis=1) < bins[i+1])
            if mask.sum() > 0:
                predicted_class = y_pred_proba[mask].argmax(axis=1)
                actual_match = (y_test[mask].values == predicted_class).mean()
                bin_results.append({
                    'predicted_prob_range': [bins[i], bins[i+1]],
                    'actual_frequency': actual_match,
                    'count': mask.sum()
                })

        # Plot calibration curve
        self.plotter.plot_calibration_curve(bin_results)

        return {
            'brier_score': brier,
            'bins': bin_results
        }

    def _analyze_errors(self, X_test, y_test, y_pred, y_pred_proba) -> Dict:
        """Analyze misclassification patterns."""
        # False negatives for dominant class (Class 3)
        dominant_class = 3
        fn_mask = (y_test == dominant_class) & (y_pred != dominant_class)
        fn_indices = X_test[fn_mask].index

        # False positives for minority classes (Class 0-2)
        fp_mask = (y_test < dominant_class) & (y_pred == dominant_class)
        fp_indices = X_test[fp_mask].index

        # Most confident errors (high probability, wrong class)
        max_proba = y_pred_proba.max(axis=1)
        error_mask = y_test.values != y_pred
        confident_errors = np.where(error_mask & (max_proba > 0.9))[0]

        return {
            'class_3_false_negatives': {
                'count': fn_mask.sum(),
                'percentage': fn_mask.sum() / (y_test == dominant_class).sum() * 100,
                'indices': fn_indices.tolist()
            },
            'class_0_2_false_positives': {
                'count': fp_mask.sum(),
                'percentage': fp_mask.sum() / (y_test < dominant_class).sum() * 100,
                'indices': fp_indices.tolist()
            },
            'most_confident_errors': confident_errors.tolist()
        }

    def _validate_temporal_split(self, X_train, X_test) -> Dict:
        """Check for temporal leakage."""
        if 'date' not in X_train.columns or 'date' not in X_test.columns:
            return {'status': 'SKIP', 'reason': 'No date column'}

        train_max_date = X_train['date'].max()
        test_min_date = X_test['date'].min()

        overlap = test_min_date < train_max_date

        return {
            'status': 'FAIL' if overlap else 'PASS',
            'train_max_date': str(train_max_date),
            'test_min_date': str(test_min_date),
            'overlap_detected': overlap
        }

    def _save_results(self, results: Dict):
        """Save JSON results."""
        import json

        json_path = self.eval_dir / 'results.json'
        with open(json_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)

    def _generate_report(self, results: Dict):
        """Generate markdown scorecard."""
        report_generator = ReportGenerator(results, self.eval_dir)
        report_path = report_generator.generate()
        return report_path

    def _register_in_db(self, results: Dict):
        """Update ModelRegistry with evaluation metrics."""
        # Extract key metrics for registry
        metrics = results['metrics']['overall']

        # Note: Current ModelRegistry only supports regression metrics
        # TODO: Add classification metric columns to models table
        # For now, store in custom_metrics JSON field
        custom_metrics = {
            'accuracy': metrics['accuracy'],
            'weighted_f1': metrics['weighted_f1'],
            'macro_f1': metrics['macro_f1'],
            'log_loss': metrics['log_loss']
        }

        # Update registry (if schema supports it)
        # self.registry.update_metrics(self.model_version, **custom_metrics)
```

### 5.2 Plotting Library

```python
# src/evaluation/plotting.py

class EvaluationPlotter:
    """Standardized plotting for model evaluation."""

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Set matplotlib style
        plt.style.use('seaborn-v0_8-darkgrid')
        sns.set_palette("husl")

    def plot_confusion_matrix(
        self,
        cm: np.ndarray,
        class_names: List[str],
        normalize: bool = False
    ):
        """Plot confusion matrix heatmap."""
        if normalize:
            cm = cm.astype('float') / cm.sum(axis=1)[:, np.newaxis]
            fmt = '.2%'
            suffix = '_normalized'
        else:
            fmt = 'd'
            suffix = ''

        fig, ax = plt.subplots(figsize=(8, 6))
        sns.heatmap(
            cm, annot=True, fmt=fmt, cmap='Blues',
            xticklabels=class_names, yticklabels=class_names,
            ax=ax
        )
        ax.set_xlabel('Predicted Class')
        ax.set_ylabel('Actual Class')
        ax.set_title(f'Confusion Matrix{" (Normalized)" if normalize else ""}')

        output_path = self.output_dir / f'confusion_matrix{suffix}.png'
        plt.tight_layout()
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close()

    def plot_feature_importance(
        self,
        importance_df: pd.DataFrame,
        top_n: int = 20
    ):
        """Plot feature importance bar chart."""
        top_features = importance_df.head(top_n)

        fig, ax = plt.subplots(figsize=(10, 8))
        ax.barh(range(len(top_features)), top_features['gain'])
        ax.set_yticks(range(len(top_features)))
        ax.set_yticklabels(top_features['feature'])
        ax.invert_yaxis()
        ax.set_xlabel('Gain')
        ax.set_title(f'Top {top_n} Feature Importance (XGBoost Gain)')

        output_path = self.output_dir / f'feature_importance_top{top_n}.png'
        plt.tight_layout()
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close()

    def plot_shap_summary(
        self,
        shap_values: np.ndarray,
        X: pd.DataFrame,
        class_idx: int,
        class_name: str
    ):
        """Plot SHAP summary (bar + beeswarm)."""
        # Bar plot (importance)
        fig1 = plt.figure(figsize=(10, 6))
        shap.summary_plot(
            shap_values, X,
            plot_type='bar',
            max_display=15,
            show=False
        )
        plt.title(f'SHAP Importance - {class_name}')
        output_path_bar = self.output_dir / f'shap_class_{class_idx}_bar.png'
        plt.tight_layout()
        plt.savefig(output_path_bar, dpi=300, bbox_inches='tight')
        plt.close()

        # Beeswarm plot (directionality)
        fig2 = plt.figure(figsize=(10, 8))
        shap.summary_plot(
            shap_values, X,
            max_display=15,
            show=False
        )
        plt.title(f'SHAP Directionality - {class_name}')
        output_path_beeswarm = self.output_dir / f'shap_class_{class_idx}_beeswarm.png'
        plt.tight_layout()
        plt.savefig(output_path_beeswarm, dpi=300, bbox_inches='tight')
        plt.close()

    def plot_roc_curves(
        self,
        y_true: np.ndarray,
        y_pred_proba: np.ndarray,
        class_names: List[str]
    ):
        """Plot ROC curves (one-vs-rest)."""
        from sklearn.metrics import roc_curve, auc

        fig, ax = plt.subplots(figsize=(10, 8))

        for class_idx, class_name in enumerate(class_names):
            y_binary = (y_true == class_idx).astype(int)
            y_score = y_pred_proba[:, class_idx]

            fpr, tpr, _ = roc_curve(y_binary, y_score)
            roc_auc = auc(fpr, tpr)

            ax.plot(fpr, tpr, label=f'{class_name} (AUC = {roc_auc:.3f})')

        ax.plot([0, 1], [0, 1], 'k--', label='Random')
        ax.set_xlabel('False Positive Rate')
        ax.set_ylabel('True Positive Rate')
        ax.set_title('ROC Curves (One-vs-Rest)')
        ax.legend(loc='lower right')
        ax.grid(True, alpha=0.3)

        output_path = self.output_dir / 'roc_curve_multiclass.png'
        plt.tight_layout()
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close()

    def plot_pr_curves(
        self,
        y_true: np.ndarray,
        y_pred_proba: np.ndarray,
        class_names: List[str]
    ):
        """Plot Precision-Recall curves (one-vs-rest)."""
        from sklearn.metrics import precision_recall_curve, average_precision_score

        fig, ax = plt.subplots(figsize=(10, 8))

        for class_idx, class_name in enumerate(class_names):
            y_binary = (y_true == class_idx).astype(int)
            y_score = y_pred_proba[:, class_idx]

            precision, recall, _ = precision_recall_curve(y_binary, y_score)
            ap = average_precision_score(y_binary, y_score)

            ax.plot(recall, precision, label=f'{class_name} (AP = {ap:.3f})')

        ax.set_xlabel('Recall')
        ax.set_ylabel('Precision')
        ax.set_title('Precision-Recall Curves (One-vs-Rest)')
        ax.legend(loc='lower left')
        ax.grid(True, alpha=0.3)

        output_path = self.output_dir / 'pr_curve_multiclass.png'
        plt.tight_layout()
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close()

    def plot_calibration_curve(self, bin_results: List[Dict]):
        """Plot calibration curve (reliability diagram)."""
        bins = [b['predicted_prob_range'][0] for b in bin_results]
        actual_freq = [b['actual_frequency'] for b in bin_results]
        counts = [b['count'] for b in bin_results]

        fig, ax = plt.subplots(figsize=(8, 8))

        # Plot calibration
        ax.plot(bins, actual_freq, 'o-', label='Model')
        ax.plot([0, 1], [0, 1], 'k--', label='Perfect Calibration')

        # Add sample counts as text
        for i, (x, y, c) in enumerate(zip(bins, actual_freq, counts)):
            ax.text(x, y, f'n={c}', fontsize=8, ha='right')

        ax.set_xlabel('Predicted Probability')
        ax.set_ylabel('Actual Frequency')
        ax.set_title('Calibration Curve (Reliability Diagram)')
        ax.legend()
        ax.grid(True, alpha=0.3)

        output_path = self.output_dir / 'calibration_curve.png'
        plt.tight_layout()
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close()
```

---

## 6. Implementation Checklist

### Phase 1: Core Evaluator (2-3 hours)
- [ ] Create `src/evaluation/classification_evaluator.py`
  - [ ] `ClassificationEvaluator` class
  - [ ] `_compute_metrics()` method
  - [ ] `_compute_feature_importance()` method
  - [ ] `_compute_shap()` method
  - [ ] `_compute_roc_pr_curves()` method
  - [ ] `_compute_calibration()` method
  - [ ] `_analyze_errors()` method
  - [ ] `_validate_temporal_split()` method
  - [ ] `_save_results()` method
  - [ ] `_register_in_db()` method

### Phase 2: Plotting Library (1-2 hours)
- [ ] Create `src/evaluation/plotting.py`
  - [ ] `EvaluationPlotter` class
  - [ ] `plot_confusion_matrix()` method
  - [ ] `plot_feature_importance()` method
  - [ ] `plot_shap_summary()` method
  - [ ] `plot_roc_curves()` method
  - [ ] `plot_pr_curves()` method
  - [ ] `plot_calibration_curve()` method

### Phase 3: Report Generator (1 hour)
- [ ] Create `src/evaluation/report_generator_classification.py`
  - [ ] Markdown template
  - [ ] Executive summary section
  - [ ] Metrics tables
  - [ ] Plot embedding
  - [ ] Recommendations section

### Phase 4: Integration (30 min)
- [ ] Update `scripts/train_mfe_classifier.py`
  - [ ] Call `ClassificationEvaluator.evaluate()` after training
  - [ ] Pass all required parameters
  - [ ] Remove ad-hoc evaluation code
- [ ] Update `ModelRegistry`
  - [ ] Add classification metrics columns (or JSON field)

### Phase 5: Testing (30 min)
- [ ] Test on M04 baseline
- [ ] Verify all plots generated
- [ ] Verify report markdown quality
- [ ] Verify JSON structure

---

## 7. Dependencies

```python
# requirements.txt additions
shap>=0.41.0          # SHAP analysis
matplotlib>=3.5.0     # Plotting
seaborn>=0.12.0       # Heatmaps
scikit-learn>=1.0.0   # Metrics
```

---

## 8. Next Session TODOs

1. **Implement `ClassificationEvaluator`** - Core evaluation logic
2. **Implement `EvaluationPlotter`** - Visualization library
3. **Implement `ReportGenerator`** - Markdown scorecard
4. **Integrate with `train_mfe_classifier.py`** - Replace ad-hoc code
5. **Run end-to-end test** - Generate full report for M04
6. **Review output quality** - Iterate on markdown formatting

---

**Design Status**: ✅ Complete
**Ready for Implementation**: Yes
**Estimated Total Time**: 4-5 hours
**Session Break Point**: After implementation, before testing
