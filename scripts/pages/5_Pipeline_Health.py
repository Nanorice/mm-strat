"""Pipeline Health — ops view: runs heatmap, data freshness, universe trend,
audit history."""

from __future__ import annotations

import html as html_lib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dashboard_utils import (
    ASSET_PULL_DIAG,
    load_data_freshness,
    load_fundamentals_volume_by_quarter,
    load_latest_fundamentals_snapshot,
    load_null_filing_writes,
    load_pipeline_runs_window,
    load_t1_ingestion_failures,
    load_universe_trend,
)

AUDIT_DIR = ROOT / "data" / "audit_reports"
ARCH_DIR = ROOT / "docs" / "architecture"
DATA_FLOW_MMD = ARCH_DIR / "data_flow.mmd"
DATA_FLOW_LEGEND = ARCH_DIR / "data_flow_legend.md"

# Tab label -> .mmd source. Overview/pipeline/serving are the drill-down split;
# "Full" is the canonical all-in-one diagram (also referenced by manual_for_me.md).
DATA_FLOW_VIEWS = [
    ("Overview", ARCH_DIR / "data_flow_overview.mmd"),
    ("Pipeline", ARCH_DIR / "data_flow_pipeline.mmd"),
    ("Serving",  ARCH_DIR / "data_flow_serving.mmd"),
    ("Full",     DATA_FLOW_MMD),
]

STATUS_COLORS = {
    "failed":  "#c62828",  # red
    "warning": "#fdd835",  # yellow — phase succeeded but logged per-entity errors
    "running": "#42a5f5",  # blue — phase still in flight
    "success": "#2e7d32",  # green — clean success
}
# z values picked so colorscale stops below render cleanly; missing cells = NaN ("(no run)").
STATUS_NUMS = {"failed": 0.0, "warning": 0.34, "running": 0.67, "success": 1.0}

def _phase_sort_key(phase_name: str) -> tuple:
    """Natural execution order for a phase row, from the registry `order` field.

    Runs write stable registry ids ('t2_screener', 'scoring', …). Unknown keys
    (e.g. a pre-2026-06 snapshot's positional keys) sort last. Returns (order, name).
    """
    from src.orchestrators.phase_registry import order_for

    return (order_for(phase_name) or 999.0, phase_name)


FRESHNESS_TOLERANCE_DAYS = {
    # Phase 1 — daily ingestion
    "price_data":           2,
    "shares_history":       30,   # weekly-ish updates
    "macro_data":           8,    # long-format mix; WALCL/WTREGEN/WBAA are weekly (Thu/Fri release)
    "t1_macro":             2,
    "fundamentals":         95,   # quarterly
    "earnings_calendar":   -200,  # future-looking; allow negative lag
    # Phase 2-5 — daily features
    "screener_membership":  2,
    "t2_screener_features": 2,
    "t2_regime_scores":     3,
    "t2_risk_scores":       2,
    "sepa_watchlist":       2,
    "t3_sepa_features":     2,
    # Phase 6-7 — materialised
    "screener_watchlist":   2,
    "d2_training_cache":    7,    # refreshed at end of daily pipeline
    # ML registry — no SLA, large lags expected
    "models":               9999,
}


# ── Architecture diagram ─────────────────────────────────────────────────────

def _render_mermaid_file(path: Path) -> None:
    if not path.exists():
        st.warning(f"Diagram source not found at `{path.relative_to(ROOT)}`.")
        return
    try:
        mermaid_src = path.read_text(encoding="utf-8")
    except OSError as e:
        st.error(f"Could not read diagram: {e}")
        return

    # Hold the source in a hidden <pre> (escaped so it survives the HTML literal)
    # and render on demand. Mermaid's startOnLoad fires once at page load — but
    # in st.tabs the inactive tabs are display:none, which collapses the
    # component's iframe to zero width. Mermaid then measures a 0-width box and
    # throws a misleading "Syntax error in text" bomb. We defer mermaid.render()
    # until the iframe actually has width (its tab is shown). A display:none
    # ancestor in the PARENT collapses the iframe, so body.offsetWidth==0 is the
    # reliable "hidden" signal inside the iframe; a ResizeObserver fires when the
    # tab is opened and width becomes nonzero.
    escaped = html_lib.escape(mermaid_src)
    page = f"""
    <pre id="src" style="display:none">{escaped}</pre>
    <div id="out"></div>
    <script type="module">
      import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
      mermaid.initialize({{ startOnLoad: false, theme: 'default', securityLevel: 'loose' }});
      const src = document.getElementById('src').textContent;
      const out = document.getElementById('out');
      let drawn = false;
      async function draw() {{
        if (drawn || document.body.offsetWidth === 0) return;   // skip while hidden
        drawn = true;
        try {{
          const {{ svg }} = await mermaid.render('g' + Date.now(), src);
          out.innerHTML = svg;
        }} catch (e) {{
          out.innerHTML = '<pre style="color:#c62828">' + e.message + '</pre>';
          drawn = false;
        }}
      }}
      new ResizeObserver(draw).observe(document.body);
      draw();  // active tab: already has width
    </script>
    """
    components.html(page, height=900, scrolling=True)


