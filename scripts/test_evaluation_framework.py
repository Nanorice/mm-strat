"""Test Evaluation Framework - Quick validation of ClassificationEvaluator.

Runs a minimal test to ensure all components work together:
- BaseEvaluator initialization
- EvaluationPlotter (all plot types)
- LeakageGuard (temporal validation)
- ClassificationEvaluator (full pipeline)

Uses synthetic data for speed.
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.datasets import make_classification
from datetime import datetime, timedelta

sys.path.append(str(Path(__file__).parent.parent))
from src.evaluation.classification_evaluator import ClassificationEvaluator
from src.evaluation.leakage_guard import LeakageGuard

print("=" * 80)
print("EVALUATION FRAMEWORK TEST")
print("=" * 80)

# 1. Create synthetic classification dataset
print("\n1. Creating synthetic dataset...")
X, y = make_classification(
    n_samples=1000,
    n_features=20,
    n_informative=15,
    n_redundant=3,
    n_classes=4,
    random_state=42
)

# Add feature names
feature_names = [f"feature_{i}" for i in range(20)]
X_df = pd.DataFrame(X, columns=feature_names)

# Add date column for temporal validation
dates = [datetime(2020, 1, 1) + timedelta(days=i) for i in range(len(X))]
X_df['date'] = dates

# Add categorical features
X_df['sector'] = np.random.choice(['Tech', 'Healthcare', 'Finance'], size=len(X))
X_df['industry'] = np.random.choice(['Software', 'Pharma', 'Banking'], size=len(X))

print(f"   Dataset: {len(X)} samples, {len(feature_names)} features, 4 classes")

# 2. Temporal split
print("\n2. Creating temporal train/val/test split...")
train_size = int(len(X) * 0.6)
val_size = int(len(X) * 0.2)

X_train = X_df.iloc[:train_size][feature_names].copy()
y_train = y[:train_size]

X_val = X_df.iloc[train_size:train_size + val_size][feature_names].copy()
y_val = y[train_size:train_size + val_size]

X_test = X_df.iloc[train_size + val_size:][feature_names].copy()
y_test = y[train_size + val_size:]

print(f"   Train: {len(X_train)}, Val: {len(X_val)}, Test: {len(X_test)}")

# 3. Validate temporal split
print("\n3. Validating temporal split...")
train_indices = np.arange(0, train_size)
val_indices = np.arange(train_size, train_size + val_size)
test_indices = np.arange(train_size + val_size, len(X))

leakage_result = LeakageGuard.validate_split_ordering(
    X_df,
    'date',
    train_indices,
    val_indices,
    test_indices
)

if not leakage_result['all_valid']:
    print("   ERROR: Temporal leakage detected!")
    sys.exit(1)

print("   Temporal validation: PASSED")

# 4. Check feature leakage
print("\n4. Checking for feature leakage...")
feature_check = LeakageGuard.check_feature_leakage(feature_names)
print(f"   Feature check: {'CLEAN' if feature_check['is_clean'] else 'SUSPICIOUS'}")

# 5. Train simple XGBoost model
print("\n5. Training XGBoost classifier...")
dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=feature_names)
dval = xgb.DMatrix(X_val, label=y_val, feature_names=feature_names)

params = {
    'objective': 'multi:softprob',
    'num_class': 4,
    'max_depth': 3,
    'learning_rate': 0.1,
    'eval_metric': 'mlogloss',
    'random_state': 42,
    'tree_method': 'hist'
}

model = xgb.train(
    params=params,
    dtrain=dtrain,
    num_boost_round=20,
    evals=[(dval, 'val')],
    verbose_eval=False
)

print("   Model trained successfully")

# 6. Run comprehensive evaluation
print("\n6. Running ClassificationEvaluator...")
output_dir = Path(__file__).parent.parent / "models" / "test_evaluation"
output_dir.mkdir(parents=True, exist_ok=True)

class_names = ['Class 0', 'Class 1', 'Class 2', 'Class 3']

evaluator = ClassificationEvaluator(
    model_name='test_model',
    model_version='v1',
    output_dir=output_dir,
    class_names=class_names
)

metrics = evaluator.evaluate(
    model=model,
    X_test=X_test,
    y_test=y_test,
    feature_names=feature_names,
    X_train=X_train,
    y_train=y_train,
    X_val=X_val,
    y_val=y_val,
    compute_shap=True,
    shap_sample_size=100  # Small sample for speed
)

# 7. Verify outputs
print("\n7. Verifying outputs...")
eval_dir = evaluator.eval_dir

expected_files = [
    'results.json',
    'confusion_matrix.png',
    'confusion_matrix_normalized.png',
    'feature_importance.png',
    'roc_curves.png',
    'pr_curves.png',
    'calibration_curves.png',
    'class_distribution.png'
]

missing_files = []
for filename in expected_files:
    filepath = eval_dir / filename
    if not filepath.exists():
        missing_files.append(filename)
    else:
        print(f"   [OK] {filename}")

if missing_files:
    print(f"\n   [ERROR] Missing files: {missing_files}")
    sys.exit(1)

# Check report
report_files = list(eval_dir.glob('report_*.md'))
if not report_files:
    print("\n   [ERROR] No report generated")
    sys.exit(1)
else:
    print(f"   [OK] Report: {report_files[0].name}")

# 8. Summary
print("\n" + "=" * 80)
print("EVALUATION FRAMEWORK TEST: PASSED")
print("=" * 80)
print(f"\nTest Accuracy: {metrics['accuracy']:.3f}")
print(f"Weighted F1: {metrics['weighted_f1']:.3f}")
print(f"Macro F1: {metrics['macro_f1']:.3f}")
print(f"\nOutputs saved to: {eval_dir}")
print("\n[OK] All components working correctly!")
