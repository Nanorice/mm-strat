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

fs_cols_df = con.execute("SELECT feature_name FROM model_feature_sets WHERE feature_set_id = 'fs_m01_prototype'").df()
fs_cols = fs_cols_df['feature_name'].str.lower().tolist()
avail_cols_df = con.execute("SELECT * FROM t3_training_cache LIMIT 1").df()
avail_cols = [c.lower() for c in avail_cols_df.columns]
fund_cols_df = con.execute("DESCRIBE fundamental_features").df()
fund_all_cols = [c.lower() for c in fund_cols_df['column_name']]
use_cols = [c for c in fs_cols if c in avail_cols]
audit_cols = [c for c in use_cols if c in fund_all_cols]

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

# Compute per-date cross-sectional percent rank for all features
print("Computing cross-sectional percent ranks...")
for col in audit_cols:
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

results = []

for col in audit_cols:
    rank_col = col + '_rank'
    d_col = d10.dropna(subset=[rank_col]).copy()
    if len(d_col) < 1000:
        continue
    
    # Terciles on rank value within RS-D10
    try:
        d_col['tercile'] = pd.qcut(d_col[rank_col], 3, labels=['T1_Bottom', 'T2_Mid', 'T3_Top'])
    except ValueError:
        d_col['tercile'] = pd.qcut(d_col[rank_col].rank(method='first'), 3, labels=['T1_Bottom', 'T2_Mid', 'T3_Top'])
    
    # Calculate conditional lift vs D10 baseline
    t_stats = d_col.groupby('tercile', observed=True).agg(
        tail_mag=('tail_mag_63', 'mean'),
        hr=('home_run_63', 'mean'),
        n=('tail_mag_63', 'count')
    )
    
    t3_tail = t_stats.loc['T3_Top', 'tail_mag']
    t1_tail = t_stats.loc['T1_Bottom', 'tail_mag']
    t3_hr = t_stats.loc['T3_Top', 'hr']
    t1_hr = t_stats.loc['T1_Bottom', 'hr']
    
    # Lift vs RS-D10 baseline (not universe)
    lift_tail = t3_tail / d10_tail
    lift_hr = t3_hr / d10_hr
    
    # Monotonicity check
    is_monotone_tail = (t_stats.loc['T3_Top', 'tail_mag'] >= t_stats.loc['T2_Mid', 'tail_mag'] >= t_stats.loc['T1_Bottom', 'tail_mag'])
    is_monotone_hr = (t_stats.loc['T3_Top', 'hr'] >= t_stats.loc['T2_Mid', 'hr'] >= t_stats.loc['T1_Bottom', 'hr'])
    
    # Stability across periods
    p_stats = d_col.groupby(['period', 'tercile'], observed=True)['tail_mag_63'].mean().unstack()
    p3_t3 = p_stats.loc['P3_2019+', 'T3_Top']
    p3_t1 = p_stats.loc['P3_2019+', 'T1_Bottom']
    survives_p3 = p3_t3 > p3_t1
    
    results.append({
        'feature': col,
        'N_valid': len(d_col),
        'T1_tail': t1_tail,
        'T3_tail': t3_tail,
        'T3_lift_vs_D10_tail': lift_tail,
        'T1_hr': t1_hr,
        'T3_hr': t3_hr,
        'T3_lift_vs_D10_hr': lift_hr,
        'monotone_tail': is_monotone_tail,
        'monotone_hr': is_monotone_hr,
        'survives_P3': survives_p3
    })

res_df = pd.DataFrame(results)
res_df = res_df.sort_values('T3_lift_vs_D10_tail', ascending=False)
print("\n--- M2: Within-RS-D10 conditional splits (Cross-sectional Rank) ---")
pd.set_option('display.max_columns', None)
print(res_df.to_string(index=False))

winners = res_df[(res_df['T3_lift_vs_D10_tail'] >= 1.3) & res_df['monotone_tail'] & res_df['survives_P3']]
print("\nWinners (Tail Gate >= 1.3x, monotone, survives 2019+):")
if len(winners) > 0:
    print(winners.to_string(index=False))
else:
    print("None. Clean Kill.")

out_md = Path("docs/session_logs/sprint_14/verdicts/2026-07-10_r1_fundamental_audit.md")
with open(out_md, 'a') as f:
    f.write("\n## M2: Rank-transform Re-test (Cross-sectional PERCENT_RANK)\n\n")
    f.write(res_df.round(3).to_markdown(index=False))
    f.write("\n\nWinners:\n")
    if len(winners) > 0:
        f.write(winners.round(3).to_markdown(index=False))
    else:
        f.write("None cleared the gate. Clean Kill of step 2 fundamental features beyond RS.\n")
