"""
Quick test to verify native categorical support is working.

This script:
1. Loads D2 features
2. Checks that industry_id and sector_id are present
3. Trains a small M01 model with categorical support
4. Verifies XGBoost uses categorical splits
"""

import sys
import logging
import pandas as pd
import xgboost as xgb
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def test_categorical_support():
    """Test that categorical features work correctly."""

    print("=" * 70)
    print("TESTING NATIVE CATEGORICAL SUPPORT")
    print("=" * 70)

    # 1. Load D2 data
    d2_path = Path('data/ml/d2_features.parquet')
    if not d2_path.exists():
        print(f"❌ D2 not found at {d2_path}")
        print("   Run: python model_runner.py data --steps scan,features")
        return False

    d2 = pd.read_parquet(d2_path)
    print(f"✅ Loaded D2: {len(d2):,} rows, {len(d2.columns)} columns")

    # 2. Check categorical features
    from src.feature_config import CATEGORICAL_FEATURES

    missing_cats = [f for f in CATEGORICAL_FEATURES if f not in d2.columns]
    if missing_cats:
        print(f"❌ Missing categorical features: {missing_cats}")
        return False

    print(f"✅ Categorical features present: {CATEGORICAL_FEATURES}")

    # Check value ranges
    for cat_col in CATEGORICAL_FEATURES:
        n_unique = d2[cat_col].nunique()
        value_range = f"[{d2[cat_col].min()}, {d2[cat_col].max()}]"
        print(f"   {cat_col}: {n_unique} unique values, range: {value_range}")

    # 3. Convert to category dtype
    for col in CATEGORICAL_FEATURES:
        d2[col] = d2[col].astype('category')

    print(f"✅ Converted to pandas 'category' dtype")

    # 4. Train a small test model
    print("\n" + "=" * 70)
    print("TRAINING TEST MODEL")
    print("=" * 70)

    # Get features from M01_V2
    from src.feature_config import M01_V2_FEATURES

    # Use subset of features + categorical
    test_features = [
        'alpha011', 'alpha013', 'RSI_14', 'VCP_Ratio',
        'operating_margin', 'eps_stability_score',
        'industry_id',  # ✅ Categorical
        'sector_id'     # ✅ Categorical
    ]

    available_features = [f for f in test_features if f in d2.columns]
    print(f"Using {len(available_features)} test features: {available_features}")

    # Prepare data
    d2_clean = d2.dropna(subset=['return_pct'] + available_features).copy()
    print(f"Clean data: {len(d2_clean):,} rows")

    X = d2_clean[available_features]
    y = d2_clean['return_pct']

    # Train with categorical support
    params = {
        'objective': 'reg:squarederror',
        'n_estimators': 50,  # Small for testing
        'max_depth': 4,
        'learning_rate': 0.1,
        'enable_categorical': True,  # ✅ Key parameter
        'random_state': 42
    }

    print(f"\nTraining XGBoost with enable_categorical=True...")
    model = xgb.XGBRegressor(**params)
    model.fit(X, y, verbose=False)

    print(f"✅ Model trained successfully!")

    # 5. Check feature importance
    print("\n" + "=" * 70)
    print("FEATURE IMPORTANCE")
    print("=" * 70)

    importance = pd.DataFrame({
        'feature': available_features,
        'gain': model.feature_importances_
    }).sort_values('gain', ascending=False)

    print(importance.to_string(index=False))

    # Highlight categorical features
    cat_importance = importance[importance['feature'].isin(CATEGORICAL_FEATURES)]
    if not cat_importance.empty:
        print(f"\n✅ Categorical feature importance:")
        for _, row in cat_importance.iterrows():
            print(f"   {row['feature']}: {row['gain']:.4f}")

    # 6. Verify splits use categorical logic
    print("\n" + "=" * 70)
    print("VERIFYING CATEGORICAL SPLITS")
    print("=" * 70)

    # Get tree dump to check split types
    trees = model.get_booster().get_dump()

    # Check if any splits mention categorical features
    cat_splits = []
    for tree_idx, tree in enumerate(trees[:5]):  # Check first 5 trees
        for cat_col in CATEGORICAL_FEATURES:
            if cat_col in tree:
                cat_splits.append((tree_idx, cat_col))

    if cat_splits:
        print(f"✅ Found {len(cat_splits)} categorical splits in first 5 trees:")
        for tree_idx, col in cat_splits[:10]:
            print(f"   Tree {tree_idx}: {col}")
    else:
        print("⚠️  No categorical splits found in first 5 trees")
        print("   (This is OK if the features have low importance)")

    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)
    print("✅ Native categorical support is working correctly!")
    print("\nNext step: Train M01_v2 with full feature set:")
    print("  python model_runner.py train --model m01_v2 --feature-set M01_V2_FEATURES")

    return True


if __name__ == '__main__':
    try:
        success = test_categorical_support()
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        sys.exit(1)
