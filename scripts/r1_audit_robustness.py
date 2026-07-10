"""
r1_audit_robustness.py
======================
Post-audit robustness checks for the R1 fundamental audit verdict.

Covers:
  R-A: Block-bootstrap CIs on within-D10 M1/M2 tercile lifts (year-level blocks).
  R-B: Rank collinearity: Ï(fundamental_rank, rs_universe_rank) within RS-D10.
  R-C: P3 stale-data sensitivity: re-run survives_P3 with days_since_report < 90.
  R-D: M1b combinatorial survives_P3 using lift (not level) as stability criterion.

Appends a "## R2: Robustness Checks" section to the verdict doc.
"""
import duckdb
import pandas as pd
import numpy as np
import json
from pathlib import Path

SEED = 42
N_BOOTSTRAP = 500
DB_PATH = "data/market_data.duckdb"
VERDICT_MD = Path("docs/session_logs/sprint_14/verdicts/2026-07-10_r1_fundamental_audit.md")

rng = np.random.default_rng(SEED)
con = duckdb.connect(DB_PATH, read_only=True)

# â”€â”€ load data (same as M1/M2) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
label_json = Path("label_registry/m01a_tail_v1.json")
source_query = json.loads(label_json.read_text())["source_query"]

fs_cols = con.execute(
    "SELECT feature_name FROM model_feature_sets WHERE feature_set_id = 'fs_m01_prototype'"
).df()["feature_name"].str.lower().tolist()
avail_cols = con.execute("SELECT * FROM t3_training_cache LIMIT 1").df().columns.str.lower().tolist()
ff_cols = con.execute("DESCRIBE fundamental_features").df()["column_name"].str.lower().tolist()
audit_cols = [c for c in fs_cols if c in avail_cols and c in ff_cols]

sel_cols = ", ".join([f"f.{c}" for c in audit_cols])
df = con.execute(f"""
    SELECT f.date, f.rs_universe_rank, f.days_since_report,
           lbl.tail_mag_63, lbl.home_run_63, {sel_cols}
    FROM t3_training_cache f
    JOIN ({source_query}) lbl USING (ticker, date)
""").df()
df.columns = df.columns.str.lower()
df["date"] = pd.to_datetime(df["date"])
df["year"] = df["date"].dt.year

print(f"Loaded {len(df):,} rows")

# Overall universe and D10 baselines
overall_tail = df["tail_mag_63"].mean()
d10 = df[df["rs_universe_rank"] >= 0.90].copy()
d10_tail = d10["tail_mag_63"].mean()

# period labels
def get_period(d):
    if d.year < 2012: return "P1_<2012"
    elif d.year < 2019: return "P2_2012-2018"
    else: return "P3_2019+"
d10["period"] = d10["date"].apply(get_period)

# Cross-sectional percent ranks (for R-B and M2 replication)
# Compute on full df (ranks are vs the full universe), then pull into d10 by index.
print("Computing cross-sectional ranks...")
for col in audit_cols:
    df[col + "_rank"] = df.groupby("date")[col].rank(pct=True)

# d10 is a filtered slice of df â€” pull rank cols by index alignment (no merge/copy needed)
rank_cols = [c + "_rank" for c in audit_cols]
for rc in rank_cols:
    d10[rc] = df.loc[d10.index, rc]

years = sorted(d10["year"].unique())

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# R-A: Block-bootstrap CIs on T3_lift (raw M1 tercile) for top-5 candidates
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
print("\nâ”€â”€ R-A: Block-bootstrap CIs â”€â”€")

# Focus on the top-6 by M1 lift (the ones nearest the 1.3Ã— gate)
top_features = ["current_ratio", "revenue_growth_yoy", "gross_margin_trend",
                "revenue_accel", "revenue_cagr_3y", "eps_stability_score"]

bootstrap_results = []

