"""M6 consumer #1: is M4's tail-ranking edge regime-dependent — NON-circularly?

The M4 smoke's "dies in the GFC" was CIRCULAR: it labelled the single worst fold
"bad" because it was the weakest ([[project_regime_during_period_goal]]). Here we
join M4's per-row OOS predictions (preds_A.parquet from m4_wfo_taillift --dump-preds)
to the INDEPENDENT regime_state label (date -> bull-calm/bull-stress/bear) and cut
the SAME metric WITHIN each state. If cond_lift10 collapses in bear but holds in
bull-calm, the pro-cyclicality is real; if it's flat across states, the earlier
GFC story was noise.

Metric recap (from M4): tail = max(mfe_pct - 30, 0); tail-lift@k = share of total
tail held by the top-k% of score / k; cond_lift10 = tail-lift@10% computed WITHIN
the top-decile of score = does the score rank the big winners among its own elite.
Cut per state using THAT state's own score decile + own tail total (self-contained,
so states are comparable at matched budget).

  python docs/session_logs/sprint_14/scripts/m4_by_regime_state.py
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

def _root() -> Path:
    """Walk up to the repo root (has config.py + src/). Robust to file depth/CWD."""
    for d in (Path(__file__).resolve(), *Path(__file__).resolve().parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError("repo root not found")


ROOT = _root()
EDA = ROOT / "data" / "model_output_eda"
PREDS = EDA / "m4_wfo" / "preds_A.parquet"          # target A = the M4 winner
OUT = EDA / "regime_state"
HR = 30.0
STATES = ["bull-calm", "bull-stress", "bear"]


def _log(m: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def tail_lift(score: np.ndarray, tail: np.ndarray, fracs=(0.01, 0.05, 0.10)) -> dict:
    n, tot = len(score), tail.sum()
    if tot <= 0 or n == 0:
        return {fr: np.nan for fr in fracs}
    order = np.argsort(-score)
    cum = np.cumsum(tail[order]) / tot
    return {fr: cum[int(fr * n) - 1] / fr for fr in fracs}


def cond_lift10(score: np.ndarray, tail: np.ndarray) -> float:
    """tail-lift@10% among the top-decile of score (the M4 mechanism metric)."""
    if len(score) < 50:
        return np.nan
    top = score >= np.quantile(score, 0.90)
    if top.sum() < 20:
        return np.nan
    return tail_lift(score[top], tail[top])[0.10]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--axis", choices=["macro", "dd"], default="dd",
                    help="which regime label to stratify by (default dd = realized drawdown/vol)")
    args = ap.parse_args()
    state_path = OUT / f"regime_state_daily_{args.axis}.parquet"

    if not PREDS.exists():
        _log(f"MISSING {PREDS} — run: m4_wfo_taillift.py --target A --dump-preds"); sys.exit(1)
    if not state_path.exists():
        _log(f"MISSING {state_path} — run: regime_state.py --axis {args.axis}"); sys.exit(1)
    preds = pd.read_parquet(PREDS)
    state = pd.read_parquet(state_path)[["date", "state"]]
    preds["date"] = pd.to_datetime(preds["date"])
    state["date"] = pd.to_datetime(state["date"])
    df = preds.merge(state, on="date", how="left")

    unlabelled = df["state"].isna().sum()
    _log(f"{len(df)} OOS rows, {unlabelled} unlabelled (dates outside 2013+ state span)")
    df = df.dropna(subset=["state"]).copy()
    df["tail"] = np.maximum(df["mfe_pct"] - HR, 0.0)

    # per-state metrics on the POOLED OOS rows in that state (self-contained decile + tail total)
    rows = []
    for s in STATES:
        g = df[df["state"] == s]
        sc, tl = g["score"].to_numpy(), g["tail"].to_numpy()
        lift = tail_lift(sc, tl)
        rows.append(dict(state=s, n=len(g), hr_rate=float((g["mfe_pct"] > HR).mean()),
                         tail_total=float(tl.sum()), lift1=lift[0.01], lift5=lift[0.05],
                         lift10=lift[0.10], cond_lift10=cond_lift10(sc, tl)))
    pooled = df[["score", "tail", "mfe_pct"]]
    lift = tail_lift(pooled["score"].to_numpy(), pooled["tail"].to_numpy())
    rows.append(dict(state="ALL", n=len(df), hr_rate=float((df["mfe_pct"] > HR).mean()),
                     tail_total=float(pooled["tail"].sum()), lift1=lift[0.01], lift5=lift[0.05],
                     lift10=lift[0.10], cond_lift10=cond_lift10(pooled["score"].to_numpy(),
                                                                pooled["tail"].to_numpy())))
    res = pd.DataFrame(rows)

    OUT.mkdir(parents=True, exist_ok=True)
    outp = OUT / f"m4_by_state_{args.axis}.csv"
    res.to_csv(outp, index=False)
    pd.set_option("display.width", 160)
    print()
    print(f"=== M4 target-A tail-ranking BY regime state — axis={args.axis} (pooled OOS, 2013-2026) ===")
    print(res[["state", "n", "hr_rate", "lift1", "lift10", "cond_lift10"]].to_string(index=False))
    _log(f"saved {outp}")

    # the honest read: is cond_lift10 monotone bull-calm > bull-stress > bear? that would be
    # the NON-circular pro-cyclicality. Flag it plainly either way.
    cl = {r["state"]: r["cond_lift10"] for _, r in res.iterrows()}
    print()
    mono = cl["bull-calm"] >= cl["bull-stress"] >= cl["bear"]
    print(f"cond_lift10: bull-calm {cl['bull-calm']:.2f} | bull-stress {cl['bull-stress']:.2f} "
          f"| bear {cl['bear']:.2f}  -> {'PRO-CYCLICAL (monotone)' if mono else 'NOT monotone'}")
    # self-check: pooled lift@1% in sane ratio range, every state got rows
    assert res["lift1"].between(0, 100).all(), "lift out of range"
    assert (res.loc[res.state.isin(STATES), "n"] > 0).all(), "an empty state"


if __name__ == "__main__":
    main()
