"""Backtest Studio — browse current-pipeline runs, C3-framed.

Promoted to the live nav 2026-07-18 (switch-over), replacing the previous run
browser. Differences (per
docs/session_logs/sprint_14/plans/dashboard_uplift/backtest_studio_page.md):
  1. C3 (exit-P&L) currency banner — Studio numbers are trade-level, not label-level.
  2. Engine column + vec-optimism caption on the run table.
  4. Single-Sharpe demoted: the per-run headline leads with annualized return and
     frames one run as a single start-time draw, not the edge.
The strategy cone (§3) reads the cone_cells cache and renders the start-date
distribution as the verdict, above the run browser. Selecting a cone cell drills
into that cell's local-only trades / exposure / rejections (§3 per-cell zoom) —
same detail as the run browser, one component entered two ways. Trades and
rejections stay dev-box-local (not synced to slim); the zoom degrades to a metric
+ exposure view on a host without the sweep tree.

Only renders runs whose manifest.json contains "manifest_version": "v1".
Tier 2 (workshop) — dense/mono, deliberately NOT theta-styled.
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
sys.path.insert(0, str(ROOT / "scripts"))  # so `import dashboard_utils` resolves

BACKTEST_DIR = ROOT / "data" / "backtest"

REGIME_LABELS = {
    1: "Strong Bear",
    2: "Bear",
    3: "Neutral",
    4: "Bull",
    5: "Strong Bull",
}

# Legacy runs (pre engine-tag) are all BackTrader — only SEPABacktestRunner /
# population_runner (also Cerebro) ever wrote data/backtest/. vec output never
# lands here. Default keeps the column honest for runs written before the tag.
DEFAULT_ENGINE = "BackTrader (assumed)"


# ── Run discovery ────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def discover_runs() -> pd.DataFrame:
    """Scan data/backtest/*/manifest.json, keep only manifest_version=v1."""
    rows = []
    if not BACKTEST_DIR.exists():
        return pd.DataFrame()  # not synced to this host (e.g. cloud) — caller shows info
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
        strategy = m.get("strategy") or "SEPAHybridV1 (assumed)"
        rows.append({
            "run_id": m.get("run_id", d.name),
            "dir": d.name,
            "created_at": m.get("created_at"),
            "engine": m.get("engine") or DEFAULT_ENGINE,
            "strategy": strategy,
            "fingerprint": m.get("fingerprint"),
            "description": m.get("description"),
            "model_name": model.get("name"),
            "model_version_id": model.get("version_id"),
            "start_date": params.get("start_date"),
            "end_date": params.get("end_date"),
            "initial_cash": params.get("initial_cash"),
            "total_return": summary.get("total_return"),
            "ann_return_pct": summary.get("ann_return_pct"),
            "sharpe_ratio": summary.get("sharpe_ratio"),
            "max_drawdown": summary.get("max_drawdown"),
            "total_trades": summary.get("total_trades"),
            "win_rate": summary.get("win_rate"),
            "_path": str(d),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Newest first. The scan is alphabetical, which put a May run at index 0 and
    # made the selectbox default to a stale run — every panel below the selector
    # then rendered that run.
    return df.sort_values("created_at", ascending=False, na_position="last") \
             .reset_index(drop=True)


def attach_sector(df: pd.DataFrame | None) -> pd.DataFrame | None:
    """Cone-cell trades.parquet carries only a ticker; the sweep writer never
    emitted sector/industry (the run-browser frames do, so this is a no-op there).
    Join at read — 2,850+ historical parquets make backfilling the writer the
    wrong end to fix it.

    ponytail: company_profiles is a CURRENT snapshot, so a 2005 trade is labelled
    with today's sector. Fine for filtering; if a point-in-time sector breakdown
    ever matters, the writer has to record it at trade time."""
    if df is None or df.empty or "ticker" not in df.columns or "sector" in df.columns:
        return df
    from dashboard_utils import load_ticker_sectors

    return df.merge(load_ticker_sectors(), on="ticker", how="left")


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
            out["trades"] = attach_sector(pd.read_parquet(trades_f))
        except OSError:
            pass

    equity_f = p / "equity_curve.parquet"
    if equity_f.exists():
        try:
            out["equity"] = pd.read_parquet(equity_f)
        except OSError:
            pass

    return out


# ── C3 currency banner ───────────────────────────────────────────────────────

def render_c3_banner() -> None:
    st.warning(
        "**Currency C3 · exit-P&L (trade-level).** Every number on this page is a "
        "realized trade result, not a label claim. A single run is **one start-date "
        "draw**, not the edge — the champion is start-time dependent, so the trade "
        "verdict is the **start-date cone** (coming, once cached), never one Sharpe. "
        "Label-level (C1) metrics live on the model card.",
        icon="🟠",
    )


# ── Per-cell zoom (local-only artifacts) ─────────────────────────────────────

SWEEP_ROOT = ROOT / "data" / "selection_sweep" / "starttime"


@st.cache_data(ttl=60)
def load_cell_artifacts(arm: str, grid: str, cell: str) -> dict:
    """Load one cone cell's local parquets. NOT in the slim DB — trades/rejections
    are a dev-box research activity (cone_and_studio_design.md §4). Returns {} keys
    None on a host without the sweep tree (e.g. cloud), so the zoom degrades."""
    d = SWEEP_ROOT / arm / grid / cell
    out: dict = {"dir": d, "trades": None, "rejections": None, "equity": None}
    for name, key in [("trades.parquet", "trades"),
                      ("rejections.parquet", "rejections"),
                      ("equity.parquet", "equity")]:
        f = d / name
        if f.exists():
            try:
                out[key] = pd.read_parquet(f)
            except OSError:
                pass
    out["trades"] = attach_sector(out["trades"])
    return out


@st.cache_data(ttl=300, show_spinner=False)
def load_arm_fan(arm: str, cells: tuple[tuple[str, str], ...]) -> pd.DataFrame:
    """Every cell's equity curve for one arm, normalized to 1.0 and aligned at
    day 0 — the strategy cone as a fan of paths.

    The cone scatter answers "what Sharpe would I have got", the fan answers
    "what would the ride have looked like". Same object, different projection.

    `cells` is a tuple so the result caches: the sweep tree is ~2.5k parquets and
    re-reading one arm's worth on every rerun is the expensive path.
    """
    frames = []
    for grid, cell in cells:
        f = SWEEP_ROOT / arm / grid / cell / "equity.parquet"
        if not f.exists():
            continue
        try:
            eq = pd.read_parquet(f, columns=["date", "value"])
        except (OSError, ValueError):
            continue
        # A 1-row cell has no path to draw (degenerate short window).
        if len(eq) < 2 or float(eq["value"].iloc[0]) <= 0:
            continue
        frames.append(pd.DataFrame({
            "cell": cell,
            "day": range(len(eq)),
            "nav": eq["value"].to_numpy() / float(eq["value"].iloc[0]),
        }))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def render_fan(arm: str, c: pd.DataFrame) -> None:
    """The fan: all start-date draws overlaid, aligned at entry.

    Individual paths are drawn thin and translucent — with 90-269 cells the
    readable signal is the DENSITY plus the median/decile bands, not any one
    curve. Bands are cross-sectional per day, so they are the cone's shape over
    holding time rather than a tradeable path.
    """
    # 2,892 objects, one blocking request each — pulled here, where the fan that
    # needs them is actually being drawn, rather than at page load (let alone at
    # app boot, where it used to be and never finished). No-op locally.
    from dashboard_utils import ensure_assets

    ensure_assets("sweep_starttime")

    cells = tuple(c[["grid", "cell"]].itertuples(index=False, name=None))
    fan = load_arm_fan(arm, cells)
    if fan.empty:
        st.info(f"No per-cell `equity.parquet` under `{SWEEP_ROOT.name}/{arm}/` — "
                "the sweep tree is dev-box-local, so the fan is blank on the remote.")
        return

    # Trim the long thin tail: past the point where few cells still run, the
    # bands are computed on a handful of curves and read as noise.
    per_day = fan.groupby("day")["cell"].size()
    n_cells = int(fan["cell"].nunique())
    keep = per_day[per_day >= max(3, n_cells * 0.1)].index.max()
    fan = fan[fan["day"] <= keep]

    q = (fan.groupby("day")["nav"]
            .quantile([0.1, 0.5, 0.9]).unstack()
            .rename(columns={0.1: "p10", 0.5: "p50", 0.9: "p90"}))

    fig = go.Figure()
    for _, g in fan.groupby("cell", sort=False):
        fig.add_scatter(x=g["day"], y=g["nav"], mode="lines",
                        line=dict(color="rgba(31,119,180,0.13)", width=1),
                        hoverinfo="skip", showlegend=False)
    fig.add_scatter(x=q.index, y=q["p90"], mode="lines", name="p90",
                    line=dict(color="#2e7d32", width=1, dash="dot"))
    fig.add_scatter(x=q.index, y=q["p10"], mode="lines", name="p10",
                    line=dict(color="#c62828", width=1, dash="dot"),
                    fill="tonexty", fillcolor="rgba(31,119,180,0.10)")
    fig.add_scatter(x=q.index, y=q["p50"], mode="lines", name="median",
                    line=dict(color="#1f77b4", width=2.5))
    fig.add_hline(y=1.0, line=dict(color="#999", width=1))
    fig.update_layout(
        title=f"Equity fan — {arm} ({n_cells} start-date draws, aligned at entry)",
        height=420, xaxis_title="Trading days from entry",
        yaxis_title="NAV (×start)", margin=dict(l=40, r=20, t=50, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=1, xanchor="right"),
    )
    st.plotly_chart(fig, width='stretch')

    end = fan.sort_values("day").groupby("cell")["nav"].last()
    st.caption(
        f"Each faint line is one start date's equity curve, normalized to 1.0 and "
        f"aligned at day 0 — the same {n_cells} draws the scatter above scores. "
        f"Bands are the per-day 10th/50th/90th percentile **across cells**, not a "
        f"path any single run took. Final NAV: median {end.median():.2f}×, "
        f"{(end < 1).mean() * 100:.0f}% of draws end below water. "
        f"Truncated at day {int(keep)} (where <10% of cells still run)."
    )


def _bear_spans(eq: pd.DataFrame) -> list[tuple]:
    """Consecutive bear-regime bars (regime 1-2) collapsed to (start, end) date
    spans, for vrect shading. Empty if the cell never went bear."""
    is_bear = eq["regime"].isin([1, 2]).to_numpy()
    spans, start = [], None
    dates = eq["date"].to_numpy()
    for i, b in enumerate(is_bear):
        if b and start is None:
            start = dates[i]
        elif not b and start is not None:
            spans.append((start, dates[i]))
            start = None
    if start is not None:
        spans.append((start, dates[-1]))
    return spans


def render_exposure(equity: pd.DataFrame) -> None:
    """Position count + cash over time — what the equity curve hides. A flat NAV
    stretch is 'no positions', not a losing hold; this separates the two."""
    if equity is None or equity.empty:
        st.info("No equity artifact for this cell.")
        return
    eq = equity.copy()
    eq["date"] = pd.to_datetime(eq["date"])

    fig = go.Figure()
    fig.add_scatter(x=eq["date"], y=eq["position_count"], mode="lines",
                    line=dict(color="#1f77b4", width=1.5), name="positions",
                    fill="tozeroy", fillcolor="rgba(31,119,180,0.15)")
    # Shade bear-regime spans (regime 1-2) — is a flat exposure stretch a cash-out
    # in a bear tape, or a dry spell in a bull one? The per-bar regime answers it.
    if "regime" in eq.columns:
        for lo, hi in _bear_spans(eq):
            fig.add_vrect(x0=lo, x1=hi, fillcolor="rgba(198,40,40,0.10)",
                          line_width=0, layer="below")
    fig.update_layout(
        title="Exposure — open positions over time (bear regime shaded)",
        height=220, yaxis_title="# open", margin=dict(l=40, r=20, t=40, b=20),
    )
    st.plotly_chart(fig, width='stretch')

    # Cash vs deployed capital — the same story in dollars.
    fig_c = go.Figure()
    fig_c.add_scatter(x=eq["date"], y=eq["cash"], mode="lines", name="cash",
                      stackgroup="one", line=dict(width=0.5, color="#999"))
    fig_c.add_scatter(x=eq["date"], y=eq["position_value"], mode="lines",
                      name="deployed", stackgroup="one",
                      line=dict(width=0.5, color="#2e7d32"))
    fig_c.update_layout(
        title="Cash vs deployed capital",
        height=220, yaxis_title="$", margin=dict(l=40, r=20, t=40, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=1, xanchor="right"),
    )
    st.plotly_chart(fig_c, width='stretch')


def render_pnl_distribution(trades: pd.DataFrame) -> None:
    if trades is None or trades.empty or "pnl_percent" not in trades.columns:
        return
    pnl = trades["pnl_percent"].dropna()
    fig = go.Figure()
    fig.add_histogram(x=pnl, nbinsx=40, marker_color="#1f77b4")
    fig.add_vline(x=0, line=dict(color="#999", width=1))
    fig.add_vline(x=float(pnl.median()), line=dict(color="#2e7d32", dash="dash"),
                  annotation_text=f"median {pnl.median():+.1f}%")
    fig.update_layout(
        title=f"Per-trade P&L — {len(pnl)} trades, "
              f"{(pnl > 0).mean() * 100:.0f}% winners",
        height=260, xaxis_title="P&L %", yaxis_title="# trades",
        margin=dict(l=40, r=20, t=50, b=30),
    )
    st.plotly_chart(fig, width='stretch')


def render_rejections(rejections: pd.DataFrame) -> None:
    """Rejections are ~125k rows — summarize by reason, never dump raw. Slot-refill
    is path-dependent (feedback_rerun_dont_postfilter): this shows WHY slots didn't
    fill, not a counterfactual of what a different gate would have bought."""
    if rejections is None or rejections.empty:
        st.info("No rejections artifact for this cell.")
        return
    r = rejections.copy()
    by_reason = (r.groupby("reason")
                  .agg(count=("ticker", "size"),
                       distinct_tickers=("ticker", "nunique"),
                       median_score=("score", "median"))
                  .reset_index()
                  .sort_values("count", ascending=False))
    styled = by_reason.style.format({
        "count": "{:,.0f}", "distinct_tickers": "{:,.0f}", "median_score": "{:.1f}",
    })
    st.dataframe(styled, width='stretch', hide_index=True)
    st.caption(f"{len(r):,} rejection rows across {r['ticker'].nunique():,} tickers "
               f"and {r['date'].nunique():,} days. Grouped by reason — not the "
               "counterfactual of a different gate (slot-refill is path-dependent).")


def render_cell_zoom(cell_rows: pd.DataFrame) -> None:
    """Drill into one cone cell's trades / exposure / rejections. Same detail as the
    run browser, entered from the cone (design §3: one detail, two ways in)."""
    st.subheader("Zoom into a cell")
    st.caption("Each cell is one start-date draw from the arm selected above. "
               "Trades and rejections are local-only (dev box), not synced to "
               "the remote.")

    # Label carries the grid: an arm mixes rolling (start-date draws, fixed 12m),
    # horizon (varying holding period), and matrix cells — a bare start date would
    # conflate them. Sharpe suffixed so the picker previews the draw.
    def _label(row) -> str:
        sh = f" · Sharpe {row.sharpe:.2f}" if pd.notna(row.sharpe) else ""
        return f"[{row.grid}] {row.start} · {row.cell}{sh}"
    labels = {_label(row): (row.arm, row.grid, row.cell)
              for row in cell_rows.itertuples()}

    # Key the widget on the ARM. Streamlit restores a selectbox's previous value
    # by key, so a shared key survives an arm switch and keeps pointing at the old
    # arm's cell — which then loads a path that doesn't exist under the new arm
    # (champion_gated has no `horizon` grid at all). Silent wrong-arm data.
    pick = st.selectbox("Cell (start date)", list(labels.keys()),
                        key=f"btv2_cell_zoom_{cell_rows['arm'].iloc[0]}")
    arm, grid, cell = labels[pick]

    art = load_cell_artifacts(arm, grid, cell)
    if art["trades"] is None and art["equity"] is None:
        st.info(f"No local artifacts for `{arm}/{grid}/{cell}` — the sweep tree "
                "isn't on this host (trades/rejections stay dev-box-local).")
        return

    # A cell that never traded has a single equity row (start bar only). Charting
    # one point renders an epoch-scaled axis and reads as broken data — it isn't,
    # the draw just deployed no capital. Same len<2 rule load_arm_fan drops on.
    eq = art["equity"]
    if eq is not None and len(eq) < 2:
        st.info(f"`{cell}` never opened a position — the window closed before any "
                "signal fired, so there is no path to chart. This is a real (zero-"
                "trade) draw, not missing data.")
        return

    render_exposure(art["equity"])
    render_pnl_distribution(art["trades"])
    render_breakdowns(art["trades"])
    render_trade_table(art["trades"], key_prefix="btv2_cell")
    with st.expander("Rejections — why slots didn't fill"):
        render_rejections(art["rejections"])


# ── Strategy cone (the verdict, promoted above the run browser) ──────────────

def render_cone() -> None:
    """The start-date distribution for a chosen arm — the trade verdict.

    One run is one draw; the cone is the whole sweep. Median/floor/%neg is the
    promotion answer, NOT any single Sharpe. Reads cone_cells (build_cone_cache.py).
    """
    from dashboard_utils import load_cone_cells

    st.subheader("Strategy Cone — start-date distribution (the verdict)")

    try:
        allc = load_cone_cells()
    except Exception as e:  # table absent on this host (dev-box-only sweep source)
        st.info(f"No `cone_cells` table — run `python scripts/build_cone_cache.py`. ({e})")
        return
    if allc.empty:
        st.info("`cone_cells` is empty — run a sweep, then `build_cone_cache.py`.")
        return

    arms = sorted(allc["arm"].unique().tolist())
    default = arms.index("champion") if "champion" in arms else 0
    arm = st.selectbox("Strategy arm", arms, index=default, key="btv2_cone_arm")
    c = allc[allc["arm"] == arm].sort_values("start")

    if c.empty:
        st.info("No cells for this arm.")
        return

    # The cone verdict: robust stats across start dates, not one draw.
    sharpe = c["sharpe"].dropna()
    med = float(sharpe.median())
    floor = float(sharpe.min())
    pct_neg = float((sharpe < 0).mean() * 100)
    med_calmar = float((c["ann_return"] / c["max_drawdown"].abs()).replace(
        [np.inf, -np.inf], np.nan).dropna().median()) if len(c) else float("nan")

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Median Sharpe", f"{med:.2f}", help="Across all start dates — the cone verdict, not a single run.")
    m2.metric("Floor (worst)", f"{floor:.2f}", help="Worst start-date Sharpe. The cone's downside, not an average.")
    m3.metric("% Negative", f"{pct_neg:.0f}%", help="Share of start dates with a negative Sharpe.")
    m4.metric("Median Calmar", f"{med_calmar:.2f}" if med_calmar == med_calmar else "—")
    m5.metric("Cells (draws)", f"{len(c):,}")

    scale = c["score_scale"].iloc[0]
    st.caption(f"Engine: `{c['engine'].iloc[0]}` · score scale: `{scale}` · "
               f"{len(c)} start-date draws. The **gate value's meaning depends on "
               f"this scale** (raw ~0.55 vs calibrated ~0.12 median) — read it, don't assume.")

    # Sharpe over start-date: the spaghetti the design doc asked for, as a scatter
    # with the median/floor rules. Each point is a start-date draw.
    cc = c.dropna(subset=["sharpe"]).copy()
    cc["start_dt"] = pd.to_datetime(cc["start"])
    fig = go.Figure()
    fig.add_scatter(x=cc["start_dt"], y=cc["sharpe"], mode="markers",
                    marker=dict(size=6, color="#1f77b4"), name="per start-date Sharpe")
    fig.add_hline(y=med, line=dict(color="#2e7d32", dash="dash"),
                  annotation_text=f"median {med:.2f}", annotation_position="right")
    fig.add_hline(y=0, line=dict(color="#999", width=1))
    fig.add_hline(y=floor, line=dict(color="#c62828", dash="dot"),
                  annotation_text=f"floor {floor:.2f}", annotation_position="right")
    fig.update_layout(
        title=f"Sharpe by start date — {arm} (each point = one draw)",
        height=340, xaxis_title="Start date", yaxis_title="Sharpe",
        margin=dict(l=40, r=80, t=50, b=30), showlegend=False,
    )
    st.plotly_chart(fig, width='stretch')

    # The fan — the same draws as equity paths rather than scored points. This is
    # the plot the cone was missing: the scatter says what each draw scored, the
    # fan says what the ride looked like.
    render_fan(arm, c)

    # Distribution of the same Sharpes — the cone as a histogram.
    fig_h = go.Figure()
    fig_h.add_histogram(x=cc["sharpe"], nbinsx=30, marker_color="#1f77b4")
    fig_h.add_vline(x=med, line=dict(color="#2e7d32", dash="dash"))
    fig_h.add_vline(x=0, line=dict(color="#999", width=1))
    fig_h.update_layout(
        title="Sharpe distribution across start dates",
        height=260, xaxis_title="Sharpe", yaxis_title="# start dates",
        margin=dict(l=40, r=20, t=50, b=30),
    )
    st.plotly_chart(fig_h, width='stretch')

    # Drill into any cell of this arm — same detail as the run browser, entered
    # from the cone (design §3: one detail component, two ways in).
    st.markdown("---")
    render_cell_zoom(c)


# ── Run list panel ───────────────────────────────────────────────────────────

def render_run_list(runs: pd.DataFrame, cone_cells: pd.DataFrame) -> Optional[str]:
    st.subheader("Backtest Runs — raw manifests")

    if runs.empty:
        st.warning("No runs with `manifest_version=v1` found in `data/backtest/`. "
                   "Re-run a backtest with the current pipeline to populate.")
        return None

    # 119 of the 121 v1 runs ARE cone cells written by the same sweep — same
    # run_id, same window. They are NOT an independent result set, and their
    # metrics DISAGREE with the cone (h_start_h6: manifest Sharpe 2.76 vs cone
    # 4.86) because build_cone_cache.py reads the arm's curated summary.json,
    # which carries the window-fair annualization; the per-run manifest carries
    # the raw BackTrader figure. The cone is authoritative — say so here rather
    # than let two different Sharpes for one run sit on the page unexplained.
    overlap = sorted(set(runs["run_id"]) & set(cone_cells["cell"])) if not cone_cells.empty else []
    if overlap:
        st.warning(
            f"⚠️ **{len(overlap)} of these {len(runs)} runs are sweep cells already "
            "scored in the cone above** — same run, re-derived. Where the two "
            "disagree the **cone wins**: it reads each arm's curated `summary.json` "
            "(window-fair annualization, degenerate short-window cells filtered), "
            "while these manifests carry the raw per-run BackTrader metrics. Use "
            "this table to inspect a run's artifacts, **not to score it**.",
            icon="⚠️",
        )

    show = runs[["run_id", "engine", "strategy", "model_name", "model_version_id",
                 "start_date", "end_date",
                 "total_return", "ann_return_pct", "max_drawdown",
                 "total_trades", "win_rate", "sharpe_ratio", "created_at"]].copy()
    rename = {
        "run_id": "Run", "engine": "Engine", "strategy": "Strategy",
        "model_name": "Model", "model_version_id": "Version",
        "start_date": "Start", "end_date": "End",
        "total_return": "Total Ret %", "ann_return_pct": "Ann Ret %",
        "max_drawdown": "Max DD %", "total_trades": "Trades",
        "win_rate": "Win %",
        "sharpe_ratio": "Sharpe (draw)",  # demoted: last column, flagged as a single draw
        "created_at": "Created",
    }
    show = show.rename(columns=rename)

    styled = show.style
    for c in ["Total Ret %", "Ann Ret %", "Max DD %", "Win %", "Sharpe (draw)"]:
        if c in show.columns:
            styled = styled.format("{:.2f}", subset=[c], na_rep="—")
    if "Trades" in show.columns:
        styled = styled.format("{:,.0f}", subset=["Trades"], na_rep="—")

    st.dataframe(styled, width='stretch', hide_index=True, height=200)

    if (runs["engine"].astype(str).str.startswith("BackTrader")).all():
        st.caption("All runs here are **BackTrader** (the promotion engine). "
                   "Vectorized runs — median Sharpe ~1.51 vs BackTrader ~0.35 on the "
                   "same config — are **ranking-only optimistic** and are not published "
                   "to this Studio; promote on BackTrader only.")
    else:
        st.caption("⚠️ **Vectorized runs are ranking-only optimistic** (median Sharpe "
                   "~1.51 vs BackTrader ~0.35 same config). Promote on BackTrader only.")

    selected = st.selectbox("Select run", runs["run_id"].tolist(), key="btv2_selected")
    return selected


# ── Per-run rendering ────────────────────────────────────────────────────────

def _date_indexed(equity: pd.DataFrame) -> pd.DataFrame:
    """Equity parquets carry a `date` COLUMN over a RangeIndex. Converting that
    RangeIndex with to_datetime silently reads 0,1,2… as nanoseconds since epoch —
    the Jan-1-1970 axis. Prefer the column; only fall back to the index."""
    eq = equity.copy()
    if "date" in eq.columns:
        eq.index = pd.to_datetime(eq["date"])
    elif not isinstance(eq.index, pd.DatetimeIndex):
        eq.index = pd.to_datetime(eq.index)
    return eq.sort_index()


def render_equity_dd(equity: pd.DataFrame, run_id: str) -> None:
    if equity is None or equity.empty:
        st.info("No equity curve data.")
        return

    eq = _date_indexed(equity)

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
    st.plotly_chart(fig, width='stretch')

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
    st.plotly_chart(fig_dd, width='stretch')


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
        st.dataframe(styled, width='stretch', hide_index=True, height=240)

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
            st.dataframe(styled, width='stretch', hide_index=True, height=240)
        else:
            st.info("No entry_regime column in trades.")


def render_trade_table(trades: pd.DataFrame, key_prefix: str = "btv2") -> None:
    # key_prefix disambiguates the filter widgets: this renders from both the run
    # browser and the cell zoom on the same page, so fixed keys would collide.
    if trades is None or trades.empty:
        return

    st.markdown("**Trades**")
    t = trades.copy()

    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        outcome = st.selectbox("Outcome", ["All", "Winners (>0)", "Losers (<=0)"],
                               index=0, key=f"{key_prefix}_outcome")
    with fc2:
        sectors = ["All"]
        if "sector" in t.columns:
            sectors += sorted(t["sector"].dropna().unique().tolist())
        sector = st.selectbox("Sector", sectors, key=f"{key_prefix}_sector")
    with fc3:
        exit_reasons = ["All"]
        if "exit_reason" in t.columns:
            exit_reasons += sorted(t["exit_reason"].dropna().unique().tolist())
        reason = st.selectbox("Exit reason", exit_reasons, key=f"{key_prefix}_reason")

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

    st.dataframe(styled, width='stretch', height=360)
    st.caption(f"Showing {len(show):,} of {len(trades):,} trades")


# ── Fingerprint glossary ─────────────────────────────────────────────────────

def render_fingerprint_glossary(fingerprint: str) -> None:
    """Decode the X1/X4/S0… components of a fingerprint into a plain-English table."""
    from src.backtest.strategy_registry import KNOB_GLOSSARY

    families = [f for f in KNOB_GLOSSARY if any(
        c.startswith(f) for c in fingerprint.split("_"))]
    if not families:
        return
    gloss = pd.DataFrame(
        [{"Term": f, "Meaning": KNOB_GLOSSARY[f]} for f in families])
    with st.expander(f"What the terms mean — `{fingerprint}`"):
        st.dataframe(gloss, width='stretch', hide_index=True)


# ── Compare mode ─────────────────────────────────────────────────────────────

def render_compare(runs: pd.DataFrame, primary_run_id: str) -> None:
    st.markdown("---")
    st.subheader("Compare")
    other_options = [r for r in runs["run_id"].tolist() if r != primary_run_id]
    if not other_options:
        st.info("Only one v1 run available — nothing to compare against yet.")
        return

    other = st.selectbox("Compare with", other_options, key="btv2_compare")
    align = st.radio("X axis", ["Absolute date", "Days from start"], horizontal=True, key="btv2_align")

    rows = []
    for rid in [primary_run_id, other]:
        run_row = runs[runs["run_id"] == rid].iloc[0]
        art = load_run_artifacts(run_row["_path"])
        eq = art["equity"]
        if eq is None or eq.empty:
            continue
        eq = _date_indexed(eq)
        nav = eq["value"] / float(eq["value"].iloc[0])
        if align == "Days from start":
            x = np.arange(len(nav))
        else:
            x = nav.index
        rows.append((rid, x, nav.values))

    if len(rows) < 2:
        st.info("Could not load both equity curves.")
        return

    # Two runs whose windows both got truncated by the data frontier produce the
    # SAME path under different nominal horizons (h6 vs h24 both end at the last
    # bar). Overplotted, that reads as one curve — say so rather than let the user
    # infer two horizons agreed.
    if np.array_equal(rows[0][2], rows[1][2]):
        st.warning(
            f"⚠️ `{primary_run_id}` and `{other}` have **identical** equity paths — "
            "both windows were cut short by the end of available data, so the "
            "nominal horizons never diverged. This is one draw shown twice, not "
            "two horizons agreeing.", icon="🟠")

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
    st.plotly_chart(fig, width='stretch')

    side = runs[runs["run_id"].isin([primary_run_id, other])][
        ["run_id", "engine", "model_name", "model_version_id",
         "total_return", "ann_return_pct", "max_drawdown", "total_trades",
         "win_rate", "sharpe_ratio"]
    ].set_index("run_id").T
    st.dataframe(side, width='stretch')


# ── Page entrypoint ──────────────────────────────────────────────────────────

st.title("Backtest Studio")
render_c3_banner()
st.caption("Showing only runs with `manifest_version=v1`. Older runs in "
           "`data/backtest/` remain on disk but are hidden here.")

# Section 1 (verdict-first): the cone is the trade verdict; the run browser below
# drills into individual draws.
render_cone()
st.markdown("---")

runs = discover_runs()
try:
    from dashboard_utils import load_cone_cells as _lcc
    _cone_cells = _lcc()
except Exception:
    _cone_cells = pd.DataFrame(columns=["cell"])
selected = render_run_list(runs, _cone_cells)
if selected is None:
    st.stop()

st.markdown("---")
run_row = runs[runs["run_id"] == selected].iloc[0]
art = load_run_artifacts(run_row["_path"])

st.subheader(f"📊 {selected}")
st.caption("⚠️ **One run = one start-date draw.** These per-run metrics describe a "
           "single window, not the strategy's edge. The edge is the start-date cone.")

# Headline leads with annualized return (window-fair), NOT Sharpe. Sharpe is
# demoted to a flagged single-draw metric at the end of the row.
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Ann Return", f"{run_row['ann_return_pct']:.1f}%" if pd.notna(run_row.get("ann_return_pct")) else "—",
          help="Annualized — the window-fair metric across different-length runs.")
c2.metric("Total Return", f"{run_row['total_return']:.2f}%" if pd.notna(run_row["total_return"]) else "—")
c3.metric("Max DD", f"{run_row['max_drawdown']:.2f}%" if pd.notna(run_row["max_drawdown"]) else "—")
c4.metric("Trades", f"{int(run_row['total_trades']):,}" if pd.notna(run_row["total_trades"]) else "—")
c5.metric("Sharpe (draw)", f"{run_row['sharpe_ratio']:.2f}" if pd.notna(run_row["sharpe_ratio"]) else "—",
          help="ONE start-date draw, not the verdict — the champion is start-time "
               "dependent. Read the start-date cone, not this number.")

fingerprint = run_row.get("fingerprint")
tag = f" · `{fingerprint}`" if fingerprint else ""
st.caption(f"Engine: `{run_row['engine']}` · Strategy: `{run_row['strategy']}`{tag} · "
           f"Model: `{run_row['model_version_id']}` · "
           f"Window: {run_row['start_date']} → {run_row['end_date']} · "
           f"Cash: ${run_row['initial_cash']:,.0f}")

if run_row.get("description"):
    st.info(run_row["description"])
if fingerprint:
    render_fingerprint_glossary(fingerprint)

plot_png = Path(run_row["_path"]) / "plot.png"
if plot_png.exists():
    with st.expander("6-panel diagnostic (equity/regime · underwater · monthly · per-trade · by-regime · exits)", expanded=True):
        st.image(str(plot_png), width='stretch')

render_equity_dd(art["equity"], selected)
st.markdown("---")
render_breakdowns(art["trades"])
st.markdown("---")
render_trade_table(art["trades"])
render_compare(runs, selected)
