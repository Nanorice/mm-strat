"""
MFE Classification Baseline - 4-Class XGBoost Classifier
==========================================================
Predicts Maximum Favorable Excursion (MFE) category for SEPA candidates.

Target Classes:
- 0: Noise (0-2%)
- 1: Moderate (2-10%)
- 2: Strong (10-30%)
- 3: Home Run (>30%)

Model: M04 (MFE Classifier)
"""

import sys
from pathlib import Path
import logging
import duckdb
import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.utils.class_weight import compute_class_weight
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix
import json
from datetime import datetime

sys.path.append(str(Path(__file__).parent.parent))
from src.model_registry import ModelRegistry
from src.evaluation.classification_evaluator import ClassificationEvaluator
from src.evaluation.leakage_guard import LeakageGuard

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Database path
DB_PATH = Path(__file__).parent.parent / "data" / "market_data.duckdb"

# Feature groups (baseline)
FEATURE_GROUPS = {
    "Moving_Averages": [
        'close_above_sma200', 'price_vs_sma_50', 'price_vs_sma_150', 'price_vs_sma_200',
        'sma_50_slope', 'price_vs_sma_50_delta', 'price_vs_sma_150_delta', 'price_vs_sma_200_delta'
    ],
    "Momentum_RS": [
        'rs_line_uptrend', 'rs_line_delta', 'rs_line_lag_delta', 'rs_rating', 'rs', 'rs_ma',
        'rs_delta', 'rs_ma_delta', 'mom_21d', 'mom_63d', 'mom_126d', 'mom_189d', 'mom_252d',
        'rs_velocity', 'price_accel_10d', 'rs_sector_rank', 'rs_vs_sector', 'sector_momentum',
        'rs_industry_rank', 'rs_vs_industry', 'industry_momentum'
    ],
    "Core_Volume": [
        'vol_ratio', 'dry_up_volume', 'dry_up_volume_delta', 'turnover',
        'volume_acceleration', 'return_1d', 'return_5d'
    ],
    "Volatility_Ranges": [
        'natr', 'natr_delta', 'atr_delta', 'vcp_ratio', 'vcp_ratio_delta',
        'consolidation_width', 'consolidation_width_delta', 'consolidation_duration',
        'dist_from_52w_high', 'dist_from_52w_high_delta',
        'dist_from_52w_low', 'dist_from_52w_low_delta',
        'low_52w_delta', 'high_52w_delta',
        'dist_from_20d_high', 'dist_from_20d_high_delta', 'highest_high_20d_delta',
        'dist_from_20d_low', 'dist_from_20d_low_delta', 'lowest_low_20d_delta'
    ],
    "Technical_Oscillators": [
        'rsi_14', 'rsi_14_delta', 'is_green_day', 'green_days_ratio_20d', 'breakout',
        'breakout_momentum', 'immediate_thrust'
    ],
    "Fundamentals": [
        'eps_diluted', 'revenue_growth_yoy', 'eps_growth_yoy', 'net_income_growth_yoy',
        'eps_accel', 'revenue_accel', 'revenue_cagr_3y', 'eps_stability_score',
        'debt_to_equity', 'current_ratio', 'gross_margin', 'operating_margin', 'roe', 'roa',
        'fcf_margin', 'earnings_quality_score', 'gross_margin_trend', 'days_since_report',
        'pe_ratio', 'ps_ratio', 'pb_ratio'
    ],
    "Fast_Alphas": [
        'alpha001', 'alpha002', 'alpha004', 'alpha006', 'alpha009', 'alpha011', 'alpha012',
        'alpha013', 'alpha015', 'alpha041', 'alpha046', 'alpha049', 'alpha054', 'alpha060',
        'alpha101'
    ],
    "M03_Regime": [
        'm03_score', 'm03_pillar_trend', 'm03_pillar_liq', 'm03_pillar_risk',
        'm03_delta_5d', 'm03_delta_20d', 'm03_regime_vol'
    ]
}


