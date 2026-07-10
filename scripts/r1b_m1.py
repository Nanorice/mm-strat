"""R1b M1: book step-2 criteria quantified holistically on the trend_ok panel.

(a) distributional portraits + per-year pass rates (selectivity drift)
(b) mediation: unconditional per-date decile ramps vs labels + per-date rank corr vs RS
(c) pairwise joint pass rates (conjunction coherence)
"""
import numpy as np
import pandas as pd
from pathlib import Path

CACHE = Path("data/research_cache/r1b")
CRIT = {  # criterion -> (book threshold expressed on our column, units are %)
    "eps_growth_yoy": 25.0,
    "revenue_growth_yoy": 20.0,
    "gross_margin_trend": 0.0,
    "eps_accel": 0.0,
    "revenue_accel": 0.0,
}
cols = ["ticker", "date", "rs_universe_rank", "tail_mag_63", "home_run_63",
        "tail_mag_126", "home_run_126"] + list(CRIT)
df = pd.read_parquet(CACHE / "panel.parquet", columns=cols)
df["date"] = pd.to_datetime(df["date"])
df["year"] = df["date"].dt.year
print(f"Panel: {len(df):,} rows", flush=True)

# ---------- (a) portraits ----------
rows = []
for c, thr in CRIT.items():
    v = df[c]
    hr, rest = df.loc[df["home_run_63"] == 1, c], df.loc[df["home_run_63"] == 0, c]
    rows.append({
        "criterion": c, "book_threshold": thr,
        "missing_pct": 100 * v.isna().mean(),
        "p10": v.quantile(0.10), "p25": v.quantile(0.25), "p50": v.quantile(0.50),
        "p75": v.quantile(0.75), "p90": v.quantile(0.90),
        "pass_rate_pct": 100 * (v >= thr).mean() if c != "gross_margin_trend" else 100 * (v > thr).mean(),
        "hr_median": hr.median(), "rest_median": rest.median(),
        "hr_p75": hr.quantile(0.75), "rest_p75": rest.quantile(0.75),
    })
portraits = pd.DataFrame(rows)
pd.set_option("display.width", 300)
print("\n--- (a) Portraits (panel dist / pass rate / home-run vs rest) ---")
print(portraits.round(2).to_string(index=False))
portraits.to_csv(CACHE / "m1_portraits.csv", index=False)

# pass masks (NaN = fail; missing tracked separately above)
passes = pd.DataFrame({c: (df[c] > thr) if thr == 0.0 else (df[c] >= thr)
                       for c, thr in CRIT.items()})
passes["year"] = df["year"].values

py = passes.groupby("year")[list(CRIT)].mean().mul(100)
print("\n--- (a) Pass rate by year (%, selectivity drift) ---")
print(py.round(1).to_string())
py.to_csv(CACHE / "m1_pass_rates_by_year.csv")

# ---------- (b) mediation: decile ramps + rank corr vs RS ----------
ramp_rows, corr_rows = [], []
for c in CRIT:
    sub = df.dropna(subset=[c])
    rk = sub.groupby("date")[c].rank(pct=True)
    dec = np.ceil(rk * 10).clip(1, 10).astype(int)
    for h in (63, 126):
        g = sub.groupby(dec)[[f"tail_mag_{h}", f"home_run_{h}"]].mean()
        ramp_rows.append({
            "criterion": c, "horizon": h,
            **{f"D{i}_hr": g.loc[i, f"home_run_{h}"] for i in range(1, 11)},
            "D10_D1_tail_ratio": g.loc[10, f"tail_mag_{h}"] / g.loc[1, f"tail_mag_{h}"],
            "D10_D1_hr_ratio": g.loc[10, f"home_run_{h}"] / g.loc[1, f"home_run_{h}"],
            "spearman_dec_vs_hr": pd.Series(range(1, 11)).corr(
                g[f"home_run_{h}"].reset_index(drop=True), method="spearman"),
        })
    # per-date Spearman vs rs_universe_rank (Pearson of within-date pct ranks)
    tmp = pd.DataFrame({"date": sub["date"].values, "x": rk.values,
                        "y": sub.groupby("date")["rs_universe_rank"].rank(pct=True).values})
    per_date = tmp.groupby("date").apply(
        lambda g: g["x"].corr(g["y"]) if len(g) > 30 else np.nan, include_groups=False)
    corr_rows.append({"criterion": c, "mean_per_date_rho_vs_rs": per_date.mean(),
                      "median_rho": per_date.median(),
                      "pct_dates_rho_pos": 100 * (per_date > 0).mean()})

ramps = pd.DataFrame(ramp_rows)
print("\n--- (b) Unconditional per-date decile ramps ---")
print(ramps.round(3).to_string(index=False))
ramps.to_csv(CACHE / "m1_decile_ramps.csv", index=False)

med = pd.DataFrame(corr_rows)
print("\n--- (b) Per-date rank corr vs rs_universe_rank (mediation link) ---")
print(med.round(3).to_string(index=False))
med.to_csv(CACHE / "m1_rs_mediation.csv", index=False)

# ---------- (c) pairwise joint pass rates ----------
names = list(CRIT)
joint = pd.DataFrame(index=names, columns=names, dtype=float)
for a in names:
    for b in names:
        joint.loc[a, b] = 100 * (passes[a] & passes[b]).mean()
conj_all = 100 * passes[names].all(axis=1).mean()
print("\n--- (c) Pairwise joint pass rates (%; diagonal = single) ---")
print(joint.round(1).to_string())
print(f"\nFull 5-way conjunction pass rate: {conj_all:.2f}% of panel rows")
joint.to_csv(CACHE / "m1_joint_pass.csv")
