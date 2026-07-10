"""R1b M2c: depth-matched head-to-head — book screen vs pure RS at equal selectivity."""
import pandas as pd
from pathlib import Path

CACHE = Path("data/research_cache/r1b")
df = pd.read_parquet(CACHE / "panel.parquet")
df["date"] = pd.to_datetime(df["date"])

CRIT = ["eps_growth_yoy", "revenue_growth_yoy", "gross_margin_trend", "eps_accel", "revenue_accel"]
fresh = df["days_since_report"] <= 135
screen = ((df["eps_growth_yoy"] >= 25) & (df["revenue_growth_yoy"] >= 20)
          & (df["gross_margin_trend"] > 0) & (df["eps_accel"] > 0)
          & (df["revenue_accel"] > 0) & fresh & (df["rs_universe_rank"] >= 0.70))

# per-date panel RS rank so the RS arm matches the screen's per-date depth
df["rs_panel_rank"] = df.groupby("date")["rs_universe_rank"].rank(pct=True)
depth = screen.mean()
rs_matched = df["rs_panel_rank"] >= (1 - depth)

rows = []
for nm, m in [("SCREEN & RS>=70 (3.7% depth)", screen), (f"pure RS top {depth:.1%}", rs_matched)]:
    sub = df[m]
    r = {"arm": nm, "rows": len(sub)}
    for h in (63, 126):
        r[f"tail_lift_{h}"] = sub[f"tail_mag_{h}"].mean() / df[f"tail_mag_{h}"].mean()
        r[f"hr_rate_{h}"] = sub[f"home_run_{h}"].mean()
        r[f"hr_capture_{h}"] = 100 * sub[f"home_run_{h}"].sum() / df[f"home_run_{h}"].sum()
    rows.append(r)
res = pd.DataFrame(rows)
pd.set_option("display.width", 250)
print(res.round(3).to_string(index=False))
res.to_csv(CACHE / "m2c_depth_matched.csv", index=False)
