"""Backtest Studio — browse current-pipeline runs.

Only renders runs whose manifest.json contains "manifest_version": "v1".
Stale pre-v1 runs remain on disk but are silently hidden.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

BACKTEST_DIR = ROOT / "data" / "backtest"

REGIME_LABELS = {
    1: "Strong Bear",
    2: "Bear",
    3: "Neutral",
    4: "Bull",
    5: "Strong Bull",
}


# ── Run discovery ────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def discover_runs() -> pd.DataFrame:
    """Scan data/backtest/*/manifest.json, keep only manifest_version=v1."""
    rows = []
    for d in sorted(BACKTEST_DIR.iterdir()):
        if not d.is_dir():
            continue
        manifest_path = d / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            m = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if m.get("manifest_version") != "v1":
            continue
        summary = m.get("summary_metrics", {})
        model = m.get("model", {})
        params = m.get("params", {})
        rows.append({
            "run_id": m.get("run_id", d.name),
            "dir": d.name,
            "created_at": m.get("created_at"),
            "model_name": model.get("name"),
            "model_version_id": model.get("version_id"),
            "start_date": params.get("start_date"),
            "end_date": params.get("end_date"),
            "initial_cash": params.get("initial_cash"),
            "total_return": summary.get("total_return"),
            "sharpe_ratio": summary.get("sharpe_ratio"),
            "max_drawdown": summary.get("max_drawdown"),
            "total_trades": summary.get("total_trades"),
            "win_rate": summary.get("win_rate"),
            "_path": str(d),
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=60)
def load_run_artifacts(run_dir: str) -> dict:
    p = Path(run_dir)
    out: dict = {"manifest": None, "metrics": None, "trades": None, "equity": None}

    for name, key in [("manifest.json", "manifest"), ("metrics.json", "metrics")]:
        f = p / name
        if f.exists():
            try:
                out[key] = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass

    trades_f = p / "trades.parquet"
    if trades_f.exists():
        try:
            out["trades"] = pd.read_parquet(trades_f)
        except OSError:
            pass

    equity_f = p / "equity_curve.parquet"
    if equity_f.exists():
        try:
            out["equity"] = pd.read_parquet(equity_f)
        except OSError:
            pass

    return out


# ── Run list panel ───────────────────────────────────────────────────────────

def render_run_list(runs: pd.DataFrame) -> Optional[str]:
    st.subheader("Backtest Runs")

    if runs.empty:
        st.warning("No runs with `manifest_version=v1` found in `data/backtest/`. "
                   "Re-run a backtest with the current pipeline to populate.")
        return None

    show = runs[["run_id", "model_name", "model_version_id",
                 "start_date", "end_date",
                 "total_return", "sharpe_ratio", "max_drawdown",
                 "total_trades", "win_rate", "created_at"]].copy()
    rename = {
        "run_id": "Run", "model_name": "Model",
        "model_version_id": "Version",
        "start_date": "Start", "end_date": "End",
        "total_return": "Total Ret %", "sharpe_ratio": "Sharpe",
        "max_drawdown": "Max DD %", "total_trades": "Trades",
        "win_rate": "Win %", "created_at": "Created",
    }
    show = show.rename(columns=rename)

    styled = show.style
    for c in ["Total Ret %", "Sharpe", "Max DD %", "Win %"]:
        if c in show.columns:
            styled = styled.format("{:.2f}", subset=[c], na_rep="—")
    if "Trades" in show.columns:
        styled = styled.format("{:,.0f}", subset=["Trades"], na_rep="—")

    st.dataframe(styled, use_container_width=True, hide_index=True, height=200)

    selected = st.selectbox("Select run", runs["run_id"].tolist(), key="bt_selected")
    return selected


# ── Per-run rendering ────────────────────────────────────────────────────────

def render_equity_dd(equity: pd.DataFrame, run_id: str) -> None:
    if equity is None or equity.empty:
        st.info("No equity curve data.")
        return

    eq = equity.copy()
    if not isinstance(eq.index, pd.DatetimeIndex):
        eq.index = pd.to_datetime(eq.index)

    nav = eq["value"] / float(eq["value"].iloc[0])
    drawdown = nav / nav.cummax() - 1
    max_dd = float(drawdown.min())
    max_dd_date = drawdown.idxmin()

    fig = go.Figure()
    fig.add_scatter(x=eq.index, y=nav, mode="lines", name=run_id,
                    line=dict(color="#1f77b4", width=2))
    fig.update_layout(
        title=f"Equity Curve (start=1.0) — final {nav.iloc[-1]:.2f}x",
        height=380, xaxis_title="", yaxis_title="NAV (×start)",
        margin=dict(l=40, r=20, t=50, b=30),
    )
    st.plotly_chart(fig, use_container_width=True)

    fig_dd = go.Figure()
    fig_dd.add_scatter(x=drawdown.index, y=drawdown, mode="lines",
                       fill="tozeroy", line=dict(color="#c62828", width=1),
                       fillcolor="rgba(198,40,40,0.25)", name="Drawdown")
    fig_dd.add_annotation(x=max_dd_date, y=max_dd,
                          text=f"max DD {max_dd:.1%}<br>{max_dd_date:%Y-%m-%d}",
                          showarrow=True, arrowhead=2, ay=-30)
    fig_dd.update_layout(
        title="Drawdown",
        height=260, yaxis_tickformat=".0%",
        margin=dict(l=40, r=20, t=50, b=30),
    )
    st.plotly_chart(fig_dd, use_container_width=True)


def render_breakdowns(trades: pd.DataFrame) -> None:
    if trades is None or trades.empty:
        st.info("No trades data.")
        return

    t = trades.copy()
    t["entry_date"] = pd.to_datetime(t["entry_date"])
    t["year"] = t["entry_date"].dt.year

    col_yr, col_reg = st.columns(2)

    with col_yr:
        yearly = t.groupby("year").agg(
            trades=("pnl_percent", "count"),
            avg_pnl=("pnl_percent", "mean"),
            median_pnl=("pnl_percent", "median"),
            win_rate=("pnl_percent", lambda s: (s > 0).mean() * 100),
        ).reset_index()
        st.markdown("**Per-year**")
        styled = yearly.style.format({
            "avg_pnl": "{:+.2f}%", "median_pnl": "{:+.2f}%",
            "win_rate": "{:.0f}%", "trades": "{:,.0f}",
        })
        st.dataframe(styled, use_container_width=True, hide_index=True, height=240)

    with col_reg:
        if "entry_regime" in t.columns:
            t["regime_label"] = t["entry_regime"].map(REGIME_LABELS).fillna(
                t["entry_regime"].astype(str))
            regime = t.groupby("regime_label").agg(
                trades=("pnl_percent", "count"),
                avg_pnl=("pnl_percent", "mean"),
                win_rate=("pnl_percent", lambda s: (s > 0).mean() * 100),
            ).reset_index()
            st.markdown("**Per-regime (entry)**")
            styled = regime.style.format({
                "avg_pnl": "{:+.2f}%", "win_rate": "{:.0f}%",
                "trades": "{:,.0f}",
            })
            st.dataframe(styled, use_container_width=True, hide_index=True, height=240)
        else:
            st.info("No entry_regime column in trades.")


def render_trade_table(trades: pd.DataFrame) -> None:
    if trades is None or trades.empty:
        return

    st.markdown("**Trades**")
    t = trades.copy()

    # Filters
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        outcome = st.selectbox("Outcome", ["All", "Winners (>0)", "Losers (<=0)"], index=0)
    with fc2:
        sectors = ["All"]
        if "sector" in t.columns:
            sectors += sorted(t["sector"].dropna().unique().tolist())
        sector = st.selectbox("Sector", sectors, key="bt_sector")
    with fc3:
        exit_reasons = ["All"]
        if "exit_reason" in t.columns:
            exit_reasons += sorted(t["exit_reason"].dropna().unique().tolist())
        reason = st.selectbox("Exit reason", exit_reasons, key="bt_reason")

    if outcome == "Winners (>0)":
        t = t[t["pnl_percent"] > 0]
    elif outcome == "Losers (<=0)":
        t = t[t["pnl_percent"] <= 0]
    if sector != "All" and "sector" in t.columns:
        t = t[t["sector"] == sector]
    if reason != "All" and "exit_reason" in t.columns:
        t = t[t["exit_reason"] == reason]

    cols = ["ticker", "entry_date", "exit_date", "entry_price", "exit_price",
            "pnl_percent", "holding_days", "exit_reason", "entry_regime",
            "sector", "industry"]
    available = [c for c in cols if c in t.columns]
    show = t[available].copy()
    if "entry_regime" in show.columns:
        show["entry_regime"] = show["entry_regime"].map(REGIME_LABELS).fillna(
            show["entry_regime"].astype(str))
    rename = {
        "ticker": "Ticker", "entry_date": "Entry", "exit_date": "Exit",
        "entry_price": "Entry $", "exit_price": "Exit $",
        "pnl_percent": "PnL %", "holding_days": "Days",
        "exit_reason": "Reason", "entry_regime": "Regime",
        "sector": "Sector", "industry": "Industry",
    }
    show = show.rename(columns={k: v for k, v in rename.items() if k in show.columns})

    styled = show.style
    if "PnL %" in show.columns:
        def color_pnl(v):
            if pd.isna(v):
                return ""
            return f"color: {'#2e7d32' if v >= 0 else '#c62828'}"
        styled = styled.map(color_pnl, subset=["PnL %"]).format("{:+.2f}%", subset=["PnL %"])
    for c in ["Entry $", "Exit $"]:
        if c in show.columns:
            styled = styled.format("${:.2f}", subset=[c])

    st.dataframe(styled, use_container_width=True, height=360)
    st.caption(f"Showing {len(show):,} of {len(trades):,} trades")


# ── Compare mode ─────────────────────────────────────────────────────────────

def render_compare(runs: pd.DataFrame, primary_run_id: str) -> None:
    st.markdown("---")
    st.subheader("Compare")
    other_options = [r for r in runs["run_id"].tolist() if r != primary_run_id]
    if not other_options:
        st.info("Only one v1 run available — nothing to compare against yet.")
        return

    other = st.selectbox("Compare with", other_options, key="bt_compare")
    align = st.radio("X axis", ["Absolute date", "Days from start"], horizontal=True, key="bt_align")

    rows = []
    for rid in [primary_run_id, other]:
        run_row = runs[runs["run_id"] == rid].iloc[0]
        art = load_run_artifacts(run_row["_path"])
        eq = art["equity"]
        if eq is None or eq.empty:
            continue
        eq = eq.copy()
        if not isinstance(eq.index, pd.DatetimeIndex):
            eq.index = pd.to_datetime(eq.index)
        nav = eq["value"] / float(eq["value"].iloc[0])
        if align == "Days from start":
            x = np.arange(len(nav))
        else:
            x = nav.index
        rows.append((rid, x, nav.values))

    if len(rows) < 2:
        st.info("Could not load both equity curves.")
        return

    fig = go.Figure()
    for rid, x, y in rows:
        fig.add_scatter(x=x, y=y, mode="lines", name=rid)
    fig.update_layout(
        title="Equity curves (start=1.0)",
        height=380, yaxis_title="NAV (×start)",
        xaxis_title="Days from start" if align == "Days from start" else "",
        margin=dict(l=40, r=20, t=50, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Side-by-side summary
    side = runs[runs["run_id"].isin([primary_run_id, other])][
        ["run_id", "model_name", "model_version_id",
         "total_return", "sharpe_ratio", "max_drawdown", "total_trades", "win_rate"]
    ].set_index("run_id").T
    st.dataframe(side, use_container_width=True)


# ── Page entrypoint ──────────────────────────────────────────────────────────

st.title("Backtest Studio")
st.caption("Showing only runs with `manifest_version=v1`. Older runs in "
           "`data/backtest/` remain on disk but are hidden here.")

runs = discover_runs()
selected = render_run_list(runs)
if selected is None:
    st.stop()

st.markdown("---")
run_row = runs[runs["run_id"] == selected].iloc[0]
art = load_run_artifacts(run_row["_path"])

st.subheader(f"📊 {selected}")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Return", f"{run_row['total_return']:.2f}%" if pd.notna(run_row["total_return"]) else "—")
c2.metric("Sharpe", f"{run_row['sharpe_ratio']:.2f}" if pd.notna(run_row["sharpe_ratio"]) else "—")
c3.metric("Max DD", f"{run_row['max_drawdown']:.2f}%" if pd.notna(run_row["max_drawdown"]) else "—")
c4.metric("Trades", f"{int(run_row['total_trades']):,}" if pd.notna(run_row["total_trades"]) else "—")
st.caption(f"Model: `{run_row['model_version_id']}` · "
           f"Window: {run_row['start_date']} → {run_row['end_date']} · "
           f"Cash: ${run_row['initial_cash']:,.0f}")

render_equity_dd(art["equity"], selected)
st.markdown("---")
render_breakdowns(art["trades"])
st.markdown("---")
render_trade_table(art["trades"])
render_compare(runs, selected)
