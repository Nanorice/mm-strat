"""Coincident trade-gauge — STEP 1b: does a MULTIVARIATE live-safe macro model
tell bad breakout-days from good ones BETTER than SPY-200d alone? (§0.5.3)

TARGET: binary BAD-day = bottom tercile of the cohort label (regime_gauge_label.py).
  Two label variants both tested: loss_mean (A) and hostility (B).
FEATURES (all LIVE-SAFE — from entry_timing_daily.parquet, built by entry_timing_features.py):
  spy_ret20/60/120, vix_close, vix_chg20, stress_ew_vix, stress_cr, stress_ew_rank.
  (raw pil_* LEVELS are non-stationary -> excluded; the expanding-z stress composites
   are the live-safe expression of the pillars.)
BASELINE: SPY_below_200d alone (the incumbent one-binary regime tool).
MODELS: logistic (interpretable signs — do pillars keep the C7 wrong sign?) + XGBoost.
VALIDATION: walk-forward by year (NO shuffled CV — days autocorrelate). AUC per fold,
  pooled OOS AUC, always vs the SPX200 baseline. Kill-criterion in the plan: no lift +
  wrong-sign pillars -> SPY-200d is the whole tool.

  python .../regime_gauge_train.py --smoke                 # loss_mean, print
  python .../regime_gauge_train.py --label hostility
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler


def _root() -> Path:
    p = Path(__file__).resolve()
    for d in (p, *p.parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError("repo root not found")


ROOT = _root()
GAUGE = ROOT / "data" / "model_output_eda" / "regime_gauge"
ET = ROOT / "data" / "model_output_eda" / "entry_timing" / "entry_timing_daily.parquet"

FEATURES = ["spy_ret20", "spy_ret60", "spy_ret120", "vix_close", "vix_chg20",
            "stress_ew_vix", "stress_cr", "stress_ew_rank"]
BAD_QUANTILE = 1 / 3            # bottom tercile of label-goodness = BAD day


def load_joined(label: str, horizon: str, weight: str) -> pd.DataFrame:
    lab_f = GAUGE / f"gauge_label_{horizon}_{weight}.parquet"
    if not lab_f.exists():
        raise FileNotFoundError(f"{lab_f} missing — run regime_gauge_label.py first")
    lab = pd.read_parquet(lab_f)
    et = pd.read_parquet(ET)
    et["date"] = pd.to_datetime(et["date"])
    lab["date"] = pd.to_datetime(lab["date"])
    df = lab.merge(et[["date", "spy_above200"] + FEATURES], on="date", how="inner")

    # binary BAD-day target. loss_mean: LOWER = worse -> bad = bottom tercile.
    # hostility: HIGHER = worse -> bad = TOP tercile. Normalize so bad=1 either way.
    if label == "loss_mean":
        cut = df[label].quantile(BAD_QUANTILE)
        df["bad"] = (df[label] <= cut).astype(int)
    else:  # hostility
        cut = df[label].quantile(1 - BAD_QUANTILE)
        df["bad"] = (df[label] >= cut).astype(int)
    df = df.dropna(subset=FEATURES + ["bad"]).sort_values("date").reset_index(drop=True)
    df["year"] = df["date"].dt.year
    return df


def walk_forward(df: pd.DataFrame) -> pd.DataFrame:
    """Expanding walk-forward by year: train on all prior years, score the year.
    Returns per-row OOS predictions for logistic, xgb, and the baseline."""
    from xgboost import XGBClassifier
    years = sorted(df["year"].unique())
    preds = []
    for i, yr in enumerate(years):
        tr = df[df["year"] < yr]
        te = df[df["year"] == yr]
        if len(tr) < 252 or te.empty or tr["bad"].nunique() < 2:
            continue
        Xtr, Xte = tr[FEATURES].values, te[FEATURES].values
        ytr = tr["bad"].values

        sc = StandardScaler().fit(Xtr)
        lr = LogisticRegression(max_iter=1000, C=1.0).fit(sc.transform(Xtr), ytr)
        p_lr = lr.predict_proba(sc.transform(Xte))[:, 1]

        xgb = XGBClassifier(n_estimators=120, max_depth=3, learning_rate=0.05,
                            subsample=0.8, colsample_bytree=0.8, eval_metric="logloss",
                            n_jobs=4, verbosity=0).fit(Xtr, ytr)
        p_xgb = xgb.predict_proba(Xte)[:, 1]

        # baseline: SPY below 200d = predicted bad. (spy_above200 in {0,1} -> p_bad = 1-it)
        p_base = 1.0 - te["spy_above200"].values

        preds.append(pd.DataFrame({
            "date": te["date"].values, "year": yr, "bad": te["bad"].values,
            "p_lr": p_lr, "p_xgb": p_xgb, "p_base": p_base}))
    return pd.concat(preds, ignore_index=True)


def _auc(y, p) -> float:
    return roc_auc_score(y, p) if len(np.unique(y)) > 1 else float("nan")


def report(oos: pd.DataFrame, df: pd.DataFrame, label: str) -> None:
    print(f"\n=== OOS walk-forward, target=BAD-day from '{label}' "
          f"(n={len(oos)}, bad-rate={oos['bad'].mean():.1%}) ===")
    print(f"{'':22}{'pooled AUC':>12}")
    for name, col in [("SPY-200d baseline", "p_base"), ("logistic (multivar)", "p_lr"),
                      ("xgboost (multivar)", "p_xgb")]:
        print(f"{name:22}{_auc(oos['bad'], oos[col]):>12.3f}")

    # per-year AUC (baseline vs best model) — where does multivar help/hurt?
    print(f"\nper-year AUC  {'base':>8}{'logit':>8}{'xgb':>8}{'lift(logit-base)':>18}")
    for yr, g in oos.groupby("year"):
        b, l, x = _auc(g["bad"], g["p_base"]), _auc(g["bad"], g["p_lr"]), _auc(g["bad"], g["p_xgb"])
        print(f"  {yr}      {b:>8.3f}{l:>8.3f}{x:>8.3f}{l-b:>+18.3f}")

    # logistic coefficient SIGNS on full data — do pillars keep C7's wrong sign?
    sc = StandardScaler().fit(df[FEATURES].values)
    lr = LogisticRegression(max_iter=1000).fit(sc.transform(df[FEATURES].values), df["bad"].values)
    print("\nlogistic coefs (standardized; + => pushes toward BAD-day):")
    for f, c in sorted(zip(FEATURES, lr.coef_[0]), key=lambda t: -abs(t[1])):
        print(f"  {f:16}{c:+.3f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="loss_mean", choices=["loss_mean", "hostility"])
    ap.add_argument("--horizon", default="fwd20")
    ap.add_argument("--weight", default="downside")
    ap.add_argument("--smoke", action="store_true", help="print only (same path; label parquet must exist)")
    args = ap.parse_args()

    df = load_joined(args.label, args.horizon, args.weight)
    print(f"joined {len(df)} days ({df['date'].min().date()}->{df['date'].max().date()}), "
          f"features={len(FEATURES)}")
    oos = walk_forward(df)
    report(oos, df, args.label)


if __name__ == "__main__":
    main()
