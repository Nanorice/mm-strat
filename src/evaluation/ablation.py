"""Ablation backtest helpers + feature-importance triangulation (§3.3).

Pure-function helpers extracted so they can be unit-tested without spinning up
training or backtest jobs. The CLI orchestrator lives in
`scripts/ablation_backtest.py`.

The triangulation rule (per the plan): a model is "feature-robust" if
SHAP top-N, permutation top-N, and ablation top-M share ≥ K features.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

import pandas as pd

from .gate import GateResult

# Keys tried in order when selecting the primary comparison metric.
# First key present in a metrics dict wins.
_PRIMARY_METRIC_CANDIDATES = ["sharpe_ratio", "roc_auc", "weighted_f1"]


def _primary_metric_key(metrics: dict) -> str:
    for k in _PRIMARY_METRIC_CANDIDATES:
        if k in metrics:
            return k
    return _PRIMARY_METRIC_CANDIDATES[0]


@dataclass
class AblationDelta:
    group_dropped: str
    baseline_sharpe: float
    ablated_sharpe: float
    delta_sharpe: float
    baseline_return: Optional[float] = None
    ablated_return: Optional[float] = None
    delta_return: Optional[float] = None
    # Set when the run used --no-backtest (classification metrics instead of Sharpe).
    primary_metric: str = "sharpe_ratio"


def compute_ablation_delta(
    baseline_metrics: dict,
    ablated_metrics: dict,
    group_name: str,
) -> AblationDelta:
    """Difference in primary metric between baseline and ablated runs.

    In backtest mode the primary metric is `sharpe_ratio`; in --no-backtest
    mode it falls back to `roc_auc` or `weighted_f1` — whichever key is
    present first in `_PRIMARY_METRIC_CANDIDATES`.

    The `baseline_sharpe` / `ablated_sharpe` / `delta_sharpe` fields on the
    returned dataclass carry the primary metric value regardless of its name,
    for downstream compatibility.
    """
    key = _primary_metric_key(baseline_metrics)
    b_primary = float(baseline_metrics.get(key) or 0.0)
    a_primary = float(ablated_metrics.get(key) or 0.0)
    b_ret = baseline_metrics.get("total_return")
    a_ret = ablated_metrics.get("total_return")
    return AblationDelta(
        group_dropped=group_name,
        baseline_sharpe=b_primary,
        ablated_sharpe=a_primary,
        delta_sharpe=a_primary - b_primary,
        baseline_return=float(b_ret) if b_ret is not None else None,
        ablated_return=float(a_ret) if a_ret is not None else None,
        delta_return=(
            float(a_ret) - float(b_ret) if (a_ret is not None and b_ret is not None) else None
        ),
        primary_metric=key,
    )


def ablation_summary_payload(deltas: Iterable[AblationDelta], baseline_metrics: dict) -> dict:
    """Pack baseline + per-group deltas into the summary JSON."""
    key = _primary_metric_key(baseline_metrics)
    delta_list = sorted(deltas, key=lambda x: x.delta_sharpe)
    return {
        "primary_metric": key,
        "baseline": {
            key: float(baseline_metrics.get(key) or 0.0),
            "total_return": baseline_metrics.get("total_return"),
            "max_drawdown": baseline_metrics.get("max_drawdown"),
            "win_rate": baseline_metrics.get("win_rate"),
            # classification-mode extras (None when in backtest mode)
            "weighted_f1": baseline_metrics.get("weighted_f1"),
            "pos_class_precision": baseline_metrics.get("pos_class_precision"),
        },
        "ablations": [
            {
                "group_dropped": d.group_dropped,
                d.primary_metric: d.ablated_sharpe,
                f"delta_{d.primary_metric}": d.delta_sharpe,
                "total_return": d.ablated_return,
                "delta_return": d.delta_return,
            }
            for d in delta_list
        ],
    }


def ablation_top_groups(
    deltas: Iterable[AblationDelta],
    n: int = 3,
) -> List[str]:
    """Top-N most-impactful groups: largest negative delta = biggest hurt."""
    return [d.group_dropped for d in sorted(deltas, key=lambda x: x.delta_sharpe)[:n]]


def _top_n_features(records: Optional[List[dict]], key: str, n: int) -> List[str]:
    if not records:
        return []
    sorted_recs = sorted(records, key=lambda r: r.get(key, 0.0), reverse=True)
    return [r["feature"] for r in sorted_recs[:n] if "feature" in r]


def triangulation_check(
    shap_summary: Optional[Dict],
    permutation_importance: Optional[List[Dict]],
    ablation_top_features: Optional[List[str]],
    feature_groups: Optional[Dict[str, List[str]]] = None,
    shap_class: Optional[str] = None,
    top_n_shap: int = 5,
    top_n_perm: int = 5,
    top_m_ablation: int = 3,
    min_overlap: int = 3,
) -> GateResult:
    """Verify SHAP / permutation / ablation agree on the model's drivers.

    Args:
        shap_summary: Output of `_compute_shap` — uses
            `shap_summary['mean_abs_shap_per_class'][shap_class]` if shap_class
            given, else the *first* class in the dict.
        permutation_importance: list of {feature, mean_importance, std_importance}
        ablation_top_features: Either feature names directly, or group names that
            get expanded via `feature_groups`.
        feature_groups: Optional mapping {group_name: [feature_names]}. When
            present, ablation_top_features is interpreted as group names and
            expanded; otherwise treated as feature names.
        min_overlap: required intersection size of the three top-K sets.

    Returns:
        A GateResult (non-blocking by default — this is a diagnostic, not a hard
        promotion gate per the plan).
    """
    # SHAP top-N
    shap_top: List[str] = []
    if shap_summary and isinstance(shap_summary, dict):
        per_class = shap_summary.get("mean_abs_shap_per_class") or {}
        if shap_class is None and per_class:
            shap_class = next(iter(per_class))
        if shap_class and shap_class in per_class:
            shap_top = _top_n_features(per_class[shap_class], key="mean_abs_shap", n=top_n_shap)

    # Permutation top-N
    perm_top = _top_n_features(permutation_importance, key="mean_importance", n=top_n_perm)

    # Ablation top-M (group → features expansion)
    abl_features: List[str] = []
    if ablation_top_features:
        if feature_groups:
            for name in ablation_top_features[:top_m_ablation]:
                if name in feature_groups:
                    abl_features.extend(feature_groups[name])
                else:
                    abl_features.append(name)
        else:
            abl_features = list(ablation_top_features[:top_m_ablation])

    # Overlap
    s_shap = set(shap_top)
    s_perm = set(perm_top)
    s_abl = set(abl_features)
    overlap = s_shap & s_perm & s_abl
    n_overlap = len(overlap)

    status = "pass" if n_overlap >= min_overlap else "fail"
    detail = (
        f"shap_top{top_n_shap}={sorted(s_shap)[:10]}; "
        f"perm_top{top_n_perm}={sorted(s_perm)[:10]}; "
        f"ablation_top{top_m_ablation}_expanded={sorted(s_abl)[:10]}; "
        f"3-way overlap={sorted(overlap)}"
    )
    return GateResult(
        name="feature_triangulation",
        status=status,
        value=float(n_overlap),
        threshold=float(min_overlap),
        detail=detail,
        blocking=False,
    )