def render_data_flow_diagram() -> None:
    st.subheader("Data Flow")
    st.caption(
        f"Sources in `{ARCH_DIR.relative_to(ROOT)}/`. **Full** is the canonical "
        "all-in-one diagram (also referenced by `docs/manual_for_me.md`); the other "
        "tabs are drill-down splits. Edit the `.mmd` files to update."
    )

    tabs = st.tabs([label for label, _ in DATA_FLOW_VIEWS])
    for tab, (_, path) in zip(tabs, DATA_FLOW_VIEWS):
        with tab:
            _render_mermaid_file(path)

    if DATA_FLOW_LEGEND.exists():
        with st.expander("Legend — node ↦ implementing module", expanded=False):
            try:
                st.markdown(DATA_FLOW_LEGEND.read_text(encoding="utf-8"))
            except OSError as e:
                st.error(f"Could not read legend: {e}")


# ── Heatmap ──────────────────────────────────────────────────────────────────

def render_runs_heatmap(runs: pd.DataFrame) -> None:
    st.subheader("Pipeline Runs (last 30d)")
    st.caption(
        "🟢 success · 🟡 success with per-entity warnings (e.g. T1 ticker errors) · "
        "🔵 still running · 🔴 failed phase · ⬜ no run that day"
    )

    if runs.empty:
        st.info("No pipeline runs in the last 30 days.")
        return

    r = runs.copy()
    r["target_date"] = pd.to_datetime(r["target_date"]).dt.date
    if "n_errors" not in r.columns:
        r["n_errors"] = 0
    r["n_errors"] = r["n_errors"].fillna(0).astype(int)

    # Most recent run per (date, phase) — older retries are superseded.
    r = (r.sort_values("started_at")
          .drop_duplicates(subset=["target_date", "phase_name"], keep="last"))

    # Promote success-with-errors to "warning" so the heatmap surfaces it.
    r["display_status"] = r["status"].where(
        ~((r["status"] == "success") & (r["n_errors"] > 0)),
        "warning",
    )

    pivot_status = r.pivot(index="phase_name", columns="target_date", values="display_status")
    pivot_runtime = r.pivot(index="phase_name", columns="target_date", values="runtime_seconds")
    pivot_errors = r.pivot(index="phase_name", columns="target_date", values="n_errors")

    # Continuous date axis: fill missing days with NaN so cells are evenly spaced
    # (fixes the "uneven bar widths" — was caused by Plotly's categorical x-axis
    # only including dates that had runs).
    min_d, max_d = pivot_status.columns.min(), pivot_status.columns.max()
    full_dates = pd.date_range(min_d, max_d, freq="D").date
    # Natural phase order (phase_1 → phase_10). With yaxis reversed below, the
    # first row renders at the TOP, so phase_1 lands on top as expected.
    phase_order = sorted(pivot_status.index, key=_phase_sort_key)
    pivot_status = pivot_status.reindex(columns=full_dates).reindex(index=phase_order)
    pivot_runtime = pivot_runtime.reindex(columns=full_dates).reindex(index=phase_order)
    pivot_errors = pivot_errors.reindex(columns=full_dates).reindex(index=phase_order)

    z = pivot_status.map(lambda s: STATUS_NUMS.get(s, np.nan)).astype(float).values

    # Discrete colorscale: each status owns a band so 0.34/0.67/1.0 render cleanly.
    colorscale = [
        [0.00, STATUS_COLORS["failed"]],
        [0.25, STATUS_COLORS["failed"]],
        [0.25, STATUS_COLORS["warning"]],
        [0.50, STATUS_COLORS["warning"]],
        [0.50, STATUS_COLORS["running"]],
        [0.84, STATUS_COLORS["running"]],
        [0.84, STATUS_COLORS["success"]],
        [1.00, STATUS_COLORS["success"]],
    ]

    hover_text = []
    for i, phase in enumerate(pivot_status.index):
        row = []
        for j, date in enumerate(pivot_status.columns):
            status = pivot_status.iloc[i, j]
            runtime = pivot_runtime.iloc[i, j]
            n_err = pivot_errors.iloc[i, j]
            if pd.isna(status):
                row.append(f"{phase}<br>{date}<br>(no run)")
            else:
                rt = f"{runtime:.0f}s" if pd.notna(runtime) else "—"
                err_str = f" · {int(n_err)} entity error(s)" if pd.notna(n_err) and n_err > 0 else ""
                row.append(f"{phase}<br>{date}<br>{status} · {rt}{err_str}")
        hover_text.append(row)

    fig = go.Figure(go.Heatmap(
        z=z,
        x=[str(d) for d in pivot_status.columns],
        y=list(pivot_status.index),
        colorscale=colorscale, zmin=0, zmax=1,
        showscale=False,
        hovertemplate="%{customdata}<extra></extra>",
        customdata=hover_text,
        xgap=1, ygap=1,
    ))
    fig.update_layout(
        height=max(280, 24 * len(pivot_status.index) + 80),
        margin=dict(l=30, r=20, t=30, b=80),
        yaxis_autorange="reversed",
        # Date-like strings get auto-parsed as a DATE axis; with a single run day
        # that becomes a sub-second range (23:59:59.9996 … ). These are one cell
        # per day — categorical is what a heatmap column actually is.
        xaxis=dict(type="category", tickangle=-45),
    )
    st.plotly_chart(fig, width='stretch')

    # Drill-downs: failed phases, then success-with-warnings.
    failed = r[r["status"] == "failed"]
    if not failed.empty:
        with st.expander(f"🔴 {len(failed)} failed run(s) — details", expanded=False):
            show = failed[["target_date", "phase_name", "started_at",
                           "runtime_seconds", "error_message"]].copy()
            st.dataframe(show, width='stretch', hide_index=True)

    warned = r[r["display_status"] == "warning"]
    if not warned.empty:
        with st.expander(
            f"🟡 {len(warned)} phase-run(s) succeeded with logged entity errors — "
            "see T1 Ingestion Failures section below for the per-ticker breakdown",
            expanded=False,
        ):
            show = warned[["target_date", "phase_name", "n_errors",
                           "runtime_seconds", "started_at"]].copy()
            show = show.rename(columns={"n_errors": "Entity Errors"})
            st.dataframe(show, width='stretch', hide_index=True)


