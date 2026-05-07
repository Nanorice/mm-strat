"""
MFE Classification Baseline - 4-Class XGBoost Classifier
==========================================================
Predicts Maximum Favorable Excursion (MFE) category for SEPA candidates.

Target Classes:
- 0: Noise (0-2%)
- 1: Moderate (2-10%)
- 2: Strong (10-30%)
- 3: Home Run (>30%)

Features are loaded dynamically from `model_feature_sets` in DuckDB.
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.utils.class_weight import compute_class_weight

sys.path.append(str(Path(__file__).parent.parent))
from src.evaluation.classification_evaluator import ClassificationEvaluator
from src.evaluation.leakage_guard import LeakageGuard
from src.model_registry import ModelRegistry

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "market_data.duckdb"


def get_feature_set(db_path: Path, feature_set_id: str) -> tuple[list[str], dict[str, list[str]]]:
    """Load feature names and groups from `model_feature_sets`.

    Returns:
        (features ordered by ordinal, feature_groups dict)
    """
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute(
            "SELECT feature_name, feature_group FROM model_feature_sets "
            "WHERE feature_set_id = ? ORDER BY ordinal",
            [feature_set_id],
        ).fetchall()
    finally:
        con.close()

    if not rows:
        raise ValueError(
            f"Feature set '{feature_set_id}' is empty or missing. "
            f"Run `python scripts/populate_feature_catalog.py` first."
        )

    features = [r[0] for r in rows]
    groups: dict[str, list[str]] = {}
    for name, group in rows:
        groups.setdefault(group or "Ungrouped", []).append(name)

    return features, groups


def load_training_data(
    db_path: Path,
    feature_version: str,
    min_date: str,
) -> pd.DataFrame:
    """Load training data from v_d2_training view."""
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        df = con.execute(
            """
            SELECT *
            FROM v_d2_training
            WHERE feature_version = ?
              AND date >= ?
              AND mfe_pct IS NOT NULL
            ORDER BY date, ticker
            """,
            [feature_version, min_date],
        ).df()
    finally:
        con.close()

    logger.info(f"✅ Loaded {len(df):,} rows from v_d2_training ({df['date'].min()} to {df['date'].max()})")
    return df


def validate_features(df: pd.DataFrame, feature_list: list[str]) -> tuple[list[str], list[str]]:
    """Match requested features to actual df columns case-insensitively."""
    df_cols_lower = {col.lower(): col for col in df.columns}
    valid, missing = [], []
    for feat in feature_list:
        actual = df_cols_lower.get(feat.lower())
        if actual is not None:
            valid.append(actual)
        else:
            missing.append(feat)
    return valid, missing


def create_mfe_labels(df: pd.DataFrame, return_col: str = 'mfe_pct') -> pd.Series:
    """Create 4-class MFE labels: Noise / Moderate / Strong / Home Run."""
    conditions = [
        (df[return_col] <= 2.0),
        (df[return_col] > 2.0) & (df[return_col] <= 10.0),
        (df[return_col] > 10.0) & (df[return_col] <= 30.0),
        (df[return_col] > 30.0),
    ]
    labels = np.select(conditions, [0, 1, 2, 3], default=0)

    unique, counts = np.unique(labels, return_counts=True)
    logger.info("📊 MFE Class Distribution:")
    for cls, count in zip(unique, counts):
        logger.info(f"   Class {cls}: {count:,} ({count / len(labels) * 100:.1f}%)")

    return pd.Series(labels, index=df.index)


DEFAULT_HYPERPARAMS: dict = {
    'objective': 'multi:softprob',
    'num_class': 4,
    'max_depth': 4,
    'learning_rate': 0.05,
    'subsample': 0.8,
    'colsample_bytree': 0.8,
    'eval_metric': 'mlogloss',
    'random_state': 42,
    'tree_method': 'hist',
    'enable_categorical': True,
}

NUM_BOOST_ROUND = 100
EARLY_STOPPING_ROUNDS = 20
LABEL_THRESHOLDS = [0, 2, 10, 30]  # upper bounds per class (last is open-ended)


def train_mfe_classifier(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    params: dict | None = None,
) -> tuple[xgb.Booster, dict]:
    """Train XGBoost multi-class classifier with early stopping on val.

    Returns:
        (model, training_info) where training_info contains class weights.
    """
    logger.info("🚀 Training MFE classifier...")

    classes = np.unique(y_train)
    weights = compute_class_weight('balanced', classes=classes, y=y_train)
    sample_weights = y_train.map(dict(zip(classes, weights)))
    class_weights = {int(c): float(w) for c, w in zip(classes, weights)}
    logger.info(f"⚖️  Class weights: {class_weights}")

    if params is None:
        params = dict(DEFAULT_HYPERPARAMS)

    X_train = X_train.replace([np.inf, -np.inf], np.nan)
    X_val = X_val.replace([np.inf, -np.inf], np.nan)

    dtrain = xgb.DMatrix(X_train, label=y_train, weight=sample_weights, enable_categorical=True)
    dval = xgb.DMatrix(X_val, label=y_val, enable_categorical=True)

    model = xgb.train(
        params=params,
        dtrain=dtrain,
        num_boost_round=NUM_BOOST_ROUND,
        evals=[(dtrain, 'train'), (dval, 'val')],
        early_stopping_rounds=EARLY_STOPPING_ROUNDS,
        verbose_eval=10,
    )

    logger.info(f"✅ Training complete (best iteration: {model.best_iteration})")
    return model, {'class_weights': class_weights, 'best_iteration': int(model.best_iteration)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train MFE classifier from a catalog feature set")
    parser.add_argument("--feature-set", default="fs_m01_prototype",
                        help="Feature set ID in model_feature_sets")
    parser.add_argument("--model-name", default="m01_prototype",
                        help="Model name (used for artifact paths and version_id prefix)")
    parser.add_argument("--model-version", default="v1",
                        help="Model version subdir under models/<model_name>/")
    parser.add_argument("--feature-version", default="v3.1")
    parser.add_argument("--min-date", default="2003-01-01")
    parser.add_argument("--no-holdout", action="store_true",
                        help="Train on 85%% / val 15%% / no test holdout. Final model uses all recent data; "
                             "metrics reported are validation-set, not unbiased test metrics.")
    parser.add_argument("--promote-prod", action="store_true",
                        help="After registration, mark this version as prod (archives previous prod).")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    logger.info("=" * 80)
    logger.info(f"MFE CLASSIFIER TRAINING — feature_set={args.feature_set}, model={args.model_name}")
    logger.info(f"Mode: {'NO-HOLDOUT (85/15/0)' if args.no_holdout else 'STANDARD (60/20/20)'}")
    logger.info("=" * 80)

    # 1. Load feature set from catalog
    requested_features, feature_groups = get_feature_set(args.db, args.feature_set)
    logger.info(f"📋 Loaded {len(requested_features)} features from '{args.feature_set}'")

    # 2. Load training data
    df = load_training_data(args.db, feature_version=args.feature_version, min_date=args.min_date)

    # 3. Validate features
    valid_features, missing_features = validate_features(df, requested_features)
    if missing_features:
        logger.warning(f"⚠️  Missing {len(missing_features)} features:")
        for feat in missing_features[:10]:
            logger.warning(f"   - {feat}")
        if len(missing_features) > 10:
            logger.warning(f"   ... and {len(missing_features) - 10} more")
    logger.info(f"✅ Valid features: {len(valid_features)}")

    # 4. Labels + features
    y = create_mfe_labels(df, return_col='mfe_pct')
    X = df[valid_features].copy()

    # XGBoost requires `category` dtype for categoricals (object dtype is rejected
    # even with enable_categorical=True). v_d2_training returns sector/industry as
    # VARCHAR → pandas object — cast them here.
    cat_mapping = {}
    for col in X.select_dtypes(include='object').columns:
        X[col] = X[col].astype('category')
        cat_mapping[col] = list(X[col].cat.categories)

    # 5. Temporal split — snap boundaries to date boundaries so same-day rows for
    # many tickers don't straddle splits (would trigger leakage guard).
    df_sorted = df.sort_values('date').reset_index(drop=True)
    X_sorted = X.loc[df.sort_values('date').index].reset_index(drop=True)
    y_sorted = y.loc[df.sort_values('date').index].reset_index(drop=True)

    n = len(X_sorted)
    train_frac = 0.85 if args.no_holdout else 0.60
    val_frac = 0.15 if args.no_holdout else 0.20

    dates = df_sorted['date'].to_numpy()
    train_size = int(np.searchsorted(dates, dates[int(n * train_frac)], side='left'))
    val_end = int(n * (train_frac + val_frac))
    val_size = (
        n - train_size if args.no_holdout
        else int(np.searchsorted(dates, dates[val_end], side='left')) - train_size
    )
    test_size = n - train_size - val_size

    X_train = X_sorted.iloc[:train_size]
    y_train = y_sorted.iloc[:train_size]
    X_val = X_sorted.iloc[train_size:train_size + val_size]
    y_val = y_sorted.iloc[train_size:train_size + val_size]

    if args.no_holdout:
        # No test set — evaluator still needs something; we'll use val and tag metrics accordingly.
        X_test = X_val
        y_test = y_val
        dates_test = df_sorted['date'].iloc[train_size:train_size + val_size].reset_index(drop=True)
    else:
        X_test = X_sorted.iloc[train_size + val_size:]
        y_test = y_sorted.iloc[train_size + val_size:]
        dates_test = df_sorted['date'].iloc[train_size + val_size:].reset_index(drop=True)

    logger.info(f"📊 Split sizes: Train={len(X_train):,}, Val={len(X_val):,}, Test={test_size:,}")

    # 6. Leakage guards
    train_idx = np.arange(train_size)
    val_idx = np.arange(train_size, train_size + val_size)
    test_idx = np.arange(train_size + val_size, n) if test_size > 0 else np.array([], dtype=int)

    if test_size > 0:
        leakage_check = LeakageGuard.validate_split_ordering(df_sorted, 'date', train_idx, val_idx, test_idx)
        if not leakage_check['all_valid']:
            raise ValueError("Temporal split validation failed")
    else:
        # No test split — only train→val ordering matters.
        train_val = LeakageGuard.validate_temporal_split(df_sorted, 'date', train_idx, val_idx, strict=False)
        leakage_check = {'all_valid': train_val['is_valid'], 'train_val': train_val}
        if not leakage_check['all_valid']:
            raise ValueError("Temporal split validation failed")

    feature_check = LeakageGuard.check_feature_leakage(valid_features)
    if not feature_check['is_clean']:
        logger.warning(f"⚠️  Suspicious features: {feature_check['suspicious_features']}")

    # 7. Train
    model, training_info = train_mfe_classifier(X_train, y_train, X_val, y_val)

    # 8. Evaluate
    output_dir = Path(__file__).parent.parent / "models"
    output_dir.mkdir(parents=True, exist_ok=True)

    class_names = ['Noise (0-2%)', 'Moderate (2-10%)', 'Strong (10-30%)', 'Home Run (>30%)']
    evaluator = ClassificationEvaluator(
        model_name=args.model_name,
        model_version=args.model_version,
        output_dir=output_dir,
        class_names=class_names,
    )
    eval_results = evaluator.evaluate(
        model=model,
        X_test=X_test,
        y_test=y_test,
        feature_names=valid_features,
        X_train=X_train,
        y_train=y_train.values,
        X_val=X_val,
        y_val=y_val.values,
        dates_test=dates_test,
        compute_shap=True,
        shap_sample_size=1000,
    )

    # 9. Save model + metadata
    model_dir = output_dir / args.model_name / args.model_version
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / "model.json"
    model.save_model(str(model_path))
    logger.info(f"💾 Model saved to {model_path}")

    # In --no-holdout mode, evaluator metrics are val-set, not test-set.
    eval_metrics_field = 'val_metrics' if args.no_holdout else 'test_metrics'

    metadata = {
        'model_name': args.model_name,
        'model_version': args.model_version,
        'feature_set_id': args.feature_set,
        'training_date': datetime.now().isoformat(),
        'feature_version': args.feature_version,
        'min_date': args.min_date,
        'split_mode': 'no_holdout_85_15_0' if args.no_holdout else 'standard_60_20_20',
        'num_features': len(valid_features),
        'valid_features': valid_features,
        'missing_features': missing_features,
        'train_samples': len(X_train),
        'val_samples': len(X_val),
        'test_samples': test_size,
        eval_metrics_field: {
            'accuracy': eval_results.get('accuracy'),
            'weighted_f1': eval_results.get('weighted_f1'),
            'macro_f1': eval_results.get('macro_f1'),
        },
        'temporal_validation': leakage_check,
        'feature_leakage_check': feature_check,
    }
    (model_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, default=str))
    logger.info(f"📝 Metadata saved to {model_dir / 'metadata.json'}")

    (model_dir / "categorical_mapping.json").write_text(json.dumps(cat_mapping, indent=2, default=str))
    logger.info(f"📝 Categorical mapping saved to {model_dir / 'categorical_mapping.json'}")

    # 10. Register in model registry
    registry = ModelRegistry(db_path=args.db)
    version_id = f'{args.model_name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    git_sha = ModelRegistry.get_git_sha()

    # In --no-holdout mode, leave the test-metric columns NULL — they'd be misleading.
    accuracy = eval_results.get('accuracy') if not args.no_holdout else None
    weighted_f1 = eval_results.get('weighted_f1') if not args.no_holdout else None
    macro_f1 = eval_results.get('macro_f1') if not args.no_holdout else None

    hyperparams = {k: v for k, v in DEFAULT_HYPERPARAMS.items()
                   if k not in ('eval_metric', 'random_state', 'tree_method', 'enable_categorical')}

    try:
        registry.register_version(
            version_id=version_id,
            specs={
                'features': valid_features,
                'hyperparameters': hyperparams,
                'training_config': {
                    'train_samples': len(X_train),
                    'val_samples': len(X_val),
                    'test_samples': test_size,
                    'feature_version': args.feature_version,
                    'min_date': args.min_date,
                    'split_mode': metadata['split_mode'],
                    'num_boost_round': NUM_BOOST_ROUND,
                    'early_stopping_rounds': EARLY_STOPPING_ROUNDS,
                    'best_iteration': training_info['best_iteration'],
                    'label_thresholds': LABEL_THRESHOLDS,
                    'class_weighting': 'balanced',
                    'class_weights': training_info['class_weights'],
                },
                'val_metrics': {
                    'accuracy': eval_results.get('accuracy'),
                    'weighted_f1': eval_results.get('weighted_f1'),
                    'macro_f1': eval_results.get('macro_f1'),
                } if args.no_holdout else None,
            },
            status='test',
            feature_version=args.feature_version,
            training_date=datetime.now().date(),
            dataset_rows=len(df),
            accuracy=accuracy,
            weighted_f1=weighted_f1,
            macro_f1=macro_f1,
            feature_set_id=args.feature_set,
            git_sha=git_sha,
            model_type='classifier',
            artifacts_path=str(model_dir),
            model_name=args.model_name,
            model_version=args.model_version,
        )
        logger.info(f"✅ Registered model version: {version_id}")

        if args.promote_prod:
            registry.set_prod(version_id)
            logger.info(f"🚀 Promoted {version_id} to PROD")
    except Exception as e:
        logger.warning(f"⚠️  Model registration failed (non-critical): {e}")
        logger.info("Model and evaluation artifacts saved successfully, continuing...")

    logger.info("=" * 80)
    logger.info("✅ TRAINING COMPLETE")
    logger.info(f"📁 Model: {model_path}")
    logger.info(f"📁 Evaluation: {evaluator.eval_dir}")
    metric_label = "Val" if args.no_holdout else "Test"
    logger.info(f"🎯 {metric_label} Accuracy: {eval_results.get('accuracy', 0):.3f}")
    logger.info(f"📊 {metric_label} Weighted F1: {eval_results.get('weighted_f1', 0):.3f}")
    logger.info(f"📊 {metric_label} Macro F1: {eval_results.get('macro_f1', 0):.3f}")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
