import duckdb
import pandas as pd
import numpy as np
import json
from pathlib import Path

db_path = "data/market_data.duckdb"
con = duckdb.connect(db_path, read_only=True)

label_json = Path("label_registry/m01a_tail_v1.json")
spec = json.loads(label_json.read_text())
source_query = spec["source_query"]

# Identify columns to fetch
audit_cols = [
    'eps_growth_yoy', 'revenue_growth_yoy', 'eps_accel', 'revenue_accel', 
    'gross_margin_trend', 'earnings_quality_score', 'roe'
]

sel_cols = ", ".join([f"f.{c}" for c in audit_cols])
query = f"""
SELECT f.date, f.rs_universe_rank, lbl.tail_mag_63, lbl.home_run_63, {sel_cols}
FROM t3_training_cache f
JOIN ({source_query}) lbl USING (ticker, date)
"""
print("Loading data...")
df = con.execute(query).df()
df.columns = df.columns.str.lower()
print(f"Loaded {len(df)} rows.")

df['date'] = pd.to_datetime(df['date'])

# Compute per-date cross-sectional percent rank for percentiles
print("Computing cross-sectional percent ranks...")
rank_cols = ['eps_growth_yoy', 'revenue_growth_yoy', 'earnings_quality_score', 'roe']
for col in rank_cols:
    df[col + '_rank'] = df.groupby('date')[col].rank(pct=True)

overall_tail = df['tail_mag_63'].mean()
overall_hr = df['home_run_63'].mean()

# Filter to RS-D10
d10 = df[df['rs_universe_rank'] >= 0.90].copy()
d10_tail = d10['tail_mag_63'].mean()
d10_hr = d10['home_run_63'].mean()
d10_tail_lift = d10_tail / overall_tail
d10_hr_lift = d10_hr / overall_hr

def get_period(d):
    if d.year < 2012: return 'P1_<2012'
    elif d.year < 2019: return 'P2_2012-2018'
    else: return 'P3_2019+'
d10['period'] = d10['date'].apply(get_period)

combinations = {
    '1. Hyper-Growth Confluence': (d10['eps_growth_yoy_rank'] > 0.67) & (d10['revenue_growth_yoy_rank'] > 0.67),
    '2. Code 33 Proxy': (d10['eps_accel'] > 0) & (d10['revenue_accel'] > 0) & (d10['gross_margin_trend'] > 0),
    '3. High-Quality Accelerator': (d10['eps_accel'] > 0) & (d10['earnings_quality_score_rank'] > 0.50) & (d10['roe_rank'] > 0.50),
    '4. Full Strict Profile': (d10['eps_growth_yoy_rank'] > 0.67) & (d10['revenue_growth_yoy_rank'] > 0.67) & (d10['revenue_accel'] > 0) & (d10['gross_margin_trend'] > 0)
}

results = []

for name, mask in combinations.items():
    d_col = d10[mask].copy()
    if len(d_col) < 100:
        print(f"Skipping {name}, only {len(d_col)} rows.")
        continue
    
    t_tail = d_col['tail_mag_63'].mean()
    t_hr = d_col['home_run_63'].mean()
    
    # Lift vs RS-D10 baseline
    lift_tail = t_tail / d10_tail
    lift_hr = t_hr / d10_hr
    
    # Stability across periods
    p_stats = d_col.groupby('period')['tail_mag_63'].mean()
    p3_val = p_stats.get('P3_2019+', np.nan)
    d10_p3_val = d10[d10['period'] == 'P3_2019+']['tail_mag_63'].mean()
    survives_p3 = p3_val > d10_p3_val if not pd.isna(p3_val) else False
    
    results.append({
        'profile': name,
        'N_valid': len(d_col),
        'tail_mag': t_tail,
        'lift_vs_D10_tail': lift_tail,
        'home_run': t_hr,
        'lift_vs_D10_hr': lift_hr,
        'P3_tail': p3_val,
        'P3_lift_vs_D10': p3_val / d10_p3_val if not pd.isna(p3_val) else np.nan,
        'survives_P3': survives_p3
    })

res_df = pd.DataFrame(results)
print(f"\nBaseline RS-D10: tail_mag_63={d10_tail:.4f}, home_run={d10_hr:.4f}")
print("\n--- M1b: Combinatorial Splits ---")
pd.set_option('display.max_columns', None)
print(res_df.to_string(index=False))

out_md = Path("docs/session_logs/sprint_14/verdicts/2026-07-10_r1_fundamental_audit.md")
with open(out_md, 'a') as f:
    f.write("\n### M1b Execution Results\n\n")
    f.write(f"Baseline Unconditional RS-D10: tail_mag_63={d10_tail:.4f} (lift {d10_tail_lift:.2f}x universe)\n\n")
    f.write(res_df.round(3).to_markdown(index=False))
    f.write("\n\n")
    
    winners = res_df[(res_df['lift_vs_D10_tail'] >= 1.3) & res_df['survives_P3']]
    if len(winners) > 0:
        f.write("Winners:\n")
        f.write(winners.round(3).to_markdown(index=False))
        f.write("\n")
    else:
        f.write("**Conclusion:** None of the combinatorial profiles achieved the >= 1.3x gate while surviving 2019+. The null result holds even under strict confluence (AND logic). Step 2 beyond RS remains a clean kill.\n")

print("M1b complete.")
