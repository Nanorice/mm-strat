"""Probability-threshold optimization for binary signals.

Used by the M01_v2 binary work to pick the deployment threshold that
*guarantees* a precision floor (e.g., 60%). Three modes:

  precision_min   minimum threshold whose precision ≥ `target`
  f1_max          threshold that maximizes F1
  youden          threshold that maximizes (TPR - FPR), aka Youden's J
"""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

import numpy as np
from sklearn.metrics import precision_recall_curve, roc_curve

Mode = Literal["precision_min", "f1_max", "youden"]


def find_optimal_threshold(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    mode: Mode,
    target: Optional[float] = None,
) -> Dict[str, Any]:
    """Find the deployment threshold for a binary signal."""
    y_true = np.asarray(y_true).astype(int)
    y_prob = np.asarray(y_prob, dtype=float)

    if y_true.shape != y_prob.shape:
        raise ValueError("y_true and y_prob must have the same shape")
    if mode not in {"precision_min", "f1_max", "youden"}:
        raise ValueError(f"unknown mode: {mode!r}")
    if mode == "precision_min" and target is None:
        raise ValueError("mode='precision_min' requires `target`")

    if mode == "precision_min":
        return _precision_min(y_true, y_prob, target)
    if mode == "f1_max":
        return _f1_max(y_true, y_prob)
    return _youden(y_true, y_prob)


def _precision_recall_at(y_true: np.ndarray, y_prob: np.ndarray, thr: float) -> tuple:
    signal = y_prob >= thr
    n_signals = int(signal.sum())
    tp = int(((y_true == 1) & signal).sum())
    precision = tp / n_signals if n_signals > 0 else 0.0
    recall = tp / int((y_true == 1).sum()) if (y_true == 1).any() else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return precision, recall, f1, n_signals


def _precision_min(y_true: np.ndarray, y_prob: np.ndarray, target: float) -> Dict[str, Any]:
    precision, recall, thresholds = precision_recall_curve(y_true, y_prob)
    # precision_recall_curve appends a trailing precision=1.0, recall=0.0 with no threshold.
    valid = np.where(precision[:-1] >= target)[0]
    if len(valid) == 0:
        return {
            "threshold": float("nan"),
            "precision_at_threshold": float("nan"),
            "recall_at_threshold": float("nan"),
            "f1_at_threshold": float("nan"),
            "n_signals": 0,
            "mode": "precision_min",
            "target": float(target),
            "achievable": False,
        }
    # Choose the *leftmost* (lowest) threshold that meets the precision floor.
    # That maximizes recall subject to the precision constraint.
    idx = int(valid.min())
    thr = float(thresholds[idx])
    p, r, f1, n_signals = _precision_recall_at(y_true, y_prob, thr)
    return {
        "threshold": thr,
        "precision_at_threshold": p,
        "recall_at_threshold": r,
        "f1_at_threshold": f1,
        "n_signals": n_signals,
        "mode": "precision_min",
        "target": float(target),
        "achievable": True,
    }


def _f1_max(y_true: np.ndarray, y_prob: np.ndarray) -> Dict[str, Any]:
    precision, recall, thresholds = precision_recall_curve(y_true, y_prob)
    p = precision[:-1]
    r = recall[:-1]
    with np.errstate(invalid="ignore", divide="ignore"):
        f1 = 2 * p * r / np.where((p + r) > 0, p + r, 1)
    if len(thresholds) == 0:
        return {
            "threshold": float("nan"),
            "precision_at_threshold": float("nan"),
            "recall_at_threshold": float("nan"),
            "f1_at_threshold": float("nan"),
            "n_signals": 0,
            "mode": "f1_max",
            "achievable": False,
        }
    idx = int(np.nanargmax(f1))
    thr = float(thresholds[idx])
    p_at, r_at, f1_at, n_signals = _precision_recall_at(y_true, y_prob, thr)
    return {
        "threshold": thr,
        "precision_at_threshold": p_at,
        "recall_at_threshold": r_at,
        "f1_at_threshold": f1_at,
        "n_signals": n_signals,
        "mode": "f1_max",
        "achievable": True,
    }


def _youden(y_true: np.ndarray, y_prob: np.ndarray) -> Dict[str, Any]:
    fpr, tpr, thresholds = roc_curve(y_true, y_prob)
    j = tpr - fpr
    # roc_curve prepends an inf threshold; skip it.
    valid = ~np.isinf(thresholds)
    if not valid.any():
        return {
            "threshold": float("nan"),
            "precision_at_threshold": float("nan"),
            "recall_at_threshold": float("nan"),
            "f1_at_threshold": float("nan"),
            "n_signals": 0,
            "mode": "youden",
            "achievable": False,
        }
    j_valid = np.where(valid, j, -np.inf)
    idx = int(np.argmax(j_valid))
    thr = float(thresholds[idx])
    p, r, f1, n_signals = _precision_recall_at(y_true, y_prob, thr)
    return {
        "threshold": thr,
        "precision_at_threshold": p,
        "recall_at_threshold": r,
        "f1_at_threshold": f1,
        "n_signals": n_signals,
        "mode": "youden",
        "tpr": float(tpr[idx]),
        "fpr": float(fpr[idx]),
        "achievable": True,
    }
