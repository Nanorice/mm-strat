"""Portfolio — the book of record for real money (sprint-14 dashboard uplift).

Reads the hand-entered `trades` fill log (append-only; entered via
`scripts/portfolio.py`). Positions are DERIVED from fills, never stored, so a
scale-in or partial exit needs no schema change.

Honesty rules binding this page (cf. Screening's):
  1. **Return is TIME-WEIGHTED off a cash-inclusive NAV.** External flows are
     stripped from the day they land, so a deposit is not a gain. This is what
     makes YTD/drawdown truthful; a naive nav.pct_change() would not be.
  2. **The model score is RAW, not calibrated** — same rule as Screening. 0.79 is
     a strong RANK, not "a 79% chance". Labelled "Score (raw)", never "P(...)".
  3. **An unscored holding shows "—", never a stale or zero score.** The model
     scores only the SEPA lifecycle universe (~751 of ~3,980 active names); a
     holding outside it has no opinion attached, and we say so.
  4. **Unrealized P&L is a mark, not a result.** It moves with the last close and
     is only realized on exit.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dashboard_utils import (load_cash, load_nav_history, load_portfolio,
                            load_portfolio_risk, load_returns)

# theta.md tokens (mirror scripts/pages/3_Screening.py).
_CSS = """
<style>
  .pf-title{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:11px;
    letter-spacing:.18em;text-transform:uppercase;color:#8a8272;
    border-bottom:1px solid #e8e3d6;padding-bottom:8px;margin:2px 0 12px}
  .pf-stats{display:flex;gap:26px;font-family:"JetBrains Mono",monospace;
    font-variant-numeric:tabular-nums;font-size:13px;color:#1c1a17;margin-bottom:4px}
  .pf-stats b{font-size:20px;font-weight:600}
  .pf-stats .lbl{color:#8a8272;font-size:11px;text-transform:uppercase;letter-spacing:.1em}
  .pf-stats .col{display:flex;flex-direction:column;gap:2px}
  .pf-pos{color:#1a7f4b} .pf-neg{color:#b3341f}
  .pf-note{font-family:"Source Serif 4",Georgia,serif;font-size:12px;color:#6f6858;
    border-left:2px solid #e8e3d6;padding-left:10px;margin:14px 0 2px}
</style>
"""


def _money(v: float) -> str:
    return f"{v:,.2f}" if pd.notna(v) else "—"


def _signed(v: float) -> str:
    if pd.isna(v):
        return "—"
    cls = "pf-pos" if v >= 0 else "pf-neg"
    return f'<span class="{cls}">{v:+,.2f}</span>'


def _pct(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    cls = "pf-pos" if v >= 0 else "pf-neg"
    return f'<span class="{cls}">{v * 100:+.1f}%</span>'


def _ytd_return(rets: pd.DataFrame):
    """Year-to-date time-weighted return: compound this calendar year's dailies."""
    if rets.empty:
        return None
    this_year = pd.to_datetime(rets["date"]).dt.year == pd.Timestamp.today().year
    r = rets.loc[this_year, "ret"]
    return (1 + r).prod() - 1 if len(r) else None


def _render_risk(pos: pd.DataFrame, nav: float) -> None:
    """Risk = a DESCRIPTION of exposure, never a signal.

    Deliberately no VaR / expected shortfall: at ~4 concentrated same-sector names
    the covariance term dominates, and a normal-ish VaR over a 172-bar window
    prints a comfortable number right up to the regime that breaks it.

    Deliberately no exit/stop suggestions either. Every acting overlay we have
    cone-tested LOST — DD circuit breaker (swept 6-30%: mechanism, not threshold),
    earnings blackout (force-exits 23.6% of the book, 77% of them winners), VIX
    de-risking (backwards: VIX>30 days are the best). Only SPY>200d survived.
    So: ATR tells you how much room a name needs. It does not tell you to sell.
    """
    risk = load_portfolio_risk()
    if risk.empty:
        return

    st.markdown('<div class="pf-title" style="margin-top:26px">'
                'Risk · exposure, not signals</div>', unsafe_allow_html=True)

    risk = risk.copy()
    risk["atr_pct_nav"] = risk["atr_move_value"] / nav * 100 if nav else pd.NA

    # Book-level reads. Beta is weighted by market value, not by name count.
    mv = pos.set_index("ticker")["market_value"]
    b = risk.set_index("ticker")["beta"].reindex(mv.index)
    book_beta = (mv * b).sum() / mv[b.notna()].sum() if b.notna().any() else None
    atr_book = risk["atr_pct_nav"].sum()

    st.markdown(
        f'<div class="pf-stats">'
        f'<div class="col"><span class="lbl">Book beta (mv-wtd)</span>'
        f'<b>{f"{book_beta:.2f}" if book_beta is not None else "—"}</b></div>'
        f'<div class="col"><span class="lbl">1-ATR move, whole book</span>'
        f'<b>{atr_book:.2f}% of NAV</b></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.dataframe(
        risk[["ticker", "atr_14", "atr_pct", "atr_pct_nav", "vol_20d", "vol_60d",
              "sup_50d", "res_50d", "atr_to_sup_50d", "atr_to_res_50d",
              "high_52w", "low_52w", "beta"]],
        hide_index=True, use_container_width=True,
        column_config={
            "ticker":   st.column_config.TextColumn("Ticker"),
            "atr_14":   st.column_config.NumberColumn("ATR(14)", format="%.2f"),
            "atr_pct":  st.column_config.NumberColumn(
                "ATR %", format="%.2f%%", help="ATR as % of last close — the name's daily noise band."),
            "atr_pct_nav": st.column_config.NumberColumn(
                "1-ATR / NAV", format="%.2f%%",
                help="What a 1-ATR move in this name costs the BOOK. Per-name noise "
                     "turned into portfolio impact."),
            "vol_20d":  st.column_config.NumberColumn("Vol 20d", format="%.0f%%"),
            "vol_60d":  st.column_config.NumberColumn("Vol 60d", format="%.0f%%"),
            "sup_50d":  st.column_config.NumberColumn("Sup 50d", format="%.2f"),
            "res_50d":  st.column_config.NumberColumn("Res 50d", format="%.2f"),
            "atr_to_sup_50d": st.column_config.NumberColumn(
                "→Sup (ATR)", format="%.1f",
                help="Distance to 50d support in ATR units — comparable across names; "
                     "dollars are not."),
            "atr_to_res_50d": st.column_config.NumberColumn("→Res (ATR)", format="%.1f"),
            "high_52w": st.column_config.NumberColumn(
                "52w high", format="%.2f",
                help="Read from t3 (precomputed). '—' = outside the SEPA screen; a true "
                     "52w level can't be recomputed from the slim DB's ~172-bar window."),
            "low_52w":  st.column_config.NumberColumn("52w low", format="%.2f"),
            "beta":     st.column_config.NumberColumn("Beta", format="%.2f"),
        },
    )

    n_no52 = int(risk["high_52w"].isna().sum())
    if n_no52:
        st.caption(
            f"{n_no52} of {len(risk)} holdings sit outside the SEPA screen, so their "
            f"52w levels show —. ATR / vol / support-resistance come from `price_data` "
            f"and cover every holding."
        )

    st.markdown(
        '<div class="pf-note">These are <b>descriptions of exposure, not signals</b>. '
        'ATR says how much room a name needs; it does not say to sell. No VaR or '
        'expected shortfall: with a concentrated same-sector book the covariance term '
        'dominates and a window-fitted VaR would print calm right up to the regime that '
        'breaks it. No stop/exit suggestions: every acting overlay we cone-tested '
        '(DD brake, earnings blackout, VIX de-risking) LOST — only SPY&gt;200d survived.'
        '</div>',
        unsafe_allow_html=True,
    )


def render() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown('<div class="pf-title">Portfolio · book of record</div>',
                unsafe_allow_html=True)

    pos = load_portfolio()

    if pos.empty:
        st.info(
            "**No open positions.** Log fills from the CLI — positions and NAV "
            "derive from the log automatically:\n\n"
            "```\n"
            "python scripts/portfolio.py buy  NVDA --qty 100 --price 178.40 --date 2026-07-16\n"
            "python scripts/portfolio.py sell NVDA --qty 40  --price 191.05\n"
            "python scripts/portfolio.py positions\n"
            "python scripts/portfolio.py nav\n"
            "```"
        )
        return

    mv = pos["market_value"].sum()
    pnl = pos["unrealized_pnl"].sum()
    cash = load_cash()
    nav = cash + mv

    # % NLV — weight of each position in the book (NLV = cash + positions).
    pos = pos.copy()
    pos["pct_nlv"] = pos["market_value"] / nav * 100 if nav else pd.NA

    rets = load_returns()
    ytd = _ytd_return(rets)
    mdd = rets["drawdown"].min() if not rets.empty else None

    st.markdown(
        f'<div class="pf-stats">'
        f'<div class="col"><span class="lbl">NAV</span><b>{_money(nav)}</b></div>'
        f'<div class="col"><span class="lbl">Cash</span><b>{_money(cash)}</b></div>'
        f'<div class="col"><span class="lbl">Positions value</span><b>{_money(mv)}</b></div>'
        f'<div class="col"><span class="lbl">Unrealized</span><b>{_signed(pnl)}</b></div>'
        f'<div class="col"><span class="lbl">YTD (TWR)</span><b>{_pct(ytd)}</b></div>'
        f'<div class="col"><span class="lbl">Max drawdown</span><b>{_pct(mdd)}</b></div>'
        f'<div class="col"><span class="lbl">Positions</span><b>{len(pos)}</b></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    if rets.empty:
        st.caption("YTD / drawdown need at least two `portfolio.py nav` snapshots — "
                   "they show — until the NAV series has a history.")

    # Concentration — plain arithmetic on the book, no invented composite score.
    if len(pos) and nav:
        top3 = pos.nlargest(3, "market_value")["market_value"].sum() / nav * 100
        st.markdown(
            f'<div class="pf-stats" style="margin-top:6px">'
            f'<div class="col"><span class="lbl">Top-3 share</span><b>{top3:.0f}%</b></div>'
            f'<div class="col"><span class="lbl">Largest</span>'
            f'<b>{pos.iloc[0]["ticker"]} {pos.iloc[0]["pct_nlv"]:.0f}%</b></div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    unpriced = pos[pos["close"].isna()]["ticker"].tolist()
    if unpriced:
        st.warning(
            f"No `price_data` for {', '.join(unpriced)} — marked NULL and excluded "
            f"from the totals above (an honest gap, not a stale mark)."
        )

    st.dataframe(
        pos[["ticker", "qty", "avg_cost", "close", "market_value", "pct_nlv",
             "unrealized_pnl", "pct_return", "score_raw", "cohort", "sector",
             "first_entry", "n_fills"]],
        hide_index=True,
        use_container_width=True,
        column_config={
            "ticker":         st.column_config.TextColumn("Ticker"),
            "qty":            st.column_config.NumberColumn("Qty", format="%.4g"),
            "avg_cost":       st.column_config.NumberColumn("Avg cost", format="%.2f"),
            "close":          st.column_config.NumberColumn("Last", format="%.2f"),
            "market_value":   st.column_config.NumberColumn("Mkt value", format="%.2f"),
            "pct_nlv":        st.column_config.NumberColumn("% NLV", format="%.1f%%"),
            "unrealized_pnl": st.column_config.NumberColumn("Unrealized", format="%+.2f"),
            "pct_return":     st.column_config.NumberColumn("Return %", format="%+.2f%%"),
            # RAW score, not calibrated — a rank, not a probability (see docstring).
            "score_raw":      st.column_config.NumberColumn(
                "Score (raw)", format="%.3f",
                help="Prod model's raw score — a RANK, not a probability. "
                     "'—' = outside the scored universe (no opinion), not a zero."),
            "cohort":         st.column_config.TextColumn(
                "Cohort", help="Lifecycle state on the model's latest run: "
                               "active / pre_breakout / removed."),
            "sector":         st.column_config.TextColumn("Sector"),
            "first_entry":    st.column_config.DateColumn("First entry"),
            "n_fills":        st.column_config.NumberColumn("Fills", format="%d"),
        },
    )

    n_unscored = int(pos["score_raw"].isna().sum())
    if n_unscored:
        st.caption(
            f"{n_unscored} of {len(pos)} holdings sit outside the model's scored "
            f"universe (it scores the SEPA lifecycle names only, ~751 of ~3,980 "
            f"active). They show — because the model has no opinion on them."
        )

    # Sector tilt — the honest version of the mock's subsector donut.
    tilt = (pos.dropna(subset=["sector", "market_value"])
               .groupby("sector")["market_value"].sum().sort_values(ascending=False))
    if len(tilt):
        st.markdown('<div class="pf-title" style="margin-top:22px">Sector tilt</div>',
                    unsafe_allow_html=True)
        st.dataframe(
            pd.DataFrame({"sector": tilt.index,
                          "market_value": tilt.values,
                          "pct_nlv": tilt.values / nav * 100 if nav else 0}),
            hide_index=True, use_container_width=True,
            column_config={
                "sector":       st.column_config.TextColumn("Sector"),
                "market_value": st.column_config.NumberColumn("Mkt value", format="%.2f"),
                "pct_nlv":      st.column_config.ProgressColumn(
                    "% NLV", format="%.1f%%", min_value=0,
                    max_value=float(tilt.max() / nav * 100) if nav else 1),
            },
        )

    _render_risk(pos, nav)

    navh = load_nav_history()
    if len(navh) > 1:
        st.markdown('<div class="pf-title" style="margin-top:22px">'
                    'NAV · cash + positions</div>', unsafe_allow_html=True)
        st.line_chart(navh.set_index("date")["nav"], height=180)
        if not rets.empty:
            st.markdown('<div class="pf-title" style="margin-top:14px">'
                        'Cumulative return · time-weighted</div>', unsafe_allow_html=True)
            st.line_chart(rets.set_index("date")["cum_ret"], height=140)

    st.markdown(
        '<div class="pf-note">NAV = <b>cash + positions</b>. Return is '
        '<b>time-weighted</b>: external deposits/withdrawals are stripped from the day '
        'they land, so a contribution is never counted as a gain and the series is '
        'comparable to a benchmark. Unrealized P&amp;L is a mark to the last close, '
        'realized only on exit. <b>Score is RAW</b> — a rank, not a probability — and '
        '&mdash; means the model has no opinion, not a zero.</div>',
        unsafe_allow_html=True,
    )


render()
