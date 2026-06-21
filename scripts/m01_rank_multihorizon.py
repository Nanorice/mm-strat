"""
m01_rank multi-horizon term-structure analysis.

User directive (2026-05-22): blindly delaying SEPA entry on a single signal is
improper. Instead train m01_rank variants at several prediction horizons and use
the SHAPE across horizons to time entry — e.g. if 20d return is expected positive
but 1d/5d is negative, the name is good but dips first => delay entry, buy the dip.

This script:
  1. Loads the dense t3 panel ONCE; builds a forward-return home-run target at
     each horizon H in {1,5,10,20}, thresholds tuned to ~6% base rate so the
     variants are comparable in rarity.
  2. Trains an XGBClassifier(binary:logistic) per horizon on <train_end (same
     spec as m01_rank.ipynb), scores the OOS window. Daily cross-sectional
     percentile per horizon = prob_pct_H.
  3. Validates each variant predicts ITS OWN horizon (per-ticker IC).
  4. Cross-horizon score correlation (are the horizons redundant or distinct?).
  5. Delay-entry cohort: on breakout days, high 20d-score + low short-horizon
     score -> realized short-horizon drawdown vs 20d forward return.

Forward returns from price_data.close, adjacency-guarded (t3 shift unsafe;
adj_close NULL). Leakage-clean: trained <train_end, evaluated OOS.

Usage:
    python scripts/m01_rank_multihorizon.py --train-end 2020-01-01 \
        --start 2020-01-01 --end 2024-12-31
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.m01_rank_scorer import load_dense_window, select_features, _fit
from scripts.validate_m01_rank_skill import fwd_returns_and_drawdown
import duckdb
import config

DB_PATH = str(config.DATA_DIR / "market_data.duckdb")

# Horizon -> threshold tuned to ~6% positive rate on pre-2021 dense rows.
HORIZON_THR = {1: 0.04, 5: 0.10, 10: 0.15, 20: 0.20}


def train_score_all_horizons(train_end, score_start, score_end, load_start="2016-01-01"):
    """Load dense once, train one classifier per horizon, return a wide scored df:
    (date, ticker, prob_1, prob_pct_1, prob_5, prob_pct_5, ...)."""
    load_end = (pd.Timestamp(score_end) + pd.Timedelta(days=max(HORIZON_THR) * 2)).strftime("%Y-%m-%d")
    print(f"Loading dense t3 {load_start}..{load_end} (once)...")
    df = load_dense_window(load_start, load_end).sort_values(["ticker", "date"])
    from src.evaluation.data_quality import warmup_clip
    df = warmup_clip(df)

    g = df.groupby("ticker", group_keys=False)
    for h in HORIZON_THR:
        df[f"_fwd_{h}"] = g["close"].shift(-h) / df["close"] - 1.0

    feature_cols = select_features(df)
    # strip our temp fwd cols from features
    feature_cols = [c for c in feature_cols if not c.startswith("_fwd_")]

    tr_mask = df["date"] < pd.Timestamp(train_end)
    te_mask = (df["date"] >= pd.Timestamp(score_start)) & (df["date"] <= pd.Timestamp(score_end))
    Xtr_base = df.loc[tr_mask, feature_cols].copy()
    for c in Xtr_base.select_dtypes(include=["object", "category"]).columns:
        Xtr_base[c] = Xtr_base[c].astype("category")
    Xte_base = df.loc[te_mask, feature_cols].copy()
    for c in Xte_base.select_dtypes(include=["object", "category"]).columns:
        Xte_base[c] = Xte_base[c].astype("category")

    scored = df.loc[te_mask, ["date", "ticker"]].copy()
    scored["date"] = pd.to_datetime(scored["date"])
    for h, thr in HORIZON_THR.items():
        ytr = (df.loc[tr_mask, f"_fwd_{h}"] > thr).astype(int)
        valid = df.loc[tr_mask, f"_fwd_{h}"].notna()
        m = _fit(Xtr_base[valid].copy(), ytr[valid])
        prob = m.predict_proba(Xte_base)[:, 1]
        scored[f"prob_{h}"] = prob
        scored[f"prob_pct_{h}"] = scored.groupby("date")[f"prob_{h}"].rank(pct=True)
        pos = float(ytr[valid].mean())
        print(f"  H={h:2d} (thr={thr}): trained on {valid.sum():,} rows, "
              f"base rate {pos:.3f}, OOS prob mean {prob.mean():.3f}")
    return scored


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-end", default="2020-01-01")
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2024-12-31")
    args = ap.parse_args()

    scored = train_score_all_horizons(args.train_end, args.start, args.end)
    print(f"Scored {len(scored):,} rows / {scored['ticker'].nunique()} tickers")

    # Forward returns + drawdowns (reuse skill-validation helper) at our horizons
    print("Computing forward returns + drawdowns...")
    fwd = fwd_returns_and_drawdown(args.start, args.end, horizons=tuple(HORIZON_THR))
    m = scored.merge(fwd, on=["ticker", "date"], how="inner")

    # breakout flag
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        bo = con.execute(
            "SELECT ticker, date, breakout_ok FROM t3_sepa_features "
            "WHERE feature_version='v3.1' AND date >= ? AND date <= ?",
            [args.start, args.end]).df()
    finally:
        con.close()
    bo["date"] = pd.to_datetime(bo["date"])
    m = m.merge(bo, on=["ticker", "date"], how="left")

    # 1. Each variant predicts its OWN horizon? (per-ticker IC)
    print("\n=== Each horizon's per-ticker IC vs its OWN forward return ===")
    rows = []
    for h in HORIZON_THR:
        ics = []
        for _, gg in m.groupby("ticker"):
            s = gg[[f"prob_{h}", f"fwd_ret_{h}"]].replace([np.inf, -np.inf], np.nan).dropna()
            if len(s) >= 30 and s[f"prob_{h}"].nunique() > 1:
                ic = stats.spearmanr(s[f"prob_{h}"], s[f"fwd_ret_{h}"]).correlation
                if not np.isnan(ic):
                    ics.append(ic)
        ics = np.array(ics)
        rows.append({"horizon": h, "ic_ticker_mean": float(ics.mean()),
                     "pct_pos": float((ics > 0).mean()), "n_tickers": len(ics)})
    print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    # 2. Cross-horizon score correlation (redundant or distinct signals?)
    print("\n=== Cross-horizon prob_pct correlation (Spearman) ===")
    pct_cols = [f"prob_pct_{h}" for h in HORIZON_THR]
    print(m[pct_cols].corr(method="spearman").to_string(float_format=lambda x: f"{x:.3f}"))

    # 3. Delay-entry cohort on breakout days: high 20d-score, vary short-horizon score.
    print("\n=== Delay-entry signature (breakout days) ===")
    print("High 20d conviction (prob_pct_20 top tertile) split by SHORT-horizon score:")
    bo_rows = m[m["breakout_ok"] == True].copy()
    hi20 = bo_rows[bo_rows["prob_pct_20"] >= 0.667]
    for sh in (1, 5):
        hi20 = hi20.copy()
        hi20[f"short_bucket_{sh}"] = pd.cut(hi20[f"prob_pct_{sh}"], [0, 0.333, 0.667, 1.0],
                                            labels=["low", "mid", "high"], include_lowest=True)
        agg = hi20.groupby(f"short_bucket_{sh}", observed=True).agg(
            n=("ticker", "size"),
            short_fwd_dd=(f"fwd_dd_{sh}", "mean"),
            short_fwd_ret=(f"fwd_ret_{sh}", "mean"),
            fwd_ret_20=("fwd_ret_20", "mean"),
        ).reset_index()
        print(f"\n  Short horizon = {sh}d  (rows: high-20d-conviction breakouts):")
        print(agg.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
        print(f"  -> 'delay-entry' = short_bucket low: short {sh}d return/dd vs the "
              f"+{hi20['fwd_ret_20'].mean()*100:.1f}% avg 20d return on these names")


if __name__ == "__main__":
    main()
