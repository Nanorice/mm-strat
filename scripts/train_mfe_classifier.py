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
from typing import Optional

import duckdb
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.utils.class_weight import compute_class_weight

sys.path.append(str(Path(__file__).parent.parent))
from src.evaluation.classification_evaluator import ClassificationEvaluator
from src.evaluation.data_quality import DataQualityError
from src.evaluation.label_registry import LabelDefinition
from src.evaluation.leakage_guard import LeakageGuard
from src.evaluation.pretrain_report import run_pretrain_audit
from src.evaluation.walk_forward import (
    aggregate_walk_forward,
    anchored_walk_forward,
    run_walk_forward,
)
from src.evaluation.walk_forward_backtest import (
    aggregate_walk_forward_backtest,
    run_walk_forward_backtest,
)
from src.evaluation.drift import reference_snapshot
from src.evaluation.calibrator import IsotonicCalibrator, calibrator_path_for
from src.evaluation.calibration import expected_calibration_error
from src.model_registry import ModelRegistry

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "market_data.duckdb"
LABEL_REGISTRY_DIR = Path(__file__).parent.parent / "label_registry"


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


def create_mfe_labels(
    df: pd.DataFrame,
    bins: list[float],
    return_col: str = 'mfe_pct',
) -> pd.Series:
    """Bucket `return_col` into integer class indices using `bins` as upper edges.

    `bins=[2,10,30]` → 4 classes (Noise/Moderate/Strong/HomeRun, original behavior).
    `bins=[30]` → 2 classes (0 if mfe<=30, 1 if mfe>30).
    """
    if not bins:
        raise ValueError("bins must be a non-empty list of upper edges")
    sorted_bins = sorted(bins)
    conditions = []
    prev = -np.inf
    for edge in sorted_bins:
        conditions.append((df[return_col] > prev) & (df[return_col] <= edge))
        prev = edge
    conditions.append(df[return_col] > prev)
    choices = list(range(len(conditions)))
    labels = np.select(conditions, choices, default=0)

    unique, counts = np.unique(labels, return_counts=True)
    logger.info(f"📊 Class Distribution (bins={sorted_bins}, n_classes={len(choices)}):")
    for cls, count in zip(unique, counts):
        logger.info(f"   Class {cls}: {count:,} ({count / len(labels) * 100:.1f}%)")

    return pd.Series(labels, index=df.index)


def _class_names_from_bins(bins: list[float]) -> list[str]:
    """Default human-readable class names derived from bin edges."""
    sorted_bins = sorted(bins)
    if sorted_bins == [2.0, 10.0, 30.0]:
        return ['Noise (0-2%)', 'Moderate (2-10%)', 'Strong (10-30%)', 'Home Run (>30%)']
    if len(sorted_bins) == 1:
        return [f'Not Home Run (<={sorted_bins[0]:.0f}%)', f'Home Run (>{sorted_bins[0]:.0f}%)']
    names = []
    prev = 0.0
    for edge in sorted_bins:
        names.append(f'({prev:.0f}-{edge:.0f}%]')
        prev = edge
    names.append(f'>{prev:.0f}%')
    return names


def _xgb_params_for_n_classes(n_classes: int) -> dict:
    """Multi-class softprob for n>=3; binary logistic for n=2."""
    base = {
        'max_depth': 4,
        'learning_rate': 0.05,
        'subsample': 0.8,
        'colsample_bytree': 0.8,
        'random_state': 42,
        'tree_method': 'hist',
    }
    if n_classes == 2:
        base.update({'objective': 'binary:logistic', 'eval_metric': 'logloss'})
    else:
        base.update({'objective': 'multi:softprob', 'num_class': n_classes, 'eval_metric': 'mlogloss'})
    return base


NUM_BOOST_ROUND = 100
EARLY_STOPPING_ROUNDS = 20


class _BinaryProbaShim:
    """Wrap an XGBoost binary booster so predict() returns 2-D [P(0), P(1)].

    The classification evaluator + WF aggregator both assume multi-class
    softprob output (shape [n, n_classes]); binary:logistic returns 1-D. This
    adapter lets binary labels flow through the same evaluator path unchanged.
    """

    def __init__(self, booster: xgb.Booster) -> None:
        self._booster = booster

    def predict(self, dmat: xgb.DMatrix) -> np.ndarray:
        p = np.asarray(self._booster.predict(dmat))
        if p.ndim == 1:
            return np.column_stack([1.0 - p, p])
        return p

    def __getattr__(self, name: str):
        return getattr(self._booster, name)


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
        params = _xgb_params_for_n_classes(len(classes))

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


