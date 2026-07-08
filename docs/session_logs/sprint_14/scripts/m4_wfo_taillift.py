"""M4 model-level WFO on the SEPA-TRADES grain (d2_training_cache, mfe_pct native).

WHY this exists (verified 2026-07-08, not from prose):
  - m01_prototype is trained on EXACTLY this population: v_d2_training / d2_training_cache,
    filter mfe_pct IS NOT NULL, target = create_mfe_labels(mfe_pct, [2,10,30]) 4-class softprob,
    features = fs_m01_prototype (train_mfe_classifier.py). So mfe_pct IS the family outcome; the
    trades grain is m01's own home, not a compromise.
  - The SHIPPED prototype was trained no_holdout_85_15_0 (test_samples=0) -> it saw all 38k rows.
    Scoring it in-sample = inflated bar. So we WALK-FORWARD: expanding train, retrain per fold,
    score the held-out fold, cut tail-lift@k on OOS mfe_pct. Champion AND M4 judged the same way.

This one harness runs the CHAMPION re-cut (--target champion, step 1) and the M4 candidates
(--target A winsorized-magnitude reg, --target B tau=0.90 quantile) so the comparison is
apples-to-apples on identical folds. Fold models saved under models/m01_prototype_wfo/v1/
(NEVER overwrites the shipped m01_prototype_2003_2026/v1).

Smoke: --folds 2013 2015 (one/two folds). Full: default fold grid.

  python docs/session_logs/sprint_14/scripts/m4_wfo_taillift.py --target champion --smoke
"""
import argparse
import json
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import xgboost as xgb


