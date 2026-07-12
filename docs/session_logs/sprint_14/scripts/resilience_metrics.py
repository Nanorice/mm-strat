"""Trough-geometry v2: published resilience metrics per (name, SPY-drawdown episode).

Replaces the time-x-distance rectangle (trough_geometry.py v1 traits) with:
  rel_ulcer      — name Ulcer Index / SPY Ulcer Index over the episode. The Ulcer Index
                   (Martin 1987) is the RMS of the underwater curve: one number for
                   depth AND duration — the rectangle's true integral.
  half_life_lead — SPY 50%-retrace days − name 50%-retrace days (>0 = heals faster).
  recovery_vel   — name %retrace-per-day off its trough ÷ SPY same (speed).
Pre-episode proxies (126td before the peak, live-computable):
  relvol, beta, beta_dn/beta_up (downside/upside beta, Ang-Chen-Xing), beta_asym,
  corr_spy, rs126.

Finding (2026-07-11, 8k name-episodes / 6 episodes): rel_ulcer beats both v1 rectangle
traits as a label (rho fwd100 −0.19) AND is the most predictable (relvol → rel_ulcer
+0.50). The velocity/decay legs grade nothing and nothing predicts them. Geometry is a
DEFENSIVE/MEDIAN axis (deep-trough names keep lottery tails — HR mildly inverts).
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
from trough_geometry import spy_close, spy_drawdown_episodes

DB = ROOT / "data/market_data.duckdb"


def _ulcer(seg: pd.Series) -> float:
    u = 1 - seg / seg.cummax()
    return float(np.sqrt((u ** 2).mean()) * 100)


def _half_life(seg: pd.Series) -> float:
    """Trading days from trough to first 50% retrace of the drawdown (nan if never)."""
    entry, tr_i = seg.iloc[0], int(seg.values.argmin())
    trough = seg.iloc[tr_i]
    hit = np.where(seg.iloc[tr_i:].values >= trough + 0.5 * (entry - trough))[0]
    return float(hit[0]) if len(hit) else np.nan


def episode_resilience(ep: pd.Series, names: list[str], spy: pd.Series) -> pd.DataFrame:
    """v2 labels + v1 traits + pre-episode proxies for every name in one episode."""
    lo = (ep.peak_date - pd.Timedelta(days=300)).strftime("%Y-%m-%d")
    hi = ep.recover_date.strftime("%Y-%m-%d")
    con = db.connect(str(DB), read_only=True)
    px = con.execute(
        "SELECT ticker, date, close FROM price_data WHERE ticker IN "
        f"{tuple(sorted(set(names)))} AND date BETWEEN ? AND ? ORDER BY ticker, date",
        [lo, hi]).df()
    con.close()
    px["date"] = pd.to_datetime(px["date"])

    spy_pre = spy.loc[lo:ep.peak_date].iloc[:-1].tail(126)
    spy_pre_ret = spy_pre.pct_change().dropna()
    spy_seg = spy.loc[ep.peak_date:ep.recover_date]
    spy_ui, spy_hl = _ulcer(spy_seg), _half_life(spy_seg)
    spy_tr_i = int(spy_seg.values.argmin())
    spy_vel = (spy_seg.iloc[-1] / spy_seg.min() - 1) / max(len(spy_seg) - spy_tr_i, 1)

    rows = []
    for t, g in px.groupby("ticker"):
        s = g.set_index("date")["close"]
        pre = s.loc[:ep.peak_date].iloc[:-1].tail(126)
        seg = s.loc[ep.peak_date:ep.recover_date]
        if len(pre) < 60 or len(seg) < 10:
            continue
        r = pre.pct_change().dropna()
        m = pd.concat([r, spy_pre_ret], axis=1, keys=["n", "s"]).dropna()
        if len(m) < 40:
            continue
        dn, up = m[m.s < 0], m[m.s > 0]
        beta = m.n.cov(m.s) / m.s.var() if m.s.var() > 0 else np.nan
        b_dn = dn.n.cov(dn.s) / dn.s.var() if len(dn) > 15 and dn.s.var() > 0 else np.nan
        b_up = up.n.cov(up.s) / up.s.var() if len(up) > 15 and up.s.var() > 0 else np.nan
        tr_i = int(seg.values.argmin())
        vel = (seg.iloc[-1] / seg.min() - 1) / max(len(seg) - tr_i, 1)
        rows.append({
            "ticker": t, "peak_date": ep.peak_date,
            "rel_ulcer": _ulcer(seg) / spy_ui if spy_ui > 0 else np.nan,
            "half_life_lead": (spy_hl - _half_life(seg)) if not np.isnan(spy_hl) else np.nan,
            "recovery_vel": vel / spy_vel if spy_vel > 0 else np.nan,
            "relative_depth": (1 - seg.min() / seg.iloc[0]) / (1 - spy_seg.min() / spy_seg.iloc[0]),
            "trough_lead_days": (spy_seg.index[spy_tr_i] - seg.index[tr_i]).days,
            "relvol": r.std() / spy_pre_ret.std(),
            "beta": beta, "beta_dn": b_dn, "beta_up": b_up,
            "beta_asym": (b_up - b_dn) if not (np.isnan(b_up) or np.isnan(b_dn)) else np.nan,
            "corr_spy": m.n.corr(m.s),
            "rs126": (pre.iloc[-1] / pre.iloc[0]) / (spy_pre.iloc[-1] / spy_pre.iloc[0]) - 1,
        })
    return pd.DataFrame(rows)


def resilience_panel(panel: pd.DataFrame, min_dd: float = 0.12,
                     since: str = "2003-01-01") -> pd.DataFrame:
    """All episodes since `since` × the panel's names (year ±1), with fwd_out attached.

    fwd_out convention matches the notebook §4 cell: the name's median panel fwd100
    over the episode year and the year after.
    """
    spy = spy_close()
    eps = spy_drawdown_episodes(min_dd=min_dd, min_len=20)
    eps = eps[eps.peak_date >= since].reset_index(drop=True)
    if "year" not in panel.columns:
        panel = panel.assign(year=panel.date.dt.year)

    frames = []
    for _, ep in eps.iterrows():
        yr = ep.peak_date.year
        names = panel[panel.year.isin([yr - 1, yr, yr + 1])].ticker.unique().tolist()
        g = episode_resilience(ep, names, spy)
        med = panel[panel.year.isin([yr, yr + 1])].groupby("ticker")["fwd100"].median()
        g["fwd_out"] = g.ticker.map(med)
        print(f"  [resilience] {ep.peak_date.date()}: {len(g)} name-episodes", flush=True)
        frames.append(g)
    return pd.concat(frames, ignore_index=True)


if __name__ == "__main__":
    # SMOKE: one episode, few hundred names
    from gated_eda_panel import load_gated_panel
    panel = load_gated_panel((2019, 2020, 2021))
    panel["year"] = panel.date.dt.year
    spy = spy_close()
    eps = spy_drawdown_episodes()
    ep = eps[eps.peak_date.dt.year == 2020].iloc[0]
    g = episode_resilience(ep, panel.ticker.unique().tolist()[:300], spy)
    assert len(g) > 100 and g.rel_ulcer.notna().mean() > 0.9
    print(f"[OK] resilience smoke: {len(g)} name-episodes, "
          f"rel_ulcer median {g.rel_ulcer.median():.2f}")
