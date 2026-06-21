# M04 Evaluation Framework - Implementation Plan

**Status**: Design Complete ✅ | Implementation Pending ⏳
**Document**: [Full Design Spec](../../docs/proposals/classification_evaluation_framework.md)
**Estimated Effort**: 4-5 hours

---

## Quick Reference

### What We're Building

A reusable `ClassificationEvaluator` that generates:
1. **JSON results** - Machine-readable metrics (`evaluation/results.json`)
2. **Markdown report** - Human-readable scorecard (`evaluation/report.md`)
3. **Visualizations** - 10+ PNG plots (`evaluation/plots/*.png`)
4. **Raw artifacts** - SHAP values, predictions CSV (`evaluation/artifacts/`)

### Output Structure
```
models/m04_baseline/
└── evaluation/
    ├── results.json              ← All metrics (JSON)
    ├── report.md                 ← Scorecard (Markdown)
    ├── plots/
    │   ├── confusion_matrix.png
    │   ├── confusion_matrix_normalized.png
    │   ├── feature_importance_top20.png
    │   ├── shap_class_{0-3}_bar.png
    │   ├── shap_class_{0-3}_beeswarm.png
    │   ├── roc_curve_multiclass.png
    │   ├── pr_curve_multiclass.png
    │   └── calibration_curve.png
    └── artifacts/
        ├── shap_values_class_{0-3}.npy
        ├── predictions.csv
        └── feature_importance.csv
```

---

## Report Preview (Markdown Structure)

```markdown
# M04 MFE Classifier - Evaluation Report

## 1. Executive Summary
- Model overview (task, algorithm, features)
- Performance summary table
- Viability assessment

## 2. Classification Metrics
- Overall performance (accuracy, F1, log loss)
- Per-class metrics (precision, recall, F1, ROC-AUC)
- Confusion matrix (raw + normalized)

## 3. Feature Importance
- XGBoost gain-based importance (top 20)
- Group-level importance
- SHAP analysis (per-class directionality)

## 4. ROC & PR Curves
- One-vs-rest ROC curves with AUC
- Precision-Recall curves with AP

## 5. Model Calibration
- Reliability diagram
- Brier score
- Calibration bins

## 6. Temporal Validation
- Train/val/test date ranges
- Leakage check (PASS/FAIL)
- Train/test performance gap

## 7. Error Analysis
- Misclassification patterns
- Most confident errors
- Common failure modes

## 8. Recommendations
- Immediate actions (before production)
- Model improvements (next iteration)
- Deployment constraints
```

---

## Implementation Checklist

### Phase 1: Core Evaluator (2-3 hours)
```python
# src/evaluation/classification_evaluator.py

class ClassificationEvaluator:
    def evaluate(model, X_test, y_test, ...) -> Dict:
        # 1. Compute metrics
        # 2. Feature importance
        # 3. SHAP analysis
        # 4. ROC/PR curves
        # 5. Calibration
        # 6. Error analysis
        # 7. Save JSON + plots + artifacts
        # 8. Generate markdown report
```

### Phase 2: Plotting Library (1-2 hours)
```python
# src/evaluation/plotting.py

class EvaluationPlotter:
    def plot_confusion_matrix(...)
    def plot_feature_importance(...)
    def plot_shap_summary(...)
    def plot_roc_curves(...)
    def plot_pr_curves(...)
    def plot_calibration_curve(...)
```

### Phase 3: Report Generator (1 hour)
```python
# src/evaluation/report_generator_classification.py

class ReportGenerator:
    def generate(results: Dict) -> Path:
        # Build markdown from template
        # Embed plots
        # Format tables
```

### Phase 4: Integration (30 min)
```python
# scripts/train_mfe_classifier.py (updated)

# After training:
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
    feature_names=valid_features,
    class_names=['Noise', 'Moderate', 'Strong', 'Home Run'],
    feature_groups=FEATURE_GROUPS
)

# Auto-saves: JSON, markdown, plots, artifacts
```

---

## Key Metrics in Report

### Overall Performance
| Metric | Value |
|--------|-------|
| Test Accuracy | 66.5% |
| Weighted F1 | 0.571 |
| Macro F1 | 0.232 |
| Log Loss | 0.918 |

### Per-Class Performance
| Class | Precision | Recall | F1 | ROC-AUC |
|-------|-----------|--------|-----|---------|
| 0 (Noise) | 0.00 | 0.00 | 0.00 | 0.523 |
| 1 (Moderate) | 0.00 | 0.00 | 0.00 | 0.547 |
| 2 (Strong) | 0.18 | 0.08 | 0.11 | 0.612 |
| 3 (Home Run) | 0.71 | 0.97 | 0.82 | 0.845 |

### Feature Importance (Top 5)
| Rank | Feature | Gain % |
|------|---------|--------|
| 1 | m03_score | 12.3% |
| 2 | rs_rating | 9.9% |
| 3 | alpha101 | 8.8% |
| 4 | breakout_momentum | 7.7% |
| 5 | dist_from_52w_high | 6.5% |

### SHAP Analysis (Class 3 - Home Runs)
| Feature | Mean |SHAP| | Direction |
|---------|------------|-----------|
| m03_score | 0.145 | High regime → Home run |
| rs_rating | 0.132 | Strong RS → Home run |
| breakout_momentum | 0.118 | Strong thrust → Home run |

---

## Dependencies

```bash
pip install shap>=0.41.0 matplotlib>=3.5.0 seaborn>=0.12.0
```

---

## Next Session

1. Implement `ClassificationEvaluator` class
2. Implement `EvaluationPlotter` class
3. Implement `ReportGenerator` class
4. Update `train_mfe_classifier.py` to use new evaluator
5. Run end-to-end test on M04 baseline
6. Review generated report quality

**Estimated Time**: 4-5 hours
**Break Point**: After implementation, before iterating on report formatting