def _load_regime_cat_for_dates(db_path: Path, dates: pd.Series) -> pd.Series:
    """Fetch regime_cat from t2_regime_scores for the given dates (aligned to dates index).

    Mirrors the SQL in `src/backtest/runner.py::_load_regime_from_duckdb`.
    Missing dates get NaN; metrics_by_regime drops those slices when n < threshold.
    """
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        df = con.execute(
            """
            SELECT
                date,
                CASE
                    WHEN m03_score >= 75 THEN 4
                    WHEN m03_score >= 55 THEN 3
                    WHEN m03_score >= 35 THEN 2
                    WHEN m03_score >= 15 THEN 1
                    ELSE 0
                END AS regime_cat
            FROM t2_regime_scores
            """
        ).fetchdf()
    finally:
        con.close()
    df["date"] = pd.to_datetime(df["date"])
    lookup = dict(zip(df["date"], df["regime_cat"]))
    aligned = pd.to_datetime(pd.Series(dates).reset_index(drop=True))
    return aligned.map(lookup)


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
    parser.add_argument("--label-id", default="mfe_4class_v1",
                        help="Label registry id (file label_registry/<id>.json must exist).")
    parser.add_argument("--skip-parity", action="store_true",
                        help="Skip the train-vs-deploy feature parity check (emergency override).")
    parser.add_argument("--deploy-view", default="v_d3_deployment",
                        help="View used as the deployment side of the parity check.")
    parser.add_argument("--walk-forward", action="store_true",
                        help="Run anchored walk-forward training in addition to the standard split. "
                             "Per-fold artifacts + walk_forward_summary.json written to models/<name>/<version>/folds/.")
    parser.add_argument("--wf-step", default="1Y",
                        help="Walk-forward step size (1Y, 6M, 1Q, etc.).")
    parser.add_argument("--wf-test-start", default=None,
                        help="First fold's test_start date (YYYY-MM-DD). Defaults to 3y before max(date).")
    parser.add_argument("--wf-min-train-years", type=int, default=3,
                        help="Skip folds whose train window is shorter than this many years.")
    parser.add_argument("--with-perm-importance", action="store_true",
                        help="Compute permutation importance during evaluation (§3.3.1, diagnostic).")
    parser.add_argument("--perm-repeats", type=int, default=5)
    parser.add_argument("--perm-sample-size", type=int, default=2000)
    parser.add_argument("--with-regime-decomp", action="store_true",
                        help="Compute per-regime metrics via regime_cat from t2_regime_scores (§3.2 gate).")
    parser.add_argument("--skip-pretrain-audit", action="store_true",
                        help="Skip the pretrain data audit HTML report (§5.3). Default: audit runs.")
    parser.add_argument("--with-wf-backtest", action="store_true",
                        help="Run per-fold backtest on walk-forward folds (§3.1 gates). Requires --walk-forward.")
    parser.add_argument("--wf-backtest-output", default=None,
                        help="Output dir for per-fold backtest artifacts (default: models/<name>/<version>/wf_backtest/).")
    parser.add_argument("--wf-backtest-initial-cash", type=float, default=100_000.0,
                        help="Initial cash for each fold's SEPABacktestRunner.")
    parser.add_argument("--with-calibration", action="store_true",
                        help="Fit an isotonic probability calibrator on the val slice and save it "
                             "to models/<name>/<version>/calibrator.joblib. Adds pre/post ECE "
                             "to results.json. Only meaningful for binary classifiers.")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    logger.info("=" * 80)
    logger.info(f"MFE CLASSIFIER TRAINING — feature_set={args.feature_set}, model={args.model_name}")
    logger.info(f"Mode: {'NO-HOLDOUT (85/15/0)' if args.no_holdout else 'STANDARD (60/20/20)'}")
    logger.info("=" * 80)

    # 0. Load label definition (frozen at training time).
    label_def_path = LABEL_REGISTRY_DIR / f"{args.label_id}.json"
    if not label_def_path.exists():
        raise FileNotFoundError(
            f"Label '{args.label_id}' not found at {label_def_path}. "
            f"Authoring guide: docs/plans/evaluation_implementation_plan_2026_05_23.md §2.1.1."
        )
    label_def = LabelDefinition.from_json(label_def_path)
    logger.info(
        f"🏷️  Label: {label_def.label_id} (horizon={label_def.horizon_days}d, "
        f"fingerprint={label_def.fingerprint()[:12]})"
    )

    # 0b. Feature parity check (training-view vs deployment-view). Catches the
    # m01_rank-class bug where categorical encoding differs across views.
    if not args.skip_parity:
        try:
            parity = LeakageGuard.feature_parity_check(
                train_view="v_d2_training",
                deploy_view=args.deploy_view,
                feature_set_id=args.feature_set,
                db_path=args.db,
                sample_n=200,
            )
            status = parity["gate"]["status"]
            logger.info(
                f"🔁 feature_parity: {status} "
                f"(sampled={parity['sampled_pairs']}, mismatches={len(parity['mismatches'])}, "
                f"dtype_mismatches={len(parity['dtype_mismatches'])})"
            )
            if not parity["passed"] and status != "n/a":
                raise SystemExit(
                    "Feature parity check failed. Use --skip-parity to override "
                    "(then expect to debug your deployment view). Mismatches: "
                    f"{parity['mismatches'][:3]}"
                )
        except ValueError as e:
            # e.g., feature_set_id not in catalog — log and continue rather
            # than crash a training run that pre-dates catalog population.
            logger.warning(f"⚠️  feature_parity_check skipped: {e}")
    else:
        logger.warning("⚠️  feature_parity_check skipped via --skip-parity")

    # 1. Load feature set from catalog
    requested_features, feature_groups = get_feature_set(args.db, args.feature_set)
    logger.info(f"📋 Loaded {len(requested_features)} features from '{args.feature_set}'")

    # 2. Load training data
    df = load_training_data(args.db, feature_version=args.feature_version, min_date=args.min_date)

    # 2b. Pre-training data audit (§5.3) — diagnostic HTML report co-located with model artifacts.
    # Warn-only: a P0 DataQualityError logs but does not abort training.
    if not args.skip_pretrain_audit:
        model_dir_early = Path(__file__).parent.parent / "models" / args.model_name / args.model_version
        model_dir_early.mkdir(parents=True, exist_ok=True)
        audit_path = model_dir_early / "pretrain_audit.html"
        logger.info(f"🔎 Running pretrain audit → {audit_path}")
        try:
            rep = run_pretrain_audit(mode="trades", output_path=audit_path)
            logger.info(
                f"✅ Pretrain audit: {rep.n_rows:,} rows, {rep.n_features} features, "
                f"quality={'PASS' if rep.quality.passed else 'FAIL'}"
            )
            if rep.quality.bad_tickers:
                logger.warning(f"   ⚠️  Bad tickers: {len(rep.quality.bad_tickers)}")
            if rep.quality.leakage_cols:
                logger.warning(f"   ⚠️  Leakage cols: {rep.quality.leakage_cols}")
        except DataQualityError as e:
            logger.warning(f"⚠️  Pretrain audit P0 quality failure (continuing training): {e}")
        except Exception as e:
            logger.warning(f"⚠️  Pretrain audit raised non-DQ exception (continuing): {e}")

    # 3. Validate features
    valid_features, missing_features = validate_features(df, requested_features)
    if missing_features:
        logger.warning(f"⚠️  Missing {len(missing_features)} features:")
        for feat in missing_features[:10]:
            logger.warning(f"   - {feat}")
        if len(missing_features) > 10:
            logger.warning(f"   ... and {len(missing_features) - 10} more")
    logger.info(f"✅ Valid features: {len(valid_features)}")

    # 4. Labels + features — bins come from the frozen label definition
    label_bins = list(label_def.bins) if label_def.bins else [2.0, 10.0, 30.0]
    y = create_mfe_labels(df, bins=label_bins, return_col='mfe_pct')
    n_classes = len(label_bins) + 1
    class_names = _class_names_from_bins(label_bins)
    train_params = _xgb_params_for_n_classes(n_classes)
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
    booster, training_info = train_mfe_classifier(X_train, y_train, X_val, y_val, params=train_params)
    # Wrap binary objective so evaluator gets 2-D probabilities. Multi-class passes through.
    model = _BinaryProbaShim(booster) if n_classes == 2 else booster

    # 8. Evaluate
    output_dir = Path(__file__).parent.parent / "models"
    output_dir.mkdir(parents=True, exist_ok=True)

    evaluator = ClassificationEvaluator(
        model_name=args.model_name,
        model_version=args.model_version,
        output_dir=output_dir,
        class_names=class_names,
    )
    # Carry reproducibility identifiers into the results.json _metadata block.
    evaluator.label_registry_id = label_def.label_id
    evaluator.feature_set_id = args.feature_set
    # Optionally fetch regime_cat aligned to X_test dates for regime decomposition.
    regimes_test = None
    if args.with_regime_decomp:
        try:
            regimes_test = _load_regime_cat_for_dates(args.db, dates_test)
            logger.info(f"📡 Loaded regime_cat for {regimes_test.notna().sum()} of {len(regimes_test)} test rows")
        except Exception as e:
            logger.warning(f"⚠️  --with-regime-decomp could not fetch regime_cat: {e}")
            regimes_test = None

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
        compute_permutation_importance=args.with_perm_importance,
        permutation_n_repeats=args.perm_repeats,
        permutation_sample_size=args.perm_sample_size,
        regimes_test=regimes_test,
    )

    # 9. Save model + metadata
    model_dir = output_dir / args.model_name / args.model_version
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / "model.json"
    booster.save_model(str(model_path))
    logger.info(f"💾 Model saved to {model_path}")

    # 9a. Isotonic probability calibration (binary only).
    # Fitted on the val slice; persisted alongside model.json so backtest /
    # deployment can apply it transparently. Pre/post ECE merged into
    # results.json for audit. Non-fatal if it errors — model still ships.
    if args.with_calibration:
        if n_classes != 2:
            logger.warning(
                "⚠️  --with-calibration set but n_classes=%d; isotonic calibrator "
                "expects binary labels. Skipping.", n_classes
            )
        else:
            try:
                X_val_clean = X_val.replace([np.inf, -np.inf], np.nan)
                dval = xgb.DMatrix(X_val_clean, enable_categorical=True)
                proba_val = np.asarray(booster.predict(dval))
                p_raw_pos = proba_val if proba_val.ndim == 1 else proba_val[:, 1]
                y_val_arr = np.asarray(y_val.values if hasattr(y_val, "values") else y_val)

                pre_ece = expected_calibration_error(y_val_arr, p_raw_pos, n_bins=10)["ece"]
                cal = IsotonicCalibrator().fit(y_val_arr, p_raw_pos, model_version_id=None)
                p_cal_pos = cal.transform(p_raw_pos)
                post_ece = expected_calibration_error(y_val_arr, p_cal_pos, n_bins=10)["ece"]
                cal.metadata.pre_ece = float(pre_ece)
                cal.metadata.post_ece = float(post_ece)

                cal_path = calibrator_path_for(model_dir)
                cal.save(cal_path)
                logger.info(
                    "📐 Calibrator: pre_ece=%.4f → post_ece=%.4f (n_fit=%d)",
                    pre_ece, post_ece, len(y_val_arr),
                )

                # Merge calibration block into results.json so the report + gates see it.
                results_json_path = evaluator.eval_dir / "results.json"
                if results_json_path.exists():
                    existing = json.loads(results_json_path.read_text())
                    existing["calibration"] = {
                        "method": "isotonic",
                        "pre_ece": float(pre_ece),
                        "post_ece": float(post_ece),
                        "n_fit_samples": int(len(y_val_arr)),
                        "calibrator_path": str(cal_path.relative_to(model_dir.parent.parent)),
                    }
                    existing.setdefault("gates", []).append({
                        "name": "calibration_ece_post",
                        "status": "pass" if post_ece < 0.10 else "fail",
                        "value": float(post_ece),
                        "threshold": 0.10,
                        "detail": f"post-isotonic ECE (pre={pre_ece:.4f})",
                        "blocking": True,
                    })
                    results_json_path.write_text(json.dumps(existing, indent=2, default=str))
                    logger.info("📝 Calibration metrics merged into %s", results_json_path)
            except Exception as e:
                logger.warning("⚠️  Calibration step failed (non-blocking): %s", e)

    # Freeze the label definition into the artifact dir.
    label_def.to_json(model_dir / "label_definition.json")
    logger.info(f"🏷️  Label definition frozen at {model_dir / 'label_definition.json'}")

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

    # 9b. Freeze PSI reference snapshot (numeric features only — categoricals
    # are skipped by `reference_snapshot` when not coercible to numeric).
    try:
        snapshot_path = model_dir / "reference_snapshot.json"
        # Use the training slice as the immutable baseline.
        psi_features = [c for c in valid_features if c not in cat_mapping]
        reference_snapshot(
            train_df=X_train,
            feature_cols=psi_features,
            output_path=snapshot_path,
            bins=10,
            model_version_id=None,  # version_id is assigned later in step 10
        )
    except Exception as e:
        logger.warning(f"⚠️  PSI reference snapshot failed (non-blocking): {e}")

    # 10. Register in model registry
    registry = ModelRegistry(db_path=args.db)
    version_id = f'{args.model_name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    git_sha = ModelRegistry.get_git_sha()

    # In --no-holdout mode, leave the test-metric columns NULL — they'd be misleading.
    accuracy = eval_results.get('accuracy') if not args.no_holdout else None
    weighted_f1 = eval_results.get('weighted_f1') if not args.no_holdout else None
    macro_f1 = eval_results.get('macro_f1') if not args.no_holdout else None

    hyperparams = {k: v for k, v in train_params.items()
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
                    'label_thresholds': label_bins,
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

    # 11. Walk-forward (additive — only runs when --walk-forward is set).
    if args.walk_forward:
        logger.info("=" * 80)
        logger.info("🔁 WALK-FORWARD MODE — anchored, step=%s, min_train_years=%d",
                    args.wf_step, args.wf_min_train_years)
        logger.info("=" * 80)
        wf_results, fold_results = _run_walk_forward_block(
            df_sorted=df_sorted,
            X_sorted=X_sorted,
            y_sorted=y_sorted,
            valid_features=valid_features,
            class_names=class_names,
            model_dir=model_dir,
            train_params=train_params,
            wf_step=args.wf_step,
            wf_test_start=args.wf_test_start,
            wf_min_train_years=args.wf_min_train_years,
        )
        # Merge WF gates into the model's evaluation results.json so the
        # promotion gate (§6) sees them.
        results_json_path = evaluator.eval_dir / "results.json"
        if results_json_path.exists():
            try:
                existing = json.loads(results_json_path.read_text())
                existing.setdefault("gates", []).extend(wf_results.get("gates", []))
                existing["walk_forward_summary"] = wf_results.get("summary", {})
                results_json_path.write_text(json.dumps(existing, indent=2, default=str))
                logger.info(f"📝 Walk-forward gates merged into {results_json_path}")
            except Exception as e:
                logger.warning(f"Could not merge WF gates into results.json: {e}")

        # 11b. Walk-forward backtest (§3.1) — only when --with-wf-backtest is set.
        if args.with_wf_backtest and fold_results:
            logger.info("=" * 80)
            logger.info("🪙 WALK-FORWARD BACKTEST — %d folds via SEPABacktestRunner",
                        len(fold_results))
            logger.info("=" * 80)
            wf_bt_dir = (
                Path(args.wf_backtest_output) if args.wf_backtest_output
                else model_dir / "wf_backtest"
            )
            # If we fitted a calibrator, point the WF backtest at it so each
            # fold's prob_elite is in true-base-rate units (matters for any
            # absolute-threshold strategy run later).
            cal_path = calibrator_path_for(model_dir)
            wf_calibrator_path = cal_path if cal_path.exists() else None
            try:
                wf_bt_agg = _run_walk_forward_backtest_block(
                    fold_results=fold_results,
                    output_dir=wf_bt_dir,
                    production_class_idx=len(class_names) - 1,
                    db_path=args.db,
                    initial_cash=args.wf_backtest_initial_cash,
                    calibrator_path=wf_calibrator_path,
                )
                # Merge into results.json so the §6 promotion gate sees these too.
                if results_json_path.exists():
                    try:
                        existing = json.loads(results_json_path.read_text())
                        existing.setdefault("gates", []).extend(wf_bt_agg.get("gates", []))
                        existing["wf_backtest_summary"] = wf_bt_agg.get("summary", {})
                        results_json_path.write_text(json.dumps(existing, indent=2, default=str))
                        logger.info(f"📝 WF-backtest gates merged into {results_json_path}")
                    except Exception as e:
                        logger.warning(f"Could not merge WF-backtest gates: {e}")
            except Exception as e:
                logger.warning(f"⚠️  WF-backtest failed (non-blocking): {e}")
        elif args.with_wf_backtest and not fold_results:
            logger.warning("--with-wf-backtest set but no folds were produced; skipping.")

    logger.info("=" * 80)
    logger.info("✅ TRAINING COMPLETE")
    logger.info(f"📁 Model: {model_path}")
    logger.info(f"📁 Evaluation: {evaluator.eval_dir}")
    metric_label = "Val" if args.no_holdout else "Test"
    logger.info(f"🎯 {metric_label} Accuracy: {eval_results.get('accuracy', 0):.3f}")
    logger.info(f"📊 {metric_label} Weighted F1: {eval_results.get('weighted_f1', 0):.3f}")
    logger.info(f"📊 {metric_label} Macro F1: {eval_results.get('macro_f1', 0):.3f}")
    logger.info("=" * 80)


def _run_walk_forward_block(
    df_sorted: pd.DataFrame,
    X_sorted: pd.DataFrame,
    y_sorted: pd.Series,
    valid_features: list[str],
    class_names: list[str],
    model_dir: Path,
    train_params: dict,
    wf_step: str,
    wf_test_start: str | None,
    wf_min_train_years: int,
) -> tuple[dict, list]:
    """Run anchored walk-forward over `df_sorted` and write per-fold artifacts.

    Returns:
        (aggregate_dict, fold_results) — fold_results is needed for an optional
        WF-backtest pass; agg is the classification aggregation written to
        walk_forward_summary.json.
    """
    panel = X_sorted.copy()
    panel["date"] = pd.to_datetime(df_sorted["date"]).values
    panel["__y__"] = y_sorted.values
    # Stash ticker on the panel so we can re-attach it to each fold's X_test
    # post-hoc (run_walk_forward strips non-feature cols from X_test).
    panel["__ticker__"] = df_sorted["ticker"].astype(str).values

    min_date = panel["date"].min().date()
    max_date = panel["date"].max().date()
    train_start = min_date
    if wf_test_start:
        test_start = pd.to_datetime(wf_test_start).date()
    else:
        # Default: leave the last 3 calendar years as the test window.
        from datetime import date as _date
        test_start = _date(max_date.year - 3, max_date.month, 1)
    test_end = max_date

    specs = list(
        anchored_walk_forward(
            panel,
            date_col="date",
            train_start=train_start,
            test_start=test_start,
            test_end=test_end,
            step=wf_step,
            min_train_years=wf_min_train_years,
        )
    )
    logger.info(f"📐 Generated {len(specs)} walk-forward folds")
    if not specs:
        logger.warning("No walk-forward folds produced — check --wf-min-train-years.")
        return {"per_fold": [], "summary": {}, "gates": []}

    def train_fn(X: pd.DataFrame, y: pd.Series) -> xgb.Booster:
        Xc = X.replace([np.inf, -np.inf], np.nan)
        classes = np.unique(y)
        weights = compute_class_weight('balanced', classes=classes, y=y)
        sample_weights = y.map(dict(zip(classes, weights)))
        dtrain = xgb.DMatrix(Xc, label=y, weight=sample_weights, enable_categorical=True)
        return xgb.train(train_params, dtrain, num_boost_round=NUM_BOOST_ROUND)

    folds_dir = model_dir / "folds"
    folds_dir.mkdir(parents=True, exist_ok=True)
    fold_results = run_walk_forward(
        df=panel,
        date_col="date",
        feature_cols=valid_features,
        target_col="__y__",
        fold_specs=specs,
        train_fn=train_fn,
        output_dir=folds_dir,
    )

    # Re-attach `date` + `ticker` to each fold's X_test. run_walk_forward
    # strips them since they aren't in feature_cols, but the WF-backtest
    # signal builder needs them. FoldResult.X_test preserves the panel's
    # row index, so we can map back through `panel`.
    for fr in fold_results:
        idx = fr.X_test.index
        fr.X_test = fr.X_test.copy()
        fr.X_test["date"] = panel.loc[idx, "date"].values
        fr.X_test["ticker"] = panel.loc[idx, "__ticker__"].values

    # Production class = last actionable class (Home Run for MFE 4-class).
    production_class_idx = len(class_names) - 1
    agg = aggregate_walk_forward(
        fold_results,
        class_names=class_names,
        production_class_idx=production_class_idx,
        worst_fold_auc_threshold=0.65,
    )
    summary_path = model_dir / "evaluation" / "walk_forward_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(agg, indent=2, default=str))
    logger.info(f"📊 Walk-forward summary: {summary_path}")
    for g in agg.get("gates", []):
        logger.info(f"   gate {g['name']}: {g['status']} (value={g.get('value')})")
    return agg, fold_results


def _run_walk_forward_backtest_block(
    fold_results: list,
    output_dir: Path,
    production_class_idx: int,
    db_path: Path,
    initial_cash: float = 100_000.0,
    calibrator_path: Optional[Path] = None,
    trailing_window: int = 10,
) -> dict:
    """Run a SEPA backtest per fold and emit aggregated gates.

    Each fold's `X_test` must already carry `date` + `ticker` columns —
    the caller (_run_walk_forward_block) re-attaches them before invoking.

    Args:
        fold_results: from `run_walk_forward`. X_test must have date + ticker.
        output_dir: per-fold artifacts (trades, equity, metrics) go under here.
        production_class_idx: which proba column the strategy treats as elite.
        db_path: DuckDB path passed to SEPABacktestRunner.
        initial_cash: starting cash for each fold's runner.

    Returns:
        Aggregate dict from `aggregate_walk_forward_backtest` (per_fold,
        summary, gates).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    from src.backtest.runner import SEPABacktestRunner
    from src.backtest.strategy_registry import STRATEGIES
    from src.backtest.macro_sizer import spy_above_200d

    # The promotion gate must judge the model in the CONFIG it deploys in —
    # champion_trail_spygate (trail exit + SPY-200d deploy gate), NOT the runner's
    # bare defaults. spy_deploy_gate is a per-window {date->bool} sentinel, filled
    # per fold (same pattern as run_strategy_confirm._run_arm).
    champion_kwargs = dict(STRATEGIES["champion_trail_spygate"].strategy_kwargs)

    def backtest_fn(scores_df: pd.DataFrame, fold_dir: Path) -> dict:
        # Date range = the span of this fold's scores.
        if scores_df.empty:
            return {"sharpe_ratio": None, "max_drawdown": None,
                    "win_rate": None, "total_return": None,
                    "trades_df": pd.DataFrame(), "equity_df": pd.DataFrame()}
        start = pd.to_datetime(scores_df["date"]).min().strftime("%Y-%m-%d")
        end = pd.to_datetime(scores_df["date"]).max().strftime("%Y-%m-%d")

        kwargs = dict(champion_kwargs)
        kwargs["spy_deploy_gate"] = spy_above_200d(start, end, str(db_path))

        runner = SEPABacktestRunner(
            start_date=start,
            end_date=end,
            initial_cash=initial_cash,
            db_path=str(db_path),
            # model_path/version intentionally None — scores_df is already built
            # from this fold's classifier; runner does not re-score.
            model_path=None,
            model_version_id=None,
        )
        runner.setup(scores_df=scores_df, strategy_kwargs=kwargs)
        metrics = runner.run()
        equity = runner.get_equity_curve_dataframe()
        trades = runner.get_trade_dataframe()
        if equity is None:
            equity = pd.DataFrame()
        if trades is None:
            trades = pd.DataFrame()
        # Flatten — drop nested dicts so JSON dumps cleanly.
        flat = {k: v for k, v in metrics.items()
                if not isinstance(v, (dict, list))}
        flat["trades_df"] = trades
        flat["equity_df"] = equity if isinstance(equity, pd.DataFrame) else pd.DataFrame()
        return flat

    bt_results = run_walk_forward_backtest(
        fold_results=fold_results,
        production_class_idx=production_class_idx,
        backtest_fn=backtest_fn,
        output_dir=output_dir,
        calibrator_path=calibrator_path,
        trailing_window=trailing_window,
    )
    agg = aggregate_walk_forward_backtest(bt_results)
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(agg, indent=2, default=str))
    logger.info(f"📊 WF-backtest summary: {summary_path}")
    for g in agg.get("gates", []):
        logger.info(f"   gate {g['name']}: {g['status']} (value={g.get('value')})")
    return agg


if __name__ == "__main__":
    main()
