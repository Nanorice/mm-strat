"""Event-centric score trajectory (§4.3.3).

For each `(ticker, event_date)`, pulls the model's score in a window around
the event (T-N → T+M) and aggregates across events to get the average score
path. Used to ask: "does the model's conviction build before the breakout,
or only afterwards?"
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


def score_trajectory(
    scores_df: pd.DataFrame,
    event_dates_df: pd.DataFrame,
    window_before: int = 30,
    window_after: int = 30,
    score_col: str = "score",
    ticker_col: str = "ticker",
    date_col: str = "date",
    event_date_col: str = "event_date",
) -> pd.DataFrame:
    """Per-event score path around each event, then mean ± CI across events.

    Returns DataFrame with columns:
        relative_day, n_events, mean_score, std_score, ci_lo, ci_hi
    sorted by `relative_day` from -window_before to +window_after.
    """
    for c in (score_col, ticker_col, date_col):
        if c not in scores_df.columns:
            raise KeyError(f"{c!r} not in scores_df")
    for c in (ticker_col, event_date_col):
        if c not in event_dates_df.columns:
            raise KeyError(f"{c!r} not in event_dates_df")

    scores = scores_df.copy()
    scores[date_col] = pd.to_datetime(scores[date_col])
    events = event_dates_df.copy()
    events[event_date_col] = pd.to_datetime(events[event_date_col])

    # Build per-ticker sorted (date, score) arrays once.
    by_ticker = {tk: g.sort_values(date_col).reset_index(drop=True)
                 for tk, g in scores.groupby(ticker_col)}

    accumulator: Dict[int, list] = {d: [] for d in range(-window_before, window_after + 1)}

    for _, ev in events.iterrows():
        tk = ev[ticker_col]
        ev_date = ev[event_date_col]
        if tk not in by_ticker:
            continue
        g = by_ticker[tk]
        # Find index of event date (or the nearest *prior* trading day so events
        # that fall on a non-trading day still anchor).
        idx_arr = g[date_col].searchsorted(ev_date)
        if idx_arr >= len(g):
            continue
        # If exact match, use idx_arr; else use idx_arr-1 (last <= ev_date).
        if idx_arr < len(g) and g[date_col].iloc[idx_arr] == ev_date:
            anchor = int(idx_arr)
        elif idx_arr > 0:
            anchor = int(idx_arr - 1)
        else:
            continue

        for rel in range(-window_before, window_after + 1):
            j = anchor + rel
            if 0 <= j < len(g):
                v = g[score_col].iloc[j]
                if not pd.isna(v):
                    accumulator[rel].append(float(v))

    rows = []
    for rel, vals in sorted(accumulator.items()):
        arr = np.asarray(vals, dtype=float)
        n = arr.size
        if n == 0:
            rows.append({
                "relative_day": rel, "n_events": 0,
                "mean_score": float("nan"), "std_score": float("nan"),
                "ci_lo": float("nan"), "ci_hi": float("nan"),
            })
            continue
        mu = float(arr.mean())
        sd = float(arr.std(ddof=1)) if n > 1 else 0.0
        # 95% CI under normality (z=1.96).
        se = sd / np.sqrt(n) if n > 0 else float("nan")
        rows.append({
            "relative_day": rel,
            "n_events": int(n),
            "mean_score": mu,
            "std_score": sd,
            "ci_lo": mu - 1.96 * se,
            "ci_hi": mu + 1.96 * se,
        })
    return pd.DataFrame(rows)
