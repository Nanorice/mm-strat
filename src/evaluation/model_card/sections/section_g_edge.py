"""Section G — edge existence (statistical).

Asks "is the model's apparent skill distinguishable from luck?" via two
classification-metric-level analyses on the Mode A pool:

  - G1 Permutation null on AUC, binary IC, top-5 hit lift. Labels are
    shuffled (per-day for IC / top-K which are per-day aggregates; globally
    for AUC which is pool-level) and metrics are recomputed; we report the
    observed metric's percentile in the null distribution and the empirical
    p-value (one-sided: observed ≥ null).

  - G2 Block bootstrap CI on AUC, binary IC, top-5 hit lift. Dates are
    block-resampled (default 60d, matching the existing trade-level
    bootstrap convention) and metrics are recomputed; the 5/95 CI is
    reported.

  - G3 Sample-size adequacy — count of label=1 events in the eval window.

Existing `permutation_null.py` and `bootstrap.py` operate at the
*backtest-trade* level (signals → backtest engine → Sharpe). Here we
operate directly on (y_true, y_prob) pairs paired with dates, so the
shuffle / resample primitives are reimplemented locally.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from ..rubric import GateEntry, MetricEntry, SectionResult, rubric_score

logger = logging.getLogger(__name__)

# Defaults. The framework doc calls 1000 permutations "deep"; the plan's
# performance budget is < 90s total build time. We default to 500 which is
# adequate for percentile resolution at the 1% level and keeps run time
# manageable for typical eval windows (~38K rows × 500 permutations of
# AUC ≈ a few seconds total).
DEFAULT_N_PERMUTATIONS = 500
DEFAULT_N_BOOTSTRAP = 500
DEFAULT_BLOCK_SIZE_DAYS = 60
TOP_K = 5

# Adequacy thresholds — per framework §G3.
ADEQUACY_MIN_POSITIVES = 100
ADEQUACY_NOISY_BELOW = 50
ADEQUACY_STRONG_ABOVE = 500


@dataclass(frozen=True)
class MetricStats:
    name: str
    observed: float
    null_median: float
    null_percentile: float          # 0-100
    p_value: float                  # one-sided P(null >= observed)
    ci_lo: float
    ci_hi: float
    bootstrap_median: float
    baseline: float                 # AUC: 0.5; IC: 0.0; top5 lift: 1.0


def _safe_auc(y: np.ndarray, p: np.ndarray) -> float:
    if y.sum() == 0 or y.sum() == len(y):
        return float("nan")
    try:
        return float(roc_auc_score(y, p))
    except ValueError:
        return float("nan")


def _per_day_binary_ic(pool: pd.DataFrame) -> float:
    """Mean across dates of within-date Spearman IC of pred_proba vs label_binary.

    Spearman = Pearson on within-day ranks. Vectorized (grouped rank + grouped
    moment sums) rather than a per-day `groupby.apply`, which is ~30x slower and
    made Section G's 500-permutation loop run for tens of minutes.
    """
    g = pool[["date", "pred_proba", "label_binary"]].dropna()
    if g.empty:
        return float("nan")
    x = g.groupby("date", sort=False)["pred_proba"].rank()
    y = g.groupby("date", sort=False)["label_binary"].rank()
    d = pd.DataFrame({"date": g["date"].to_numpy(), "x": x.to_numpy(), "y": y.to_numpy()})
    grp = d.groupby("date", sort=False)
    cx = d["x"] - grp["x"].transform("mean")
    cy = d["y"] - grp["y"].transform("mean")
    d = d.assign(cxy=cx * cy, cx2=cx * cx, cy2=cy * cy)
    agg = d.groupby("date", sort=False).agg(
        num=("cxy", "sum"), dx=("cx2", "sum"), dy=("cy2", "sum"), n=("x", "size"),
    )
    denom = np.sqrt(agg["dx"] * agg["dy"]).replace(0, np.nan)
    ic = (agg["num"] / denom)[agg["n"] >= 2].dropna()
    return float(ic.mean()) if len(ic) else float("nan")


def _per_day_top_k_lift(pool: pd.DataFrame, k: int = TOP_K) -> float:
    """Mean across dates of (top-K mean label_binary) / (pool mean label_binary).

    Vectorized: `rank(method="first", ascending=False) <= k` reproduces
    `nlargest(k, pred_proba)`'s tie-breaking (first-in-order) without a per-day
    `groupby.apply`.
    """
    g = pool[["date", "pred_proba", "label_binary"]].dropna()
    if g.empty:
        return float("nan")
    pool_mean = g.groupby("date", sort=False)["label_binary"].transform("mean")
    rnk = g.groupby("date", sort=False)["pred_proba"].rank(method="first", ascending=False)
    g = g.assign(pm=pool_mean.to_numpy(), rnk=rnk.to_numpy())
    g = g[g["pm"] > 0]
    if g.empty:
        return float("nan")
    top_mean = g[g["rnk"] <= k].groupby("date", sort=False)["label_binary"].mean()
    pm = g.groupby("date", sort=False)["pm"].first()
    lift = (top_mean / pm).dropna()
    return float(lift.mean()) if len(lift) else float("nan")


def _shuffled_pool_global(pool: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Shuffle label_binary across the full pool (breaks ticker↔label link entirely).

    Used for AUC where the metric is pool-level.
    """
    out = pool.copy()
    perm = rng.permutation(len(out))
    out["label_binary"] = out["label_binary"].to_numpy()[perm]
    return out