# ── Data freshness ───────────────────────────────────────────────────────────

def render_freshness(fresh: pd.DataFrame) -> None:
    st.subheader("Data Freshness")
    st.caption(
        "`fresh` means lag ≤ the table's tolerance, not lag = 0. Tolerances vary "
        "by cadence: `fundamentals` = 95d (quarterly filings, so 14-day lag is "
        "normal/fresh), `earnings_calendar` is negative (future-looking — max "
        "date is ahead of today, so a −95 lag is expected). 🟡 stale = up to 2× "
        "tolerance, 🔴 very stale beyond that."
    )
    if fresh.empty:
        st.info("No tables registered.")
        return

    def tol_for(table):
        return FRESHNESS_TOLERANCE_DAYS.get(table, 7)

    def status_icon(row):
        if row["max_date"] is None or pd.isna(row["lag_days"]):
            return "⚪ no data"
        tol = tol_for(row["table"])
        # Negative tolerance = future-looking table: fresh while max_date is ahead.
        if tol < 0:
            return "🟢 fresh" if row["lag_days"] <= abs(tol) else "🔴 very stale"
        if row["lag_days"] <= tol:
            return "🟢 fresh"
        if row["lag_days"] <= tol * 2:
            return "🟡 stale"
        return "🔴 very stale"

    f = fresh.copy()
    f["status"] = f.apply(status_icon, axis=1)
    f["tolerance"] = f["table"].apply(tol_for)
    f = f.rename(columns={
        "table": "Table", "max_date": "Max Date",
        "rows": "Rows", "lag_days": "Lag (days)",
        "tolerance": "Tolerance (days)", "status": "Status",
    })
    f = f[["Table", "Max Date", "Rows", "Lag (days)", "Tolerance (days)", "Status"]]
    styled = f.style
    styled = styled.format("{:,.0f}", subset=["Rows"], na_rep="—")
    styled = styled.format("{:.0f}", subset=["Lag (days)", "Tolerance (days)"], na_rep="—")
    st.dataframe(styled, width='stretch', hide_index=True, height=380)


