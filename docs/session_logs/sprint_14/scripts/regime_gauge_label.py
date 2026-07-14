"""Coincident trade-gauge — STEP 1a: build the per-day cohort label (§0.5.3 of
`plans/2026-07-13_regime_tiering_and_system_usage.md`).

WHAT: one row per trading day. For the SEPA-candidate cohort entering that day
(the t3-scored universe in `multiyear/raw_full_*_fwd.parquet` — model-AGNOSTIC,
we use ONLY fwd returns, never the m01 score), summarize how hostile the tape was
to breakouts-as-a-class:

  (A) loss_mean : cohort mean of a LOSS-WEIGHTED fwd return. Default weight =
      downside-only (min(fwd,0)) so a day where breakouts bled scores worse than
      the plain mean. The weight is a one-line-swappable registry entry (LOSS_WEIGHTS).
  (B) hostility  : fraction of the cohort whose fwd return <= HOSTILE_THRESH
      (default -0.15, the 15% stop) — the §0.3 "71% stopped out" failure mode.

Both are COINCIDENT labels (built from future fwd, knowable only in hindsight);
the classifier (step 1b) learns to nowcast them from live-safe features.

HORIZON is parameterized (--horizon fwd20|fwd50|fwd100): fwd20 first cut, infra
ready for fwd50/100 next iteration (regime gap triples fwd20->fwd100).

  python .../regime_gauge_label.py --smoke                 # 3 years, print + self-check
  python .../regime_gauge_label.py                         # full 25y -> parquet
  python .../regime_gauge_label.py --horizon fwd100 --weight semivar
"""
from __future__ import annotations

import argparse
import glob
import sys
import time
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd


def _root() -> Path:
    p = Path(__file__).resolve()
    for d in (p, *p.parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError("repo root not found")


ROOT = _root()
CACHE = ROOT / "data" / "model_output_eda" / "multiyear"
OUT = ROOT / "data" / "model_output_eda" / "regime_gauge"
HOSTILE_THRESH = -0.15          # label B: fwd <= this counts as a stop-out
MIN_COHORT = 20                 # days with fewer names are too thin to trust -> dropped


# --- loss-weight registry: swap the label-(A) weighting in ONE line ----------
# each maps a cohort's fwd Series -> a per-row weighted value; day label = mean of it.
LOSS_WEIGHTS: dict[str, Callable[[pd.Series], pd.Series]] = {
    "downside": lambda f: f.clip(upper=0.0),                 # DEFAULT: min(fwd,0), the loss only
    "semivar":  lambda f: -f.clip(upper=0.0) ** 2,           # convex; squares big losses (sign kept: higher=better)
    "plain":    lambda f: f,                                 # ablation: unweighted cohort mean
}
DEFAULT_WEIGHT = "downside"


def load_cohort() -> pd.DataFrame:
    """All years of the t3-scored SEPA cohort. Keep ONLY date + the fwd columns
    (model-agnostic — prob_elite deliberately dropped)."""
    fs = sorted(glob.glob(str(CACHE / "raw_full_*_fwd.parquet")))
    if not fs:
        raise FileNotFoundError(f"no cohort parquets in {CACHE}")
    frames = []
    for f in fs:
        df = pd.read_parquet(f, columns=None)
        keep = ["date"] + [c for c in df.columns if c.startswith("fwd")]
        frames.append(df[keep])
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"])
    return out.sort_values("date").reset_index(drop=True)


def build_label(cohort: pd.DataFrame, horizon: str, weight: str) -> pd.DataFrame:
    """Collapse the cohort to one row/day: loss_mean (A) + hostility (B) + n."""
    if horizon not in cohort.columns:
        raise ValueError(f"{horizon} not in cohort cols {[c for c in cohort if c.startswith('fwd')]}")
    if weight not in LOSS_WEIGHTS:
        raise ValueError(f"weight '{weight}' not in {list(LOSS_WEIGHTS)}")
    wfn = LOSS_WEIGHTS[weight]
    d = cohort[["date", horizon]].dropna(subset=[horizon]).copy()

    def agg(g: pd.DataFrame) -> pd.Series:
        f = g[horizon]
        return pd.Series({
            "n": len(f),
            "loss_mean": wfn(f).mean(),                      # label A (weighted)
            "hostility": (f <= HOSTILE_THRESH).mean(),       # label B (stop-out rate)
            "raw_mean": f.mean(),                            # reference (unweighted)
        })

    lab = d.groupby("date").apply(agg, include_groups=False).reset_index()
    lab = lab[lab["n"] >= MIN_COHORT].reset_index(drop=True)
    lab["horizon"] = horizon
    lab["weight"] = weight
    return lab


def _self_check(lab: pd.DataFrame) -> None:
    # A and B must both flag the same bad days: they should be strongly correlated.
    r = lab["loss_mean"].corr(lab["hostility"], method="spearman")
    assert r < 0, f"loss_mean (higher=better) vs hostility (higher=worse) should be NEG corr, got {r:+.2f}"
    # downside label is <= raw mean by construction (it only counts losses)
    assert (lab["loss_mean"] <= lab["raw_mean"] + 1e-9).all(), "loss_mean must be <= raw_mean"
    assert (lab["hostility"].between(0, 1)).all()
    print(f"[self-check] OK  loss_mean~hostility spearman={r:+.2f}  n_days={len(lab)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", default="fwd20", choices=["fwd20", "fwd50", "fwd100"])
    ap.add_argument("--weight", default=DEFAULT_WEIGHT, choices=list(LOSS_WEIGHTS))
    ap.add_argument("--smoke", action="store_true", help="last 3 years only, print, no write")
    args = ap.parse_args()

    t0 = time.time()
    cohort = load_cohort()
    if args.smoke:
        cutoff = cohort["date"].max() - pd.Timedelta(days=365 * 3)
        cohort = cohort[cohort["date"] >= cutoff]
    print(f"cohort: {len(cohort):,} rows, {cohort['date'].nunique()} days "
          f"({cohort['date'].min().date()}->{cohort['date'].max().date()})  [{time.time()-t0:.1f}s]")

    lab = build_label(cohort, args.horizon, args.weight)
    _self_check(lab)
    print(f"\nlabel head ({args.horizon}, weight={args.weight}):")
    print(lab.head().to_string(index=False))
    print(f"\nbottom-tercile (BAD-day) cutoff loss_mean={lab['loss_mean'].quantile(1/3):+.4f}  "
          f"hostility p67={lab['hostility'].quantile(2/3):.3f}")

    if not args.smoke:
        OUT.mkdir(parents=True, exist_ok=True)
        f = OUT / f"gauge_label_{args.horizon}_{args.weight}.parquet"
        lab.to_parquet(f, index=False)
        print(f"\nwrote {f.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
