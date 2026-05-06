"""Streamlit dashboard — Phase 1: Screener Watchlist + M01 + M03 Regime."""

import sys
from pathlib import Path
import json

import duckdb
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import xgboost as xgb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "data" / "market_data.duckdb"
MODEL_DIR = ROOT / "models" / "m01_baseline"
MODEL_PATH = MODEL_DIR / "model.json"
META_PATH = MODEL_DIR / "metadata.json"

CLASS_LABELS = ["Noise (0-2%)", "Moderate (2-10%)", "Strong (10-30%)", "Home Run (>30%)"]
CLASS_COLORS = ["#9e9e9e", "#42a5f5", "#66bb6a", "#ffa726"]

REGIME_THRESHOLDS = {
    "Strong Bull": (80, 100, "#2e7d32"),
    "Bull": (60, 80, "#66bb6a"),
    "Neutral": (40, 60, "#fdd835"),
    "Bear": (20, 40, "#ef5350"),
    "Strong Bear": (0, 20, "#b71c1c"),
}

PILLAR_FORMULAS = {
    "Trend (40%)": "50 + 50 x tanh(pct_above_sma200 x 10)  —  SPY vs 200d SMA",
    "Liquidity (30%)": "50 + 50 x tanh(slope_pct x 50)  —  20d slope of Fed Net Liquidity (WALCL - WTREGEN - RRPONTSYD)",
    "Risk Appetite (30%)": "VIX component (0-50) + HY Credit Spread component (0-50)",
}

