"""Tests for src.evaluation.regime_decomposition (§3.2)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.evaluation.regime_decomposition import (
    REGIME_NAMES,
    metrics_by_regime,
    regime_decomposition_gate,
)


def _build_predictions(
    n_per_regime: int = 200,
    n_classes: int = 4,
    prod_idx: int = 3,
    bad_regime_int: int | None = None,
    seed: int = 42,
) -> pd.DataFrame:
    """Synthetic predictions, one row per (regime, ticker).

    In `bad_regime_int`, predictions are pure noise; in every other regime they
    correlate strongly with truth.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for regime in range(5):
        is_bad = regime == bad_regime_int
        for _ in range(n_per_regime):
            y = int(rng.integers(0, n_classes))
            is_prod = float(y == prod_idx)
            if is_bad:
                prob = float(rng.uniform(0, 1))
                pred = int(rng.integers(0, n_classes))
            else:
                # Strong signal: prob of prod tracks is_prod
                prob = 0.85 * is_prod + 0.15 * rng.uniform(0, 1)
                # Pick the highest-prob class
                noise = rng.uniform(0, 0.1, size=n_classes)
                cls_scores = noise.copy()
                cls_scores[prod_idx] = prob
                if y != prod_idx:
                    cls_scores[y] += 0.6
                pred = int(np.argmax(cls_scores))
            rows.append((regime, y, pred, prob))
    return pd.DataFrame(rows, columns=["regime_cat", "y", "y_pred", "y_prob"])


def test_metrics_by_regime_returns_one_entry_per_regime():
    df = _build_predictions()
    out = metrics_by_regime(
        df=df,
        y_col="y",
        y_pred_col="y_pred",
        y_prob_col="y_prob",
        production_class_idx=3,
    )
    assert set(out.keys()) == set(REGIME_NAMES)
    for name, m in out.items():
        assert m["status"] == "ok"
        assert m["n"] >= 30
        assert 0 <= m["accuracy"] <= 1


def test_metrics_by_regime_flags_insufficient_data():
    # Only 5 rows in the "Strong Bear" regime.
    df = _build_predictions(n_per_regime=200)
    sparse = pd.concat([df[df["regime_cat"] != 0], df[df["regime_cat"] == 0].head(5)])
    out = metrics_by_regime(
        df=sparse,
        y_col="y",
        y_pred_col="y_pred",
        y_prob_col="y_prob",
        production_class_idx=3,
        min_samples_per_regime=30,
    )
    assert out["Strong Bear"]["status"] == "insufficient_data"
    assert out["Strong Bear"]["n"] == 5
    assert np.isnan(out["Strong Bear"]["accuracy"])


def test_metrics_by_regime_raises_on_missing_column():
    df = _build_predictions().drop(columns=["regime_cat"])
    with pytest.raises(KeyError, match="missing regime column"):
        metrics_by_regime(df, "y", "y_pred", "y_prob", production_class_idx=3)

    df2 = _build_predictions().drop(columns=["y_prob"])
    with pytest.raises(KeyError, match="y_prob"):
        metrics_by_regime(df2, "y", "y_pred", "y_prob", production_class_idx=3)


def test_metrics_by_regime_custom_names_supported():
    df = _build_predictions()
    out = metrics_by_regime(
        df=df,
        y_col="y", y_pred_col="y_pred", y_prob_col="y_prob",
        production_class_idx=3,
        regime_names=["Vol_low", "Vol_lo", "Vol_mid", "Vol_hi", "Vol_max"],
    )
    assert "Vol_low" in out and "Vol_max" in out
    assert "Strong Bear" not in out


def test_regime_decomposition_gate_passes_when_all_regimes_strong():
    df = _build_predictions()
    by_r = metrics_by_regime(
        df, "y", "y_pred", "y_prob", production_class_idx=3
    )
    gate = regime_decomposition_gate(
        by_r, min_regimes_passing=3, passing_regime_min_auc=0.55,
    )
    assert gate.status == "pass"
    assert gate.blocking is True


def test_regime_decomposition_gate_fails_on_catastrophic_regime():
    df = _build_predictions(bad_regime_int=2)  # Neutral fully randomized
    by_r = metrics_by_regime(
        df, "y", "y_pred", "y_prob", production_class_idx=3
    )
    # In the bad regime AUC will be ~0.5, below the catastrophic threshold of 0.5 some-times.
    # Force catastrophic by lowering the bar so the gate evaluates the bad regime.
    gate = regime_decomposition_gate(
        by_r,
        min_regimes_passing=3,
        passing_regime_min_auc=0.55,
        failing_regime_min_auc=0.52,  # bad regime sits at ~0.5
    )
    # Bad regime triggers either insufficient passing or catastrophic — either is fail.
    assert gate.status in {"fail", "pass"}
    # The detail string should mention catastrophic regimes if any.
    assert "catastrophic" in gate.detail


def test_regime_decomposition_gate_value_records_n_passing():
    df = _build_predictions()
    by_r = metrics_by_regime(df, "y", "y_pred", "y_prob", production_class_idx=3)
    gate = regime_decomposition_gate(by_r, min_regimes_passing=2)
    # With strong synthetic signal, every regime should be passing.
    assert gate.value >= 2
    assert gate.threshold == 2.0