def load_training_data(
    db_path: Path,
    feature_version: str = 'v3.1',
    min_date: str = '2020-01-01'
) -> pd.DataFrame:
    """
    Load training data from v_d2_training view.

    Args:
        db_path: Path to DuckDB database
        feature_version: Feature schema version
        min_date: Minimum date for training data

    Returns:
        DataFrame with features and mfe_pct target
    """
    con = duckdb.connect(str(db_path))

    try:
        query = f"""
            SELECT *
            FROM v_d2_training
            WHERE feature_version = '{feature_version}'
              AND date >= '{min_date}'
              AND mfe_pct IS NOT NULL
            ORDER BY date, ticker
        """

        df = con.execute(query).df()
        logger.info(f"✅ Loaded {len(df):,} rows from v_d2_training ({df['date'].min()} to {df['date'].max()})")

        return df

    finally:
        con.close()


def validate_features(df: pd.DataFrame, feature_list: list[str]) -> tuple[list[str], list[str]]:
    """
    Validate that features exist in dataframe.

    Args:
        df: Training dataframe
        feature_list: List of feature names to validate

    Returns:
        Tuple of (valid_features, missing_features)
    """
    # Normalize column names to lowercase for comparison
    df_cols_lower = {col.lower(): col for col in df.columns}

    valid = []
    missing = []

    for feat in feature_list:
        feat_lower = feat.lower()
        if feat_lower in df_cols_lower:
            valid.append(df_cols_lower[feat_lower])  # Use actual column name
        else:
            missing.append(feat)

    return valid, missing


def create_mfe_labels(df: pd.DataFrame, return_col: str = 'mfe_pct') -> pd.Series:
    """
    Create 4-class MFE labels.

    Classes:
    - 0: Noise (0-2%)
    - 1: Moderate (2-10%)
    - 2: Strong (10-30%)
    - 3: Home Run (>30%)

    Args:
        df: Training dataframe
        return_col: Column name for MFE percentage

    Returns:
        Series with class labels (0-3)
    """
    conditions = [
        (df[return_col] <= 2.0),
        (df[return_col] > 2.0) & (df[return_col] <= 10.0),
        (df[return_col] > 10.0) & (df[return_col] <= 30.0),
        (df[return_col] > 30.0)
    ]
    choices = [0, 1, 2, 3]

    labels = np.select(conditions, choices, default=0)

    # Log distribution
    unique, counts = np.unique(labels, return_counts=True)
    logger.info("📊 MFE Class Distribution:")
    for cls, count in zip(unique, counts):
        pct = count / len(labels) * 100
        logger.info(f"   Class {cls}: {count:,} ({pct:.1f}%)")

    return pd.Series(labels, index=df.index)


def train_mfe_classifier(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    params: dict = None
) -> xgb.Booster:
    """
    Train XGBoost multi-class classifier for MFE prediction.

    Args:
        X_train: Training features
        y_train: Training labels (0-3)
        X_val: Validation features
        y_val: Validation labels
        params: Model hyperparameters (optional)

    Returns:
        Trained XGBoost booster
    """
    logger.info("🚀 Training MFE classifier...")

    # Compute class weights
    classes = np.unique(y_train)
    weights = compute_class_weight('balanced', classes=classes, y=y_train)
    sample_weights = y_train.map(dict(zip(classes, weights)))

    logger.info(f"⚖️  Class weights: {dict(zip(classes, weights))}")

    # Default parameters
    if params is None:
        params = {
            'objective': 'multi:softprob',
            'num_class': 4,
            'max_depth': 4,
            'learning_rate': 0.05,
            'subsample': 0.8,
            'colsample_bytree': 0.8,
            'eval_metric': 'mlogloss',
            'random_state': 42,
            'tree_method': 'hist',
            'enable_categorical': True  # Support sector/industry
        }

    # Handle infinite values
    X_train = X_train.replace([np.inf, -np.inf], np.nan)
    X_val = X_val.replace([np.inf, -np.inf], np.nan)

    # Create DMatrix
    dtrain = xgb.DMatrix(X_train, label=y_train, weight=sample_weights, enable_categorical=True)
    dval = xgb.DMatrix(X_val, label=y_val, enable_categorical=True)

    # Train
    evals = [(dtrain, 'train'), (dval, 'val')]
    model = xgb.train(
        params=params,
        dtrain=dtrain,
        num_boost_round=100,
        evals=evals,
        early_stopping_rounds=20,
        verbose_eval=10
    )

    logger.info(f"✅ Training complete (best iteration: {model.best_iteration})")

    return model


