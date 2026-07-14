"""§1.2b — per-regime gate sweep (DIAGNOSTIC re-cut, NOT a promotion).

Re-cut the champion_trail cone's persisted trades (90 cells, 2664 trades) by
SPY-200d-at-entry, then sweep the prob_elite gate on the ABOVE-200d (bull)
subset. Tests the Q47 hunch: does a higher gate pay in clean bull, where the
POOLED sweep found it hurts?

HARD CAVEAT: this is per-trade basket distribution only — no slot contention,
no sizing, no rotation. Trade-log lift != cone edge (proven 3x,
project_vec_engine_optimistic). A tier earns a bull-only CONE only if the
bull-subset distribution visibly improves at a higher gate where the pooled
sweep said it hurt. The chop (below-200d) subset is REFERENCE CONTRAST ONLY
(those entries are gate-blocked live) — not swept.
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from src.backtest.macro_sizer import spy_above_200d  # noqa: E402

CONE = ROOT / "data/selection_sweep/starttime/champion_trail/rolling"
GATES = [0.15, 0.20, 0.25, 0.30]


def load_trades() -> pd.DataFrame:
    fs = sorted(glob.glob(str(CONE / "r_*/trades.parquet")))
    if not fs:
        raise FileNotFoundError(f"no trades.parquet under {CONE}")
    df = pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    return df


def tag_regime(df: pd.DataFrame) -> pd.DataFrame:
    """One DB load over the full entry-date span; tag each trade bull/chop."""
    start = df["entry_date"].min().strftime("%Y-%m-%d")
    end = df["entry_date"].max().strftime("%Y-%m-%d")
    above = spy_above_200d(start, end)  # {date -> bool}
    above = pd.Series(above)
    above.index = pd.to_datetime(above.index)
    above = above.sort_index()
    # as-of: SPY>200d state known at each entry day's close (ffill for non-trading keys)
    df = df.sort_values("entry_date")
    df["bull"] = above.reindex(df["entry_date"], method="ffill").values
    n_na = df["bull"].isna().sum()
    if n_na:
        print(f"[WARN] {n_na} trades with no SPY state (pre-history) -> dropped")
        df = df[df["bull"].notna()]
    df["bull"] = df["bull"].astype(bool)
    return df


def dist(sub: pd.DataFrame) -> dict:
    p = sub["pnl_percent"]
    return {
        "n": len(sub),
        "mean": round(p.mean(), 2),
        "median": round(p.median(), 2),
        "%losing": round(100 * (p < 0).mean(), 1),
        "p10": round(p.quantile(0.10), 2),
        "p90": round(p.quantile(0.90), 2),
        "hold_d": round(sub["holding_days"].mean(), 1),
        "%stop": round(100 * (sub["exit_reason"] == "stop").mean(), 1),
    }


def main() -> None:
    df = tag_regime(load_trades())
    bull, chop = df[df["bull"]], df[~df["bull"]]
    print(f"\n{'='*72}\ntotal {len(df)} trades | bull(>200d) {len(bull)} | chop(<=200d) {len(chop)}\n{'='*72}")

    # --- headline: gate sweep on the BULL subset (the live-relevant question) ---
    print("\n### GATE SWEEP on BULL (SPY>200d) entries — the Q47 hunch ###")
    rows = []
    for g in GATES:
        d = dist(bull[bull["prob_elite"] >= g])
        d["gate"] = g
        rows.append(d)
    bull_tbl = pd.DataFrame(rows).set_index("gate")
    print(bull_tbl.to_string())

    # --- reference contrast: chop subset at the champion floor (NOT swept) ---
    print("\n### REFERENCE: chop (SPY<=200d) entries @ 0.15 floor — what the gate removes live ###")
    print(pd.DataFrame([dist(chop), dist(bull[bull["prob_elite"] >= 0.15])],
                       index=["chop@0.15", "bull@0.15"]).to_string())

    # --- the read: is a higher gate BETTER in bull, where pooled Q47 said worse? ---
    base = bull_tbl.loc[0.15]
    print(f"\n### READ (bull subset, vs 0.15 baseline) ###")
    for g in GATES[1:]:
        r = bull_tbl.loc[g]
        dm = r["median"] - base["median"]
        print(f"  gate {g}: median {r['median']:+.2f} (d{dm:+.2f}) | "
              f"mean {r['mean']:+.2f} | %losing {r['%losing']:.1f} | "
              f"p90 {r['p90']:+.2f} | n {r['n']} ({100*r['n']/base['n']:.0f}% kept)")
    print("\nGO/NO-GO: run a bull-only CONE only if a higher gate LIFTS the bull median "
          "(+distribution) where Q47's pooled sweep found it HURT. Trade-log only; "
          "cone confirms. If bull looks like pooled (median falls with gate) -> hunch dead, bank it.")


if __name__ == "__main__":
    main()
