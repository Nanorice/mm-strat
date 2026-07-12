"""Per-start-day basket forward paths under the FULL mechanism (governor + SL [+ TP]).

The reframe (user, 2026-07-09): stop looking at ONE equity curve (which bakes in a
single start-date + the exposure-drift artifact). Instead, treat every start-day as a
lottery draw: on day d, buy that day's governor-gated top-N by prob_elite, hold each
name applying SL/TP/horizon, and forward-track the basket. This removes exposure drift
(fixed notional per start-day, N equal-weighted names) and IS the honest model of a
start-time-dependent strategy.

Outputs a per-(start_day) record + per-(start_day, day_offset) equity path, for:
  Plot A  — distribution of basket forward return across start-days (the lottery).
  Plot B  — every start-day's equity curve overlaid, aligned at x=0 (days after start),
            VARIABLE LENGTH so a curve ending early SHOWS the basket fully exiting
            (the "when do we stop" variable made visual).

Governor is applied at the START-DAY level: if the gate is off (SPY<=200d) on day d,
that day deploys nothing (no basket) — matching "don't deploy in a down-regime".
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
from src.backtest.macro_sizer import MacroSizer
from src.backtest.sepa_gate import attach_sepa_flags

SCORE_CACHE = ROOT / "data/score_cache/m01_binary_calibrated_2003-01-01_2026-05-22.parquet"
# Pre-gated population (only trend_ok AND breakout_ok rows). Built once from the
# full cache via attach_sepa_flags — see build note in the notebook. Preferred
# when present so the basket functions don't re-join the flags on every call.
SCORE_CACHE_GATED = (ROOT /
    "data/score_cache/m01_binary_calibrated_2003-01-01_2026-05-22_sepa_gated.parquet")
DB_PATH = ROOT / "data/market_data.duckdb"


def _load_scores() -> pd.DataFrame:
    """The genuine-breakout population (trend_ok AND breakout_ok).

    The full cache scores EVERY trend-active t3 row (score_from_t3 scores the
    whole panel), so an un-gated nlargest(prob_elite) draws from an inflated pool
    of off-setup days — the population-inflation bug. Prefer the pre-gated cache;
    else join the flags from t3_sepa_features and filter on the fly."""
    if SCORE_CACHE_GATED.exists():
        scores = pd.read_parquet(SCORE_CACHE_GATED)
        scores["date"] = pd.to_datetime(scores["date"])
        print(f"[sepa gate] pre-gated cache: {len(scores)} breakout rows")
        return scores
    scores = pd.read_parquet(SCORE_CACHE)
    scores["date"] = pd.to_datetime(scores["date"])
    tagged = attach_sepa_flags(scores, str(DB_PATH))
    gated = tagged[tagged["trend_ok"] & tagged["breakout_ok"]].copy()
    print(f"[sepa gate] {len(gated)}/{len(scores)} rows are genuine breakouts (joined live)")
    return gated


def _name_path(close: np.ndarray, sl_pct: float, tp_pct: float | None,
               horizon: int) -> np.ndarray:
    """One name's equity multiple path from entry (=1.0), applying SL/TP/horizon.

    Returns the cumulative multiple per bar until exit; after exit the value is
    FROZEN (cash held flat). Length = horizon+1 (bar 0 = entry = 1.0).
    """
    ret = np.ones(horizon + 1)
    entry = close[0]
    for i in range(1, min(horizon + 1, len(close))):
        mult = close[i] / entry
        if mult <= 1 - sl_pct:                 # stop-loss (book at the stop)
            ret[i:] = 1 - sl_pct
            return ret
        if tp_pct is not None and mult >= 1 + tp_pct:   # take-profit
            ret[i:] = 1 + tp_pct
            return ret
        ret[i] = mult
    # ran past available data: freeze at last known
    if len(close) <= horizon:
        ret[len(close):] = ret[len(close) - 1]
    return ret


def basket_paths(top_n: int = 5, horizon: int = 150, sl_pct: float = 0.15,
                 tp_pct: float | None = None, sample_every: int = 1,
                 use_governor: bool = True,
                 min_score: float | None = None) -> tuple[pd.DataFrame, np.ndarray, list]:
    """Build per-start-day basket equity paths.

    Returns:
      summary  — one row/start-day: fwd return at horizon, exit_day (when basket
                 fully closed / frozen), governor-deployed flag.
      paths    — (n_start_days, horizon+1) basket equity multiples (mean of names).
      starts   — the start-day timestamps aligned to `paths` rows.
    """
    scores = _load_scores()   # genuine breakouts only (population-inflation fix)

    gov = MacroSizer().governor_weight("2003-01-01", "2026-05-22") if use_governor else None

    con = db.connect(str(DB_PATH), read_only=True)
    px = con.execute("SELECT ticker, date, close FROM price_data").df()
    con.close()
    px["date"] = pd.to_datetime(px["date"])
    px = px.sort_values(["ticker", "date"])
    # ticker -> (dates array, close array) for fast forward slicing
    by_tkr = {t: (g["date"].to_numpy(), g["close"].to_numpy())
              for t, g in px.groupby("ticker")}

    start_days = np.sort(scores["date"].unique())[::sample_every]

    summary, paths, starts = [], [], []
    for d in start_days:
        d = pd.Timestamp(d)
        deployed = True
        if gov is not None:
            gv = gov.reindex([d]).ffill().iloc[0] if d in gov.index or (gov.index <= d).any() else 1.0
            g_on = gov.loc[:d]
            deployed = bool(g_on.iloc[-1] > 0) if len(g_on) else True
        if not deployed:
            summary.append({"start": d, "fwd_return": 0.0, "exit_day": 0, "deployed": False})
            paths.append(np.ones(horizon + 1)); starts.append(d)
            continue

        day = scores.loc[scores["date"] == d]
        if min_score is not None:
            day = day[day["prob_elite"] >= min_score]     # quality gate (Q11)
        day_top = day.nlargest(top_n, "prob_elite")["ticker"].tolist()
        name_curves = []
        for t in day_top:
            if t not in by_tkr:
                continue
            dts, cls = by_tkr[t]
            j = np.searchsorted(dts, d)
            if j >= len(dts) or dts[j] != d:
                continue
            fwd_close = cls[j:j + horizon + 1]
            if len(fwd_close) < 2:
                continue
            name_curves.append(_name_path(fwd_close, sl_pct, tp_pct, horizon))
        if not name_curves:
            summary.append({"start": d, "fwd_return": 0.0, "exit_day": 0, "deployed": False})
            paths.append(np.ones(horizon + 1)); starts.append(d)
            continue

        basket = np.mean(np.vstack(name_curves), axis=0)   # equal-weight basket
        # exit_day = first bar the basket goes flat and stays flat to the end.
        flat = np.isclose(np.diff(basket), 0.0)
        exit_day = horizon
        if flat.all():
            exit_day = int(np.argmax(basket != basket[0])) if (basket != basket[0]).any() else 0
        else:
            # last bar with any movement +1
            moved = np.where(~flat)[0]
            exit_day = int(moved[-1] + 1) if len(moved) else horizon
        summary.append({"start": d, "fwd_return": basket[-1] - 1.0,
                        "exit_day": exit_day, "deployed": True})
        paths.append(basket); starts.append(d)

    return pd.DataFrame(summary), np.vstack(paths), starts


# -----------------------------------------------------------------------------
# Minervini overlay: pivot-trigger entry + progressive add-on + tight stop.
# The 3 pieces the plain lottery is missing (user, 2026-07-09):
#   (1) ENTRY TRIGGER — only enter a top-N name if it CLEARED its pivot on volume
#       on the start-day: t3.breakout_momentum > 0 (close > 20d-high, ATR-norm) AND
#       vol_ratio > vol_mult. Most names don't fire -> a real filter (regime-aware:
#       ~28% fire in a bull, ~1% in a crash). VCP setup quality is already in the
#       model's prob_elite; this adds only the TIMING EVENT (not re-weighting VCP).
#   (2) PROGRESSIVE EXPOSURE — enter at half weight; add the other half only if the
#       name confirms (up >= add_pct by add_day). Concentrates into what works.
#   (3) TIGHT STOP — sl_pct default 0.07 (Minervini 5-8%), the real risk tool.
# -----------------------------------------------------------------------------
def _load_triggers() -> pd.DataFrame:
    """(date,ticker) -> breakout_momentum, vol_ratio from t3 (already computed)."""
    con = db.connect(str(DB_PATH), read_only=True)
    t = con.execute(
        "SELECT date, ticker, breakout_momentum, vol_ratio FROM t3_sepa_features "
        "WHERE breakout_momentum IS NOT NULL"
    ).df()
    con.close()
    t["date"] = pd.to_datetime(t["date"])
    return t


def basket_paths_minervini(top_n: int = 5, horizon: int = 150, sl_pct: float = 0.07,
                           vol_mult: float = 1.4, add_pct: float = 0.10, add_day: int = 10,
                           sample_every: int = 1, use_governor: bool = True,
                           ) -> tuple[pd.DataFrame, np.ndarray, list]:
    """Like basket_paths but with the 3-part Minervini overlay. Same return shape.

    A start-day deploys only the top-N names that TRIGGERED that day; if none
    triggered (or governor gate off) it's a no-deploy (flat). Each triggered name
    enters at 0.5 weight and adds to 1.0 iff up >= add_pct by add_day.
    """
    scores = _load_scores()   # trend_ok gate; the pivot trigger below is stricter still
    trig = _load_triggers()
    trig_ok = trig[(trig["breakout_momentum"] > 0) & (trig["vol_ratio"] > vol_mult)]
    trig_set = set(zip(trig_ok["date"], trig_ok["ticker"]))

    gov = MacroSizer().governor_weight("2003-01-01", "2026-05-22") if use_governor else None

    con = db.connect(str(DB_PATH), read_only=True)
    px = con.execute("SELECT ticker, date, close FROM price_data").df()
    con.close()
    px["date"] = pd.to_datetime(px["date"])
    px = px.sort_values(["ticker", "date"])
    by_tkr = {t: (g["date"].to_numpy(), g["close"].to_numpy())
              for t, g in px.groupby("ticker")}

    start_days = np.sort(scores["date"].unique())[::sample_every]
    summary, paths, starts = [], [], []
    for d in start_days:
        d = pd.Timestamp(d)
        if gov is not None:
            g_on = gov.loc[:d]
            if len(g_on) and g_on.iloc[-1] <= 0:
                summary.append({"start": d, "fwd_return": 0.0, "exit_day": 0, "deployed": False})
                paths.append(np.ones(horizon + 1)); starts.append(d); continue

        # candidates = top-N by prob_elite THAT ALSO triggered the pivot today.
        day = scores.loc[scores["date"] == d].nlargest(top_n * 4, "prob_elite")
        picks = [t for t in day["ticker"] if (d, t) in trig_set][:top_n]
        if not picks:
            summary.append({"start": d, "fwd_return": 0.0, "exit_day": 0, "deployed": False})
            paths.append(np.ones(horizon + 1)); starts.append(d); continue

        curves, weights = [], []
        for t in picks:
            if t not in by_tkr:
                continue
            dts, cls = by_tkr[t]
            j = np.searchsorted(dts, d)
            if j >= len(dts) or dts[j] != d:
                continue
            fwd = cls[j:j + horizon + 1]
            if len(fwd) < 2:
                continue
            path = _name_path(fwd, sl_pct, None, horizon)
            confirmed = (add_day < len(path)) and (path[add_day] >= 1 + add_pct)
            curves.append(path); weights.append(1.0 if confirmed else 0.5)
        if not curves:
            summary.append({"start": d, "fwd_return": 0.0, "exit_day": 0, "deployed": False})
            paths.append(np.ones(horizon + 1)); starts.append(d); continue

        C = np.vstack(curves); w = np.array(weights); w = w / w.sum()
        basket = (C * w[:, None]).sum(0)
        flat = np.isclose(np.diff(basket), 0.0)
        moved = np.where(~flat)[0]
        exit_day = int(moved[-1] + 1) if len(moved) else 0
        summary.append({"start": d, "fwd_return": basket[-1] - 1.0,
                        "exit_day": exit_day, "deployed": True, "n_picks": len(curves)})
        paths.append(basket); starts.append(d)

    return pd.DataFrame(summary), np.vstack(paths), starts


if __name__ == "__main__":
    # SMOKE: quarterly start-days only (sample_every large), sanity.
    summ, paths, starts = basket_paths(sample_every=60, horizon=150)
    dep = summ[summ.deployed]
    print(f"[baseline smoke] start-days: {len(summ)}  deployed: {len(dep)}  "
          f"gated-off: {(~summ.deployed).sum()}")
    print(f"  mean {dep.fwd_return.mean():+.1%}  median {dep.fwd_return.median():+.1%}  "
          f"min {dep.fwd_return.min():+.1%}  max {dep.fwd_return.max():+.1%}")
    assert len(dep) > 5 and paths.shape[1] == 151
    print("[OK] baseline smoke passed")

    ms, mp, _ = basket_paths_minervini(sample_every=60, horizon=150)
    md = ms[ms.deployed]
    print(f"[minervini smoke] deployed {len(md)}  mean {md.fwd_return.mean():+.1%}  "
          f"median {md.fwd_return.median():+.1%}  std {md.fwd_return.std():.1%}  "
          f"max {md.fwd_return.max():+.0%}")
    assert len(md) > 3, "minervini overlay produced too few baskets"
    print("[OK] minervini smoke passed")
