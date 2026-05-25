"""Section D — ranker performance (stateful pool).

Split into D-binary (rank by binary home-run label) and D-magnitude (rank by
realised mfe_pct). Each half computes the same family of metrics:

  - per-day Spearman IC (mean, median, t-stat, n_days)
  - top-K lift across K ∈ {1, 3, 5, 10}
  - decile profile (mean / median / 90th-pct of target per decile of P)
  - tail recall (top-1% realised → model's top decile of P)
  - top-decile vs bottom-decile ratio + absolute floor (binary half)

Run twice — once over the entry-only Mode A pool (gates apply here), once
over the stateful Mode B pool (reported, no gates).

Per the framework's §6 R1 / §6 R2, all metrics are also returned per (mode,
target) so the verdict matrix can consume D_binary and D_magnitude as
independent dimensions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from ..data_loader import EvalSplit
from ..rubric import GateEntry, MetricEntry, SectionResult, rubric_score

logger = logging.getLogger(__name__)

TOP_K_VALUES = (1, 3, 5, 10)
TAIL_TOP_PCT = 0.01    # top-1% by realised target
TAIL_DECILE = 0.9      # model's top decile of P


@dataclass(frozen=True)
class RankerMetrics:
    """Container for one (mode, target) pass through the metric family."""
    mode: str               # 'A' (entry) or 'B' (stateful)
    target: str             # 'binary' or 'magnitude'
    n_rows: int
    n_days: int
    ic_mean: float
    ic_median: float
    ic_std: float
    ic_t_stat: float
    top_k_lift: dict[int, float]
    decile_profile: list[dict]
    tail_recall: float
    top_decile_vs_bottom: float
    top_decile_mean: float
    pool_mean: float

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "target": self.target,
            "n_rows": self.n_rows,
            "n_days": self.n_days,
            "ic_mean": self.ic_mean,
            "ic_median": self.ic_median,
            "ic_std": self.ic_std,
            "ic_t_stat": self.ic_t_stat,
            "top_k_lift": {str(k): v for k, v in self.top_k_lift.items()},
            "decile_profile": self.decile_profile,
            "tail_recall": self.tail_recall,
            "top_decile_vs_bottom": self.top_decile_vs_bottom,
            "top_decile_mean": self.top_decile_mean,
            "pool_mean": self.pool_mean,
        }


def _per_day_ic(pool: pd.DataFrame, target_col: str) -> tuple[float, float, float, float, int]:
    """Spearman IC of pred_proba vs target_col within each date.

    Days with < 2 distinct values in either series produce NaN and are dropped.
    Returns (mean, median, std, t_stat, n_days). t_stat is mean / (std / sqrt(n)).
    """
    if pool.empty or "date" not in pool.columns:
        return float("nan"), float("nan"), float("nan"), float("nan"), 0

    def _safe_ic(g: pd.DataFrame) -> float:
        if len(g) < 2:
            return np.nan
        x = g["pred_proba"].to_numpy(dtype=float)
        y = pd.to_numeric(g[target_col], errors="coerce").to_numpy(dtype=float)
        m = ~(np.isnan(x) | np.isnan(y))
        if m.sum() < 2:
            return np.nan
        if np.unique(x[m]).size < 2 or np.unique(y[m]).size < 2:
            return np.nan
        return pd.Series(x[m]).corr(pd.Series(y[m]), method="spearman")

    daily = pool.groupby("date", sort=False).apply(_safe_ic, include_groups=False)
    daily = pd.to_numeric(daily, errors="coerce").dropna()
    n = int(len(daily))
    if n == 0:
        return float("nan"), float("nan"), float("nan"), float("nan"), 0
    mean = float(daily.mean())
    median = float(daily.median())
    std = float(daily.std(ddof=1)) if n >= 2 else float("nan")
    if not np.isnan(std) and std > 0:
        t = mean / (std / np.sqrt(n))
    elif not np.isnan(std) and std == 0:
        # Zero within-fold variance + non-zero mean = perfectly consistent
        # signal. The t-stat is undefined as a ratio but the practical
        # interpretation is "signal exists with no noise" — return +/-inf
        # matching the sign of the mean so gates that require t > 2 pass.
        if mean > 0:
            t = float("inf")
        elif mean < 0:
            t = float("-inf")
        else:
            t = float("nan")
    else:
        t = float("nan")
    return mean, median, std, t, n


def _top_k_lift(pool: pd.DataFrame, target_col: str, k: int) -> float:
    """Per-day average of (mean of top-K target) / (mean of all target).

    Computed per-day to match deployment semantics; then averaged across days.
    """
    if pool.empty:
        return float("nan")

    def _per_day(g: pd.DataFrame) -> float:
        g = g.dropna(subset=["pred_proba", target_col])
        if len(g) == 0:
            return np.nan
        pool_mean = g[target_col].mean()
        if not pool_mean or pool_mean == 0 or np.isnan(pool_mean):
            return np.nan
        top = g.nlargest(k, "pred_proba")
        top_mean = top[target_col].mean()
        if np.isnan(top_mean):
            return np.nan
        return float(top_mean / pool_mean)

    per_day = pool.groupby("date", sort=False).apply(_per_day, include_groups=False)
    per_day = pd.to_numeric(per_day, errors="coerce").dropna()
    if per_day.empty:
        return float("nan")
    return float(per_day.mean())


def _decile_profile(pool: pd.DataFrame, target_col: str) -> list[dict]:
    """Mean/median/90th-percentile of target per decile of pred_proba (pooled)."""
    df = pool.dropna(subset=["pred_proba", target_col]).copy()
    if len(df) < 10:
        return []
    try:
        df["decile"] = pd.qcut(df["pred_proba"], 10, labels=False, duplicates="drop")
    except ValueError:
        return []
    rows = []
    for d, sub in df.groupby("decile", sort=True, observed=True):
        if pd.isna(d):
            continue
        target = pd.to_numeric(sub[target_col], errors="coerce")
        target = target.dropna()
        if target.empty:
            continue
        rows.append({
            "decile": int(d) + 1,  # 1..10 reads better than 0..9
            "n": int(len(target)),
            "p_min": float(sub["pred_proba"].min()),
            "p_max": float(sub["pred_proba"].max()),
            "mean": float(target.mean()),
            "median": float(target.median()),
            "p90": float(target.quantile(0.9)),
        })
    return rows


def _tail_recall(pool: pd.DataFrame, target_col: str,
                 top_pct: float = TAIL_TOP_PCT,
                 decile_cut: float = TAIL_DECILE) -> float:
    """Fraction of realised top-`top_pct` target rows that the model placed in
    its top (1 - decile_cut) decile of pred_proba."""
    df = pool.dropna(subset=["pred_proba", target_col])
    if len(df) < int(1 / top_pct) + 10:
        return float("nan")
    target = pd.to_numeric(df[target_col], errors="coerce")
    df = df.assign(_t=target).dropna(subset=["_t"])
    if df.empty:
        return float("nan")
    target_thr = df["_t"].quantile(1 - top_pct)
    p_thr = df["pred_proba"].quantile(decile_cut)
    realised_top = df["_t"] >= target_thr
    model_top = df["pred_proba"] >= p_thr
    if realised_top.sum() == 0:
        return float("nan")
    return float((realised_top & model_top).sum() / realised_top.sum())


def _top_vs_bottom_decile(pool: pd.DataFrame, target_col: str) -> tuple[float, float, float]:
    """Returns (ratio = top/bottom, top_mean, bottom_mean). NaN-safe.

    If bottom decile mean is zero we return inf for the ratio so the gate
    can still surface "top decile clearly different from zero" via the
    absolute-floor check.
    """
    df = pool.dropna(subset=["pred_proba", target_col]).copy()
    if len(df) < 10:
        return float("nan"), float("nan"), float("nan")
    try:
        df["decile"] = pd.qcut(df["pred_proba"], 10, labels=False, duplicates="drop")
    except ValueError:
        return float("nan"), float("nan"), float("nan")
    top = df[df["decile"] == df["decile"].max()][target_col]
    bot = df[df["decile"] == df["decile"].min()][target_col]
    top = pd.to_numeric(top, errors="coerce").dropna()
    bot = pd.to_numeric(bot, errors="coerce").dropna()
    if top.empty or bot.empty:
        return float("nan"), float("nan"), float("nan")
    top_mean = float(top.mean())
    bot_mean = float(bot.mean())
    if bot_mean == 0:
        ratio = float("inf") if top_mean > 0 else float("nan")
    else:
        ratio = top_mean / bot_mean
    return ratio, top_mean, bot_mean


def _compute_for_pool(pool: pd.DataFrame, mode: str, target_col: str,
                      target_label: str) -> Optional[RankerMetrics]:
    """Single (mode, target) metric pass."""
    if pool.empty or target_col not in pool.columns:
        return None
    df = pool.dropna(subset=["pred_proba", target_col])
    if df.empty:
        return None

    ic_mean, ic_med, ic_std, ic_t, n_days = _per_day_ic(df, target_col)
    top_k = {k: _top_k_lift(df, target_col, k) for k in TOP_K_VALUES}
    decile_profile = _decile_profile(df, target_col)
    tail_recall = _tail_recall(df, target_col)
    ratio, top_mean, _ = _top_vs_bottom_decile(df, target_col)
    pool_mean = float(pd.to_numeric(df[target_col], errors="coerce").mean())

    return RankerMetrics(
        mode=mode,
        target=target_label,
        n_rows=int(len(df)),
        n_days=n_days,
        ic_mean=ic_mean,
        ic_median=ic_med,
        ic_std=ic_std,
        ic_t_stat=ic_t,
        top_k_lift=top_k,
        decile_profile=decile_profile,
        tail_recall=tail_recall,
        top_decile_vs_bottom=ratio,
        top_decile_mean=top_mean,
        pool_mean=pool_mean,
    )


def _add_binary_gates(section: SectionResult, mode_a: RankerMetrics,
                      prevalence: float) -> None:
    """D-gate-1..3 — applied on Mode A pool only."""
    ic_ok = (
        not np.isnan(mode_a.ic_median) and mode_a.ic_median > 0
        and not np.isnan(mode_a.ic_t_stat) and mode_a.ic_t_stat > 2.0
    )
    section.gates.append(GateEntry(
        name="D1_binary_ic",
        status="pass" if ic_ok else "fail",
        value=mode_a.ic_median if not np.isnan(mode_a.ic_median) else None,
        threshold=0.0,
        detail=(
            f"median daily binary IC={mode_a.ic_median:.4f}, "
            f"t-stat={mode_a.ic_t_stat:.2f} (need > 0 with t > 2)"
        ),
        blocking=True,
    ))
    top5 = mode_a.top_k_lift.get(5, float("nan"))
    section.gates.append(GateEntry(
        name="D2_top5_hit_lift",
        status="pass" if (not np.isnan(top5) and top5 > 1.5) else "fail",
        value=float(top5) if not np.isnan(top5) else None,
        threshold=1.5,
        detail=f"top-5 hit lift={top5:.3f}× (need > 1.5×)",
        blocking=True,
    ))
    # D-gate-3: top decile vs bottom AND absolute floor 1.5× prevalence
    ratio_ok = not np.isnan(mode_a.top_decile_vs_bottom) and mode_a.top_decile_vs_bottom >= 2.0
    floor_ok = (
        not np.isnan(mode_a.top_decile_mean)
        and prevalence > 0
        and mode_a.top_decile_mean >= 1.5 * prevalence
    )
    section.gates.append(GateEntry(
        name="D3_top_vs_bottom_decile",
        status="pass" if (ratio_ok and floor_ok) else "fail",
        value=float(mode_a.top_decile_vs_bottom)
            if not np.isnan(mode_a.top_decile_vs_bottom) and np.isfinite(mode_a.top_decile_vs_bottom) else None,
        threshold=2.0,
        detail=(
            f"top decile mean={mode_a.top_decile_mean:.4f}, "
            f"top/bot ratio={mode_a.top_decile_vs_bottom:.2f}× "
            f"(need ≥ 2× ratio AND top ≥ 1.5×prevalence={1.5*prevalence:.4f})"
        ),
        blocking=True,
    ))


def _add_magnitude_gates(section: SectionResult, mode_a: RankerMetrics) -> None:
    """D-gate-4..6 — applied on Mode A pool only."""
    ic_ok = (
        not np.isnan(mode_a.ic_median) and mode_a.ic_median > 0
        and not np.isnan(mode_a.ic_t_stat) and mode_a.ic_t_stat > 2.0
    )
    section.gates.append(GateEntry(
        name="D4_magnitude_ic",
        status="pass" if ic_ok else "fail",
        value=mode_a.ic_median if not np.isnan(mode_a.ic_median) else None,
        threshold=0.0,
        detail=(
            f"median daily MFE-IC={mode_a.ic_median:.4f}, "
            f"t-stat={mode_a.ic_t_stat:.2f} (need > 0 with t > 2)"
        ),
        blocking=True,
    ))
    top5 = mode_a.top_k_lift.get(5, float("nan"))
    section.gates.append(GateEntry(
        name="D5_top5_magnitude_lift",
        status="pass" if (not np.isnan(top5) and top5 > 1.5) else "fail",
        value=float(top5) if not np.isnan(top5) else None,
        threshold=1.5,
        detail=f"top-5 magnitude lift={top5:.3f}× (need > 1.5×)",
        blocking=True,
    ))
    # D-gate-6: warning gate, threshold 0.20
    tr = mode_a.tail_recall
    section.gates.append(GateEntry(
        name="D6_tail_recall",
        status="pass" if (not np.isnan(tr) and tr >= 0.20) else "warn",
        value=float(tr) if not np.isnan(tr) else None,
        threshold=0.20,
        detail=f"tail recall (top-1% MFE → top decile P)={tr:.3f} (warn if < 0.20)",
        blocking=False,
    ))


def _aggregate_d_score(binary_a: Optional[RankerMetrics],
                       magnitude_a: Optional[RankerMetrics]) -> dict[str, int]:
    """Return {'D_binary': band, 'D_magnitude': band} per framework rubric.

    Bands per docs/proposals/model_card_framework_2026_05_25.md §3 (Section D).
    Each half scored against the weakest of (median IC, top-5 lift, tail/decile).
    """
    out: dict[str, int] = {}
    if binary_a is not None:
        ic = binary_a.ic_median
        top5 = binary_a.top_k_lift.get(5, float("nan"))
        # decile monotonicity proxy: top-vs-bottom ratio
        ratio = binary_a.top_decile_vs_bottom
        ic_score = rubric_score(ic if not np.isnan(ic) else 0.0, [0.0, 0.03, 0.08])
        top5_score = rubric_score(top5 if not np.isnan(top5) else 0.0, [1.2, 1.5, 2.5])
        # +inf ⇒ perfect separation (bottom decile mean is zero); treat as Strong.
        if np.isnan(ratio):
            decile_score = 0
        elif np.isinf(ratio):
            decile_score = 3
        else:
            decile_score = rubric_score(ratio, [1.2, 2.0, 4.0])
        out["D_binary"] = int(min(ic_score, top5_score, decile_score))
    if magnitude_a is not None:
        ic = magnitude_a.ic_median
        top5 = magnitude_a.top_k_lift.get(5, float("nan"))
        tr = magnitude_a.tail_recall
        ic_score = rubric_score(ic if not np.isnan(ic) else 0.0, [0.0, 0.03, 0.08])
        top5_score = rubric_score(top5 if not np.isnan(top5) else 0.0, [1.2, 1.5, 2.5])
        tr_score = rubric_score(tr if not np.isnan(tr) else 0.0, [0.10, 0.20, 0.35])
        out["D_magnitude"] = int(min(ic_score, top5_score, tr_score))
    return out


def _metrics_for_summary(prefix: str, m: RankerMetrics) -> list[MetricEntry]:
    return [
        MetricEntry(f"{prefix}_ic_mean", m.ic_mean,
                    f"mean of daily Spearman IC across {m.n_days} days"),
        MetricEntry(f"{prefix}_ic_median", m.ic_median,
                    "median of daily IC (less sensitive to outliers)"),
        MetricEntry(f"{prefix}_ic_t_stat", m.ic_t_stat,
                    "IC mean / (IC std / √N_days); > 2 = significant"),
        MetricEntry(f"{prefix}_top5_lift", m.top_k_lift.get(5, float("nan")),
                    "per-day mean of (top-5 mean target) / (pool mean target)"),
        MetricEntry(f"{prefix}_top10_lift", m.top_k_lift.get(10, float("nan")),
                    "per-day mean of (top-10 mean target) / (pool mean target)"),
        MetricEntry(f"{prefix}_tail_recall", m.tail_recall,
                    "of realised top-1%, fraction model placed in top decile"),
        MetricEntry(f"{prefix}_top_vs_bot_decile", m.top_decile_vs_bottom
                    if np.isfinite(m.top_decile_vs_bottom) else float("nan"),
                    "top decile mean / bottom decile mean"),
    ]


def run_section_d(
    split: EvalSplit,
    mode_a_pool: pd.DataFrame,
    mode_b_pool: Optional[pd.DataFrame] = None,
) -> SectionResult:
    """Build Section D.

    `mode_a_pool` must have columns: ticker, date, pred_proba, label_binary,
    label_mfe (entry-only ledger). `mode_b_pool` is optional — when present,
    reported alongside Mode A but does not drive gates.
    """
    section = SectionResult(
        name="D",
        title="Ranker performance (D-binary + D-magnitude)",
        scored=True,
    )

    # Mode A — gates apply here.
    binary_a = _compute_for_pool(mode_a_pool, mode="A",
                                 target_col="label_binary", target_label="binary")
    magnitude_a = _compute_for_pool(mode_a_pool, mode="A",
                                    target_col="label_mfe", target_label="magnitude")

    binary_b = magnitude_b = None
    if mode_b_pool is not None and not mode_b_pool.empty:
        # Mode B's outcome columns are sparse (only rows that became entries).
        binary_b = _compute_for_pool(mode_b_pool, mode="B",
                                     target_col="label_binary", target_label="binary")
        magnitude_b = _compute_for_pool(mode_b_pool, mode="B",
                                        target_col="label_mfe", target_label="magnitude")

    if binary_a is None or magnitude_a is None:
        section.detail = (
            "Section D could not be computed — Mode A pool empty after "
            "filtering. Check trend_ok / date range."
        )
        section.gates.append(GateEntry(
            name="D_pool_available",
            status="fail",
            value=None, threshold=None,
            detail="Mode A pool is empty; no ranker metrics computable",
            blocking=True,
        ))
        return section

    # Metrics (one set of headline numbers per half, Mode A).
    section.metrics.extend(_metrics_for_summary("Abin", binary_a))
    section.metrics.extend(_metrics_for_summary("Amag", magnitude_a))
    if binary_b is not None:
        section.metrics.extend(_metrics_for_summary("Bbin", binary_b))
    if magnitude_b is not None:
        section.metrics.extend(_metrics_for_summary("Bmag", magnitude_b))

    # Rubric: split into D_binary and D_magnitude
    band_map = _aggregate_d_score(binary_a, magnitude_a)
    section.rubric_scores.update(band_map)

    # Gates
    _add_binary_gates(section, binary_a, prevalence=split.prevalence)
    _add_magnitude_gates(section, magnitude_a)

    # Tables: decile profiles for binary and magnitude (Mode A)
    section.tables["decile_binary_mode_a"] = binary_a.decile_profile
    section.tables["decile_magnitude_mode_a"] = magnitude_a.decile_profile
    if binary_b is not None:
        section.tables["decile_binary_mode_b"] = binary_b.decile_profile
    if magnitude_b is not None:
        section.tables["decile_magnitude_mode_b"] = magnitude_b.decile_profile

    # Summary table: side-by-side mode comparison
    summary_rows = []
    for label, m in [("A_binary", binary_a), ("A_magnitude", magnitude_a),
                     ("B_binary", binary_b), ("B_magnitude", magnitude_b)]:
        if m is None:
            continue
        summary_rows.append({
            "view": label,
            "n_rows": m.n_rows,
            "n_days": m.n_days,
            "ic_median": m.ic_median,
            "ic_t_stat": m.ic_t_stat,
            "top1_lift": m.top_k_lift.get(1, float("nan")),
            "top5_lift": m.top_k_lift.get(5, float("nan")),
            "top10_lift": m.top_k_lift.get(10, float("nan")),
            "tail_recall": m.tail_recall,
            "top_vs_bot_decile": m.top_decile_vs_bottom
                if np.isfinite(m.top_decile_vs_bottom) else float("nan"),
        })
    section.tables["summary"] = summary_rows

    # Detail line
    section.detail = (
        f"Mode A (entry-only): n={binary_a.n_rows} across {binary_a.n_days} days. "
        f"Binary IC median={binary_a.ic_median:.4f} (t={binary_a.ic_t_stat:.2f}), "
        f"MFE IC median={magnitude_a.ic_median:.4f} (t={magnitude_a.ic_t_stat:.2f}). "
        f"Mode B: " + (
            f"n={binary_b.n_rows if binary_b else 0} pool rows."
            if binary_b is not None else "not built (skip mode_b)."
        )
    )
    return section
