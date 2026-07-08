"""M6: a quantified, model-agnostic REGIME STATE label (date -> named state).

WHAT this is (user steer 2026-07-08, [[project_regime_during_period_goal]]):
  NOT a leading/timing signal. A COINCIDENT state EXPRESSION we can join to ANY
  population (M4 folds, SEPA candidates, future models) to characterize how the
  strategy behaves DURING each state. The reusable artifact is the date->state map.

STATE = f(stress composite, SPY>200d), reusing the LIVE-SAFE machinery already
built + validated in entry_timing_features.py (Thread F): expanding-z of the
6-pillar macro (+credit, -rates, -cape, +vix), and the SPY-above-200d bull flag.
Both are live-safe (day t uses only stats through t-1). Discrete named states:

    bear         : SPY <= 200d MA         (downtrend — regardless of stress)
    bull-stress  : SPY > 200d & stress HIGH (top tercile of live stress)
    bull-calm    : SPY > 200d & stress not high

  Rationale for the split (from Thread F findings): the stress axis flips sign by
  trend — high stress is a BUY tilt in bull, a falling-knife in bear
  ([[project_entry_timing_macro_axis]]). So bear is its own state; stress only
  sub-divides the bull side. Terciles cut on the LIVE (expanding) stress so the
  boundary itself carries no look-ahead.

TWO AXES for the bull sub-split (bear = SPY<=200d is shared):
  --axis dd    (DEFAULT, recommended): realized SPY drawdown-from-peak >= 10%. Price-only,
               STATIONARY, live-safe, spans the FULL 25y (reaches 2001/2008). No macro gap,
               no expanding-z drift.
  --axis macro: top-tercile of expanding-z macro stress (stress_ew_vix). LEAKY + 2013+ only,
               kept ONLY for the review-cell comparison, NOT recommended.

WHY the macro axis is LEAKY (verified 2026-07-08 — the reason the dd axis exists): two problems.
(1) COVERAGE: the stress composite is only fully populated 2013+ (credit 2003-01, CAPE_OURS
2012-12), so it can't see 2001/2008. (2) DRIFT: the expanding-z is mechanically higher in early
years (short history -> wider z), so a static tercile FRONT-LOADS "stress" into 2013-2016 (2013 =
88% stressed, 2017/2025 = 0%). The macro "bull-stress" is thus confounded with TIME, not just
stress level. The dd axis has neither problem: drawdown is absolute, stationary, full-history. The
macro axis stays only so the cells can SHOW the difference and justify the switch.

  python docs/session_logs/sprint_14/scripts/regime_state.py --smoke        # self-check (dd)
  python docs/session_logs/sprint_14/scripts/regime_state.py                # write dd label
  python docs/session_logs/sprint_14/scripts/regime_state.py --axis macro   # write macro label
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

def _root() -> Path:
    """Walk up to the repo root (has config.py + src/). Robust to file depth/CWD."""
    for d in (Path(__file__).resolve(), *Path(__file__).resolve().parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError("repo root not found")


ROOT = _root()
DB = ROOT / "data" / "market_data.duckdb"
OUT = ROOT / "data" / "model_output_eda" / "regime_state"

# reuse the exact pillar loader + expanding-z + composite from Thread F — do NOT
# re-implement (ponytail: the live-safe machinery is already built and validated)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from entry_timing_features import load_macro_pillars_raw, add_stress_score  # noqa: E402

STRESS_COL = "stress_ew_vix"       # Thread F's best live-safe composite (F5)
STRESS_HI_Q = 2 / 3                # top tercile of live stress = "stressed"
CLEAN_ERA = "2013-01-01"           # first date all 4 pillars are live (see COVERAGE)
DD_HI = 0.10                       # SPY drawdown-from-peak >= 10% = "stressed" (realized axis)
STATES = ["bear", "bull-stress", "bull-calm"]


def _log(m: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def _spy_market_state() -> pd.DataFrame:
    """SPY-derived, price-only, LIVE-SAFE market state — stationary + full 25y (no macro gap).
      spy_above200 : close > 200d MA (bull/bear trend axis)
      spy_dd       : drawdown from running peak (>=0), a realized crash/stress axis
      spy_vol20    : 20d realized vol of daily returns, annualized
    All use only past closes -> no look-ahead. This is the axis that reaches 2008 and doesn't
    drift the way the expanding-z macro stress does (see regime_state header)."""
    con = duckdb.connect(str(DB), read_only=True)
    try:
        spy = con.execute(
            "SELECT date, spy_close FROM t1_macro WHERE spy_close IS NOT NULL ORDER BY date"
        ).df()
    finally:
        con.close()
    spy["date"] = pd.to_datetime(spy["date"])
    c = spy["spy_close"]
    spy["spy_above200"] = (c > c.rolling(200).mean()).astype("float")
    spy["spy_dd"] = 1.0 - c / c.cummax()                       # 0 at highs, grows in selloffs
    ret = c.pct_change()
    spy["spy_vol20"] = ret.rolling(20).std() * np.sqrt(252)
    return spy[["date", "spy_above200", "spy_dd", "spy_vol20"]]


def build_state_label(axis: str = "macro") -> pd.DataFrame:
    """date -> {stress cols, spy_above200, spy_dd, spy_vol20, state}. One row / trading day.

    axis:
      'macro' — bull sub-split by top-tercile macro stress (stress_ew_vix). LEAKY: the
                expanding-z drifts, so the static tercile is front-loaded (mostly early years).
                Kept for the comparison in the review cells; NOT the recommended state.
      'dd'    — bull sub-split by SPY drawdown-from-peak >= DD_HI (realized, stationary, no
                time-drift). The vol/drawdown axis. Available full 25y (reaches 2008).
    Both share the same bear = SPY<=200d trunk.
    """
    spy = _spy_market_state()
    if axis == "macro":
        pillars = load_macro_pillars_raw()
        day = add_stress_score(pillars).merge(spy, on="date", how="inner")
        day = day.sort_values("date").reset_index(drop=True)
        day = day[day["date"] >= CLEAN_ERA].reset_index(drop=True)   # macro stress clean only 2013+
        hi_cut = day[STRESS_COL].quantile(STRESS_HI_Q)
        stressed = day[STRESS_COL] >= hi_cut
    elif axis == "dd":
        # realized axis: no macro dependency -> full span. stationary threshold (10% drawdown),
        # no era-scoping needed. (ponytail: fixed 10% cut, absolute + interpretable; make it a
        # rolling percentile only if 10% proves regime-specific.)
        day = spy.sort_values("date").reset_index(drop=True)
        stressed = day["spy_dd"] >= DD_HI
    else:
        raise ValueError(f"axis must be 'macro' or 'dd', got {axis!r}")

    bull = day["spy_above200"] == 1
    day["state"] = np.select(
        [~bull, bull & stressed, bull & ~stressed],
        ["bear", "bull-stress", "bull-calm"],
        default="bull-calm",
    )
    cols = ["date", "spy_above200", "spy_dd", "spy_vol20", "state"]
    if STRESS_COL in day.columns:
        cols.insert(1, STRESS_COL)
    return day[cols]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--axis", choices=["macro", "dd"], default="dd",
                    help="dd = realized drawdown/vol axis (stationary, full 25y, default); "
                         "macro = leaky expanding-z stress tercile (2013+ only, for comparison)")
    ap.add_argument("--smoke", action="store_true", help="build + self-check, no full write")
    args = ap.parse_args()

    df = build_state_label(axis=args.axis)
    _log(f"built state label (axis={args.axis}): {len(df)} days, "
         f"{df.date.min().date()}..{df.date.max().date()}")

    counts = df["state"].value_counts()
    _log("state distribution:")
    for s in STATES:
        n = int(counts.get(s, 0))
        print(f"    {s:<12} {n:>6}  ({n / len(df):.1%})", flush=True)

    # self-checks: every day labelled, every state used, bear == SPY-below-200d exactly
    assert df["state"].notna().all(), "unlabelled days"
    assert set(df["state"].unique()) <= set(STATES), "unexpected state"
    bear_matches = ((df["state"] == "bear") == (df["spy_above200"] == 0)).all()
    assert bear_matches, "bear must equal SPY<=200d"
    assert (df["state"] == "bull-stress").any(), "no stressed bull days — threshold broke"

    if not args.smoke:
        OUT.mkdir(parents=True, exist_ok=True)
        outp = OUT / f"regime_state_daily_{args.axis}.parquet"
        df.to_parquet(outp, index=False)
        _log(f"wrote {outp.relative_to(ROOT)}")
    else:
        _log("smoke OK — self-checks passed, nothing written")


if __name__ == "__main__":
    main()
