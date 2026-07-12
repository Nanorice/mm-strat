"""Trough-geometry LEADERSHIP study (Sprint-14 consolidation, NEW).

Minervini's claim: true market leaders, during an index decline, (a) BOTTOM BEFORE
the index, (b) fall SHALLOWER (higher relative low), and (c) RECOVER their prior
high FASTER. This is a DOWN-CYCLE relative-strength SHAPE that plain RS (a smoothed
momentum ratio, already in the model) does NOT explicitly encode.

The test: measure the three traits per name per index-drawdown episode, then ask
whether they grade the name's fwd63 tail-magnitude INCREMENTAL to RS. If the traits
only proxy RS, they add nothing (the R2 lesson — leadership traits collapsed into RS).
If down-cycle geometry carries residual tail signal, it's the piece RS misses.

    from trough_geometry import spy_drawdown_episodes, name_trough_geometry
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd


def _root() -> Path:
    p = Path(__file__).resolve()
    for d in (p, *p.parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError("root not found")


ROOT = _root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import db

DB = ROOT / "data/market_data.duckdb"


def spy_close() -> pd.Series:
    con = db.connect(str(DB), read_only=True)
    df = con.execute(
        "SELECT date, close FROM price_data WHERE ticker='SPY' ORDER BY date").df()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["close"]


def spy_drawdown_episodes(min_dd: float = 0.12, min_len: int = 20) -> pd.DataFrame:
    """Peak→trough→recovery episodes where SPY fell >= min_dd from a running high.

    An episode = [peak_date .. trough_date .. recover_date] where recover_date is
    the first day SPY reclaims the pre-drop peak (or series end if never). Only
    episodes with depth >= min_dd and peak→trough length >= min_len kept.
    """
    spy = spy_close()
    run_max = spy.cummax()
    dd = spy / run_max - 1.0

    episodes = []
    i, n = 0, len(spy)
    idx = spy.index
    while i < n:
        if dd.iloc[i] >= -1e-9:            # at a new high — no drawdown open
            i += 1
            continue
        # a drawdown is open: the peak is the last new-high before i
        peak_pos = int(np.where(run_max.values[:i + 1] == spy.values[:i + 1])[0][-1])
        peak = run_max.iloc[i]
        # walk to recovery (reclaim peak) or end
        j = i
        while j < n and spy.iloc[j] < peak:
            j += 1
        seg = spy.iloc[peak_pos:j + 1]     # peak .. recover (inclusive)
        trough_pos_rel = int(seg.values.argmin())
        depth = 1.0 - seg.min() / peak
        length = trough_pos_rel            # peak→trough in bars
        if depth >= min_dd and length >= min_len:
            episodes.append({
                "peak_date": idx[peak_pos],
                "trough_date": seg.index[trough_pos_rel],
                "recover_date": idx[j] if j < n else idx[-1],
                "depth": depth,
                "peak_to_trough_days": length,
                "recovered": j < n,
            })
        i = j + 1                          # continue after recovery
    return pd.DataFrame(episodes)


def name_trough_geometry(tickers: list[str], episodes: pd.DataFrame,
                         pad_days: int = 20) -> pd.DataFrame:
    """Per (name, episode) the three leader traits vs SPY.

    trough_lead_days   = SPY_trough_date − name_trough_date  (>0 = name bottomed FIRST)
    relative_depth     = name_maxDD / spy_maxDD              (<1 = shallower = leader)
    recover_lead_days  = SPY_recover_date − name_recover_date (>0 = name reclaimed FIRST;
                         name recover = first day it reclaims its own pre-episode high)
    Names with no price in the window are dropped.
    """
    spy = spy_close()
    con = db.connect(str(DB), read_only=True)
    tks = tuple(sorted(set(tickers)))
    lo = (episodes["peak_date"].min() - pd.Timedelta(days=pad_days * 2)).strftime("%Y-%m-%d")
    hi = (episodes["recover_date"].max() + pd.Timedelta(days=pad_days * 2)).strftime("%Y-%m-%d")
    px = con.execute(
        "SELECT ticker, date, close FROM price_data WHERE ticker IN "
        f"{tks} AND date BETWEEN ? AND ? ORDER BY ticker, date", [lo, hi]).df()
    con.close()
    px["date"] = pd.to_datetime(px["date"])
    by = {t: g.set_index("date")["close"] for t, g in px.groupby("ticker")}

    rows = []
    for _, ep in episodes.iterrows():
        spy_seg = spy.loc[ep.peak_date:ep.recover_date]
        spy_dd = 1.0 - spy_seg.min() / spy_seg.iloc[0]
        for t, s in by.items():
            seg = s.loc[ep.peak_date:ep.recover_date]
            if len(seg) < 5:
                continue
            entry = seg.iloc[0]
            name_dd = 1.0 - seg.min() / entry
            name_trough = seg.idxmin()
            # name recover = first day after its trough it reclaims the episode-start level
            post = seg.loc[name_trough:]
            recov = post[post >= entry]
            name_recover = recov.index[0] if len(recov) else ep.recover_date
            rows.append({
                "ticker": t,
                "peak_date": ep.peak_date,
                "trough_lead_days": (ep.trough_date - name_trough).days,
                "relative_depth": name_dd / spy_dd if spy_dd > 0 else np.nan,
                "recover_lead_days": (ep.recover_date - name_recover).days,
                "name_maxDD": name_dd,
            })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    eps = spy_drawdown_episodes()
    print(f"[episodes] {len(eps)} SPY drawdowns >=12%:")
    with pd.option_context("display.width", 140):
        print(eps.assign(
            peak=eps.peak_date.dt.date, trough=eps.trough_date.dt.date,
            recover=eps.recover_date.dt.date, depth=(eps.depth * 100).round(1),
        )[["peak", "trough", "recover", "depth", "peak_to_trough_days", "recovered"]].to_string(index=False))
    assert len(eps) >= 4, "expected several major drawdowns"
    print("[OK] episode detection smoke passed")
