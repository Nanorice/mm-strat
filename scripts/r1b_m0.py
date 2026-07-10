"""R1b M0: corrected step-1 gate — RS-percentile floor sweep on the trend_ok panel.

Funnel triple per cut: names remaining (median/day + rows retained), tail lift
vs panel, home-run capture (% of all panel home-runs surviving).
"""
import pandas as pd
from pathlib import Path

CACHE = Path("data/research_cache/r1b")
df = pd.read_parquet(CACHE / "panel.parquet",
                     columns=["ticker", "date", "rs_universe_rank",
                              "tail_mag_63", "home_run_63", "tail_mag_126", "home_run_126"])
print(f"Panel: {len(df):,} rows")

base_tail = {63: df["tail_mag_63"].mean(), 126: df["tail_mag_126"].mean()}
base_hr_n = {63: df["home_run_63"].sum(), 126: df["home_run_126"].sum()}

rows = []
for cut in [0.0, 0.70, 0.80, 0.90]:
    sub = df[df["rs_universe_rank"] >= cut]
    names_day = sub.groupby("date")["ticker"].nunique().median()
    r = {"rs_floor": f">={int(cut*100)}pct" if cut else "panel (none)",
         "rows": len(sub), "pct_of_panel": 100 * len(sub) / len(df),
         "median_names_per_day": names_day}
    for h in (63, 126):
        r[f"tail_lift_{h}"] = sub[f"tail_mag_{h}"].mean() / base_tail[h]
        r[f"hr_rate_{h}"] = sub[f"home_run_{h}"].mean()
        r[f"hr_capture_{h}"] = 100 * sub[f"home_run_{h}"].sum() / base_hr_n[h]
    rows.append(r)

res = pd.DataFrame(rows)
pd.set_option("display.width", 250)
print(res.round(3).to_string(index=False))
res.to_csv(CACHE / "m0_rs_floor_sweep.csv", index=False)
print(f"\nCached -> {CACHE / 'm0_rs_floor_sweep.csv'}")

# RS distribution inside trend_ok (context: how much RS work does step 1 already do?)
dist = df["rs_universe_rank"].describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9]).round(3)
print("\nrs_universe_rank distribution within trend_ok panel:")
print(dist.to_string())
