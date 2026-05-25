"""Tests for src.evaluation.calibrator."""

from __future__ import annotations

import numpy as np
import pytest

from src.evaluation.calibrator import IsotonicCalibrator, calibrator_path_for
from src.evaluation.calibration import expected_calibration_error


def _miscalibrated_pair(n: int = 5000, seed: int = 0):
    """Build a (y_true, y_prob_raw) pair where probabilities are systematically
    biased upward — simulates the class-weighted XGBoost case where the model
    over-confidently flags positives because training was rebalanced.
    """
    rng = np.random.default_rng(seed)
    # True base rate ~15%
    y_true = (rng.uniform(size=n) < 0.15).astype(int)
    # Latent score correlates with y_true but is biased: positives get [0.4, 0.9],
    # negatives get [0.2, 0.7]. Mean(p) ≈ 0.5 vs base rate 0.15 → big ECE.
    y_prob_raw = np.where(
        y_true == 1,
        rng.uniform(0.4, 0.9, size=n),
        rng.uniform(0.2, 0.7, size=n),
    )
    return y_true, y_prob_raw


def test_fit_transform_reduces_ece():
    y, p_raw = _miscalibrated_pair(n=5000)
    pre = expected_calibration_error(y, p_raw, n_bins=10)["ece"]
    cal = IsotonicCalibrator().fit(y, p_raw, model_version_id="test_v1")
    p_cal = cal.transform(p_raw)
    post = expected_calibration_error(y, p_cal, n_bins=10)["ece"]
    assert post < pre, f"calibration should reduce ECE; pre={pre:.3f} post={post:.3f}"
    # And the calibrated mean should be close to the true base rate.
    assert abs(p_cal.mean() - y.mean()) < 0.02


def test_transform_without_fit_raises():
    cal = IsotonicCalibrator()
    with pytest.raises(RuntimeError):
        cal.transform(np.array([0.1, 0.5, 0.9]))


def test_fit_rejects_non_binary_labels():
    cal = IsotonicCalibrator()
    with pytest.raises(ValueError):
        cal.fit(np.array([0, 1, 2] * 20), np.random.uniform(size=60))


def test_fit_rejects_tiny_sample():
    cal = IsotonicCalibrator()
    with pytest.raises(ValueError):
        cal.fit(np.array([0, 1] * 5), np.random.uniform(size=10))


def test_transform_is_monotone_in_raw_input():
    # Higher raw probability must map to higher-or-equal calibrated probability.
    y, p_raw = _miscalibrated_pair(n=3000)
    cal = IsotonicCalibrator().fit(y, p_raw)
    sorted_raw = np.linspace(p_raw.min(), p_raw.max(), 100)
    cal_out = cal.transform(sorted_raw)
    assert np.all(np.diff(cal_out) >= -1e-9), "calibrator must be non-decreasing"


def test_save_load_round_trip(tmp_path):
    y, p_raw = _miscalibrated_pair(n=2000)
    cal = IsotonicCalibrator().fit(y, p_raw, model_version_id="round_trip_test")
    p_cal = cal.transform(p_raw)

    target = calibrator_path_for(tmp_path / "model")
    cal.save(target)
    assert target.exists()
    assert target.with_suffix(".meta.json").exists()

    cal2 = IsotonicCalibrator.load(target)
    p_cal2 = cal2.transform(p_raw)
    np.testing.assert_allclose(p_cal, p_cal2)
    assert cal2.metadata.model_version_id == "round_trip_test"
    assert cal2.metadata.n_fit_samples == 2000


def test_save_unfitted_raises(tmp_path):
    cal = IsotonicCalibrator()
    with pytest.raises(RuntimeError):
        cal.save(tmp_path / "x.joblib")


def test_transform_handles_out_of_range_inputs():
    # If new data comes in below the training min or above the training max,
    # isotonic's `out_of_bounds='clip'` should clamp, not crash.
    y, p_raw = _miscalibrated_pair(n=2000)
    cal = IsotonicCalibrator().fit(y, p_raw)
    edge = np.array([-0.1, 0.0, 1.0, 1.1])
    out = cal.transform(edge)
    assert np.all(np.isfinite(out))
    assert out.min() >= 0.0 and out.max() <= 1.0