# ── T1 ingestion failures ────────────────────────────────────────────────────

def render_t1_failures() -> None:
    st.subheader("T1 Ingestion Failures (last 30d)")
    st.caption(
        "One row per (ticker, phase, error_type). `days_failing` is the count "
        "of distinct `target_date`s in the last 30 days where this ticker "
        "errored — chronic offenders (high days_failing) are pruning candidates."
    )

    fails = load_t1_ingestion_failures(days=30)
    if fails.empty:
        st.success("No T1 ingestion failures in the last 30 days.")
        return

    # Headline: how many chronic offenders (>=10 days failing)?
    chronic = fails[fails["days_failing"] >= 10]
    if not chronic.empty:
        st.warning(
            f"⚠️ {len(chronic)} ticker(s) with ≥10 days of failures — review for "
            "deactivation via `python tools/deactivate_tickers.py <TICKERS> --execute`."
        )

    # Ticker → Finviz link via LinkColumn (mirror watchlist pattern); the
    # display_text regex strips the URL back to the bare ticker.
    fails = fails.copy()
    fails["ticker"] = fails["ticker"].apply(
        lambda t: f"https://finviz.com/quote.ashx?t={t}" if pd.notna(t) else None
    )

    rename = {
        "ticker": "Ticker", "phase": "Phase", "error_type": "Error",
        "days_failing": "Days Failing",
        "first_failure_date": "First", "last_failure_date": "Last",
        "sample_detail": "Sample Detail",
    }
    show = fails.rename(columns=rename)
    st.dataframe(
        show, width='stretch', hide_index=True, height=380,
        column_config={
            "Ticker": st.column_config.LinkColumn(
                "Ticker", display_text=r"finviz\.com/quote\.ashx\?t=(.+)$"
            ),
        },
    )
    st.caption(f"Total: {len(fails)} (ticker, phase, error_type) tuples.")


# ── Fundamentals updates audit ───────────────────────────────────────────────

