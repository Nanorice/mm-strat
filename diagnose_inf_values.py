"""
Diagnostic script to find which features have infinite values.
"""

import pandas as pd
import numpy as np
import sys
import io
from pathlib import Path

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Load dataset
dataset_path = 'data/ml/training_dataset_final.parquet'
print(f"Loading {dataset_path}...")
df = pd.read_parquet(dataset_path)

print(f"Dataset shape: {df.shape}")
print(f"\nChecking for infinite values...")

# Get numeric columns only
exclude_cols = [
    'date', 'ticker', 'trade_id', 'entry_date', 'exit_date',
    'label', 'return_pct', 'days_held', 'exit_reason',
    'entry_price', 'exit_price', 'stop_price',
    'max_drawdown_pct', 'max_favorable_excursion_pct',
    'r_multiple', 'sharpe_ratio', 'initial_risk_pct',
    'simulation_start', 'simulation_end', 'success_threshold_pct',
    'fiscal_date', 'filing_date_matched', 'fiscal_period',
    'symbol', 'fiscalYear', 'accepted_date', 'reportedCurrency',
    'cik', 'statement_type'
]

numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
feature_cols = [col for col in numeric_cols if col not in exclude_cols]

print(f"\nChecking {len(feature_cols)} numeric feature columns...")

# Check for inf values
inf_features = {}
for col in feature_cols:
    inf_mask = np.isinf(df[col])
    inf_count = inf_mask.sum()
    if inf_count > 0:
        inf_features[col] = {
            'count': inf_count,
            'pct': (inf_count / len(df)) * 100,
            'pos_inf': (df[col] == np.inf).sum(),
            'neg_inf': (df[col] == -np.inf).sum()
        }

if inf_features:
    print(f"\n❌ Found infinite values in {len(inf_features)} features:")
    print("=" * 80)
    for feat, info in sorted(inf_features.items(), key=lambda x: x[1]['count'], reverse=True):
        print(f"\n{feat}:")
        print(f"  Total inf: {info['count']:,} ({info['pct']:.2f}%)")
        print(f"  +inf: {info['pos_inf']:,}")
        print(f"  -inf: {info['neg_inf']:,}")

        # Show some sample values
        sample_vals = df[col][~np.isinf(df[col])].dropna().head(5).values
        print(f"  Sample non-inf values: {sample_vals}")
else:
    print("\n✅ No infinite values found in feature columns!")

# Also check if any inf values after transform would happen
print("\n" + "=" * 80)
print("Testing feature selector transform...")

from src.model_preparation import FeatureSelector

selector = FeatureSelector(correlation_threshold=0.95)

# Simulate fit_transform on train data (first 800 rows)
X_train = df[feature_cols].iloc[:800]
y_train = df['label'].iloc[:800]

print(f"\nFitting selector on {len(X_train)} samples...")
X_train_selected = selector.fit_transform(X_train, y_train)
print(f"Selected {len(X_train_selected.columns)} features")

# Check for inf in selected features
inf_in_selected = {}
for col in X_train_selected.columns:
    inf_count = np.isinf(X_train_selected[col]).sum()
    if inf_count > 0:
        inf_in_selected[col] = inf_count

if inf_in_selected:
    print(f"\n❌ After fit_transform, still have inf in {len(inf_in_selected)} features:")
    for feat, count in sorted(inf_in_selected.items(), key=lambda x: x[1], reverse=True):
        print(f"  {feat}: {count} inf values")
else:
    print("\n✅ After fit_transform, no inf values in selected features")

# Now test transform on test data (remaining rows)
X_test = df[feature_cols].iloc[800:]
print(f"\nTransforming test data ({len(X_test)} samples)...")
X_test_selected = selector.transform(X_test)

inf_in_test = {}
for col in X_test_selected.columns:
    inf_count = np.isinf(X_test_selected[col]).sum()
    if inf_count > 0:
        inf_in_test[col] = inf_count

if inf_in_test:
    print(f"\n❌ After transform (test), still have inf in {len(inf_in_test)} features:")
    for feat, count in sorted(inf_in_test.items(), key=lambda x: x[1], reverse=True):
        print(f"  {feat}: {count} inf values")
else:
    print("\n✅ After transform (test), no inf values")

print("\n" + "=" * 80)
print("Diagnosis complete!")
