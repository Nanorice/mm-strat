"""Rolling Information Coefficient (§4.3.1).

Spearman or Pearson IC computed per date, then rolled over `window_days` to
get a smooth mean + Newey-West-adjusted t-stat. This is the standard quant
diagnostic for "is the model's score predictive *now*?".
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


def _daily_ic(group: pd.DataFrame, score_col: str, return_col: str, method: str) -> float:
    s = group[score_col].to_numpy(dtype=float)
    r = group[return_col].to_numpy(dtype=float)
    mask = ~(np.isnan(s) | np.isnan(r))
    if mask.sum() < 5:
        return float("nan")
    s = s[mask]
    r = r[mask]
    if method == "spearman":
        rho, _ = spearmanr(s, r)
        return float(rho) if rho is not None else float("nan")
    elif method == "pearson":
        if s.std(ddof=1) == 0 or r.std(ddof=1) == 0:
            return float("nan")
        return float(np.corrcoef(s, r)[0, 1])
    else:
        raise ValueError(f"unknown method {method!r}")


def _newey_west_t(values: np.ndarray, lag: int = 5) -> float:
    """Newey-West t-stat on the *mean* of `values` with `lag` Newey-West lags.

    Returns nan if too few observations or zero variance.
    """
    x = values[~np.isnan(values)]
    n = len(x)
    if n < lag + 2:
        return float("nan")
    mu = x.mean()
    e = x - mu
    # gamma_0
    gamma0 = (e @ e) / n
    # weighted sum of autocovariances
    cov_sum = 0.0
    for k in range(1, lag + 1):
        w = 1.0 - k / (lag + 1)
        gk = (e[:-k] @ e[k:]) / n
        cov_sum += 2.0 * w * gk
    var = gamma0 + cov_sum
    if var <= 0:
        return float("nan")
    se = np.sqrt(var / n)
    return float(mu / se)


def rolling_ic(
    df: pd.DataFrame,
    date_col: str = "date",
    score_col: str = "score",
    return_col: str = "forward_return",
    method: Literal["spearman", "pearson"] = "spearman",
    window_days: int = 252,
    nw_lag: int = 5,
) -> pd.DataFrame:
    """Per-date IC + rolling mean + rolling NW t-stat.

    Returns DataFrame indexed by date with columns:
        ic, rolling_ic_mean, rolling_ic_t_stat, n_daily_obs
    """
    for c in (date_col, score_col, return_col):
        if c not in df.columns:
            raise KeyError(f"{c!r} not in df columns")

    # Daily IC.
    daily = df.groupby(date_col).apply(
        lambda g: pd.Series({
            "ic": _daily_ic(g, score_col, return_col, method),
            "n_daily_obs": int(g[[score_col, return_col]].dropna().shape[0]),
        }),
        include_groups=False,
    )
    daily.index = pd.to_datetime(daily.index)
    daily = daily.sort_index()

    # Rolling mean.
    daily["rolling_ic_mean"] = daily["ic"].rolling(window=window_days, min_periods=max(1, window_days // 4)).mean()

    # Rolling NW t-stat.
    def _nw(series: pd.Series) -> float:
        return _newey_west_t(series.to_numpy(dtype=float), lag=nw_lag)

    daily["rolling_ic_t_stat"] = daily["ic"].rolling(window=window_days, min_periods=nw_lag + 2).apply(
        _nw, raw=False
    )

    return daily[["ic", "n_daily_obs", "rolling_ic_mean", "rolling_ic_t_stat"]]
