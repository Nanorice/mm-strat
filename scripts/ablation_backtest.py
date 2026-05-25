"""Ablation backtest CLI (§3.3.2).

For each feature group passed in `--feature-groups`, retrains the classifier
with that group's features removed, runs a backtest over the same time
window, captures (delta_sharpe, delta_return) vs the full-feature baseline.

Output is `models/<name>/<version>/ablation/ablation_summary.json` and a
horizontal bar plot of delta-Sharpe by group.

Usage:
    python scripts/ablation_backtest.py \\
      --model-version M01_baseline_v0.1 \\
      --feature-groups Momentum,RegimeContext,Volume \\
      --output models/M01_baseline_v0.1/ablation/
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import pandas as pd
import xgboost as xgb

from src.evaluation.ablation import (
    AblationDelta,
    ablation_summary_payload,
    compute_ablation_delta,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ablation backtest CLI")
    parser.add_argument("--model-version", required=True,
                        help="Model version_id (e.g., M01_baseline_v0.1)")
    parser.add_argument("--model-name", required=True,
                        help="Model family name (used to compose artifact paths)")
    parser.add_argument("--feature-set", required=True,
                        help="Feature set id in `model_feature_sets`")
    parser.add_argument("--feature-groups", required=True,
                        help="Comma-separated group names to ablate (must exist in model_feature_sets.feature_group)")
    parser.add_argument("--output", type=Path, required=True,
                        help="Output dir for ablation_summary.json + plot")
    parser.add_argument("--feature-version", default="v3.1")
    parser.add_argument("--min-date", default="2003-01-01")
    parser.add_argument("--backtest-start", default="2020-01-01")
    parser.add_argument("--backtest-end", default="2025-01-01")
    parser.add_argument("--label-id", default=None,
                        help="Label registry id (e.g., mfe_binary_homerun_v1). If omitted, "
                             "reads label_definition.json from the source model dir; if that "
                             "is also missing, falls back to 4-class bins=[2,10,30] for back-compat.")
    parser.add_argument("--db", type=Path,
                        default=Path(__file__).resolve().parent.parent / "data" / "market_data.duckdb")
    parser.add_argument("--no-backtest", action="store_true",
                        help="Skip Backtrader execution; measure ablation impact via classification "
                             "metrics only (ROC-AUC, weighted-F1, positive-class precision). "
                             "Use this to isolate model quality from strategy effects.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip retraining + backtest; emit a placeholder summary.")
    return parser.parse_args()


def load_feature_set_with_groups(db_path: Path, feature_set_id: str) -> Tuple[List[str], Dict[str, List[str]]]:
    import duckdb
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
        raise ValueError(f"Feature set '{feature_set_id}' missing or empty.")
    features = [r[0] for r in rows]
    groups: Dict[str, List[str]] = {}
    for name, group in rows:
        groups.setdefault(group or "Ungrouped", []).append(name)
    return features, groups


def train_with_features(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    feature_cols: List[str],
    params: dict,
    num_boost_round: int = 100,
) -> xgb.Booster:
    from sklearn.utils.class_weight import compute_class_weight
    classes = np.unique(y_train)
    weights = compute_class_weight("balanced", classes=classes, y=y_train)
    sample_weights = y_train.map(dict(zip(classes, weights)))
    Xc = X_train[feature_cols].replace([np.inf, -np.inf], np.nan)
    dtrain = xgb.DMatrix(Xc, label=y_train, weight=sample_weights, enable_categorical=True)
    return xgb.train(params, dtrain, num_boost_round=num_boost_round)


def run_baseline_and_ablations(
    df: pd.DataFrame,
    features_all: List[str],
    feature_groups: Dict[str, List[str]],
    groups_to_ablate: List[str],
    backtest_fn,
    train_params: dict,
    output_dir: Path,
) -> dict:
    """Pure orchestrator — kept narrow so the I/O-heavy bits are testable
    by injecting `backtest_fn`.

    `backtest_fn(model, feature_cols, label) -> metrics_dict` evaluates one
    model and returns a metrics dict.  In backtest mode it must contain at
    minimum `sharpe_ratio`; in --no-backtest mode it contains `roc_auc`,
    `weighted_f1`, and `pos_class_precision`.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Baseline
    logger.info("📐 Training baseline with all %d features", len(features_all))
    baseline_model = train_with_features(df, df["__y__"], features_all, train_params)
    baseline_metrics = backtest_fn(baseline_model, features_all, "baseline")

    deltas: List[AblationDelta] = []
    for group in groups_to_ablate:
        group_features = feature_groups.get(group, [])
        if not group_features:
            logger.warning("group %s has no features — skipping", group)
            continue
        kept = [f for f in features_all if f not in set(group_features)]
        logger.info("🧪 Ablating group=%s (%d features) → training on %d remaining",
                    group, len(group_features), len(kept))
        ablated_model = train_with_features(df, df["__y__"], kept, train_params)
        ablated_metrics = backtest_fn(ablated_model, kept, f"ablate_{group}")
        deltas.append(compute_ablation_delta(baseline_metrics, ablated_metrics, group))

    payload = ablation_summary_payload(deltas, baseline_metrics)
    summary_path = output_dir / "ablation_summary.json"
    summary_path.write_text(json.dumps(payload, indent=2, default=str))
    logger.info("💾 Wrote %s", summary_path)
    return payload


