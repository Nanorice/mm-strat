"""R1b follow-up: is missing-fundamental/small-cap a real SECOND watchlist axis next to RS?

Tests: (1) incremental to RS bands, (2) is the true axis market-cap, (3) does the
lift survive volatility matching (MFE is vol-inflated), (4) tradability.
"""
import duckdb
import pandas as pd
from pathlib import Path

CACHE = Path("data/research_cache/r1b")
pd.set_option("display.width", 300)

con = duckdb.connect("data/market_data.duckdb", read_only=True)
df = con.execute(f"""
    SELECT p.*, f.volatility_20d, f.adr_20d, f.dollar_volume_avg_20
    FROM read_parquet('{(CACHE / "panel.parquet").as_posix()}') p
    JOIN t3_training_cache f USING (ticker, date)
""").df()
con.close()
df["date"] = pd.to_datetime(df["date"])
print(f"Panel + vol/liq cols: {len(df):,} rows", flush=True)

CRIT = ["eps_growth_yoy", "revenue_growth_yoy", "gross_margin_trend", "eps_accel", "revenue_accel"]
df["missing"] = df[CRIT].isna().any(axis=1)
df["cap"] = df["px_close"] * df["shares_outstanding"]
df["cap_rk"] = df.groupby("date")["cap"].rank(pct=True)
df["vol_q"] = df.groupby("date")["volatility_20d"].rank(pct=True).mul(5).apply(lambda x: min(int(x) + 1, 5))
base_tail = df["tail_mag_63"].mean()

def lift(m) -> float:
    return df.loc[m, "tail_mag_63"].mean() / base_tail

# ---------- 1. incremental to RS? fund status x RS band ----------
rows = []
for lo, hi, band in [(0.70, 0.80, "RS 70-80"), (0.80, 0.90, "RS 80-90"), (0.90, 1.01, "RS 90+")]:
    b = (df["rs_universe_rank"] >= lo) & (df["rs_universe_rank"] < hi)
    for st, m in [("has_fund", b & ~df["missing"]), ("missing", b & df["missing"])]:
        rows.append({"rs_band": band, "fund": st, "rows": m.sum(), "tail_lift_63": lift(m),
                     "hr_rate_63": df.loc[m, "home_run_63"].mean()})
t1 = pd.DataFrame(rows)
print("\n--- 1. Fund status x RS band (lift vs panel) ---")
print(t1.round(3).to_string(index=False))
t1.to_csv(CACHE / "axis2_rs_band_grid.csv", index=False)

# ---------- 2. is the axis really CAP? ----------
df["cap_dec"] = df["cap_rk"].mul(10).apply(lambda x: min(int(x) + 1, 10))
t2 = df.groupby("cap_dec").apply(
    lambda g: pd.Series({"rows": len(g), "tail_lift_63": g["tail_mag_63"].mean() / base_tail,
                         "hr_rate_63": g["home_run_63"].mean(),
                         "pct_missing": 100 * g["missing"].mean()}), include_groups=False)
print("\n--- 2a. Cap-decile ramp (D1=smallest), unconditional ---")
print(t2.round(3).to_string())
t2.to_csv(CACHE / "axis2_cap_decile_ramp.csv")

d10 = df["rs_universe_rank"] >= 0.90
t2b = df[d10].groupby("cap_dec").apply(
    lambda g: pd.Series({"rows": len(g), "tail_lift_63": g["tail_mag_63"].mean() / base_tail,
                         "hr_rate_63": g["home_run_63"].mean()}), include_groups=False)
print("\n--- 2b. Cap-decile ramp WITHIN RS-D10 ---")
print(t2b.round(3).to_string())
t2b.to_csv(CACHE / "axis2_cap_decile_within_d10.csv")

# missingness residual after cap: within per-date cap terciles
df["cap_ter"] = df["cap_rk"].mul(3).apply(lambda x: min(int(x) + 1, 3))
rows = []
for t in (1, 2, 3):
    b = df["cap_ter"] == t
    for st, m in [("has_fund", b & ~df["missing"]), ("missing", b & df["missing"])]:
        rows.append({"cap_tercile": t, "fund": st, "rows": m.sum(), "tail_lift_63": lift(m)})
t2c = pd.DataFrame(rows)
print("\n--- 2c. Missingness residual within cap terciles ---")
print(t2c.round(3).to_string(index=False))
t2c.to_csv(CACHE / "axis2_missing_within_cap.csv")

# ---------- 3. vol control: does anything survive vol matching? ----------
rows = []
for q in range(1, 6):
    b = df["vol_q"] == q
    rows.append({"vol_quintile": q, "panel_lift": lift(b),
                 "smallcap_T1_lift": lift(b & (df["cap_ter"] == 1)),
                 "missing_lift": lift(b & df["missing"]),
                 "has_fund_lift": lift(b & ~df["missing"]),
                 "rsD10_lift": lift(b & d10),
                 "rsD10_smallcap_lift": lift(b & d10 & (df["cap_ter"] == 1))})
t3 = pd.DataFrame(rows)
print("\n--- 3. Lift within per-date volatility quintiles (Q5=most volatile) ---")
print(t3.round(3).to_string(index=False))
t3.to_csv(CACHE / "axis2_vol_matched.csv", index=False)

# ---------- 4. tradability ----------
print("\n--- 4. Tradability: dollar_volume_avg_20 ($M/day) ---")
for nm, m in [("panel", pd.Series(True, index=df.index)),
              ("missing & RS>=70", df["missing"] & (df["rs_universe_rank"] >= 0.70)),
              ("smallcap T1 & RS-D10", (df["cap_ter"] == 1) & d10)]:
    dv = df.loc[m, "dollar_volume_avg_20"] / 1e6
    print(f"{nm:22s} p25/50/75 = {dv.quantile(0.25):7.1f}/{dv.median():7.1f}/{dv.quantile(0.75):7.1f}"
          f" | %>=$5M/day = {100 * (dv >= 5).mean():5.1f}% | %>=$20M/day = {100 * (dv >= 20).mean():5.1f}%")

# ---------- 5. era stability of the surviving candidate axes within RS-D10 ----------
period = pd.cut(df["date"].dt.year, bins=[0, 2011, 2018, 2100], labels=["P1_<2012", "P2_2012-18", "P3_2019+"])
rows = []
for nm, m in [("RS-D10 & missing", d10 & df["missing"]),
              ("RS-D10 & smallcap T1", d10 & (df["cap_ter"] == 1)),
              ("RS-D10 & has_fund & bigcap T3", d10 & ~df["missing"] & (df["cap_ter"] == 3))]:
    for p in period.cat.categories:
        pm = period == p
        rows.append({"arm": nm, "period": p, "rows": (m & pm).sum(),
                     "tail_lift_63": df.loc[m & pm, "tail_mag_63"].mean() / df.loc[pm, "tail_mag_63"].mean()})
t5 = pd.DataFrame(rows)
print("\n--- 5. Era stability within RS-D10 (lift vs same-period panel) ---")
print(t5.round(3).to_string(index=False))
t5.to_csv(CACHE / "axis2_era_stability.csv", index=False)
