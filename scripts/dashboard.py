"""Quantamental Dashboard — entrypoint.

Two-tier navigation (Decide / Workshop) defined at the bottom of this file;
pages live under scripts/pages/. Macro is the default landing.

Auth model:
  Local: localhost-only (no --server.address 0.0.0.0), no auth needed.
  Streamlit Cloud: viewer allowlist by Google email (set in Community Cloud
  settings). R2_ACCOUNT_ID + R2_ACCESS_KEY + R2_SECRET_KEY + R2_BUCKET_NAME
  (+ optional R2_JURI_ENDPOINT_URL) + DASHBOARD_DB_PATH must be set as
  Streamlit secrets. Key names must match .env.example / dashboard_utils.py.

🛑 **DATA FLOW IS ONE-WAY** (rule set 2026-07-18 after a tier-0 incident):

    local main DB → build_dashboard_db → slim DB → R2 → remote viewer

  Nothing ever flows R2 → local. Pulling from R2 requires an explicit
  **`DASHBOARD_PULL_FROM_R2=1`** opt-in that ONLY the Streamlit Cloud
  deployment sets — credentials alone grant nothing (the dev and ops boxes hold
  them too, which is how a pull once overwrote the 67 GB main DB).

  ⚠️ **Streamlit Cloud must set `DASHBOARD_PULL_FROM_R2=1` as a secret**, or the
  remote serves whatever DB shipped with the repo and never refreshes.

  ⚠️ **NEVER set `DASHBOARD_DB_PATH=data/market_data.duckdb`.** To read the full
  local database, leave the variable UNSET — that is already the default.
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
    P_HR_COL,
    P_STRONG_COL,
    load_activity_feed,
    load_cohort_return_panel,
    load_daily_predictions_today,
    load_macro_pillars,
    load_past_decisions,
    load_pipeline_status,
    load_prod_model_version_id,
    load_rank_cohorts,
    load_rank_history,
    load_rank_history_bounds,
    load_recent_exits,
    load_scored_pre_breakout,
    load_scored_watchlist,
    load_sector_heat,
    load_shortlist,
    load_vip_watchlist,
    load_weather_gauge,
    load_ticker_history,
    load_watchlist,
    update_decision_taken,
)


# ── Header components ────────────────────────────────────────────────────────

def render_pipeline_status(pipeline: pd.DataFrame) -> None:
    if pipeline.empty:
        return
    latest = pipeline.iloc[0]
    status_icon = {"SUCCESS": "🟢", "FAILED": "🔴", "RUNNING": "🟡"}.get(latest["status"], "⚪")
    ts = latest["completed_at"] or latest["started_at"]
    st.caption(f"Pipeline: {status_icon} {latest['phase_name']} — {ts}")


def render_macro_dashboard() -> None:
    st.subheader("6-Pillar Macro Environment")
    df = load_macro_pillars()
    if df.empty:
        st.warning("No macro data available.")
        return
        
    latest = df.iloc[-1]
    
    col1, col2 = st.columns([1, 1.2])
    
    with col1:
        st.markdown("**Latest Snapshot** (Percentiles 0-100)")
        
        pillars = [
            ("VIX (Fear)", "VIX_pct"),
            ("Credit Stress", "Credit_pct"),
            ("Term Spread", "Term Spread_pct"),
            ("Rates (Financial Conditions)", "Rates_pct"),
            ("Net Liquidity", "Liquidity_pct"),
            ("Valuation (CAPE*)", "CAPE_pct"),
        ]
        _cape_now = latest.get("CAPE")
        _cape_note = (
            f"*Valuation = self-computed aggregate CAPE (latest **{_cape_now:.1f}**), "
            "not the published Shiller number — tracks it (rank corr 0.87) but runs ~1.3× "
            "high by construction. Read the percentile, not the level."
            if pd.notna(_cape_now) else ""
        )
        
        names = []
        vals = []
        colors = []
        # Reverse for top-to-bottom layout
        for name, col_pct in reversed(pillars): 
            names.append(name)
            val = latest[col_pct] if pd.notna(latest.get(col_pct)) else 0
            vals.append(val)
            if val < 40:
                colors.append("#2e7d32") # Green
            elif val < 75:
                colors.append("#fb8c00") # Orange
            else:
                colors.append("#c62828") # Red
                
        fig = go.Figure(go.Bar(
            x=vals, y=names, orientation='h',
            marker=dict(color=colors),
            text=[f"{v:.0f}" if v else "N/A" for v in vals],
            textposition='auto'
        ))
        fig.update_layout(
            height=300, margin=dict(l=0, r=20, t=10, b=0),
            xaxis=dict(range=[0, 100], title="Percentile"),
        )
        st.plotly_chart(fig, use_container_width=True)
        if _cape_note:
            st.caption(_cape_note)

    with col2:
        st.markdown("**Historical Trends**")
        
        c_lb, c_sel = st.columns([1, 2])
        with c_lb:
            days = _lookback_selector("macro_hist_lb", default="3y")
        with c_sel:
            selected_pillars = st.multiselect(
                "Overlay Pillars", 
                options=[p[0] for p in pillars],
                default=["VIX (Fear)", "Net Liquidity"],
                label_visibility="collapsed"
            )
            
        if days is not None:
            cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=days)
            hist = df[df["date"] >= cutoff]
        else:
            hist = df
            
        fig2 = go.Figure()
        
        line_colors = {
            "VIX (Fear)": "#42a5f5",
            "Credit Stress": "#ab47bc",
            "Term Spread": "#26a69a",
            "Rates (Financial Conditions)": "#ffa726",
            "Net Liquidity": "#8d6e63",
            "Valuation (CAPE*)": "#ef5350"
        }
        
        for name, col_pct in pillars:
            if name in selected_pillars:
                fig2.add_trace(go.Scatter(
                    x=hist["date"], y=hist[col_pct], name=name,
                    mode="lines", line=dict(color=line_colors[name], width=1.5)
                ))
                
        fig2.add_hline(y=75, line=dict(color="#b71c1c", width=1, dash="dash"), annotation_text="Elevated", annotation_position="top right")
                
        fig2.update_layout(
            height=300, margin=dict(l=0, r=20, t=10, b=0),
            yaxis=dict(range=[0, 100], title="Percentile"),
            legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0)
        )
        st.plotly_chart(fig2, use_container_width=True)


# ── Regime / risk history charts ──────────────────────────────────────────────

_LOOKBACKS = {"90d": 90, "1y": 365, "3y": 365 * 3, "All": None}


def _lookback_selector(key: str, default: str = "1y") -> int | None:
    choice = st.radio(
        "Lookback", list(_LOOKBACKS), index=list(_LOOKBACKS).index(default),
        horizontal=True, key=key, label_visibility="collapsed",
    )
    return _LOOKBACKS[choice]





# ── Weather gauge (deploy posture) ────────────────────────────────────────────

# Posture → (ordinal level for the history strip, colour). Higher = more risk-on.
_POSTURE_META = {
    "STAND ASIDE":      (0, "#c62828"),  # red — the brake
    "DEPLOY, TRIM NEW": (1, "#fb8c00"),  # amber — late-cycle
    "DEPLOY":           (2, "#2e7d32"),  # green — baseline bull
    "DEPLOY MORE":      (3, "#1565c0"),  # blue — rare stress-famine pocket
}


def render_weather_gauge() -> None:
    st.subheader("🌦️ Weather Gauge — deploy posture")
    df = load_weather_gauge()
    if df.empty:
        st.info("No weather-gauge state available.")
        return

    latest = df.iloc[-1]
    posture = latest["deploy_posture"]
    _, colour = _POSTURE_META.get(posture, (2, "#666"))
    as_of = pd.Timestamp(latest["date"]).date()

    st.markdown(
        f"<div style='background:{colour};color:white;padding:12px 18px;border-radius:8px;"
        f"font-size:1.4rem;font-weight:700;display:inline-block'>{posture}</div>"
        f"<span style='margin-left:12px;color:#888'>as of {as_of}</span>",
        unsafe_allow_html=True,
    )
    st.caption(
        "SPY-200d is the BRAKE (below it → STAND ASIDE, regardless of everything). "
        "Above it, breakout-supply + stress are the during-period STEER. `stress_z` is "
        "**provisional** (flicker-stabilization open) — the posture leans on the brake + "
        "supply. 6-pillar macro below is context, not a gate."
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("SPY vs 200d", "ABOVE ✅" if latest["spy_above_200d"] else "BELOW 🛑")
    c2.metric("Breakout supply", latest["supply_regime"].upper(),
              help="famine = early-recovery scarcity (the +10.5% pocket); flood = late-cycle over-supply")
    c3.metric("Stress z (provisional)", f"{latest['stress_z']:.2f}",
              delta="high" if latest["stress_high"] else "normal")

    # History strip: posture level over the loaded window (regime transitions, not a point).
    strip = df.copy()
    strip["level"] = strip["deploy_posture"].map(lambda p: _POSTURE_META.get(p, (2, ""))[0])
    strip["date"] = pd.to_datetime(strip["date"])
    fig = go.Figure(go.Scatter(
        x=strip["date"], y=strip["level"], mode="lines",
        line=dict(shape="hv", width=1),
        marker=dict(color=[_POSTURE_META.get(p, (2, "#666"))[1] for p in strip["deploy_posture"]]),
        hovertext=strip["deploy_posture"], hoverinfo="text+x",
    ))
    fig.update_layout(
        height=140, margin=dict(l=0, r=10, t=6, b=0),
        yaxis=dict(tickvals=[0, 1, 2, 3],
                   ticktext=["Aside", "Trim", "Deploy", "More"], range=[-0.3, 3.3]),
        xaxis=dict(title=None),
    )
    st.plotly_chart(fig, use_container_width=True)


# ── Daily shortlist (tail-edge artifact) ──────────────────────────────────────

def render_shortlist() -> None:
    st.subheader("📋 Daily Shortlist — tail-edge candidates")
    df = load_shortlist()
    if df.empty:
        st.info("No shortlist for the latest pipeline date.")
        return

    as_of = pd.Timestamp(df["date"].iloc[0]).date()
    st.caption(
        f"Today's ACTIVE SEPA breakouts ({as_of}), ranked by the validated tail cell — "
        "**strong-RS × small-cap × prob_elite**. These are **tail-odds, not a return "
        "forecast** (the median inverts — the edge is a minority of home-runs, not the "
        "typical name). Liquidity <$7.5M/day is tagged, not hidden — those names sink to "
        "the bottom. `aggressive` = the high-RS small-cap tail pocket; `defensive` = calmer."
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Candidates", len(df))
    c2.metric("Aggressive (tail)", int((df["posture"] == "aggressive").sum()))
    c3.metric("Liquid (≥$7.5M/day)", int(df["liquidity_ok"].sum()))

    show = df.head(50).copy()
    show["dollar_volume"] = (show["dollar_volume"] / 1e6).round(1)
    show["market_cap"] = (show["market_cap"] / 1e6).round(0)
    cols = {
        "ticker": "Ticker", "sector": "Sector", "close": "Close",
        "market_cap": "Mkt Cap ($M)", "rs_universe_rank": "RS %ile",
        "smallcap_pctl": "Small-cap %ile", "prob_elite": "P(Home Run)",
        "dollar_volume": "$Vol/day ($M)", "liquidity_ok": "Liquid",
        "posture": "Posture", "shortlist_score": "Score",
    }
    show = show[list(cols)].rename(columns=cols)
    st.dataframe(
        show.style.format({
            "Close": "{:.2f}", "RS %ile": "{:.2f}", "Small-cap %ile": "{:.2f}",
            "P(Home Run)": "{:.1%}", "$Vol/day ($M)": "{:.1f}",
            "Mkt Cap ($M)": "{:,.0f}", "Score": "{:.3f}",
        }, na_rep="—"),
        use_container_width=True, hide_index=True,
    )


def render_vip_watchlist() -> None:
    st.subheader("⭐ VIP Watchlist — your manually-curated names")
    df = load_vip_watchlist()
    if df.empty:
        st.info("No VIP names. Add via `python scripts/vip_add.py add TICKER "
                "--source ... --comment ...` — takes effect next nightly run.")
        return

    st.caption(
        "Names **you** added (from reports/tips) forced into the pipeline so you can "
        "monitor their daily SEPA status + prod model score even if they'd never pass "
        "the screen. `watching` = has data, nothing yet · `trend_ok` = valid setup · "
        "`breakout` = breakout today · `active`/`removed` = in/out of a SEPA session. "
        "⚠️ `not_in_universe` = no price data yet (needs a data fetch)."
    )

    GLYPH = {
        "active": "🟢 active", "breakout": "🔵 breakout", "trend_ok": "🟡 trend_ok",
        "watching": "⚪ watching", "removed": "🔴 removed",
        "not_in_universe": "⚠️ no data",
    }
    show = df.copy()
    show["status"] = show["status"].map(GLYPH).fillna(show["status"])
    show["dollar_volume"] = (show["dollar_volume"] / 1e6).round(1)
    cols = {
        "ticker": "Ticker", "status": "Status", "prob_elite": "P(Home Run)",
        "rs_universe_rank": "RS %ile", "close": "Close",
        "dollar_volume": "$Vol/day ($M)", "as_of_date": "As of",
        "added_date": "Added", "source": "Source", "comment": "Why I added it",
    }
    show = show[list(cols)].rename(columns=cols)
    st.dataframe(
        show.style.format({
            "P(Home Run)": "{:.1%}", "RS %ile": "{:.2f}", "Close": "{:.2f}",
            "$Vol/day ($M)": "{:.1f}",
        }, na_rep="—"),
        use_container_width=True, hide_index=True,
    )


# ── Active trades table ───────────────────────────────────────────────────────

def render_watchlist_table(scored: pd.DataFrame, watchlist: pd.DataFrame) -> None:
    st.subheader("Screener Watchlist")
    st.caption(
        "M01 scores are the prod model's P(Home Run), materialized nightly. "
        "ACTIVE trades show the LATEST score (tracks the name while held); EXITED "
        "trades show the score as of their entry day. Blank when the name has no "
        "score in any cohort — its SEPA session predates the 252-day deployment "
        "window, or it is a new listing with no t3 features."
    )

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

    # `scored` carries the FULL watchlist (every ACTIVE + EXITED trade) joined to
    # predictions — filter by status here, don't assume it's pre-filtered.
    if status_filter == "ACTIVE":
        display = scored[scored["status"] == "ACTIVE"].copy()
    elif status_filter == "EXITED":
        display = scored[scored["status"] == "EXITED"].copy()
    else:  # "All"
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
    show_cols = ["ticker", "company_name", "sector", "market_cap",
                 "entry_date", "entry_price", "close_price",
                 "pct_return", "days_held"]
    if "m01_class" in display.columns:
        show_cols.append("m01_class")
        show_cols.extend(proba_cols)
    show_cols.append("status")

    available_cols = [c for c in show_cols if c in display.columns]
    table = display[available_cols].copy()

    # Cap rows before styling — pandas Styler errors past ~262K cells, and the
    # EXITED/All views carry ~38K trades. The frame is already sorted, so the cap
    # keeps the most relevant rows (top of the chosen sort).
    MAX_ROWS = 2000
    truncated = len(table) > MAX_ROWS
    if truncated:
        table = table.head(MAX_ROWS)

    # Ticker → Finviz link via LinkColumn. URL goes in the column; display_text
    # regex strips it back to the bare ticker for display.
    if "ticker" in table.columns:
        table["ticker"] = table["ticker"].apply(
            lambda t: f"https://finviz.com/quote.ashx?t={t}" if pd.notna(t) else None
        )

    rename = {
        "ticker": "Ticker", "company_name": "Company", "sector": "Sector",
        "market_cap": "Mkt Cap",
        "entry_date": "Entry Date", "entry_price": "Entry $", "close_price": "Price $",
        "pct_return": "Return %", "days_held": "Days", "status": "Status",
        "m01_class": "M01 Class",
    }
    for l in CLASS_LABELS:
        rename[f"p_{l}"] = f"P({l.split(' ')[0]})"
    table = table.rename(columns={k: v for k, v in rename.items() if k in table.columns})

    def _fmt_mcap(v):
        if pd.isna(v):
            return "—"
        if v >= 1e12:
            return f"${v / 1e12:.2f}T"
        if v >= 1e9:
            return f"${v / 1e9:.2f}B"
        if v >= 1e6:
            return f"${v / 1e6:.0f}M"
        return f"${v:,.0f}"

    column_config: dict = {}
    if "Ticker" in table.columns:
        column_config["Ticker"] = st.column_config.LinkColumn(
            "Ticker", help="Open Finviz quote",
            display_text=r"finviz\.com/quote\.ashx\?t=(.+)$",
        )
    if "Mkt Cap" in table.columns:
        column_config["Mkt Cap"] = st.column_config.TextColumn(
            "Mkt Cap", help="Market cap (point-in-time at watchlist refresh)",
        )
        table["Mkt Cap"] = table["Mkt Cap"].apply(_fmt_mcap)

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

    st.dataframe(styled, use_container_width=True, height=500,
                 column_config=column_config)
    cap_note = f" (capped at {MAX_ROWS:,} of {len(display):,})" if truncated else ""
    st.caption(f"Showing {len(table)} trades{cap_note} · sorted by {sort_choice}")


# ── Watchlist activity / exits (F2) ───────────────────────────────────────────

def _finviz(t):
    return f"https://finviz.com/quote.ashx?t={t}" if pd.notna(t) else None


_FINVIZ_LINK = st.column_config.LinkColumn(
    "Ticker", help="Open Finviz quote",
    display_text=r"finviz\.com/quote\.ashx\?t=(.+)$",
)


def _style_return_col(styled, col: str):
    def _c(val):
        if pd.isna(val):
            return ""
        return f"color: {'#2e7d32' if val >= 0 else '#c62828'}"
    return styled.map(_c, subset=[col]).format("{:+.2f}%", subset=[col], na_rep="—")


def render_activity_feed(model_version_id: str | None = None) -> None:
    st.subheader("Watchlist Activity")
    st.caption(
        "What recently left the watchlist (realized trade exits) and the universe "
        "(screener add/remove flips). Use the per-ticker lookup for full session history."
    )

    tab_exits, tab_feed, tab_ticker = st.tabs(
        ["Recent exits", "Activity feed", "Ticker history"]
    )

    # ── Recent trade exits ─────────────────────────────────────────────
    with tab_exits:
        window = st.radio(
            "Window", [7, 14, 30], index=1, horizontal=True,
            format_func=lambda d: f"Last {d}d", key="exits_window",
        )
        exits = load_recent_exits(days=int(window))
        if exits.empty:
            st.info(f"No trade exits in the last {window} days.")
        else:
            tbl = exits.copy()
            tbl["ticker"] = tbl["ticker"].apply(_finviz)
            tbl = tbl.rename(columns={
                "ticker": "Ticker", "company_name": "Company", "sector": "Sector",
                "entry_date": "Entered", "exit_date": "Exited",
                "days_held": "Days", "pct_return": "Return %",
            })
            styled = _style_return_col(tbl.style, "Return %")
            styled = styled.format("{:.0f}", subset=["Days"], na_rep="—")
            st.dataframe(
                styled, use_container_width=True, hide_index=True, height=420,
                column_config={"Ticker": _FINVIZ_LINK},
            )
            st.caption(f"{len(exits)} exits · sorted by exit date (newest first)")

    # ── Unified activity feed ──────────────────────────────────────────
    with tab_feed:
        window = st.radio(
            "Window", [7, 14, 30], index=1, horizontal=True,
            format_func=lambda d: f"Last {d}d", key="feed_window",
        )
        feed = load_activity_feed(days=int(window))
        if feed.empty:
            st.info(f"No activity in the last {window} days.")
        else:
            type_opts = sorted(feed["event_type"].unique().tolist())
            picked = st.multiselect(
                "Event types", type_opts, default=type_opts, key="activity_types",
            )
            view = feed[feed["event_type"].isin(picked)] if picked else feed
            badge = {
                "TRADE_EXIT": "🔴 Trade exit",
                "UNIVERSE_ADD": "🟢 Universe add",
                "UNIVERSE_REMOVE": "⚪ Universe remove",
            }
            disp = view.copy()
            disp["event_type"] = disp["event_type"].map(lambda t: badge.get(t, t))
            disp["ticker"] = disp["ticker"].apply(_finviz)
            disp = disp.rename(columns={
                "event_date": "Date", "ticker": "Ticker", "company_name": "Company",
                "event_type": "Event", "detail": "Detail",
            })
            st.dataframe(
                disp, use_container_width=True, hide_index=True, height=420,
                column_config={"Ticker": _FINVIZ_LINK},
            )
            st.caption(f"{len(view)} events in the last {window} days")

    # ── Per-ticker session history ─────────────────────────────────────
    with tab_ticker:
        tk = st.text_input(
            "Ticker", "", placeholder="e.g. AAOI (press Enter)",
            key="activity_ticker_lookup",
        ).strip().upper()
        if not tk:
            st.info("Enter a ticker to see every SEPA session it has run.")
        else:
            hist = load_ticker_history(tk, model_version_id)
            if hist.empty:
                st.info(f"No watchlist sessions found for {tk}.")
            else:
                name = hist["company_name"].dropna().iloc[0] if hist["company_name"].notna().any() else ""
                st.markdown(f"**{tk}** — {name} · {len(hist)} session(s)")
                h = hist.copy()
                # An ACTIVE row's exit_date is the as-of date, not a realized exit.
                h.loc[h["status"] == "ACTIVE", "exit_date"] = pd.NaT
                h = h.rename(columns={
                    "entry_date": "Entered", "entry_price": "Entry $",
                    "exit_date": "Exited", "status": "Status",
                    "close_price": "Last $", "pct_return": "Return %",
                    "days_held": "Days", "entry_score": "Entry P(HR)",
                })
                show = ["Entered", "Entry $", "Entry P(HR)", "Exited", "Status",
                        "Last $", "Return %", "Days"]
                show = [c for c in show if c in h.columns]
                styled = _style_return_col(h[show].style, "Return %")
                styled = styled.format("${:.2f}", subset=["Entry $", "Last $"], na_rep="—")
                styled = styled.format("{:.0f}", subset=["Days"], na_rep="—")
                if "Entry P(HR)" in show:
                    styled = styled.format("{:.2f}", subset=["Entry P(HR)"], na_rep="—")
                st.dataframe(styled, use_container_width=True, hide_index=True)
                st.caption("Entry P(HR) = prod M01 P(Home Run) as the signal fired "
                           "(NULL for sessions predating the scored window).")


# ── Pre-breakout watch table ──────────────────────────────────────────────────

def render_pre_breakout(scored: pd.DataFrame) -> None:
    st.subheader("Pre-Breakout Watch")
    st.caption("trend_ok = TRUE, breakout_ok = FALSE — names in setup, not yet triggered. "
               "Scored nightly by the prod M01 model (materialized).")

    if scored.empty:
        st.info("No pre-breakout candidates today.")
        return

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
    st.caption(f"Showing {len(table)} candidates (scored nightly)")


# ── Daily rank bump chart (2b) ────────────────────────────────────────────────

_RANK_TOP_N = [5, 10, 20, 50]


def _rank_metric_for(model_version_id: str) -> str:
    """Score column carrying P(Home Run) for this model — binary uses class_1,
    the 4-class prototype uses class_3. Rank itself comes from rank_within_day;
    this only picks the probability shown on hover."""
    return "prob_class_1" if "binary" in model_version_id.lower() else "prob_class_3"


def render_rank_bump_chart(model_version_id: str | None) -> None:
    st.subheader("Daily Rank Bump — top P(Home Run) names over time")
    if not model_version_id:
        st.info("No prod model registered — nothing to rank.")
        return

    cohorts = load_rank_cohorts(model_version_id)
    if not cohorts:
        st.info("No daily predictions for the prod model yet.")
        return
    lo, hi = load_rank_history_bounds(model_version_id)

    st.caption(
        "Each line is one ticker; y = its prod-model P(Home Run) rank that day "
        "(1 = best, on top). Membership is per-day top-N, so lines enter/leave as "
        "ranks shift. A segment connects two days only when the ticker is top-N on "
        "both — isolated days render as points. The breakout cohort is fresh "
        "breakouts (turns over daily → mostly points); pre_breakout names persist "
        "as they set up → more crossing lines."
    )

    # pre_breakout shows persistence, so prefer it when available.
    default_cohort = "pre_breakout" if "pre_breakout" in cohorts else cohorts[0]
    # Form: controls only fire on Apply (avoids the per-keystroke whole-page rerun).
    with st.form("rank_bump_controls", border=False):
        bc1, bc2, bc3 = st.columns([1, 1, 2])
        with bc1:
            cohort = st.selectbox(
                "Cohort", cohorts, index=cohorts.index(default_cohort),
                key="rank_bump_cohort",
            )
        with bc2:
            top_n = st.selectbox("Top-N", _RANK_TOP_N, index=1, key="rank_bump_top_n")
        with bc3:
            dr = st.date_input(
                "Date range", value=(hi - pd.Timedelta(days=60), hi),
                min_value=lo, max_value=hi, key="rank_bump_date_range",
            )
        st.form_submit_button("Apply", type="primary")

    if not (isinstance(dr, (list, tuple)) and len(dr) == 2):
        st.info("Pick a start and end date.")
        return
    start, end = dr

    metric = _rank_metric_for(model_version_id)
    df = load_rank_history(model_version_id, top_n=int(top_n),
                           start=start, end=end, metric=metric, cohort=cohort)
    if df.empty:
        st.info("No ranked names in this range.")
        return

    df = df.copy()
    df["prediction_date"] = pd.to_datetime(df["prediction_date"])

    # Adjacency: only consecutive entries on calendar-adjacent prediction dates
    # (no top-N gap day between them) get a connecting segment. Index each
    # distinct date so a one-step gap in position == adjacent.
    dates = sorted(df["prediction_date"].unique())
    date_pos = {d: i for i, d in enumerate(dates)}
    df["dpos"] = df["prediction_date"].map(date_pos)

    fig = go.Figure()
    palette = px.colors.qualitative.Alphabet + px.colors.qualitative.Light24
    for i, (tk, g) in enumerate(df.groupby("ticker", sort=False)):
        g = g.sort_values("dpos")
        color = palette[i % len(palette)]
        # Split into runs of consecutive (adjacent) dates; isolated runs of
        # length 1 draw as a marker, runs >=2 draw as a connected line.
        run_id = (g["dpos"].diff() != 1).cumsum()
        last_x = g["prediction_date"].iloc[-1]
        last_y = g["rank_within_day"].iloc[-1]
        for _, run in g.groupby(run_id):
            mode = "lines+markers" if len(run) >= 2 else "markers"
            fig.add_trace(go.Scatter(
                x=run["prediction_date"], y=run["rank_within_day"],
                name=tk, legendgroup=tk, mode=mode,
                line=dict(color=color, width=1.6),
                marker=dict(color=color, size=6),
                showlegend=False,
                customdata=run[["score"]],
                hovertemplate=(f"<b>{tk}</b><br>%{{x|%Y-%m-%d}}<br>"
                               "rank %{y}<br>P(HR) %{customdata[0]:.3f}<extra></extra>"),
            ))
        # End-of-line label so the dense chart stays readable without a legend.
        fig.add_trace(go.Scatter(
            x=[last_x], y=[last_y], mode="text", text=[tk],
            textposition="middle right", textfont=dict(size=9, color=color),
            showlegend=False, hoverinfo="skip",
        ))

    fig.update_layout(
        height=560, margin=dict(l=30, r=60, t=20, b=30),
        xaxis=dict(title="date"),
        yaxis=dict(title="rank (1 = best)", autorange="reversed",
                   dtick=1 if top_n <= 20 else 5),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_cohort_return_tracker(model_version_id: str | None) -> None:
    st.subheader("Watchlist Cohort-Return Tracker — did recent signals actually pay?")
    if not model_version_id:
        st.info("No prod model registered — nothing to score.")
        return
    cohorts = load_rank_cohorts(model_version_id)
    if not cohorts:
        st.info("No daily predictions for the prod model yet.")
        return

    st.caption(
        "Each x-position is a signal day (days before the latest data). The band is "
        "the realized-return distribution of the tickers scored **that day** — "
        "membership is per-day, so it turns over. Raise the P(Home Run) knob to keep "
        "only high-conviction names and watch the distribution shift. Bounded by the "
        "slim DB's ~1y price window."
    )

    default_cohort = "breakout" if "breakout" in cohorts else cohorts[0]
    with st.form("cohort_ret_controls", border=False):
        c1, c2, c3, c4 = st.columns([1.2, 1.4, 1.4, 1])
        with c1:
            cohort = st.selectbox("Cohort", cohorts,
                                  index=cohorts.index(default_cohort),
                                  key="cohort_ret_cohort")
        with c2:
            min_score = st.slider("P(Home Run) ≥", 0.0, 1.0, 0.0, 0.05,
                                  key="cohort_ret_score")
        with c3:
            mode_label = st.radio("Return", ["To latest", "Forward N-day"],
                                  horizontal=True, key="cohort_ret_mode")
        with c4:
            horizon = st.number_input("N (days)", 5, 120, 20, 5,
                                      key="cohort_ret_horizon")
        st.form_submit_button("Apply", type="primary")

    mode = "to_today" if mode_label == "To latest" else "forward"
    df = load_cohort_return_panel(model_version_id, cohort=cohort,
                                  min_score=float(min_score), mode=mode,
                                  horizon=int(horizon))
    if df.empty:
        st.info("No scored names with a computable return in this cohort/threshold.")
        return

    # Per-day distribution: median line + p25–p75 / p10–p90 bands, x = days ago
    # (reversed so recent is on the right, reading left→right = past→present).
    g = df.groupby("days_before_today")["ret_pct"]
    stats = pd.DataFrame({
        "median": g.median(), "mean": g.mean(),
        "p10": g.quantile(0.10), "p25": g.quantile(0.25),
        "p75": g.quantile(0.75), "p90": g.quantile(0.90),
        "n": g.size(),
    }).reset_index().sort_values("days_before_today", ascending=False)
    x = stats["days_before_today"]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=stats["p90"], mode="lines",
                             line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=stats["p10"], mode="lines", line=dict(width=0),
                             fill="tonexty", fillcolor="rgba(31,119,180,0.12)",
                             name="p10–p90", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=stats["p75"], mode="lines",
                             line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=stats["p25"], mode="lines", line=dict(width=0),
                             fill="tonexty", fillcolor="rgba(31,119,180,0.25)",
                             name="p25–p75", hoverinfo="skip"))
    fig.add_trace(go.Scatter(
        x=x, y=stats["median"], mode="lines", name="median",
        line=dict(color="#1f77b4", width=2),
        customdata=stats[["mean", "n"]],
        hovertemplate=("%{x} d ago<br>median %{y:.1f}%<br>"
                       "mean %{customdata[0]:.1f}%<br>n=%{customdata[1]}<extra></extra>"),
    ))
    fig.add_hline(y=0, line=dict(color="grey", width=1, dash="dot"))
    fig.update_layout(
        height=460, margin=dict(l=30, r=30, t=20, b=30),
        xaxis=dict(title="days before latest data", autorange="reversed"),
        yaxis=dict(title="return %"),
        legend=dict(orientation="h", y=1.05),
    )
    st.plotly_chart(fig, use_container_width=True)
    span = f"{int(x.min())}–{int(x.max())} days back"
    tail = (f" · forward mode: the newest ~{int(horizon)} days lack a full "
            "future window and drop out." if mode == "forward" else "")
    st.caption(f"{len(df):,} name-days across {span}, "
               f"{stats['n'].sum():,} return observations.{tail}")


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


# ── Daily decision log (Phase D §5.1) ────────────────────────────────────────

DECISION_OPTIONS = ["—", "Taken", "Skipped"]
_DECISION_TO_DB = {"—": None, "Taken": "taken", "Skipped": "skipped"}
_DB_TO_DECISION = {v: k for k, v in _DECISION_TO_DB.items()}


def render_decision_log() -> None:
    st.subheader("Today's Predictions — Decision Log")
    st.caption("Logged from the daily pipeline. Toggle Decision per ticker to record "
               "paper-trade actions; updates persist to `daily_predictions`.")

    version_id = load_prod_model_version_id()
    if not version_id:
        st.info("No prod model registered — nothing to log.")
        return

    preds = load_daily_predictions_today(version_id)
    if preds.empty:
        st.info(
            "No predictions logged yet for the latest pipeline run. "
            "Run the daily pipeline (`scripts/run_daily_pipeline.py`) to populate."
        )
        return

    pred_date = preds["prediction_date"].iloc[0]
    st.caption(f"Model: `{version_id}` · prediction_date = {pred_date} · {len(preds)} tickers")

    display = preds[[
        "ticker", "rank_within_day", "predicted_class",
        "prob_class_3", "prob_class_2", "decision_taken", "notes",
    ]].copy()
    display["Decision"] = display["decision_taken"].map(lambda v: _DB_TO_DECISION.get(v, "—"))
    display = display.drop(columns=["decision_taken"]).rename(columns={
        "ticker": "Ticker",
        "rank_within_day": "Rank",
        "predicted_class": "Pred Class",
        "prob_class_3": "P(Home Run)",
        "prob_class_2": "P(Strong)",
        "notes": "Notes",
    })

    edited = st.data_editor(
        display,
        column_config={
            "Decision": st.column_config.SelectboxColumn(
                "Decision", options=DECISION_OPTIONS, required=True,
                help="Taken = entered position · Skipped = passed · — = undecided",
            ),
            "Notes": st.column_config.TextColumn("Notes", help="Optional free text"),
            "Ticker": st.column_config.TextColumn("Ticker", disabled=True),
            "Rank": st.column_config.NumberColumn("Rank", disabled=True),
            "Pred Class": st.column_config.NumberColumn("Pred Class", disabled=True),
            "P(Home Run)": st.column_config.NumberColumn(
                "P(Home Run)", format="%.3f", disabled=True,
            ),
            "P(Strong)": st.column_config.NumberColumn(
                "P(Strong)", format="%.3f", disabled=True,
            ),
        },
        hide_index=True,
        use_container_width=True,
        key="decision_editor",
    )

    # Diff editor output vs source, apply only the changed rows.
    changed = 0
    for i, row in edited.iterrows():
        orig_dec = display.loc[i, "Decision"]
        orig_notes = display.loc[i, "Notes"]
        new_dec = row["Decision"]
        new_notes = row.get("Notes")
        if new_dec != orig_dec or (pd.notna(new_notes) and new_notes != orig_notes):
            update_decision_taken(
                prediction_date=pred_date,
                ticker=row["Ticker"],
                model_version_id=version_id,
                decision=_DECISION_TO_DB[new_dec],
                notes=new_notes if pd.notna(new_notes) and new_notes else None,
            )
            changed += 1

    if changed > 0:
        load_daily_predictions_today.clear()
        load_past_decisions.clear()
        st.success(f"Updated {changed} decision{'s' if changed != 1 else ''}.")
        st.rerun()


def render_past_decisions() -> None:
    st.subheader("Performance of Past Decisions")
    st.caption("Joins `daily_predictions` (decision_taken IS NOT NULL) against "
               "`screener_watchlist` for realized outcomes.")

    version_id = load_prod_model_version_id()
    if not version_id:
        return

    past = load_past_decisions(version_id, limit=200)
    if past.empty:
        st.info("No past decisions yet. Toggle Decision above to start logging.")
        return

    # An ACTIVE session's exit_date is the as-of price date (prospective trend
    # boundary), not a realized exit — blank it so "Exited" reads honestly.
    past = past.copy()
    past.loc[past["status"] == "ACTIVE", "exit_date"] = pd.NaT

    show = past[[
        "prediction_date", "ticker", "decision_taken", "p_home_run",
        "predicted_class", "entry_date", "exit_date", "status",
        "pct_return", "days_held", "notes",
    ]].rename(columns={
        "prediction_date": "Predicted",
        "ticker": "Ticker",
        "decision_taken": "Decision",
        "p_home_run": "P(HR)",
        "predicted_class": "Pred Class",
        "entry_date": "Entered",
        "exit_date": "Exited",
        "status": "Status",
        "pct_return": "Return %",
        "days_held": "Days",
        "notes": "Notes",
    })

    styled = show.style
    if "P(HR)" in show.columns:
        styled = styled.format("{:.3f}", subset=["P(HR)"])
    if "Return %" in show.columns:
        styled = styled.format("{:+.2f}%", subset=["Return %"], na_rep="—")

    st.dataframe(styled, use_container_width=True, height=400)

    # Aggregate stats: hit-rate of "taken" decisions
    taken = past[past["decision_taken"] == "taken"]
    if not taken.empty and taken["pct_return"].notna().any():
        wins = (taken["pct_return"] > 0).sum()
        n_with_outcome = taken["pct_return"].notna().sum()
        avg_ret = taken["pct_return"].mean()
        st.metric(
            "Taken hit-rate",
            f"{wins}/{n_with_outcome} ({wins / n_with_outcome:.0%})" if n_with_outcome else "—",
            delta=f"avg {avg_ret:+.2f}%" if pd.notna(avg_ret) else None,
        )


# ── Page entrypoint ──────────────────────────────────────────────────────────

def page_today() -> None:
    st.title("Quantamental — Today")

    render_pipeline_status(load_pipeline_status())
    st.markdown("---")

    # Weather gauge — the headline deploy posture (brake + supply + stress)
    render_weather_gauge()

    st.markdown("---")

    # 6-pillar macro — context panel below the gauge (value/stress axis, not a gate)
    render_macro_dashboard()

    st.markdown("---")

    # Daily shortlist — the sprint-14 tail edge as a ranked morning artifact
    render_shortlist()

    st.markdown("---")

    # VIP watchlist — your manually-curated names + their live status/score
    render_vip_watchlist()

    st.markdown("---")

    # Active trades — scores from daily_predictions (no model file needed)
    version_id = load_prod_model_version_id()
    scored = load_scored_watchlist(version_id) if version_id else load_watchlist()
    render_watchlist_table(scored, scored)

    st.markdown("---")

    # Watchlist activity / exits (F2) — what recently left the watchlist + universe
    render_activity_feed(version_id)

    st.markdown("---")

    # Pre-breakout watch — scores from daily_predictions (no model file needed)
    pre = load_scored_pre_breakout(version_id, limit=100) if version_id else pd.DataFrame()
    render_pre_breakout(pre)

    st.markdown("---")

    # Daily decision log (Phase D §5.1)
    render_decision_log()

    st.markdown("---")

    # Past decisions performance
    render_past_decisions()

    st.markdown("---")

    # Daily rank bump chart (2b) — top-N P(Home Run) rank trajectories over time
    render_rank_bump_chart(version_id)

    st.markdown("---")

    # Watchlist cohort-return tracker — per-day return distribution of scored names
    render_cohort_return_tracker(version_id)

    st.markdown("---")

    # Sector heat (loads internally based on window radio)
    render_sector_heat()

    st.markdown("---")

    # Analytics — `scored` is the full watchlist (all statuses) + scores
    render_analytics(scored, scored)


# ── Navigation ────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Quantamental Dashboard", layout="wide")

PAGES_DIR = Path(__file__).resolve().parent / "pages"

# ── Two-tier navigation (sprint-14 uplift, switched over 2026-07-18) ──────────
# Tier 1 "Decide" = theta cream/serif decision surface. Tier 2 "Workshop" =
# dense/mono operator view, deliberately NOT theta-styled.
#
# The "Today" monolith is GONE. Its 13 sections were triaged at switch-over
# (dashboard_uplift/README.md): 5 already migrated, 4 carried onto dedicated
# pages, 4 dropped with evidence. No slim "Today" landing survived — once the
# Decision Log and Past-Decision Perf were dropped (1 logged decision in 302,220
# prediction rows; the `trades` CLI replaced them), the planned landing had
# nothing left to render but a title. Macro is the landing instead: the deploy
# posture is the first thing you want in the morning.
#
# `page_today` and its ~950 lines of render_* helpers are retained BELOW this
# nav but no longer routed — dead code pending the follow-up deletion pass, kept
# for one cycle so anything that turns out to be missed can be recovered from
# HEAD rather than git history.
pg = st.navigation({
    "Decide": [
        st.Page(str(PAGES_DIR / "2_Macro.py"), title="Macro", icon="🌐", default=True),
        st.Page(str(PAGES_DIR / "3_Screening.py"), title="Screening", icon="🔍"),
        st.Page(str(PAGES_DIR / "5_Session_Activity.py"),
                title="Session activity", icon="🗓️"),
        st.Page(str(PAGES_DIR / "4_Portfolio.py"), title="Portfolio", icon="💼"),
        st.Page(str(PAGES_DIR / "6_Supply_Chain.py"), title="Supply chain", icon="🕸️"),
        st.Page(str(PAGES_DIR / "7_Equity_Research.py"),
                title="Equity research", icon="📄"),
    ],
    "Workshop": [
        st.Page(str(PAGES_DIR / "1_Dataset_EDA.py"), title="Dataset EDA", icon="📈"),
        st.Page(str(PAGES_DIR / "3_Model_Lab.py"), title="Model Lab", icon="🧪"),
        st.Page(str(PAGES_DIR / "4_Backtest_Studio.py"),
                title="Backtest Studio", icon="📊"),
        st.Page(str(PAGES_DIR / "5_Pipeline_Health.py"),
                title="Pipeline Health", icon="🔧"),
    ],
})
pg.run()
