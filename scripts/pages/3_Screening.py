"""Screening — the single "what to look at" surface (sprint-14 dashboard uplift).

One population (today's trend_ok ∨ breakout_ok universe), filterable by stage +
fundamentals, ranked by the prod model's P(Home Run). Retires the old Today
page's four overlapping candidate tables (Shortlist / Pre-Breakout / VIP /
Screener) into one view. Reads the nightly-materialized `v_d3_screening`.

Honest-forecast rule (project_champion_starttime_dependent): we present
P(Home Run) — a probability — NOT a point return. No expected-return column.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dashboard_utils import load_screening

# theta.md tokens (mirror scripts/pages/2_Macro.py) — a scoped strip so the
# native Streamlit widgets below still theme cleanly.
_HEADER_CSS = """
<style>
  .scr-wrap{font-family:"Source Serif 4",Georgia,serif;color:#1c1a17}
  .scr-title{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:11px;
    letter-spacing:.18em;text-transform:uppercase;color:#8a8272;
    border-bottom:1px solid #e8e3d6;padding-bottom:8px;margin:2px 0 12px}
  .scr-stats{display:flex;gap:26px;font-family:"JetBrains Mono",monospace;
    font-variant-numeric:tabular-nums;font-size:13px;color:#1c1a17;margin-bottom:4px}
  .scr-stats b{font-size:20px;font-weight:600}
  .scr-stats .lbl{color:#8a8272;font-size:11px;text-transform:uppercase;letter-spacing:.1em}
  .scr-stats .col{display:flex;flex-direction:column;gap:2px}
</style>
"""


def _header(df: pd.DataFrame) -> None:
    as_of = str(df["date"].iloc[0])[:10] if len(df) else "—"
    n = len(df)
    n_setup = int((df["stage"] == "setup").sum())
    n_trig = int((df["stage"] == "triggered").sum())
    n_scored = int(df["prob_home_run"].notna().sum())
    st.markdown(_HEADER_CSS + f"""
    <div class="scr-wrap">
      <div class="scr-title">SC · Screening — what to look at · as of {as_of}</div>
      <div class="scr-stats">
        <div class="col"><span class="lbl">Universe</span><b>{n}</b></div>
        <div class="col"><span class="lbl">Setup</span><b>{n_setup}</b></div>
        <div class="col"><span class="lbl">Triggered</span><b>{n_trig}</b></div>
        <div class="col"><span class="lbl">Scored</span><b>{n_scored}</b></div>
      </div>
    </div>
    """, unsafe_allow_html=True)


def _cap_tier(mcap: float) -> str:
    if pd.isna(mcap):
        return "—"
    if mcap >= 10e9:
        return "large"
    if mcap >= 2e9:
        return "mid"
    if mcap >= 300e6:
        return "small"
    return "micro"


_TABLE_COLS = {
    "ticker": st.column_config.TextColumn("Ticker", width="small"),
    "company_name": st.column_config.TextColumn("Name", width="medium"),
    "sector": st.column_config.TextColumn("Sector", width="small"),
    "stage": st.column_config.TextColumn("Stage", width="small"),
    "prob_home_run": st.column_config.NumberColumn("P(HR)", format="%.0f%%", width="small"),
    "close": st.column_config.NumberColumn("Price", format="$%.2f", width="small"),
    "gross_margin": st.column_config.NumberColumn("Gross %", format="%.0f", width="small"),
    "net_margin": st.column_config.NumberColumn("Net %", format="%.0f", width="small"),
    "pe_ratio": st.column_config.NumberColumn("P/E", format="%.1f", width="small"),
    "fcf": st.column_config.TextColumn("FCF", width="small"),
    "revenue_growth_yoy": st.column_config.NumberColumn("Rev g %", format="%.0f", width="small"),
    "rs_universe_rank": st.column_config.NumberColumn("RS", format="%.2f", width="small"),
}


def _shape(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["prob_home_run"] = out["prob_home_run"] * 100  # 0-1 → % for the formatter
    out["fcf"] = np.where(out["fcf_positive"].fillna(False), "＋", "－")
    out["stage"] = out["stage"].map({"setup": "◔ setup", "triggered": "● triggered"})
    return out[list(_TABLE_COLS.keys())]


st.markdown("### Screening")
st.caption("Every name in setup or triggered, ranked by the prod model's "
           "P(Home Run). Probability, not a return forecast (the median inverts — "
           "we present tail-odds; see the champion start-date cone).")

df = load_screening()
if df is None or df.empty:
    st.info("v_d3_screening snapshot not found — run the view "
            "(`ViewManager()._create_v_d3_screening`) and rebuild the slim DB.")
    st.stop()

df["cap_tier"] = df["market_cap"].apply(_cap_tier)
_header(df)

with st.form("screening_filters", border=False):
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        stage_f = st.selectbox("Stage", ["All", "Setup", "Triggered"], index=0)
        sector_f = st.selectbox("Sector", ["All"] + sorted(df["sector"].dropna().unique()))
    with c2:
        cap_f = st.selectbox("Market cap", ["All", "large", "mid", "small", "micro"])
        fcf_only = st.checkbox("FCF positive only", value=False)
    with c3:
        gm_min = st.number_input("Gross margin ≥ (%)", value=0, step=5)
        nm_min = st.number_input("Net margin ≥ (%)", value=-1000, step=5)
    with c4:
        pe_max = st.number_input("P/E ≤ (0 = no cap)", value=0, step=5)
        rg_min = st.number_input("Rev growth ≥ (%)", value=-1000, step=5)
    st.form_submit_button("Apply filters", type="primary")

d = df
if stage_f != "All":
    d = d[d["stage"] == stage_f.lower()]
if sector_f != "All":
    d = d[d["sector"] == sector_f]
if cap_f != "All":
    d = d[d["cap_tier"] == cap_f]
if fcf_only:
    d = d[d["fcf_positive"] == True]  # noqa: E712 — NaN → excluded, intended
# Fundamental thresholds: a NULL fundamental means "unknown", not "fails" — only
# drop a row when the value is present AND below the bar (keeps pre-report names).
if gm_min:
    d = d[d["gross_margin"].isna() | (d["gross_margin"] >= gm_min)]
if nm_min > -1000:
    d = d[d["net_margin"].isna() | (d["net_margin"] >= nm_min)]
if pe_max:
    d = d[d["pe_ratio"].isna() | (d["pe_ratio"] <= pe_max)]
if rg_min > -1000:
    d = d[d["revenue_growth_yoy"].isna() | (d["revenue_growth_yoy"] >= rg_min)]

st.caption(f"{len(d)} of {len(df)} names match")
st.dataframe(_shape(d), column_config=_TABLE_COLS, use_container_width=True,
             hide_index=True, height=560)

# Aggressive picks — top P(HR) small-cap tilt (matches the shortlist's kept
# small-cap tilt, project_binary_promoted_cone_gate). Tail-odds, not a forecast.
st.markdown("#### Aggressive picks — top P(HR), small-cap tilt")
agg = df[df["cap_tier"].isin(["small", "micro"]) & df["prob_home_run"].notna()]
agg = agg.sort_values("prob_home_run", ascending=False).head(15)
if agg.empty:
    st.caption("No scored small-cap names today.")
else:
    st.dataframe(_shape(agg), column_config=_TABLE_COLS, use_container_width=True,
                 hide_index=True, height=300)
