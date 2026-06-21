"""Tests for src.evaluation.calibration (§2.2)."""

from __future__ import annotations

import numpy as np
import pytest

from src.evaluation.calibration import calibration_audit, expected_calibration_error


def _perfectly_calibrated_binary(n: int = 5000, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    probs = rng.uniform(0, 1, n)
    outcomes = (rng.uniform(0, 1, n) < probs).astype(int)
    return outcomes, probs


def test_ece_near_zero_when_perfectly_calibrated():
    y_true, y_prob = _perfectly_calibrated_binary()
    result = expected_calibration_error(y_true, y_prob, n_bins=10)
    assert result["ece"] < 0.03
    assert result["n"] == len(y_true)


def test_ece_grows_when_probs_shifted():
    y_true, y_prob = _perfectly_calibrated_binary()
    shifted = np.clip(y_prob + 0.2, 0, 1)
    result = expected_calibration_error(y_true, shifted, n_bins=10)
    assert result["ece"] > 0.10


def test_ece_handles_empty_input():
    result = expected_calibration_error(np.array([]), np.array([]), n_bins=10)
    assert result["ece"] == 0.0
    assert result["n"] == 0
    assert result["bin_data"] == []


def test_ece_shape_validation():
    with pytest.raises(ValueError, match="shape mismatch"):
        expected_calibration_error(np.array([0, 1]), np.array([0.1]))


def test_calibration_audit_passes_when_well_calibrated():
    rng = np.random.default_rng(1)
    n = 4000
    y_true = rng.integers(0, 4, n)
    # Build well-calibrated probs: one-hot + a bit of smoothing.
    probs = np.full((n, 4), 0.05)
    probs[np.arange(n), y_true] = 0.85
    # add tiny noise
    probs += rng.normal(0, 0.01, probs.shape)
    probs = np.clip(probs, 1e-6, 1)
    probs = probs / probs.sum(axis=1, keepdims=True)

    result = calibration_audit(
        y_true=y_true,
        y_pred_proba=probs,
        class_names=["Noise", "Moderate", "Strong", "HomeRun"],
        production_class_idx=3,
        ece_threshold=0.10,
    )
    assert result["gate"]["status"] == "pass"
    assert result["production_class"] == "HomeRun"
    assert result["production_class_ece"] <= 0.10


def test_calibration_audit_fails_when_shifted():
    rng = np.random.default_rng(2)
    n = 4000
    y_true = rng.integers(0, 4, n)
    # Severely overconfident on class 3 (predict 0.95 regardless of truth).
    probs = np.full((n, 4), 0.05 / 3)
    probs[:, 3] = 0.95
    probs = probs / probs.sum(axis=1, keepdims=True)

    result = calibration_audit(
        y_true=y_true,
        y_pred_proba=probs,
        class_names=["Noise", "Moderate", "Strong", "HomeRun"],
        production_class_idx=3,
        ece_threshold=0.05,
    )
    assert result["gate"]["status"] == "fail"
    assert result["gate"]["blocking"] is True
    assert result["production_class_ece"] > 0.05


def test_calibration_audit_validates_class_count():
    probs = np.array([[0.4, 0.6], [0.7, 0.3]])
    with pytest.raises(ValueError, match="class_names has"):
        calibration_audit(
            y_true=np.array([0, 1]),
            y_pred_proba=probs,
            class_names=["A", "B", "C"],
            production_class_idx=1,
        )


def test_calibration_audit_validates_production_idx():
    probs = np.array([[0.4, 0.6], [0.7, 0.3]])
    with pytest.raises(ValueError, match="out of range"):
        calibration_audit(
            y_true=np.array([0, 1]),
            y_pred_proba=probs,
            class_names=["A", "B"],
            production_class_idx=5,
        )
