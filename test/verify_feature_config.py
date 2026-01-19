"""
Feature Config Verification Script

Verifies that feature_config.py is in sync with the d2 dataset.
Checks for:
1. Features in config but missing from d2
2. Features in d2 but missing from config
"""

import pandas as pd
import sys
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent))

from src.feature_config import TECHNICAL_FEATURES, FUNDAMENTAL_FEATURES, ALPHA_FEATURES, FEATURES_TO_LAG

def verify_feature_config():
    """Verify feature config completeness against d2 dataset."""
    
    print("=" * 70)
    print("FEATURE CONFIG VERIFICATION")
    print("=" * 70)
    
    # Load d2 dataset
    d2_path = Path("data/ml/d2_features.parquet")
    if not d2_path.exists():
        print(f"❌ D2 dataset not found at {d2_path}")
        print("   Run: python model_trainer.py --steps d2 --start 2020-01-01 --end 2023-12-31")
        return
    
    d2 = pd.read_parquet(d2_path)
    print(f"✅ Loaded d2 dataset: {len(d2)} rows, {len(d2.columns)} columns\n")
    
    # Get all declared features from config
    declared_features = set(TECHNICAL_FEATURES + FUNDAMENTAL_FEATURES + ALPHA_FEATURES)
    
    # Add lagged versions
    for feat in FEATURES_TO_LAG:
        declared_features.add(f"{feat}_Lag1")
    
    print(f"📋 Declared features in config: {len(declared_features)}")
    
    # Get features in d2 (exclude metadata columns)
    metadata_cols = {'date', 'ticker', 'label', 'return_pct', 'days_held', 'exit_reason',
                     'Open', 'High', 'Low', 'Close', 'Volume'}
    d2_features = set(d2.columns) - metadata_cols
    
    print(f"📊 Features in d2 dataset: {len(d2_features)}\n")
    
    # Check 1: Features in config but missing from d2
    missing_in_d2 = declared_features - d2_features
    if missing_in_d2:
        print(f"⚠️  Features declared in config but MISSING in d2 ({len(missing_in_d2)}):")
        for feat in sorted(missing_in_d2):
            print(f"   - {feat}")
        print()
    else:
        print("✅ All config features present in d2\n")
    
    # Check 2: Features in d2 but not in config
    not_in_config = d2_features - declared_features
    
    # Filter out known supporting features and intermediate calculations
    known_supporting = {'SMA_50', 'SMA_150', 'SMA_200', 'Vol_MA', 'ATR',
                        'sector_id', 'industry_id', 'mktCap_log', 'beta',
                        'fiscal_date', 'filing_date', 'fiscal_period', 'fiscal_year',
                        'has_fundamentals', 'is_stale', 'filing_date_matched',
                        'days_since_report'}
    
    significant_missing = not_in_config - known_supporting
    
    if significant_missing:
        print(f"⚠️  Features in d2 but NOT in config ({len(significant_missing)}):")
        for feat in sorted(significant_missing):
            # Show sample non-null count
            non_null_pct = (d2[feat].notna().sum() / len(d2)) * 100
            print(f"   - {feat} (non-null: {non_null_pct:.1f}%)")
        print()
    else:
        print("✅ All d2 features are declared in config\n")
    
    # Summary statistics
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total declared features: {len(declared_features)}")
    print(f"Total d2 features (excl. metadata): {len(d2_features)}")
    print(f"Features in config but missing in d2: {len(missing_in_d2)}")
    print(f"Significant features in d2 but not in config: {len(significant_missing)}")
    
    if not missing_in_d2 and not significant_missing:
        print("\n✅ VERIFICATION PASSED: Config is in sync with d2!")
    else:
        print("\n⚠️  VERIFICATION INCOMPLETE: Please review discrepancies above")
    
    # Feature group breakdown
    print("\n" + "=" * 70)
    print("FEATURE GROUP BREAKDOWN")
    print("=" * 70)
    
    # Count by category
    technical_in_d2 = sum(1 for f in TECHNICAL_FEATURES if f in d2.columns)
    fundamental_in_d2 = sum(1 for f in FUNDAMENTAL_FEATURES if f in d2.columns)
    alpha_in_d2 = sum(1 for f in ALPHA_FEATURES if f in d2.columns)
    lagged_in_d2 = sum(1 for f in FEATURES_TO_LAG if f"{f}_Lag1" in d2.columns)
    
    print(f"Technical features: {technical_in_d2}/{len(TECHNICAL_FEATURES)} in d2")
    print(f"Fundamental features: {fundamental_in_d2}/{len(FUNDAMENTAL_FEATURES)} in d2")
    print(f"Alpha features: {alpha_in_d2}/{len(ALPHA_FEATURES)} in d2")
    print(f"Lagged features: {lagged_in_d2}/{len(FEATURES_TO_LAG)} in d2")
    
    return len(missing_in_d2) == 0 and len(significant_missing) == 0

if __name__ == "__main__":
    success = verify_feature_config()
    sys.exit(0 if success else 1)
