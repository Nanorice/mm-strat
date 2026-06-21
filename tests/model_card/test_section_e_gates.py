"""Section E — threshold sweep on Mode A pool."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.evaluation.model_card.data_loader import EvalSplit
from src.evaluation.model_card.sections.section_e_gates import (
    DEPLOYMENT_T_STAR,
    THRESHOLDS,
    run_section_e,
)


def _make_split_and_pool(pred: np.ndarray, mfe: np.ndarray,
                        dates: pd.DatetimeIndex | None = None) -> tuple[EvalSplit, pd.DataFrame]:
    n = len(pred)
    if dates is None:
        # spread across ~3 years so trades/month is sane and stability has folds
        dates = pd.date_range("2022-01-01", periods=n, freq="2D")
    label_binary = (mfe > 30.0).astype(int)
    df = pd.DataFrame({
        "ticker": [f"T{i}" for i in range(n)],
        "date": dates,
        "mfe_pct": mfe,
        "trend_ok": True,
    })
    split = EvalSplit(
        df=df,
        feature_cols=[],
        label_binary=pd.Series(label_binary, index=df.index),
        label_mfe=pd.Series(mfe, index=df.index),
        label_4class=pd.Series(np.zeros(n, dtype=int), index=df.index),
        pred_proba=pd.Series(pred, index=df.index),
        meta={"n_rows": n, "prevalence": float(label_binary.mean()),
              "model_id": "synthetic", "date_min": str(df["date"].min()),
              "date_max": str(df["date"].max())},
        db_path=Path("."), model_path=Path("."),
    )
    pool = pd.DataFrame({
        "ticker": df["ticker"].values,
        "date": df["date"].values,
        "pred_proba": pred,
        "label_binary": label_binary,
        "label_mfe": mfe,
    })
    return split, pool


def test_threshold_sweep_returns_one_row_per_threshold():
    rng = np.random.default_rng(0)
    n = 1000
    pred = rng.uniform(size=n)
    mfe = rng.exponential(scale=15, size=n)
    split, pool = _make_split_and_pool(pred, mfe)
    section = run_section_e(split, pool)
    sweep = section.tables["threshold_sweep"]
    assert len(sweep) == len(THRESHOLDS)
    assert [r["threshold"] for r in sweep] == list(THRESHOLDS)


def test_perfect_classifier_passes_precision_gate():
    """If pred = label_binary perfectly, precision at any T > 0 = 1.0."""
    rng = np.random.default_rng(1)
    n = 1000
    mfe = rng.exponential(scale=20, size=n)
    label_binary = (mfe > 30.0).astype(int)
    pred = label_binary.astype(float) * 0.95 + 0.025  # avoids exact 0/1
    split, pool = _make_split_and_pool(pred, mfe)
    section = run_section_e(split, pool)
    # E1 (precision lift > 1.5×) must pass — precision at T*=0.6 captures only label=1 rows.
    e1 = next(g for g in section.gates if g.name == "E1_precision_lift")
    assert e1.status == "pass", e1.detail


def test_random_classifier_precision_near_prevalence():
    rng = np.random.default_rng(2)
    n = 2000
    pred = rng.uniform(size=n)
    mfe = rng.exponential(scale=15, size=n)
    split, pool = _make_split_and_pool(pred, mfe)
    section = run_section_e(split, pool)
    sweep = section.tables["threshold_sweep"]
    prevalence = float(split.prevalence)
    # Pool average of precision_lift across T should be ~1.0.
    lifts = [r["precision_lift_over_prevalence"] for r in sweep
             if r["precision_lift_over_prevalence"] == r["precision_lift_over_prevalence"]]
    assert lifts, "expected at least one non-NaN precision lift"
    assert all(0.5 < l < 2.0 for l in lifts), lifts


def test_empty_pool_emits_blocking_gate():
    split, pool = _make_split_and_pool(np.array([0.5]), np.array([10.0]))
    section = run_section_e(split, pool.iloc[0:0])
    assert any(g.blocking and g.status == "fail" for g in section.gates)


def test_t_star_metric_present():
    rng = np.random.default_rng(3)
    n = 500
    pred = rng.uniform(size=n)
    mfe = rng.exponential(scale=15, size=n)
    split, pool = _make_split_and_pool(pred, mfe)
    section = run_section_e(split, pool)
    names = {m.name for m in section.metrics}
    assert f"precision_at_t={DEPLOYMENT_T_STAR}" in names
    assert f"coverage_pct_at_t={DEPLOYMENT_T_STAR}" in names
    assert f"trades_per_month_at_t={DEPLOYMENT_T_STAR}" in names
