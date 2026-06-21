"""Synthetic-classifier sanity tests for section B."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.evaluation.model_card.data_loader import EvalSplit
from src.evaluation.model_card.sections.section_b_discrimination import run_section_b


def _make_split(y: np.ndarray, p: np.ndarray) -> EvalSplit:
    n = len(y)
    df = pd.DataFrame({
        "ticker": [f"T{i:04d}" for i in range(n)],
        "date": pd.date_range("2024-01-01", periods=n, freq="D"),
        "mfe_pct": np.where(y == 1, 50.0, 5.0),
        "trend_ok": True,
    })
    return EvalSplit(
        df=df,
        feature_cols=[],
        label_binary=pd.Series(y, index=df.index),
        label_mfe=df["mfe_pct"],
        label_4class=pd.Series(np.zeros(n, dtype=int), index=df.index),
        pred_proba=pd.Series(p, index=df.index),
        meta={"n_rows": n, "prevalence": float(y.mean()), "model_id": "synthetic"},
        db_path=Path("."),
        model_path=Path("."),
    )


def test_perfect_classifier_scores_strong():
    y = np.array([0] * 100 + [1] * 30)
    p = y.astype(float)
    split = _make_split(y, p)
    section = run_section_b(split)
    auc = next(m.value for m in section.metrics if m.name == "roc_auc")
    assert auc == pytest.approx(1.0)
    # All three gates should pass
    assert all(g.status == "pass" for g in section.gates), section.gates


def test_random_classifier_fails_blocking_gates():
    rng = np.random.default_rng(0)
    y = (rng.uniform(size=500) < 0.15).astype(int)
    p = rng.uniform(size=500)
    split = _make_split(y, p)
    section = run_section_b(split)
    # AUC should be near 0.5; both B1 and B2 should fail
    failing_blockers = [g for g in section.gates if g.blocking and g.status == "fail"]
    assert failing_blockers, "random classifier must trip at least one blocking gate"


def test_inverted_classifier_has_negative_signal():
    """An inverted-perfect classifier has AUC near 0 — gates must fail."""
    y = np.array([0] * 100 + [1] * 30)
    p = 1.0 - y.astype(float)
    split = _make_split(y, p)
    section = run_section_b(split)
    auc = next(m.value for m in section.metrics if m.name == "roc_auc")
    assert auc == pytest.approx(0.0)
    assert any(g.name == "B1_auc" and g.status == "fail" for g in section.gates)