def render_fundamentals_audit() -> None:
    st.subheader("Fundamentals Updates Audit")
    st.caption(
        "Most-recently-updated fundamentals rows (sanity check the ingestor is "
        "actually writing) + quarterly fetch volume (spot coverage drops)."
    )

    # ── Latest snapshot ──
    snap = load_latest_fundamentals_snapshot(n=10)
    if snap.empty:
        st.info("No fundamentals rows with `updated_at` set.")
    else:
        last_update = snap["updated_at"].iloc[0]
        st.markdown(f"**Last `updated_at`:** `{last_update}`")
        show = snap.rename(columns={
            "ticker": "Ticker", "period_end": "Period",
            "filing_date": "Filed", "updated_at": "Updated",
            "source": "Source", "total_revenue": "Revenue",
            "net_income": "Net Income", "basic_eps": "Basic EPS",
            "free_cash_flow": "FCF",
        })
        styled = show.style
        for c in ["Revenue", "Net Income", "FCF"]:
            if c in show.columns:
                styled = styled.format("{:,.0f}", subset=[c], na_rep="—")
        if "Basic EPS" in show.columns:
            styled = styled.format("{:.2f}", subset=["Basic EPS"], na_rep="—")
        st.dataframe(styled, width='stretch', hide_index=True, height=320)

    # ── NULL filing_date written (per-run DQ) ──
    nfw = load_null_filing_writes(days=30)
    if not nfw.empty:
        latest = nfw.iloc[0]
        st.metric(
            "NULL filing_date written (last run)",
            int(latest["null_filing_written"]),
            help="Tickers whose fundamentals wrote OK but with no filing_date "
                 "(yfinance earnings fetch failed → no point-in-time anchor). "
                 "Not errors — the EDGAR backfill repairs these on a later run. "
                 "A rising trend means the earnings endpoint is degrading.",
        )
        if (nfw["null_filing_written"] > 0).any():
            st.caption(
                f"30-day trend: "
                + ", ".join(
                    f"{pd.to_datetime(r.target_date).date()}={int(r.null_filing_written)}"
                    for r in nfw.head(8).itertuples()
                )
            )

    # ── Quarterly fetch volume chart ──
    st.markdown("**Rows fetched per quarter** (period_end basis, non-null revenue)")
    vol = load_fundamentals_volume_by_quarter(start_year=2020)
    if vol.empty:
        st.info("No fundamentals data.")
        return

    fig = go.Figure()
    fig.add_bar(
        x=vol["quarter_label"], y=vol["rows_fetched"],
        marker_color="#42a5f5", name="rows",
        text=vol["rows_fetched"], textposition="outside",
    )
    fig.update_layout(
        height=320, margin=dict(l=40, r=20, t=20, b=60),
        xaxis_tickangle=-45, yaxis_title="Rows", xaxis_title="",
        showlegend=False,
    )
    st.plotly_chart(fig, width='stretch')
    st.caption(
        "Mid-quarter dips (latest bar) are expected — companies report on rolling "
        "schedules. Look for prior-quarter drops vs the trailing baseline."
    )


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
    st.plotly_chart(fig, width='stretch')


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
        # Shape written by tools/run_all_audits.py build_report():
        # summary.total = {"FAIL": n, "WARNING": n, "OK": n, "INFO": n}
        total = (d.get("summary") or {}).get("total") or {}
        rows.append({
            "date": date,
            "pass": total.get("OK", 0),
            "warn": total.get("WARNING", 0),
            "fail": total.get("FAIL", 0),
            "info": total.get("INFO", 0),
            "overall": d.get("overall", ""),
            "file": f.name,
        })
    return pd.DataFrame(rows)


def load_latest_audit() -> dict:
    """Newest audit report, whole envelope (per_audit / results / new_fails)."""
    if not AUDIT_DIR.exists():
        return {}
    files = sorted(AUDIT_DIR.glob("audit_report_*.json"))
    for f in reversed(files):
        try:
            return json.loads(f.read_text(encoding="utf-8")) | {"_file": f.name}
        except (OSError, ValueError):
            continue
    return {}


def render_data_quality() -> None:
    """Today's DQ detail: per-audit breakdown + the checks that actually failed.

    Reads the same nightly JSON as the history chart — `per_audit`, `results` and
    `new_fails` are written by run_all_audits.py and were previously unread.
    """
    st.subheader("Data Quality")
    rep = load_latest_audit()
    if not rep:
        st.info("No audit reports in `data/audit_reports/` yet.")
        return

    overall = rep.get("overall", "")
    total = (rep.get("summary") or {}).get("total") or {}
    badge = {"FAIL": "🛑", "WARNING": "⚠️", "OK": "✅"}.get(overall, "")
    st.caption(f"{badge} **{overall}** — from `{rep.get('_file','')}` (run {rep.get('run_at','')})")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("FAIL", total.get("FAIL", 0))
    c2.metric("WARNING", total.get("WARNING", 0))
    c3.metric("OK", total.get("OK", 0))
    c4.metric("INFO", total.get("INFO", 0))

    per_audit = (rep.get("summary") or {}).get("per_audit") or {}
    if per_audit:
        pa = pd.DataFrame(per_audit).T.reindex(columns=["FAIL", "WARNING", "OK", "INFO"]).fillna(0)
        pa.index.name = "audit"
        st.dataframe(pa.astype(int).reset_index(), width='stretch', hide_index=True)

    # New fails = a regression vs the previous run. The signal worth paging on.
    new_fails = rep.get("new_fails") or []
    if new_fails:
        st.error(f"🛑 {len(new_fails)} NEW failure(s) vs the previous run")
        st.dataframe(pd.DataFrame(new_fails), width='stretch', hide_index=True)

    results = rep.get("results") or []
    bad = [r for r in results if r.get("status") in ("FAIL", "WARNING")]
    if not bad:
        st.success("No failing or warning checks.")
        return
    df = pd.DataFrame(bad)
    keep = [c for c in ["status", "audit", "section", "check", "value", "detail"] if c in df.columns]
    with st.expander(f"Failing / warning checks ({len(bad)})", expanded=bool(new_fails)):
        st.dataframe(df[keep], width='stretch', hide_index=True)


