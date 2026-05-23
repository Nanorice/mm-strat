"""Circular block bootstrap on trade lists (§4.1).

Resamples blocks of trades (grouped by exit-date proximity) with replacement,
recomputes a user-supplied metric `metric_fn` on each replicate, then returns
the empirical distribution + CI.

Why circular blocks: trades cluster in time (regime persistence, multi-day
exits, etc.). Resampling individual trades destroys serial correlation and
yields over-tight CIs. Block resampling preserves the dependence structure.
Circular = wrap-around, so the tail of the series can pair with the head and
every observation has equal selection probability.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from .gate import GateResult

logger = logging.getLogger(__name__)

MetricFn = Callable[[pd.DataFrame], float]


def _make_blocks_by_exit_date(
    trades_df: pd.DataFrame,
    block_size_days: int,
    exit_col: str,
) -> List[np.ndarray]:
    """Group trades into blocks where each block spans `block_size_days` of exit-date.

    Returns a list of int-arrays — each array holds positional indices into
    `trades_df` for that block.
    """
    if exit_col not in trades_df.columns:
        raise KeyError(f"{exit_col!r} not in trades_df columns; got {list(trades_df.columns)}")
    if trades_df.empty:
        return []

    sorted_df = trades_df.sort_values(exit_col).reset_index(drop=True)
    dates = pd.to_datetime(sorted_df[exit_col])
    min_date = dates.min()

    # Day-offset since first trade.
    day_offset = (dates - min_date).dt.days.to_numpy()
    block_id = day_offset // block_size_days

    # Group positional indices by block_id.
    order = np.argsort(block_id, kind="stable")
    sorted_block_ids = block_id[order]
    splits = np.where(np.diff(sorted_block_ids) != 0)[0] + 1
    return [arr for arr in np.split(order, splits) if len(arr) > 0]


def circular_block_bootstrap(
    trades_df: pd.DataFrame,
    metric_fn: MetricFn,
    block_size_days: int = 60,
    n_iterations: int = 10_000,
    seed: int = 42,
    exit_col: str = "exit_date",
    ci_lo: float = 5.0,
    ci_hi: float = 95.0,
    ci_lo_gate_value: float = 0.0,
) -> Dict:
    """Circular block bootstrap a per-trade metric over a list of trades.

    Args:
        trades_df: one row per trade. Must contain `exit_col` (parseable to date).
        metric_fn: f(trades_df) -> float. Called once on observed, then n_iterations
            times on resampled DataFrames.
        block_size_days: blocks span this many calendar days. Trades within a
            block move together when resampled.
        n_iterations: bootstrap replicates.
        seed: RNG seed.
        ci_lo, ci_hi: percentile cuts (default 5/95).
        ci_lo_gate_value: threshold the lower CI must exceed for the gate to pass.

    Returns:
        dict with `metric_observed`, `metric_median`, `ci_lo`, `ci_hi`,
        `n_iterations`, `block_size_days`, `n_trades`, `n_blocks`, `gate`.
    """
    if trades_df.empty:
        return {
            "metric_observed": float("nan"),
            "metric_median": float("nan"),
            "ci_lo": float("nan"),
            "ci_hi": float("nan"),
            "n_iterations": int(n_iterations),
            "block_size_days": int(block_size_days),
            "n_trades": 0,
            "n_blocks": 0,
            "gate": GateResult(
                name="block_bootstrap_ci_lo",
                status="n/a",
                value=None,
                threshold=float(ci_lo_gate_value),
                detail="empty trade list",
                blocking=False,
            ).to_dict(),
        }

    blocks = _make_blocks_by_exit_date(trades_df, block_size_days, exit_col)
    n_blocks = len(blocks)
    n_trades = int(len(trades_df))
    if n_blocks == 0:
        raise ValueError("no blocks formed — check block_size_days / exit_date column")

    # Sorted view, since blocks reference positions into the sorted frame.
    sorted_trades = trades_df.sort_values(exit_col).reset_index(drop=True)

    rng = np.random.default_rng(seed)
    observed = float(metric_fn(sorted_trades))

    replicates = np.empty(n_iterations, dtype=float)
    for i in range(n_iterations):
        # Sample blocks with replacement until we have at least n_trades trades.
        pick = rng.integers(0, n_blocks, size=n_blocks)
        idx_parts = [blocks[k] for k in pick]
        idx = np.concatenate(idx_parts) if idx_parts else np.empty(0, dtype=int)
        # Trim to original length so block effects don't bias size.
        if len(idx) > n_trades:
            idx = idx[:n_trades]
        try:
            replicates[i] = float(metric_fn(sorted_trades.iloc[idx]))
        except Exception:
            replicates[i] = float("nan")

    valid = replicates[~np.isnan(replicates)]
    if valid.size == 0:
        ci_lo_val, ci_hi_val, median = float("nan"), float("nan"), float("nan")
    else:
        ci_lo_val = float(np.percentile(valid, ci_lo))
        ci_hi_val = float(np.percentile(valid, ci_hi))
        median = float(np.median(valid))

    gate = GateResult(
        name="block_bootstrap_ci_lo",
        status="pass" if (not np.isnan(ci_lo_val) and ci_lo_val > ci_lo_gate_value) else "fail",
        value=float(ci_lo_val),
        threshold=float(ci_lo_gate_value),
        detail=f"observed={observed:.4f}, ci[{ci_lo:.0f},{ci_hi:.0f}]=[{ci_lo_val:.4f}, {ci_hi_val:.4f}]",
        blocking=False,  # Diagnostic — significant CI is a strong signal, not promotion-gating by itself.
    )

    return {
        "metric_observed": observed,
        "metric_median": median,
        "ci_lo": ci_lo_val,
        "ci_hi": ci_hi_val,
        "n_iterations": int(n_iterations),
        "block_size_days": int(block_size_days),
        "n_trades": n_trades,
        "n_blocks": n_blocks,
        "gate": gate.to_dict(),
    }


# ----------------------------- common metrics -----------------------------


def sharpe_from_trades(
    trades_df: pd.DataFrame,
    pnl_col: str = "pnl_percent",
    periods_per_year: float = 252.0,
    avg_hold_days: Optional[float] = None,
) -> float:
    """Naive trade-level Sharpe approximation.

    NOT the same as daily-returns Sharpe — this assumes each trade is one
    observation. `periods_per_year` and `avg_hold_days` together let you
    annualize. Default behaviour: treat trades as ~daily.
    """
    if trades_df.empty or pnl_col not in trades_df.columns:
        return float("nan")
    r = trades_df[pnl_col].to_numpy(dtype=float) / 100.0
    sd = r.std(ddof=1) if r.size >= 2 else 0.0
    if r.size < 2 or sd < 1e-12:
        return float("nan")
    sharpe = r.mean() / sd
    if avg_hold_days is not None and avg_hold_days > 0:
        sharpe *= np.sqrt(periods_per_year / avg_hold_days)
    else:
        sharpe *= np.sqrt(periods_per_year)
    return float(sharpe)


def total_return_from_trades(
    trades_df: pd.DataFrame,
    pnl_col: str = "pnl_percent",
) -> float:
    """Sum of PnL percentages — approximation, not compounded."""
    if trades_df.empty or pnl_col not in trades_df.columns:
        return float("nan")
    return float(trades_df[pnl_col].sum())
