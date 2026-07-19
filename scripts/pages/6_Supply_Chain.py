"""Supply-chain — the knowledge-base map (FRAMEWORK ONLY, zero real edges).

Wires the Tier-0 mock (`build_supply_chain_mock.py` → standalone HTML) into the
app as a real page. Per `supply_chain_page.md` + the user's framing:

    screening → shortlist → agentic markdown report → agentic digestion → knowledge base

Edges accrue as that pipeline runs, so the page ships framework-first and is NOT
gated on edges.

🛑 **THE RIBBONS ARE CO-MOVEMENT, NOT DEPENDENCY.** Every number here is real
(252d sector return correlation from `price_data`), but a correlation is not a
supply relationship — sectors co-move via shared macro factors, common ownership
and index flows. This locks the FORMAT. It is not the product.

Two placeholders requested 2026-07-18, both wired as real UI with honest
"no data yet" bodies rather than dead buttons:
  - sector → **sub-sector drill-down** (149 industries in `company_profiles`; this
    is live, it's a taxonomy split not an edge claim)
  - sector/industry → **company network** (needs edges; renders the gap)

Plotly, not the mock's d3: the mock loads d3 from a CDN, which a Streamlit
component can't rely on offline/remote. Same chord *information* (a weighted
sector×sector matrix) rendered with the charting lib every other page already uses.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dashboard_utils import load_sector_comovement, load_sector_industries  # noqa: E402

# theta palette (style.md) — one hue per sector, matching the mock exactly so the
# page and the standalone HTML read as the same artifact.
SECTOR_COLORS = {
    "Technology": "#6b6a3a", "Financial Services": "#a5542f",
    "Healthcare": "#3f7d4e", "Industrials": "#b9862e",
    "Consumer Cyclical": "#7a6a9a", "Consumer Defensive": "#4a7a8a",
    "Energy": "#8a5a3a", "Communication Services": "#9a6a7a",
    "Basic Materials": "#5a7a5a", "Real Estate": "#8a7a4a",
    "Utilities": "#6a7a8a",
}

_CSS = """
<style>
  .sc-wrap{font-family:"Source Serif 4",Georgia,serif;color:#1c1a17}
  .sc-title{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:11px;
    letter-spacing:.18em;text-transform:uppercase;color:#8a8272;
    border-bottom:1px solid #e8e3d6;padding-bottom:8px;margin:2px 0 12px}
  .sc-caveat{padding:12px 16px;background:#fdf6e8;border:1px solid #b9862e;
    border-radius:4px;font-size:13px;line-height:1.55;margin:10px 0 18px}
  .sc-caveat b{color:#8a6420}
  .sc-empty{border:1px dashed #d8d2c2;border-radius:6px;padding:22px;
    background:#faf8f3;color:#6f6858;font-size:13px;line-height:1.6}
  .sc-empty b{color:#1c1a17}
  .sc-empty code{font-family:"JetBrains Mono",monospace;font-size:12px;
    background:#f0ece1;padding:1px 5px;border-radius:3px}
</style>
"""


def _html(markup: str) -> None:
    st.markdown("\n".join(l.lstrip() for l in markup.splitlines()),
                unsafe_allow_html=True)


def _chord_matrix(corr: pd.DataFrame) -> tuple[list[str], pd.DataFrame]:
    """Non-negative weights, zero diagonal, hub-first ordering.

    Self-correlation (1.0) would swamp every ribbon; a negative correlation has no
    chord representation. Both handled the same way as the mock: clip at 0, zero
    the diagonal, and say so in the caption.
    """
    order = sorted(corr.columns, key=lambda s: -corr[s].drop(s).mean())
    m = corr.loc[order, order].clip(lower=0.0).copy()
    np.fill_diagonal(m.values, 0.0)
    return order, m


def _render_chord(order: list[str], m: pd.DataFrame, counts: pd.Series,
                  n_days: int) -> None:
    """The chord diagram — the format the Tier-0 mock locked.

    Hand-rolled SVG, no d3. The mock loads d3 from a CDN and guards against it
    failing; vendoring a 280KB library to draw 55 ribbons is the wrong trade, and
    a CDN is exactly what breaks on the remote. The chord layout is ~30 lines of
    arithmetic (cumulative angles, then a quadratic-Bezier ribbon through the
    circle centre), so it's computed in Python and emitted as static SVG paths.

    Hover-to-isolate is preserved via a tiny inline script — that interaction is
    what makes an 11-sector chord legible, and dropping it was most of why the
    heatmap replaced it.
    """
    n = len(order)
    if n == 0:
        return

    W = 760
    cx = cy = W / 2
    outer_r = W * 0.5 - 110
    inner_r = outer_r - 20
    pad = 0.02  # radians between arcs

    totals = [float(m.loc[s].sum()) for s in order]
    grand = sum(totals)
    if grand <= 0:
        st.info("No positive co-movement to draw.")
        return

    # Angular span per sector, proportional to its total correlation.
    avail = 2 * math.pi - pad * n
    spans = [t / grand * avail for t in totals]
    starts, acc = [], -math.pi / 2  # start at 12 o'clock
    for sp in spans:
        starts.append(acc)
        acc += sp + pad

    def pt(r: float, a: float) -> tuple[float, float]:
        return cx + r * math.cos(a), cy + r * math.sin(a)

    def arc_path(r_in: float, r_out: float, a0: float, a1: float) -> str:
        x0, y0 = pt(r_out, a0)
        x1, y1 = pt(r_out, a1)
        x2, y2 = pt(r_in, a1)
        x3, y3 = pt(r_in, a0)
        large = 1 if (a1 - a0) > math.pi else 0
        return (f"M{x0:.1f},{y0:.1f}A{r_out:.1f},{r_out:.1f} 0 {large},1 {x1:.1f},{y1:.1f}"
                f"L{x2:.1f},{y2:.1f}A{r_in:.1f},{r_in:.1f} 0 {large},0 {x3:.1f},{y3:.1f}Z")

    # Sub-arc allocation: each sector's span is divided among its partners, so a
    # ribbon lands on a slice sized by that pair's correlation (same construction
    # as d3.chord).
    cursor = list(starts)
    ribbons = []
    for i, si in enumerate(order):
        for j, sj in enumerate(order):
            w = float(m.iloc[i, j])
            if w <= 0:
                continue
            sub = w / totals[i] * spans[i] if totals[i] > 0 else 0.0
            a0 = cursor[i]
            cursor[i] += sub
            if j > i:  # draw each pair once, from the i-side; store both ends
                ribbons.append({"i": i, "j": j, "a0": a0, "a1": cursor[i], "w": w})

    # Match each stored i-side slice with its j-side counterpart.
    cursor2 = list(starts)
    jslice: dict[tuple[int, int], tuple[float, float]] = {}
    for i, si in enumerate(order):
        for j, sj in enumerate(order):
            w = float(m.iloc[i, j])
            if w <= 0:
                continue
            sub = w / totals[i] * spans[i] if totals[i] > 0 else 0.0
            a0 = cursor2[i]
            cursor2[i] += sub
            if j < i:
                jslice[(j, i)] = (a0, cursor2[i])

    parts = []
    for rb in ribbons:
        i, j = rb["i"], rb["j"]
        b0, b1 = jslice.get((i, j), (rb["a0"], rb["a1"]))
        x0, y0 = pt(inner_r, rb["a0"])
        x1, y1 = pt(inner_r, rb["a1"])
        x2, y2 = pt(inner_r, b0)
        x3, y3 = pt(inner_r, b1)
        color = SECTOR_COLORS.get(order[i], "#8a8272")
        # Quadratic Bezier through the centre — the classic chord ribbon.
        d = (f"M{x0:.1f},{y0:.1f}"
             f"A{inner_r:.1f},{inner_r:.1f} 0 0,1 {x1:.1f},{y1:.1f}"
             f"Q{cx:.1f},{cy:.1f} {x2:.1f},{y2:.1f}"
             f"A{inner_r:.1f},{inner_r:.1f} 0 0,1 {x3:.1f},{y3:.1f}"
             f"Q{cx:.1f},{cy:.1f} {x0:.1f},{y0:.1f}Z")
        parts.append(
            f"<path class='rb' data-i='{i}' data-j='{j}' d='{d}' fill='{color}' "
            f"fill-opacity='.35' stroke='rgba(0,0,0,.06)'>"
            f"<title>{order[i]} ↔ {order[j]} — corr {rb['w']:.2f} "
            f"(co-movement, not dependency)</title></path>")

    for i, s in enumerate(order):
        a0, a1 = starts[i], starts[i] + spans[i]
        color = SECTOR_COLORS.get(s, "#8a8272")
        parts.append(
            f"<path class='arc' data-i='{i}' d='{arc_path(inner_r, outer_r, a0, a1)}' "
            f"fill='{color}'><title>{s} — {int(counts.get(s, 0))} companies</title></path>")
        mid = (a0 + a1) / 2
        lx, ly = pt(outer_r + 8, mid)
        deg = math.degrees(mid)
        flip = 90 < deg % 360 < 270 or -270 < deg < -90
        anchor = "end" if flip else "start"
        rot = f"rotate({deg + 180:.1f},{lx:.1f},{ly:.1f})" if flip else \
              f"rotate({deg:.1f},{lx:.1f},{ly:.1f})"
        parts.append(
            f"<text class='arc-label' x='{lx:.1f}' y='{ly:.1f}' transform='{rot}' "
            f"text-anchor='{anchor}' dy='-0.1em'>{s}</text>"
            f"<text class='arc-sub' x='{lx:.1f}' y='{ly:.1f}' transform='{rot}' "
            f"text-anchor='{anchor}' dy='1.05em'>{int(counts.get(s, 0))} cos</text>")

    svg = "".join(parts)
    components.html(f"""
<style>
  body{{margin:0;background:transparent;
    font-family:"Source Serif 4",Georgia,serif}}
  .hero{{text-align:center;margin:6px 0 2px}}
  .hero h1{{font-size:26px;font-weight:600;margin:0;letter-spacing:-.01em;color:#1c1a17}}
  .hero .sub{{color:#8a8272;font-size:15px;font-style:italic;margin-top:2px}}
  .arc-label{{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:10px;fill:#1c1a17}}
  .arc-sub{{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:9px;fill:#8a8272}}
  .rb,.arc{{transition:fill-opacity 180ms}}
  .meta{{text-align:center;color:#8a8272;font-size:12px;margin-top:6px;
    font-family:"JetBrains Mono",ui-monospace,monospace}}
  .hint{{text-align:center;color:#8a8272;font-size:12px;font-style:italic;margin-top:8px}}
  svg{{display:block;margin:0 auto;max-width:100%;height:auto}}
</style>
<div class="hero">
  <h1>The market is not a list of sectors.</h1>
  <div class="sub">It is a dependency system.</div>
</div>
<svg id="chord" viewBox="0 0 {W} {W}" width="{W}" height="{W}">{svg}</svg>
<div class="meta">{int(counts.sum()):,} companies · {n} sectors ·
  {n_days}d correlation · 0 supply-chain edges</div>
<div class="hint">Hover a sector arc to isolate its ribbons — try the top arc (the hub).</div>
<script>
  const rbs = [...document.querySelectorAll('.rb')];
  const arcs = [...document.querySelectorAll('.arc')];
  const reset = () => {{
    rbs.forEach(r => r.setAttribute('fill-opacity', .35));
    arcs.forEach(a => a.setAttribute('fill-opacity', 1));
  }};
  arcs.forEach(a => {{
    a.addEventListener('mouseenter', () => {{
      const i = a.dataset.i;
      rbs.forEach(r => r.setAttribute('fill-opacity',
        (r.dataset.i === i || r.dataset.j === i) ? .85 : .06));
      arcs.forEach(x => x.setAttribute('fill-opacity', x.dataset.i === i ? 1 : .35));
    }});
    a.addEventListener('mouseleave', reset);
  }});
  rbs.forEach(r => {{
    r.addEventListener('mouseenter', () => {{
      rbs.forEach(o => o.setAttribute('fill-opacity', o === r ? .85 : .06));
      arcs.forEach(x => x.setAttribute('fill-opacity',
        (x.dataset.i === r.dataset.i || x.dataset.i === r.dataset.j) ? 1 : .35));
    }});
    r.addEventListener('mouseleave', reset);
  }});
</script>
""", height=W + 120, scrolling=False)


def _render_matrix(order: list[str], m: pd.DataFrame) -> None:
    """Heatmap of the same matrix the chord encodes.

    Kept ALONGSIDE the chord, not instead of it: the chord locks the format and
    shows structure, but a pairwise magnitude lookup ("how correlated are these
    two exactly?") is what a matrix answers and a ribbon does not.
    """
    fig = go.Figure(go.Heatmap(
        z=m.values, x=order, y=order,
        colorscale=[[0, "#faf8f3"], [0.5, "#c8bf9a"], [1, "#6b6a3a"]],
        zmin=0, zmax=float(m.values.max()) if m.values.size else 1,
        hovertemplate="%{y} ↔ %{x}<br>corr %{z:.2f}<extra></extra>",
        colorbar=dict(title=dict(text="corr", side="right"), thickness=12),
    ))
    fig.update_layout(
        height=560, margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(tickangle=-45, side="bottom"),
        yaxis=dict(autorange="reversed"),
        plot_bgcolor="#fcfbf8", paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_hubs(order: list[str], m: pd.DataFrame, counts: pd.Series) -> None:
    """Mean off-diagonal correlation per sector — the 'hub vs loner' read."""
    mean_corr = m.replace(0.0, np.nan).mean(axis=1).reindex(order)
    tbl = pd.DataFrame({
        "Sector": order,
        "Companies": [int(counts.get(s, 0)) for s in order],
        "Mean corr": mean_corr.values,
    })
    st.dataframe(
        tbl, hide_index=True, use_container_width=True,
        column_config={
            "Sector": st.column_config.TextColumn(width="medium"),
            "Companies": st.column_config.NumberColumn(format="%d", width="small"),
            "Mean corr": st.column_config.ProgressColumn(
                "Mean corr", format="%.2f", min_value=0.0,
                max_value=float(np.nanmax(mean_corr.values)) if len(mean_corr) else 1.0,
                help="Average correlation with every OTHER sector. High = moves with "
                     "the market (a hub); low = diversifier. Not a dependency rank."),
        },
    )


def _render_drilldown(order: list[str]) -> None:
    """Sector → sub-sector. LIVE (taxonomy), not a placeholder."""
    sector = st.selectbox("Sector", order, key="sc_drill_sector")
    inds = load_sector_industries(sector)
    if inds is None or inds.empty:
        st.info(f"No industries recorded for {sector}.")
        return
    st.caption(f"**{len(inds)}** industries · "
               f"{int(inds['n_companies'].sum()):,} companies in {sector}")
    fig = go.Figure(go.Bar(
        x=inds["n_companies"], y=inds["industry"], orientation="h",
        marker_color=SECTOR_COLORS.get(sector, "#8a8272"),
        hovertemplate="%{y}<br>%{x} companies<extra></extra>",
    ))
    fig.update_layout(
        height=max(260, 22 * len(inds)), margin=dict(l=10, r=10, t=10, b=10),
        xaxis_title="companies", yaxis=dict(autorange="reversed"),
        plot_bgcolor="#fcfbf8", paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("⚠️ Taxonomy only — `company_profiles.industry` says what a company "
               "**is**, never what it **buys from**. More resolution, still zero edges.")


def _render_network_placeholder() -> None:
    """Company network — the genuinely blocked one."""
    _html("""
    <div class="sc-empty">
      <b>Company network — waiting on edges.</b><br><br>
      A company-level graph needs a <code>supply_chain_edges</code> table
      (supplier → customer, with a source and a confidence). <b>That table does
      not exist, and there is no partial version of it</b> — the sector view above
      is co-movement, which cannot be drilled into a supply relationship no matter
      how far you zoom.<br><br>
      Two ways it gets built, an open user decision
      (<code>supply_chain_page.md</code>):<br>
      &nbsp;&nbsp;• <b>Build</b> — Tier 1, extract from EDGAR 10-K customer
      disclosures. Multi-week new engine.<br>
      &nbsp;&nbsp;• <b>Buy</b> — Tier 2, a vendor relationship feed. Paid, immediate.<br><br>
      A third path fills it incrementally for free: the agentic pipeline
      (<code>screening → report → digestion → knowledge base</code>) yields edges
      per name as reports accrue. That is why this page ships framework-first.
    </div>
    """)


_html(_CSS + """
<div class="sc-wrap">
  <div class="sc-title">SX · Supply chain — the knowledge-base map</div>
</div>
""")

corr, counts, n_days = load_sector_comovement()
if corr is None or corr.empty:
    st.info("No price history available to compute sector co-movement.")
    st.stop()

order, m = _chord_matrix(corr)

_html(f"""
<div class="sc-caveat">
  <b>These are co-movement, not dependency.</b> Every number below is real — a
  {n_days}-day sector return correlation over
  {int(counts.sum()):,} companies — but sectors co-move via shared macro factors,
  common ownership and index flows, <b>none of which is a supply relationship</b>.
  This page locks the format and is the platform stress case. Real supplier→customer
  edges do not exist yet; see the Company network tab.
</div>
""")

tab_map, tab_drill, tab_net = st.tabs(
    ["Sector map", "Sub-sectors", "Company network"]
)

with tab_map:
    _render_chord(order, m, counts, n_days)
    st.caption(
        f"Equal-weight daily sector returns, {n_days} trading days. Diagonal zeroed "
        "(self-correlation would swamp the scale) and negatives clipped to 0 — a "
        "negative co-movement has no place on a dependency-shaped chart. "
        "ETF pseudo-sectors excluded. Ribbon width is the pair's correlation; arc "
        "width is the sector's total co-movement."
    )
    with st.expander("Pairwise matrix — exact values"):
        _render_matrix(order, m)
    st.markdown("##### Hubs and loners")
    _render_hubs(order, m, counts)

with tab_drill:
    _render_drilldown(order)

with tab_net:
    _render_network_placeholder()
