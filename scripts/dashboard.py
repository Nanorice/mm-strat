"""Quantamental Dashboard — entrypoint.

Page 1 (Today, this file) is the default landing. Pages 3/4/5 live under
scripts/pages/ and auto-mount via st.navigation. NEVER expose --server.address
0.0.0.0 — this is a localhost-only single-user UI with no auth.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dashboard_utils import (
    CLASS_COLORS,
    CLASS_LABELS,
    FACTOR_FRIENDLY,
    P_HR_COL,
    P_STRONG_COL,
    PILLAR_FORMULAS,
    VETO_THRESHOLD,
    classify_regime,
    exposure_band_label,
    load_deployment_features,
    load_pipeline_status,
    load_pre_breakout,
    load_regime,
    load_risk_5f,
    load_sector_heat,
    load_watchlist,
    score_features_df,
)


# ── M01 scoring on the active watchlist ──────────────────────────────────────

def score_active_trades(
    watchlist: pd.DataFrame, deployment: pd.DataFrame
) -> pd.DataFrame:
    active = watchlist[watchlist["status"] == "ACTIVE"].copy()
    if active.empty or deployment.empty:
        return active

    latest_features = (
        deployment.sort_values("date").groupby("ticker").last().reset_index()
    )
    merged = active.merge(latest_features, on="ticker", how="left", suffixes=("", "_feat"))
    return score_features_df(merged)


# ── Header components ────────────────────────────────────────────────────────

def render_pipeline_status(pipeline: pd.DataFrame) -> None:
    if pipeline.empty:
        return
    latest = pipeline.iloc[0]
    status_icon = {"SUCCESS": "🟢", "FAILED": "🔴", "RUNNING": "🟡"}.get(latest["status"], "⚪")
    ts = latest["completed_at"] or latest["started_at"]
    st.caption(f"Pipeline: {status_icon} {latest['phase_name']} — {ts}")


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


def render_risk_5f_header(risk: pd.Series | None) -> None:
    st.subheader("5-Factor Risk Regime")
    if risk is None:
        st.warning("No 5F data found in t2_risk_scores.")
        return

    target = float(risk["target_exposure"])
    band, color = exposure_band_label(target)
    pct = float(risk["rolling_percentile"]) if pd.notna(risk["rolling_percentile"]) else None
    veto = bool(risk["veto_flag"]) if pd.notna(risk["veto_flag"]) else False

    veto_tag = (
        " <span style='background:#b71c1c;color:#fff;padding:1px 7px;border-radius:6px;"
        "font-size:0.8em;'>VETO</span>" if veto else ""
    )
    st.markdown(
        f"<span style='font-size:1.4em;font-weight:bold;color:{color}'>{band}</span>"
        f" &nbsp; Exposure: **{target:.0%}**{veto_tag} &nbsp; "
        f"<span style='font-size:0.85em;color:#888'>"
        f"5y-pct: {pct:.0%} · as of {risk['date']}</span>"
        if pct is not None else
        f"<span style='font-size:1.4em;font-weight:bold;color:{color}'>{band}</span>"
        f" &nbsp; Exposure: **{target:.0%}**{veto_tag} &nbsp; "
        f"<span style='font-size:0.85em;color:#888'>as of {risk['date']}</span>",
        unsafe_allow_html=True,
    )

    # Worst factor — largest z-score (most stretched)
    z_cols = ["z_vix", "z_hy", "z_term", "z_trend", "z_slope"]
    zs = {c: float(risk[c]) for c in z_cols if pd.notna(risk[c])}
    if zs:
        worst_col = max(zs, key=lambda k: zs[k])
        worst_val = zs[worst_col]
        f_name = FACTOR_FRIENDLY[worst_col]
        worst_color = "#c62828" if worst_val >= VETO_THRESHOLD else (
            "#fb8c00" if worst_val >= 1.0 else "#2e7d32"
        )
        weighted_z = float(risk["weighted_z"]) if pd.notna(risk["weighted_z"]) else None
        c1, c2 = st.columns(2)
        with c1:
            st.metric("Worst Factor", f_name, f"{worst_val:+.2f}σ")
            st.caption(
                f"*Veto fires at |z| ≥ {VETO_THRESHOLD}σ (any single factor) → forces 15% exposure*"
            )
        with c2:
            if weighted_z is not None:
                st.metric("Weighted z", f"{weighted_z:+.2f}")
                st.caption("*Aggregate 5F stress; lower = riskier*")

        # Expander with all z-scores
        with st.expander("All factor z-scores", expanded=False):
            z_df = pd.DataFrame({
                "Factor": [FACTOR_FRIENDLY[c] for c in z_cols],
                "z-score": [zs.get(c, float("nan")) for c in z_cols],
            })
            st.dataframe(
                z_df.style.format({"z-score": "{:+.3f}"})
                          .background_gradient(subset=["z-score"], cmap="RdYlGn_r",
                                               vmin=-2, vmax=2),
                use_container_width=True, hide_index=True,
            )


# ── Active trades table ───────────────────────────────────────────────────────

def render_watchlist_table(scored: pd.DataFrame, watchlist: pd.DataFrame) -> None:
    st.subheader("Screener Watchlist")

    # Wrap filters in a form so the page only reruns on Apply / Enter — not on
    # every keystroke. The whole-page rerun (which includes live M01 scoring of
    # the pre-breakout cohort) is what made search feel laggy before.
    with st.form("watchlist_filters", border=False):
        fc1, fc2, fc3, fc4 = st.columns([1, 1, 1, 1])
        with fc1:
            ticker_search = st.text_input(
                "Search Ticker", "", placeholder="e.g. ROST (press Enter)",
                key="watchlist_ticker_search",
            ).strip().upper()
        with fc2:
            status_filter = st.selectbox("Status", ["ACTIVE", "EXITED", "All"], index=0)
        with fc3:
            sectors = ["All"] + sorted(watchlist["sector"].dropna().unique().tolist())
            sector_filter = st.selectbox("Sector", sectors)
        with fc4:
            date_range = st.date_input("Entry Date Range", value=[],
                                       help="Leave blank to show all dates")
        st.form_submit_button("Apply filters", type="primary")

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

    if ticker_search:
        display = display[display["ticker"].str.contains(ticker_search, case=False, na=False)]
    if sector_filter != "All":
        display = display[display["sector"] == sector_filter]
    if len(date_range) == 2:
        s, e = date_range
        m = ((display["entry_date"] >= pd.Timestamp(s))
             & (display["entry_date"] <= pd.Timestamp(e)))
        display = display[m]

    # Default sort: Entry Date desc — most-recent trades first. Other sorts
    # remain available and persist across reruns.
    sort_options = ["Entry Date ↓", "P(Home Run) ↓", "P(Strong+HR) ↓", "Return % ↓", "Days Held ↓"]
    sort_choice = st.session_state.get("watchlist_sort", sort_options[0])
    sort_choice = st.selectbox(
        "Sort by", sort_options,
        index=sort_options.index(sort_choice) if sort_choice in sort_options else 0,
        key="watchlist_sort",
    )

    if sort_choice == "P(Home Run) ↓" and P_HR_COL in display.columns:
        display = display.sort_values(P_HR_COL, ascending=False, na_position="last")
    elif sort_choice == "P(Strong+HR) ↓" and P_HR_COL in display.columns and P_STRONG_COL in display.columns:
        display = display.assign(_p_strong_hr=display[P_HR_COL] + display[P_STRONG_COL])
        display = display.sort_values("_p_strong_hr", ascending=False, na_position="last")
        display = display.drop(columns=["_p_strong_hr"])
    elif sort_choice == "Entry Date ↓":
        display = display.sort_values("entry_date", ascending=False)
    elif sort_choice == "Return % ↓":
        display = display.sort_values("pct_return", ascending=False, na_position="last")
    elif sort_choice == "Days Held ↓":
        display = display.sort_values("days_held", ascending=False, na_position="last")

    # Column order: probabilities BEFORE status (action-relevant first).
    proba_cols = [f"p_{l}" for l in CLASS_LABELS]
    show_cols = ["ticker", "company_name", "sector", "entry_date", "entry_price",
                 "close_price", "pct_return", "days_held"]
    if "m01_class" in display.columns:
        show_cols.append("m01_class")
        show_cols.extend(proba_cols)
    show_cols.append("status")

    available_cols = [c for c in show_cols if c in display.columns]
    table = display[available_cols].copy()

    rename = {
        "ticker": "Ticker", "company_name": "Company", "sector": "Sector",
        "entry_date": "Entry Date", "entry_price": "Entry $", "close_price": "Price $",
        "pct_return": "Return %", "days_held": "Days", "status": "Status",
        "m01_class": "M01 Class",
    }
    for l in CLASS_LABELS:
        rename[f"p_{l}"] = f"P({l.split(' ')[0]})"
    table = table.rename(columns={k: v for k, v in rename.items() if k in table.columns})

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
    st.caption(f"Showing {len(table)} trades · sorted by {sort_choice}")


# ── Pre-breakout watch table ──────────────────────────────────────────────────

def render_pre_breakout(pre: pd.DataFrame) -> None:
    st.subheader("Pre-Breakout Watch")
    st.caption("trend_ok = TRUE, breakout_ok = FALSE — names in setup, not yet triggered. "
               "Scored live by the prod M01 model.")

    if pre.empty:
        st.info("No pre-breakout candidates today.")
        return

    # Live scoring — small cohort (<= 100), acceptable in request path for MVP.
    # Mark as 'live' so the user knows this isn't snapshot-cached.
    scored = score_features_df(pre)

    if P_HR_COL in scored.columns:
        scored = scored.sort_values(P_HR_COL, ascending=False, na_position="last")

    show = ["ticker", "company_name", "sector", "close", "dist_from_20d_high",
            "vol_ratio_50", "vcp_ratio", "days_in_setup"]
    if "m01_class" in scored.columns:
        show.append("m01_class")
        show.extend([f"p_{l}" for l in CLASS_LABELS])

    available = [c for c in show if c in scored.columns]
    table = scored[available].copy()

    rename = {
        "ticker": "Ticker", "company_name": "Company", "sector": "Sector",
        "close": "Close $", "dist_from_20d_high": "Dist 20d-High %",
        "vol_ratio_50": "Vol Ratio", "vcp_ratio": "VCP",
        "days_in_setup": "Days in Setup", "m01_class": "M01 Class",
    }
    for l in CLASS_LABELS:
        rename[f"p_{l}"] = f"P({l.split(' ')[0]})"
    table = table.rename(columns={k: v for k, v in rename.items() if k in table.columns})

    styled = table.style
    for pcol in [f"P({l.split(' ')[0]})" for l in CLASS_LABELS]:
        if pcol in table.columns:
            styled = styled.format("{:.3f}", subset=[pcol])
    if "Close $" in table.columns:
        styled = styled.format("${:.2f}", subset=["Close $"])
    if "Dist 20d-High %" in table.columns:
        styled = styled.format("{:.1%}", subset=["Dist 20d-High %"])
    for fcol in ["Vol Ratio", "VCP"]:
        if fcol in table.columns:
            styled = styled.format("{:.2f}", subset=[fcol])

    st.dataframe(styled, use_container_width=True, height=400)
    st.caption(f"Showing {len(table)} candidates (live-scored)")


# ── Sector heat ───────────────────────────────────────────────────────────────

def render_sector_heat() -> None:
    st.subheader("Sector Heat")

    window_choice = st.radio(
        "Lookback", ["Today", "5 days (avg)", "20 days (avg)"],
        horizontal=True, key="sector_heat_window",
        help="Average per-day counts of trend_ok / breakout_ok tickers per sector.",
    )
    window_days = {"Today": 1, "5 days (avg)": 5, "20 days (avg)": 20}[window_choice]
    heat = load_sector_heat(window_days=window_days)

    if heat.empty:
        st.info("No sector heat data.")
        return

    # Drop ETF pseudo-sectors and any zero-universe rows
    h = heat[~heat["sector"].astype(str).str.startswith("ETF:")]
    h = h[h["universe_n"] > 0].copy()

    if h.empty:
        st.info("No equity sectors above threshold.")
        return

    # Format text labels — averages should be int-ish to one decimal
    is_avg = window_days > 1
    fmt = "{:.1f}" if is_avg else "{:.0f}"

    fig = go.Figure()
    fig.add_bar(
        x=h["sector"], y=h["trend_ok_n"], name="trend_ok",
        marker_color="#42a5f5",
        text=[fmt.format(v) for v in h["trend_ok_n"]],
        textposition="outside", cliponaxis=False,
    )
    fig.add_bar(
        x=h["sector"], y=h["breakout_n"], name="breakout_ok",
        marker_color="#ffa726",
        text=[fmt.format(v) for v in h["breakout_n"]],
        textposition="outside", cliponaxis=False,
    )

    # Fixed y-axis 0 → 150 (or higher if the data exceeds it) so the chart is
    # comparable across days and the top-bar text doesn't get clipped.
    y_max = max(150, float(h["trend_ok_n"].max()) * 1.15)

    suffix = "" if window_days == 1 else f" — {window_days}d avg"
    fig.update_layout(
        barmode="group",
        title=f"Setups by sector (latest trading day{suffix})",
        xaxis_tickangle=-45,
        yaxis=dict(range=[0, y_max], title="Tickers"),
        height=420, margin=dict(l=30, r=30, t=60, b=90),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)


# ── Analytics (legacy panel, kept) ────────────────────────────────────────────

def render_analytics(scored: pd.DataFrame, watchlist: pd.DataFrame) -> None:
    st.subheader("Analytics")
    active = watchlist[watchlist["status"] == "ACTIVE"]
    exited = watchlist[watchlist["status"] == "EXITED"]

    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Active Trades", len(active))
    q2.metric("Avg Return (Active)",
              f"{active['pct_return'].mean():+.1f}%" if not active.empty else "N/A")
    win_rate = (exited["pct_return"] > 0).mean() * 100 if not exited.empty else 0
    q3.metric("Win Rate (Exited)", f"{win_rate:.0f}%")
    q4.metric("Avg Holding Period",
              f"{active['days_held'].mean():.0f}d" if not active.empty else "N/A")

    col_a, col_b = st.columns(2)
    with col_a:
        if not active.empty:
            ag = active[["ticker", "sector", "days_held", "pct_return"]].copy()
            # Quadrants are always computed on raw pct_return — the y-scale toggle
            # only changes how it's displayed, not the quadrant boundary semantics.
            #   Aging  : >60d and <5%   (red — running stale)
            #   Mature : >60d and >=5%  (green — let it run)
            #   Young  : <=60d and <5%  (gray — still developing)
            #   Hot    : <=60d and >=5% (orange — early winner)
            def _q(row):
                if row["days_held"] > 60 and row["pct_return"] < 5:
                    return "Aging"
                if row["days_held"] > 60 and row["pct_return"] >= 5:
                    return "Mature"
                if row["days_held"] <= 60 and row["pct_return"] < 5:
                    return "Young"
                return "Hot"
            ag["quadrant"] = ag.apply(_q, axis=1)
            color_map = {"Aging": "#ef5350", "Mature": "#2e7d32",
                         "Young": "#9e9e9e", "Hot":  "#fb8c00"}

            ctrl_a, ctrl_b = st.columns([1, 1])
            with ctrl_a:
                scale = st.radio(
                    "Y scale", ["Linear", "Log (signed)"],
                    horizontal=True, key="age_scatter_scale",
                    help="Log compresses big winners and stretches small losers — "
                         "useful when one or two trades dominate the linear view.",
                )
            with ctrl_b:
                lock_x = st.checkbox(
                    "Lock X axis (zoom Y only)", value=True,
                    key="age_scatter_lock_x",
                    help="TradingView-style: scroll/drag zooms Y only. "
                         "Double-click to reset.",
                )

            # Signed log transform: sign(r) * log10(1 + |r|) — keeps zero at zero,
            # works for negatives, compresses tails symmetrically.
            if scale == "Log (signed)":
                ag["_y"] = np.sign(ag["pct_return"]) * np.log10(
                    1 + ag["pct_return"].abs())
                y_5_line = float(np.sign(5) * np.log10(1 + 5))
                y_title = "Return (signed log10)"
                hover_fmt = {"pct_return": ":+.2f"}
            else:
                ag["_y"] = ag["pct_return"]
                y_5_line = 5.0
                y_title = "Return %"
                hover_fmt = None

            fig = px.scatter(
                ag, x="days_held", y="_y",
                color="quadrant", color_discrete_map=color_map,
                hover_data={"ticker": True, "sector": True,
                            "pct_return": ":+.2f", "days_held": True,
                            "_y": False, "quadrant": False},
                text="ticker",
                title="Days Held vs Return (active)",
                category_orders={"quadrant": ["Hot", "Mature", "Young", "Aging"]},
            )
            fig.update_traces(textposition="top center",
                              textfont=dict(size=9, color="#444"),
                              marker=dict(size=10, line=dict(width=0.5, color="#fff")))
            fig.add_hline(y=y_5_line, line_dash="dash", line_color="#9e9e9e",
                          annotation_text="5%", annotation_position="right")
            fig.add_vline(x=60, line_dash="dash", line_color="#9e9e9e",
                          annotation_text="60d", annotation_position="top")
            fig.update_layout(
                height=400, xaxis_title="Days Held", yaxis_title=y_title,
                legend=dict(orientation="h", yanchor="bottom", y=1.02,
                            xanchor="right", x=1),
                margin=dict(l=40, r=20, t=60, b=40),
                dragmode="zoom",
            )
            if lock_x:
                fig.update_xaxes(fixedrange=True)
                fig.update_yaxes(fixedrange=False)
            st.plotly_chart(fig, use_container_width=True)

            with st.expander("Tickers by quadrant", expanded=False):
                quad_filter = st.multiselect(
                    "Filter quadrants",
                    options=["Hot", "Mature", "Young", "Aging"],
                    default=["Aging"],
                    key="age_quadrant_filter",
                    help="Aging = held >60d but still under 5% return — review for exit.",
                )
                sub = ag[ag["quadrant"].isin(quad_filter)] if quad_filter else ag
                sub = sub.sort_values(["quadrant", "days_held"], ascending=[True, False])
                st.dataframe(
                    sub[["ticker", "sector", "days_held", "pct_return", "quadrant"]]
                       .rename(columns={"ticker": "Ticker", "sector": "Sector",
                                        "days_held": "Days", "pct_return": "Return %",
                                        "quadrant": "Quadrant"})
                       .style.format({"Return %": "{:+.2f}%", "Days": "{:.0f}"}),
                    use_container_width=True, hide_index=True,
                )
        else:
            st.info("No active trades.")

    with col_b:
        if not active.empty:
            sector_counts = active["sector"].value_counts().reset_index()
            sector_counts.columns = ["sector", "count"]
            fig = px.bar(sector_counts, x="sector", y="count",
                         title="Active Sector Concentration")
            fig.update_traces(marker_color="#42a5f5")
            fig.update_layout(height=350, xaxis_tickangle=-45,
                              yaxis_title="Trades", xaxis_title="")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No active trades.")


# ── Page entrypoint ──────────────────────────────────────────────────────────

def page_today() -> None:
    st.title("Quantamental — Today")

    render_pipeline_status(load_pipeline_status())
    st.markdown("---")

    # M03 + 5F side-by-side
    regime = load_regime()
    risk = load_risk_5f()
    col_regime, col_risk = st.columns(2)
    with col_regime:
        render_regime_header(regime)
    with col_risk:
        render_risk_5f_header(risk)

    st.markdown("---")

    # Active trades
    watchlist = load_watchlist()
    deployment = load_deployment_features()
    scored = score_active_trades(watchlist, deployment)
    render_watchlist_table(scored, watchlist)

    st.markdown("---")

    # Pre-breakout watch
    render_pre_breakout(load_pre_breakout(limit=100))

    st.markdown("---")

    # Sector heat (loads internally based on window radio)
    render_sector_heat()

    st.markdown("---")

    # Analytics
    render_analytics(scored, watchlist)


# ── Navigation ────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Quantamental Dashboard", layout="wide")

PAGES_DIR = Path(__file__).resolve().parent / "pages"

pg = st.navigation([
    st.Page(page_today, title="Today", icon="📋"),
    st.Page(str(PAGES_DIR / "1_Feature_Time_Series.py"),
            title="Feature Time Series", icon="📈"),
    st.Page(str(PAGES_DIR / "3_Model_Lab.py"),
            title="Model Lab", icon="🧪"),
    st.Page(str(PAGES_DIR / "4_Backtest_Studio.py"),
            title="Backtest Studio", icon="📊"),
    st.Page(str(PAGES_DIR / "5_Pipeline_Health.py"),
            title="Pipeline Health", icon="🔧"),
])
pg.run()
