"""Quantamental Dashboard — UPLIFT SHADOW entrypoint (sprint-14 dashboard uplift).

Separate app so the in-progress theta.md-style redesign never touches the live
`dashboard.py`. Develop here; when every uplift page is built, fold these pages
into dashboard.py's st.navigation and retire this file.

Run:  streamlit run scripts/dashboard_uplift.py
      (slim DB: set DASHBOARD_DB_PATH=data/dashboard.duckdb first)
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

PAGES_DIR = ROOT / "scripts" / "pages"

st.set_page_config(page_title="Dashboard Uplift", layout="wide")

pg = st.navigation([
    st.Page(str(PAGES_DIR / "2_Macro.py"), title="Macro", icon="🌐"),
])
pg.run()
