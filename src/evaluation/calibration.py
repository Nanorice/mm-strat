"""Expected Calibration Error (ECE) and per-class calibration audit.

Brier score (already in ClassificationEvaluator) tells us "are probabilities
sharp?" ECE tells us "when the model says 70%, does it happen 70% of the
time?" — that's the property we actually rely on for ranking and position
sizing.

The audit returns ECE for every class and records a *blocking* GateResult for
the production class only. Non-production classes are reported, not gated, so
we don't block promotion on an unused class's miscalibration.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from .gate import GateResult


def expected_calibration_error(
    y_true_binary: np.ndarray,
    y_prob: np.ndarray,
    n_bins: int = 10,
) -> Dict[str, Any]:
    """Compute one-vs-rest ECE for a single class.

    Bins are equal-width over [0, 1]. We use equal-width rather than
    equal-frequency because that's what the canonical Guo et al. (2017) paper
    uses and it produces stable, comparable bin edges across models.
    """
    y_true_binary = np.asarray(y_true_binary).astype(int)
    y_prob = np.asarray(y_prob, dtype=float)

    if y_true_binary.shape != y_prob.shape:
        raise ValueError(
            f"shape mismatch: y_true_binary={y_true_binary.shape} y_prob={y_prob.shape}"
        )

    n = len(y_prob)
    if n == 0:
        return {
            "ece": 0.0,
            "max_calibration_error": 0.0,
            "n_bins": n_bins,
            "bin_data": [],
            "n": 0,
        }

    # np.linspace gives n_bins+1 edges
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_idx = np.clip(np.digitize(y_prob, edges, right=True) - 1, 0, n_bins - 1)

    ece = 0.0
    max_ce = 0.0
    bin_data: List[Dict[str, Any]] = []
    for b in range(n_bins):
        mask = bin_idx == b
        n_b = int(mask.sum())
        if n_b == 0:
            bin_data.append(
                {"lo": float(edges[b]), "hi": float(edges[b + 1]), "n": 0,
                 "mean_pred": None, "mean_obs": None, "gap": None}
            )
            continue
        mean_pred = float(y_prob[mask].mean())
        mean_obs = float(y_true_binary[mask].mean())
        gap = abs(mean_pred - mean_obs)
        weight = n_b / n
        ece += weight * gap
        max_ce = max(max_ce, gap)
        bin_data.append(
            {"lo": float(edges[b]), "hi": float(edges[b + 1]), "n": n_b,
             "mean_pred": mean_pred, "mean_obs": mean_obs, "gap": float(gap)}
        )

    return {
        "ece": float(ece),
        "max_calibration_error": float(max_ce),
        "n_bins": n_bins,
        "bin_data": bin_data,
        "n": int(n),
    }


def calibration_audit(
    y_true: np.ndarray,
    y_pred_proba: np.ndarray,
    class_names: List[str],
    production_class_idx: int,
    ece_threshold: float = 0.05,
    n_bins: int = 10,
) -> Dict[str, Any]:
    """Run ECE per class; record a blocking GateResult on the production class."""
    y_true = np.asarray(y_true).astype(int)
    y_pred_proba = np.asarray(y_pred_proba, dtype=float)

    n_classes = y_pred_proba.shape[1]
    if production_class_idx < 0 or production_class_idx >= n_classes:
        raise ValueError(
            f"production_class_idx={production_class_idx} out of range "
            f"for {n_classes} classes"
        )
    if len(class_names) != n_classes:
        raise ValueError(
            f"class_names has {len(class_names)} entries but y_pred_proba "
            f"has {n_classes} columns"
        )

    ece_per_class: Dict[str, Dict[str, Any]] = {}
    for i, name in enumerate(class_names):
        binary = (y_true == i).astype(int)
        ece_per_class[name] = expected_calibration_error(
            y_true_binary=binary,
            y_prob=y_pred_proba[:, i],
            n_bins=n_bins,
        )

    prod_name = class_names[production_class_idx]
    prod_ece = ece_per_class[prod_name]["ece"]
    passed = prod_ece <= ece_threshold

    gate = GateResult(
        name="calibration_ece",
        status="pass" if passed else "fail",
        value=float(prod_ece),
        threshold=float(ece_threshold),
        detail=(
            f"production_class='{prod_name}' ece={prod_ece:.4f} "
            f"threshold={ece_threshold:.4f}"
        ),
        blocking=True,
    )

    return {
        "ece_per_class": ece_per_class,
        "production_class": prod_name,
        "production_class_idx": int(production_class_idx),
        "production_class_ece": float(prod_ece),
        "ece_threshold": float(ece_threshold),
        "gate": gate.to_dict(),
    }
