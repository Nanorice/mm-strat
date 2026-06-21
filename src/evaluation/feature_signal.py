"""Feature signal analysis — the 3 reused functions + target distribution.

Ports model_proto.ipynb cells 42 (IC), 44 (MI), 47/49 (redundancy) exactly,
plus the target-distribution table the user explicitly asked for. Kept as
independent functions so they compose without a wrapper. Plotting is a
delegated concern (EvaluationPlotter), not duplicated here.
"""

import logging
from dataclasses import dataclass
from typing import List, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.feature_selection import mutual_info_classif
from sklearn.preprocessing import LabelEncoder

logger = logging.getLogger(__name__)

IC_LOW_SIGNAL = 0.02       # |IC| below this is flagged low-signal (model_proto cell 49)
IC_MIN_OBS = 100           # min non-null obs per feature (model_proto cell 42)
MI_SAMPLE_N = 20000        # MI sample cap (model_proto cell 44)
MI_SEED = 42
REDUNDANCY_THRESHOLD = 0.80  # model_proto cell 47/49 actual value (not 0.75)
REDUNDANCY_SAMPLE_N = 200_000  # row cap for Spearman corr — population stat, sample suffices

DEFAULT_CLASS_NAMES = ("Dud", "Noise", "Solid", "Elite")

# Forward-return horizons present in v_d2_training (fractional: 1.0 == 100%).
RETURN_HORIZONS = ("return_1d", "return_5d", "return_20d", "return_60d")


@dataclass
class TargetDist:
    counts: pd.Series
    proportions: pd.Series
    imbalance_ratio: float       # max class count / min class count


def target_distribution(
    y: pd.Series,
    class_names: Sequence[str] = DEFAULT_CLASS_NAMES,
) -> TargetDist:
    """Class counts, proportions, imbalance ratio. trades-mode only."""
    counts = y.value_counts().sort_index()
    counts.index = [
        class_names[i] if i < len(class_names) else str(i) for i in counts.index
    ]
    proportions = counts / counts.sum()
    imbalance = float(counts.max() / counts.min()) if counts.min() > 0 else float("inf")
    return TargetDist(
        counts=counts,
        proportions=proportions,
        imbalance_ratio=imbalance,
    )


def return_horizon_stats(
    df: pd.DataFrame,
    horizons: Sequence[str] = RETURN_HORIZONS,
) -> pd.DataFrame:
    """Per-horizon forward-return summary (max/min/median/avg + n).

    Columns are fractional (1.0 == 100%); reported as percent for readability.
    Missing horizon columns are skipped, not errored — the view schema evolves.
    """
    rows = []
    for h in horizons:
        if h not in df.columns:
            continue
        s = pd.to_numeric(df[h], errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        ).dropna()
        if s.empty:
            continue
        rows.append({
            "horizon": h,
            "n": int(s.size),
            "avg_pct": float(s.mean() * 100.0),
            "median_pct": float(s.median() * 100.0),
            "min_pct": float(s.min() * 100.0),
            "max_pct": float(s.max() * 100.0),
            "std_pct": float(s.std() * 100.0),
        })
    return pd.DataFrame(rows)


