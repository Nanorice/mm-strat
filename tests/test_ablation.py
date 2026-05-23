"""Tests for src.evaluation.ablation (§3.3.2 helper functions)."""

from __future__ import annotations

import pytest

from src.evaluation.ablation import (
    AblationDelta,
    ablation_summary_payload,
    ablation_top_groups,
    compute_ablation_delta,
    triangulation_check,
)


# ----------------------------- compute_ablation_delta -----------------------------


def test_compute_ablation_delta_basic():
    baseline = {"sharpe_ratio": 1.5, "total_return": 80.0}
    ablated = {"sharpe_ratio": 0.7, "total_return": 30.0}
    delta = compute_ablation_delta(baseline, ablated, "Momentum")
    assert delta.group_dropped == "Momentum"
    assert delta.baseline_sharpe == 1.5
    assert delta.ablated_sharpe == 0.7
    assert delta.delta_sharpe == pytest.approx(-0.8)
    assert delta.delta_return == pytest.approx(-50.0)


def test_compute_ablation_delta_handles_missing_return():
    baseline = {"sharpe_ratio": 1.0}
    ablated = {"sharpe_ratio": 0.8}
    delta = compute_ablation_delta(baseline, ablated, "X")
    assert delta.delta_return is None


def test_compute_ablation_delta_treats_none_sharpe_as_zero():
    baseline = {"sharpe_ratio": None, "total_return": 50}
    ablated = {"sharpe_ratio": 0.4, "total_return": 30}
    delta = compute_ablation_delta(baseline, ablated, "X")
    assert delta.baseline_sharpe == 0.0
    assert delta.delta_sharpe == 0.4


# ----------------------------- ablation_summary_payload -----------------------------


def test_summary_payload_sorts_by_delta_sharpe():
    baseline = {"sharpe_ratio": 1.0, "total_return": 50.0, "max_drawdown": 12.0}
    deltas = [
        AblationDelta("A", 1.0, 0.9, -0.1, None, None, None),
        AblationDelta("B", 1.0, 0.3, -0.7, None, None, None),
        AblationDelta("C", 1.0, 0.8, -0.2, None, None, None),
    ]
    payload = ablation_summary_payload(deltas, baseline)
    groups = [a["group_dropped"] for a in payload["ablations"]]
    # Smallest delta_sharpe (most negative) first.
    assert groups == ["B", "C", "A"]
    assert payload["baseline"]["sharpe_ratio"] == 1.0


def test_ablation_top_groups_returns_most_impactful():
    deltas = [
        AblationDelta("A", 1.0, 0.9, -0.1, None, None, None),
        AblationDelta("B", 1.0, 0.3, -0.7, None, None, None),
        AblationDelta("C", 1.0, 0.5, -0.5, None, None, None),
        AblationDelta("D", 1.0, 0.95, -0.05, None, None, None),
    ]
    assert ablation_top_groups(deltas, n=2) == ["B", "C"]
    assert ablation_top_groups(deltas, n=3) == ["B", "C", "A"]


# ----------------------------- triangulation_check -----------------------------


def _shap_summary(features_by_class):
    return {
        "mean_abs_shap_per_class": {
            cls: [{"feature": f, "mean_abs_shap": v}
                  for f, v in feats]
            for cls, feats in features_by_class.items()
        }
    }


def test_triangulation_passes_when_three_shared_features():
    shap = _shap_summary({
        "Home Run": [("rs_pct_chg", 0.5), ("atr_14", 0.4), ("alpha012", 0.3),
                     ("vol_ratio", 0.2), ("rsi_14", 0.1)],
    })
    perm = [
        {"feature": "rs_pct_chg", "mean_importance": 0.05},
        {"feature": "atr_14", "mean_importance": 0.04},
        {"feature": "alpha012", "mean_importance": 0.03},
        {"feature": "x", "mean_importance": 0.02},
        {"feature": "y", "mean_importance": 0.01},
    ]
    ablation_groups = ["Momentum", "Volatility"]
    feature_groups = {
        "Momentum": ["rs_pct_chg", "alpha012", "rsi_14"],
        "Volatility": ["atr_14", "vol_ratio"],
    }
    gate = triangulation_check(
        shap_summary=shap,
        permutation_importance=perm,
        ablation_top_features=ablation_groups,
        feature_groups=feature_groups,
        shap_class="Home Run",
        min_overlap=3,
    )
    assert gate.status == "pass"
    assert gate.value >= 3
    assert gate.blocking is False  # Diagnostic only


def test_triangulation_fails_when_disjoint():
    shap = _shap_summary({"prod": [("a", 1), ("b", 1), ("c", 1), ("d", 1), ("e", 1)]})
    perm = [{"feature": "p", "mean_importance": 1}, {"feature": "q", "mean_importance": 1},
            {"feature": "r", "mean_importance": 1}]
    abl = ["GroupA"]
    fg = {"GroupA": ["x", "y", "z"]}
    gate = triangulation_check(
        shap_summary=shap, permutation_importance=perm,
        ablation_top_features=abl, feature_groups=fg,
        shap_class="prod", min_overlap=3,
    )
    assert gate.status == "fail"
    assert gate.value == 0


def test_triangulation_handles_none_inputs():
    gate = triangulation_check(
        shap_summary=None,
        permutation_importance=None,
        ablation_top_features=None,
    )
    assert gate.status == "fail"
    assert gate.value == 0


def test_triangulation_treats_ablation_as_features_when_no_groups():
    shap = _shap_summary({"prod": [("a", 1), ("b", 1), ("c", 1)]})
    perm = [{"feature": "a", "mean_importance": 1}, {"feature": "b", "mean_importance": 1},
            {"feature": "c", "mean_importance": 1}]
    abl = ["a", "b", "c"]
    gate = triangulation_check(
        shap_summary=shap, permutation_importance=perm,
        ablation_top_features=abl, feature_groups=None,
        shap_class="prod", min_overlap=3,
    )
    assert gate.status == "pass"
    assert gate.value == 3


def test_triangulation_picks_first_shap_class_when_unspecified():
    shap = _shap_summary({
        "ClassA": [("a", 1), ("b", 1)],
        "ClassB": [("c", 1), ("d", 1)],
    })
    perm = [{"feature": "a", "mean_importance": 1}, {"feature": "b", "mean_importance": 1}]
    abl = ["a", "b"]
    gate = triangulation_check(
        shap_summary=shap, permutation_importance=perm,
        ablation_top_features=abl, min_overlap=2,
    )
    # ClassA is first → should overlap with a,b
    assert gate.status == "pass"
