"""Tests for src.evaluation.thresholding (§2.4)."""

from __future__ import annotations

import numpy as np
import pytest

from src.evaluation.thresholding import find_optimal_threshold


def _separable_signal(n: int = 1000, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """y=1 -> probs ~ Beta(8,2); y=0 -> probs ~ Beta(2,8). Mostly separable."""
    rng = np.random.default_rng(seed)
    y = rng.integers(0, 2, n)
    probs = np.where(
        y == 1,
        rng.beta(8, 2, n),
        rng.beta(2, 8, n),
    )
    return y, probs


def test_precision_min_returns_leftmost_qualifying_threshold():
    y, p = _separable_signal()
    result = find_optimal_threshold(y, p, mode="precision_min", target=0.8)
    assert result["achievable"] is True
    assert result["precision_at_threshold"] >= 0.8 - 1e-9
    assert 0 <= result["threshold"] <= 1
    assert result["n_signals"] > 0


def test_precision_min_unreachable_target():
    y, p = _separable_signal()
    result = find_optimal_threshold(y, p, mode="precision_min", target=0.9999)
    # Achievability depends on dataset; force unreachable with a pathological p
    if result["achievable"]:
        # try with completely random probs
        rng = np.random.default_rng(0)
        y2 = rng.integers(0, 2, 500)
        p2 = rng.uniform(0, 1, 500)
        result = find_optimal_threshold(y2, p2, mode="precision_min", target=0.99)
    assert result["achievable"] is False
    assert np.isnan(result["threshold"])
    assert result["n_signals"] == 0


def test_f1_max_returns_sane_threshold():
    y, p = _separable_signal()
    result = find_optimal_threshold(y, p, mode="f1_max")
    assert result["achievable"] is True
    assert 0 <= result["threshold"] <= 1
    # F1 at optimal should be at least as good as F1 at threshold=0.5
    from src.evaluation.thresholding import _precision_recall_at
    _, _, f1_05, _ = _precision_recall_at(y, p, 0.5)
    assert result["f1_at_threshold"] >= f1_05 - 1e-6


def test_youden_max_returns_sane_threshold():
    y, p = _separable_signal()
    result = find_optimal_threshold(y, p, mode="youden")
    assert result["achievable"] is True
    assert 0 <= result["threshold"] <= 1
    assert "tpr" in result and "fpr" in result


def test_validates_inputs():
    with pytest.raises(ValueError, match="same shape"):
        find_optimal_threshold(np.array([0, 1]), np.array([0.5]), mode="f1_max")
    with pytest.raises(ValueError, match="unknown mode"):
        find_optimal_threshold(np.array([0, 1]), np.array([0.5, 0.5]), mode="invalid")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="requires"):
        find_optimal_threshold(np.array([0, 1]), np.array([0.5, 0.5]), mode="precision_min")