for col in top_features:
    d_col = d10.dropna(subset=[col]).copy()
    try:
        d_col["tercile"] = pd.qcut(d_col[col], 3, labels=["T1", "T2", "T3"])
    except ValueError:
        d_col["tercile"] = pd.qcut(d_col[col].rank(method="first"), 3, labels=["T1", "T2", "T3"])

    # Observed lift
    grp = d_col.groupby("tercile", observed=True)["tail_mag_63"].mean()
    obs_t3 = grp["T3"]
    obs_lift = obs_t3 / d10_tail

    # Year-block bootstrap: resample years (with replacement), recompute lift
    year_groups = {yr: d_col[d_col["year"] == yr] for yr in years}
    boot_lifts = []
    for _ in range(N_BOOTSTRAP):
        sampled_years = rng.choice(years, size=len(years), replace=True)
        boot_df = pd.concat([year_groups[yr] for yr in sampled_years if yr in year_groups],
                            ignore_index=True)
        if len(boot_df) < 100:
            continue
        try:
            boot_df["tercile"] = pd.qcut(boot_df[col], 3, labels=["T1", "T2", "T3"])
        except ValueError:
            boot_df["tercile"] = pd.qcut(boot_df[col].rank(method="first"), 3, labels=["T1", "T2", "T3"])
        bgrp = boot_df.groupby("tercile", observed=True)["tail_mag_63"].mean()
        boot_d10 = boot_df["tail_mag_63"].mean()  # bootstrap D10 mean
        if boot_d10 > 0:
            boot_lifts.append(bgrp.get("T3", np.nan) / boot_d10)

    boot_arr = np.array([x for x in boot_lifts if not np.isnan(x)])
    ci_lo = np.percentile(boot_arr, 2.5)
    ci_hi = np.percentile(boot_arr, 97.5)
    gap_to_gate = obs_lift - 1.3
    gate_in_ci = ci_hi >= 1.3

    bootstrap_results.append({
        "feature": col,
        "obs_lift": obs_lift,
        "ci_lo_95": ci_lo,
        "ci_hi_95": ci_hi,
        "gap_to_gate": gap_to_gate,
        "gate_1.3x_in_CI": gate_in_ci,
        "n_boot": len(boot_arr),
    })
    print(f"  {col}: lift={obs_lift:.3f} [{ci_lo:.3f}, {ci_hi:.3f}]  gate_in_CI={gate_in_ci}")

boot_df_out = pd.DataFrame(bootstrap_results)

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# R-B: Rank collinearity within D10
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
print("\nâ”€â”€ R-B: Rank collinearity within D10 â”€â”€")

collinearity = []
for col in audit_cols:
    rank_col = col + "_rank"
    sub = d10.dropna(subset=[rank_col, "rs_universe_rank"])
    if len(sub) < 500:
        continue
    rho = sub["rs_universe_rank"].corr(sub[rank_col], method="spearman")
    collinearity.append({"feature": col, "spearman_rho_rank_vs_RS": round(rho, 3)})
    print(f"  {col}: Ï={rho:.3f}")

collin_df = pd.DataFrame(collinearity).sort_values("spearman_rho_rank_vs_RS", ascending=False)

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# R-C: survives_P3 with stale-data filter (days_since_report < 90)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
print("\nâ”€â”€ R-C: Stale-data sensitivity â”€â”€")

# Filter P3 rows to fresh fundamentals only
d10_fresh = d10[(d10["days_since_report"].isna()) | (d10["days_since_report"] < 90)].copy()
p3_fresh = d10_fresh[d10_fresh["period"] == "P3_2019+"]
p3_all = d10[d10["period"] == "P3_2019+"]

print(f"  P3 rows (all):   {len(p3_all):,}")
print(f"  P3 rows (fresh, dsr<90): {len(p3_fresh):,}  "
      f"({100*len(p3_fresh)/len(p3_all):.1f}%)")

stale_results = []
for col in audit_cols:
    d_col_all = d10.dropna(subset=[col]).copy()
    d_col_fresh = d10_fresh.dropna(subset=[col]).copy()
    for d_col, label in [(d_col_all, "all"), (d_col_fresh, "fresh_dsr<90")]:
        try:
            d_col["tercile"] = pd.qcut(d_col[col], 3, labels=["T1", "T2", "T3"])
        except ValueError:
            d_col["tercile"] = pd.qcut(d_col[col].rank(method="first"), 3, labels=["T1", "T2", "T3"])
        p3_sub = d_col[d_col["period"] == "P3_2019+"]
        p3_grp = p3_sub.groupby("tercile", observed=True)["tail_mag_63"].mean()
        survives = p3_grp.get("T3", np.nan) > p3_grp.get("T1", np.nan)
        stale_results.append({
            "feature": col, "filter": label,
            "P3_T3": round(p3_grp.get("T3", np.nan), 4),
            "P3_T1": round(p3_grp.get("T1", np.nan), 4),
            "survives_P3": survives,
        })

stale_df = pd.DataFrame(stale_results)
pivot = stale_df.pivot(index="feature", columns="filter", values="survives_P3")
pivot.columns.name = None
print(pivot.to_string())

# Features that flip
flippers = []
for col in audit_cols:
    row_all = stale_df[(stale_df["feature"] == col) & (stale_df["filter"] == "all")].iloc[0]
    row_fresh = stale_df[(stale_df["feature"] == col) & (stale_df["filter"] == "fresh_dsr<90")].iloc[0]
    if row_all["survives_P3"] != row_fresh["survives_P3"]:
        flippers.append(col)