def evaluate_model_legacy(
    model: xgb.Booster,
    X_test: pd.DataFrame,
    y_test: pd.Series,
    output_dir: Path
) -> dict:
    """
    LEGACY: Simple evaluation (replaced by ClassificationEvaluator).
    Kept for backward compatibility.

    Args:
        model: Trained XGBoost booster
        X_test: Test features
        y_test: Test labels
        output_dir: Directory to save results

    Returns:
        Dictionary with evaluation metrics
    """
    logger.info("📊 Evaluating model (legacy)...")

    # Handle infinite values
    X_test = X_test.replace([np.inf, -np.inf], np.nan)

    # Predict
    dtest = xgb.DMatrix(X_test, enable_categorical=True)
    y_pred_proba = model.predict(dtest)
    y_pred = np.argmax(y_pred_proba, axis=1)

    # Classification report
    report = classification_report(y_test, y_pred, output_dict=True, zero_division=0)
    logger.info("\n" + classification_report(y_test, y_pred, zero_division=0))

    # Confusion matrix
    cm = confusion_matrix(y_test, y_pred)
    logger.info("\n📊 Confusion Matrix:")
    logger.info(f"\n{cm}")

    # Save results
    results = {
        'classification_report': report,
        'confusion_matrix': cm.tolist(),
        'test_samples': len(y_test),
        'test_accuracy': report['accuracy'],
        'weighted_f1': report['weighted avg']['f1-score']
    }

    results_path = output_dir / 'evaluation_results_legacy.json'
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2)

    logger.info(f"✅ Legacy results saved to {results_path}")

    return results


