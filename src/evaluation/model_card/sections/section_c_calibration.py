"""Section C — calibration (probability trustworthiness).

Wraps src/evaluation/calibration.expected_calibration_error and adds:
  - per-threshold-bin calibration (does P in [T, T+0.1] match observed freq?)
  - sharpness (variance of pred_proba)
  - reliability-curve table for the report
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from src.evaluation.calibration import expected_calibration_error

from ..data_loader import EvalSplit
from ..rubric import GateEntry, MetricEntry, SectionResult, rubric_score

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLDS = (0.3, 0.4, 0.5, 0.6, 0.7)


def _per_threshold_bin_calibration(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS,
    tolerance: float = 0.05,
) -> list[dict]:
    """For each T, check |observed - predicted_mean| inside [T, T+0.1]."""
    rows = []
    for t in thresholds:
        mask = (y_prob >= t) & (y_prob < t + 0.1)
        n = int(mask.sum())
        if n == 0:
            rows.append({
                "threshold": float(t),
                "bin_lo": float(t),
                "bin_hi": float(t + 0.1),
                "n": 0,
                "observed_freq": None,
                "predicted_mean": None,
                "gap": None,
                "within_tolerance": None,
            })
            continue
        observed = float(y_true[mask].mean())
        predicted = float(y_prob[mask].mean())
        gap = abs(observed - predicted)
        rows.append({
            "threshold": float(t),
            "bin_lo": float(t),
            "bin_hi": float(t + 0.1),
            "n": n,
            "observed_freq": observed,
            "predicted_mean": predicted,
            "gap": float(gap),
            "within_tolerance": bool(gap <= tolerance),
        })
    return rows


def run_section_c(split: EvalSplit, tolerance: float = 0.05) -> SectionResult:
    y = split.label_binary.values.astype(int)
    p = np.clip(split.pred_proba.values.astype(float), 0.0, 1.0)

    ece_result = expected_calibration_error(y_true_binary=y, y_prob=p, n_bins=10)
    ece = float(ece_result["ece"])
    max_ce = float(ece_result["max_calibration_error"])
    sharpness = float(np.var(p))

    threshold_bins = _per_threshold_bin_calibration(y, p, DEFAULT_THRESHOLDS, tolerance)
    bins_with_data = [b for b in threshold_bins if b["n"] > 0]
    failing_bins = [b for b in bins_with_data if not b["within_tolerance"]]

    section = SectionResult(
        name="C",
        title="Calibration (probability trustworthiness)",
        scored=True,
    )

    section.metrics.extend([
        MetricEntry("ece", ece, f"expected calibration error (n_bins=10)"),
        MetricEntry("max_calibration_error", max_ce, "worst bin gap"),
        MetricEntry("sharpness_var", sharpness,
                    "variance of pred_proba (higher = more commitment)"),
        MetricEntry(
            "threshold_bins_within_tolerance",
            float(len(bins_with_data) - len(failing_bins)),
            f"of {len(bins_with_data)} non-empty bins (±{tolerance})",
        ),
    ])

    # ECE rubric: lower is better, thresholds [strong, good, marginal] when
    # mapping "lower is better" — rubric_score expects ascending order with
    # higher_is_better=False.
    section.rubric_scores["ece"] = rubric_score(
        ece, [0.02, 0.05, 0.10], higher_is_better=False
    )

    section.gates.append(GateEntry(
        name="C1_ece",
        status="pass" if ece < 0.05 else "fail",
        value=ece, threshold=0.05,
        detail=f"ECE={ece:.4f} (gate: < 0.05)",
        blocking=True,
    ))
    section.gates.append(GateEntry(
        name="C2_threshold_bin_calibration",
        status="pass" if not failing_bins else "fail",
        value=float(len(failing_bins)),
        threshold=0.0,
        detail=(
            f"{len(failing_bins)} of {len(bins_with_data)} non-empty bins exceed "
            f"±{tolerance}"
        ),
        blocking=True,
    ))
    section.gates.append(GateEntry(
        name="C3_sharpness",
        status="pass" if sharpness > 0.005 else "warn",
        value=sharpness, threshold=0.005,
        detail=(
            f"sharpness={sharpness:.5f} "
            f"(warn if < 0.005 ⇒ model barely commits)"
        ),
        blocking=False,
    ))

    section.tables["reliability_curve"] = [
        {
            "bin_lo": b["lo"], "bin_hi": b["hi"], "n": b["n"],
            "mean_pred": b["mean_pred"], "mean_obs": b["mean_obs"],
            "gap": b["gap"],
        }
        for b in ece_result["bin_data"]
    ]
    section.tables["threshold_bin_calibration"] = threshold_bins
    section.detail = (
        f"ECE={ece:.4f} (max-bin gap={max_ce:.4f}), sharpness={sharpness:.5f}. "
        f"Threshold-bins: {len(failing_bins)}/{len(bins_with_data)} fail ±{tolerance}."
    )
    return section
