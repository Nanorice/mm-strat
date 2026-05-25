"""Section F — regime & temporal robustness.

Bucketing taxonomies (per §6 R2):
  - Taxonomy 1: M03 score quintiles (continuous DOUBLE)
  - Taxonomy 2: t2_risk_scores.target_exposure (naturally discrete)

Plus per-year and per-sector breakdowns. PSI between train and eval is
computed against the model's `reference_snapshot.json` when present.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from src.evaluation.drift import compute_psi

from ..data_loader import EvalSplit
from ..rubric import GateEntry, MetricEntry, SectionResult, rubric_score

logger = logging.getLogger(__name__)


def _safe_auc(y: np.ndarray, p: np.ndarray) -> float:
    if len(y) == 0 or y.sum() == 0 or y.sum() == len(y):
        return float("nan")
    try:
        return float(roc_auc_score(y, p))
    except ValueError:
        return float("nan")


def _safe_pr_auc(y: np.ndarray, p: np.ndarray) -> float:
    if y.sum() == 0:
        return float("nan")
    try:
        return float(average_precision_score(y, p))
    except ValueError:
        return float("nan")


def _safe_brier(y: np.ndarray, p: np.ndarray) -> float:
    if len(y) == 0:
        return float("nan")
    return float(brier_score_loss(y, np.clip(p, 0.0, 1.0)))


def _metrics_in_bucket(bucket_label, df: pd.DataFrame) -> dict:
    y = df["label_binary"].values.astype(int)
    p = df["pred_proba"].values.astype(float)
    return {
        "bucket": str(bucket_label),
        "n": int(len(df)),
        "n_positives": int(y.sum()),
        "prevalence": float(y.mean()) if len(y) else float("nan"),
        "auc": _safe_auc(y, p),
        "pr_auc": _safe_pr_auc(y, p),
        "brier": _safe_brier(y, p),
    }


def _by_bucket(working: pd.DataFrame, bucket_col: pd.Series) -> list[dict]:
    rows = []
    for label, sub in working.groupby(bucket_col, dropna=False, observed=True):
        if pd.isna(label):
            continue
        rows.append(_metrics_in_bucket(label, sub))
    return rows


def _attach_target_exposure(working: pd.DataFrame, db_path: Path) -> pd.Series:
    """Join t2_risk_scores.target_exposure on date."""
    dates = working["date"].drop_duplicates()
    if dates.empty:
        return pd.Series([], dtype=float)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        risk = con.execute(
            "SELECT date, target_exposure FROM t2_risk_scores"
        ).fetchdf()
    finally:
        con.close()
    risk["date"] = pd.to_datetime(risk["date"]).dt.date
    working_dates = pd.to_datetime(working["date"]).dt.date
    lookup = dict(zip(risk["date"], risk["target_exposure"]))
    return pd.Series(
        [lookup.get(d) for d in working_dates],
        index=working.index,
        name="target_exposure",
    )


def _quintile_buckets(s: pd.Series) -> pd.Series:
    """qcut into 5 buckets with stable labels Q1..Q5; falls back to N unique
    values if duplicates collapse the bin count."""
    try:
        return pd.qcut(s, 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"], duplicates="drop")
    except ValueError:
        # not enough distinct values for 5 quantiles
        return pd.cut(s, bins=5, labels=False)


def _compute_psi_vs_reference(split: EvalSplit) -> dict:
    """Compute per-feature PSI using the model's reference_snapshot.json."""
    ref_path = split.model_path.parent / "reference_snapshot.json"
    if not ref_path.exists():
        return {"available": False, "reason": f"no reference_snapshot.json at {ref_path}"}
    try:
        ref = json.loads(ref_path.read_text())
    except Exception as e:
        return {"available": False, "reason": f"failed to parse {ref_path}: {e}"}

    feature_refs = ref.get("features") or ref.get("feature_distributions") or {}
    if not feature_refs:
        return {"available": False, "reason": "reference snapshot has no feature distributions"}

    per_feature = []
    for feat in split.feature_cols:
        meta = feature_refs.get(feat)
        if not meta:
            continue
        # reference_snapshot stores per-feature samples or quantile edges; we
        # rely on a 'samples' or 'values' array if present.
        ref_values = meta.get("samples") or meta.get("values")
        if ref_values is None:
            continue
        if feat not in split.df.columns:
            continue
        cur = pd.to_numeric(split.df[feat], errors="coerce").dropna().values
        ref_arr = np.asarray(ref_values, dtype=float)
        ref_arr = ref_arr[~np.isnan(ref_arr)]
        if cur.size < 50 or ref_arr.size < 50:
            continue
        try:
            psi = compute_psi(ref_arr, cur)
            per_feature.append({"feature": feat, "psi": float(psi)})
        except Exception as e:
            logger.debug("PSI failed for %s: %s", feat, e)
    if not per_feature:
        return {"available": False, "reason": "no features could be PSI-scored"}
    per_feature.sort(key=lambda r: r["psi"], reverse=True)
    psi_values = [r["psi"] for r in per_feature]
    return {
        "available": True,
        "max_psi": float(max(psi_values)),
        "median_psi": float(np.median(psi_values)),
        "n_features_scored": len(per_feature),
        "n_above_0_25": int(sum(1 for v in psi_values if v > 0.25)),
        "per_feature": per_feature[:25],  # top 25 by PSI
    }