def weekly_ticker_activity(
    df: pd.DataFrame,
    entry_col: str = "entry_date",
    exit_col: str = "sepa_exit_date",
    trade_key: str = "trade_id",
) -> pd.DataFrame:
    """Per-ISO-week SEPA activity, derived from trade spans.

    v_d2_training is one row per trade (v_d1_candidates Step 4 keeps only the
    entry_date row), so daily activity cannot be counted from `date` — it must
    be reconstructed from each trade's [entry_date, sepa_exit_date] span.

    new_additions  : distinct trades whose entry_date falls in the week.
    avg_daily_active: mean # of trades whose span covers a given business day,
                      averaged over the business days in that week.

    Returns one row per week (Fri-ending) with both series so the caller can
    draw a bar (additions) + line (avg active) combo chart.
    """
    if entry_col not in df.columns:
        return pd.DataFrame()

    key = trade_key if trade_key in df.columns else entry_col
    t = df[[c for c in {key, entry_col, exit_col} if c in df.columns]].copy()
    t = t.drop_duplicates(subset=[key])
    t[entry_col] = pd.to_datetime(t[entry_col])

    t["wk"] = t[entry_col].dt.to_period("W-FRI").dt.start_time
    adds = (
        t.groupby("wk")[key].nunique().reset_index(name="new_additions")
        .rename(columns={"wk": "week"})
    )

    if exit_col not in t.columns:
        return adds.sort_values("week").reset_index(drop=True)

    # Active days: a trade is "active" on every business day in
    # [entry, exit]. Count concurrent trades per day via a sweep line
    # (+1 at entry, -1 the business day after exit), then average within
    # each ISO week. Open trades (NaT exit) clip to the latest entry so
    # they don't run unbounded. O(trades + days), no per-trade loop.
    t[exit_col] = pd.to_datetime(t[exit_col])
    horizon = t[entry_col].max()
    spans = t.dropna(subset=[entry_col]).copy()
    spans[exit_col] = spans[exit_col].fillna(horizon).clip(upper=horizon)
    spans = spans[spans[exit_col] >= spans[entry_col]]

    if spans.empty:
        out = adds
    else:
        starts = spans[entry_col].value_counts()
        ends = (spans[exit_col] + pd.offsets.BDay(1)).value_counts()
        delta = starts.subtract(ends, fill_value=0).sort_index()
        cal = pd.bdate_range(spans[entry_col].min(), spans[exit_col].max())
        active_by_day = (
            delta.reindex(delta.index.union(cal), fill_value=0)
            .sort_index()
            .cumsum()
            .reindex(cal, method="ffill")
            .fillna(0)
        )
        wk = active_by_day.index.to_period("W-FRI").start_time
        active = active_by_day.groupby(wk).mean().reset_index()
        active.columns = ["week", "avg_daily_active"]
        out = adds.merge(active, on="week", how="outer")

    out = out.sort_values("week").reset_index(drop=True)
    for col in ("avg_daily_active", "new_additions"):
        if col in out.columns:
            out[col] = out[col].fillna(0)
    return out


def days_active_by_class(
    df: pd.DataFrame,
    target_col: str = "target_class",
    days_col: str = "days_observed",
    class_names: Sequence[str] = DEFAULT_CLASS_NAMES,
) -> pd.DataFrame:
    """Trade-grain (days_observed, class) for the per-class density chart.

    days_observed = COUNT(*) trading days the trade was tracked (view_manager
    outcomes CTE) — i.e. total days the candidate stayed active. Deduped to one
    row per trade so long trades don't dominate the density.
    """
    needed = {target_col, days_col}
    if not needed.issubset(df.columns):
        logger.warning(
            "days_active_by_class skipped — missing %s",
            needed - set(df.columns),
        )
        return pd.DataFrame(columns=["class", "days_observed"])

    key = "trade_id" if "trade_id" in df.columns else None
    sub = (
        df.drop_duplicates(subset=[key]) if key else df
    )[[target_col, days_col]].copy()
    sub[days_col] = pd.to_numeric(sub[days_col], errors="coerce")
    sub = sub.dropna(subset=[days_col, target_col])
    sub["class"] = sub[target_col].astype(int).map(
        lambda i: class_names[i] if 0 <= i < len(class_names) else str(i)
    )
    return sub[["class", days_col]].rename(columns={days_col: "days_observed"})


