"""
Quick test script to verify training setup before full run.

This script checks:
1. Dataset availability and structure
2. Feature selection logic
3. Temporal splitting logic
4. Module imports (without ML libraries)

Run this BEFORE installing ML dependencies to catch any issues.
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
import io

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

print("=" * 80)
print(" TRAINING SETUP VERIFICATION")
print("=" * 80)

# Test 1: Dataset loading
print("\n[1/5] Testing dataset loading...")
dataset_path = 'data/ml/training_dataset_final.parquet'

if not Path(dataset_path).exists():
    print(f"  ❌ Dataset not found: {dataset_path}")
    print("  Please run: python prepare_training_dataset.py --start 2021-01-01 --end 2025-11-28")
    sys.exit(1)

df = pd.read_parquet(dataset_path)
print(f"  ✅ Dataset loaded: {len(df):,} rows × {len(df.columns)} columns")
print(f"  Date range: {df['entry_date'].min().date()} to {df['entry_date'].max().date()}")
print(f"  Label distribution: {df['label'].value_counts().to_dict()}")

# Test 2: Feature detection
print("\n[2/5] Testing feature detection...")
exclude_cols = [
    # Core metadata
    'date', 'ticker', 'trade_id', 'entry_date', 'exit_date',
    # Labels and outcomes
    'label', 'return_pct', 'days_held', 'exit_reason',
    # Trade details
    'entry_price', 'exit_price', 'stop_price',
    'max_drawdown_pct', 'max_favorable_excursion_pct',
    'r_multiple', 'sharpe_ratio', 'initial_risk_pct',
    # Simulation metadata
    'simulation_start', 'simulation_end', 'success_threshold_pct',
    # Fundamental metadata (dates, identifiers)
    'fiscal_date', 'filing_date_matched', 'fiscal_period',
    'symbol', 'fiscalYear', 'accepted_date', 'reportedCurrency',
    'cik', 'statement_type'
]

# Get only numeric columns
numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
feature_cols = [col for col in numeric_cols if col not in exclude_cols]

print(f"  ✅ Found {len(feature_cols)} numeric feature columns")
print(f"  ℹ️  Excluded {len(df.columns) - len(feature_cols)} non-numeric/metadata columns")

# Check for 100% missing features
missing_pct = df[feature_cols].isnull().mean()
fully_missing = missing_pct[missing_pct > 0.99].index.tolist()
if fully_missing:
    print(f"  ⚠️  Features with >99% missing values: {fully_missing}")
else:
    print(f"  ✅ No features with excessive missing values")

# Test 3: Temporal splitting logic
print("\n[3/5] Testing temporal splitting logic...")
df['entry_date'] = pd.to_datetime(df['entry_date'])

fold_specs = [
    ('2021-01-01', '2022-12-31', '2023-12-31'),
    ('2021-01-01', '2023-12-31', '2025-12-31')
]

purge_gap_days = 60

for fold_idx, (train_start, train_end, test_end) in enumerate(fold_specs, 1):
    train_start_dt = pd.to_datetime(train_start)
    train_end_dt = pd.to_datetime(train_end)
    test_start_dt = train_end_dt + pd.Timedelta(days=purge_gap_days)
    test_end_dt = pd.to_datetime(test_end)

    train_mask = (df['entry_date'] >= train_start_dt) & (df['entry_date'] <= train_end_dt)
    test_mask = (df['entry_date'] > test_start_dt) & (df['entry_date'] <= test_end_dt)

    n_train = train_mask.sum()
    n_test = test_mask.sum()

    print(f"  Fold {fold_idx}:")
    print(f"    Train: {train_start_dt.date()} to {train_end_dt.date()} ({n_train} samples)")
    print(f"    Test: {test_start_dt.date()} to {test_end_dt.date()} ({n_test} samples)")

    if n_train == 0 or n_test == 0:
        print(f"    ❌ Empty fold!")
    else:
        print(f"    ✅ Valid fold")

# Test 4: Correlation calculation
print("\n[4/5] Testing correlation calculation...")
numeric_cols = df[feature_cols].select_dtypes(include=[np.number]).columns[:20]  # Sample 20
if len(numeric_cols) > 1:
    sample_corr = df[numeric_cols].corr(method='spearman').abs()
    high_corr_pairs = []
    for i in range(len(sample_corr.columns)):
        for j in range(i+1, len(sample_corr.columns)):
            if sample_corr.iloc[i, j] > 0.95:
                high_corr_pairs.append((sample_corr.columns[i], sample_corr.columns[j], sample_corr.iloc[i, j]))

    if high_corr_pairs:
        print(f"  ✅ Found {len(high_corr_pairs)} highly correlated pairs (sample of 20 features)")
        print(f"     Example: {high_corr_pairs[0][0]} <-> {high_corr_pairs[0][1]} (corr={high_corr_pairs[0][2]:.3f})")
    else:
        print(f"  ✅ No highly correlated pairs in sample")
else:
    print(f"  ⚠️  Not enough numeric features for correlation test")

# Test 5: Module structure
print("\n[5/5] Testing module structure...")
required_modules = [
    'src/model_preparation.py',
    'src/train_model.py',
    'src/evaluate_model.py'
]

all_exist = True
for module_path in required_modules:
    if Path(module_path).exists():
        print(f"  ✅ {module_path}")
    else:
        print(f"  ❌ {module_path} - NOT FOUND")
        all_exist = False

if not all_exist:
    print("\n❌ Some modules are missing!")
    sys.exit(1)

# Test 6: Check ML dependencies
print("\n[6/6] Checking ML dependencies...")
missing_deps = []

try:
    import xgboost
    print(f"  ✅ xgboost ({xgboost.__version__})")
except ImportError:
    print(f"  ❌ xgboost - NOT INSTALLED")
    missing_deps.append('xgboost')

try:
    import optuna
    print(f"  ✅ optuna ({optuna.__version__})")
except ImportError:
    print(f"  ⚠️  optuna - NOT INSTALLED (optional, but recommended)")
    missing_deps.append('optuna')

try:
    import shap
    print(f"  ✅ shap ({shap.__version__})")
except ImportError:
    print(f"  ⚠️  shap - NOT INSTALLED (optional, feature importance will use gain)")
    missing_deps.append('shap')

try:
    import sklearn
    print(f"  ✅ scikit-learn ({sklearn.__version__})")
except ImportError:
    print(f"  ❌ scikit-learn - NOT INSTALLED")
    missing_deps.append('scikit-learn')

# Final summary
print("\n" + "=" * 80)
if missing_deps:
    print(" SETUP INCOMPLETE - Missing Dependencies")
    print("=" * 80)
    print("\nPlease install missing packages:")
    print(f"  pip install {' '.join(missing_deps)}")
    print("\nOr install all ML dependencies:")
    print("  pip install -r requirements_ml.txt")
    print("\n" + "=" * 80)
else:
    print(" SETUP COMPLETE - Ready for Training")
    print("=" * 80)
    print("\nYou can now run:")
    print("  python train_sepa_model.py --dataset data/ml/training_dataset_final.parquet")
    print("\nFor full optimization:")
    print("  python train_sepa_model.py --dataset data/ml/training_dataset_final.parquet --optimize --n-trials 50")
    print("\n" + "=" * 80)
