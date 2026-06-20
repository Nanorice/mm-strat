"""Shared ranking-diff core for prod-vs-shadow model comparison.

Both models score the SAME candidate universe (SEPA criteria gate entry, not the
model), so comparison is counterfactual re-scoring, not an A/B test. The model
only RANKS — and ranking is how stocks are selected — so the core question is:
do the two models rank the same tickers differently, and how much?

This module is the single computation path shared by:
  - Module A1 (scripts/compare_shadow.py)  — over a wide date range → markdown
  - Module B  (orchestrator nightly)        — over one day → shadow_divergence row

Inputs are already-materialized RAW scores from daily_predictions (no model is
loaded here, no outcomes, no calibration — ranking is monotonic-invariant so raw
probs are sufficient and leakage-free). The production-class probability is the
highest-indexed prob_class_* column, mirroring prediction_logger's ranking.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

logger = logging.getLogger(__name__)


def _prod_prob_col(df: pd.DataFrame) -> str:
    """Highest-indexed prob_class_* present — the production class probability."""
    prob_cols = sorted(
        (c for c in df.columns if c.startswith("prob_class_")),
        key=lambda c: int(c.rsplit("_", 1)[1]),
    )
    if not prob_cols:
        raise ValueError("frame has no prob_class_* column to rank by")
    # Production class is the highest index that is not all-null (a binary model
    # pads prob_class_2/3 with NULL; we must not pick those).
    for col in reversed(prob_cols):
        if df[col].notna().any():
            return col
    raise ValueError("all prob_class_* columns are null")


@dataclass
class DayDivergence:
    """Ranking divergence between prod and shadow for a single date."""

    prediction_date: object
    n_common: int
    spearman: float
    jaccard_at_10: float
    n_disagreements: int  # tickers whose rank differs by more than `churn_tol`


@dataclass
class ComparisonResult:
    """Aggregate ranking comparison over a date range, plus drill-downs."""

    prod_version_id: str
    shadow_version_id: str
    cohort: str
    n_dates: int
    n_rows_prod: int
    n_rows_shadow: int
    mean_spearman: float
    mean_jaccard_at_10: float
    total_disagreements: int
    per_day: pd.DataFrame = field(default_factory=pd.DataFrame)
    top_disagreements: pd.DataFrame = field(default_factory=pd.DataFrame)


def compare_day(
    prod_day: pd.DataFrame,
    shadow_day: pd.DataFrame,
    top_k: int = 10,
    churn_tol: int = 0,
) -> Optional[DayDivergence]:
    """Ranking divergence for one date. None if the two share no tickers.

    `churn_tol`: a ticker counts as a disagreement only if |prod_rank -
    shadow_rank| > churn_tol (0 = any rank change counts).
    """
    prod_col = _prod_prob_col(prod_day)
    shadow_col = _prod_prob_col(shadow_day)

    merged = prod_day[["ticker", prod_col]].merge(
        shadow_day[["ticker", shadow_col]],
        on="ticker",
        how="inner",
        suffixes=("_prod", "_shadow"),
    )
    n_common = len(merged)
    if n_common == 0:
        return None

    p = merged[f"{prod_col}_prod" if prod_col == shadow_col else prod_col]
    s = merged[f"{shadow_col}_shadow" if prod_col == shadow_col else shadow_col]

    # Dense ranking within the day (1 = highest production-class prob).
    prod_rank = p.rank(method="first", ascending=False)
    shadow_rank = s.rank(method="first", ascending=False)

    if n_common >= 2 and p.nunique() > 1 and s.nunique() > 1:
        rho = float(spearmanr(prod_rank, shadow_rank).correlation)
    else:
        rho = float("nan")

    k = min(top_k, n_common)
    prod_topk = set(merged.loc[prod_rank <= k, "ticker"])
    shadow_topk = set(merged.loc[shadow_rank <= k, "ticker"])
    union = prod_topk | shadow_topk
    jaccard = len(prod_topk & shadow_topk) / len(union) if union else float("nan")

    n_disagree = int((np.abs(prod_rank - shadow_rank) > churn_tol).sum())

    date_val = (
        prod_day["prediction_date"].iloc[0]
        if "prediction_date" in prod_day.columns
        else None
    )
    return DayDivergence(date_val, n_common, rho, jaccard, n_disagree)


def compare_rankings(
    prod_df: pd.DataFrame,
    shadow_df: pd.DataFrame,
    prod_version_id: str,
    shadow_version_id: str,
    cohort: str,
    top_k: int = 10,
    churn_tol: int = 0,
    max_disagreements: int = 50,
) -> ComparisonResult:
    """Aggregate ranking comparison across all shared dates in the two frames.

    Both frames must carry `prediction_date`, `ticker`, and prob_class_* columns
    (the daily_predictions schema). Iterates per date so ranks are computed
    within-day, then aggregates.
    """
    common_dates = sorted(
        set(prod_df["prediction_date"]) & set(shadow_df["prediction_date"])
    )
    prod_by_date = dict(tuple(prod_df.groupby("prediction_date")))
    shadow_by_date = dict(tuple(shadow_df.groupby("prediction_date")))

    rows: list[DayDivergence] = []
    disagreement_frames: list[pd.DataFrame] = []
    for d in common_dates:
        day = compare_day(prod_by_date[d], shadow_by_date[d], top_k, churn_tol)
        if day is not None:
            rows.append(day)
            disagreement_frames.append(
                _day_disagreement_rows(prod_by_date[d], shadow_by_date[d], d, churn_tol)
            )

    per_day = pd.DataFrame(
        [
            {
                "prediction_date": r.prediction_date,
                "n_common": r.n_common,
                "spearman": r.spearman,
                "jaccard_at_10": r.jaccard_at_10,
                "n_disagreements": r.n_disagreements,
            }
            for r in rows
        ]
    )

    all_disagree = (
        pd.concat(disagreement_frames, ignore_index=True)
        if disagreement_frames
        else pd.DataFrame()
    )
    if not all_disagree.empty:
        all_disagree = all_disagree.reindex(
            all_disagree["rank_delta"].abs().sort_values(ascending=False).index
        ).head(max_disagreements)

    return ComparisonResult(
        prod_version_id=prod_version_id,
        shadow_version_id=shadow_version_id,
        cohort=cohort,
        n_dates=len(per_day),
        n_rows_prod=len(prod_df),
        n_rows_shadow=len(shadow_df),
        mean_spearman=float(per_day["spearman"].mean()) if not per_day.empty else float("nan"),
        mean_jaccard_at_10=float(per_day["jaccard_at_10"].mean()) if not per_day.empty else float("nan"),
        total_disagreements=int(per_day["n_disagreements"].sum()) if not per_day.empty else 0,
        per_day=per_day,
        top_disagreements=all_disagree,
    )


def _day_disagreement_rows(
    prod_day: pd.DataFrame, shadow_day: pd.DataFrame, date_val, churn_tol: int
) -> pd.DataFrame:
    """Per-ticker rank divergence for one date (for the drill-down table)."""
    prod_col = _prod_prob_col(prod_day)
    shadow_col = _prod_prob_col(shadow_day)
    merged = prod_day[["ticker", prod_col]].merge(
        shadow_day[["ticker", shadow_col]], on="ticker", how="inner",
        suffixes=("_p", "_s"),
    )
    if merged.empty:
        return merged
    pcol = prod_col + "_p" if prod_col == shadow_col else prod_col
    scol = shadow_col + "_s" if prod_col == shadow_col else shadow_col
    merged["prod_rank"] = merged[pcol].rank(method="first", ascending=False).astype(int)
    merged["shadow_rank"] = merged[scol].rank(method="first", ascending=False).astype(int)
    merged["rank_delta"] = merged["shadow_rank"] - merged["prod_rank"]
    merged["prediction_date"] = date_val
    out = merged[np.abs(merged["rank_delta"]) > churn_tol]
    return out[
        ["prediction_date", "ticker", "prod_rank", "shadow_rank", "rank_delta",
         pcol, scol]
    ].rename(columns={pcol: "prod_prob", scol: "shadow_prob"})


_DIVERGENCE_MIGRATION = (
    Path(__file__).resolve().parent.parent.parent
    / "scripts" / "migrations" / "2026_06_18_create_shadow_divergence.sql"
)


def ensure_divergence_schema(db_path: str) -> None:
    """Create the shadow_divergence table if absent. Idempotent."""
    if not _DIVERGENCE_MIGRATION.exists():
        raise FileNotFoundError(f"migration missing: {_DIVERGENCE_MIGRATION}")
    con = duckdb.connect(str(db_path))
    try:
        con.execute(_DIVERGENCE_MIGRATION.read_text(encoding="utf-8"))
    finally:
        con.close()


def write_day_divergence(
    db_path: str,
    prediction_date,
    prod_version_id: str,
    shadow_version_id: str,
    cohort: str,
    day: DayDivergence,
) -> None:
    """Upsert one day's divergence verdict into shadow_divergence."""
    ensure_divergence_schema(db_path)
    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            """
            INSERT OR REPLACE INTO shadow_divergence
                (prediction_date, prod_version_id, shadow_version_id, cohort,
                 n_common, spearman, jaccard_at_10, n_disagreements, computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            [
                prediction_date, prod_version_id, shadow_version_id, cohort,
                day.n_common,
                None if day.spearman != day.spearman else day.spearman,  # NaN→NULL
                None if day.jaccard_at_10 != day.jaccard_at_10 else day.jaccard_at_10,
                day.n_disagreements,
            ],
        )
    finally:
        con.close()


def load_cohort_scores(
    db_path: str,
    model_version_id: str,
    cohort: str = "breakout",
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> pd.DataFrame:
    """Pull one model's materialized scores from daily_predictions for a cohort.

    Read-only. The shadow's scores must already be materialized (via the nightly
    Phase 7.4 shadow pass or backfill_daily_predictions.py --model-version-id);
    this never runs a model.
    """
    pred = ["model_version_id = ?", "cohort = ?"]
    params: list = [model_version_id, cohort]
    if start:
        pred.append("prediction_date >= ?"); params.append(start)
    if end:
        pred.append("prediction_date <= ?"); params.append(end)
    where = " AND ".join(pred)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        return con.execute(
            f"""
            SELECT prediction_date, ticker, model_version_id,
                   prob_class_0, prob_class_1, prob_class_2, prob_class_3,
                   predicted_class, rank_within_day
            FROM daily_predictions
            WHERE {where}
            ORDER BY prediction_date, ticker
            """,
            params,
        ).df()
    finally:
        con.close()
