# Q65 (cache substrate) — score the d2_training_cache with prod m01_prototype,
# plot day-1 score vs the cache's NATIVE SEPA exit return (return_at_exit).
#
# Why the cache and not the champion_trail cone: one exit mechanism (native SEPA
# stop, `return_at_exit`) instead of the cone's trailing-stop, so the score-vs-return
# read isn't blurred by two SLs. Scoring reuses UniverseScorer's loaded model +
# encode_categoricals + predict block verbatim (no reinvented scoring path).
#
# ⚠️ TWO overfits, both stated: (1) score plotted vs realized outcome (Q65 is
# overfit by construction); (2) the cache IS the training set -> this is IN-SAMPLE,
# so the score-return link reads OPTIMISTIC vs live. Intuition only, never a claim.
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
import xgboost as xgb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from src.backtest.universe_scorer import UniverseScorer, encode_categoricals, load_categorical_map

MODEL = ROOT / "models/m01_prototype_2003_2026/v1/model.json"
DB = ROOT / "data/market_data.duckdb"
CASE_MAP = {"RS_Sector_Rank": "rs_sector_rank", "RS_Industry_Rank": "rs_industry_rank",
            "RS_vs_Sector": "rs_vs_sector", "RS_vs_Industry": "rs_vs_industry",
            "Sector_Momentum": "sector_momentum", "Industry_Momentum": "industry_momentum",
            "RS_Universe_Rank": "rs_universe_rank"}


def load_cache() -> pd.DataFrame:
    con = duckdb.connect(str(DB), read_only=True)
    try:
        # one row per trade; keep entry-day features + the native SEPA exit outcome
        df = con.execute("""
            SELECT * FROM d2_training_cache
            WHERE return_at_exit IS NOT NULL AND date = entry_date
        """).fetchdf()
    finally:
        con.close()
    return df


def score(df: pd.DataFrame, scorer: UniverseScorer) -> np.ndarray:
    """Day-1 prob_elite via the SAME encode+predict path score_from_t3 uses."""
    for src, dst in CASE_MAP.items():
        if src in df.columns and dst not in df.columns:
            df[dst] = df[src]
    for f in scorer._m01_features:
        if f not in df.columns:
            df[f] = np.nan  # NaN-passthrough (XGBoost treats missing as missing, = prod)
    X = df[scorer._m01_features].replace([np.inf, -np.inf], np.nan)
    cat_map = load_categorical_map(scorer.m01_path)
    X = encode_categoricals(X, scorer._m01_features, cat_map)
    proba = scorer.m01_model.get_booster().predict(xgb.DMatrix(X, enable_categorical=True))
    return proba[:, -1]  # prob(top class) = prob_elite (4-class softprob)


def main() -> None:
    scorer = UniverseScorer(m01_path=str(MODEL))
    scorer.load_model()
    df = load_cache()
    print(f"cache trades (entry-day rows w/ return_at_exit): {len(df)}")
    df["prob_elite"] = score(df, scorer)

    d = df.dropna(subset=["prob_elite", "return_at_exit"]).copy()
    d["ret_pct"] = d["return_at_exit"] * 100 if d["return_at_exit"].abs().median() < 5 else d["return_at_exit"]
    d["dec"] = pd.qcut(d["prob_elite"], 10, labels=False, duplicates="drop")
    d["home_run"] = (d["ret_pct"] > 30).astype(float)
    d["tail"] = np.maximum(d["ret_pct"] - 30, 0.0)  # magnitude above the home-run line
    rho, pval = spearmanr(d["prob_elite"], d["ret_pct"])
    rho_tail, _ = spearmanr(d["prob_elite"], d["tail"])

    fig, (axL, axR) = plt.subplots(1, 2, figsize=(15, 6))

    # LEFT — the median lens (why the naive ρ looks flat/negative)
    axL.scatter(d["prob_elite"], d["ret_pct"], s=8, alpha=.15, color="#607d8b", edgecolors="none")
    g = d.groupby("dec").agg(x=("prob_elite", "median"), med=("ret_pct", "median"),
                             q25=("ret_pct", lambda v: v.quantile(.25)),
                             q75=("ret_pct", lambda v: v.quantile(.75)))
    axL.plot(g.x, g.med, "o-", color="#c62828", lw=2, label="decile median")
    axL.fill_between(g.x, g.q25, g.q75, color="#c62828", alpha=.12, label="decile IQR")
    axL.axhline(0, color="k", lw=.7, alpha=.5)
    axL.set_xlabel("day-1 prob_elite (m01_prototype, 4-class)")
    axL.set_ylabel("return_at_exit % (native SEPA stop)")
    axL.set_title(f"MEDIAN lens: flat/negative at every score\nSpearman rho={rho:+.3f} — the misleading number")
    axL.legend(fontsize=9)

    # RIGHT — the TAIL lens (the signal the median hides): home-run rate + mean-tail by decile
    t = d.groupby("dec").agg(x=("prob_elite", "median"), hr=("home_run", "mean"),
                             mean_tail=("tail", "mean"))
    pool_hr = d["home_run"].mean()
    axR.bar(t.x, t.mean_tail, width=.045, color="#2e7d32", alpha=.8, label="mean tail Σmax(ret−30,0)")
    axR.set_ylabel("mean tail magnitude (pts)", color="#2e7d32")
    axR.set_xlabel("day-1 prob_elite (decile medians)")
    axt = axR.twinx()
    axt.plot(t.x, t.hr * 100, "o-", color="#c62828", lw=2, label="home-run rate P(ret>30%)")
    axt.axhline(pool_hr * 100, color="#c62828", ls=":", alpha=.6, label=f"pool {pool_hr*100:.1f}%")
    axt.set_ylabel("home-run rate %", color="#c62828")
    axR.set_title(f"TAIL lens: score DOES rank winners\nrho(tail)={rho_tail:+.3f}; HR {t.hr.iloc[0]*100:.1f}%→{t.hr.iloc[-1]*100:.1f}% low→high decile")
    l1, la1 = axR.get_legend_handles_labels(); l2, la2 = axt.get_legend_handles_labels()
    axR.legend(l1 + l2, la1 + la2, fontsize=8, loc="upper left")

    fig.suptitle(f"Q65 cache — day-1 score vs NATIVE-SEPA exit return  (IN-SAMPLE, overfit, {len(d)} trades)",
                 weight="bold")
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    out = ROOT / "docs/session_logs/sprint_14/verdicts/2026-07-14_q65_cache_score_vs_return.png"
    plt.savefig(out, dpi=110, bbox_inches="tight")
    print(f"saved {out}")

    top = d[d["prob_elite"] >= d["prob_elite"].quantile(.9)]["ret_pct"].median()
    bot = d[d["prob_elite"] <= d["prob_elite"].quantile(.1)]["ret_pct"].median()
    print(f"MEDIAN lens rho={rho:+.3f} | top-decile median {top:+.2f}% vs bottom-decile {bot:+.2f}%")
    print(f"TAIL   lens rho={rho_tail:+.3f} | home-run rate low-decile {t.hr.iloc[0]*100:.1f}% "
          f"vs high-decile {t.hr.iloc[-1]*100:.1f}% (pool {pool_hr*100:.1f}%)")
    # sanity check: score must vary and rank must be non-degenerate
    assert d["prob_elite"].nunique() > 10, "prob_elite collapsed — scoring path broke"


if __name__ == "__main__":
    main()
