"""Permutation null backtest (§4.2).

Shuffles signal labels within each date to break the ticker↔signal link while
preserving universe size and per-date signal density. Re-runs the backtest on
each shuffled signal frame and compares the observed Sharpe to the null
distribution.

Why per-date shuffle: shuffling globally would let signals migrate across
regimes; per-date keeps the number of signals fired each day constant and
only tests the *attribution* — "could random tickers picked within the same
universe have generated the same edge?"
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, Optional

import numpy as np
import pandas as pd

from .gate import GateResult

logger = logging.getLogger(__name__)

BacktestFn = Callable[[pd.DataFrame], Dict]


def _shuffle_signals_within_date(
    signals_df: pd.DataFrame,
    signal_col: str,
    date_col: str,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Per-date shuffle of the signal column. Returns a *copy*."""
    out = signals_df.copy()
    for _, group_idx in out.groupby(date_col).groups.items():
        idx = np.asarray(group_idx)
        if len(idx) <= 1:
            continue
        shuffled = idx.copy()
        rng.shuffle(shuffled)
        out.loc[idx, signal_col] = out.loc[shuffled, signal_col].values
    return out


def permutation_null_backtest(
    signals_df: pd.DataFrame,
    backtest_fn: BacktestFn,
    n_permutations: int = 100,
    seed: int = 42,
    signal_col: str = "signal",
    date_col: str = "date",
    metric_key: str = "sharpe_ratio",
    one_sided: bool = True,
) -> Dict:
    """Per-date permutation null test for a backtest.

    Args:
        signals_df: long DataFrame with at minimum (`date_col`, `signal_col`).
            `signal_col` is whatever the backtest engine consumes (could be a
            boolean signal flag, a probability, a normalized score — anything
            the engine ranks against).
        backtest_fn: f(signals_df) -> dict with `metric_key`. Should be deterministic
            (no internal RNG) — the only randomness comes from this function's shuffle.
        n_permutations: shuffles. The plan calls 100 "fast" and 1000 "deep".
        seed: RNG.
        signal_col: column to permute.
        date_col: groupby column for per-date shuffle.
        metric_key: key in `backtest_fn`'s output dict.
        one_sided: if True, the test is observed > null (we want positive edge).
            If False, two-sided.

    Returns:
        dict with observed metric, null distribution, percentile, p-value, gate.
    """
    if signals_df.empty:
        raise ValueError("signals_df is empty")
    for c in (signal_col, date_col):
        if c not in signals_df.columns:
            raise KeyError(f"{c!r} not in signals_df columns")

    observed_metrics = backtest_fn(signals_df)
    if metric_key not in observed_metrics:
        raise KeyError(f"{metric_key!r} not in observed metrics; got {list(observed_metrics)}")
    observed = float(observed_metrics[metric_key])

    rng = np.random.default_rng(seed)
    null = np.empty(n_permutations, dtype=float)
    for i in range(n_permutations):
        shuffled = _shuffle_signals_within_date(signals_df, signal_col, date_col, rng)
        try:
            null[i] = float(backtest_fn(shuffled).get(metric_key, np.nan))
        except Exception as e:
            logger.warning("permutation %d failed: %s", i, e)
            null[i] = float("nan")

    valid = null[~np.isnan(null)]
    if valid.size == 0:
        percentile = float("nan")
        p_value = float("nan")
    else:
        if one_sided:
            # percentile = fraction of null replicates < observed.
            percentile = float((valid < observed).mean() * 100.0)
            # p-value: prob a random realization >= observed.
            p_value = float((valid >= observed).mean())
        else:
            percentile = float((np.abs(valid) < abs(observed)).mean() * 100.0)
            p_value = float((np.abs(valid) >= abs(observed)).mean())

    # Gate: observed should sit in the top 5% of the null (percentile > 95).
    gate = GateResult(
        name="permutation_null",
        status="pass" if (not np.isnan(percentile) and percentile > 95.0) else "fail",
        value=float(percentile),
        threshold=95.0,
        detail=(
            f"observed={observed:.4f}, null_median={float(np.median(valid)) if valid.size else float('nan'):.4f}, "
            f"p_value={p_value:.4f}, n_permutations={n_permutations}, one_sided={one_sided}"
        ),
        blocking=True,
    )

    return {
        "observed_metric": observed,
        "metric_key": metric_key,
        "null_median": float(np.median(valid)) if valid.size else float("nan"),
        "null_min": float(valid.min()) if valid.size else float("nan"),
        "null_max": float(valid.max()) if valid.size else float("nan"),
        "null_distribution": valid.tolist(),
        "percentile": percentile,
        "p_value": p_value,
        "n_permutations": int(n_permutations),
        "n_valid_replicates": int(valid.size),
        "gate": gate.to_dict(),
    }
