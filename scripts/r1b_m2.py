"""R1b M2: book-faithful step-2 screen on the corrected step-1 survivors.

Screen (book verbatim, % units): eps_growth_yoy>=25, revenue_growth_yoy>=20,
gross_margin_trend>0, eps_accel>0, revenue_accel>0. Staleness guard:
days_since_report<=135 (1 quarter + ~45d filing grace) — zombie fundamentals fail,
never pass. Missing-fundamental rows are a tracked bucket, not silently dropped.
"""
import numpy as np
import pandas as pd
from pathlib import Path

CACHE = Path("data/research_cache/r1b")
df = pd.read_parquet(CACHE / "panel.parquet")
df["date"] = pd.to_datetime(df["date"])
print(f"Panel: {len(df):,} rows", flush=True)

CRIT = list({"eps_growth_yoy": 25.0, "revenue_growth_yoy": 20.0,
             "gross_margin_trend": 0.0, "eps_accel": 0.0, "revenue_accel": 0.0})
has_fund = df[CRIT].notna().all(axis=1)
fresh = df["days_since_report"] <= 135
screen = ((df["eps_growth_yoy"] >= 25) & (df["revenue_growth_yoy"] >= 20)
          & (df["gross_margin_trend"] > 0) & (df["eps_accel"] > 0)
          & (df["revenue_accel"] > 0) & fresh)
rs70, rs80, rs90 = (df["rs_universe_rank"] >= c for c in (0.70, 0.80, 0.90))

base_tail = {h: df[f"tail_mag_{h}"].mean() for h in (63, 126)}
base_hr_n = {h: df[f"home_run_{h}"].sum() for h in (63, 126)}

def triple(mask: pd.Series, name: str) -> dict:
    sub = df[mask]
    r = {"arm": name, "rows": len(sub), "pct_of_panel": 100 * len(sub) / len(df),
         "median_names_per_day": sub.groupby("date")["ticker"].nunique().median() if len(sub) else 0}
    for h in (63, 126):
        r[f"tail_lift_{h}"] = sub[f"tail_mag_{h}"].mean() / base_tail[h]
        r[f"hr_rate_{h}"] = sub[f"home_run_{h}"].mean()
        r[f"hr_capture_{h}"] = 100 * sub[f"home_run_{h}"].sum() / base_hr_n[h]
    return r

arms = {
    "panel": pd.Series(True, index=df.index),
    "RS>=70 (step1 corrected)": rs70,
    "RS>=80": rs80,
    "RS-D10 (>=90)": rs90,
    "SCREEN alone": screen,
    "SCREEN & RS>=70 (book funnel)": screen & rs70,
    "SCREEN & RS-D10": screen & rs90,
    "missing-fund bucket (RS>=70)": rs70 & ~has_fund,
    "stale-fund bucket (RS>=70, dsr>135)": rs70 & has_fund & ~fresh,
}
res = pd.DataFrame([triple(m, n) for n, m in arms.items()])
pd.set_option("display.width", 300)
print("\n--- Funnel triples (63d + 126d) ---")
print(res.round(3).to_string(index=False))
res.to_csv(CACHE / "m2_funnel_triples.csv", index=False)

# ---------- overlap: substitutes or complements? ----------
sets = {"SCREEN&RS70": screen & rs70, "RS>=80": rs80, "RS-D10": rs90}
print("\n--- Row-level Jaccard overlap ---")
ov_rows = []
for a in ["SCREEN&RS70"]:
    for b in ["RS>=80", "RS-D10"]:
        inter = (sets[a] & sets[b]).sum()
        union = (sets[a] | sets[b]).sum()
        ov_rows.append({"A": a, "B": b, "jaccard": inter / union,
                        "pct_A_in_B": 100 * inter / sets[a].sum()})
ov = pd.DataFrame(ov_rows)
print(ov.round(3).to_string(index=False))
ov.to_csv(CACHE / "m2_overlap.csv", index=False)

# ---------- who survives: sector / cap / age ----------
surv, base = df[screen & rs70], df[rs70]
comp = pd.DataFrame({
    "screen_pct": surv["sector"].value_counts(normalize=True).mul(100),
    "rs70_pct": base["sector"].value_counts(normalize=True).mul(100),
}).fillna(0)
comp["tilt"] = comp["screen_pct"] - comp["rs70_pct"]
comp = comp.sort_values("tilt", ascending=False)
print("\n--- Survivor sector composition (SCREEN&RS70 vs RS>=70) ---")
print(comp.round(1).to_string())
comp.to_csv(CACHE / "m2_sector_composition.csv")

for d, nm in ((surv, "SCREEN&RS70"), (base, "RS>=70")):
    cap = (d["px_close"] * d["shares_outstanding"]) / 1e9
    age = (d["date"] - pd.to_datetime(d["listing_date"])).dt.days / 365.25
    print(f"\n{nm}: mktcap $B p25/50/75 = {cap.quantile(0.25):.2f}/{cap.median():.2f}/{cap.quantile(0.75):.2f}"
          f" (missing {100*cap.isna().mean():.0f}%) | age yrs p25/50/75 = "
          f"{age.quantile(0.25):.1f}/{age.median():.1f}/{age.quantile(0.75):.1f} (missing {100*age.isna().mean():.0f}%)")

# ---------- era stability (date-thirds) ----------
period = pd.cut(df["date"].dt.year, bins=[0, 2011, 2018, 2100],
                labels=["P1_<2012", "P2_2012-18", "P3_2019+"])
era_rows = []
for n in ["RS>=70 (step1 corrected)", "RS-D10 (>=90)", "SCREEN & RS>=70 (book funnel)", "SCREEN & RS-D10"]:
    m = arms[n]
    for p in period.cat.categories:
        pm = period == p
        sub, ref = df[m & pm], df[pm]
        era_rows.append({"arm": n, "period": p, "rows": len(sub),
                         "tail_lift_63": sub["tail_mag_63"].mean() / ref["tail_mag_63"].mean(),
                         "hr_capture_63": 100 * sub["home_run_63"].sum() / ref["home_run_63"].sum(),
                         "tail_lift_126": sub["tail_mag_126"].mean() / ref["tail_mag_126"].mean(),
                         "hr_capture_126": 100 * sub["home_run_126"].sum() / ref["home_run_126"].sum()})
era = pd.DataFrame(era_rows)
print("\n--- Era stability (lift/capture vs same-period panel) ---")
print(era.round(3).to_string(index=False))
era.to_csv(CACHE / "m2_era_stability.csv", index=False)

# ---------- threshold sensitivity (secondary) ----------
sens_rows = []
for eps_t, rev_t in [(15, 10), (25, 20), (35, 30)]:
    s = ((df["eps_growth_yoy"] >= eps_t) & (df["revenue_growth_yoy"] >= rev_t)
         & (df["gross_margin_trend"] > 0) & (df["eps_accel"] > 0)
         & (df["revenue_accel"] > 0) & fresh & rs70)
    sub = df[s]
    sens_rows.append({"eps_thr": eps_t, "rev_thr": rev_t, "rows": s.sum(),
                      "tail_lift_63": sub["tail_mag_63"].mean() / base_tail[63],
                      "hr_capture_63": 100 * sub["home_run_63"].sum() / base_hr_n[63]})
sens = pd.DataFrame(sens_rows)
print("\n--- Threshold sensitivity (+-10pts, SCREEN&RS70, 63d) ---")
print(sens.round(3).to_string(index=False))
sens.to_csv(CACHE / "m2_threshold_sensitivity.csv", index=False)
