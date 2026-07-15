"""§1.2a — regime-tiered fan/cone (DIAGNOSTIC re-cut, NOT a promotion).

Partition the 90-cell ungated `champion_trail` start-date cone by SPY-200d regime
and compare the Sharpe/return/DD DISTRIBUTIONS of "SEPA in clean bull" vs
"SEPA in chop". No new backtest — reads each cell's persisted metrics.json /
equity.parquet / config.json.

Two cuts, coarse -> fine:
  A. START-TAG cone: tag each 12m cell by SPY-200d state at its START date, split
     the per-cell metrics into two cones. This is the headline "start in bull vs
     start in chop" fan. Coarse: a bull-started cell can roll into chop mid-window.
  B. SUB-PERIOD cut: attribute each equity-curve DAY's book return to that day's
     SPY-200d state, pool across all cells, and compute a bull-day vs chop-day
     return/vol/Sharpe. Honest regime attribution (no whole-cell mislabel), but
     loses the start-date-cone shape.

HARD CAVEAT (same as §1.2b): the ungated champion_trail trades in BOTH regimes;
the LIVE champion is SPY-gated so it never opens chop-start positions. This re-cut
is a DIAGNOSTIC of how the strategy behaves per regime, and whether a per-regime
tier is worth a fresh per-regime CONE. Trade/cell-log split != promotion. Prior
(the whole sprint): the 200d gate already IS the tier — expect "chop cone is the
loss cone, bull cone carries the edge", i.e. the gate we have, not a new axis.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from src.backtest.macro_sizer import spy_above_200d  # noqa: E402

CONE = ROOT / "data/selection_sweep/starttime/champion_trail/rolling"


def load_cells() -> pd.DataFrame:
    """One row per cell: start date + the persisted metrics."""
    rows = []
    for cfg_f in sorted(glob.glob(str(CONE / "r_*/config.json"))):
        d = Path(cfg_f).parent
        cfg = json.loads(Path(cfg_f).read_text())
        met = json.loads((d / "metrics.json").read_text())
        # description = "champion_trail 2008-07-01..2009-07-01"
        start = cfg["description"].split()[-1].split("..")[0]
        rows.append({"cell": cfg["id"], "start": pd.Timestamp(start),
                     "sharpe": met["sharpe_ratio"], "total_return": met["total_return"],
                     "max_dd": met["max_drawdown"], "trades": met["total_trades"],
                     "win_rate": met["win_rate"], "dir": str(d)})
    return pd.DataFrame(rows).sort_values("start").reset_index(drop=True)


def spy_state_series(start: str, end: str) -> pd.Series:
    above = pd.Series(spy_above_200d(start, end))
    above.index = pd.to_datetime(above.index)
    return above.sort_index()


def q(x: pd.Series) -> dict:
    return {"n": len(x), "min": round(x.min(), 2), "p25": round(x.quantile(.25), 2),
            "median": round(x.median(), 2), "p75": round(x.quantile(.75), 2),
            "max": round(x.max(), 2), "%neg": round(100 * (x < 0).mean(), 1)}


def cut_a_start_tag(cells: pd.DataFrame, spy: pd.Series) -> pd.DataFrame:
    """Headline: split per-cell Sharpe by SPY-200d at each cell's START."""
    cells = cells.copy()
    cells["bull_start"] = spy.reindex(cells["start"], method="ffill").values
    cells["bull_start"] = cells["bull_start"].astype(bool)
    bull, chop = cells[cells.bull_start], cells[~cells.bull_start]
    print(f"\n{'='*74}\nCUT A — START-TAG cone ({len(cells)} cells | "
          f"bull-start {len(bull)} | chop-start {len(chop)})\n{'='*74}")
    for metric in ["sharpe", "total_return", "max_dd"]:
        tbl = pd.DataFrame({"bull-start": q(bull[metric]), "chop-start": q(chop[metric])}).T
        print(f"\n[{metric}]"); print(tbl.to_string())
    return cells


def cut_b_subperiod(cells: pd.DataFrame) -> None:
    """Honest: attribute each equity-curve DAY's return to that day's regime."""
    all_start = cells["start"].min().strftime("%Y-%m-%d")
    all_end = (cells["start"].max() + pd.DateOffset(years=1, days=10)).strftime("%Y-%m-%d")
    spy = spy_state_series(all_start, all_end)

    frames = []
    for _, r in cells.iterrows():
        eq = pd.read_parquet(Path(r["dir"]) / "equity.parquet")[["date", "value"]]
        eq["date"] = pd.to_datetime(eq["date"])
        eq = eq.sort_values("date")
        eq["ret"] = eq["value"].pct_change()
        eq["bull"] = spy.reindex(eq["date"], method="ffill").values
        frames.append(eq.dropna(subset=["ret", "bull"]))
    days = pd.concat(frames, ignore_index=True)
    days["bull"] = days["bull"].astype(bool)

    print(f"\n{'='*74}\nCUT B — SUB-PERIOD day-return attribution "
          f"({len(days)} book-days pooled across cells)\n{'='*74}")
    rows = []
    for name, sub in [("bull-day (SPY>200d)", days[days.bull]),
                      ("chop-day (SPY<=200d)", days[~days.bull])]:
        rt = sub["ret"]
        ann_sharpe = (rt.mean() / rt.std() * np.sqrt(252)) if rt.std() > 0 else np.nan
        rows.append({"regime": name, "book-days": len(sub),
                     "mean_daily_ret_bps": round(1e4 * rt.mean(), 2),
                     "daily_vol_bps": round(1e4 * rt.std(), 1),
                     "ann_sharpe": round(ann_sharpe, 2),
                     "%down_days": round(100 * (rt < 0).mean(), 1)})
    print(pd.DataFrame(rows).set_index("regime").to_string())
    print("\nNB annualized Sharpe here is a POOLED day-return proxy (ignores which cell "
          "a day belongs to) — comparable bull-vs-chop, not equal to the per-cell cone Sharpe.")


def main() -> None:
    cells = load_cells()
    spy = spy_state_series(cells["start"].min().strftime("%Y-%m-%d"),
                           (cells["start"].max() + pd.DateOffset(days=5)).strftime("%Y-%m-%d"))
    cut_a_start_tag(cells, spy)
    cut_b_subperiod(cells)
    print("\nREAD: if the chop-start cone is the loss cone and the bull-start cone carries "
          "the edge, the tier IS the SPY-200d gate we already ship (bull=deploy, chop=stand "
          "aside). A NEW tier would need chop to hold its own edge, or bull to want a "
          "DIFFERENT config. Diagnostic only; a promotion needs a fresh per-regime cone.")


if __name__ == "__main__":
    main()