def compute_ic(
    df: pd.DataFrame,
    features: List[str],
    target: str,
    method: str = "spearman",
    min_obs: int = IC_MIN_OBS,
    exclude: List[str] = None,
) -> pd.DataFrame:
    """Per-feature rank IC vs target (model_proto.ipynb cell 42).

    inf -> nan -> dropna per feature; require >= min_obs non-null; target
    aligned by index. Sorted by abs(IC) desc. Flags |IC| < 0.02 low-signal.
    """
    if method != "spearman":
        raise ValueError("only spearman IC is supported (model_proto parity)")

    if exclude is None:
        exclude = []
    
    # Always exclude the target itself just to be safe
    exclude_set = set(exclude)
    exclude_set.add(target)

    rows = []
    for feat in features:
        if feat in exclude_set:
            continue
        if feat not in df.columns:
            continue
        if not pd.api.types.is_numeric_dtype(df[feat]):
            continue  # categoricals (sector/industry) handled by MI, not IC
        series = df[feat].replace([np.inf, -np.inf], np.nan).dropna()
        if len(series) < min_obs:
            continue
        aligned = df.loc[series.index, target]
        corr, pval = stats.spearmanr(series, aligned)
        rows.append({
            "feature": feat,
            "spearman_ic": corr,
            "pval": pval,
            "abs_ic": abs(corr),
            "low_signal": abs(corr) < IC_LOW_SIGNAL,
        })

    ic_df = (
        pd.DataFrame(rows)
        .sort_values("abs_ic", ascending=False)
        .reset_index(drop=True)
    )
    return ic_df


def compute_mutual_information(
    df: pd.DataFrame,
    features: List[str],
    target: str,
    sample_n: int = MI_SAMPLE_N,
    seed: int = MI_SEED,
    exclude: List[str] = None,
) -> pd.DataFrame:
    """mutual_info_classif on a <= sample_n sample (model_proto.ipynb cell 44).

    inf -> nan, dropna over features+target BEFORE sampling. sector/industry
    label-encoded (fresh encoder per column). discrete_features=False.
    """
    if exclude is None:
        exclude = []
    
    exclude_set = set(exclude)
    exclude_set.add(target)

    feats = [f for f in features if f in df.columns and f not in exclude_set]
    mi_data = (
        df.replace([np.inf, -np.inf], np.nan)
        .dropna(subset=feats + [target])
    )
    if mi_data.empty:
        logger.warning("compute_mutual_information: no rows after dropna")
        return pd.DataFrame(columns=["feature", "mi_score"])

    mi_sample = mi_data.sample(n=min(sample_n, len(mi_data)), random_state=seed)
    x = mi_sample[feats].copy()
    y = mi_sample[target]

    for cat in ("sector", "industry"):
        if cat in x.columns:
            x[cat] = LabelEncoder().fit_transform(x[cat].astype(str))

    mi_scores = mutual_info_classif(
        x, y, discrete_features=False, random_state=seed
    )
    return (
        pd.DataFrame({"feature": feats, "mi_score": mi_scores})
        .sort_values("mi_score", ascending=False)
        .reset_index(drop=True)
    )


def compute_redundancy(
    df: pd.DataFrame,
    features: List[str],
    threshold: float = REDUNDANCY_THRESHOLD,
    sample_n: int = REDUNDANCY_SAMPLE_N,
    seed: int = MI_SEED,
) -> Tuple[pd.DataFrame, List[Tuple[str, str, float]]]:
    """Spearman corr matrix + pairs |r| > threshold (model_proto.ipynb cell 47/49).

    Spearman = Pearson of ranks. Computed as rank-then-Pearson so the pairwise
    correlation runs as a single vectorised matrix product across all columns,
    instead of pandas' O(F^2) per-pair `corr(method="spearman")` loop that hangs
    on multi-million-row dense inputs.

    sample_n caps rows before ranking (None disables). Spearman is a population
    statistic; a 200k stratified-by-row sample reproduces the matrix to ~3 dp.
    sector/industry are label-encoded so they participate in the matrix.

    Returns:
        (corr_matrix, [(feature_a, feature_b, abs_corr), ...] sorted desc)
    """
    feats = [f for f in features if f in df.columns]
    work = df[feats].replace([np.inf, -np.inf], np.nan).copy()
    for cat in ("sector", "industry"):
        if cat in work.columns:
            work[cat] = LabelEncoder().fit_transform(work[cat].astype(str))

    work = work.select_dtypes(include=[np.number])
    if sample_n is not None and len(work) > sample_n:
        work = work.sample(n=sample_n, random_state=seed)

    corr = work.rank(method="average").corr(method="pearson")

    upper = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
    stacked = upper.stack()
    high = stacked[stacked.abs() > threshold]
    pairs = sorted(
        ((a, b, abs(v)) for (a, b), v in high.items()),
        key=lambda t: t[2],
        reverse=True,
    )
    return corr, pairs