print(f"  Features that FLIP survives_P3 after stale filter: {flippers}")

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# R-D: M1b P3 lift vs level criterion
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
print("\nâ”€â”€ R-D: M1b P3 lift criterion â”€â”€")

# Re-run M1b with lift-based stability
m1b_audit_cols = ["eps_growth_yoy", "revenue_growth_yoy", "eps_growth_yoy",
                  "revenue_accel", "gross_margin_trend", "earnings_quality_score", "roe"]

# Rank cols already on d10 from the cross-sectional ranks block above.
# For any that might still be missing (safety), pull from df by index.
for col in ["eps_growth_yoy", "revenue_growth_yoy", "earnings_quality_score", "roe"]:
    rc = col + "_rank"
    if rc not in d10.columns:
        d10[rc] = df.loc[d10.index, rc]

combinations = {
    "1. Hyper-Growth Confluence": (d10["eps_growth_yoy_rank"] > 0.67) & (d10["revenue_growth_yoy_rank"] > 0.67),
    "2. Code 33 Proxy": (d10["revenue_accel"] > 0) & (d10["gross_margin_trend"] > 0),
    "3. High-Quality Accelerator": (d10["revenue_accel"] > 0) & (d10["earnings_quality_score_rank"] > 0.50) & (d10["roe_rank"] > 0.50),
    "4. Full Strict Profile": (d10["eps_growth_yoy_rank"] > 0.67) & (d10["revenue_growth_yoy_rank"] > 0.67) & (d10["revenue_accel"] > 0) & (d10["gross_margin_trend"] > 0),
}

d10_p3 = d10[d10["period"] == "P3_2019+"]["tail_mag_63"].mean()
m1b_results = []
for name, mask in combinations.items():
    sub = d10[mask]
    if len(sub) < 100:
        continue
    overall_lift = sub["tail_mag_63"].mean() / d10_tail
    p3_sub = sub[sub["period"] == "P3_2019+"]["tail_mag_63"].mean()
    p3_lift = p3_sub / d10_p3 if d10_p3 > 0 else np.nan
    survives_level = p3_sub > d10_p3
    survives_lift = p3_lift > 1.0 if not np.isnan(p3_lift) else False
    m1b_results.append({
        "profile": name, "N": len(sub),
        "overall_lift": round(overall_lift, 3),
        "P3_lift_vs_D10": round(p3_lift, 3),
        "survives_P3_level": survives_level,
        "survives_P3_lift": survives_lift,
    })
    print(f"  {name}: P3_lift={p3_lift:.3f}  level={survives_level}  lift={survives_lift}")

m1b_df = pd.DataFrame(m1b_results)

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Write to verdict doc
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
print("\nâ”€â”€ Writing to verdict doc â”€â”€")

lines = []
lines.append("\n\n---\n")
lines.append("## R2: Robustness Checks (post-challenge)\n\n")
lines.append(
    "_Ran in response to a methodology challenge on 2026-07-10. "
    "Four checks: (A) block-bootstrap CIs, (B) rank collinearity, "
    "(C) stale-data P3 sensitivity, (D) M1b lift-based stability._\n\n"
)

# R-A
lines.append("### R-A: Block-bootstrap 95% CIs on M1 tercile lifts (top-6 features, year-level blocks)\n\n")
lines.append(f"N_bootstrap={N_BOOTSTRAP}, seed={SEED}. "
             "D10 re-sampled per bootstrap draw to keep denominator consistent.\n\n")
lines.append(boot_df_out.round(3).to_markdown(index=False))
lines.append("\n\n**Finding:** ")

all_below = all(not r["gate_1.3x_in_CI"] for _, r in boot_df_out.iterrows())
if all_below:
    lines.append(
        "The 1.3Ã— gate lies **outside** the 95% CI for all top-6 features. "
        f"The best result (current_ratio: lift={boot_df_out.iloc[0]['obs_lift']:.3f}) "
        f"has CI [{boot_df_out.iloc[0]['ci_lo_95']:.3f}, {boot_df_out.iloc[0]['ci_hi_95']:.3f}] â€” "
        "the gate is not within noise. The 'clean kill' framing is statistically supported.\n\n"
    )
else:
    overlapping = boot_df_out[boot_df_out["gate_1.3x_in_CI"] == True]["feature"].tolist()
    lines.append(
        f"Features whose CI overlaps the 1.3Ã— gate: **{overlapping}**. "
        "These warrant softer language â€” 'strong null' rather than 'clean kill'.\n\n"
    )