# ── Data loading ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_regime() -> pd.Series | None:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        row = con.execute("""
            SELECT date, m03_score, m03_pillar_trend, m03_pillar_liq, m03_pillar_risk,
                   m03_delta_5d, m03_delta_20d
            FROM t2_regime_scores
            ORDER BY date DESC LIMIT 1
        """).fetchdf()
        return row.iloc[0] if not row.empty else None
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_watchlist() -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute("""
            SELECT ticker, company_name, sector, industry, market_cap,
                   entry_date, entry_price, exit_date, status,
                   close_price, price_date, pct_return, days_held, refreshed_at
            FROM screener_watchlist
            ORDER BY entry_date DESC, ticker
        """).fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_deployment_features() -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute("SELECT * FROM v_d3_deployment").fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_pipeline_status() -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute("""
            SELECT target_date, phase_name, status, runtime_seconds,
                   started_at, completed_at
            FROM pipeline_runs
            ORDER BY started_at DESC
            LIMIT 20
        """).fetchdf()
    finally:
        con.close()


@st.cache_resource
def load_model() -> tuple[xgb.XGBClassifier, list[str]]:
    meta = json.loads(META_PATH.read_text())
    features = meta["valid_features"]
    model = xgb.XGBClassifier()
    model.load_model(str(MODEL_PATH))
    return model, features


def classify_regime(score: float) -> tuple[str, str]:
    for label, (lo, hi, color) in REGIME_THRESHOLDS.items():
        if lo <= score < hi or (label == "Strong Bull" and score >= hi):
            return label, color
    return "Unknown", "#757575"


# ── M01 scoring ──────────────────────────────────────────────────────────────

def score_active_trades(
    watchlist: pd.DataFrame, deployment: pd.DataFrame
) -> pd.DataFrame:
    model, features = load_model()
    active = watchlist[watchlist["status"] == "ACTIVE"].copy()
    if active.empty:
        return active

    # For each active trade, get the latest deployment features by ticker + entry_date
    # A trade is identified by (ticker, entry_date); we want features from the most
    # recent date in v_d3_deployment for that ticker.
    latest_features = (
        deployment
        .sort_values("date")
        .groupby("ticker")
        .last()
        .reset_index()
    )

    merged = active.merge(latest_features, on="ticker", how="left", suffixes=("", "_feat"))

    # Lowercase column mapping — DuckDB returns lowercase but model may expect mixed case
    col_map = {c.lower(): c for c in merged.columns}
    available = []
    for f in features:
        col = col_map.get(f.lower())
        if col and col in merged.columns:
            available.append((f, col))

    if not available:
        return active

    X = merged[[col for _, col in available]].copy()
    X.columns = [f for f, _ in available]

    # Fill missing features with NaN (XGBoost handles natively)
    for f in features:
        if f not in X.columns:
            X[f] = np.nan
    X = X[features]

    # pandas merge can upcast bool columns to object — cast back to int
    for col in X.select_dtypes(include="object").columns:
        X[col] = X[col].astype(float)

    probas = model.predict_proba(X)
    preds = np.argmax(probas, axis=1)

    active = active.copy()
    active["m01_class"] = [CLASS_LABELS[p] for p in preds]
    active["m01_class_id"] = preds
    for i, label in enumerate(CLASS_LABELS):
        active[f"p_{label}"] = probas[:, i]

    return active


# ── Rendering ─────────────────────────────────────────────────────────────────

def render_regime_header(regime: pd.Series | None) -> None:
    st.subheader("M03 Market Regime")
    if regime is None:
        st.warning("No M03 regime data found in t2_regime_scores.")
        return

    score = regime["m03_score"]
    label, color = classify_regime(score)

    st.markdown(
        f"<span style='font-size:1.4em;font-weight:bold;color:{color}'>{label}</span>"
        f" &nbsp; Score: **{score:.1f}** &nbsp; "
        f"<span style='font-size:0.85em;color:#888'>"
        f"{regime['m03_delta_5d']:+.1f} (5d) · as of {regime['date']}</span>",
        unsafe_allow_html=True,
    )

    p1, p2, p3 = st.columns(3)
    for col, pillar_name, value, formula_key in [
        (p1, "Trend", regime["m03_pillar_trend"], "Trend (40%)"),
        (p2, "Liquidity", regime["m03_pillar_liq"], "Liquidity (30%)"),
        (p3, "Risk Appetite", regime["m03_pillar_risk"], "Risk Appetite (30%)"),
    ]:
        with col:
            st.metric(pillar_name, f"{value:.1f}")
            st.caption(f"*{PILLAR_FORMULAS[formula_key]}*")


def render_signal_summary(scored: pd.DataFrame) -> None:
    if scored.empty:
        st.info("No active trades to score.")
        return

    st.subheader("M01 Signal Summary")
    total = len(scored)
    high_conviction = scored["m01_class_id"].isin([2, 3]).sum()

    c1, c2, c3 = st.columns(3)
    c1.metric("Active Trades Scored", total)
    c2.metric("High Conviction (Strong + HR)", high_conviction)
    c3.metric("Conviction Rate", f"{high_conviction / total * 100:.0f}%" if total else "N/A")

    fig = px.histogram(
        scored, x="m01_class", color="m01_class",
        color_discrete_map={l: c for l, c in zip(CLASS_LABELS, CLASS_COLORS)},
        category_orders={"m01_class": CLASS_LABELS},
        title="M01 Class Distribution (Active Trades)",
    )
    fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="Count", height=300)
    st.plotly_chart(fig, use_container_width=True)


def render_watchlist_table(scored: pd.DataFrame, watchlist: pd.DataFrame) -> None:
    st.subheader("Screener Watchlist")

    # Filters
    fc1, fc2, fc3, fc4 = st.columns([1, 1, 1, 1])
    with fc1:
        ticker_search = st.text_input(
            "Search Ticker", "", placeholder="e.g. ROST",
            key="watchlist_ticker_search",
        ).strip().upper()
    with fc2:
        status_filter = st.selectbox("Status", ["ACTIVE", "EXITED", "All"], index=0)
    with fc3:
        sectors = ["All"] + sorted(watchlist["sector"].dropna().unique().tolist())
        sector_filter = st.selectbox("Sector", sectors)
    with fc4:
        date_range = st.date_input(
            "Entry Date Range",
            value=[],
            help="Leave blank to show all dates",
        )

    # Decide which dataframe to show
    if status_filter == "ACTIVE" and not scored.empty:
        display = scored.copy()
    elif status_filter == "EXITED":
        display = watchlist[watchlist["status"] == "EXITED"].copy()
    elif status_filter == "All":
        exited = watchlist[watchlist["status"] == "EXITED"].copy()
        display = pd.concat([scored, exited], ignore_index=True) if not scored.empty else exited
    else:
        display = scored.copy()

    if display.empty:
        st.info("No trades match filters.")
        return

    # Apply filters
    if ticker_search:
        display = display[display["ticker"].str.contains(ticker_search, case=False, na=False)]
    if sector_filter != "All":
        display = display[display["sector"] == sector_filter]
    if len(date_range) == 2:
        start, end = date_range
        mask = (display["entry_date"] >= pd.Timestamp(start)) & (display["entry_date"] <= pd.Timestamp(end))
        display = display[mask]

    # Format columns
    show_cols = [
        "ticker", "company_name", "sector", "entry_date", "entry_price",
        "close_price", "pct_return", "days_held", "status",
    ]
    proba_cols = [f"p_{l}" for l in CLASS_LABELS]
    if "m01_class" in display.columns:
        show_cols.insert(-1, "m01_class")
        show_cols.extend(proba_cols)

    available_cols = [c for c in show_cols if c in display.columns]
    table = display[available_cols].copy()

    # Rename for display
    rename = {
        "ticker": "Ticker", "company_name": "Company", "sector": "Sector",
        "entry_date": "Entry Date", "entry_price": "Entry $", "close_price": "Price $",
        "pct_return": "Return %", "days_held": "Days", "status": "Status",
        "m01_class": "M01 Class",
    }
    for l in CLASS_LABELS:
        rename[f"p_{l}"] = f"P({l.split(' ')[0]})"
    table = table.rename(columns={k: v for k, v in rename.items() if k in table.columns})

    # Styling
    def style_return(val):
        if pd.isna(val):
            return ""
        return f"color: {'#2e7d32' if val >= 0 else '#c62828'}"

    styled = table.style
    if "Return %" in table.columns:
        styled = styled.map(style_return, subset=["Return %"])
    for pcol in [f"P({l.split(' ')[0]})" for l in CLASS_LABELS]:
        if pcol in table.columns:
            styled = styled.format("{:.3f}", subset=[pcol])
    for dcol in ["Entry $", "Price $"]:
        if dcol in table.columns:
            styled = styled.format("${:.2f}", subset=[dcol])
    if "Return %" in table.columns:
        styled = styled.format("{:+.2f}%", subset=["Return %"])

    st.dataframe(styled, use_container_width=True, height=500)
    st.caption(f"Showing {len(table)} trades")


def render_analytics(scored: pd.DataFrame, watchlist: pd.DataFrame) -> None:
    st.subheader("Analytics")

    active = watchlist[watchlist["status"] == "ACTIVE"]
    exited = watchlist[watchlist["status"] == "EXITED"]

    # Quick stats
    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Active Trades", len(active))
    q2.metric(
        "Avg Return (Active)",
        f"{active['pct_return'].mean():+.1f}%" if not active.empty else "N/A",
    )
    win_rate = (exited["pct_return"] > 0).mean() * 100 if not exited.empty else 0
    q3.metric("Win Rate (Exited)", f"{win_rate:.0f}%")
    q4.metric(
        "Avg Holding Period",
        f"{active['days_held'].mean():.0f}d" if not active.empty else "N/A",
    )

    col_a, col_b = st.columns(2)

    # Trade age heatmap
    with col_a:
        if not active.empty:
            age_df = active[["ticker", "days_held", "pct_return"]].copy()
            age_df["risk"] = "Normal"
            age_df.loc[
                (age_df["days_held"] > 60) & (age_df["pct_return"] < 5), "risk"
            ] = "Aging"
            color_map = {"Normal": "#42a5f5", "Aging": "#ef5350"}
            fig = px.bar(
                age_df.sort_values("days_held", ascending=False),
                x="ticker", y="days_held", color="risk",
                color_discrete_map=color_map,
                title="Trade Age (>60d & <5% flagged)",
            )
            fig.update_layout(height=350, showlegend=True, xaxis_tickangle=-45)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No active trades.")

    # Sector concentration
    with col_b:
        if not active.empty:
            sector_counts = active["sector"].value_counts().reset_index()
            sector_counts.columns = ["sector", "count"]
            fig = px.bar(
                sector_counts, x="sector", y="count",
                title="Sector Concentration (Active)",
                color="count", color_continuous_scale="Blues",
            )
            fig.update_layout(height=350, xaxis_tickangle=-45, coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No active trades.")

    # Return distribution (exited trades)
    if not exited.empty:
        st.markdown("---")
        st.markdown("**Return Distribution (Exited Trades)**")
        returns = exited["pct_return"].dropna()
        # symlog: sign(x) * log10(1 + |x|) — handles negatives and zero
        log_returns = np.sign(returns) * np.log10(1 + returns.abs())
        plot_df = pd.DataFrame({"log_return": log_returns})
        fig = px.histogram(
            plot_df, x="log_return", nbins=50,
            title="Exited Trade Returns (symlog scale)",
            color_discrete_sequence=["#42a5f5"],
        )
        fig.add_vline(x=0, line_dash="dash", line_color="red")
        fig.update_layout(
            height=300,
            xaxis_title="Return % — sign(x) * log10(1+|x|)",
            yaxis_title="Count",
        )
        st.plotly_chart(fig, use_container_width=True)


def render_pipeline_status(pipeline: pd.DataFrame) -> None:
    if pipeline.empty:
        return
    latest = pipeline.iloc[0]
    status_icon = {"SUCCESS": "🟢", "FAILED": "🔴", "RUNNING": "🟡"}.get(latest["status"], "⚪")
    ts = latest["completed_at"] or latest["started_at"]
    st.caption(f"Pipeline: {status_icon} {latest['phase_name']} — {ts}")


# ── Page: Screener Watchlist ──────────────────────────────────────────────────

def page_screener_watchlist() -> None:
    st.title("Quantamental — Screener Watchlist")

    # Pipeline status
    pipeline = load_pipeline_status()
    render_pipeline_status(pipeline)

    st.markdown("---")

    # Load data
    watchlist = load_watchlist()
    deployment = load_deployment_features()

    # Score active trades
    scored = score_active_trades(watchlist, deployment)

    # M03 Regime + M01 Signal side-by-side
    regime = load_regime()
    col_regime, col_signals = st.columns(2)
    with col_regime:
        render_regime_header(regime)
    with col_signals:
        render_signal_summary(scored)

    st.markdown("---")

    # Watchlist table
    render_watchlist_table(scored, watchlist)

    st.markdown("---")

    # Analytics
    render_analytics(scored, watchlist)


# ── Entrypoint with navigation ───────────────────────────────────────────────

st.set_page_config(page_title="Quantamental Dashboard", layout="wide")

PAGES_DIR = Path(__file__).resolve().parent / "pages"

pg = st.navigation([
    st.Page(page_screener_watchlist, title="Screener Watchlist", icon="📋"),
    st.Page(str(PAGES_DIR / "1_Feature_Time_Series.py"), title="Feature Time Series", icon="📈"),
])
pg.run()