def _root() -> Path:
    p = Path(__file__).resolve()
    for d in (p, *p.parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError("repo root not found")


ROOT = _root()
sys.path.insert(0, str(ROOT))
from src.utils import get_model_features  # noqa: E402

DB = ROOT / "data" / "market_data.duckdb"
CACHE_TBL = "d2_training_cache"
OUT = ROOT / "data" / "model_output_eda" / "m4_wfo"
MODEL_DIR = ROOT / "models" / "m01_prototype_wfo" / "v1"   # NEW version, never the shipped v1
FEATURE_SET = "fs_m01_prototype"
HR = 30.0                       # home-run / tail threshold, in mfe_pct UNITS (percent, not fraction)
MFE_BINS = [2.0, 10.0, 30.0]    # champion's 4-class edges

# expanding-window WFO: each fold trains on everything strictly before [test_start, test_end)
# and scores that 2-year OOS window. Pre-2013 is too thin per-year to be a test fold -> it seeds
# the first train set. (ponytail: fixed grid, not param-swept — this is a bar re-cut, not a tuner.)
DEFAULT_FOLDS = [
    (2013, 2015), (2015, 2017), (2017, 2019), (2019, 2021),
    (2021, 2023), (2023, 2025), (2025, 2027),
]

XGB_BASE = dict(max_depth=4, learning_rate=0.05, subsample=0.8,
                colsample_bytree=0.8, random_state=42, tree_method="hist")
NUM_BOOST_ROUND = 100
EARLY_STOPPING = 20


def _log(m: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def load_trades() -> tuple[pd.DataFrame, list[str]]:
    """Full trades cache, sorted by date, with sector/industry as category dtype (codes shared
    across all folds so train/OOS align — dodges the categorical-mismatch trap)."""
    feats = get_model_features("m01_prototype", db_path=str(DB))
    con = duckdb.connect(str(DB), read_only=True)
    try:
        df = con.execute(
            f"SELECT * FROM {CACHE_TBL} WHERE mfe_pct IS NOT NULL ORDER BY date, ticker"
        ).df()
    finally:
        con.close()
    df.columns = [c.lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    # match features case-insensitively to actual columns
    lower = {c.lower(): c for c in df.columns}
    valid = [lower[f.lower()] for f in feats if f.lower() in lower]
    missing = [f for f in feats if f.lower() not in lower]
    if missing:
        _log(f"WARN {len(missing)} features missing from cache: {missing}")
    for col in ("sector", "industry"):
        if col in df.columns:
            df[col] = df[col].astype("category")
    return df, valid


# ---- target builders: (name) -> (y, xgb_params, extract_score_fn) ------------------------------
def _softprob_params():
    p = dict(XGB_BASE); p.update(objective="multi:softprob", num_class=4, eval_metric="mlogloss")
    return p


def build_target(target: str, mfe: pd.Series):
    """Return (y, params, score_from_pred). score_from_pred maps raw booster output -> 1-D rank score.
    All three rank names by 'expected tail' — champion via P(Elite), A/B via predicted magnitude."""
    if target == "champion":
        # 4-class softprob; score = P(class 3 = Elite)
        conds = [(mfe > lo) & (mfe <= hi) for lo, hi in zip([-np.inf, *MFE_BINS], [*MFE_BINS, np.inf])]
        y = pd.Series(np.select(conds, range(4), default=0), index=mfe.index).astype(int)
        return y, _softprob_params(), lambda pred: pred[:, 3]
    if target == "A":
        # winsorized-magnitude regressor (null control). winsor at p99 to cap single-name blowups.
        cap = mfe.quantile(0.99)
        y = mfe.clip(upper=cap)
        p = dict(XGB_BASE); p.update(objective="reg:squarederror", eval_metric="rmse")
        return y, p, lambda pred: pred
    if target == "B":
        # tau=0.90 quantile regressor (the thesis: predict the upper conditional magnitude).
        y = mfe.copy()
        p = dict(XGB_BASE)
        p.update(objective="reg:quantileerror", quantile_alpha=0.90, eval_metric="mae")
        return y, p, lambda pred: pred
    raise ValueError(f"unknown target {target!r}")


def tail_lift(score: np.ndarray, tail: np.ndarray, fracs=(0.01, 0.05, 0.10, 0.25)) -> dict:
    N, tot = len(score), tail.sum()
    if tot <= 0 or N == 0:
        return {fr: np.nan for fr in fracs}
    order = np.argsort(-score)
    cum = np.cumsum(tail[order]) / tot
    return {fr: cum[int(fr * N) - 1] / fr for fr in fracs}


def run_fold(df, valid, target, test_start, test_end):
    tr = df[df["date"] < pd.Timestamp(f"{test_start}-01-01")]
    te = df[(df["date"] >= pd.Timestamp(f"{test_start}-01-01"))
            & (df["date"] < pd.Timestamp(f"{test_end}-01-01"))]
    if len(te) < 200 or len(tr) < 1000:
        _log(f"  fold {test_start}-{test_end}: SKIP (train={len(tr)} test={len(te)})")
        return None, None
    y_all, params, score_fn = build_target(target, df["mfe_pct"])
    Xtr = tr[valid].replace([np.inf, -np.inf], np.nan)
    Xte = te[valid].replace([np.inf, -np.inf], np.nan)
    # inner val = last 15% of train (temporal) for early stopping, mirroring the shipped recipe
    cut = int(len(Xtr) * 0.85)
    dtr = xgb.DMatrix(Xtr.iloc[:cut], label=y_all.loc[tr.index].iloc[:cut], enable_categorical=True)
    dval = xgb.DMatrix(Xtr.iloc[cut:], label=y_all.loc[tr.index].iloc[cut:], enable_categorical=True)
    dte = xgb.DMatrix(Xte, enable_categorical=True)
    booster = xgb.train(params, dtr, num_boost_round=NUM_BOOST_ROUND,
                        evals=[(dtr, "train"), (dval, "val")],
                        early_stopping_rounds=EARLY_STOPPING, verbose_eval=False)
    pred = booster.predict(dte)
    score = score_fn(pred)
    mfe_te = te["mfe_pct"].to_numpy()
    tail = np.maximum(mfe_te - HR, 0.0)
    lift = tail_lift(score, tail)
    # above-gate residual: for champion, gate at P(Elite)>=median-of-top? we report the
    # conditional lift among the top-decile score (matched budget) so all targets compare fairly.
    top10 = score >= np.quantile(score, 0.90)
    cond = tail_lift(score[top10], tail[top10]) if top10.sum() > 50 else {k: np.nan for k in lift}
    # save fold model (new version dir)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    mp = MODEL_DIR / f"{target}_fold_{test_start}_{test_end}.json"
    booster.save_model(str(mp))
    res = dict(target=target, test_start=test_start, test_end=test_end,
               n_train=len(tr), n_test=len(te), tail_total=float(tail.sum()),
               hr_rate=float((mfe_te > HR).mean()),
               lift1=lift[0.01], lift5=lift[0.05], lift10=lift[0.10],
               cond_lift10=cond[0.10], best_iter=int(booster.best_iteration), model=mp.name)
    _log(f"  fold {test_start}-{test_end}: n_te={len(te)} lift@1%={lift[0.01]:.2f} "
         f"lift@10%={lift[0.10]:.2f} cond@top10={cond[0.10]:.2f} (best_iter={booster.best_iteration})")
    # per-row OOS predictions for downstream regime-state stratification (M6 consumer).
    # emitting from HERE keeps this harness the single source of fold scores — no re-scoring.
    preds = pd.DataFrame({"date": te["date"].to_numpy(), "ticker": te["ticker"].to_numpy(),
                          "score": score, "mfe_pct": mfe_te, "test_start": test_start})
    return res, preds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["champion", "A", "B"], default="champion")
    ap.add_argument("--smoke", action="store_true", help="two folds only (2013-15, 2021-23)")
    ap.add_argument("--folds", type=int, nargs="+", help="explicit test_start years")
    ap.add_argument("--dump-preds", action="store_true",
                    help="also write per-row OOS (date,ticker,score,mfe_pct) for regime stratification")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    df, valid = load_trades()
    _log(f"loaded {len(df)} trades, {len(valid)} features, target={args.target}")

    if args.smoke:
        folds = [(2013, 2015), (2021, 2023)]
    elif args.folds:
        grid = {s: e for s, e in DEFAULT_FOLDS}
        folds = [(s, grid.get(s, s + 2)) for s in args.folds]
    else:
        folds = DEFAULT_FOLDS

    rows, pred_frames = [], []
    for ts, te in folds:
        r, preds = run_fold(df, valid, args.target, ts, te)
        if r:
            rows.append(r)
            pred_frames.append(preds)

    if not rows:
        _log("no folds ran"); return
    res = pd.DataFrame(rows)
    outp = OUT / f"wfo_{args.target}.csv"
    res.to_csv(outp, index=False)
    if args.dump_preds:
        pp = OUT / f"preds_{args.target}.parquet"
        pd.concat(pred_frames, ignore_index=True).to_parquet(pp, index=False)
        _log(f"saved per-row preds {pp}")
    _log(f"\n=== {args.target} WFO tail-lift (OOS mfe_pct, {len(res)} folds) ===")
    pd.set_option("display.width", 160)
    print(res[["test_start", "test_end", "n_test", "hr_rate", "lift1", "lift5",
               "lift10", "cond_lift10"]].to_string(index=False))
    for c in ("lift1", "lift10", "cond_lift10"):
        v = res[c].dropna()
        _log(f"  {c:<12} median {v.median():.2f}  min {v.min():.2f}  max {v.max():.2f}  "
             f"folds<1x: {(v < 1).sum()}/{len(v)}")
    _log(f"saved {outp}")
    # self-check: lift is a ratio in [0, 1/frac]; median finite for champion
    assert res["lift1"].between(0, 100).all(), "lift out of sane range"


if __name__ == "__main__":
    main()
