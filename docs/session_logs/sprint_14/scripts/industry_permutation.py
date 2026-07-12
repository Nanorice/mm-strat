"""Permutation-at-scoring audit: which feature block is LOAD-BEARING for the deployed
tail-ranking (vs total_gain cardinality bias)?

Scores sampled breakout days with the prototype model, then shuffles one feature block
WITHIN each day and re-scores. Degradation is measured on what we deploy: the breakout
pool's within-day rank corr, top-5 mean fwd100, top-5 home-run rate.

Finding (2026-07-11, 552 days / 12.6k breakout rows): permuting `industry` is the only
ablation that degrades deployed metrics (top-5 HR −1.1pp, |Δscore| 0.058); permuting the
ENTIRE RS family or momentum block does nothing — redundant across collinear features.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd


def _root() -> Path:
    p = Path(__file__).resolve()
    for d in (p, *p.parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError("root not found")


ROOT = _root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import db
from src.backtest.universe_scorer import (UniverseScorer, encode_categoricals,
                                          load_categorical_map)

MODEL = ROOT / "models/m01_prototype_2003_2026/v1/model.json"
DB = ROOT / "data/market_data.duckdb"

MOMENTUM_BLOCK = ["dist_from_20d_high", "mom_21d", "price_vs_spy_ma63", "mom_63d",
                  "mom_126d", "dist_from_50d_high", "price_vs_sector_ma63"]
RS_FAMILY = ["rs", "rs_vs_sector", "rs_vs_industry", "rs_sector_rank",
             "rs_industry_rank", "rs_universe_rank"]


def run_permutation_audit(panel: pd.DataFrame, per_month: int = 1,
                          years: tuple[int, ...] | None = None, seed: int = 14,
                          ) -> tuple[dict, pd.DataFrame]:
    """Returns (baseline metrics dict, per-block delta DataFrame)."""
    import xgboost as xgb

    rng_state = seed
    dates = pd.Series(sorted(panel.date.unique()))
    if years:
        dates = dates[dates.dt.year.isin(years)]
    sample_dates = dates.groupby([dates.dt.year, dates.dt.month]).apply(
        lambda s: s.iloc[:: max(len(s) // per_month, 1)][:per_month]).reset_index(drop=True)
    print(f"[permutation] {len(sample_dates)} sampled breakout days", flush=True)

    scorer = UniverseScorer(m01_path=str(MODEL), calibration_path=None)
    scorer.load_model()
    feats = scorer._m01_features
    cat_map = load_categorical_map(scorer.m01_path)

    dlist = ",".join(f"'{pd.Timestamp(d).date()}'" for d in sample_dates)
    con = db.connect(str(DB), read_only=True)
    df = con.execute(f"SELECT * FROM v_t3_training WHERE date IN ({dlist})").fetchdf()
    con.close()
    df = scorer._filter_equities_only(df, DB)
    df["date"] = pd.to_datetime(df["date"])
    print(f"[permutation] {len(df)} scored rows", flush=True)

    # row-local prep, identical to score_from_t3
    for col in list(df.columns):
        if col.endswith("_pct_chg"):
            dc = col[: -len("_pct_chg")] + "_delta"
            if dc not in df.columns:
                df[dc] = df[col] / 100.0
    case_map = {"RS_Sector_Rank": "rs_sector_rank", "RS_Industry_Rank": "rs_industry_rank",
                "RS_vs_Sector": "rs_vs_sector", "RS_vs_Industry": "rs_vs_industry",
                "Sector_Momentum": "sector_momentum", "Industry_Momentum": "industry_momentum",
                "RS_Universe_Rank": "rs_universe_rank"}
    for s, t in case_map.items():
        if s in df.columns and t not in df.columns:
            df[t] = df[s]
    for f in [f for f in feats if f not in df.columns and f.startswith("log_")]:
        if f[4:] in df.columns:
            df[f] = np.sign(df[f[4:]]) * np.log1p(np.abs(df[f[4:]]))
    for f in [f for f in feats if f not in df.columns]:
        df[f] = np.nan

    X0 = encode_categoricals(df[feats].replace([np.inf, -np.inf], np.nan), feats, cat_map)
    day_codes = df["date"].values

    def predict(X: pd.DataFrame) -> np.ndarray:
        p = np.asarray(scorer.m01_model.get_booster().predict(
            xgb.DMatrix(X, enable_categorical=True)))
        return p if p.ndim == 1 else p[:, -1]

    meta = df[["date", "ticker"]].copy()
    meta["fwd100"] = meta.merge(panel[["date", "ticker", "fwd100"]],
                                on=["date", "ticker"], how="left")["fwd100"].values
    bko = meta.merge(panel[["date", "ticker"]].assign(is_bko=True), on=["date", "ticker"],
                     how="left")["is_bko"].notna().values

    def metrics(score: np.ndarray) -> dict:
        m = pd.DataFrame({"date": meta.date, "fwd": meta.fwd100, "s": score})[bko].dropna()
        wd = m.groupby("date").apply(
            lambda g: g.s.corr(g.fwd, method="spearman") if len(g) >= 8 else np.nan,
            include_groups=False).dropna()
        t5 = m.sort_values(["date", "s"], ascending=[True, False]).groupby("date").head(5)
        return {"within_day_rho": wd.mean(), "top5_mean": t5.fwd.mean() * 100,
                "top5_HR": (t5.fwd > 0.30).mean() * 100,
                "pool_mean": m.fwd.mean() * 100, "pool_HR": (m.fwd > 0.30).mean() * 100}

    base_p = predict(X0)
    base = metrics(base_p)

    blocks = [("industry", ["industry"]), ("sector", ["sector"]),
              ("RS family", [f for f in RS_FAMILY if f in feats]),
              ("momentum block", [f for f in MOMENTUM_BLOCK if f in feats])]
    rows = []
    for lab, cols in blocks:
        Xp = X0.copy()
        for c in cols:
            Xp[c] = pd.Series(Xp[c].values, index=Xp.index).groupby(day_codes).transform(
                lambda s: s.sample(frac=1, random_state=rng_state).values)
            if str(X0[c].dtype) == "category":
                Xp[c] = Xp[c].astype(X0[c].dtype)
        pp = predict(Xp)
        mm = metrics(pp)
        rows.append({"block": lab, "d_rho": mm["within_day_rho"] - base["within_day_rho"],
                     "d_top5_mean_pp": mm["top5_mean"] - base["top5_mean"],
                     "d_top5_HR_pp": mm["top5_HR"] - base["top5_HR"],
                     "mean_abs_dscore": float(np.abs(pp - base_p).mean())})
        print(f"  [permutation] {lab}: dHR {rows[-1]['d_top5_HR_pp']:+.1f}pp", flush=True)
    return base, pd.DataFrame(rows).set_index("block")


if __name__ == "__main__":
    # SMOKE: two years only
    from gated_eda_panel import load_gated_panel
    panel = load_gated_panel(gate="breakout")
    base, deltas = run_permutation_audit(panel, per_month=2, years=(2010, 2020))
    print(f"\nbaseline: {base}")
    print(deltas.round(3).to_string())
    assert abs(deltas.loc["industry", "mean_abs_dscore"]) > \
           abs(deltas.loc["RS family", "mean_abs_dscore"]), "industry should dominate"
    print("[OK] permutation smoke passed")
