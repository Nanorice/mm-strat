"""Pipeline Health — ops view: runs heatmap, data freshness, universe trend,
audit history."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dashboard_utils import (
    load_data_freshness,
    load_pipeline_runs_window,
    load_universe_trend,
)

AUDIT_DIR = ROOT / "data" / "audit_reports"

STATUS_COLORS = {
    "success": "#2e7d32",
    "running": "#fdd835",
    "failed":  "#c62828",
}
STATUS_NUMS = {"success": 1, "running": 0.5, "failed": 0}  # for heatmap z

FRESHNESS_TOLERANCE_DAYS = {
    "price_data":           2,
    "daily_features":       2,
    "t2_screener_features": 2,
    "t3_sepa_features":     2,
    "t2_regime_scores":     3,
    "t2_risk_scores":       2,
    "fundamentals":         95,   # quarterly
    "earnings_calendar":   -200,  # future-looking, allow negative lag
    "screener_watchlist":   2,
}


# ── Heatmap ──────────────────────────────────────────────────────────────────

def render_runs_heatmap(runs: pd.DataFrame) -> None:
    st.subheader("Pipeline Runs (last 30d)")

    if runs.empty:
        st.info("No pipeline runs in the last 30 days.")
        return

    r = runs.copy()
    r["target_date"] = pd.to_datetime(r["target_date"]).dt.date
    # Most recent status per (date, phase) — older retries get superseded
    r = (r.sort_values("started_at")
          .drop_duplicates(subset=["target_date", "phase_name"], keep="last"))

    pivot_status = r.pivot(index="phase_name", columns="target_date", values="status")
    pivot_runtime = r.pivot(index="phase_name", columns="target_date", values="runtime_seconds")

    # Sort phases by name (phase_1, phase_2, ...) — alpha-sort on the raw name
    # is good enough since they follow phase_N_ prefix.
    pivot_status = pivot_status.sort_index()
    pivot_runtime = pivot_runtime.reindex_like(pivot_status)

    z = pivot_status.map(lambda s: STATUS_NUMS.get(s, np.nan)).astype(float).values
    text = pivot_status.fillna("").values

    colorscale = [
        [0.0, STATUS_COLORS["failed"]],
        [0.5, STATUS_COLORS["running"]],
        [1.0, STATUS_COLORS["success"]],
    ]

    # hover with runtime
    hover_text = []
    for i, phase in enumerate(pivot_status.index):
        row = []
        for j, date in enumerate(pivot_status.columns):
            status = pivot_status.iloc[i, j]
            runtime = pivot_runtime.iloc[i, j]
            if pd.isna(status):
                row.append("(no run)")
            else:
                rt = f"{runtime:.0f}s" if pd.notna(runtime) else "—"
                row.append(f"{phase}<br>{date}<br>{status} · {rt}")
        hover_text.append(row)

    fig = go.Figure(go.Heatmap(
        z=z,
        x=[str(d) for d in pivot_status.columns],
        y=list(pivot_status.index),
        colorscale=colorscale, zmin=0, zmax=1,
        showscale=False,
        text=text, texttemplate="",
        hovertemplate="%{customdata}<extra></extra>",
        customdata=hover_text,
        xgap=1, ygap=1,
    ))
    fig.update_layout(
        height=max(280, 24 * len(pivot_status.index) + 80),
        margin=dict(l=30, r=20, t=30, b=80),
        xaxis_tickangle=-45,
        yaxis_autorange="reversed",
    )
    st.plotly_chart(fig, use_container_width=True)

    # Drill-down: failed runs in window
    failed = r[r["status"] == "failed"]
    if not failed.empty:
        with st.expander(f"⚠️ {len(failed)} failed run(s) — details", expanded=False):
            show = failed[["target_date", "phase_name", "started_at",
                           "runtime_seconds", "error_message"]].copy()
            st.dataframe(show, use_container_width=True, hide_index=True)


# ── Data freshness ───────────────────────────────────────────────────────────

def render_freshness(fresh: pd.DataFrame) -> None:
    st.subheader("Data Freshness")
    if fresh.empty:
        st.info("No tables registered.")
        return

    def status_icon(row):
        if row["max_date"] is None or pd.isna(row["lag_days"]):
            return "⚪ no data"
        tol = FRESHNESS_TOLERANCE_DAYS.get(row["table"], 7)
        if row["lag_days"] <= tol:
            return "🟢 fresh"
        if row["lag_days"] <= tol * 2:
            return "🟡 stale"
        return "🔴 very stale"

    f = fresh.copy()
    f["status"] = f.apply(status_icon, axis=1)
    f = f.rename(columns={
        "table": "Table", "max_date": "Max Date",
        "rows": "Rows", "lag_days": "Lag (days)", "status": "Status",
    })
    styled = f.style
    if "Rows" in f.columns:
        styled = styled.format("{:,.0f}", subset=["Rows"], na_rep="—")
    if "Lag (days)" in f.columns:
        styled = styled.format("{:.0f}", subset=["Lag (days)"], na_rep="—")
    st.dataframe(styled, use_container_width=True, hide_index=True, height=380)


# ── Universe / breakout trend ────────────────────────────────────────────────

def render_universe_trend(trend: pd.DataFrame) -> None:
    st.subheader("Universe & Breakout Trend (60d)")
    if trend.empty:
        st.info("No universe trend data.")
        return

    fig = go.Figure()
    fig.add_scatter(x=trend["date"], y=trend["trend_ok_n"], mode="lines",
                    name="trend_ok", line=dict(color="#42a5f5", width=2))
    fig.add_scatter(x=trend["date"], y=trend["breakout_n"], mode="lines",
                    name="breakout_ok", line=dict(color="#ffa726", width=2))
    fig.update_layout(
        height=320, margin=dict(l=40, r=20, t=20, b=30),
        yaxis_title="Count",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)


# ── Audit history ────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_audit_history() -> pd.DataFrame:
    if not AUDIT_DIR.exists():
        return pd.DataFrame()
    rows = []
    for f in sorted(AUDIT_DIR.glob("audit_report_*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        # Filename pattern: audit_report_YYYYMMDD.json
        stem = f.stem.replace("audit_report_", "")
        try:
            date = pd.to_datetime(stem, format="%Y%m%d").date()
        except ValueError:
            date = pd.to_datetime(f.stat().st_mtime, unit="s").date()
        summary = d.get("summary") or d.get("Summary") or {}
        rows.append({
            "date": date,
            "pass": summary.get("pass_count") or summary.get("passed", 0),
            "warn": summary.get("warn_count") or summary.get("warnings", 0),
            "fail": summary.get("fail_count") or summary.get("failed", 0),
            "file": f.name,
        })
    return pd.DataFrame(rows)


def render_audit_history() -> None:
    st.subheader("Audit History")
    audit = load_audit_history()
    if audit.empty:
        st.info("No audit reports in `data/audit_reports/` yet. "
                "History will populate once the daily pipeline starts writing audit JSONs.")
        return

    if len(audit) == 1:
        st.warning("⚠️ Only 1 audit report on disk — line chart shows a single point. "
                   "History will accumulate as the daily pipeline writes more.")

    fig = go.Figure()
    fig.add_scatter(x=audit["date"], y=audit["pass"], mode="lines+markers",
                    name="pass", line=dict(color="#2e7d32"))
    fig.add_scatter(x=audit["date"], y=audit["warn"], mode="lines+markers",
                    name="warn", line=dict(color="#fdd835"))
    fig.add_scatter(x=audit["date"], y=audit["fail"], mode="lines+markers",
                    name="fail", line=dict(color="#c62828"))
    fig.update_layout(
        height=280, margin=dict(l=40, r=20, t=20, b=30),
        yaxis_title="Count",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Raw audit files", expanded=False):
        st.dataframe(audit, use_container_width=True, hide_index=True)


# ── Storage ──────────────────────────────────────────────────────────────────

def render_storage() -> None:
    st.subheader("Storage")

    items = [
        ("market_data.duckdb", ROOT / "data" / "market_data.duckdb"),
        ("models/",            ROOT / "models"),
        ("data/backtest/",     ROOT / "data" / "backtest"),
        ("docs/reports/",      ROOT / "docs" / "reports"),
        ("logs/",              ROOT / "logs"),
    ]

    rows = []
    for label, path in items:
        if not path.exists():
            rows.append({"path": label, "size": "—", "note": "(missing)"})
            continue
        if path.is_file():
            size = path.stat().st_size
        else:
            size = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
        rows.append({
            "path": label,
            "size_mb": size / 1024 ** 2,
            "size": f"{size / 1024 ** 2:.1f} MB" if size < 1024 ** 3 else f"{size / 1024 ** 3:.2f} GB",
        })
    df = pd.DataFrame(rows)
    st.dataframe(df[["path", "size"]], use_container_width=True, hide_index=True)


# ── Page entrypoint ──────────────────────────────────────────────────────────

st.title("Pipeline Health")
st.caption("Daily ops dashboard — spot drift, freshness issues, and audit "
           "regressions before they propagate.")

render_runs_heatmap(load_pipeline_runs_window(days=30))
st.markdown("---")
render_freshness(load_data_freshness())
st.markdown("---")
render_universe_trend(load_universe_trend(days=60))
st.markdown("---")
render_audit_history()
st.markdown("---")
render_storage()
