"""Benchmarks the model card scores against.

Two kinds of benchmarks per framework §B (DummyClassifier) and the
"vs BASELINE" block in the §4 final verdict (SEPA-composite ranker):

1. **DummyClassifier-style baselines** are already produced by
   `section_b_discrimination.run_section_b` (prior + stratified). They live
   on Section B and don't need duplicating here.

2. **SEPA-composite-score baseline** — replace `pred_proba` with a simple
   hand-crafted SEPA score (no ML) and re-run a subset of the ranker
   metrics. Answers the "does the model add value over a domain-knowledge
   score?" question. This is the §4 "vs SEPA composite-score ranker"
   line in the final verdict.

The composite score is a normalized equal-weight blend of canonical SEPA
strength signals: trend strength (RS line), proximity to 52w high, and
recent relative momentum. Components are min-max normalized within each
date (cross-sectional rank) before averaging — so the composite is itself
a per-day rank. Missing components are skipped (score = average of
available components per row).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)

from .data_loader import EvalSplit

logger = logging.getLogger(__name__)

# Candidate composite components. We use whichever subset is available in
# the eval dataframe — these are the canonical SEPA strength features
# exposed by v_d2_training (per memory `daily_features Schema v3.1`).
# Names are checked in both lowercase (DuckDB native) and TitleCase
# (after view-manager COLUMN_CASE_MAP rename); the loader picks whichever
# is present.
_COMPOSITE_COMPONENTS_HIGHER_BETTER: tuple[str, ...] = (
    "rs_rating",              # 1-99 IBD-style cross-sectional rank
    "rs",                     # raw RS momentum blend
    "rs_ma",                  # smoothed RS
    "rs_line_log",            # log RS line (relative strength vs benchmark)
    "return_20d",             # short-term momentum
    "price_vs_spy",           # benchmark-relative price
    "vol_ratio",              # volume confirmation
    "rs_universe_rank",       # if catalog reranked
)

# Components where smaller absolute value = better (distance metrics).
# `pct_from_high_52w` is typically negative; closer to zero = stronger.
_COMPOSITE_COMPONENTS_LOWER_BETTER: tuple[str, ...] = (
    "pct_from_high_52w",
    "dist_from_52w_high",     # alt name from v3.1 derived features
)


@dataclass(frozen=True)
class BaselineMetrics:
    name: str
    n_rows: int
    auc: float
    pr_auc: float
    brier: float
    log_loss: float
    binary_ic_mean: float
    top5_lift: float
    prevalence: float

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "n_rows": self.n_rows,
            "auc": self.auc,
            "pr_auc": self.pr_auc,
            "brier": self.brier,
            "log_loss": self.log_loss,
            "binary_ic_mean": self.binary_ic_mean,
            "top5_lift": self.top5_lift,
            "prevalence": self.prevalence,
        }


def _per_day_rank(series: pd.Series, dates: pd.Series,
                  higher_is_better: bool = True) -> pd.Series:
    """Per-date rank in (0, 1] — 1 = best. NaN inputs propagate."""
    s = pd.to_numeric(series, errors="coerce")
    if not higher_is_better:
        s = -s
    # rank.pct gives values in (0, 1] within each group
    return s.groupby(dates).rank(method="average", pct=True)


def _per_day_binary_ic(df: pd.DataFrame, score_col: str) -> float:
    def _ic(g: pd.DataFrame) -> float:
        if len(g) < 2:
            return np.nan
        x = g[score_col].to_numpy(dtype=float)
        y = g["label_binary"].to_numpy(dtype=float)
        m = ~(np.isnan(x) | np.isnan(y))
        if m.sum() < 2:
            return np.nan
        if np.unique(x[m]).size < 2 or np.unique(y[m]).size < 2:
            return np.nan
        return pd.Series(x[m]).corr(pd.Series(y[m]), method="spearman")

    daily = df.groupby("date", sort=False).apply(_ic, include_groups=False)
    daily = pd.to_numeric(daily, errors="coerce").dropna()
    if daily.empty:
        return float("nan")
    return float(daily.mean())


def _per_day_top_k_lift(df: pd.DataFrame, score_col: str, k: int = 5) -> float:
    def _lift(g: pd.DataFrame) -> float:
        g = g.dropna(subset=[score_col, "label_binary"])
        if len(g) == 0:
            return np.nan
        pool_mean = g["label_binary"].mean()
        if not pool_mean or pool_mean == 0 or np.isnan(pool_mean):
            return np.nan
        top = g.nlargest(k, score_col)
        return float(top["label_binary"].mean() / pool_mean)

    per_day = df.groupby("date", sort=False).apply(_lift, include_groups=False)
    per_day = pd.to_numeric(per_day, errors="coerce").dropna()
    if per_day.empty:
        return float("nan")
    return float(per_day.mean())


def _safe_auc(y: np.ndarray, p: np.ndarray) -> float:
    if y.sum() == 0 or y.sum() == len(y):
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


def _classification_block(score: pd.Series, label: pd.Series) -> tuple[float, float, float, float]:
    mask = score.notna() & label.notna()
    if mask.sum() < 2:
        return (float("nan"),) * 4
    s = score[mask].to_numpy(dtype=float)
    y = label[mask].to_numpy(dtype=int)
    # Normalize score to (0, 1) so AUC / brier / log_loss are well-defined
    # for non-probability inputs (composite is a rank, not a probability).
    s_min, s_max = float(s.min()), float(s.max())
    if s_max > s_min:
        p = (s - s_min) / (s_max - s_min)
    else:
        p = np.full_like(s, 0.5)
    auc = _safe_auc(y, p)
    pr_auc = _safe_pr_auc(y, p)
    brier = float(brier_score_loss(y, np.clip(p, 0.0, 1.0)))
    ll = float(log_loss(y, np.clip(p, 1e-7, 1 - 1e-7)))
    return auc, pr_auc, brier, ll


def _build_composite_score(pool: pd.DataFrame, *,
                           available_cols: set[str]) -> tuple[pd.Series, list[str]]:
    """Build the per-row SEPA composite score.

    Returns (score_series, components_used). If no components are
    available, returns an all-NaN series and an empty list.
    """
    components_used: list[str] = []
    component_ranks: list[pd.Series] = []
    for col in _COMPOSITE_COMPONENTS_HIGHER_BETTER:
        if col in available_cols:
            r = _per_day_rank(pool[col], pool["date"], higher_is_better=True)
            if r.notna().any():
                component_ranks.append(r)
                components_used.append(col)
    for col in _COMPOSITE_COMPONENTS_LOWER_BETTER:
        if col in available_cols:
            r = _per_day_rank(pool[col], pool["date"], higher_is_better=False)
            if r.notna().any():
                component_ranks.append(r)
                components_used.append(col)

    if not component_ranks:
        return pd.Series(np.nan, index=pool.index), []

    # Row-wise mean across components, skipping NaN components.
    stacked = pd.concat(component_ranks, axis=1)
    composite = stacked.mean(axis=1, skipna=True)
    return composite, components_used


def _resolve_components(available_cols: set[str]) -> tuple[
    list[tuple[str, bool]], list[tuple[str, str]]
]:
    """Case-insensitive resolution of composite components.

    Returns:
        (matched, renames) where:
          matched: list of (actual_col_name_in_df, higher_is_better)
          renames: list of (actual_col_name_in_df, canonical_lowercase_name)
        — caller renames df columns to canonical names so downstream code
        can use the lowercase forms consistently.
    """
    avail_lower = {c.lower(): c for c in available_cols}
    matched: list[tuple[str, bool]] = []
    renames: list[tuple[str, str]] = []
    for canonical in _COMPOSITE_COMPONENTS_HIGHER_BETTER:
        actual = avail_lower.get(canonical.lower())
        if actual is not None:
            matched.append((actual, True))
            if actual != canonical:
                renames.append((actual, canonical))
    for canonical in _COMPOSITE_COMPONENTS_LOWER_BETTER:
        actual = avail_lower.get(canonical.lower())
        if actual is not None:
            matched.append((actual, False))
            if actual != canonical:
                renames.append((actual, canonical))
    return matched, renames


def sepa_composite_baseline(
    split: EvalSplit, mode_a_pool: pd.DataFrame,
) -> Optional[BaselineMetrics]:
    """Run a SEPA composite-score baseline against the entry-only pool.

    Joins canonical SEPA feature columns from `split.df` onto the mode A
    pool (matching on the row index — both come from the same source) and
    re-runs the binary classification + ranker metrics. Returns None if
    no composite components are available in the eval dataframe.
    """
    if mode_a_pool.empty:
        return None

    available_cols = set(split.df.columns)
    matched, renames = _resolve_components(available_cols)
    if not matched:
        logger.warning(
            "SEPA composite baseline: no canonical components present in "
            "eval dataframe; skipping. Available cols hint: %s",
            sorted(c for c in available_cols if "rs" in c.lower())[:5],
        )
        return None

    # Pick the actual df column names; we'll rename to canonical lowercase
    # so the composite builder stays simple.
    actual_cols = [c for c, _ in matched]

    # Build a working frame: join the composite components from split.df
    # onto the pool by (ticker, date). The pool was produced from split.df
    # so both share ticker+date keys.
    join_cols = ["ticker", "date"] + actual_cols
    src = split.df[join_cols].copy()
    if renames:
        src = src.rename(columns=dict(renames))
    src["date"] = pd.to_datetime(src["date"])
    pool = mode_a_pool[["ticker", "date", "label_binary", "label_mfe"]].copy()
    pool["date"] = pd.to_datetime(pool["date"])
    merged = pool.merge(src, on=["ticker", "date"], how="left")

    # After renames, the canonical lowercase names exist in `merged`.
    present_canonical = {
        canonical for _, canonical in renames
    } | {actual for actual, _ in matched if actual not in {a for a, _ in renames}}

    composite, components_used = _build_composite_score(
        merged, available_cols=present_canonical,
    )
    merged["composite_score"] = composite

    if merged["composite_score"].notna().sum() < 10:
        logger.warning(
            "SEPA composite baseline: too few non-null composite rows (%d) — skipping",
            int(merged["composite_score"].notna().sum()),
        )
        return None

    # Classification block
    auc, pr_auc, brier, ll = _classification_block(
        merged["composite_score"], merged["label_binary"],
    )
    # Ranker block
    ic = _per_day_binary_ic(merged.rename(columns={}), score_col="composite_score")
    top5 = _per_day_top_k_lift(merged, score_col="composite_score", k=5)
    prev = float(merged["label_binary"].mean())

    return BaselineMetrics(
        name=f"sepa_composite[{','.join(components_used)}]",
        n_rows=int(merged["composite_score"].notna().sum()),
        auc=auc, pr_auc=pr_auc, brier=brier, log_loss=ll,
        binary_ic_mean=ic, top5_lift=top5,
        prevalence=prev,
    )


def model_metrics_for_comparison(
    split: EvalSplit, mode_a_pool: pd.DataFrame,
) -> BaselineMetrics:
    """Same metric block as the SEPA baseline, computed on the model's
    `pred_proba`. Used to populate the side-by-side comparison table.
    """
    pool = mode_a_pool.copy()
    auc, pr_auc, brier, ll = _classification_block(
        pool["pred_proba"], pool["label_binary"],
    )
    ic = _per_day_binary_ic(pool, score_col="pred_proba")
    top5 = _per_day_top_k_lift(pool, score_col="pred_proba", k=5)
    return BaselineMetrics(
        name=f"model[{split.meta.get('model_id', 'model')}]",
        n_rows=int(pool["pred_proba"].notna().sum()),
        auc=auc, pr_auc=pr_auc, brier=brier, log_loss=ll,
        binary_ic_mean=ic, top5_lift=top5,
        prevalence=float(pool["label_binary"].mean()),
    )


def baseline_delta(model: BaselineMetrics,
                   baseline: BaselineMetrics) -> dict[str, float]:
    """Model − baseline per metric. Returns a comparable dict for the report."""
    return {
        "delta_auc": model.auc - baseline.auc
            if not (np.isnan(model.auc) or np.isnan(baseline.auc)) else float("nan"),
        "delta_pr_auc": model.pr_auc - baseline.pr_auc
            if not (np.isnan(model.pr_auc) or np.isnan(baseline.pr_auc)) else float("nan"),
        "delta_brier": baseline.brier - model.brier
            if not (np.isnan(model.brier) or np.isnan(baseline.brier)) else float("nan"),
        "delta_binary_ic": model.binary_ic_mean - baseline.binary_ic_mean
            if not (np.isnan(model.binary_ic_mean) or np.isnan(baseline.binary_ic_mean)) else float("nan"),
        "delta_top5_lift": model.top5_lift - baseline.top5_lift
            if not (np.isnan(model.top5_lift) or np.isnan(baseline.top5_lift)) else float("nan"),
    }
