"""Equity Research — read surface for single-name markdown reports.

Per `equity_research_page.md`. One step in the knowledge-base pipeline:

    screening → shortlist → agentic markdown report → agentic digestion → knowledge base

This page is where a human reads step 3.

`research_reports` landed 2026-07-20 (`src/research_report_engine.py`), but the
empty states stay: the table is absent from any DB built before that, and
`_load_reports` still distinguishes "table missing" from "table empty".

No scoring, no NLP, no summary generation here — this page renders what the
agent wrote and nothing else.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dashboard_utils import (  # noqa: E402
    _connect, escape_markdown_dollars, fell_back_to_free_text,
    split_report_sections,
)

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

  /* Phone. Streamlit reflows its own layout; these are the things it can't know
     about — this page's typography and the report body's own content. */
  @media (max-width:640px){
    /* .18em tracking on an uppercase mono line eats ~40% of a 375px screen and
       wraps the title mid-phrase. */
    .er-title{letter-spacing:.08em;font-size:10px}
    .er-empty{padding:18px 14px;font-size:13px}
    /* Accession numbers (0000002488-26-000018) and ticker/URL runs are single
       unbreakable tokens — without this they push the whole column sideways and
       the page scrolls horizontally. */
    [data-testid="stExpander"] p, [data-testid="stExpander"] li{
      overflow-wrap:anywhere}
    /* A markdown table can't reflow; give it its own scroll rather than letting
       it widen the body. */
    [data-testid="stExpander"] table{display:block;overflow-x:auto;
      max-width:100%}
  }
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
            SELECT ticker, report_date, raw_md, key_facts_json
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

raw_md = row["raw_md"] or ""
sections = split_report_sections(raw_md)

if not sections:
    # Older or hand-written report with no agent headings — render it whole
    # rather than showing nothing.
    st.markdown("---")
    st.markdown(escape_markdown_dollars(raw_md) or
                "_Report row exists but `raw_md` is empty._")
    st.stop()

# Business analyst first: it carries the relations/evidence the knowledge base
# is built from, so it is what this page is usually opened for — and it is the
# one section worth opening by default.
names = list(sections)
if "Business Analyst" in names:
    names.insert(0, names.pop(names.index("Business Analyst")))

st.markdown("---")

# One collapsed expander per section, replacing a 13-option horizontal radio.
# The radio was a single tap on a desktop and an unreadable wrapped block on a
# phone; collapsed sections also give a scannable table of contents, which a
# 100 KB wall of prose otherwise doesn't have. All bodies are in the DOM either
# way, so this costs no extra query.
for name in names:
    with st.expander(name, expanded=(name == names[0])):
        if fell_back_to_free_text(row["key_facts_json"], name):
            st.warning(
                f"**This section is a free-text fallback, not the agent's typed "
                f"output.** {name}'s structured call failed on this run, so "
                f"`report.json` holds `null` and the prose below is whatever the "
                f"model emitted unconstrained — often a raw JSON dump. Nothing "
                f"downstream (relations, quote fidelity) can score it. "
                f"Re-run the name to replace it."
            )
        st.markdown(escape_markdown_dollars(sections[name]))
