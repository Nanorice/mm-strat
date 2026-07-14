"""Floor-lift cone comparison: DD-breaker + earnings-blackout overlays vs the
champion_trail_spygate baseline (§1.1 + earnings arms, 90-cell paired cone).

Reads the persisted per-cell summary.json for each arm, pairs by cell, and
reports the cone DISTRIBUTION (median Sharpe, floor, %neg, IQR, maxDD) — the
floor-lift test, judged on the distribution not aggregate return
(project_champion_starttime_dependent). An overlay only earns promotion if it
LIFTS THE FLOOR without killing the median (the recurring variance-vs-median
test that killed the governor).

Usage: python overlay_cone_compare.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
CONE = ROOT / "data/selection_sweep/starttime"
BASELINE = "champion_trail_spygate"
ARMS = ["champion_trail_spygate_ddbrake6", "champion_trail_spygate_ddbrake10",
        "champion_trail_spygate_ddbrake15", "champion_trail_spygate_ddbrake20",
        "champion_trail_spygate_ddbrake30", "champion_trail_spygate_earn5"]


def load(arm: str) -> pd.DataFrame:
    f = CONE / arm / "rolling/summary.json"
    if not f.exists():
        raise FileNotFoundError(f"missing {f} — has the cone finished?")
    cells = json.loads(f.read_text())["cells"]
    df = pd.DataFrame(cells).set_index("cell")
    return df[["sharpe", "max_drawdown", "total_return"]]


def cone_stats(s: pd.Series) -> dict:
    return {
        "median": round(s.median(), 3),
        "mean": round(s.mean(), 3),
        "floor": round(s.min(), 3),
        "p25": round(s.quantile(0.25), 3),
        "p90": round(s.quantile(0.90), 3),
        "%neg": round(100 * (s < 0).mean(), 1),
    }


def main() -> None:
    base = load(BASELINE)
    print(f"baseline = {BASELINE}  ({len(base)} cells)\n")

    for arm in ARMS:
        try:
            a = load(arm)
        except FileNotFoundError as e:
            print(f"[SKIP] {arm}: {e}\n")
            continue
        # pair by cell (inner join; both are the same 90-cell grid)
        j = base.join(a, lsuffix="_base", rsuffix="_arm", how="inner")
        print(f"{'='*72}\n{arm}  vs baseline  ({len(j)} paired cells)\n{'='*72}")

        for metric in ["sharpe", "max_drawdown", "total_return"]:
            b = cone_stats(j[f"{metric}_base"])
            r = cone_stats(j[f"{metric}_arm"])
            print(f"\n-- {metric} --")
            print(f"  baseline: {b}")
            print(f"  {arm.split('_')[-1]:>9}: {r}")
            # deltas on the floor-lift-relevant stats
            if metric == "sharpe":
                print(f"  Δ median {r['median']-b['median']:+.3f} | "
                      f"Δ floor {r['floor']-b['floor']:+.3f} | "
                      f"Δ %neg {r['%neg']-b['%neg']:+.1f}pp")
            if metric == "max_drawdown":
                print(f"  Δ floor(worst DD) {r['floor']-b['floor']:+.3f} | "
                      f"Δ median DD {r['median']-b['median']:+.3f}")

        # paired win-rate on Sharpe (context, not the verdict — pairs mislead
        # when the overlay is inert in bull windows; judge distribution)
        wins = (j["sharpe_arm"] > j["sharpe_base"]).sum()
        diff = (j["sharpe_arm"] != j["sharpe_base"]).sum()
        print(f"\n  paired: arm beats baseline in {wins}/{len(j)} cells "
              f"({diff} differ — overlay inert in the rest)")
        print(f"\n  READ: floor-lift earns promotion only if floor UP + median NOT killed. "
              f"If the arm is inert in most cells (differ small), the overlay only "
              f"fires in the whipsaw/bleed cells — that's expected; weight those.\n")


if __name__ == "__main__":
    main()
