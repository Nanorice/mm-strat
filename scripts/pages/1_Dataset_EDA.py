"""Dataset EDA — lists the latest pretrain audit reports in docs/reports/.

Reports are produced by `python scripts/run_pretrain_audit.py [--mode trades]
[--label-set NAME]`. This page sorts the HTML artefacts by mtime descending
and embeds the chosen one. Filenames follow the convention
`pretrain_audit_<mode>[_<label_set>]_<YYYYMMDD_HHMMSS>.html`.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

REPORTS_DIR = ROOT / "docs" / "reports"
FNAME_RE = re.compile(
    r"^pretrain_audit_(?P<mode>dense|trades)(?:_(?P<labelset>[A-Za-z0-9]+))?"
    r"_(?P<ts>\d{8}_\d{6})\.html$"
)


def _parse_report(p: Path) -> dict | None:
    m = FNAME_RE.match(p.name)
    if not m:
        return None
    try:
        ts = datetime.strptime(m.group("ts"), "%Y%m%d_%H%M%S")
    except ValueError:
        return None
    return {
        "path": p,
        "mode": m.group("mode"),
        "label_set": m.group("labelset") or "default",
        "ts": ts,
        "size_kb": p.stat().st_size / 1024,
    }


def _label(r: dict) -> str:
    return (
        f"{r['ts']:%Y-%m-%d %H:%M}  ·  mode={r['mode']}  ·  "
        f"label-set={r['label_set']}  ·  {r['size_kb']:.0f} KB"
    )


# ── Page ─────────────────────────────────────────────────────────────────────

st.title("Dataset EDA")
st.caption(
    "Pretrain audit reports — target distribution, class balance, "
    "feature/target relationships. Sorted by recency. Generate new ones with "
    "`python scripts/run_pretrain_audit.py --mode trades --label-set <name>`."
)

if not REPORTS_DIR.exists():
    st.warning(f"Reports directory not found: `{REPORTS_DIR.relative_to(ROOT)}`")
    st.stop()

reports = [
    r for r in (
        _parse_report(p) for p in REPORTS_DIR.glob("pretrain_audit_*.html")
    ) if r is not None
]
if not reports:
    st.info(
        "No pretrain audit reports in `docs/reports/`. "
        "Generate one with `python scripts/run_pretrain_audit.py --mode trades`."
    )
    st.stop()

reports.sort(key=lambda r: r["ts"], reverse=True)

# Optional filters keep the dropdown short when reports accumulate
modes = sorted({r["mode"] for r in reports})
label_sets = sorted({r["label_set"] for r in reports})

c1, c2 = st.columns(2)
with c1:
    mode_filter = st.selectbox("Mode", ["(all)"] + modes, index=0)
with c2:
    ls_filter = st.selectbox("Label set", ["(all)"] + label_sets, index=0)

filtered = [
    r for r in reports
    if (mode_filter == "(all)" or r["mode"] == mode_filter)
    and (ls_filter == "(all)" or r["label_set"] == ls_filter)
]

if not filtered:
    st.info("No reports match the selected filters.")
    st.stop()

selected_label = st.selectbox(
    "Report",
    [_label(r) for r in filtered],
    index=0,
    help="Most recent first.",
)
selected = filtered[[_label(r) for r in filtered].index(selected_label)]

st.caption(
    f"Source: `{selected['path'].relative_to(ROOT)}` · "
    f"Generated: {selected['ts']:%Y-%m-%d %H:%M:%S} · "
    f"Mode: **{selected['mode']}** · "
    f"Label set: **{selected['label_set']}**"
)
st.markdown("---")

try:
    content = selected["path"].read_text(encoding="utf-8")
    components.html(content, height=900, scrolling=True)
except OSError as e:
    st.error(f"Could not read pretrain audit HTML: {e}")
