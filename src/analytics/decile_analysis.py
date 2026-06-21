"""Decile (or N-tile) analysis (§4.3.2).

Buckets a score column into N quantile groups per-date, computes mean forward
return per bucket, and reports a monotonicity score (Spearman rank correlation
between bucket index and bucket mean return).
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


def decile_analysis(
    df: pd.DataFrame,
    score_col: str = "score",
    return_col: str = "forward_return",
    date_col: str = "date",
    n_buckets: int = 10,
) -> Dict:
    """Bucket scores per-date, average forward returns per bucket.

    Returns:
        {
          'n_buckets': int,
          'per_bucket': list[{bucket, n, mean_return, std_return}],
          'monotonicity_spearman': float,    # rank correlation of (bucket_idx, mean_return)
          'top_minus_bottom_return': float,  # diff of bucket N vs bucket 1
        }
    """
    for c in (score_col, return_col, date_col):
        if c not in df.columns:
            raise KeyError(f"{c!r} not in df columns")
    if n_buckets < 2:
        raise ValueError("n_buckets must be >= 2")

    work = df[[date_col, score_col, return_col]].dropna().copy()
    if work.empty:
        return {
            "n_buckets": n_buckets,
            "per_bucket": [],
            "monotonicity_spearman": float("nan"),
            "top_minus_bottom_return": float("nan"),
        }

    # Per-date qcut into 1..N (1 = lowest score).
    def _bucket(group: pd.DataFrame) -> pd.Series:
        try:
            return pd.qcut(group[score_col], q=n_buckets, labels=False, duplicates="drop") + 1
        except ValueError:
            return pd.Series(np.full(len(group), np.nan), index=group.index)

    work["bucket"] = work.groupby(date_col, group_keys=False).apply(_bucket, include_groups=False)
    work = work.dropna(subset=["bucket"])
    work["bucket"] = work["bucket"].astype(int)

    grouped = work.groupby("bucket")[return_col].agg(["count", "mean", "std"]).reset_index()
    per_bucket = [
        {
            "bucket": int(row["bucket"]),
            "n": int(row["count"]),
            "mean_return": float(row["mean"]),
            "std_return": float(row["std"]) if not pd.isna(row["std"]) else 0.0,
        }
        for _, row in grouped.iterrows()
    ]

    if len(per_bucket) >= 2:
        idx = np.array([b["bucket"] for b in per_bucket], dtype=float)
        mu = np.array([b["mean_return"] for b in per_bucket], dtype=float)
        rho, _ = spearmanr(idx, mu)
        monotonicity = float(rho) if rho is not None else float("nan")
        top_minus_bot = float(per_bucket[-1]["mean_return"] - per_bucket[0]["mean_return"])
    else:
        monotonicity = float("nan")
        top_minus_bot = float("nan")

    return {
        "n_buckets": int(n_buckets),
        "per_bucket": per_bucket,
        "monotonicity_spearman": monotonicity,
        "top_minus_bottom_return": top_minus_bot,
    }