def _shuffled_pool_per_day(pool: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Shuffle label_binary within each date (preserves per-day prevalence).

    Used for IC and top-K lift which are computed per-day.
    """
    out = pool.copy()
    labels = out["label_binary"].to_numpy().copy()
    for _, idxs in out.groupby("date", sort=False).groups.items():
        idx_arr = np.asarray(idxs)
        if len(idx_arr) <= 1:
            continue
        sub = labels[idx_arr]
        rng.shuffle(sub)
        labels[idx_arr] = sub
    out["label_binary"] = labels
    return out


def _permutation_null(
    pool: pd.DataFrame,
    metric_fn: Callable[[pd.DataFrame], float],
    shuffle_fn: Callable[[pd.DataFrame, np.random.Generator], pd.DataFrame],
    n_permutations: int,
    seed: int,
) -> tuple[float, np.ndarray]:
    """Returns (observed, null_array). Null array drops NaN replicates."""
    observed = float(metric_fn(pool))
    rng = np.random.default_rng(seed)
    null = np.empty(n_permutations, dtype=float)
    for i in range(n_permutations):
        shuffled = shuffle_fn(pool, rng)
        try:
            null[i] = float(metric_fn(shuffled))
        except Exception as e:  # pragma: no cover
            logger.debug("permutation %d failed: %s", i, e)
            null[i] = float("nan")
    null = null[~np.isnan(null)]
    return observed, null


def _percentile_and_pvalue(observed: float, null: np.ndarray) -> tuple[float, float]:
    if null.size == 0 or np.isnan(observed):
        return float("nan"), float("nan")
    # Percentile = fraction of null strictly < observed (0-100).
    percentile = float((null < observed).mean() * 100.0)
    # One-sided p-value: P(null >= observed).
    p_value = float((null >= observed).mean())
    return percentile, p_value


def _make_date_blocks(
    dates: pd.Series, block_size_days: int,
) -> list[np.ndarray]:
    """Group positional indices of the *sorted* pool into blocks of contiguous
    dates spanning `block_size_days` calendar days each.

    Returns a list of int-arrays; each array holds positional indices into the
    date-sorted pool for that block.
    """
    d = pd.to_datetime(dates).reset_index(drop=True)
    if d.empty:
        return []
    min_date = d.min()
    day_offset = (d - min_date).dt.days.to_numpy()
    block_id = day_offset // block_size_days
    order = np.argsort(block_id, kind="stable")
    sorted_block_ids = block_id[order]
    splits = np.where(np.diff(sorted_block_ids) != 0)[0] + 1
    return [arr for arr in np.split(order, splits) if len(arr) > 0]


def _block_bootstrap(
    pool: pd.DataFrame,
    metric_fn: Callable[[pd.DataFrame], float],
    n_iterations: int,
    block_size_days: int,
    seed: int,
    ci_lo_pct: float = 5.0,
    ci_hi_pct: float = 95.0,
) -> tuple[float, float, float, float, int]:
    """Block-bootstrap a metric over `pool`.

    Resamples blocks of contiguous dates (length = block_size_days). Returns
    (observed, ci_lo, ci_hi, median, n_blocks).
    """
    sorted_pool = pool.sort_values("date").reset_index(drop=True)
    observed = float(metric_fn(sorted_pool))
    blocks = _make_date_blocks(sorted_pool["date"], block_size_days)
    n_blocks = len(blocks)
    if n_blocks == 0:
        return observed, float("nan"), float("nan"), float("nan"), 0
    n_rows = len(sorted_pool)
    rng = np.random.default_rng(seed)
    replicates = np.empty(n_iterations, dtype=float)
    for i in range(n_iterations):
        pick = rng.integers(0, n_blocks, size=n_blocks)
        idx_parts = [blocks[k] for k in pick]
        idx = np.concatenate(idx_parts) if idx_parts else np.empty(0, dtype=int)
        if len(idx) > n_rows:
            idx = idx[:n_rows]
        try:
            replicates[i] = float(metric_fn(sorted_pool.iloc[idx]))
        except Exception as e:  # pragma: no cover
            logger.debug("bootstrap %d failed: %s", i, e)
            replicates[i] = float("nan")
    valid = replicates[~np.isnan(replicates)]
    if valid.size == 0:
        return observed, float("nan"), float("nan"), float("nan"), n_blocks
    ci_lo = float(np.percentile(valid, ci_lo_pct))
    ci_hi = float(np.percentile(valid, ci_hi_pct))
    median = float(np.median(valid))
    return observed, ci_lo, ci_hi, median, n_blocks


def _metric_auc(pool: pd.DataFrame) -> float:
    y = pool["label_binary"].to_numpy(dtype=float)
    p = pool["pred_proba"].to_numpy(dtype=float)
    m = ~(np.isnan(y) | np.isnan(p))
    if m.sum() < 2:
        return float("nan")
    return _safe_auc(y[m].astype(int), p[m])


def _metric_ic(pool: pd.DataFrame) -> float:
    return _per_day_binary_ic(pool)


def _metric_top5(pool: pd.DataFrame) -> float:
    return _per_day_top_k_lift(pool, k=TOP_K)


def _rubric_for_percentile(pct: float) -> int:
    """Per framework §G rubric (permutation percentile column).

    < 90  -> 0 (Poor)
    90-95 -> 1 (Marginal)
    95-99 -> 2 (Good)
    > 99  -> 3 (Strong)
    """
    if pct is None or np.isnan(pct):
        return 0
    if pct >= 99.0:
        return 3
    if pct >= 95.0:
        return 2
    if pct >= 90.0:
        return 1
    return 0


def _rubric_for_ci(ci_lo: float, baseline: float, scale: float) -> int:
    """Per framework §G rubric (bootstrap CI column).

    CI lower bound vs baseline (random):
      includes baseline       -> 0
      within 10% of baseline  -> 1
      clearly above baseline  -> 2
      tight + well above      -> 3

    `scale` controls what "10%" means for IC (which has very different
    natural scale than AUC). We use `scale * 0.1` as the band edge.
    """
    if ci_lo is None or np.isnan(ci_lo):
        return 0
    margin = ci_lo - baseline
    if margin <= 0:
        return 0
    if margin < 0.1 * scale:
        return 1
    if margin < 0.3 * scale:
        return 2
    return 3


def _stats_to_metrics(stats: list[MetricStats]) -> list[MetricEntry]:
    out: list[MetricEntry] = []
    for s in stats:
        out.extend([
            MetricEntry(
                f"{s.name}_observed", s.observed,
                f"observed metric (random baseline = {s.baseline})",
            ),
            MetricEntry(
                f"{s.name}_null_percentile", s.null_percentile,
                "observed metric's rank in permutation null (0-100)",
            ),
            MetricEntry(
                f"{s.name}_p_value", s.p_value,
                "one-sided P(null >= observed)",
            ),
            MetricEntry(
                f"{s.name}_ci_lo", s.ci_lo, "block-bootstrap 5th percentile",
            ),
            MetricEntry(
                f"{s.name}_ci_hi", s.ci_hi, "block-bootstrap 95th percentile",
            ),
        ])
    return out


def _required_cols_present(pool: pd.DataFrame) -> bool:
    needed = {"date", "pred_proba", "label_binary"}
    return needed.issubset(pool.columns)


def run_section_g(
    mode_a_pool: pd.DataFrame,
    *,
    n_permutations: int = DEFAULT_N_PERMUTATIONS,
    n_bootstrap: int = DEFAULT_N_BOOTSTRAP,
    block_size_days: int = DEFAULT_BLOCK_SIZE_DAYS,
    seed: int = 42,
) -> SectionResult:
    """Build Section G from the entry-only Mode A pool.

    The Mode A pool already has `date`, `pred_proba`, `label_binary` per the
    Section D contract; no DB access is needed.
    """
    section = SectionResult(
        name="G",
        title="Edge existence (statistical)",
        scored=True,
    )

    if mode_a_pool is None or mode_a_pool.empty:
        section.detail = "Mode A pool empty — edge tests not computable."
        section.gates.append(GateEntry(
            name="G_pool_available",
            status="fail", value=None, threshold=None,
            detail="empty pool", blocking=True,
        ))
        return section

    if not _required_cols_present(mode_a_pool):
        missing = sorted({"date", "pred_proba", "label_binary"} - set(mode_a_pool.columns))
        section.detail = f"Mode A pool missing required cols: {missing}"
        section.gates.append(GateEntry(
            name="G_pool_available",
            status="fail", value=None, threshold=None,
            detail=f"missing cols {missing}", blocking=True,
        ))
        return section

    pool = mode_a_pool[["date", "pred_proba", "label_binary"]].copy()
    pool = pool.dropna(subset=["pred_proba", "label_binary"])
    # label_binary may be Int64/nullable; coerce to int for AUC.
    pool["label_binary"] = pd.to_numeric(pool["label_binary"], errors="coerce").astype(int)
    pool["date"] = pd.to_datetime(pool["date"])

    n_positives = int(pool["label_binary"].sum())
    n_rows = int(len(pool))
    n_days = int(pool["date"].nunique())

    # G3 — sample-size adequacy
    if n_positives < ADEQUACY_NOISY_BELOW:
        adequacy_score = 0
    elif n_positives < ADEQUACY_MIN_POSITIVES:
        adequacy_score = 1
    elif n_positives < ADEQUACY_STRONG_ABOVE:
        adequacy_score = 2
    else:
        adequacy_score = 3

    if pool["label_binary"].sum() == 0 or pool["label_binary"].sum() == n_rows:
        section.detail = (
            f"Mode A pool has {n_positives}/{n_rows} positives — degenerate "
            f"label set, AUC and IC undefined."
        )
        section.gates.append(GateEntry(
            name="G_degenerate_labels",
            status="fail", value=None, threshold=None,
            detail="all labels identical; null distribution undefined",
            blocking=True,
        ))
        return section

    # Permutation null
    logger.info(
        "Section G: %d permutations, %d bootstrap iters, block_size=%dd, "
        "n_rows=%d, n_positives=%d, n_days=%d",
        n_permutations, n_bootstrap, block_size_days, n_rows, n_positives, n_days,
    )

    obs_auc, null_auc = _permutation_null(
        pool, _metric_auc, _shuffled_pool_global, n_permutations, seed=seed,
    )
    obs_ic, null_ic = _permutation_null(
        pool, _metric_ic, _shuffled_pool_per_day, n_permutations, seed=seed + 1,
    )
    obs_top5, null_top5 = _permutation_null(
        pool, _metric_top5, _shuffled_pool_per_day, n_permutations, seed=seed + 2,
    )

    pct_auc, pval_auc = _percentile_and_pvalue(obs_auc, null_auc)
    pct_ic, pval_ic = _percentile_and_pvalue(obs_ic, null_ic)
    pct_top5, pval_top5 = _percentile_and_pvalue(obs_top5, null_top5)

    # Block bootstrap CIs (using same observed)
    _, ci_lo_auc, ci_hi_auc, med_auc, n_blocks = _block_bootstrap(
        pool, _metric_auc, n_bootstrap, block_size_days, seed=seed + 10,
    )
    _, ci_lo_ic, ci_hi_ic, med_ic, _ = _block_bootstrap(
        pool, _metric_ic, n_bootstrap, block_size_days, seed=seed + 11,
    )
    _, ci_lo_top5, ci_hi_top5, med_top5, _ = _block_bootstrap(
        pool, _metric_top5, n_bootstrap, block_size_days, seed=seed + 12,
    )

    stats = [
        MetricStats(
            name="auc",
            observed=obs_auc, null_median=float(np.median(null_auc)) if null_auc.size else float("nan"),
            null_percentile=pct_auc, p_value=pval_auc,
            ci_lo=ci_lo_auc, ci_hi=ci_hi_auc, bootstrap_median=med_auc,
            baseline=0.5,
        ),
        MetricStats(
            name="ic_binary",
            observed=obs_ic, null_median=float(np.median(null_ic)) if null_ic.size else float("nan"),
            null_percentile=pct_ic, p_value=pval_ic,
            ci_lo=ci_lo_ic, ci_hi=ci_hi_ic, bootstrap_median=med_ic,
            baseline=0.0,
        ),
        MetricStats(
            name="top5_lift",
            observed=obs_top5, null_median=float(np.median(null_top5)) if null_top5.size else float("nan"),
            null_percentile=pct_top5, p_value=pval_top5,
            ci_lo=ci_lo_top5, ci_hi=ci_hi_top5, bootstrap_median=med_top5,
            baseline=1.0,
        ),
    ]

    section.metrics.extend(_stats_to_metrics(stats))
    section.metrics.append(MetricEntry(
        "n_positives_eval", float(n_positives),
        f"positives in eval window (≥ {ADEQUACY_MIN_POSITIVES} = adequate)",
    ))

    # Rubric: take the *best* of the three metrics for the percentile band
    # (gate already requires 2 of 3 above 95th). The CI band uses scales
    # tuned to each metric's natural range.
    perm_scores = {
        "auc": _rubric_for_percentile(pct_auc),
        "ic_binary": _rubric_for_percentile(pct_ic),
        "top5_lift": _rubric_for_percentile(pct_top5),
    }
    ci_scores = {
        "auc": _rubric_for_ci(ci_lo_auc, baseline=0.5, scale=0.5),
        "ic_binary": _rubric_for_ci(ci_lo_ic, baseline=0.0, scale=0.1),
        "top5_lift": _rubric_for_ci(ci_lo_top5, baseline=1.0, scale=1.0),
    }
    section.rubric_scores["permutation_min"] = int(min(perm_scores.values()))
    section.rubric_scores["bootstrap_min"] = int(min(ci_scores.values()))
    section.rubric_scores["sample_adequacy"] = adequacy_score

    # Gates per framework §G:
    #   G-gate-1 (blocking): permutation pct > 95 for >= 2 of 3 metrics
    perm_above_95 = sum(
        1 for v in (pct_auc, pct_ic, pct_top5)
        if not np.isnan(v) and v > 95.0
    )
    section.gates.append(GateEntry(
        name="G1_permutation_null",
        status="pass" if perm_above_95 >= 2 else "fail",
        value=float(perm_above_95), threshold=2.0,
        detail=(
            f"{perm_above_95}/3 of {{AUC, binary-IC, top-5 lift}} sit above the "
            f"95th percentile of their permutation null. "
            f"AUC pct={pct_auc:.1f}, IC pct={pct_ic:.1f}, top5 pct={pct_top5:.1f}"
        ),
        blocking=True,
    ))
    # G-gate-2 (blocking): >= 1 of bootstrap CIs excludes the random baseline
    ci_excludes_baseline = sum(
        1 for s in stats
        if not np.isnan(s.ci_lo) and s.ci_lo > s.baseline
    )
    section.gates.append(GateEntry(
        name="G2_bootstrap_ci_excludes_baseline",
        status="pass" if ci_excludes_baseline >= 1 else "fail",
        value=float(ci_excludes_baseline), threshold=1.0,
        detail=(
            f"{ci_excludes_baseline}/3 metric CIs sit entirely above their random "
            f"baseline (AUC>0.5, IC>0, top5>1.0)"
        ),
        blocking=True,
    ))
    # G-gate-3 (warning): N positives >= 100
    section.gates.append(GateEntry(
        name="G3_sample_adequacy",
        status="pass" if n_positives >= ADEQUACY_MIN_POSITIVES else "warn",
        value=float(n_positives), threshold=float(ADEQUACY_MIN_POSITIVES),
        detail=(
            f"n_positives={n_positives}; "
            f"< {ADEQUACY_NOISY_BELOW} noisy, "
            f"< {ADEQUACY_MIN_POSITIVES} marginal, "
            f"≥ {ADEQUACY_STRONG_ABOVE} strong"
        ),
        blocking=False,
    ))

    # Summary table the report can render directly
    section.tables["summary"] = [
        {
            "metric": s.name,
            "observed": s.observed,
            "baseline": s.baseline,
            "null_median": s.null_median,
            "null_percentile": s.null_percentile,
            "p_value": s.p_value,
            "ci_lo_5pct": s.ci_lo,
            "ci_hi_95pct": s.ci_hi,
            "bootstrap_median": s.bootstrap_median,
            "ci_excludes_baseline": (
                False if np.isnan(s.ci_lo) else (s.ci_lo > s.baseline)
            ),
        }
        for s in stats
    ]

    section.detail = (
        f"n_rows={n_rows} across {n_days} days, n_positives={n_positives}. "
        f"AUC={obs_auc:.4f} (perm pct={pct_auc:.1f}, CI=[{ci_lo_auc:.4f}, {ci_hi_auc:.4f}]). "
        f"Binary IC={obs_ic:.4f} (perm pct={pct_ic:.1f}, CI=[{ci_lo_ic:.4f}, {ci_hi_ic:.4f}]). "
        f"Top-5 lift={obs_top5:.3f}× (perm pct={pct_top5:.1f}, "
        f"CI=[{ci_lo_top5:.3f}, {ci_hi_top5:.3f}])."
    )
    return section
