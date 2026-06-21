# Model Evaluation Framework - Quick Start Guide

## For Classification Models (M04+)

### Basic Usage

```python
from pathlib import Path
from src.evaluation import ClassificationEvaluator

# 1. Initialize evaluator
evaluator = ClassificationEvaluator(
    model_name='m04_baseline',           # Model identifier
    model_version='v1',                   # Version string
    output_dir=Path('models'),            # Base output directory
    class_names=['Class 0', 'Class 1', 'Class 2', 'Class 3']  # Optional labels
)

# 2. Run evaluation
metrics = evaluator.evaluate(
    model=trained_xgb_model,              # XGBoost Booster
    X_test=X_test,                        # Test features (DataFrame)
    y_test=y_test,                        # Test labels (Series or array)
    feature_names=feature_list,           # List of feature names
    X_train=X_train,                      # Optional: for class distribution plot
    y_train=y_train,                      # Optional: training labels
    X_val=X_val,                          # Optional: validation features
    y_val=y_val,                          # Optional: validation labels
    compute_shap=True,                    # Enable SHAP analysis (default: True)
    shap_sample_size=1000                 # Max samples for SHAP (default: 1000)
)

# 3. Access results
print(f"Accuracy: {metrics['accuracy']:.3f}")
print(f"Weighted F1: {metrics['weighted_f1']:.3f}")
print(f"Report: {evaluator.eval_dir / 'report_*.md'}")
```

### Outputs

```
models/
└── m04_baseline/
    └── v1/
        └── evaluation/
            ├── results.json                    # All metrics (JSON)
            ├── report_YYYYMMDD_HHMMSS.md      # Markdown scorecard
            ├── confusion_matrix.png            # Confusion matrix (counts)
            ├── confusion_matrix_normalized.png # Confusion matrix (percentages)
            ├── feature_importance.png          # Top 20 features
            ├── roc_curves.png                  # ROC curves (one-vs-rest)
            ├── pr_curves.png                   # Precision-Recall curves
            ├── calibration_curves.png          # Calibration curves
            └── class_distribution.png          # Class distribution across splits
```

---

## Temporal Leakage Detection

### Validate Train/Test Split

```python
from src.evaluation import LeakageGuard
import numpy as np

# 1. Create split indices
train_indices = np.arange(0, 1000)
val_indices = np.arange(1000, 1300)
test_indices = np.arange(1300, 1500)

# 2. Validate temporal ordering
leakage_check = LeakageGuard.validate_split_ordering(
    df,                    # Full dataframe with date column
    'date',                # Name of date column
    train_indices,
    val_indices,
    test_indices
)

# 3. Check results
if not leakage_check['all_valid']:
    raise ValueError("Temporal leakage detected!")
```

### Check Feature Names for Leakage

```python
feature_check = LeakageGuard.check_feature_leakage(
    feature_names=['price', 'volume', 'return_1d'],  # Your features
    forbidden_patterns=['mfe', 'mae', 'return_at_exit', 'outcome_']
)

if not feature_check['is_clean']:
    print(f"Suspicious features: {feature_check['suspicious_features']}")
```

### Create Temporal Split Automatically

```python
train_idx, val_idx, test_idx = LeakageGuard.create_temporal_split(
    df,
    date_col='date',
    train_frac=0.6,
    val_frac=0.2,
    test_frac=0.2
)

# Returns validated chronological split
```

---

## Visualization Only

### Plot Confusion Matrix

```python
from src.evaluation import EvaluationPlotter
from pathlib import Path

plotter = EvaluationPlotter()

# Counts
plotter.plot_confusion_matrix(
    cm=confusion_matrix,
    class_names=['Noise', 'Moderate', 'Strong', 'Home Run'],
    output_path=Path('confusion_matrix.png'),
    normalize=False
)

# Percentages
plotter.plot_confusion_matrix(
    cm=confusion_matrix,
    class_names=['Noise', 'Moderate', 'Strong', 'Home Run'],
    output_path=Path('confusion_matrix_pct.png'),
    normalize=True
)
```

### Plot Feature Importance

```python
import pandas as pd

importance_df = pd.DataFrame({
    'feature': ['feature_1', 'feature_2', 'feature_3'],
    'gain': [0.5, 0.3, 0.2]
})

plotter.plot_feature_importance(
    importance_df=importance_df,
    output_path=Path('feature_importance.png'),
    top_n=20
)
```

### Plot ROC/PR Curves

