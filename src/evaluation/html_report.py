"""Self-contained HTML pre-training report.

One standalone .html file: plotly.js inlined (offline-viewable, no CDN, no
server), interactive charts, sortable-by-eye tables. Chart-first — prose is
captions, not the payload. Pure rendering: every figure is fed a DataFrame /
dataclass produced elsewhere (data_quality, feature_signal). No analysis here.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

logger = logging.getLogger(__name__)

# Minervini-ish palette, stable across charts so a class colour means the
# same thing everywhere.
CLASS_COLORS = {
    "Dud": "#9e9e9e",
    "Noise": "#42a5f5",
    "Solid": "#66bb6a",
    "Elite": "#ffa726",
}
ACCENT = "#1f77b4"
GRID = "rgba(0,0,0,0.08)"
_LAYOUT = dict(
    template="plotly_white",
    font=dict(family="Segoe UI, Helvetica, Arial, sans-serif", size=13),
    margin=dict(l=60, r=30, t=60, b=50),
)


def _fig_html(fig: go.Figure, *, first: bool) -> str:
    """Inline the plotly bundle once (first chart), CDN-free thereafter."""
    return pio.to_html(
        fig,
        include_plotlyjs="inline" if first else False,
        full_html=False,
        config={"displayModeBar": False, "displaylogo": False},
    )


def _df_table(df: pd.DataFrame, *, float_fmt: str = "{:.4f}") -> str:
    if df.empty:
        return "<p class='muted'>No rows.</p>"
    fmt = df.copy()
    for c in fmt.columns:
        if pd.api.types.is_float_dtype(fmt[c]):
            fmt[c] = fmt[c].map(lambda v: "" if pd.isna(v) else float_fmt.format(v))
    head = "".join(f"<th>{c}</th>" for c in fmt.columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{v}</td>" for v in row) + "</tr>"
        for row in fmt.itertuples(index=False, name=None)
    )
    return f"<table class='grid'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


# --- figures --------------------------------------------------------------

def _fig_return_horizons(stats: pd.DataFrame) -> Optional[go.Figure]:
    if stats.empty:
        return None
    fig = go.Figure()
    fig.add_bar(
        x=stats["horizon"], y=stats["avg_pct"], name="Mean %",
        marker_color=ACCENT, opacity=0.85,
    )
    fig.add_scatter(
        x=stats["horizon"], y=stats["median_pct"], name="Median %",
        mode="markers+lines", marker=dict(size=10, color="#d62728"),
    )
    fig.update_layout(
        title="Forward Return by Horizon (mean vs median, %)",
        yaxis_title="Return %", xaxis_title="Horizon", **_LAYOUT,
    )
    return fig


def _fig_weekly_activity(weekly: pd.DataFrame) -> Optional[go.Figure]:
    if weekly.empty:
        return None
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if "new_additions" in weekly.columns:
        fig.add_bar(
            x=weekly["week"], y=weekly["new_additions"],
            name="New SEPA additions / week",
            marker_color=ACCENT, opacity=0.55,
            secondary_y=False,
        )
    if "avg_daily_active" in weekly.columns:
        fig.add_scatter(
            x=weekly["week"], y=weekly["avg_daily_active"],
            name="Avg daily active tickers", mode="lines",
            line=dict(color="#d62728", width=2),
            secondary_y=True,
        )
    fig.update_layout(
        title="Weekly SEPA Activity",
        xaxis_title="Week (ISO, Fri-ending)", **_LAYOUT,
    )
    fig.update_yaxes(title_text="New additions", secondary_y=False)
    fig.update_yaxes(title_text="Avg daily active", secondary_y=True)
    return fig


def _fig_mfe_hist(mfe: pd.Series) -> Optional[go.Figure]:
    s = pd.to_numeric(mfe, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if s.empty:
        return None
    # clip the long right tail for readability; note it in the caption
    hi = float(s.quantile(0.99))
    fig = go.Figure()
    fig.add_histogram(
        x=s.clip(upper=hi), nbinsx=80, marker_color=ACCENT, opacity=0.85,
    )
    fig.add_vline(
        x=float(s.median()), line=dict(color="#d62728", dash="dash"),
        annotation_text=f"median {s.median():.1f}%",
    )
    fig.update_layout(
        title="Raw MFE Distribution (max favourable excursion since watchlist add)",
        xaxis_title="MFE % (clipped at p99)", yaxis_title="Trades", **_LAYOUT,
    )
    return fig


def _fig_class_counts(counts: pd.Series, proportions: pd.Series) -> go.Figure:
    fig = go.Figure()
    fig.add_bar(
        x=list(counts.index), y=list(counts.values),
        marker_color=[CLASS_COLORS.get(c, ACCENT) for c in counts.index],
        text=[f"{p:.1%}" for p in proportions.values],
        textposition="outside",
    )
    fig.update_layout(
        title="Target Class Distribution (count, label = share)",
        xaxis_title="Class", yaxis_title="Trades", **_LAYOUT,
    )
    return fig


def _fig_days_active_density(days: pd.DataFrame) -> Optional[go.Figure]:
    if days.empty:
        return None
    cap = float(days["days_observed"].quantile(0.98))
    fig = go.Figure()
    for cls in ["Dud", "Noise", "Solid", "Elite"]:
        sub = days.loc[days["class"] == cls, "days_observed"]
        if sub.empty:
            continue
        fig.add_histogram(
            x=sub.clip(upper=cap), name=cls, histnorm="probability density",
            opacity=0.55, marker_color=CLASS_COLORS.get(cls, ACCENT), nbinsx=60,
        )
    fig.update_layout(
        barmode="overlay",
        title="Days Active Density by Class (days_observed, p98-clipped)",
        xaxis_title="Days active", yaxis_title="Density", **_LAYOUT,
    )
    return fig


def _fig_corr_heatmap(corr: pd.DataFrame, top: int = 40) -> Optional[go.Figure]:
    if corr is None or corr.empty:
        return None
    # rank features by total absolute off-diagonal correlation, keep top-N so
    # the heatmap stays legible on the 150+ feature matrix
    m = corr.copy()
    np.fill_diagonal(m.values, 0.0)
    order = m.abs().sum().sort_values(ascending=False).head(top).index.tolist()
    sub = corr.loc[order, order]
    fig = go.Figure(
        go.Heatmap(
            z=sub.values, x=sub.columns, y=sub.index,
            zmin=-1, zmax=1, colorscale="RdBu", reversescale=True,
            colorbar=dict(title="ρ"),
        )
    )
    fig.update_layout(
        title=f"Multicollinearity — Spearman ρ (top {len(order)} most-correlated features)",
        height=820, **{k: v for k, v in _LAYOUT.items() if k != "margin"},
        margin=dict(l=140, r=30, t=60, b=140),
    )
    fig.update_xaxes(tickangle=45, tickfont=dict(size=9))
    fig.update_yaxes(tickfont=dict(size=9))
    return fig


def _fig_bar(df: pd.DataFrame, value_col: str, title: str, n: int = 30) -> Optional[go.Figure]:
    if df is None or df.empty:
        return None
    sub = df.head(n).iloc[::-1]
    fig = go.Figure(
        go.Bar(
            x=sub[value_col], y=sub["feature"], orientation="h",
            marker=dict(
                color=sub[value_col],
                colorscale="Viridis",
            ),
        )
    )
    fig.update_layout(
        title=title, xaxis_title=value_col, height=max(420, 18 * len(sub)),
        **{k: v for k, v in _LAYOUT.items() if k != "margin"},
        margin=dict(l=180, r=30, t=60, b=50),
    )
    return fig


# --- assembler ------------------------------------------------------------

_CSS = """
body{font-family:'Segoe UI',Helvetica,Arial,sans-serif;margin:0;background:#fafbfc;color:#1a1a2e}
.wrap{max-width:1180px;margin:0 auto;padding:28px 32px 80px}
h1{font-size:26px;margin:0 0 4px}
h2{font-size:20px;margin:42px 0 6px;padding-top:14px;border-top:2px solid #e5e8ec}
.sub{color:#6b7280;font-size:13px;margin:0 0 18px}
.kpis{display:flex;gap:14px;flex-wrap:wrap;margin:18px 0 8px}
.kpi{background:#fff;border:1px solid #e5e8ec;border-radius:10px;padding:14px 18px;min-width:150px}
.kpi .v{font-size:22px;font-weight:600}
.kpi .l{font-size:12px;color:#6b7280;text-transform:uppercase;letter-spacing:.04em}
.pass{color:#1b873f}.fail{color:#cf222e}
.cap{color:#6b7280;font-size:13px;margin:4px 0 24px}
.muted{color:#9ca3af;font-style:italic}
table.grid{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0 26px}
table.grid th{background:#f1f3f5;text-align:left;padding:7px 10px;border-bottom:2px solid #dde1e6}
table.grid td{padding:6px 10px;border-bottom:1px solid #eef0f3}
table.grid tr:hover td{background:#f8f9fb}
.badge{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600}
.b-pass{background:#dafbe1;color:#1b873f}.b-fail{background:#ffebe9;color:#cf222e}
.warn{background:#fff8e1;border-left:4px solid #ffa726;padding:10px 14px;border-radius:6px;margin:8px 0;font-size:13px}
.code{background:#0d1117;color:#e6edf3;padding:14px 16px;border-radius:8px;font-family:Consolas,monospace;font-size:12.5px;white-space:pre-wrap;overflow:auto}
"""


def build_html_report(
    *,
    mode: str,
    n_rows: int,
    n_features: int,
    quality,
    target_dist,
    mfe_series: Optional[pd.Series],
    return_stats: pd.DataFrame,
    weekly_activity: pd.DataFrame,
    days_active: pd.DataFrame,
    corr_matrix: Optional[pd.DataFrame],
    redundant_pairs: List[tuple],
    ic_df: pd.DataFrame,
    mi_df: pd.DataFrame,
    output_path: Path,
) -> Path:
    """Render the standalone HTML report. All inputs are pre-computed."""
    charts: List[str] = []

    def emit(fig: Optional[go.Figure], caption: str = "") -> None:
        if fig is None:
            return
        charts.append(_fig_html(fig, first=not charts))
        if caption:
            charts.append(f"<p class='cap'>{caption}</p>")

    parts: List[str] = []
    q = quality
    gate = (
        "<span class='badge b-pass'>PASS</span>"
        if q.passed else "<span class='badge b-fail'>FAIL</span>"
    )
    parts.append(
        "<div class='kpis'>"
        f"<div class='kpi'><div class='v'>{n_rows:,}</div><div class='l'>Rows</div></div>"
        f"<div class='kpi'><div class='v'>{n_features}</div><div class='l'>Features</div></div>"
        f"<div class='kpi'><div class='v'>{len(q.bad_tickers)}</div><div class='l'>Bad tickers</div></div>"
        f"<div class='kpi'><div class='v'>{len(redundant_pairs)}</div><div class='l'>Redundant pairs</div></div>"
        f"<div class='kpi'><div class='v'>{gate}</div><div class='l'>Quality gate</div></div>"
        "</div>"
    )

    # 1. Returns
    parts.append("<h2>1. Forward-Return Profile</h2>")
    fig = _fig_return_horizons(return_stats)
    if fig is not None:
        charts_before = len(charts)
        emit(fig, "Mean vs median forward return across 1/5/20/60-day horizons. "
                  "Right-skew (mean &gt; median) is expected for breakout trades.")
        parts.append("".join(charts[charts_before:]))
        parts.append(_df_table(return_stats, float_fmt="{:.2f}"))
    else:
        parts.append("<p class='muted'>No return columns in this mode.</p>")

    # 2. Weekly SEPA activity
    parts.append("<h2>2. Universe Activity (weekly)</h2>")
    fig = _fig_weekly_activity(weekly_activity)
    if fig is not None:
        cb = len(charts)
        emit(fig, "Bars: new SEPA additions per ISO week (one trade = one add). "
                  "Line: average distinct active tickers per trading day that week.")
        parts.append("".join(charts[cb:]))
    else:
        parts.append("<p class='muted'>No date/entry columns in this mode.</p>")

    # 3. Target distribution (x3)
    parts.append("<h2>3. Target Distribution</h2>")
    if target_dist is not None:
        cb = len(charts)
        emit(_fig_mfe_hist(mfe_series) if mfe_series is not None else None,
             "Raw MFE — the continuous outcome the class bins are cut from.")
        emit(_fig_class_counts(target_dist.counts, target_dist.proportions),
             f"Imbalance ratio (max/min) = {target_dist.imbalance_ratio:.2f}.")
        emit(_fig_days_active_density(days_active),
             "How long trades stay active, split by outcome class — "
             "Elite trades should run longer than Duds.")
        parts.append("".join(charts[cb:]))
    else:
        parts.append("<p class='muted'>Dense mode has no target column.</p>")

    # 4. Multicollinearity
    parts.append("<h2>4. Multicollinearity</h2>")
    fig = _fig_corr_heatmap(corr_matrix)
    if fig is not None:
        cb = len(charts)
        emit(fig, "Spearman ρ on the most-entangled features. Deep red/blue "
                  "blocks are redundant clusters — candidates for pruning.")
        parts.append("".join(charts[cb:]))
        rp = pd.DataFrame(redundant_pairs[:40], columns=["feature_a", "feature_b", "abs_corr"]) \
            if redundant_pairs else pd.DataFrame()
        parts.append(f"<p class='cap'>{len(redundant_pairs)} pairs |ρ| &gt; 0.80 "
                     f"(top 40 shown).</p>")
        parts.append(_df_table(rp))
    else:
        parts.append("<p class='muted'>Redundancy not computed in this mode.</p>")

    # 5. Feature signal
    parts.append("<h2>5. Feature Signal</h2>")
    fic = _fig_bar(ic_df, "abs_ic", "Spearman |IC| vs target — Top 30") \
        if not ic_df.empty else None
    fmi = _fig_bar(mi_df, "mi_score", "Mutual Information vs target — Top 30") \
        if not mi_df.empty else None
    if fic is not None or fmi is not None:
        cb = len(charts)
        emit(fic, "Monotonic rank association with the target class.")
        emit(fmi, "Non-linear dependence (captures what IC misses).")
        parts.append("".join(charts[cb:]))
    else:
        parts.append("<p class='muted'>No target — signal analysis skipped (dense mode).</p>")

    # 6. Data quality
    parts.append("<h2>6. Data Quality</h2>")
    top_null = q.null_rates[q.null_rates > 0].head(20)
    if len(top_null):
        nd = pd.DataFrame({
            "column": top_null.index,
            "null_rate_%": (top_null.values * 100),
            "P0": ["yes" if c in q.null_p0_cols else "" for c in top_null.index],
        })
        parts.append(_df_table(nd, float_fmt="{:.2f}"))
    else:
        parts.append("<p class='muted'>No null columns.</p>")
    if q.warnings:
        for w in q.warnings:
            parts.append(f"<div class='warn'>⚠️ {w}</div>")
    parts.append("<h3>Action Required (upstream feature_pipeline.py)</h3>")
    if q.action_required:
        parts.append("<div class='code'>" + "\n".join(q.action_required) + "</div>")
    else:
        parts.append("<p class='muted'>None — no P0 violations.</p>")

    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>Pre-Training Audit — {mode}</title><style>{_CSS}</style></head>"
        "<body><div class='wrap'>"
        f"<h1>Pre-Training Data Audit</h1>"
        f"<p class='sub'>mode <b>{mode}</b> &nbsp;·&nbsp; generated "
        f"{datetime.now():%Y-%m-%d %H:%M}</p>"
        + "".join(parts)
        + "</div></body></html>"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    logger.info("HTML pre-train audit written: %s", output_path)
    return output_path
