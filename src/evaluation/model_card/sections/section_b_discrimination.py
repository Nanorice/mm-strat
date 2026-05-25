"""Section B — discrimination (binary classification quality).

ROC-AUC, PR-AUC, Brier, log-loss + DummyClassifier baselines + rubric scoring.
Existing classification_evaluator code wraps the multi-class pipeline; here
we re-implement the four metrics directly on the projected-binary head to
keep this section independent of the prototype eval flow.
"""

from __future__ import annotations

import logging

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)

from ..data_loader import EvalSplit
from ..rubric import GateEntry, MetricEntry, SectionResult, rubric_score

logger = logging.getLogger(__name__)


def _baseline_prior(label_binary: np.ndarray, prevalence: float) -> dict:
    """Always predict the prior probability (= prevalence)."""
    y_prob = np.full_like(label_binary, prevalence, dtype=float)
    # AUC undefined for constant predictor; report nan.
    return {
        "auc": float("nan"),
        "pr_auc": float(average_precision_score(label_binary, y_prob))
        if label_binary.sum() > 0 else float("nan"),
        "brier": float(brier_score_loss(label_binary, y_prob)),
        # log_loss explodes if probs are exactly 0 or 1; prior is always in (0,1)
        "log_loss": float(log_loss(label_binary, np.clip(y_prob, 1e-7, 1 - 1e-7))),
    }


def _baseline_stratified(label_binary: np.ndarray, prevalence: float,
                         seed: int = 42) -> dict:
    """Random predictions in proportion to class balance."""
    rng = np.random.default_rng(seed)
    y_prob = rng.uniform(size=len(label_binary))
    return {
        "auc": float(roc_auc_score(label_binary, y_prob))
        if 0 < label_binary.sum() < len(label_binary) else float("nan"),
        "pr_auc": float(average_precision_score(label_binary, y_prob))
        if label_binary.sum() > 0 else float("nan"),
        "brier": float(brier_score_loss(label_binary, y_prob)),
        "log_loss": float(log_loss(label_binary, np.clip(y_prob, 1e-7, 1 - 1e-7))),
    }


def _gate(name: str, ok: bool, value: float, threshold: float, detail: str,
          *, blocking: bool = True) -> GateEntry:
    return GateEntry(
        name=name,
        status="pass" if ok else "fail",
        value=float(value) if value is not None else None,
        threshold=float(threshold),
        detail=detail,
        blocking=blocking,
    )


def run_section_b(split: EvalSplit) -> SectionResult:
    y = split.label_binary.values.astype(int)
    p = split.pred_proba.values.astype(float)
    prevalence = split.prevalence

    if 0 < y.sum() < len(y):
        auc = float(roc_auc_score(y, p))
    else:
        auc = float("nan")
    pr_auc = float(average_precision_score(y, p)) if y.sum() > 0 else float("nan")
    brier = float(brier_score_loss(y, np.clip(p, 0.0, 1.0)))
    ll = float(log_loss(y, np.clip(p, 1e-7, 1 - 1e-7)))

    baseline_prior = _baseline_prior(y, prevalence)
    baseline_stratified = _baseline_stratified(y, prevalence)

    pr_lift = (pr_auc / prevalence) if (prevalence and not np.isnan(pr_auc)) else float("nan")

    section = SectionResult(
        name="B",
        title="Discrimination (classification quality)",
        scored=True,
    )
    section.metrics.extend([
        MetricEntry("roc_auc", auc, "P(positive scored above negative)"),
        MetricEntry("pr_auc", pr_auc, f"average precision; baseline=prevalence={prevalence:.4f}"),
        MetricEntry("pr_auc_lift_over_prevalence", pr_lift,
                    "PR-AUC / prevalence (≥1.5 ⇒ usable)"),
        MetricEntry("brier", brier, "lower is better"),
        MetricEntry("log_loss", ll, "lower is better"),
        MetricEntry("baseline_prior_brier", baseline_prior["brier"], ""),
        MetricEntry("baseline_prior_log_loss", baseline_prior["log_loss"], ""),
        MetricEntry("baseline_stratified_auc", baseline_stratified["auc"], ""),
    ])

    section.rubric_scores["roc_auc"] = rubric_score(auc, [0.55, 0.60, 0.68])
    section.rubric_scores["pr_auc_lift"] = rubric_score(pr_lift, [1.5, 2.0, 3.0])

    section.gates.append(_gate(
        "B1_auc",
        not np.isnan(auc) and auc > 0.55,
        auc, 0.55,
        f"ROC-AUC={auc:.4f} (gate: > 0.55)",
    ))
    section.gates.append(_gate(
        "B2_pr_auc_lift",
        not np.isnan(pr_lift) and pr_lift > 1.5,
        pr_lift, 1.5,
        f"PR-AUC/prev={pr_lift:.3f}× (gate: > 1.5×)",
    ))
    section.gates.append(_gate(
        "B3_brier_beats_prior",
        brier < baseline_prior["brier"],
        brier, baseline_prior["brier"],
        f"Brier={brier:.4f} vs prior={baseline_prior['brier']:.4f}",
        blocking=False,
    ))

    section.tables["baselines"] = [
        {"baseline": "DummyClassifier(prior)", **baseline_prior},
        {"baseline": "DummyClassifier(stratified)", **baseline_stratified},
        {"baseline": "model", "auc": auc, "pr_auc": pr_auc,
         "brier": brier, "log_loss": ll},
    ]
    section.detail = (
        f"n={len(y)}, positives={int(y.sum())}, prevalence={prevalence:.4f}. "
        f"AUC={auc:.3f}, PR-AUC={pr_auc:.3f} ({pr_lift:.2f}× prev), Brier={brier:.4f}."
    )
    return section