```python
# ROC curves (one-vs-rest)
plotter.plot_roc_curve_multiclass(
    y_true=y_test,
    y_pred_proba=predictions,  # Shape: (n_samples, n_classes)
    class_names=['Class 0', 'Class 1', 'Class 2', 'Class 3'],
    output_path=Path('roc_curves.png')
)

# Precision-Recall curves
plotter.plot_pr_curve_multiclass(
    y_true=y_test,
    y_pred_proba=predictions,
    class_names=['Class 0', 'Class 1', 'Class 2', 'Class 3'],
    output_path=Path('pr_curves.png')
)
```

### Plot Calibration Curves

```python
plotter.plot_calibration_curve(
    y_true=y_test,
    y_pred_proba=predictions,
    class_names=['Class 0', 'Class 1', 'Class 2', 'Class 3'],
    output_path=Path('calibration.png'),
    n_bins=10
)
```

### Plot Class Distribution

```python
plotter.plot_class_distribution(
    y_train=y_train,
    y_val=y_val,
    y_test=y_test,
    class_names=['Class 0', 'Class 1', 'Class 2', 'Class 3'],
    output_path=Path('class_distribution.png')
)
```

---

## Advanced: Custom Evaluator

### Extend BaseEvaluator

```python
from src.evaluation import BaseEvaluator
from pathlib import Path
from typing import Dict, Any

class MyCustomEvaluator(BaseEvaluator):
    """Custom evaluator for my model type."""

    def __init__(self, model_name: str, model_version: str, output_dir: Path):
        super().__init__(model_name, model_version, output_dir)
        # Add custom initialization

    def evaluate(self, **kwargs) -> Dict[str, Any]:
        """Custom evaluation logic."""
        # 1. Compute metrics
        metrics = {
            'custom_metric_1': 0.95,
            'custom_metric_2': 0.87
        }

        # 2. Generate plots
        # ... use EvaluationPlotter ...

        # 3. Save results
        self.save_results(metrics, self.plots, update_registry=True)

        return metrics

    def generate_report(self, metrics: Dict, plots: Dict) -> Path:
        """Custom report generation."""
        report_path = self.eval_dir / 'custom_report.md'

        # Generate markdown content
        lines = [
            f"# {self.model_name} Report",
            f"**Version:** {self.model_version}",
            "",
            "## Metrics",
            f"- Custom Metric 1: {metrics['custom_metric_1']:.3f}",
            f"- Custom Metric 2: {metrics['custom_metric_2']:.3f}"
        ]

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        return report_path
```

---

## Performance Optimization

### 1. Disable SHAP for Large Datasets

```python
# Fast evaluation (no SHAP)
metrics = evaluator.evaluate(
    model=model,
    X_test=X_test,
    y_test=y_test,
    feature_names=features,
    compute_shap=False  # Skip SHAP computation
)
```

### 2. Reduce SHAP Sample Size

```python
# Use smaller sample for SHAP
metrics = evaluator.evaluate(
    model=model,
    X_test=X_test,
    y_test=y_test,
    feature_names=features,
    compute_shap=True,
    shap_sample_size=500  # Default: 1000
)
```

### 3. Batch Evaluation

```python
# Evaluate multiple models in sequence
models = {
    'v1': model_v1,
    'v2': model_v2,
    'v3': model_v3
}

for version, model in models.items():
    evaluator = ClassificationEvaluator(
        model_name='m04_baseline',
        model_version=version,
        output_dir=Path('models')
    )

    evaluator.evaluate(
        model=model,
        X_test=X_test,
        y_test=y_test,
        feature_names=features,
        compute_shap=False  # Disable for speed
    )
```

---

## Troubleshooting

### Issue: UnicodeEncodeError when generating report

**Cause:** Windows default encoding (cp1252) doesn't support emojis

**Solution:** Already fixed in v1 - report uses UTF-8 encoding

**Workaround (if needed):**
```python
import locale
locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
```

---

### Issue: Feature importance plot missing

**Cause:** XGBoost model has no feature names

**Solution:** Pass feature_names to DMatrix during training:
```python
dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=feature_names)
```

**Alternative:** Evaluator will use feature indices (f0, f1, ...) if names not available

---

### Issue: SHAP computation is slow

**Cause:** Large dataset (>10,000 samples)

**Solution:** Reduce sample size:
```python
evaluator.evaluate(
    ...,
    compute_shap=True,
    shap_sample_size=500  # Reduce from default 1000
)
```

