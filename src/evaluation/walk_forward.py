"""Anchored walk-forward classification harness.

The whitepaper §5.1 spec is anchored, not sliding:
  - `train_start` is fixed (e.g. 2010-01-01)
  - `train_end` advances by `step`
  - each fold tests on (train_end, train_end + step]

Why anchored: sliding-window WF discards regime data the model could still
benefit from. Anchored mirrors how the production system will eventually be
retrained — cumulative history, fresh test window.

Module responsibilities:
  - `anchored_walk_forward`: yield FoldSpecs for a date range.
  - `run_walk_forward`: train one model per fold, serialize, return per-fold results.
  - `aggregate_walk_forward`: aggregate per-fold metrics + emit gates.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Iterator, List, Optional, Tuple

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score

from .gate import GateResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FoldSpec:
    fold_idx: int
    train_start: date
    train_end: date  # inclusive
    test_start: date
    test_end: date

    def to_dict(self) -> dict:
        return {
            "fold_idx": self.fold_idx,
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "test_start": self.test_start.isoformat(),
            "test_end": self.test_end.isoformat(),
        }


@dataclass
class FoldResult:
    spec: FoldSpec
    model_path: Optional[Path]
    X_test: pd.DataFrame
    y_test: pd.Series
    y_pred_proba: np.ndarray
    metrics: dict
    train_seconds: float


def _parse_step(step: str) -> Tuple[int, str]:
    """Parse '1Y' / '6M' / '1Q' / '90D' into (n, unit)."""
    s = step.strip().upper()
    if len(s) < 2:
        raise ValueError(f"unparseable step: {step!r}")
    unit = s[-1]
    try:
        n = int(s[:-1])
    except ValueError as e:
        raise ValueError(f"unparseable step: {step!r}") from e
    if unit not in {"Y", "Q", "M", "D"}:
        raise ValueError(f"unknown step unit {unit!r} in {step!r}")
    return n, unit


def _advance(d: date, step: str) -> date:
    """Advance d by the given step (Y/Q/M/D)."""
    n, unit = _parse_step(step)
    if unit == "Y":
        return date(d.year + n, d.month, min(d.day, 28))
    if unit == "Q":
        return _advance(d, f"{3 * n}M")
    if unit == "M":
        m = d.month - 1 + n
        year = d.year + m // 12
        month = m % 12 + 1
        return date(year, month, min(d.day, 28))
    # D
    return d + timedelta(days=n)


def anchored_walk_forward(
    df: pd.DataFrame,
    date_col: str,
    train_start: date,
    test_start: date,
    test_end: date,
    step: str = "1Y",
    min_train_years: int = 3,
) -> Iterator[FoldSpec]:
    """Yield FoldSpecs over (test_start, test_end] in `step`-sized windows.

    train_start is fixed; train_end = current test_start - 1 day; test window
    is [current test_start, current test_start + step].
    """
    if test_start <= train_start:
        raise ValueError("test_start must be after train_start")
    if test_end <= test_start:
        raise ValueError("test_end must be after test_start")

    dates = pd.to_datetime(df[date_col])
    min_date, max_date = dates.min().date(), dates.max().date()
    if train_start < min_date:
        logger.warning(
            "train_start=%s earlier than min(df.date)=%s; first fold may be empty",
            train_start, min_date,
        )

    fold_idx = 0
    cur_test_start = test_start
    while cur_test_start < test_end:
        cur_test_end = min(_advance(cur_test_start, step), test_end)
        cur_train_end = cur_test_start - timedelta(days=1)

        train_years = (cur_train_end - train_start).days / 365.25
        if train_years < min_train_years:
            logger.info(
                "fold_idx=%d skipped: only %.2fy of training data (<%d)",
                fold_idx, train_years, min_train_years,
            )
            cur_test_start = cur_test_end
            continue

        yield FoldSpec(
            fold_idx=fold_idx,
            train_start=train_start,
            train_end=cur_train_end,
            test_start=cur_test_start,
            test_end=cur_test_end,
        )
        fold_idx += 1
        cur_test_start = cur_test_end


def _slice_panel(
    df: pd.DataFrame,
    date_col: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    dates = pd.to_datetime(df[date_col]).dt.date
    return df.loc[(dates >= start) & (dates <= end)].copy()


def run_walk_forward(
    df: pd.DataFrame,
    date_col: str,
    feature_cols: List[str],
    target_col: str,
    fold_specs: List[FoldSpec],
    train_fn: Callable[[pd.DataFrame, pd.Series], xgb.Booster],
    output_dir: Path,
    serialize_models: bool = True,
) -> List[FoldResult]:
    """Train one model per fold and return per-fold results.

    `train_fn(X_train_df, y_train_series)` must return a fitted xgb.Booster
    (or anything with `.predict(DMatrix)` returning per-class probabilities).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results: List[FoldResult] = []
    for spec in fold_specs:
        train_slice = _slice_panel(df, date_col, spec.train_start, spec.train_end)
        test_slice = _slice_panel(df, date_col, spec.test_start, spec.test_end)
        if train_slice.empty or test_slice.empty:
            logger.warning(
                "fold_idx=%d skipped: train_rows=%d test_rows=%d",
                spec.fold_idx, len(train_slice), len(test_slice),
            )
            continue

        X_train = train_slice[feature_cols]
        y_train = train_slice[target_col]
        X_test = test_slice[feature_cols]
        y_test = test_slice[target_col]

        t0 = time.perf_counter()
        booster = train_fn(X_train, y_train)
        train_seconds = time.perf_counter() - t0

        # Score.
        # Use the model's predict path; assume booster returns class probs.
        try:
            dtest = xgb.DMatrix(X_test.replace([np.inf, -np.inf], np.nan), enable_categorical=True)
            proba = booster.predict(dtest)
        except Exception:
            # Allow non-xgb.Booster (e.g., sklearn-like) for tests.
            proba = booster.predict_proba(X_test)  # type: ignore[attr-defined]

        proba = np.asarray(proba)
        if proba.ndim == 1:
            # Binary: turn into 2-col proba.
            proba = np.column_stack([1 - proba, proba])

        y_pred = np.argmax(proba, axis=1)
        metrics = {
            "n_train": int(len(X_train)),
            "n_test": int(len(X_test)),
            "accuracy": float(accuracy_score(y_test, y_pred)),
            "weighted_f1": float(f1_score(y_test, y_pred, average="weighted", zero_division=0)),
            "macro_f1": float(f1_score(y_test, y_pred, average="macro", zero_division=0)),
        }

        model_path: Optional[Path] = None
        if serialize_models:
            fold_dir = output_dir / f"fold_{spec.fold_idx:02d}"
            fold_dir.mkdir(parents=True, exist_ok=True)
            model_path = fold_dir / "model.json"
            try:
                booster.save_model(str(model_path))
            except Exception as e:  # pragma: no cover — sklearn-like fallback
                logger.warning("Could not serialize model for fold %d: %s", spec.fold_idx, e)
                model_path = None
            (fold_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
            (fold_dir / "spec.json").write_text(json.dumps(spec.to_dict(), indent=2))

        results.append(
            FoldResult(
                spec=spec,
                model_path=model_path,
                X_test=X_test,
                y_test=y_test,
                y_pred_proba=proba,
                metrics=metrics,
                train_seconds=train_seconds,
            )
        )

    return results


def aggregate_walk_forward(
    fold_results: List[FoldResult],
    class_names: List[str],
    production_class_idx: int,
    worst_fold_auc_threshold: float = 0.65,
    baseline_f1: Optional[float] = None,
    in_sample_drift_tol: float = 0.10,
) -> dict:
    """Aggregate per-fold metrics and emit gates."""
    if not fold_results:
        return {"per_fold": [], "summary": {}, "gates": []}

    rows = []
    aggregate_cm = None
    aucs: List[float] = []
    for fr in fold_results:
        y_true = np.asarray(fr.y_test)
        proba = fr.y_pred_proba
        y_pred = np.argmax(proba, axis=1)

        # ROC-AUC for the production class (one-vs-rest).
        try:
            auc = float(
                roc_auc_score(
                    (y_true == production_class_idx).astype(int),
                    proba[:, production_class_idx],
                )
            )
        except ValueError:
            auc = float("nan")
        aucs.append(auc)

        # Confusion-matrix sum.
        from sklearn.metrics import confusion_matrix
        cm = confusion_matrix(y_true, y_pred, labels=list(range(len(class_names))))
        aggregate_cm = cm if aggregate_cm is None else aggregate_cm + cm

        rows.append(
            {
                "fold_idx": fr.spec.fold_idx,
                "train_start": fr.spec.train_start.isoformat(),
                "train_end": fr.spec.train_end.isoformat(),
                "test_start": fr.spec.test_start.isoformat(),
                "test_end": fr.spec.test_end.isoformat(),
                "n_train": fr.metrics["n_train"],
                "n_test": fr.metrics["n_test"],
                "accuracy": fr.metrics["accuracy"],
                "weighted_f1": fr.metrics["weighted_f1"],
                "macro_f1": fr.metrics["macro_f1"],
                f"roc_auc_{class_names[production_class_idx]}": auc,
                "train_seconds": fr.train_seconds,
            }
        )

    df = pd.DataFrame(rows)
    summary = {
        "n_folds": int(len(df)),
        "accuracy_mean": float(df["accuracy"].mean()),
        "accuracy_std": float(df["accuracy"].std(ddof=0)),
        "accuracy_worst": float(df["accuracy"].min()),
        "weighted_f1_mean": float(df["weighted_f1"].mean()),
        "weighted_f1_std": float(df["weighted_f1"].std(ddof=0)),
        "weighted_f1_worst": float(df["weighted_f1"].min()),
        "macro_f1_mean": float(df["macro_f1"].mean()),
        "macro_f1_worst": float(df["macro_f1"].min()),
        "production_class_auc_mean": float(np.nanmean(aucs)),
        "production_class_auc_worst": float(np.nanmin(aucs)),
        "aggregate_confusion_matrix": aggregate_cm.tolist() if aggregate_cm is not None else None,
    }

    gates: List[dict] = []

    # Gate: worst-fold ROC-AUC ≥ threshold on production class.
    worst_auc = summary["production_class_auc_worst"]
    gates.append(
        GateResult(
            name="walk_forward_worst_auc",
            status="pass" if worst_auc >= worst_fold_auc_threshold else "fail",
            value=float(worst_auc),
            threshold=float(worst_fold_auc_threshold),
            detail=f"worst-fold ROC-AUC for class {class_names[production_class_idx]!r}",
            blocking=True,
        ).to_dict()
    )

    # Gate: mean weighted_f1 within ±tol of in-sample baseline (if provided).
    if baseline_f1 is not None:
        mean_f1 = summary["weighted_f1_mean"]
        drift = abs(mean_f1 - baseline_f1) / max(baseline_f1, 1e-9)
        gates.append(
            GateResult(
                name="walk_forward_in_sample_drift",
                status="pass" if drift <= in_sample_drift_tol else "fail",
                value=float(drift),
                threshold=float(in_sample_drift_tol),
                detail=(
                    f"mean weighted_f1={mean_f1:.4f} vs in-sample baseline "
                    f"={baseline_f1:.4f} (drift={drift:.2%})"
                ),
                blocking=True,
            ).to_dict()
        )

    return {
        "per_fold": rows,
        "summary": summary,
        "gates": gates,
    }