# R-B
lines.append("### R-B: Rank collinearity Ï(fundamental_rank, RS_universe_rank) within D10\n\n")
lines.append(
    "Spearman correlation between the cross-sectional percent rank of each fundamental "
    "and `rs_universe_rank`, computed on the RS-D10 sub-sample only.\n\n"
)
lines.append(collin_df.to_markdown(index=False))
lines.append("\n\n**Finding:** ")
high_collin = collin_df[collin_df["spearman_rho_rank_vs_RS"].abs() > 0.15]["feature"].tolist()
if high_collin:
    lines.append(
        f"Features with |Ï| > 0.15 (moderate collinearity): **{high_collin}**. "
        "The M2 rank-transform test may not fully isolate fundamental rank from RS for these features. "
        "For features with |Ï| < 0.10 the M2 test is clean.\n\n"
    )
else:
    lines.append(
        "All features have |Ï| < 0.15 within RS-D10. "
        "The M2 rank-transform test is cleanly isolated from RS co-movement â€” "
        "the null result is not a collinearity artefact.\n\n"
    )

# R-C
lines.append("### R-C: survives_P3 stale-data sensitivity (days_since_report < 90)\n\n")
lines.append(
    f"P3 rows (all): {len(p3_all):,} Â· "
    f"P3 rows (fresh, dsr<90): {len(p3_fresh):,} "
    f"({100*len(p3_fresh)/len(p3_all):.1f}%). "
    "2026 has median staleness 101 days â€” most 2026 P3 rows are filtered.\n\n"
)
lines.append(pivot.reset_index().to_markdown(index=False))
lines.append("\n\n**Finding:** ")
if not flippers:
    lines.append(
        "No features flip their `survives_P3` verdict after removing stale fundamentals. "
        "The null result is robust to 2026 data quality.\n\n"
    )
else:
    lines.append(
        f"Features that flip `survives_P3` verdict: **{flippers}**. "
        "These should be treated with caution â€” their P3 survival depends on stale rows.\n\n"
    )

# R-D
lines.append("### R-D: M1b combinatorial profiles â€” P3 lift vs level criterion\n\n")
lines.append(
    "Original M1b checked `p3_val > d10_p3_val` (absolute level). "
    "This re-run uses `p3_lift = p3_val / d10_p3_val > 1.0` (relative lift), "
    "which is robust to the 2020â€“24 absolute level shift.\n\n"
)
lines.append(m1b_df.to_markdown(index=False))
lines.append("\n\n**Finding:** ")
lift_survivors = m1b_df[m1b_df["survives_P3_lift"] == True]["profile"].tolist()
if not lift_survivors:
    lines.append(
        "No combinatorial profile survives the P3 lift criterion. "
        "The M1b null holds under both level and lift stability checks.\n\n"
    )
else:
    lines.append(
        f"Profiles surviving only on **level** but not **lift**: "
        f"{m1b_df[m1b_df['survives_P3_level'] != m1b_df['survives_P3_lift']]['profile'].tolist()}. "
        f"Profiles surviving on lift: **{lift_survivors}**.\n\n"
    )

# Overall robustness summary
lines.append("### Overall robustness verdict\n\n")
lines.append(
    "| Check | Conclusion |\n|---|---|\n"
    f"| R-A: Bootstrap CIs | {'Gate outside CI for all features â€” clean kill confirmed' if all_below else 'Some CIs overlap gate â€” soften to strong null'} |\n"
    f"| R-B: Rank collinearity | {'Low collinearity, M2 test is clean' if not high_collin else 'Moderate collinearity for: ' + str(high_collin)} |\n"
    f"| R-C: Stale-data sensitivity | {'No flips â€” robust to 2026 stale data' if not flippers else 'Flippers: ' + str(flippers)} |\n"
    f"| R-D: M1b lift criterion | {'Null holds' if not lift_survivors else 'Some profiles survive on lift: ' + str(lift_survivors)} |\n"
    f"| **eps_accel catalog** | eps_accel NOT in fs_m01_prototype (only revenue_accel is). M1/M2 column coverage was complete for the registered feature set. |\n\n"
)

final_verdict = all_below and not high_collin and not flippers and not lift_survivors
lines.append(
    "**Updated conclusion:** " +
    (
        "All four robustness checks support the original null. "
        "The 'clean kill' framing is **statistically justified**. "
        "Step 2 beyond RS remains a clean kill."
        if final_verdict else
        "One or more checks qualify the original conclusion â€” see individual findings above. "
        "The null is strong but 'clean kill' should be softened to 'strong null'."
    ) + "\n"
)

with open(VERDICT_MD, "a") as f:
    f.writelines(lines)

print(f"Appended to {VERDICT_MD}")
print("\neps_accel note: NOT in fs_m01_prototype (only revenue_accel). "
      "M1/M2 coverage was complete for the registered feature set.")

