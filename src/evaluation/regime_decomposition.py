"""Regime-conditional classification metrics (§3.2).

Decomposes evaluation metrics across the five M03 macro regimes:
  0=Strong Bear, 1=Bear, 2=Neutral, 3=Bull, 4=Strong Bull
(matches `SEPABacktestRunner._load_regime_from_duckdb`).

Promoted to P0 in the plan because S3 (regime routing) cannot be validated
without per-regime metrics.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from .calibration import expected_calibration_error
from .gate import GateResult

logger = logging.getLogger(__name__)

REGIME_NAMES = ["Strong Bear", "Bear", "Neutral", "Bull", "Strong Bull"]


def _safe_accuracy(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if len(y_true) == 0:
        return float("nan")
    return float((y_true == y_pred).mean())


def _safe_weighted_f1(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    from sklearn.metrics import f1_score
    if len(y_true) == 0:
        return float("nan")
    return float(f1_score(y_true, y_pred, average="weighted", zero_division=0))


def _safe_top_k_lift(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    production_class_idx: int,
    k: int = 3,
) -> float:
    """Top-k lift = P(prod | top-k by score) / P(prod), global within this slice."""
    if len(y_true) == 0 or k <= 0:
        return float("nan")
    is_prod = (y_true == production_class_idx).astype(float)
    base = float(is_prod.mean())
    if base == 0:
        return float("nan")
    top_idx = np.argsort(-y_prob)[:k]
    if len(top_idx) == 0:
        return float("nan")
    return float(is_prod[top_idx].mean() / base)


def _safe_roc_auc_production_class(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    production_class_idx: int,
) -> float:
    from sklearn.metrics import roc_auc_score
    if len(y_true) == 0:
        return float("nan")
    binary = (y_true == production_class_idx).astype(int)
    if binary.sum() == 0 or binary.sum() == len(binary):
        return float("nan")
    try:
        return float(roc_auc_score(binary, y_prob))
    except ValueError:
        return float("nan")


def _safe_ece_production_class(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    production_class_idx: int,
    n_bins: int = 10,
) -> float:
    if len(y_true) == 0:
        return float("nan")
    binary = (y_true == production_class_idx).astype(int)
    if binary.sum() == 0:
        return float("nan")
    try:
        return float(expected_calibration_error(binary, y_prob, n_bins=n_bins)["ece"])
    except Exception:
        return float("nan")


def metrics_by_regime(
    df: pd.DataFrame,
    y_col: str,
    y_pred_col: str,
    y_prob_col: str,
    production_class_idx: int,
    regime_col: str = "regime_cat",
    min_samples_per_regime: int = 30,
    regime_names: Optional[List[str]] = None,
    top_k: int = 3,
) -> Dict[str, Dict]:
    """Compute per-regime classification metrics.

    Args:
        df: One row per prediction. Must include:
            - `regime_col`: integer 0..4 (or whatever schema is in use)
            - `y_col`: true class index
            - `y_pred_col`: predicted class index
            - `y_prob_col`: predicted probability of `production_class_idx`
        production_class_idx: class index used for ROC-AUC / top-k lift / ECE
        regime_names: override default REGIME_NAMES (must match regime values)

    Returns:
        {
          regime_name: {
            'n': int, 'accuracy': float, 'weighted_f1': float, 'top_k_lift': float,
            'calibration_ece': float, 'roc_auc_production_class': float,
            'status': 'ok' | 'insufficient_data',
          }
        }
    """
    if regime_names is None:
        regime_names = REGIME_NAMES

    if regime_col not in df.columns:
        raise KeyError(f"missing regime column {regime_col!r}; got {list(df.columns)}")
    for c in (y_col, y_pred_col, y_prob_col):
        if c not in df.columns:
            raise KeyError(f"missing {c!r} in df")

    out: Dict[str, Dict] = {}
    for regime_int, name in enumerate(regime_names):
        slice_df = df.loc[df[regime_col] == regime_int]
        n = int(len(slice_df))
        if n < min_samples_per_regime:
            out[name] = {
                "n": n,
                "status": "insufficient_data",
                "accuracy": float("nan"),
                "weighted_f1": float("nan"),
                f"top_{top_k}_lift": float("nan"),
                "calibration_ece": float("nan"),
                "roc_auc_production_class": float("nan"),
            }
            continue

        y_true = np.asarray(slice_df[y_col])
        y_pred = np.asarray(slice_df[y_pred_col])
        y_prob = np.asarray(slice_df[y_prob_col], dtype=float)

        out[name] = {
            "n": n,
            "status": "ok",
            "accuracy": _safe_accuracy(y_true, y_pred),
            "weighted_f1": _safe_weighted_f1(y_true, y_pred),
            f"top_{top_k}_lift": _safe_top_k_lift(y_true, y_prob, production_class_idx, k=top_k),
            "calibration_ece": _safe_ece_production_class(y_true, y_prob, production_class_idx),
            "roc_auc_production_class": _safe_roc_auc_production_class(
                y_true, y_prob, production_class_idx
            ),
        }
    return out


def regime_decomposition_gate(
    by_regime: Dict[str, Dict],
    min_regimes_passing: int = 3,
    failing_regime_min_auc: float = 0.5,
    passing_regime_min_auc: float = 0.55,
) -> GateResult:
    """Gate: at least `min_regimes_passing` regimes have ROC-AUC >= passing_regime_min_auc
    AND in every other regime (with enough data) ROC-AUC >= failing_regime_min_auc
    (no catastrophic behavior).
    """
    aucs_with_data = {}
    for name, m in by_regime.items():
        if m["status"] != "ok":
            continue
        auc = m.get("roc_auc_production_class")
        if auc is None or (isinstance(auc, float) and np.isnan(auc)):
            continue
        aucs_with_data[name] = auc

    passing = [n for n, a in aucs_with_data.items() if a >= passing_regime_min_auc]
    catastrophic = [n for n, a in aucs_with_data.items() if a < failing_regime_min_auc]

    n_passing = len(passing)
    status = "pass" if (n_passing >= min_regimes_passing and not catastrophic) else "fail"
    detail = (
        f"{n_passing}/{len(aucs_with_data)} regimes >= {passing_regime_min_auc:.2f} AUC; "
        f"catastrophic regimes (< {failing_regime_min_auc:.2f}): {catastrophic or 'none'}"
    )
    return GateResult(
        name="regime_decomposition",
        status=status,
        value=float(n_passing),
        threshold=float(min_regimes_passing),
        detail=detail,
        blocking=True,
    )