def run_section_f(split: EvalSplit, db_path: Path) -> SectionResult:
    working = pd.DataFrame({
        "date": pd.to_datetime(split.df["date"]),
        "label_binary": split.label_binary.values,
        "pred_proba": split.pred_proba.values,
        "m03_score": split.df.get("m03_score", pd.Series(np.nan, index=split.df.index)),
        "sector": split.df.get("sector", pd.Series("Unknown", index=split.df.index)).fillna("Unknown"),
    })

    # Taxonomy 1 — M03 quintiles
    m03_buckets = _quintile_buckets(working["m03_score"])
    taxonomy_m03 = _by_bucket(working, m03_buckets)

    # Taxonomy 2 — target_exposure (already-discrete)
    target_exp = _attach_target_exposure(working, db_path)
    taxonomy_target_exp = _by_bucket(working, target_exp.fillna(-1.0))

    # Per-year
    year_bucket = working["date"].dt.year.astype(str)
    per_year = _by_bucket(working, year_bucket)

    # Per-sector
    per_sector = _by_bucket(working, working["sector"])

    # PSI
    psi = _compute_psi_vs_reference(split)

    section = SectionResult(
        name="F",
        title="Regime & temporal robustness",
        scored=True,
    )

    def _auc_pass_rate(rows: list[dict], min_n: int = 30) -> float:
        eligible = [r for r in rows if r["n"] >= min_n and not np.isnan(r["auc"])]
        if not eligible:
            return float("nan")
        return float(sum(1 for r in eligible if r["auc"] > 0.55) / len(eligible))

    auc_pass_m03 = _auc_pass_rate(taxonomy_m03)
    auc_pass_target = _auc_pass_rate(taxonomy_target_exp)
    worst_auc_pass = (
        min(auc_pass_m03, auc_pass_target)
        if not (np.isnan(auc_pass_m03) or np.isnan(auc_pass_target))
        else float("nan")
    )

    # Year-over-year stability — range of AUCs
    year_aucs = [r["auc"] for r in per_year if r["n"] >= 30 and not np.isnan(r["auc"])]
    if len(year_aucs) >= 2:
        yoy_range = float(max(year_aucs) - min(year_aucs))
    else:
        yoy_range = float("nan")

    section.metrics.extend([
        MetricEntry("auc_regime_pass_rate_m03", auc_pass_m03,
                    "fraction of M03 quintiles with AUC > 0.55 (min n=30)"),
        MetricEntry("auc_regime_pass_rate_target_exp", auc_pass_target,
                    "fraction of target_exposure buckets with AUC > 0.55 (min n=30)"),
        MetricEntry("yoy_auc_range", yoy_range,
                    "max(yearly AUC) - min(yearly AUC) for years with n≥30"),
    ])
    if psi.get("available"):
        section.metrics.extend([
            MetricEntry("psi_max", psi["max_psi"], "worst per-feature PSI vs training reference"),
            MetricEntry("psi_median", psi["median_psi"], "median per-feature PSI"),
            MetricEntry("psi_features_over_0_25", float(psi["n_above_0_25"]),
                        "count of features with PSI > 0.25 (material drift)"),
        ])

    # Rubric: regime pass rate
    section.rubric_scores["regime_pass_rate"] = rubric_score(
        worst_auc_pass if not np.isnan(worst_auc_pass) else 0.0,
        [0.4, 0.6, 0.8],
    )
    if not np.isnan(yoy_range):
        section.rubric_scores["yoy_stability"] = rubric_score(
            yoy_range, [0.15, 0.10, 0.05], higher_is_better=False
        )

    # Gates
    section.gates.append(GateEntry(
        name="F1_regime_pass_rate",
        status="pass" if (not np.isnan(worst_auc_pass) and worst_auc_pass >= 0.6) else "fail",
        value=worst_auc_pass if not np.isnan(worst_auc_pass) else None,
        threshold=0.6,
        detail=(
            f"min pass-rate across taxonomies={worst_auc_pass:.2f}"
            if not np.isnan(worst_auc_pass) else
            "could not compute (insufficient bucket samples)"
        ),
        blocking=True,
    ))
    bad_years = [r["bucket"] for r in per_year
                 if r["n"] >= 30 and not np.isnan(r["auc"]) and r["auc"] < 0.50]
    section.gates.append(GateEntry(
        name="F2_no_year_worse_than_random",
        status="pass" if not bad_years else "warn",
        value=float(len(bad_years)),
        threshold=0.0,
        detail=f"years with AUC < 0.50: {bad_years or 'none'}",
        blocking=False,
    ))
    if psi.get("available"):
        psi_ok = psi["max_psi"] < 0.25
        section.gates.append(GateEntry(
            name="F4_psi_drift",
            status="pass" if psi_ok else "fail",
            value=psi["max_psi"], threshold=0.25,
            detail=f"max PSI={psi['max_psi']:.3f} (gate: < 0.25)",
            blocking=True,
        ))

    section.tables["taxonomy_m03_quintiles"] = taxonomy_m03
    section.tables["taxonomy_target_exposure"] = taxonomy_target_exp
    section.tables["per_year"] = per_year
    section.tables["per_sector"] = per_sector
    if psi.get("available"):
        section.tables["psi_per_feature_top25"] = psi["per_feature"]
    else:
        section.detail += f" PSI: {psi.get('reason', 'unavailable')}."

    section.detail = (
        f"M03 pass-rate={auc_pass_m03:.2f}, target_exp pass-rate={auc_pass_target:.2f}, "
        f"yoy AUC range={yoy_range:.3f}." + (section.detail or "")
    )
    return section
