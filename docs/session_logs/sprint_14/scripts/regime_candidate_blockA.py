"""Regime-indicator manual — Block A (label-separation / nowcaster) for every candidate.

Protocol (S0.3-S0.4, pre-registered — do NOT deviate):
  - target: L1 cohort BAD-day = bottom tercile of fwd50 loss_mean (gauge_label_fwd50).
  - features: candidate_features_daily.parquet (expanding-z, shift(1) already applied).
  - WFO: anchored expanding, yearly. Train <= Y-1, test = Y. First test year 2003.
  - EMBARGO: drop the last 50 train rows each fold (fwd50 label leakage guard).
  - min train: 3y / 750 rows.
  - baseline: SPY below 200d (p_bad = 1 - spy_above200).
  - each candidate scored two ways:
      standalone : 1-var logistic on the candidate's z (sign learned from TRAIN only).
      group      : multi-var logistic + XGB on the candidate's feature set.
  - metrics: pooled OOS AUC, median/worst fold, calm/crisis split, block-bootstrap
             CI (50d blocks, 1000 resamples) on AUC and on delta vs SPY-200d.

  python .../regime_candidate_blockA.py           # full run -> blockA_results.json + print
  python .../regime_candidate_blockA.py --smoke   # 2 candidates, fewer boots
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import duckdb
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
DB = ROOT / "data" / "market_data.duckdb"
EMBARGO = 50           # fwd50 label leakage guard (S0.3)
MIN_TRAIN = 750
FIRST_TEST_YEAR = 2003
BAD_Q = 1 / 3

# candidate feature GROUPS (the ladder). standalone = the group's lead z-feature.
GROUPS: dict[str, list[str]] = {
    "spy200_slope_dist": ["spy_dist200_z", "spy_sma200_slope_z"],            # S6.8 (highest prior)
    "breadth": ["breadth_200d_z", "ad_slope_20d_z"],                          # S4
    "adx": ["spy_adx14_z"],                                                   # S6.2
    "donchian": ["spy_dc_pct20_z", "spy_dc_pct55_z", "spy_dc_pct252_z"],      # S6.3
    "supertrend": ["spy_supertrend_up_z"],                                    # S6.5
    "aroon": ["spy_aroon_osc_z"],                                             # S6.4
    "bbw": ["spy_bbw_z"],                                                     # S6.7
    "rv22": ["spy_rv22_z"],                                                   # S2 vol-state
    "qqq_spy_rs": ["qqq_spy_rs_slope_z"],                                     # S6.9
    # S5-batch: everything into one 6-cap XGB (the manual's "batch or cut" rung 5)
    "batch_all": ["spy_dist200_z", "breadth_200d_z", "spy_adx14_z",
                  "spy_dc_pct252_z", "spy_rv22_z", "qqq_spy_rs_slope_z"],
}
STANDALONE_LEAD = {g: cols[0] for g, cols in GROUPS.items()}


# ---------------------------------------------------------------- data + labels
def load() -> pd.DataFrame:
    lab = pd.read_parquet(GAUGE / "gauge_label_fwd50_downside.parquet")
    feats = pd.read_parquet(GAUGE / "candidate_features_daily.parquet")
    lab["date"] = pd.to_datetime(lab["date"]); feats["date"] = pd.to_datetime(feats["date"])
    df = lab.merge(feats, on="date", how="inner")
    # binary BAD-day: bottom tercile of loss_mean (LOWER loss_mean = worse day)
    df["bad"] = (df["loss_mean"] <= df["loss_mean"].quantile(BAD_Q)).astype(int)
    df["year"] = df["date"].dt.year
    # crisis/calm year tagging via SPY drawdown (S0.4)
    df = df.merge(_year_regime(), on="year", how="left")
    return df.sort_values("date").reset_index(drop=True)


def _year_regime() -> pd.DataFrame:
    """Tag each year crisis (SPY max-dd <= -20%), calm (max-dd > -10%), or mid."""
    con = duckdb.connect(str(DB), read_only=True)
    spy = con.execute("SELECT date, close FROM price_data WHERE ticker='SPY' ORDER BY date").df()
    con.close()
    spy["date"] = pd.to_datetime(spy["date"]); spy["year"] = spy["date"].dt.year
    spy["peak"] = spy["close"].cummax()
    spy["dd"] = spy["close"] / spy["peak"] - 1
    g = spy.groupby("year")["dd"].min().reset_index().rename(columns={"dd": "year_maxdd"})
    g["regime"] = np.where(g["year_maxdd"] <= -0.20, "crisis",
                           np.where(g["year_maxdd"] > -0.10, "calm", "mid"))
    return g[["year", "year_maxdd", "regime"]]


# ------------------------------------------------------------------- WFO engine
def wfo_predict(df: pd.DataFrame, cols: list[str], model: str) -> pd.DataFrame:
    """Anchored-expanding yearly WFO with 50d embargo. Returns per-test-row p_bad."""
    d = df.dropna(subset=cols + ["bad"]).reset_index(drop=True)
    years = [y for y in sorted(d["year"].unique()) if y >= FIRST_TEST_YEAR]
    out = []
    for yr in years:
        tr = d[d["year"] < yr]
        if len(tr) > EMBARGO:
            tr = tr.iloc[:-EMBARGO]                       # embargo: drop tail 50 rows
        te = d[d["year"] == yr]
        if len(tr) < MIN_TRAIN or te.empty or tr["bad"].nunique() < 2:
            continue
        Xtr, Xte, ytr = tr[cols].values, te[cols].values, tr["bad"].values
        if model == "logit":
            sc = StandardScaler().fit(Xtr)
            m = LogisticRegression(max_iter=1000, C=1.0).fit(sc.transform(Xtr), ytr)
            p = m.predict_proba(sc.transform(Xte))[:, 1]
        elif model == "xgb":
            from xgboost import XGBClassifier
            m = XGBClassifier(n_estimators=120, max_depth=3, learning_rate=0.05,
                              subsample=0.8, colsample_bytree=0.8, eval_metric="logloss",
                              n_jobs=4, verbosity=0).fit(Xtr, ytr)
            p = m.predict_proba(Xte)[:, 1]
        else:
            raise ValueError(model)
        out.append(pd.DataFrame({"date": te["date"].values, "year": yr, "bad": te["bad"].values,
                                 "regime": te["regime"].values, "p": p}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def baseline_predict(df: pd.DataFrame) -> pd.DataFrame:
    d = df.dropna(subset=["spy_above200", "bad"]).reset_index(drop=True)
    d = d[d["year"] >= FIRST_TEST_YEAR]
    return pd.DataFrame({"date": d["date"].values, "year": d["year"].values, "bad": d["bad"].values,
                         "regime": d["regime"].values, "p": (1.0 - d["spy_above200"]).values})


def _auc(y, p) -> float:
    return roc_auc_score(y, p) if len(np.unique(y)) > 1 else float("nan")


def summarize(oos: pd.DataFrame) -> dict:
    fold = oos.groupby("year").apply(lambda g: _auc(g["bad"], g["p"]), include_groups=False)
    fold = fold.dropna()
    crisis = oos[oos["regime"] == "crisis"]; calm = oos[oos["regime"] == "calm"]
    return {
        "pooled": _auc(oos["bad"], oos["p"]),
        "median_fold": float(fold.median()), "worst_fold": float(fold.min()),
        "auc_crisis": _auc(crisis["bad"], crisis["p"]) if len(crisis) else float("nan"),
        "auc_calm": _auc(calm["bad"], calm["p"]) if len(calm) else float("nan"),
        "n": int(len(oos)), "n_folds": int(len(fold)),
    }


def block_bootstrap_delta(oos_c: pd.DataFrame, oos_b: pd.DataFrame,
                          n_boot: int, block: int = EMBARGO, seed: int = 0) -> dict:
    """50d-block bootstrap CI on pooled AUC(candidate) and delta vs baseline.
    Both frames aligned on date so blocks resample the SAME days."""
    j = oos_c[["date", "bad", "p"]].merge(
        oos_b[["date", "p"]].rename(columns={"p": "pb"}), on="date", how="inner")
    j = j.sort_values("date").reset_index(drop=True)
    n = len(j); n_blocks = int(np.ceil(n / block))
    rng = np.random.default_rng(seed)
    starts_all = np.arange(0, n - block + 1)
    aucs, deltas = [], []
    for _ in range(n_boot):
        starts = rng.choice(starts_all, size=n_blocks, replace=True)
        idx = np.concatenate([np.arange(s, s + block) for s in starts])[:n]
        s = j.iloc[idx]
        if s["bad"].nunique() < 2:
            continue
        ac, ab = _auc(s["bad"], s["p"]), _auc(s["bad"], s["pb"])
        aucs.append(ac); deltas.append(ac - ab)
    q = lambda a, p: float(np.quantile(a, p)) if a else float("nan")
    return {
        "auc_ci": [q(aucs, .025), q(aucs, .975)],
        "delta_ci": [q(deltas, .025), q(deltas, .975)],
        "delta_excludes_0": bool(q(deltas, .025) > 0 or q(deltas, .975) < 0),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    n_boot = 200 if args.smoke else 1000

    t0 = time.time()
    df = load()
    print(f"joined {len(df)} days ({df['date'].min().date()}->{df['date'].max().date()}), "
          f"bad-rate={df['bad'].mean():.1%}")
    print("year regimes:", df.groupby("regime")["year"].nunique().to_dict())

    base = baseline_predict(df)
    base_sum = summarize(base)
    print(f"\n=== SPY-200d BASELINE ===  pooled AUC {base_sum['pooled']:.3f}  "
          f"crisis {base_sum['auc_crisis']:.3f}  calm {base_sum['auc_calm']:.3f}")

    groups = list(GROUPS)
    if args.smoke:
        groups = ["spy200_slope_dist", "breadth"]

    results = {"baseline": base_sum, "candidates": {}}
    print(f"\n{'candidate':20}{'mode':10}{'pooled':>8}{'medFold':>9}{'worst':>8}"
          f"{'crisis':>8}{'calm':>8}{'d_vsBase':>9}{'CI!0':>6}")
    for g in groups:
        cols = GROUPS[g]
        # standalone (1-var logit) + group logit + group xgb (skip xgb for 1-col groups)
        modes = [("standalone", [STANDALONE_LEAD[g]], "logit")]
        if len(cols) > 1:
            modes.append(("group_logit", cols, "logit"))
        modes.append(("group_xgb", cols, "xgb"))
        for mode, mcols, mdl in modes:
            oos = wfo_predict(df, mcols, mdl)
            if oos.empty:
                continue
            s = summarize(oos)
            bb = block_bootstrap_delta(oos, base, n_boot)
            delta = s["pooled"] - base_sum["pooled"]
            results["candidates"][f"{g}__{mode}"] = {**s, **bb, "delta_vs_base": delta,
                                                     "cols": mcols, "model": mdl}
            print(f"{g:20}{mode:10}{s['pooled']:>8.3f}{s['median_fold']:>9.3f}"
                  f"{s['worst_fold']:>8.3f}{s['auc_crisis']:>8.3f}{s['auc_calm']:>8.3f}"
                  f"{delta:>+9.3f}{('Y' if bb['delta_excludes_0'] else 'n'):>6}")

    out = GAUGE / ("blockA_results_smoke.json" if args.smoke else "blockA_results.json")
    out.write_text(json.dumps(results, indent=2, default=float))
    print(f"\nwrote {out.relative_to(ROOT)}  [{time.time()-t0:.1f}s]")
    # decision helper against the pre-registered bars
    print("\nGATE (S0.4-A): pooled>=0.65 to PROMOTE, >=0.62 interesting, worst>=0.55.")
    for k, v in results["candidates"].items():
        flag = "PASS-A" if v["pooled"] >= 0.65 else ("interesting" if v["pooled"] >= 0.62 else "")
        if flag:
            print(f"  {k}: pooled {v['pooled']:.3f}  {flag}")


if __name__ == "__main__":
    main()
