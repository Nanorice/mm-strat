import duckdb
import pandas as pd
import json
from pathlib import Path

# Setup
db_path = "data/market_data.duckdb"
con = duckdb.connect(db_path, read_only=True)
label_json = Path("label_registry/m01a_tail_v1.json")
spec = json.loads(label_json.read_text())
source_query = spec["source_query"]

# 1. Get features in fs_m01_prototype
fs_cols_df = con.execute("SELECT feature_name FROM model_feature_sets WHERE feature_set_id = 'fs_m01_prototype' ORDER BY ordinal").df()
fs_cols = fs_cols_df['feature_name'].str.lower().tolist()

# 2. Get available cols in t3_training_cache
avail_cols_df = con.execute("SELECT * FROM t3_training_cache LIMIT 1").df()
avail_cols = [c.lower() for c in avail_cols_df.columns]

# 3. Intersection as in train_m01a_tail.py
use_cols = [c for c in fs_cols if c in avail_cols]

# 4. Find which of these are 'Fundamentals'
fund_cols_df = con.execute("DESCRIBE fundamental_features").df()
fund_all_cols = [c.lower() for c in fund_cols_df['column_name']]

audit_cols = [c for c in use_cols if c in fund_all_cols]
print(f"Fundamental features in audit ({len(audit_cols)}): {audit_cols}")

# Ensure days_since_report is selected
query_cols = list(audit_cols)
if 'days_since_report' not in query_cols:
    query_cols.append('days_since_report')

# 5. Build M0 coverage query
sel_cols = ", ".join([f"f.{c}" for c in query_cols])
query = f"""
WITH panel_data AS (
    SELECT f.date, {sel_cols}
    FROM t3_training_cache f
    JOIN ({source_query}) lbl USING (ticker, date)
)
SELECT 
    YEAR(date) as year,
    COUNT(*) as total_rows,
    {", ".join([f"SUM(CASE WHEN {c} IS NOT NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as cov_{c}" for c in audit_cols])},
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY days_since_report) as days_since_report_p50,
    PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY days_since_report) as days_since_report_p90
FROM panel_data
GROUP BY YEAR(date)
ORDER BY year
"""

print("Executing M0 coverage query...")
cov_df = con.execute(query).df()
pd.set_option('display.max_columns', None)
print(cov_df.to_string())

# Save to markdown
out_md = Path("docs/session_logs/sprint_14/verdicts/2026-07-10_r1_fundamental_audit.md")
out_md.parent.mkdir(parents=True, exist_ok=True)
with open(out_md, 'w') as f:
    f.write("# R1: Fundamental Coverage Audit (M0)\n\n")
    f.write(f"Fundamental features audited: {len(audit_cols)}\n")
    f.write(f"`{', '.join(audit_cols)}`\n\n")
    f.write("## Coverage by Year (% non-null)\n\n")
    f.write(cov_df.round(2).to_markdown(index=False))
    f.write("\n")

print("M0 complete. Saved to", out_md)
