"""Tests for src.evaluation.walk_forward (§2.3)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xgboost as xgb

from src.evaluation.walk_forward import (
    FoldResult,
    FoldSpec,
    aggregate_walk_forward,
    anchored_walk_forward,
    run_walk_forward,
)


def _build_panel(seed: int = 0) -> pd.DataFrame:
    """5 years × 100 tickers × ~252 trading days. Signal in `x` predicts `y`."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2019-01-02", "2023-12-29")
    tickers = [f"T{i:03d}" for i in range(20)]
    rows = []
    for d in dates:
        for tk in tickers:
            x1 = rng.normal()
            x2 = rng.normal()
            # 4-class label: bucket x1+x2
            score = x1 + 0.5 * x2 + rng.normal(0, 0.2)
            y = int(np.clip(np.searchsorted([-0.7, 0, 0.7], score), 0, 3))
            rows.append((d, tk, x1, x2, y))
    return pd.DataFrame(rows, columns=["date", "ticker", "x1", "x2", "y"])


def test_anchored_walk_forward_disjoint_folds():
    df = _build_panel()
    specs = list(
        anchored_walk_forward(
            df,
            date_col="date",
            train_start=date(2019, 1, 2),
            test_start=date(2022, 1, 1),
            test_end=date(2023, 12, 29),
            step="1Y",
            min_train_years=2,
        )
    )
    assert len(specs) >= 2
    for s in specs:
        assert s.train_start < s.train_end < s.test_start < s.test_end
    for prev, nxt in zip(specs, specs[1:]):
        assert prev.test_end <= nxt.test_start, "folds overlap"
        assert nxt.train_start == prev.train_start, "anchored: train_start fixed"


def test_anchored_skips_when_under_min_train_years():
    df = _build_panel()
    specs = list(
        anchored_walk_forward(
            df,
            date_col="date",
            train_start=date(2019, 1, 2),
            test_start=date(2019, 6, 1),
            test_end=date(2023, 12, 29),
            step="1Y",
            min_train_years=5,
        )
    )
    # min_train_years=5 means no fold gets enough training data
    assert specs == []


def test_anchored_validates_inputs():
    df = _build_panel().head(10)
    with pytest.raises(ValueError, match="test_start must be after"):
        list(anchored_walk_forward(df, "date", date(2022, 1, 1), date(2019, 1, 1), date(2023, 1, 1)))
    with pytest.raises(ValueError, match="test_end must be after"):
        list(anchored_walk_forward(df, "date", date(2019, 1, 1), date(2022, 1, 1), date(2021, 1, 1)))


def test_run_walk_forward_returns_one_result_per_fold(tmp_path: Path):
    df = _build_panel()
    specs = list(
        anchored_walk_forward(
            df,
            date_col="date",
            train_start=date(2019, 1, 2),
            test_start=date(2022, 1, 1),
            test_end=date(2023, 12, 29),
            step="1Y",
            min_train_years=2,
        )
    )

    def train_fn(X: pd.DataFrame, y: pd.Series) -> xgb.Booster:
        dtrain = xgb.DMatrix(X.values, label=y.values)
        params = {
            "objective": "multi:softprob",
            "num_class": 4,
            "max_depth": 3,
            "eta": 0.2,
            "verbosity": 0,
        }
        return xgb.train(params, dtrain, num_boost_round=20)

    results = run_walk_forward(
        df=df,
        date_col="date",
        feature_cols=["x1", "x2"],
        target_col="y",
        fold_specs=specs,
        train_fn=train_fn,
        output_dir=tmp_path,
    )
    assert len(results) == len(specs)
    for r in results:
        assert r.y_pred_proba.shape[1] == 4
        assert r.y_pred_proba.shape[0] == len(r.y_test)
        assert r.metrics["accuracy"] > 0
        assert r.model_path is not None
        assert r.model_path.exists()


def _build_fold(fold_idx: int, prod_class_signal: float, seed: int) -> FoldResult:
    """Make a fake fold where class-3 probs correlate with truth at `prod_class_signal`.

    signal=1.0  → near-perfect separation (AUC ~1.0)
    signal=0.0  → random (AUC ~0.5)
    """
    rng = np.random.default_rng(seed)
    spec = FoldSpec(
        fold_idx=fold_idx,
        train_start=date(2019, 1, 1),
        train_end=date(2019 + fold_idx, 1, 1),
        test_start=date(2019 + fold_idx, 1, 2),
        test_end=date(2020 + fold_idx, 1, 1),
    )
    n = 800
    y_test = pd.Series(rng.integers(0, 4, n))
    is_prod = (y_test == 3).values.astype(float)

    # class-3 score: signal * is_prod + (1 - signal) * uniform noise.
    score3 = prod_class_signal * is_prod + (1 - prod_class_signal) * rng.uniform(0, 1, n)
    # Other classes get random non-class-3 mass.
    other = rng.uniform(0, 1, (n, 3))
    # Normalize.
    raw = np.column_stack([other, score3.reshape(-1, 1)])
    proba = raw / raw.sum(axis=1, keepdims=True)

    y_pred = np.argmax(proba, axis=1)
    from sklearn.metrics import accuracy_score, f1_score
    metrics = {
        "n_train": 1000,
        "n_test": n,
        "accuracy": float(accuracy_score(y_test, y_pred)),
        "weighted_f1": float(f1_score(y_test, y_pred, average="weighted", zero_division=0)),
        "macro_f1": float(f1_score(y_test, y_pred, average="macro", zero_division=0)),
    }
    return FoldResult(
        spec=spec,
        model_path=None,
        X_test=pd.DataFrame({"dummy": np.zeros(n)}),
        y_test=y_test,
        y_pred_proba=proba,
        metrics=metrics,
        train_seconds=0.1,
    )


def test_aggregate_walk_forward_gate_fails_on_weak_fold():
    # Two strong folds + one with no signal at all.
    folds = [
        _build_fold(0, prod_class_signal=0.95, seed=10),
        _build_fold(1, prod_class_signal=0.95, seed=11),
        _build_fold(2, prod_class_signal=0.0, seed=12),
    ]
    agg = aggregate_walk_forward(
        folds,
        class_names=["Noise", "Moderate", "Strong", "HomeRun"],
        production_class_idx=3,
        worst_fold_auc_threshold=0.65,
    )
    assert agg["summary"]["n_folds"] == 3
    worst_auc_gate = next(g for g in agg["gates"] if g["name"] == "walk_forward_worst_auc")
    assert worst_auc_gate["status"] == "fail"
    assert worst_auc_gate["blocking"] is True


def test_aggregate_walk_forward_gate_passes_on_strong_folds():
    folds = [_build_fold(i, prod_class_signal=0.95, seed=20 + i) for i in range(3)]
    agg = aggregate_walk_forward(
        folds,
        class_names=["Noise", "Moderate", "Strong", "HomeRun"],
        production_class_idx=3,
        worst_fold_auc_threshold=0.65,
    )
    worst_auc_gate = next(g for g in agg["gates"] if g["name"] == "walk_forward_worst_auc")
    assert worst_auc_gate["status"] == "pass"


def test_aggregate_handles_empty_fold_list():
    agg = aggregate_walk_forward([], class_names=["A", "B"], production_class_idx=1)
    assert agg["per_fold"] == []
    assert agg["summary"] == {}
