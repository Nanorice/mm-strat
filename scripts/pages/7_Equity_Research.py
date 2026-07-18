"""Equity Research — read surface for single-name markdown reports (PLACEHOLDER).

Per `equity_research_page.md`. One step in the knowledge-base pipeline:

    screening → shortlist → agentic markdown report → agentic digestion → knowledge base

This page is where a human reads step 3.

⚠️ **`research_reports` DOES NOT EXIST YET.** It is a *contract*
(`research_layer_contract.md`), not a built table — verified against the live DB
2026-07-18: zero tables matching %research%/%report%. So this page ships as an
honest empty state and degrades the moment the table appears, without a rewrite:
`_load_reports` probes for the table and returns None when absent.

Placeholder means placeholder — no scoring, no NLP, no summary generation. An
honest empty state beats a fabricated report.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dashboard_utils import _connect  # noqa: E402

_CSS = """
<style>
  .er-wrap{font-family:"Source Serif 4",Georgia,serif;color:#1c1a17}
  .er-title{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:11px;
    letter-spacing:.18em;text-transform:uppercase;color:#8a8272;
    border-bottom:1px solid #e8e3d6;padding-bottom:8px;margin:2px 0 12px}
  .er-empty{border:1px dashed #d8d2c2;border-radius:6px;padding:28px 24px;
    background:#faf8f3;color:#6f6858;font-size:14px;line-height:1.6}
  .er-empty b{color:#1c1a17}
  .er-empty code{font-family:"JetBrains Mono",monospace;font-size:12px;
    background:#f0ece1;padding:1px 5px;border-radius:3px}
</style>
"""


def _html(markup: str) -> None:
    st.markdown("\n".join(l.lstrip() for l in markup.splitlines()),
                unsafe_allow_html=True)


@st.cache_data(ttl=300)
def _load_reports() -> pd.DataFrame | None:
    """Latest report per ticker, or None when `research_reports` doesn't exist.

    None (table absent) and an empty frame (table present, no rows) are different
    states and the page says so differently — collapsing them would hide whether
    the research layer is unbuilt or merely unpopulated.
    """
    con = _connect()
    try:
        exists = con.execute("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_name = 'research_reports'
        """).fetchone()[0]
        if not exists:
            return None
        return con.execute("""
            SELECT ticker, report_date, raw_md
            FROM research_reports
            QUALIFY row_number() OVER (PARTITION BY ticker ORDER BY report_date DESC) = 1
            ORDER BY ticker
        """).fetchdf()
    finally:
        con.close()


_html(_CSS + """
<div class="er-wrap">
  <div class="er-title">ER · Equity research — single-name reports</div>
</div>
""")
st.caption("Agentic markdown reports, one per name. Study material for a "
           "discretionary decision — entries and exits stay yours.")

reports = _load_reports()

if reports is None:
    _html("""
    <div class="er-empty">
      <b>The research layer isn't built yet.</b><br><br>
      This page reads <code>research_reports.raw_md</code>, specified in
      <code>research_layer_contract.md</code> as the source of truth for report
      markdown. That table does not exist in the database yet — so there is
      nothing to render, and nothing here is stale.<br><br>
      It fills in automatically once the table lands and an agentic pass writes
      reports into it. No change to this page required.
    </div>
    """)
    st.stop()

if reports.empty:
    _html("""
    <div class="er-empty">
      <b>No reports written yet.</b><br><br>
      <code>research_reports</code> exists but holds no rows — the table is built,
      the producing pipeline hasn't run (or hasn't covered a name yet).
    </div>
    """)
    st.stop()

tickers = reports["ticker"].tolist()
pick = st.selectbox(f"Ticker · {len(tickers)} with a report", tickers)
row = reports[reports["ticker"] == pick].iloc[0]
st.caption(f"**{pick}** · report date {str(row['report_date'])[:10]}")
st.markdown("---")
st.markdown(row["raw_md"] or "_Report row exists but `raw_md` is empty._")