def plot_ablation_impact(payload: dict, output_path: Path) -> None:
    """Horizontal bar chart of delta_sharpe by feature group."""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("matplotlib not installed — skipping plot")
        return

    ablations = payload.get("ablations", [])
    if not ablations:
        logger.warning("no ablations to plot")
        return

    groups = [a["group_dropped"] for a in ablations]
    deltas = [a["delta_sharpe"] for a in ablations]

    fig, ax = plt.subplots(figsize=(8, max(3, len(groups) * 0.4)))
    colors = ["#d63b3b" if d < 0 else "#3bb04f" for d in deltas]
    ax.barh(groups, deltas, color=colors, alpha=0.85)
    ax.axvline(0, color="black", linewidth=0.6)
    ax.set_xlabel("Δ Sharpe (ablated − baseline)")
    ax.set_title("Ablation impact on Sharpe")
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("🎨 Saved %s", output_path)


def main() -> int:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        logger.info("🟡 --dry-run: emitting placeholder summary")
        if args.no_backtest:
            baseline_placeholder = {"roc_auc": 0.0, "weighted_f1": 0.0, "pos_class_precision": 0.0}
        else:
            baseline_placeholder = {"sharpe_ratio": 0.0, "total_return": 0.0,
                                     "max_drawdown": 0.0, "win_rate": 0.0}
        payload = {
            "baseline": baseline_placeholder,
            "ablations": [],
            "note": "dry run — no training or evaluation executed",
        }
        (args.output / "ablation_summary.json").write_text(json.dumps(payload, indent=2))
        return 0

    # Lazy imports so dry-run / tests don't pay for DuckDB.
    from scripts.train_mfe_classifier import (
        _xgb_params_for_n_classes,
        create_mfe_labels,
        load_training_data,
    )
    if not args.no_backtest:
        from src.backtest.runner import SEPABacktestRunner
        from src.backtest.universe_scorer import UniverseScorer

    features, groups = load_feature_set_with_groups(args.db, args.feature_set)

    # Cross-sectional rank columns come out of DuckDB in TitleCase via the
    # daily_features pipeline (UPDATE ... SET RS_Sector_Rank = ...). The
    # `model_feature_sets` catalog has them lowercase. Bridge here so training
    # downstream finds them in df.
    _titlecase_map = {
        "rs_sector_rank": "RS_Sector_Rank",
        "rs_vs_sector": "RS_vs_Sector",
        "sector_momentum": "Sector_Momentum",
        "rs_industry_rank": "RS_Industry_Rank",
        "rs_vs_industry": "RS_vs_Industry",
        "industry_momentum": "Industry_Momentum",
        "rs_universe_rank": "RS_Universe_Rank",
    }
    features = [_titlecase_map.get(f, f) for f in features]
    for group_name, members in list(groups.items()):
        groups[group_name] = [_titlecase_map.get(f, f) for f in members]

    requested = [g.strip() for g in args.feature_groups.split(",") if g.strip()]
    unknown = [g for g in requested if g not in groups]
    if unknown:
        raise ValueError(f"Unknown feature group(s): {unknown}. Known: {sorted(groups)}")

    # Resolve label bins from --label-id, the source model's label_definition.json, or the
    # 4-class fallback. The number of classes drives the XGBoost objective; ablation deltas
    # must be measured under the same objective as the source model, not a hardcoded one.
    from src.evaluation.label_registry import LabelDefinition
    LABEL_REGISTRY_DIR = REPO_ROOT / "label_registry"
    src_model_dir = REPO_ROOT / "models" / args.model_name / args.model_version

    label_bins: List[float]
    label_id: str
    if args.label_id:
        label_path = LABEL_REGISTRY_DIR / f"{args.label_id}.json"
        if not label_path.exists():
            raise FileNotFoundError(f"--label-id '{args.label_id}' not found at {label_path}")
        label_def = LabelDefinition.from_json(label_path)
        label_bins = list(label_def.bins) if label_def.bins else [2.0, 10.0, 30.0]
        label_id = label_def.label_id
        logger.info(f"📛 Label from --label-id: {label_id} (bins={label_bins})")
    elif (src_model_dir / "label_definition.json").exists():
        label_def = LabelDefinition.from_json(src_model_dir / "label_definition.json")
        label_bins = list(label_def.bins) if label_def.bins else [2.0, 10.0, 30.0]
        label_id = label_def.label_id
        logger.info(f"📛 Label from source model: {label_id} (bins={label_bins})")
    else:
        label_bins = [2.0, 10.0, 30.0]
        label_id = "fallback_4class"
        logger.warning("📛 No --label-id or source label_definition.json — falling back to 4-class bins=[2,10,30]")

    df = load_training_data(args.db, feature_version=args.feature_version, min_date=args.min_date)
    y = create_mfe_labels(df, bins=label_bins, return_col="mfe_pct")
    df = df.copy()
    df["__y__"] = y

    # Convert object columns to category (XGBoost requirement)
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].astype("category")

    n_classes = len(label_bins) + 1
    train_params = _xgb_params_for_n_classes(n_classes)
    logger.info(f"🧪 Ablation objective: {train_params.get('objective')} (n_classes={n_classes})")

    # Copy the original model's categorical_mapping.json next to tmp models so
    # UniverseScorer (which reads m01_path.parent/categorical_mapping.json)
    # finds consistent sector/industry encodings.
    import shutil
    src_cat_map = REPO_ROOT / "models" / args.model_name / args.model_version / "categorical_mapping.json"
    if src_cat_map.exists():
        shutil.copy(src_cat_map, args.output / "categorical_mapping.json")
        logger.info("Copied categorical_mapping.json into ablation output dir")

    if args.no_backtest:
        # Pure classification evaluation — no Backtrader, no strategy effects.
        # Splits df by backtest_start to give an out-of-sample hold-out; uses
        # the full pre-start window for training (mirrors how backtest_fn works).
        from sklearn.metrics import roc_auc_score, f1_score, precision_score

        y_all = df["__y__"].values
        in_sample_mask = pd.to_datetime(df["date"]) < pd.Timestamp(args.backtest_start)
        oos_mask = ~in_sample_mask

        if oos_mask.sum() == 0:
            raise ValueError(
                f"--backtest-start={args.backtest_start} leaves no out-of-sample rows. "
                "Lower --backtest-start or widen --min-date."
            )

        def eval_fn(model: xgb.Booster, feature_cols: List[str], label: str) -> dict:
            Xc = df.loc[oos_mask, feature_cols].replace([np.inf, -np.inf], np.nan)
            dmat = xgb.DMatrix(Xc, enable_categorical=True)
            proba = model.predict(dmat)           # shape (n,) binary or (n, k) multiclass
            y_oos = y_all[oos_mask]
            n_classes = len(np.unique(y_all))

            if proba.ndim == 1 or (proba.ndim == 2 and proba.shape[1] == 1):
                # Binary: proba is positive-class probability
                p1d = proba.ravel()
                try:
                    auc = roc_auc_score(y_oos, p1d)
                except ValueError:
                    auc = float("nan")
                pred = (p1d >= 0.5).astype(int)
                wf1 = f1_score(y_oos, pred, average="weighted", zero_division=0)
                prec = precision_score(y_oos, pred, pos_label=1, zero_division=0)
            else:
                # Multiclass: use last class (highest MFE bin) as "positive"
                pos_idx = proba.shape[1] - 1
                try:
                    auc = roc_auc_score(y_oos, proba, multi_class="ovr", average="weighted")
                except ValueError:
                    auc = float("nan")
                pred = proba.argmax(axis=1)
                wf1 = f1_score(y_oos, pred, average="weighted", zero_division=0)
                prec = precision_score(y_oos, pred, labels=[pos_idx],
                                       average="micro", zero_division=0)

            logger.info("  [%s] roc_auc=%.4f  weighted_f1=%.4f  pos_precision=%.4f  oos_n=%d",
                        label, auc, wf1, prec, oos_mask.sum())
            return {"roc_auc": round(float(auc), 4),
                    "weighted_f1": round(float(wf1), 4),
                    "pos_class_precision": round(float(prec), 4)}

        eval_closure = eval_fn
        logger.info("⚙️  --no-backtest: ablation measured via classification metrics on %d OOS rows "
                    "(%s → %s)", oos_mask.sum(), args.backtest_start, args.backtest_end)
    else:
        # Full Backtrader path — strategy metrics drive ablation deltas.
        def backtest_fn(model: xgb.Booster, feature_cols: List[str], label: str) -> dict:
            tmp_dir = args.output / label
            tmp_dir.mkdir(parents=True, exist_ok=True)
            tmp_model_path = tmp_dir / "model.json"
            model.save_model(str(tmp_model_path))
            (tmp_dir / "metadata.json").write_text(json.dumps({
                "valid_features": feature_cols,
                "feature_version": args.feature_version,
            }, indent=2))
            if src_cat_map.exists():
                shutil.copy(src_cat_map, tmp_dir / "categorical_mapping.json")
            scorer = UniverseScorer(m01_path=str(tmp_model_path), calibration_path=None)
            scorer.load_model()
            scores_df = scorer.score_from_t3(args.backtest_start, args.backtest_end)
            runner = SEPABacktestRunner(
                start_date=args.backtest_start,
                end_date=args.backtest_end,
                model_path=str(tmp_model_path),
            )
            runner.setup(scores_df=scores_df)
            return runner.run()

        eval_closure = backtest_fn

    payload = run_baseline_and_ablations(
        df=df,
        features_all=features,
        feature_groups=groups,
        groups_to_ablate=requested,
        backtest_fn=eval_closure,
        train_params=train_params,
        output_dir=args.output,
    )
    plot_ablation_impact(payload, args.output / "ablation_impact.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
