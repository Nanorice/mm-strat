"""R1b M2b: characterize the missing-fundamental bucket (lift 2.4x!) + age proxy.

listing_date is NULL in company_profiles for panel names -> age proxy = years
since first price bar in price_data.
"""
import duckdb
import pandas as pd
from pathlib import Path

CACHE = Path("data/research_cache/r1b")
con = duckdb.connect("data/market_data.duckdb", read_only=True)

cov = con.execute("SELECT COUNT(*) n, SUM(CASE WHEN listing_date IS NULL THEN 1 ELSE 0 END) n_null FROM company_profiles").df()
print("company_profiles listing_date:", cov.to_dict("records")[0], flush=True)

first_bar = con.execute("SELECT ticker, MIN(date) AS first_bar FROM price_data GROUP BY ticker").df()
con.close()

df = pd.read_parquet(CACHE / "panel.parquet")
df["date"] = pd.to_datetime(df["date"])
df = df.merge(first_bar, on="ticker", how="left")
df["age_yrs"] = (df["date"] - pd.to_datetime(df["first_bar"])).dt.days / 365.25

CRIT = ["eps_growth_yoy", "revenue_growth_yoy", "gross_margin_trend", "eps_accel", "revenue_accel"]
has_fund = df[CRIT].notna().all(axis=1)
fresh = df["days_since_report"] <= 135
screen = ((df["eps_growth_yoy"] >= 25) & (df["revenue_growth_yoy"] >= 20)
          & (df["gross_margin_trend"] > 0) & (df["eps_accel"] > 0)
          & (df["revenue_accel"] > 0) & fresh)
rs70 = df["rs_universe_rank"] >= 0.70
missing = rs70 & ~has_fund

print("\n--- Age (yrs since first price bar) by bucket ---")
for nm, m in [("panel", pd.Series(True, index=df.index)), ("RS>=70", rs70),
              ("SCREEN&RS70", screen & rs70), ("missing-fund (RS>=70)", missing)]:
    a = df.loc[m, "age_yrs"]
    cap = (df.loc[m, "px_close"] * df.loc[m, "shares_outstanding"]) / 1e9
    print(f"{nm:24s} age p25/50/75 = {a.quantile(0.25):5.1f}/{a.median():5.1f}/{a.quantile(0.75):5.1f}"
          f" | pct age<3y = {100*(a < 3).mean():4.1f}% | mktcap med $B = {cap.median():.2f}")

print("\n--- Which criteria are missing in the missing bucket ---")
print(df.loc[missing, CRIT].isna().mean().mul(100).round(1).to_string())

print("\n--- Missing bucket era stability (tail lift vs same-period panel, 63d/126d) ---")
period = pd.cut(df["date"].dt.year, bins=[0, 2011, 2018, 2100], labels=["P1_<2012", "P2_2012-18", "P3_2019+"])
rows = []
for p in period.cat.categories:
    pm = period == p
    sub, ref = df[missing & pm], df[pm]
    rows.append({"period": p, "rows": len(sub),
                 "tail_lift_63": sub["tail_mag_63"].mean() / ref["tail_mag_63"].mean(),
                 "hr_capture_63": 100 * sub["home_run_63"].sum() / ref["home_run_63"].sum(),
                 "tail_lift_126": sub["tail_mag_126"].mean() / ref["tail_mag_126"].mean(),
                 "pct_age_lt3": 100 * (df.loc[missing & pm, "age_yrs"] < 3).mean()})
era = pd.DataFrame(rows)
print(era.round(2).to_string(index=False))
era.to_csv(CACHE / "m2b_missing_bucket_era.csv", index=False)

# age split of the missing-bucket lift: is it just youth?
young = df["age_yrs"] < 3
rows = []
for nm, m in [("missing & young<3y", missing & young), ("missing & old>=3y", missing & ~young),
              ("RS>=70 & young<3y (any fund)", rs70 & young), ("RS>=70 & old & has_fund", rs70 & ~young & has_fund)]:
    sub = df[m]
    rows.append({"bucket": nm, "rows": len(sub),
                 "tail_lift_63": sub["tail_mag_63"].mean() / df["tail_mag_63"].mean(),
                 "hr_rate_63": sub["home_run_63"].mean()})
ys = pd.DataFrame(rows)
print("\n--- Is the missing-fund lift a youth effect? ---")
print(ys.round(3).to_string(index=False))
ys.to_csv(CACHE / "m2b_missing_youth_split.csv", index=False)