def main():
    """Main training workflow."""
    logger.info("=" * 80)
    logger.info("MFE CLASSIFIER TRAINING (M04 Baseline)")
    logger.info("=" * 80)

    # 1. Load data
    df = load_training_data(DB_PATH, feature_version='v3.1', min_date='2020-01-01')

    # 2. Flatten feature groups
    all_features = []
    for group_name, features in FEATURE_GROUPS.items():
        all_features.extend(features)

    logger.info(f"📋 Total features: {len(all_features)}")

    # 3. Validate features
    valid_features, missing_features = validate_features(df, all_features)

    if missing_features:
        logger.warning(f"⚠️  Missing {len(missing_features)} features:")
        for feat in missing_features[:10]:  # Show first 10
            logger.warning(f"   - {feat}")
        if len(missing_features) > 10:
            logger.warning(f"   ... and {len(missing_features) - 10} more")

    logger.info(f"✅ Valid features: {len(valid_features)}")

    # 4. Create labels
    y = create_mfe_labels(df, return_col='mfe_pct')

    # 5. Filter features
    X = df[valid_features].copy()

    # 6. Train/val/test split (temporal)
    # Sort by date to ensure temporal split
    df_sorted = df.sort_values('date')
    X_sorted = X.loc[df_sorted.index]
    y_sorted = y.loc[df_sorted.index]

    # 60% train, 20% val, 20% test
    train_size = int(len(X_sorted) * 0.6)
    val_size = int(len(X_sorted) * 0.2)

    X_train = X_sorted.iloc[:train_size]
    y_train = y_sorted.iloc[:train_size]

    X_val = X_sorted.iloc[train_size:train_size + val_size]
    y_val = y_sorted.iloc[train_size:train_size + val_size]

    X_test = X_sorted.iloc[train_size + val_size:]
    y_test = y_sorted.iloc[train_size + val_size:]

    logger.info(f"📊 Split sizes: Train={len(X_train):,}, Val={len(X_val):,}, Test={len(X_test):,}")

    # 6.1 Validate temporal split (check for leakage)
    logger.info("🔍 Validating temporal split...")
    train_indices = np.arange(len(X_train))
    val_indices = np.arange(len(X_train), len(X_train) + len(X_val))
    test_indices = np.arange(len(X_train) + len(X_val), len(df_sorted))

    leakage_check = LeakageGuard.validate_split_ordering(
        df_sorted,
        'date',
        train_indices,
        val_indices,
        test_indices
    )

    if not leakage_check['all_valid']:
        logger.error("❌ Temporal leakage detected! Aborting training.")
        raise ValueError("Temporal split validation failed")

    # 6.2 Check for feature leakage
    feature_check = LeakageGuard.check_feature_leakage(valid_features)
    if not feature_check['is_clean']:
        logger.warning(f"⚠️  Suspicious features detected: {feature_check['suspicious_features']}")

    # 7. Train model
    model = train_mfe_classifier(X_train, y_train, X_val, y_val)

    # 8. Create output directory
    output_dir = Path(__file__).parent.parent / "models"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 9. Comprehensive Evaluation (NEW)
    logger.info("=" * 80)
    logger.info("🎯 COMPREHENSIVE EVALUATION")
    logger.info("=" * 80)

    class_names = ['Noise (0-2%)', 'Moderate (2-10%)', 'Strong (10-30%)', 'Home Run (>30%)']

    evaluator = ClassificationEvaluator(
        model_name='M01_baseline',
        model_version='v1',
        output_dir=output_dir,
        class_names=class_names
    )

    results = evaluator.evaluate(
        model=model,
        X_test=X_test,
        y_test=y_test,
        feature_names=valid_features,
        X_train=X_train,
        y_train=y_train.values,
        X_val=X_val,
        y_val=y_val.values,
        compute_shap=True,
        shap_sample_size=1000
    )

    # 10. Save model
    model_dir = output_dir / "M01_baseline" / "v1"
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / "model.json"
    model.save_model(str(model_path))
    logger.info(f"💾 Model saved to {model_path}")

    # 11. Save metadata
    metadata = {
        'model_name': 'M01_MFE_Classifier',
        'version': 'baseline_v1',
        'training_date': datetime.now().isoformat(),
        'feature_version': 'v3.1',
        'num_features': len(valid_features),
        'feature_groups': {k: len(v) for k, v in FEATURE_GROUPS.items()},
        'valid_features': valid_features,
        'missing_features': missing_features,
        'train_samples': len(X_train),
        'val_samples': len(X_val),
        'test_samples': len(X_test),
        'test_accuracy': results.get('accuracy', 0),
        'weighted_f1': results.get('weighted_f1', 0),
        'macro_f1': results.get('macro_f1', 0),
        'temporal_validation': leakage_check,
        'feature_leakage_check': feature_check
    }

    meta_path = model_dir / "metadata.json"
    with open(meta_path, 'w') as f:
        json.dump(metadata, f, indent=2)

    logger.info(f"📝 Metadata saved to {meta_path}")

    # 12. Register in model registry
    registry = ModelRegistry()

    # Use timestamp-based version ID to avoid duplicates
    version_id = f'M01_baseline_{datetime.now().strftime("%Y%m%d_%H%M%S")}'

    try:
        registry.register_version(
            version_id=version_id,
            specs={
                'features': valid_features,
                'hyperparameters': {
                    'objective': 'multi:softprob',
                    'num_class': 4,
                    'max_depth': 4,
                    'learning_rate': 0.05,
                    'subsample': 0.8,
                    'colsample_bytree': 0.8
                },
                'training_config': {
                    'train_samples': len(X_train),
                    'val_samples': len(X_val),
                    'test_samples': len(X_test),
                    'feature_version': 'v3.1'
                }
            },
            status='test',
            feature_version='v3.1',
            training_date=datetime.now().date(),
            dataset_rows=len(df)
        )
        logger.info(f"✅ Registered model version: {version_id}")
    except Exception as e:
        logger.warning(f"⚠️  Model registration failed (non-critical): {e}")
        logger.info("Model and evaluation artifacts saved successfully, continuing...")

    logger.info("=" * 80)
    logger.info("✅ TRAINING COMPLETE")
    logger.info(f"📁 Model: {model_path}")
    logger.info(f"📁 Evaluation: {evaluator.eval_dir}")
    logger.info(f"🎯 Test Accuracy: {results.get('accuracy', 0):.3f}")
    logger.info(f"📊 Weighted F1: {results.get('weighted_f1', 0):.3f}")
    logger.info(f"📊 Macro F1: {results.get('macro_f1', 0):.3f}")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
