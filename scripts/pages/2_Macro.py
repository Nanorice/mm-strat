"""Macro — Market Regime & Macro. All three sections are live (see
docs/session_logs/sprint_14/plans/dashboard_uplift/macro_page.md).

S1 = regime headline (F&G dial + 6 macro-pillar percentile tiles + deploy headline).
S3 = indicator board over `config.FRED_SERIES` entries carrying a `group` tag —
coverage is incomplete BY DESIGN (~42 of ~66; C2 scrapes + C3 live feeds pending),
so a configured-but-empty series greys out and the page never gates on completeness.

S2 renders the `sector_breadth` nightly snapshot (sector_breadth_engine): per
sector, today's return distribution (KDE from stored quantiles) + up/down breadth
+ trend/breakout participation + names added today/5d. Click a sector to expand
its subsectors. Native Yahoo/FMP taxonomy; ETF:* excluded; subsectors below the
min-name threshold collapse into an 'Other' card (a KDE over <5 names is a dot).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dashboard_utils import (
    fear_greed_label,
    load_fear_greed,
    load_macro_indicators,
    load_macro_pillars,
    load_regime,
    load_sector_breadth,
    load_weather_gauge,
)
import config
from src.sector_breadth_engine import HIST_LO, HIST_HI, HIST_BINS

MIN_NAMES = 5  # below this a KDE is a dot → collapse into "Other" (plan §S2 constraint 1)


def _html(markup: str) -> None:
    """Emit raw HTML through st.markdown.

    Streamlit runs the string through a markdown parser first, which treats any
    line indented >=4 spaces as a CODE BLOCK — so indented markup renders as
    literal text instead of HTML. Interpolated f-string fragments carry their
    source indentation, so strip leading whitespace from every line before it
    reaches the parser.
    """
    flat = "\n".join(line.lstrip() for line in markup.splitlines())
    st.markdown(flat, unsafe_allow_html=True)

# S1 pillar tiles. (label, value_col, pctile_col, fmt, high_is). `high_is` tags
# what a HIGH percentile means for risk appetite — the tile's regime-bias chip.
# NB the plan doc says "6 pillars (t2_regime_scores)" — that's a doc error: the
# 6-pillar board is load_macro_pillars (VIX/Credit/Term/Rates/Liquidity/CAPE);
# t2_regime_scores carries M03's THREE pillars (trend/liq/risk) and feeds the
# deploy headline below instead.
S1_PILLARS = [
    ("VIX",         "VIX",         "VIX_pct",         "{:.1f}",   "risk-off"),
    ("Credit",      "Credit",      "Credit_pct",      "{:.2f}",   "risk-off"),
    ("Term Spread", "Term Spread", "Term Spread_pct", "{:.2f}",   "risk-on"),
    ("Rates",       "Rates",       "Rates_pct",       "{:.2f}",   "risk-off"),
    ("Liquidity",   "Liquidity",   "Liquidity_pct",   "{:,.0f}",  "risk-on"),
    ("CAPE",        "CAPE",        "CAPE_pct",        "{:.1f}",   "risk-off"),
]

# S3 board group order + display titles. Keys match `group` in config.FRED_SERIES /
# YAHOO_SERIES / SENTIMENT_SERIES; a group with no ingested series is skipped.
# Group 10 (calendar) has no source yet — it lands with the C3 feeds.
S3_GROUPS = [
    ("growth",           "1 · Growth"),
    ("inflation",        "2 · Inflation"),
    ("fed_policy",       "3 · Fed policy"),
    ("rates_curve",      "4 · Rates & curve"),
    ("liquidity_credit", "5 · Liquidity & credit"),
    ("risk_regime",      "6 · Risk regime"),
    ("flows",            "7 · Flows & positioning"),
    ("geopolitics",      "8 · Geopolitics"),
    ("cyclicals",        "9 · Cyclical sectors"),
]


def _fg_gauge(score: float, prev: float | None) -> str:
    """0-100 F&G dial as a semicircular arc; needle at `score`."""
    import math
    label = fear_greed_label(score)
    # arc: 180° sweep, left=0 (fear) → right=100 (greed).
    ang = math.pi * (1 - score / 100.0)
    cx, cy, r = 92, 86, 66
    nx, ny = cx + r * 0.82 * math.cos(ang), cy - r * 0.82 * math.sin(ang)
    delta = "" if prev is None else f"{score - prev:+.1f} vs prior"
    # colour bands mirror CNN's own 0-100 banding.
    bands = [(0, 25, "#b23b3b"), (25, 45, "#c9752f"), (45, 55, "#b9862e"),
             (55, 75, "#6b8f4a"), (75, 100, "#3f7d4e")]
    segs = ""
    for lo, hi, col in bands:
        a0, a1 = math.pi * (1 - lo / 100), math.pi * (1 - hi / 100)
        x0, y0 = cx + r * math.cos(a0), cy - r * math.sin(a0)
        x1, y1 = cx + r * math.cos(a1), cy - r * math.sin(a1)
        segs += (f'<path d="M {x0:.1f} {y0:.1f} A {r} {r} 0 0 1 {x1:.1f} {y1:.1f}" '
                 f'fill="none" stroke="{col}" stroke-width="11" stroke-linecap="butt"/>')
    return f"""
    <div class="card fg">
      <svg width="184" height="104" viewBox="0 0 184 104">
        {segs}
        <line x1="{cx}" y1="{cy}" x2="{nx:.1f}" y2="{ny:.1f}"
              stroke="var(--foreground)" stroke-width="2.5" stroke-linecap="round"/>
        <circle cx="{cx}" cy="{cy}" r="4" fill="var(--foreground)"/>
        <text x="{cx}" y="{cy - 22}" text-anchor="middle" class="fgval">{score:.0f}</text>
      </svg>
      <div class="fglab">{label}</div>
      <div class="fgsub mono">Fear &amp; Greed · {delta}</div>
    </div>"""


def _render_s1(pillars, weather, regime, fg) -> None:
    """S1 regime headline: F&G dial + the 6 macro pillars + deploy headline.

    Two complementary lenses, no redundant tiles (plan §S1): F&G = the market's
    mood in one familiar number; the pillars = where each macro axis sits in its
    own history; the deploy headline = our research's own answer (weather_gauge).
    """
    last = pillars.iloc[-1] if len(pillars) else None
    as_of = str(pillars["date"].iloc[-1])[:10] if len(pillars) else "—"

    # F&G tile — rendered only when the scrape has actually landed data.
    fg_html = ""
    if fg is not None and not fg.empty:
        cur = float(fg["score"].iloc[-1])
        prev = float(fg["score"].iloc[-2]) if len(fg) > 1 else None
        fg_html = _fg_gauge(cur, prev)

    tiles = ""
    for label, vcol, pcol, fmt, high_is in S1_PILLARS:
        if last is None or vcol not in pillars.columns or pd.isna(last[vcol]):
            continue
        val, pct = last[vcol], last.get(pcol)
        pct_txt = "—" if pd.isna(pct) else f"{pct:.0f}th"
        # bias chip: what THIS pillar being high/low implies for risk appetite.
        if pd.isna(pct):
            bias, bcls = "—", "neu"
        elif (pct >= 70 and high_is == "risk-off") or (pct <= 30 and high_is == "risk-on"):
            bias, bcls = "SHORT", "neg"
        elif (pct <= 30 and high_is == "risk-off") or (pct >= 70 and high_is == "risk-on"):
            bias, bcls = "LONG", "pos"
        else:
            bias, bcls = "NEUTRAL", "neu"
        tiles += f"""
        <div class="card ptile">
          <div class="prow"><span class="plab">{label}</span>
            <span class="chip {bcls}">{bias}</span></div>
          <div class="pval mono">{fmt.format(val)}</div>
          <div class="pbar"><i style="width:{0 if pd.isna(pct) else pct:.0f}%"></i></div>
          <div class="psub mono">{pct_txt} pctile</div>
        </div>"""

    # Deploy headline — weather_gauge is the research's own go/no-go answer.
    dep = ""
    if weather is not None and not weather.empty:
        w = weather.iloc[-1]
        posture = str(w["deploy_posture"])
        pcls = "neg" if posture == "STAND ASIDE" else "pos"
        spy = "above" if bool(w["spy_above_200d"]) else "below"
        m03 = f"{regime['m03_score']:.0f}" if regime is not None else "—"
        dep = f"""
        <div class="card dep">
          <div class="deprow">
            <span class="chip big {pcls}">{posture}</span>
            <span class="depitem"><span class="dlab">SPY vs 200d</span>
              <b class="mono {'pos' if spy == 'above' else 'neg'}">{spy}</b></span>
            <span class="depitem"><span class="dlab">Supply</span>
              <b class="mono">{w['supply_regime']}</b>
              <span class="dsub mono">{w['breakout_supply_share'] * 100:.1f}% breakout</span></span>
            <span class="depitem"><span class="dlab">Stress z</span>
              <b class="mono">{w['stress_z']:+.2f}</b></span>
            <span class="depitem"><span class="dlab">M03 regime</span>
              <b class="mono">{m03}</b></span>
          </div>
        </div>"""

    _html(f"""
    <style>
      .s1{{font-family:"Source Serif 4",Georgia,serif;color:#1c1a17}}
      .s1 .card{{background:#fffefb;border:1px solid #e8e3d6;border-radius:6px;padding:12px}}
      .s1 .mono{{font-family:"JetBrains Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums}}
      .s1 .sectitle{{font-family:"JetBrains Mono",monospace;font-size:11px;letter-spacing:.18em;
        text-transform:uppercase;color:#8a8272;border-bottom:1px solid #e8e3d6;
        padding-bottom:8px;margin:2px 0 12px}}
      .s1 .grid{{display:grid;grid-template-columns:200px repeat(6,1fr);gap:10px;align-items:stretch}}
      .s1 .fg{{text-align:center;display:flex;flex-direction:column;justify-content:center}}
      .s1 .fgval{{font-family:"JetBrains Mono",monospace;font-size:26px;font-weight:600;fill:#1c1a17}}
      .s1 .fglab{{font-size:14px;font-weight:600;margin-top:-6px}}
      .s1 .fgsub{{font-size:10px;color:#8a8272;margin-top:2px}}
      .s1 .prow{{display:flex;justify-content:space-between;align-items:center;gap:4px}}
      .s1 .plab{{font-size:12px;color:#8a8272}}
      .s1 .pval{{font-size:19px;font-weight:600;margin:6px 0 4px}}
      .s1 .pbar{{height:4px;background:#ece4d4;border-radius:2px;overflow:hidden}}
      .s1 .pbar i{{display:block;height:100%;background:#6b6a3a}}
      .s1 .psub{{font-size:10px;color:#8a8272;margin-top:4px}}
      .s1 .chip{{font-family:"JetBrains Mono",monospace;font-size:9px;letter-spacing:.06em;
        padding:2px 5px;border-radius:3px;border:1px solid #e8e3d6}}
      .s1 .chip.big{{font-size:13px;padding:5px 12px;letter-spacing:.1em;font-weight:600}}
      .s1 .pos{{color:#3f7d4e;border-color:#3f7d4e40}}
      .s1 .neg{{color:#b23b3b;border-color:#b23b3b40}}
      .s1 .neu{{color:#8a8272}}
      .s1 .dep{{margin-top:10px}}
      .s1 .deprow{{display:flex;align-items:center;gap:30px;flex-wrap:wrap}}
      .s1 .depitem{{display:flex;flex-direction:column;gap:1px}}
      .s1 .dlab{{font-size:10px;color:#8a8272;text-transform:uppercase;letter-spacing:.1em}}
      .s1 .depitem b{{font-size:15px}}
      .s1 .dsub{{font-size:10px;color:#8a8272}}
      /* Phone: 200px + six 1fr columns leaves each pillar ~29px wide. Gauge on
         its own row, pillars two-up. */
      @media (max-width:640px){{
        .s1 .grid{{grid-template-columns:repeat(2,1fr)}}
        .s1 .grid > :first-child{{grid-column:1/-1}}
        .s1 .sectitle{{letter-spacing:.08em}}
        .s1 .deprow{{gap:14px}}
      }}
    </style>
    <div class="s1">
      <div class="sectitle">1 · Regime headline
        <span style="text-transform:none;letter-spacing:0;color:#8a8272"> — as of {as_of}</span></div>
      <div class="grid">{fg_html}{tiles}</div>
      {dep}
    </div>
    """)


def _fmt(v: float) -> str:
    """Board number formatting. The board spans ~4 orders of magnitude (SOFR 4.3 →
    payrolls 160,000), so a fixed precision either wastes width on the big ones or
    flattens the small ones: scale the decimals to the value."""
    if pd.isna(v):
        return "—"
    a = abs(v)
    if a >= 1000:
        return f"{v:,.0f}"
    if a >= 100:
        return f"{v:,.1f}"
    return f"{v:,.2f}"


SPARK_DAYS = 180  # observation window; passed to the loader so the footer can't drift from it


def _sparkline(vals: list[float], w: int = 90, h: int = 24) -> str:
    """Inline SVG LEVEL sparkline (line + area), oldest→newest, scaled to the window.

    A line is the right mark for a level series — it shows the path, which bars only
    approximate. It's wider (90px) than the earlier attempt (64px) and lightly
    downsampled so points stay resolvable rather than collapsing to sub-pixel noise:
    that, not the mark type, was what made the first version unreadable.

    The "is today unusual?" question a per-row histogram would answer is handled by
    the z column instead — a histogram needs ~50+ points to have a shape, and 22 of
    the board's series are monthly/quarterly (6 points in this window), so half the
    board would render a shape the data can't support.
    """
    if not vals:
        return f'<svg class="spk" width="{w}" height="{h}"></svg>'
    if len(vals) == 1:
        return (f'<svg class="spk" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
                f'<circle cx="{w/2}" cy="{h/2}" r="1.6" fill="#8a8272"/></svg>')

    # cap at ~1 point per 1.5px: beyond that the line is drawing detail the eye
    # cannot resolve (the original 180-in-64px = 0.4px/point failure).
    cap = int(w / 1.5)
    if len(vals) > cap:
        step = len(vals) / cap
        pts = [vals[min(int(i * step), len(vals) - 1)] for i in range(cap)]
    else:
        pts = list(vals)

    lo, hi = min(pts), max(pts)
    rng = hi - lo
    dx = w / (len(pts) - 1)
    # flat series (rng==0) -> mid-line rather than a div-by-zero.
    ys = [(h - 2) - ((v - lo) / rng if rng else 0.5) * (h - 4) for v in pts]
    line = " ".join(f"{i * dx:.1f},{y:.1f}" for i, y in enumerate(ys))
    up = pts[-1] >= pts[0]
    col = "#2f6b3d" if up else "#a32f2f"
    area = f"0,{h} {line} {w},{h}"
    return (f'<svg class="spk" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<polygon points="{area}" fill="{col}" opacity=".08"/>'
            f'<polyline points="{line}" fill="none" stroke="{col}" stroke-width="1.3"/>'
            f'<circle cx="{w:.1f}" cy="{ys[-1]:.1f}" r="1.8" fill="{col}"/></svg>')


def _render_s3(ind) -> None:
    """S3 indicator board: the macro groups, one row per series.

    Coverage is INCOMPLETE BY DESIGN (plan §S3): ~42 of ~66 land from FRED (C1).
    The C2 scrapes (AAII/NAAIM/COT) and C3 live feeds (futures/MOVE/VVIX/SKEW/term
    premium) are pending — a configured-but-empty series greys out rather than
    vanishing, and the page never gates on completeness.

    `Δ` is vs the previous OBSERVATION (so w/w for weekly, m/m for monthly), not a
    fixed calendar lag. A `rev` chip marks FRED-revised series, which our
    INSERT-OR-IGNORE ingest captures at FIRST PRINT ONLY — display-only, see
    config.FRED_SERIES.
    """
    if ind is None or ind.empty:
        st.info("No macro indicators configured.")
        return

    as_of = max((d for d in ind["date"] if pd.notna(d)), default=None)
    as_of = str(as_of)[:10] if as_of is not None else "—"

    # Anomaly banner — the day's |z| outliers, worst first. Thresholds live in config
    # (1.5/2.5, measured: 0.5/1.0 would fire on a median 14 of 56 rows EVERY day).
    az = ind["z"].abs()
    hot = ind[az >= config.S3_SIGMA_WARN].reindex(
        az[az >= config.S3_SIGMA_WARN].sort_values(ascending=False).index)
    banner = ""
    if not hot.empty:
        n_red = int((az >= config.S3_SIGMA_ALERT).sum())
        bcls = "alert" if n_red else "warn"
        chips = "".join(
            f'<span class="bchip {"red" if abs(r["z"]) >= config.S3_SIGMA_ALERT else "amber"}">'
            f'{r["name"]}<b class="mono">{r["z"]:+.1f}σ</b></span>'
            for _, r in hot.iterrows())
        headline = (f"{n_red} indicator{'s' if n_red != 1 else ''} beyond "
                    f"{config.S3_SIGMA_ALERT}σ" if n_red
                    else f"{len(hot)} indicator{'s' if len(hot) != 1 else ''} beyond "
                         f"{config.S3_SIGMA_WARN}σ")
        banner = f"""
        <div class="card bnr {bcls}">
          <div class="bhd"><b>{headline}</b>
            <span class="bsub">unusual move vs each series' own history</span></div>
          <div class="bchips">{chips}</div>
        </div>"""

    groups = ""
    for gid, title in S3_GROUPS:
        sub = ind[ind["group"] == gid]
        if sub.empty:
            continue
        live = int(sub["value"].notna().sum())
        rows = ""
        for _, r in sub.iterrows():
            have = pd.notna(r["value"])
            rev = '<span class="chip rev" title="FRED-revised; captured at first print">rev</span>' if r["revised"] else ""
            namecell = (f'<td class="iname"><span class="inm">{r["name"]}</span>'
                        f'<span class="imeta mono">{r["symbol"]}{rev}</span></td>')
            if not have:
                rows += f'<tr class="off">{namecell}<td class="miss mono" colspan="5">not ingested</td></tr>'
                continue
            chg = r["chg_pct"]
            ccls = "neu" if pd.isna(chg) else ("pos" if chg >= 0 else "neg")
            ctxt = "—" if pd.isna(chg) else f"{chg:+.2f}%"
            z = r["z"]
            if pd.isna(z):
                ztxt, zcls = "—", "neu"
            else:
                ztxt = f"{z:+.1f}σ"
                zcls = ("zred" if abs(z) >= config.S3_SIGMA_ALERT
                        else "zamber" if abs(z) >= config.S3_SIGMA_WARN else "neu")
            spark = r["spark"] or []
            rng_txt = f"{_fmt(min(spark))}–{_fmt(max(spark))}" if spark else "—"
            rows += f"""
            <tr>
              {namecell}
              <td class="iprior mono">{_fmt(r['prior'])}</td>
              <td class="ival mono">{_fmt(r['value'])}</td>
              <td class="ichg mono {ccls}">{ctxt}</td>
              <td class="iz mono {zcls}">{ztxt}</td>
              <td class="ispk">{_sparkline(spark)}</td>
              <td class="irange mono">{rng_txt}</td>
            </tr>"""
        groups += f"""
        <div class="card gcard">
          <div class="gtitle"><b>{title}</b>
            <span class="gcount mono">{live}/{len(sub)} indicators</span></div>
          <table class="itab">
            <tr class="ihdr">
              <th class="iname">Indicator</th><th class="iprior">Prior</th>
              <th class="ival">Now</th><th class="ichg">Δ%</th><th class="iz">Z</th>
              <th class="ispk">History</th><th class="irange">Range</th>
            </tr>{rows}
          </table>
        </div>"""

    _html(f"""
    <style>
      .s3{{font-family:"Source Serif 4",Georgia,serif;color:#1c1a17}}
      .s3 .card{{background:#fffefb;border:1px solid #e8e3d6;border-radius:6px;padding:12px}}
      .s3 .mono{{font-family:"JetBrains Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums}}
      .s3 .sectitle{{font-family:"JetBrains Mono",monospace;font-size:11px;letter-spacing:.18em;
        text-transform:uppercase;color:#8a8272;border-bottom:1px solid #e8e3d6;
        padding-bottom:8px;margin:2px 0 12px}}
      /* One group per row, full width. The old auto-fit grid packed 2-3 groups into
         380px columns, which is what made the board feel squeezed — six numeric
         columns need room to breathe more than the page needs density. */
      .s3 .ggrid{{display:flex;flex-direction:column;gap:14px}}
      .s3 .gcard{{padding:0;overflow:hidden}}
      .s3 .gtitle{{font-family:"JetBrains Mono",monospace;font-size:12px;letter-spacing:.1em;
        text-transform:uppercase;color:#1c1a17;padding:13px 16px;display:flex;
        justify-content:space-between;align-items:center;background:#faf8f2;
        border-bottom:1px solid #e8e3d6}}
      .s3 .gtitle b{{font-weight:600}}
      .s3 .gcount{{color:#8a8272;font-size:10px;letter-spacing:.06em}}
      .s3 .itab{{width:100%;border-collapse:collapse;table-layout:fixed}}
      .s3 .itab tr{{border-top:1px solid #f2ede0}}
      .s3 .itab tr.ihdr{{border-top:none}}
      .s3 .itab tr.off{{opacity:.42}}
      .s3 .itab th{{font-family:"JetBrains Mono",monospace;font-size:9px;letter-spacing:.12em;
        text-transform:uppercase;color:#8a8272;font-weight:400;text-align:right;
        padding:9px 16px 8px}}
      .s3 .itab th:first-child{{text-align:left}}
      /* 13px vertical padding: the airy row the mock has and the 4px version lacked. */
      .s3 .itab td{{padding:13px 16px;vertical-align:middle;text-align:right}}
      /* name column: label on top, symbol + rev chip on a second line beneath it. */
      .s3 .iname{{text-align:left;width:24%}}
      .s3 .inm{{display:block;font-size:14px;color:#1c1a17;line-height:1.25}}
      .s3 .imeta{{display:block;font-size:9px;color:#8a8272;letter-spacing:.05em;
        margin-top:3px}}
      .s3 .iprior{{font-size:13px;color:#6f6858;width:13%;white-space:nowrap}}
      .s3 .ival{{font-size:15px;font-weight:600;color:#1c1a17;width:13%;white-space:nowrap}}
      .s3 .ichg{{font-size:12px;width:10%;white-space:nowrap}}
      .s3 .iz{{font-size:12px;width:8%;white-space:nowrap;color:#8a8272}}
      .s3 .ispk{{width:13%;white-space:nowrap}}
      .s3 .spk{{vertical-align:middle}}
      /* range: same size as prior — it was 10px and read as a footnote. */
      .s3 .irange{{font-size:12px;color:#6f6858;width:19%;white-space:nowrap}}
      .s3 .miss{{font-size:12px;color:#a89f8b;font-style:italic;text-align:right}}
      .s3 .chip{{font-family:"JetBrains Mono",monospace;font-size:8px;padding:1px 3px;
        border-radius:2px;border:1px solid #e8e3d6;color:#8a8272;margin-left:5px}}
      .s3 .zred{{color:#b23b3b;font-weight:600}}
      .s3 .zamber{{color:#b9862e;font-weight:600}}
      /* anomaly banner */
      .s3 .bnr{{margin-bottom:14px;border-left:3px solid #b9862e}}
      .s3 .bnr.alert{{border-left-color:#b23b3b}}
      .s3 .bhd{{display:flex;align-items:baseline;gap:10px;margin-bottom:9px}}
      .s3 .bhd b{{font-size:14px}}
      .s3 .bnr.alert .bhd b{{color:#b23b3b}}
      .s3 .bnr.warn .bhd b{{color:#b9862e}}
      .s3 .bsub{{font-size:11px;color:#8a8272}}
      .s3 .bchips{{display:flex;flex-wrap:wrap;gap:6px}}
      .s3 .bchip{{font-size:11px;padding:3px 8px;border-radius:3px;border:1px solid #e8e3d6;
        background:#faf8f2;display:inline-flex;gap:6px;align-items:baseline}}
      .s3 .bchip b{{font-size:10px}}
      .s3 .bchip.red{{border-color:#b23b3b55;color:#b23b3b}}
      .s3 .bchip.amber{{border-color:#b9862e55;color:#8a6a24}}
      .s3 .pos{{color:#3f7d4e}}
      .s3 .neg{{color:#b23b3b}}
      .s3 .neu{{color:#8a8272}}
      .s3 .foot{{font-size:10px;color:#8a8272;margin-top:10px;font-family:"JetBrains Mono",monospace}}
      /* Phone: drop the sparkline column outright and give the width to the
         indicator name. The name is the only column that wraps, and every line it
         wraps to sets the height of the whole row — a 13% name column made every
         cell three lines tall. The history column is the most redundant thing
         here (Range already states the same span numerically), so it goes first.
         Widths are re-stated because table-layout:fixed reads them off the header
         row — which is why the <th>s carry the column classes. */
      @media (max-width:640px){{
        .s3 .gcard{{overflow-x:auto}}
        .s3 .itab{{min-width:420px}}
        .s3 .ispk{{display:none}}
        .s3 .iname{{width:38%}}
        .s3 .iprior{{width:14%}}
        .s3 .ival{{width:15%}}
        .s3 .ichg{{width:12%}}
        .s3 .iz{{width:9%}}
        .s3 .irange{{width:12%}}
        .s3 .itab th,.s3 .itab td{{padding-left:8px;padding-right:8px}}
        /* Trimmed from 13px: the airy desktop row costs a phone screen a row per
           scroll. Keeping name-over-symbol stacked is deliberate — inlining them
           was measured and came out TALLER (median 64px → 72px), because the run
           then wraps mid-name instead of at the symbol boundary. */
        .s3 .itab td{{padding-top:10px;padding-bottom:10px}}
        .s3 .sectitle{{letter-spacing:.08em}}
      }}
    </style>
    <div class="s3">
      <div class="sectitle">3 · Indicator board
        <span style="text-transform:none;letter-spacing:0;color:#8a8272"> — as of {as_of}</span></div>
      {banner}
      <div class="ggrid">{groups}</div>
      <div class="foot">Δ + Prior vs previous observation (w/w weekly, m/m monthly) ·
        <b>Z</b> = that change vs the series' own full-history change distribution
        (pct-change for prices, absolute for spreads); amber ≥{config.S3_SIGMA_WARN}σ,
        red ≥{config.S3_SIGMA_ALERT}σ · History &amp; Range = last <b>{SPARK_DAYS}</b>
        observations · <span class="chip rev">rev</span> = FRED-revised, captured at
        first print · <b>display-only</b> (all-time stats = look-ahead; never a model
        input) · flows/positioning + live futures feeds pending</div>
    </div>
    """)


def _sector_payload(df) -> tuple[list[dict], str]:
    """Shape the flat sector_breadth frame into the nested JSON the S2 renderer wants."""
    sec = df[df.grain == "sector"].sort_values("n_names", ascending=False)
    subs = df[df.grain == "subsector"]
    as_of = str(df["as_of_date"].iloc[0])[:10] if len(df) else "—"

    payload = []
    for _, r in sec.iterrows():
        kids = subs[subs.sector == r["name"]].sort_values("n_names", ascending=False)
        payload.append({
            "name": r["name"], "cos": int(r["n_names"]),
            "ret": float(r["ret_median_pct"]),
            "hist": json.loads(r["ret_hist"]),
            "up": int(r["n_up"]), "down": int(r["n_down"]),
            "trend": int(r["n_trend_ok"]), "brk": int(r["n_breakout_ok"]),
            "add1": int(r["trend_added_today"]), "add5": int(r["trend_added_5d"]),
            "subs": [{
                "name": s["name"], "cos": int(s["n_names"]),
                "ret": float(s["ret_median_pct"]),
                "hist": json.loads(s["ret_hist"]),
                "up": int(s["n_up"]), "down": int(s["n_down"]),
                "trend": int(s["n_trend_ok"]), "brk": int(s["n_breakout_ok"]),
            } for _, s in kids.iterrows()],
        })
    return payload, as_of


def _render(df) -> None:
    payload, as_of = _sector_payload(df)
    data_js = json.dumps(payload)
    # CSS + JS lifted from the design mock; SECTORS is injected from the DB and the
    # KDE is drawn from real quantiles (mock faked a bell). f-string: literal braces
    # are doubled; {data_js}/{as_of}/{MIN_NAMES} are the only interpolations.
    html = f"""
<style>
  :root{{--background:#fcfbf8;--foreground:#1c1a17;--muted:#8a8272;--border:#e8e3d6;
    --accent:#6b6a3a;--rust:#a5542f;--positive:#3f7d4e;--negative:#b23b3b;
    --warn:#b9862e;--card:#fffefb;}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--background);color:var(--foreground);
    font-family:"Source Serif 4",Georgia,serif;font-size:15px;line-height:1.5}}
  .mono{{font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-variant-numeric:tabular-nums}}
  .sub{{color:var(--muted);font-size:13px}}
  .pos{{color:var(--positive)}} .neg{{color:var(--negative)}}
  .sectitle{{font-family:"JetBrains Mono",monospace;font-size:11px;letter-spacing:.18em;
    text-transform:uppercase;color:var(--muted);margin:6px 0 14px;
    border-bottom:1px solid var(--border);padding-bottom:8px}}
  .card{{background:var(--card);border:1px solid var(--border);border-radius:6px;padding:14px}}
  .heat{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
  .scard{{cursor:pointer;transition:border-color .12s}}
  .scard:hover{{border-color:var(--accent)}}
  .scard .row1{{display:flex;justify-content:space-between;align-items:baseline}}
  .scard .name{{font-size:15px;font-weight:600}}
  .scard .ret{{font-family:"JetBrains Mono",monospace;font-size:17px;font-weight:600}}
  .kde{{margin:8px 0 6px}}
  .breadth{{display:flex;font-size:11px;justify-content:space-between;color:var(--muted);
    font-family:"JetBrains Mono",monospace}}
  .partbar{{height:6px;border-radius:3px;overflow:hidden;display:flex;margin-top:6px;background:#ece4d4}}
  .partbar i{{display:block;height:100%}}
  .addnote{{font-size:11px;color:var(--muted);margin-top:6px;font-family:"JetBrains Mono",monospace}}
  .subrow{{grid-column:1/-1;background:#f4f1e8;border:1px solid var(--border);
    border-radius:6px;padding:12px;display:none}}
  .subrow.open{{display:block}}
  .subgrid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:8px}}
  /* Phone: four cards across is ~85px each — the KDE and the return both become
     illegible. Two-up. This block is an iframe with a fixed 1400px height, so the
     taller stack scrolls inside it (scrolling=True); a height that follows the
     content needs a JS→Streamlit round trip and is not worth it here. */
  @media (max-width:640px){{
    .heat,.subgrid{{grid-template-columns:repeat(2,1fr)}}
    .sectitle{{letter-spacing:.08em}}
  }}
  .subhdr{{font-family:"JetBrains Mono",monospace;font-size:11px;letter-spacing:.1em;
    color:var(--accent);text-transform:uppercase}}
</style>

<div class="sectitle">2 · Sector / subsector heatmap
  <span class="sub" style="text-transform:none;letter-spacing:0"> — as of {as_of} · click a sector to expand subsectors</span></div>
<div class="heat" id="heat"></div>

<script>
const SECTORS = {data_js};
const MIN_NAMES = {MIN_NAMES};
const H_LO={HIST_LO}, H_HI={HIST_HI}, H_BINS={HIST_BINS};  // fixed return-bin axis (%)

// Density from the real per-name return histogram: one filled area over fixed
// bins (shared x-axis across cards). A light 3-tap smooth softens the staircase.
// today's median = solid marker; 0% = dashed reference.
function kde(hist, med){{
  const w=180,h=42,pad=4, n=hist.length;
  const X=v=>pad+((Math.max(H_LO,Math.min(H_HI,v))-H_LO)/(H_HI-H_LO))*(w-2*pad);
  const sm=hist.map((_,i)=>(hist[Math.max(0,i-1)]+2*hist[i]+hist[Math.min(n-1,i+1)])/4);
  const maxd=Math.max(...sm)||1;
  const bx=i=>pad+(i/(n-1))*(w-2*pad);
  let d=`M ${{pad}} ${{h-pad}}`;
  sm.forEach((v,i)=>{{d+=` L ${{bx(i).toFixed(1)}} ${{(h-pad-(v/maxd)*(h-2*pad)).toFixed(1)}}`;}});
  d+=` L ${{w-pad}} ${{h-pad}} Z`;
  const col=med>=0?"var(--positive)":"var(--negative)";
  const mx=X(med), zx=X(0);
  return `<svg class="kde" width="${{w}}" height="${{h}}" viewBox="0 0 ${{w}} ${{h}}">
    <path d="${{d}}" fill="${{col}}" fill-opacity=".14" stroke="${{col}}" stroke-width="1.3" opacity=".85"/>
    <line x1="${{zx}}" y1="6" x2="${{zx}}" y2="${{h-pad}}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="2 2" opacity=".5"/>
    <line x1="${{mx}}" y1="4" x2="${{mx}}" y2="${{h-pad}}" stroke="${{col}}" stroke-width="2"/>
  </svg>`;
}}
function sclass(r){{return r>=0?"pos":"neg"}}
function sign(r){{return (r>=0?"+":"")+r.toFixed(2)+"%"}}

function scard(s,isSub){{
  const partT=(s.trend/s.cos*100), partB=(s.brk/s.cos*100);
  return `<div class="card scard" ${{isSub?"":`onclick="toggle(this)"`}} data-name="${{s.name}}">
    <div class="row1"><span class="name">${{s.name}}</span><span class="ret ${{sclass(s.ret)}}">${{sign(s.ret)}}</span></div>
    <div class="sub mono">${{s.cos}} names</div>
    ${{kde(s.hist,s.ret)}}
    <div class="breadth"><span class="pos">▲${{s.up}}</span><span class="neg">▼${{s.down}}</span></div>
    <div class="partbar" title="trend_ok / breakout_ok">
      <i style="width:${{partT}}%;background:var(--accent)"></i>
      <i style="width:${{partB}}%;background:var(--rust)"></i></div>
    ${{isSub?"":`<div class="addnote">trend ${{s.trend}} · brk ${{s.brk}} · +${{s.add1}} today · +${{s.add5}} 5d</div>`}}
  </div>`;
}}

function render(){{
  let html='';
  SECTORS.forEach((s,i)=>{{
    html+=scard(s,false);
    const big=s.subs.filter(x=>x.cos>=MIN_NAMES);
    const small=s.subs.filter(x=>x.cos<MIN_NAMES);
    let subs=big.map(x=>scard(x,true)).join('');
    if(small.length){{
      const merged=Array(H_BINS).fill(0);
      small.forEach(x=>x.hist.forEach((c,j)=>merged[j]+=c));
      // representative center = count-weighted mean of bin centers.
      const bw=(H_HI-H_LO)/H_BINS, tot=merged.reduce((a,c)=>a+c,0)||1;
      const ctr=merged.reduce((a,c,j)=>a+c*(H_LO+(j+0.5)*bw),0)/tot;
      const roll=k=>small.reduce((a,x)=>a+x[k],0);
      subs+=scard({{name:`Other (${{small.length}})`,cos:roll('cos'),ret:ctr,hist:merged,
        up:roll('up'),down:roll('down'),trend:roll('trend'),brk:roll('brk')}},true);
    }}
    html+=`<div class="subrow" id="sub-${{i}}">
      <div class="subhdr">${{s.name}} — subsectors</div>
      <div class="subgrid">${{subs||'<span class=sub>no subsectors</span>'}}</div></div>`;
  }});
  document.getElementById('heat').innerHTML=html;
}}
function toggle(el){{
  const cards=[...document.querySelectorAll('#heat > .scard')];
  const i=cards.indexOf(el);
  if(i>=0) document.getElementById('sub-'+i).classList.toggle('open');
}}
render();
</script>
"""
    components.html(html, height=1400, scrolling=True)


st.markdown("### Market Regime & Macro")
st.caption("Where to deploy, and whether to deploy at all.")

_render_s1(load_macro_pillars(), load_weather_gauge(), load_regime(), load_fear_greed())

df = load_sector_breadth()
if df is None or df.empty:
    st.info("sector_breadth snapshot not found — run "
            "`python -c \"from src.sector_breadth_engine import SectorBreadthEngine; "
            "SectorBreadthEngine().refresh()\"` (or the nightly pipeline Phase 7.46).")
else:
    _render(df)

_render_s3(load_macro_indicators(SPARK_DAYS))