**Alternative:** Disable SHAP:
```python
evaluator.evaluate(
    ...,
    compute_shap=False
)
```

---

### Issue: Class distribution plot shows empty bars

**Cause:** Training/validation data not provided

**Solution:** Pass X_train, y_train, X_val, y_val to evaluator:
```python
evaluator.evaluate(
    model=model,
    X_test=X_test,
    y_test=y_test,
    feature_names=features,
    X_train=X_train,      # Add these
    y_train=y_train,      # Add these
    X_val=X_val,          # Add these
    y_val=y_val           # Add these
)
```

---

## Example: Complete M04 Training Script

See [scripts/train_mfe_classifier.py](../scripts/train_mfe_classifier.py) for a complete example including:
- Data loading from DuckDB
- Temporal split creation
- Leakage validation
- XGBoost training
- Comprehensive evaluation
- Model registry integration

**Run:**
```bash
python scripts/train_mfe_classifier.py
```

---

## API Reference

### ClassificationEvaluator

```python
class ClassificationEvaluator(BaseEvaluator):
    """Multi-class classification evaluator."""

    def __init__(
        self,
        model_name: str,
        model_version: str,
        output_dir: Path,
        class_names: Optional[List[str]] = None,
        db_path: Optional[Path] = None
    )

    def evaluate(
        self,
        model: xgb.Booster,
        X_test: pd.DataFrame,
        y_test: pd.Series,
        feature_names: List[str],
        X_train: Optional[pd.DataFrame] = None,
        y_train: Optional[np.ndarray] = None,
        X_val: Optional[pd.DataFrame] = None,
        y_val: Optional[np.ndarray] = None,
        compute_shap: bool = True,
        shap_sample_size: int = 1000
    ) -> Dict[str, Any]
```

**Returns:**
```python
{
    'accuracy': float,
    'weighted_f1': float,
    'macro_f1': float,
    'micro_f1': float,
    'test_samples': int,
    'confusion_matrix': List[List[int]],
    'classification_report': Dict,
    'per_class_metrics': Dict[str, Dict],
    'feature_importance': List[Dict],
    'roc_auc_per_class': Dict[str, float],
    'pr_auc_per_class': Dict[str, float],
    'brier_score': Dict[str, float],
    'shap_summary': Dict  # Optional
}
```

---

### LeakageGuard

```python
class LeakageGuard:
    """Temporal leakage detection."""

    @staticmethod
    def validate_temporal_split(
        df: pd.DataFrame,
        date_col: str,
        train_indices: np.ndarray,
        test_indices: np.ndarray,
        strict: bool = True
    ) -> Dict

    @staticmethod
    def validate_split_ordering(
        df: pd.DataFrame,
        date_col: str,
        train_indices: np.ndarray,
        val_indices: np.ndarray,
        test_indices: np.ndarray
    ) -> Dict

    @staticmethod
    def check_feature_leakage(
        feature_names: List[str],
        forbidden_patterns: List[str] = None
    ) -> Dict

    @staticmethod
    def create_temporal_split(
        df: pd.DataFrame,
        date_col: str,
        train_frac: float = 0.6,
        val_frac: float = 0.2,
        test_frac: float = 0.2
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]
```

---

### EvaluationPlotter

```python
class EvaluationPlotter:
    """Standardized plotting utilities."""

    @staticmethod
    def plot_confusion_matrix(
        cm: np.ndarray,
        class_names: List[str],
        output_path: Path,
        normalize: bool = False,
        title: str = "Confusion Matrix"
    ) -> Path

    @staticmethod
    def plot_feature_importance(
        importance_df: pd.DataFrame,
        output_path: Path,
        top_n: int = 20,
        title: str = "Feature Importance"
    ) -> Path

    @staticmethod
    def plot_roc_curve_multiclass(...) -> Path

    @staticmethod
    def plot_pr_curve_multiclass(...) -> Path

    @staticmethod
    def plot_calibration_curve(...) -> Path

    @staticmethod
    def plot_class_distribution(...) -> Path
```

---

## Best Practices

1. **Always validate temporal splits** before training
2. **Check for feature leakage** in your feature list
3. **Use descriptive class names** for better reports
4. **Provide train/val data** for complete analysis
5. **Disable SHAP** for quick iterations, enable for final evaluation
6. **Review generated reports** before deploying models
7. **Compare multiple versions** side-by-side

---

For more details, see [Implementation Summary](evaluation_framework_implementation.md)
