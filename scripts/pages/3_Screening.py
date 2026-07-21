"""Screening — the single "what to look at" surface (sprint-14 dashboard uplift).

One population (today's trend_ok ∨ breakout_ok universe), filterable by stage +
fundamentals, ranked by the prod model's raw score. Retires the old Today page's
four overlapping candidate tables (Shortlist / Pre-Breakout / VIP / Screener)
into one view. Reads the nightly-materialized `v_d3_screening`.

Two honesty rules bind this page:
  1. **No point forecasts** — we show a score, never an expected return
     (label-lift != trade-edge; the start-date cone is our truth).
  2. **The score is RAW, not calibrated** — `daily_predictions` stores raw
     softprob (score_engine: "RAW class probabilities only"). The prod binary
     model's positive class is fwd return >30% (`label_thresholds: [30.0]`), but
     the model is overconfident and the isotonic calibrator that would correct it
     is NOT applied here (calibrated 0.15 ~ raw 0.48). So 0.79 is a strong RANK,
     not "a 79% chance". Labelled "Score (raw)" — never "P(...)" — deliberately.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dashboard_utils import (
    finviz_ticker_col, finviz_url, load_screening, load_vip_watchlist,
)

# theta.md tokens (mirror scripts/pages/2_Macro.py) — a scoped strip so the
# native Streamlit widgets below still theme cleanly.
_HEADER_CSS = """
<style>
  .scr-wrap{font-family:"Source Serif 4",Georgia,serif;color:#1c1a17}
  .scr-title{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:11px;
    letter-spacing:.18em;text-transform:uppercase;color:#8a8272;
    border-bottom:1px solid #e8e3d6;padding-bottom:8px;margin:2px 0 12px}
  .scr-stats{display:flex;gap:26px;font-family:"JetBrains Mono",monospace;
    font-variant-numeric:tabular-nums;font-size:13px;color:#1c1a17;margin-bottom:4px}
  .scr-stats b{font-size:20px;font-weight:600}
  .scr-stats .lbl{color:#8a8272;font-size:11px;text-transform:uppercase;letter-spacing:.1em}
  .scr-stats .col{display:flex;flex-direction:column;gap:2px}

  /* Filter form: label on the same line as its control, and a control that stops
     at a readable width. Streamlit stacks label-over-widget and stretches the
     widget to the full column, so a 3-column row gave three ~380px dropdowns
     holding the word "All" — a lot of vertical space and screen for six choices.
     Selectboxes only. The fundamentals row is five columns wide and its labels
     ("Gross margin ≥ %") are longer than its controls — inlining those was
     measured and left the input 11px wide, so they stay stacked. */
  [data-testid="stForm"] [data-testid="stSelectbox"]{
    display:flex;align-items:center;gap:10px}
  [data-testid="stForm"] [data-testid="stSelectbox"] > label{
    flex:0 0 auto;margin:0;white-space:nowrap}
  [data-testid="stForm"] [data-testid="stSelectbox"] > div{
    flex:1 1 auto;min-width:0;max-width:220px}
  /* Phone: back to stacked — inline is a wide-screen affordance. */
  @media (max-width:640px){
    [data-testid="stForm"] [data-testid="stSelectbox"]{display:block}
    [data-testid="stForm"] [data-testid="stSelectbox"] > div{max-width:none}
  }
</style>
"""

# Preset filter combos. Each is a plain predicate over the population — the same
# thing the filter row does by hand, saved. (Replaces the old "Aggressive picks"
# strip, which was pure overlap: it was just cap_tier in {small,micro} + score
# desc, i.e. reproducible from the filters already on this page.)
#
# NULL fundamentals are treated as "unknown, keep" everywhere EXCEPT where a
# preset's whole point is the constraint (e.g. Value needs a real P/E) — a
# pre-report name shouldn't silently pass a quality screen it was never tested on.
PRESETS: dict[str, str] = {
    "None (all filters manual)": "",
    "Aggressive — small-cap tail":
        "small/micro cap, ranked by score. The tail cell the research says the "
        "edge lives in (strong-RS x small-cap); liquidity-capped in practice.",
    "Growth — revenue & EPS compounding":
        "revenue growth >= 20% and EPS growth > 0. Ignores valuation.",
    "Value — cheap and profitable":
        "P/E between 0 and 20, FCF positive. Requires a real P/E (unprofitable "
        "names are excluded, not kept).",
    "Conservative — quality balance sheet":
        "net margin >= 10%, FCF positive, debt/equity <= 1. Requires the "
        "fundamentals to exist.",
}


def _apply_preset(d: pd.DataFrame, preset: str) -> pd.DataFrame:
    """Preset -> filtered frame. Kept as data-in/data-out so it's unit-testable."""
    if preset.startswith("Aggressive"):
        return d[d["cap_tier"].isin(["small", "micro"])]
    if preset.startswith("Growth"):
        return d[(d["revenue_growth_yoy"] >= 20) & (d["eps_growth_yoy"] > 0)]
    if preset.startswith("Value"):
        return d[(d["pe_ratio"] > 0) & (d["pe_ratio"] <= 20) & (d["fcf_positive"] == True)]  # noqa: E712
    if preset.startswith("Conservative"):
        return d[(d["net_margin"] >= 10) & (d["fcf_positive"] == True)  # noqa: E712
                 & (d["debt_to_equity"] <= 1)]
    return d


def _html(markup: str) -> None:
    """Emit raw HTML through st.markdown.

    Streamlit markdown-parses the string first, and treats any line indented >=4
    spaces as a CODE BLOCK — so indented markup renders as literal text. Strip
    per-line leading whitespace before it reaches the parser.
    """
    st.markdown("\n".join(l.lstrip() for l in markup.splitlines()),
                unsafe_allow_html=True)


def _header(df: pd.DataFrame) -> None:
    as_of = str(df["date"].iloc[0])[:10] if len(df) else "—"
    n = len(df)
    n_setup = int((df["stage"] == "setup").sum())
    n_trig = int((df["stage"] == "triggered").sum())
    n_scored = int(df["prob_home_run"].notna().sum())
    _html(_HEADER_CSS + f"""
    <div class="scr-wrap">
      <div class="scr-title">SC · Screening — what to look at · as of {as_of}</div>
      <div class="scr-stats">
        <div class="col"><span class="lbl">Universe</span><b>{n}</b></div>
        <div class="col"><span class="lbl">Setup</span><b>{n_setup}</b></div>
        <div class="col"><span class="lbl">Triggered</span><b>{n_trig}</b></div>
        <div class="col"><span class="lbl">Scored</span><b>{n_scored}</b></div>
      </div>
    </div>
    """)


def _cap_tier(mcap: float) -> str:
    if pd.isna(mcap):
        return "—"
    if mcap >= 10e9:
        return "large"
    if mcap >= 2e9:
        return "mid"
    if mcap >= 300e6:
        return "small"
    return "micro"


def _fmt_mcap(m: float) -> str:
    """Compact market cap: $1.2B / $340M. Blank when unknown."""
    if pd.isna(m):
        return "—"
    if m >= 1e12:
        return f"${m / 1e12:.2f}T"
    if m >= 1e9:
        return f"${m / 1e9:.1f}B"
    if m >= 1e6:
        return f"${m / 1e6:.0f}M"
    return f"${m:,.0f}"


_TABLE_COLS = {
    # Pinned: this table is 17 columns wide, so on a phone the ticker is off-screen
    # before you reach Score. Frozen left, every row stays identifiable.
    "ticker": finviz_ticker_col(pinned=True),
    "company_name": st.column_config.TextColumn("Name", width="medium"),
    "sector": st.column_config.TextColumn("Sector", width="small"),
    "stage": st.column_config.TextColumn("Stage", width="small"),
    # "In play since" trio. `anchor_date` is the ACTIVE session entry when there is
    # one, else the start of the current trend_ok run — see _create_v_d3_screening.
    "anchor_date": st.column_config.DateColumn(
        "Since", width="small",
        help="When this name became actionable: its open SEPA session's entry date, "
             "or — for names with no session yet — the first day of the current "
             "unbroken trend_ok run. Blank for a breakout that fired from outside "
             "the trend template (no run, no session: nothing to date yet)."),
    "anchor_close": st.column_config.NumberColumn(
        "Px @ since", format="$%.2f", width="small",
        help="Close on the Since date. Unadjusted, like every price here."),
    "close": st.column_config.NumberColumn("Price", format="$%.2f", width="small",
                                           help="Latest close."),
    "pct_return": st.column_config.NumberColumn(
        "Δ %", format="%.1f%%", width="small",
        help="Price vs Px @ since. Not a trade P&L — no stop, no exit, no sizing."),
    # RAW model score — deliberately NOT called "P(...)": daily_predictions stores
    # uncalibrated softprob, so this ranks, it does not state odds.
    "prob_home_run": st.column_config.NumberColumn(
        "Score (raw)", format="%.3f", width="small",
        help="Prod binary model's RAW score for fwd return >30%. Uncalibrated — "
             "the model is overconfident, so read this as a RANK, not a probability."),
    "mcap": st.column_config.TextColumn("Mkt cap", width="small"),
    # The two clocks behind `anchor_date`, kept visible so the anchor is auditable.
    "trend_start_date": st.column_config.DateColumn(
        "Trend since", width="small",
        help="First day of the current unbroken trend_ok run (C1-C9 template). "
             "Capped at a 400-day lookback."),
    "entry_date": st.column_config.DateColumn(
        "Entry", width="small",
        help="Entry date of the open SEPA session (trend_ok ∧ breakout_ok, held to a "
             "C1∨C2∨C6 exit). Blank when the name has never opened one. This — not "
             "`stage` — is the persistent 'triggered' state: breakout_ok is a "
             "same-day event flag, so a triggered row always broke out TODAY."),
    "gross_margin": st.column_config.NumberColumn("Gross %", format="%.0f", width="small"),
    "net_margin": st.column_config.NumberColumn("Net %", format="%.0f", width="small"),
    "pe_ratio": st.column_config.NumberColumn("P/E", format="%.1f", width="small"),
    "fcf": st.column_config.TextColumn("FCF", width="small"),
    "revenue_growth_yoy": st.column_config.NumberColumn("Rev g %", format="%.0f", width="small"),
    "rs_universe_rank": st.column_config.NumberColumn("RS", format="%.2f", width="small"),
}


def _default_order(d: pd.DataFrame, as_of) -> pd.DataFrame:
    """Fresh first, then triggered, then score — the read order of the page.

    "Fresh" is anchor_date == the SNAPSHOT's date, not wall-clock today: on a
    Sunday, or any morning before the nightly run lands, wall-clock would mark
    every row stale and silently flatten the first sort key.
    """
    anchor = pd.to_datetime(d["anchor_date"], errors="coerce")
    return d.assign(
        _fresh=anchor.eq(pd.to_datetime(as_of)),
        _trig=d["stage"].eq("triggered"),
    ).sort_values(
        ["_fresh", "_trig", "prob_home_run"],
        ascending=False, na_position="last",
    ).drop(columns=["_fresh", "_trig"])


def _shape(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["mcap"] = out["market_cap"].apply(_fmt_mcap)
    out["fcf"] = np.where(out["fcf_positive"].fillna(False), "＋", "－")
    out["stage"] = out["stage"].map({"setup": "◔ setup", "triggered": "● triggered"})
    out["ticker"] = out["ticker"].apply(finviz_url)
    return out[list(_TABLE_COLS.keys())]


st.markdown("### Screening")
st.caption("Every name in setup or triggered, ranked by the prod model's raw score — "
           "a **rank, not odds** (see below).")
with st.expander("How to read the score"):
    st.markdown(
        "- The prod binary model's positive class is a **forward return >30%** "
        "(`label_thresholds: [30.0]`).\n"
        "- The value shown is **raw softprob — uncalibrated**. `daily_predictions` "
        "stores raw scores only; the isotonic calibrator that would correct the "
        "model's overconfidence is *not* applied here (calibrated 0.15 ≈ raw 0.48).\n"
        "- So **0.79 is not a 79% chance.** Use it to rank, not to size.\n"
        "- **No expected-return column, by design** — the median inverts, so a point "
        "forecast would mislead. We present tail-odds (cf. the champion start-date cone).\n"
        "- Blank score = the name isn't in a scored cohort. An honest gap, not a stale value."
    )
with st.expander("How to read the dates"):
    st.markdown(
        "- **Stage does not date itself.** `breakout_ok` is a *same-day event flag* "
        "(`breakout = 1 AND volume/vol_avg_50 > 1.3`), not a sticky state — so every "
        "**● triggered** row broke out **today**. A literal \"day of breakout\" column "
        "would read today's date and 0.00% on every triggered name.\n"
        "- So **Since** anchors to the sharper available date: the **Entry** of an open "
        "SEPA session where one exists (`trend_ok ∧ breakout_ok`, held to a C1∨C2∨C6 "
        "exit — the persistent notion of *triggered*), otherwise **Trend since**, the "
        "first day of the current unbroken trend_ok run.\n"
        "- **Δ %** is Price ÷ Px @ since − 1. It is a **price move, not a trade P&L** — "
        "no stop, no exit rule, no sizing. Prices are unadjusted (`adj_close` is NULL "
        "repo-wide), so a split inside the window will distort it.\n"
        "- **● triggered now means the real SEPA gate** (`trend_ok ∧ breakout_ok`). "
        "Until 2026-07-20 the population was `trend_ok ∨ breakout_ok`, which admitted "
        "names that broke out while *failing* C1-C9 — 42 of 79 \"triggered\" rows, most "
        "never in the trend template at all. They were never tradeable and no scorer "
        "covered them, so they showed as blank rows. Dropped.\n"
        "- A blank **Score** is the last honest gap: t3 features exist only for tickers "
        "that have opened a SEPA session at least once, so a name in setup for the "
        "**first time** has nothing to score yet (13 names). It fills in once it triggers."
    )

df = load_screening()
if df is None or df.empty:
    st.info("v_d3_screening snapshot not found — run the view "
            "(`ViewManager()._create_v_d3_screening`) and rebuild the slim DB.")
    st.stop()

df["cap_tier"] = df["market_cap"].apply(_cap_tier)
_header(df)

with st.form("screening_filters", border=True):
    # Row 1 — preset + population. Row 2 — fundamentals. Two labelled bands beat
    # eight equal-weight boxes: the preset drives, population narrows, fundamentals
    # refine. Thresholds default to None ("no filter") rather than a -1000/0
    # sentinel — an empty box reads as "off", a magic number reads as broken.
    preset = st.selectbox(
        "Preset", list(PRESETS.keys()), index=0,
        help="A saved filter combo — stacks with the filters below.")

    st.caption("POPULATION")
    p1, p2, p3 = st.columns(3)
    stage_f = p1.selectbox("Stage", ["All", "Setup", "Triggered"], index=0)
    sector_f = p2.selectbox("Sector", ["All"] + sorted(df["sector"].dropna().unique()))
    cap_f = p3.selectbox("Market cap", ["All", "large", "mid", "small", "micro"])

    st.caption("FUNDAMENTALS · blank = no filter")
    f1, f2, f3, f4, f5 = st.columns(5)
    gm_min = f1.number_input("Gross margin ≥ %", value=None, step=5, placeholder="—")
    nm_min = f2.number_input("Net margin ≥ %", value=None, step=5, placeholder="—")
    rg_min = f3.number_input("Rev growth ≥ %", value=None, step=5, placeholder="—")
    pe_max = f4.number_input("P/E ≤", value=None, step=5, placeholder="—")
    with f5:
        st.write("")  # baseline the checkbox against the inputs' labels
        fcf_only = st.checkbox("FCF positive", value=False)

    st.form_submit_button("Apply", type="primary")

if PRESETS[preset]:
    st.caption(f"**{preset}** — {PRESETS[preset]}")

d = _apply_preset(df, preset)
if stage_f != "All":
    d = d[d["stage"] == stage_f.lower()]
if sector_f != "All":
    d = d[d["sector"] == sector_f]
if cap_f != "All":
    d = d[d["cap_tier"] == cap_f]
if fcf_only:
    d = d[d["fcf_positive"] == True]  # noqa: E712 — NaN → excluded, intended
# Manual fundamental thresholds: a NULL fundamental means "unknown", not "fails" —
# only drop a row when the value is present AND below the bar (keeps pre-report
# names visible). The presets above are stricter on purpose; see PRESETS.
# `None` = box left blank = filter off.
if gm_min is not None:
    d = d[d["gross_margin"].isna() | (d["gross_margin"] >= gm_min)]
if nm_min is not None:
    d = d[d["net_margin"].isna() | (d["net_margin"] >= nm_min)]
if pe_max is not None:
    d = d[d["pe_ratio"].isna() | (d["pe_ratio"] <= pe_max)]
if rg_min is not None:
    d = d[d["revenue_growth_yoy"].isna() | (d["revenue_growth_yoy"] >= rg_min)]

st.caption(f"**{len(d)}** of {len(df)} names match · sorted newest-anchored first, "
           "then triggered, then score")
st.dataframe(_shape(_default_order(d, df["date"].iloc[0])), column_config=_TABLE_COLS,
             width='stretch', hide_index=True, height=620)

# ── watchlist ────────────────────────────────────────────────────────────────
# A separate table, NOT a preset: the watchlist is a hand-curated population
# (added via `scripts/vip_add.py`), not a slice of the screening universe. These
# names are force-fed into T3 (`feature_pipeline.py` UNIONs `vip_watchlist` into
# the candidate set), so a name can sit here while failing every screen — which is
# the point (you watch it ripen). That's why it can't be a filter over
# v_d3_screening: most watchlist names aren't in that population at all.
#
# Naming (user, 2026-07-18): the table above is **sepa_active**, this one is the
# **watchlist**. "VIP" is retired as a user-facing word; the underlying table is
# still `vip_watchlist` and stays that way (a rename is a separate migration).

_VIP_STATUS = {  # view's derived status → glyph (most-advanced state wins)
    "not_in_universe": "○ not in universe",
    "watching":        "· watching",
    "trend_ok":        "◔ setup",
    "breakout":        "● breakout",
    "active":          "◆ active",
    "removed":         "✕ removed",
}

_VIP_COLS = {
    "ticker": finviz_ticker_col(pinned=True),
    "status": st.column_config.TextColumn("Status", width="small"),
    "close": st.column_config.NumberColumn("Price", format="$%.2f", width="small"),
    "prob_elite": st.column_config.NumberColumn(
        "Score (raw)", format="%.3f", width="small",
        help="Same raw, uncalibrated prod-model score as the table above — a rank, "
             "not odds. BLANK for any name that has never opened a SEPA session: "
             "the nightly scorer reads v_d3_lifecycle, which inner-joins "
             "screener_watchlist, so a watchlist-only name lands in no cohort and "
             "gets no daily_predictions row. Known gap, deferred — the blank is "
             "honest, not stale."),
    "rs_universe_rank": st.column_config.NumberColumn("RS", format="%.2f", width="small"),
    "added_date": st.column_config.DateColumn("Added", width="small"),
    "source": st.column_config.TextColumn("Source", width="medium"),
    "comment": st.column_config.TextColumn("Note", width="large"),
    "as_of_date": st.column_config.DateColumn("As of", width="small"),
}

st.markdown("#### Watchlist")
st.caption("Hand-curated names, tracked whether or not they pass the screen above.")
vip = load_vip_watchlist()
if vip is None or vip.empty:
    st.caption("No watchlist names yet — add via `python scripts/vip_add.py add NVDA "
               "--source \"semis report\" --comment \"AI capex, watching VCP\"`. "
               "Names take effect on the next nightly T3 run, forward from the add date.")
else:
    v = vip.copy()
    v["status"] = v["status"].map(_VIP_STATUS).fillna(v["status"])
    v["ticker"] = v["ticker"].apply(finviz_url)
    st.caption(f"{len(v)} curated name{'s' if len(v) != 1 else ''} · "
               "CLI-managed (`vip_add.py`); this page is read-only.")
    st.dataframe(v[list(_VIP_COLS.keys())], column_config=_VIP_COLS,
                 width='stretch', hide_index=True,
                 height=min(60 + 35 * len(v), 400))
    if bool(v["as_of_date"].isna().any()):
        st.caption("○ Names with no as-of date have no t3 row yet — just added, or "
                   "not in the price universe. They ripen into the table after the "
                   "next nightly run.")