def render_audit_history() -> None:
    st.subheader("Audit History")
    st.caption(
        "Daily pipeline Phase 8 invokes `tools/run_all_audits.py` and writes a "
        "JSON to `data/audit_reports/audit_report_YYYYMMDD.json`. Each line below "
        "is one daily report; history accumulates one row per successful daily run."
    )
    audit = load_audit_history()
    if audit.empty:
        st.info("No audit reports in `data/audit_reports/` yet. "
                "History will populate once the daily pipeline starts writing audit JSONs.")
        return

    if len(audit) == 1:
        st.warning("⚠️ Only 1 audit report on disk — line chart shows a single point. "
                   "More will accumulate as the daily pipeline runs.")

    # Stacked area: the top edge is total checks run, and a widening yellow/red
    # band is the signal. fail is drawn FIRST so it sits at the baseline where a
    # few rows stay visible — stacked above ~225 passes it would be unreadable.
    fig = go.Figure()
    for col, color in [("fail", "#c62828"), ("warn", "#fdd835"), ("pass", "#2e7d32")]:
        fig.add_scatter(x=audit["date"], y=audit[col], name=col, mode="lines",
                        stackgroup="checks", line=dict(width=0.5, color=color),
                        fillcolor=color,
                        hovertemplate=f"%{{x}}<br>{col}: %{{y}}<extra></extra>")
    fig.update_layout(
        height=280, margin=dict(l=40, r=20, t=20, b=30),
        yaxis_title="Checks (stacked)",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, width='stretch')

    with st.expander("Raw audit files", expanded=False):
        st.dataframe(audit, width='stretch', hide_index=True)


# ── Storage ──────────────────────────────────────────────────────────────────

def render_storage() -> None:
    st.subheader("Storage")

    items = [
        ("market_data.duckdb (full)",  ROOT / "data" / "market_data.duckdb"),
        ("dashboard.duckdb (slim)",    ROOT / "data" / "dashboard.duckdb"),
        ("models/",                    ROOT / "models"),
        ("model_cards/",               ROOT / "model_cards"),
        ("data/backtest/",             ROOT / "data" / "backtest"),
        ("data/audit_reports/",        ROOT / "data" / "audit_reports"),
        ("logs/drift/ (quarterly)",    ROOT / "logs" / "drift"),
        ("docs/reports/",              ROOT / "docs" / "reports"),
        ("logs/",                      ROOT / "logs"),
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
    st.dataframe(df[["path", "size"]], width='stretch', hide_index=True)


# ── Page entrypoint ──────────────────────────────────────────────────────────

def render_asset_pull_diag() -> None:
    """Surface the R2 asset-pull outcome (cloud only). The pull is best-effort
    and was previously silent, so a cloud-side failure left model cards/artifacts
    absent with no trace. ASSET_PULL_DIAG is empty on local runs → render nothing.
    """
    if not ASSET_PULL_DIAG:
        return
    err = any(r["error"] for r in ASSET_PULL_DIAG)
    label = "🔧 R2 asset pull — diagnostics" + ("  ⚠️ errors" if err else "")
    with st.expander(label, expanded=err):
        df = pd.DataFrame(ASSET_PULL_DIAG)[
            ["prefix", "pulled", "skipped", "exists", "error"]
        ]
        st.dataframe(df, width='stretch', hide_index=True)
        st.caption(
            "pulled = files fetched this boot · skipped = sentinel <23h (no pull) · "
            "exists = dir present after · error = swallowed exception (still non-fatal). "
            "All zeros + no error usually means the sentinel skipped a stale pull."
        )


st.title("Pipeline Health")
st.caption("Daily ops dashboard — spot drift, freshness issues, and audit "
           "regressions before they propagate.")

render_asset_pull_diag()
render_data_flow_diagram()
st.markdown("---")
render_runs_heatmap(load_pipeline_runs_window(days=30))
st.markdown("---")
render_freshness(load_data_freshness())
st.markdown("---")
render_t1_failures()
st.markdown("---")
render_fundamentals_audit()
st.markdown("---")
render_universe_trend(load_universe_trend(days=60))
st.markdown("---")
render_data_quality()
st.markdown("---")
render_audit_history()
st.markdown("---")
render_storage()
