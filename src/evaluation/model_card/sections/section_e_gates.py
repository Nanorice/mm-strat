"""Section E — gate performance (threshold operating points).

Per §6 R1 of the framework: scan T ∈ {0.3, 0.4, 0.5, 0.6, 0.7} on the Mode A
pool. For each T, report precision, recall, coverage, monthly trade
frequency, magnitude-conditional precision (E6), and E[MFE|P≥T] (E7).

E5 (threshold stability across folds) is a Phase 4 concern; here we
substitute "variance across calendar years" as a cheap proxy.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ..data_loader import EvalSplit
from ..rubric import GateEntry, MetricEntry, SectionResult, rubric_score

logger = logging.getLogger(__name__)

THRESHOLDS: tuple[float, ...] = (0.3, 0.4, 0.5, 0.6, 0.7)
DEPLOYMENT_T_STAR = 0.6
MFE_PRECISION_CUTS: tuple[float, ...] = (30.0, 50.0, 100.0)
MIN_TRADES_PER_MONTH = 3.0


def _trades_per_month(pool: pd.DataFrame, mask: pd.Series) -> float:
    """Estimate trades/month: passing rows / months in window."""
    if mask.sum() == 0:
        return 0.0
    dates = pd.to_datetime(pool.loc[mask, "date"])
    if dates.empty:
        return 0.0
    months = max(1.0, (dates.max() - dates.min()).days / 30.4375)
    return float(mask.sum() / months)


def _per_threshold_row(pool: pd.DataFrame, prevalence: float, t: float) -> dict:
    p = pool["pred_proba"].to_numpy(dtype=float)
    y = pool["label_binary"].to_numpy(dtype=float)
    mfe = pool["label_mfe"].to_numpy(dtype=float)
    gate = p >= t

    n_pass = int(gate.sum())
    n_total = int(len(pool))
    n_positives_total = int(np.nansum(y))

    if n_pass == 0:
        precision = float("nan")
        recall = float("nan")
        mean_mfe = float("nan")
        median_mfe = float("nan")
        mfe_precisions = {c: float("nan") for c in MFE_PRECISION_CUTS}
    else:
        gated_y = y[gate]
        gated_mfe = mfe[gate]
        gated_y_nonan = gated_y[~np.isnan(gated_y)]
        precision = float(gated_y_nonan.mean()) if gated_y_nonan.size else float("nan")
        recall = (
            float(np.nansum(gated_y) / n_positives_total) if n_positives_total else float("nan")
        )
        gated_mfe_nonan = gated_mfe[~np.isnan(gated_mfe)]
        if gated_mfe_nonan.size:
            mean_mfe = float(gated_mfe_nonan.mean())
            median_mfe = float(np.median(gated_mfe_nonan))
            mfe_precisions = {
                c: float((gated_mfe_nonan > c).mean()) for c in MFE_PRECISION_CUTS
            }
        else:
            mean_mfe = median_mfe = float("nan")
            mfe_precisions = {c: float("nan") for c in MFE_PRECISION_CUTS}

    coverage = float(n_pass / n_total) if n_total else float("nan")
    trades_pm = _trades_per_month(pool, pd.Series(gate, index=pool.index))
    lift = (precision / prevalence) if (prevalence and not np.isnan(precision)) else float("nan")

    return {
        "threshold": t,
        "n_pass": n_pass,
        "coverage_pct": 100.0 * coverage,
        "precision": precision,
        "precision_lift_over_prevalence": lift,
        "recall": recall,
        "trades_per_month": trades_pm,
        "mean_mfe_given_gate": mean_mfe,
        "median_mfe_given_gate": median_mfe,
        "p_mfe_gt_30": mfe_precisions[30.0],
        "p_mfe_gt_50": mfe_precisions[50.0],
        "p_mfe_gt_100": mfe_precisions[100.0],
    }


def _stability_by_year(pool: pd.DataFrame, t: float) -> dict:
    """Variance of precision at threshold T across calendar years (proxy for E5)."""
    df = pool.copy()
    df["year"] = pd.to_datetime(df["date"]).dt.year
    rows = []
    for year, sub in df.groupby("year", sort=True, observed=True):
        gate = sub["pred_proba"] >= t
        if gate.sum() == 0:
            continue
        gated_y = sub.loc[gate, "label_binary"].dropna()
        if gated_y.empty:
            continue
        rows.append({
            "year": int(year),
            "n_pass": int(gate.sum()),
            "precision": float(gated_y.mean()),
        })
    if len(rows) < 2:
        return {"variance": float("nan"), "rows": rows, "min": float("nan"),
                "max": float("nan"), "range": float("nan")}
    precs = np.array([r["precision"] for r in rows], dtype=float)
    return {
        "variance": float(precs.var(ddof=1)),
        "range": float(precs.max() - precs.min()),
        "min": float(precs.min()),
        "max": float(precs.max()),
        "rows": rows,
    }


def run_section_e(split: EvalSplit, mode_a_pool: pd.DataFrame) -> SectionResult:
    section = SectionResult(
        name="E",
        title="Gate performance (threshold sweep)",
        scored=True,
    )

    if mode_a_pool.empty:
        section.detail = "Mode A pool empty — gate metrics not computable."
        section.gates.append(GateEntry(
            name="E_pool_available",
            status="fail", value=None, threshold=None,
            detail="empty pool", blocking=True,
        ))
        return section

    needed_cols = {"pred_proba", "label_binary", "label_mfe", "date"}
    missing = needed_cols - set(mode_a_pool.columns)
    if missing:
        raise ValueError(f"Mode A pool missing required cols: {sorted(missing)}")

    prevalence = float(split.prevalence)
    rows = [_per_threshold_row(mode_a_pool, prevalence, t) for t in THRESHOLDS]
    sweep = pd.DataFrame(rows)
    section.tables["threshold_sweep"] = sweep.to_dict(orient="records")

    # Headline numbers at deployment T*
    star_idx = sweep["threshold"].sub(DEPLOYMENT_T_STAR).abs().idxmin()
    star = sweep.iloc[star_idx]
    section.metrics.extend([
        MetricEntry(
            f"precision_at_t={DEPLOYMENT_T_STAR}",
            float(star["precision"]) if not pd.isna(star["precision"]) else None,
            f"P(label=1 | P ≥ {DEPLOYMENT_T_STAR}). Prevalence={prevalence:.4f}.",
        ),
        MetricEntry(
            f"precision_lift_at_t={DEPLOYMENT_T_STAR}",
            float(star["precision_lift_over_prevalence"])
                if not pd.isna(star["precision_lift_over_prevalence"]) else None,
            "precision / prevalence (≥ 1.5 = gate adds value)",
        ),
        MetricEntry(
            f"coverage_pct_at_t={DEPLOYMENT_T_STAR}",
            float(star["coverage_pct"]),
            "fraction of pool above T (in percent)",
        ),
        MetricEntry(
            f"trades_per_month_at_t={DEPLOYMENT_T_STAR}",
            float(star["trades_per_month"]),
            f"min usable = {MIN_TRADES_PER_MONTH}/month",
        ),
        MetricEntry(
            f"mean_mfe_given_gate_at_t={DEPLOYMENT_T_STAR}",
            float(star["mean_mfe_given_gate"]) if not pd.isna(star["mean_mfe_given_gate"]) else None,
            "E[MFE % | P ≥ T*]",
        ),
        MetricEntry(
            f"p_mfe_gt_30_at_t={DEPLOYMENT_T_STAR}",
            float(star["p_mfe_gt_30"]) if not pd.isna(star["p_mfe_gt_30"]) else None,
            "P(MFE > 30% | P ≥ T*) — 30% home-run gate",
        ),
        MetricEntry(
            f"p_mfe_gt_50_at_t={DEPLOYMENT_T_STAR}",
            float(star["p_mfe_gt_50"]) if not pd.isna(star["p_mfe_gt_50"]) else None,
            "P(MFE > 50% | P ≥ T*) — bigger winners",
        ),
        MetricEntry(
            f"p_mfe_gt_100_at_t={DEPLOYMENT_T_STAR}",
            float(star["p_mfe_gt_100"]) if not pd.isna(star["p_mfe_gt_100"]) else None,
            "P(MFE > 100% | P ≥ T*) — 10-baggers",
        ),
    ])

    # Stability across years at T* (proxy for E5 until walk-forward folds)
    stability = _stability_by_year(mode_a_pool, DEPLOYMENT_T_STAR)
    if stability["rows"]:
        section.tables["precision_by_year_at_t_star"] = stability["rows"]
    if not np.isnan(stability["variance"]):
        section.metrics.append(MetricEntry(
            f"precision_variance_across_years_at_t={DEPLOYMENT_T_STAR}",
            stability["variance"],
            f"variance of yearly precision; range={stability['range']:.3f}",
        ))

    # Rubric scoring at T*: precision lift, coverage, stability
    lift = star["precision_lift_over_prevalence"]
    section.rubric_scores["precision_lift"] = rubric_score(
        float(lift) if not pd.isna(lift) else 0.0, [1.0, 1.5, 3.0]
    )
    # Coverage band: too sparse OR too loose are both bad (we use 0.3..0.5..2.0% as ramp)
    cov = float(star["coverage_pct"])
    if cov >= 0.5 and cov <= 50.0:
        # well-shaped coverage — score on the lower side (0.5%) being marginal,
        # 1.5% being good, 5% being strong (operational pool size)
        cov_score = rubric_score(cov, [0.3, 1.0, 3.0])
    else:
        cov_score = 0
    section.rubric_scores["coverage"] = cov_score
    if not np.isnan(stability["variance"]):
        section.rubric_scores["stability"] = rubric_score(
            stability["variance"], [0.20, 0.10, 0.05], higher_is_better=False
        )

    # Gates
    e1_ok = not pd.isna(lift) and lift > 1.5
    section.gates.append(GateEntry(
        name="E1_precision_lift",
        status="pass" if e1_ok else "fail",
        value=float(lift) if not pd.isna(lift) else None,
        threshold=1.5,
        detail=f"precision at T*={DEPLOYMENT_T_STAR}: {lift:.3f}× prevalence "
               f"(need > 1.5×)",
        blocking=True,
    ))
    tpm = float(star["trades_per_month"])
    e2_ok = tpm >= MIN_TRADES_PER_MONTH
    section.gates.append(GateEntry(
        name="E2_trade_frequency",
        status="pass" if e2_ok else "fail",
        value=tpm, threshold=MIN_TRADES_PER_MONTH,
        detail=f"trades/month at T*={DEPLOYMENT_T_STAR}: {tpm:.2f} "
               f"(need ≥ {MIN_TRADES_PER_MONTH})",
        blocking=True,
    ))
    if not np.isnan(stability["variance"]):
        var_ok = stability["variance"] < 0.10
        section.gates.append(GateEntry(
            name="E3_stability_warn",
            status="pass" if var_ok else "warn",
            value=stability["variance"], threshold=0.10,
            detail=f"yearly precision variance={stability['variance']:.4f} "
                   f"(warn if ≥ 0.10)",
            blocking=False,
        ))

    section.detail = (
        f"Sweep T ∈ {list(THRESHOLDS)}. At T*={DEPLOYMENT_T_STAR}: "
        f"precision={star['precision']:.4f} ({lift:.2f}× prev), "
        f"coverage={star['coverage_pct']:.2f}%, "
        f"trades/mo={tpm:.2f}, "
        f"E[MFE|gate]={star['mean_mfe_given_gate']:.2f}%."
    )
    return section
