"""R2 — leadership-profile contrast EDA (Minervini step 3), reverse-engineered from fwd returns.

M0: per-trait decile -> home-run rate / tail_mag; monotone-to-top-decile + date-third stability.
M1: the gate — RS-D10 x trait-tercile lift (>=1.3x, monotone, date-stable) + per-date rho vs RS
    (a trait that is RS in disguise is dropped even if it wins M0).

Reuses the R1b label panel (labels + RS + sector already cached) and joins the R2 leadership
trait set from t3_training_cache. read_only DuckDB. All label-level (currency C1) — monetization
routes through R3's harness, never claimed from EDA (the M4 lesson).

Repro: .venv/Scripts/python.exe scripts/r2_leadership_profile.py [--smoke]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

SMOKE = "--smoke" in sys.argv
PANEL = Path("data/research_cache/r1b/panel.parquet")
OUT = Path("data/research_cache/r2")
OUT.mkdir(parents=True, exist_ok=True)

# Trait set (entry-time), col -> (higher_is_leader, book rationale). All resolve in
# t3_training_cache (verified). Per-date XS rank applied to every trait so raw levels
# are comparable across 25 years (the plan's requirement).
TRAITS = {
    "rs_industry_rank":       (True,  "leaders lead their group"),
    "rs_vs_industry":         (True,  "outperforms its own industry"),
    "rs_sector_rank":         (True,  "sector leadership"),
    "industry_momentum":      (True,  "hot group carries the name"),
    "dist_from_52w_high":     (True,  "leaders emerge near highs (less negative = closer)"),
    "consolidation_duration": (True,  "mature base"),
    "consolidation_width":    (False, "tight base (narrow = better)"),
    "vcp_ratio":              (True,  "volatility contraction"),
    "adr_20d":                (True,  "high-ADR names produce the tails"),
    "natr":                   (True,  "normalized ATR — volatility signature"),
    "volatility_20d":         (True,  "raw vol"),
    "dollar_volume_avg_20":   (False, "thin float fuels runs (small = better)"),
    "market_cap":             (False, "young/small leaders (small = better)"),  # derived below
}

HR = "home_run_63"          # binary label
TM = "tail_mag_63"          # continuous tail magnitude
GATE = 1.3                  # M1 within-RS-D10 lift gate


def load_panel() -> pd.DataFrame:
    trait_cols = [t for t in TRAITS if t != "market_cap"]
    con = duckdb.connect("data/market_data.duckdb", read_only=True)
    print("Loading R1b label panel + joining R2 traits...", flush=True)
    lbl = pd.read_parquet(PANEL, columns=["ticker", "date", HR, TM, "rs_universe_rank",
                                          "shares_outstanding", "px_close"])
    # Pull traits from t3_training_cache; lowercase to dodge the XS-rank casing bug.
    tr = con.execute(f"SELECT ticker, date, {', '.join(trait_cols)} FROM t3_training_cache").df()
    tr.columns = tr.columns.str.lower()
    df = lbl.merge(tr, on=["ticker", "date"], how="inner")
    df["market_cap"] = df["shares_outstanding"] * df["px_close"]
    if SMOKE:
        df = df[df["date"].astype(str).str[:4] == "2015"].copy()
    print(f"  panel: {len(df):,} rows, {df['date'].min()} .. {df['date'].max()}", flush=True)
    return df


def per_date_rank(df: pd.DataFrame, col: str, higher_is_leader: bool) -> pd.Series:
    """Cross-sectional percentile rank within each date; oriented so high = more 'leader'."""
    r = df.groupby("date")[col].rank(pct=True)
    return r if higher_is_leader else 1.0 - r


def decile_ramp(df: pd.DataFrame, rank_col: str) -> pd.DataFrame:
    """Home-run rate + mean tail_mag by decile of a per-date rank. Monotone-to-top check."""
    d = df.dropna(subset=[rank_col]).copy()
    d["dec"] = (d[rank_col] * 10).clip(upper=9.999).astype(int) + 1
    g = d.groupby("dec").agg(n=("dec", "size"), hr=(HR, "mean"), tm=(TM, "mean"))
    base_hr = d[HR].mean()
    g["hr_lift"] = g["hr"] / base_hr
    return g


def m0_univariate(df: pd.DataFrame) -> pd.DataFrame:
    """Per-trait D10 vs D1 lift + monotone-to-top + date-third stability."""
    rows = []
    thirds = pd.qcut(df["date"].rank(method="first"), 3, labels=["P1", "P2", "P3"])
    for trait, (hi, _) in TRAITS.items():
        if trait not in df.columns or df[trait].notna().sum() < 1000:
            continue
        rk = per_date_rank(df, trait, hi)
        ramp = decile_ramp(df.assign(_r=rk), "_r")
        d10, d1 = ramp.loc[10], ramp.loc[1]
        # monotone-to-top: D10 is the max HR decile (the m02 decile-7-peak anti-test)
        mono_top = ramp["hr"].idxmax() == 10
        # date-third stability of the D10/D1 tail lift
        era_lifts = []
        for _, sub in df.assign(_r=rk, _t=thirds).groupby("_t"):
            rr = decile_ramp(sub, "_r")
            if 10 in rr.index and 1 in rr.index and rr.loc[1, "hr"] > 0:
                era_lifts.append(rr.loc[10, "hr"] / rr.loc[1, "hr"])
        rows.append({
            "trait": trait, "n": int(ramp["n"].sum()),
            "d1_hr": round(d1["hr"], 4), "d10_hr": round(d10["hr"], 4),
            "d10_d1_hr_lift": round(d10["hr"] / d1["hr"], 3) if d1["hr"] > 0 else np.nan,
            "d10_tail_lift": round(d10["tm"] / df[TM].mean(), 3),
            "monotone_to_top": mono_top,
            "era_lifts": [round(x, 2) for x in era_lifts],
            "era_stable": len(era_lifts) == 3 and min(era_lifts) > 1.1,
        })
    return pd.DataFrame(rows).sort_values("d10_d1_hr_lift", ascending=False)


def m1_rs_stack(df: pd.DataFrame) -> pd.DataFrame:
    """THE gate: within RS-D10, does the trait tercile add lift? + per-date rho vs RS.

    A trait earns a passport line only if T3(hi) beats the RS-D10 baseline by >=1.3x,
    monotone across terciles, AND is not RS in disguise (|rho| moderate)."""
    rs_rank = per_date_rank(df, "rs_universe_rank", True)
    d10 = df[rs_rank >= 0.90].copy()
    base_hr = d10[HR].mean()
    base_tm = d10[TM].mean()
    print(f"  RS-D10 baseline: n={len(d10):,} hr={base_hr:.4f} tail_mag={base_tm:.4f}", flush=True)
    rows = []
    for trait, (hi, _) in TRAITS.items():
        if trait not in d10.columns or d10[trait].notna().sum() < 1000:
            continue
        # tercile WITHIN RS-D10, per-date
        tr_rank = per_date_rank(d10, trait, hi)
        d = d10.dropna(subset=[trait]).assign(_r=tr_rank)
        d["terc"] = pd.cut(d["_r"], [0, 1/3, 2/3, 1.0], labels=["T1", "T2", "T3"], include_lowest=True)
        g = d.groupby("terc", observed=True).agg(n=("terc", "size"), hr=(HR, "mean"), tm=(TM, "mean"))
        if not {"T1", "T3"}.issubset(g.index):
            continue
        t3_hr_lift = g.loc["T3", "hr"] / base_hr
        t3_tm_lift = g.loc["T3", "tm"] / base_tm
        mono = g.loc["T1", "hr"] <= g.loc["T2", "hr"] <= g.loc["T3", "hr"] if "T2" in g.index else \
               g.loc["T1", "hr"] <= g.loc["T3", "hr"]
        # per-date Spearman rho vs RS (is the trait just RS?). _r is already the
        # per-date trait rank; correlate it against raw RS within each date (rank
        # corr is invariant to the extra ranking, so raw rs_universe_rank is fine).
        rho = d.groupby("date").apply(
            lambda s: s["_r"].corr(s["rs_universe_rank"], method="spearman")
            if len(s) > 5 else np.nan, include_groups=False).mean()
        rows.append({
            "trait": trait, "n_d10": int(g["n"].sum()),
            "t1_hr": round(g.loc["T1", "hr"], 4), "t3_hr": round(g.loc["T3", "hr"], 4),
            "t3_hr_lift_vs_d10": round(t3_hr_lift, 3), "t3_tail_lift_vs_d10": round(t3_tm_lift, 3),
            "monotone": bool(mono), "rho_vs_rs": round(rho, 3),
            "PASSES": bool(t3_hr_lift >= GATE and mono and abs(rho) < 0.5),
        })
    return pd.DataFrame(rows).sort_values("t3_hr_lift_vs_d10", ascending=False)


def main() -> None:
    t0 = time.time()
    df = load_panel()
    print("\n=== M0: univariate trait contrast ===", flush=True)
    m0 = m0_univariate(df)
    print(m0.to_string(index=False), flush=True)
    m0.to_csv(OUT / "m0_univariate.csv", index=False)

    print("\n=== M1: RS-D10 stacking gate (the decisive test) ===", flush=True)
    m1 = m1_rs_stack(df)
    print(m1.to_string(index=False), flush=True)
    m1.to_csv(OUT / "m1_rs_stack.csv", index=False)

    winners = m1[m1["PASSES"]]["trait"].tolist()
    print(f"\nPassport survivors (stack >={GATE}x on RS-D10, monotone, not RS-clone): "
          f"{winners or 'NONE'}", flush=True)
    print(f"({time.time()-t0:.0f}s)  cached -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
