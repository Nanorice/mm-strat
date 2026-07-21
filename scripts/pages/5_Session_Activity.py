"""Session activity log — what the screener opened and closed (sprint-14 uplift).

The read surface for `screener_watchlist`: the SEPA **session** store, i.e. every
entry→exit cycle the screener has run. Replaces the old Today page's "Screener
Watchlist" + "Watchlist Activity" pair, which were two views of this one table
(a holdings-style grid and an event feed) sitting under names that implied two
populations.

🛑 **These are NOT trades.** A session is the screener saying "this name entered a
SEPA setup on D and left on D+n". Nobody bought it. The real book is `trades` on
the Portfolio page — a discretionary fill log with cash and NAV. Mixing the two
was the exact error the switch-over triage caught, so this page never shows P&L
in currency, only per-session % moves.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dashboard_utils import (  # noqa: E402
    finviz_ticker_col,
    finviz_url,
    load_activity_feed,
    load_prod_model_version_id,
    load_recent_exits,
    load_ticker_history,
    load_watchlist,
)

_CSS = """
<style>
  .sa-wrap{font-family:"Source Serif 4",Georgia,serif;color:#1c1a17}
  .sa-title{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:11px;
    letter-spacing:.18em;text-transform:uppercase;color:#8a8272;
    border-bottom:1px solid #e8e3d6;padding-bottom:8px;margin:2px 0 12px}
  .sa-stats{display:flex;gap:26px;font-family:"JetBrains Mono",monospace;
    font-variant-numeric:tabular-nums;font-size:13px;color:#1c1a17;margin-bottom:4px}
  .sa-stats b{font-size:20px;font-weight:600}
  .sa-stats .lbl{color:#8a8272;font-size:11px;text-transform:uppercase;letter-spacing:.1em}
  .sa-stats .col{display:flex;flex-direction:column;gap:2px}
</style>
"""

_EVENT_GLYPH = {
    "TRADE_EXIT": "● session closed",
    "UNIVERSE_ADD": "＋ universe add",
    "UNIVERSE_REMOVE": "－ universe remove",
}

_RET = st.column_config.NumberColumn("Return %", format="%+.2f", width="small")
_DAYS = st.column_config.NumberColumn("Days", format="%d", width="small")


def _html(markup: str) -> None:
    """Emit raw HTML. Streamlit markdown-parses first and treats >=4-space
    indents as code blocks, so strip per-line leading whitespace."""
    st.markdown("\n".join(l.lstrip() for l in markup.splitlines()),
                unsafe_allow_html=True)


def _header(wl: pd.DataFrame) -> None:
    n_active = int((wl["status"] == "ACTIVE").sum()) if len(wl) else 0
    n_total = len(wl)
    as_of = str(wl["price_date"].max())[:10] if len(wl) and "price_date" in wl else "—"
    _html(_CSS + f"""
    <div class="sa-wrap">
      <div class="sa-title">SA · Session activity — screener open/close history · as of {as_of}</div>
      <div class="sa-stats">
        <div class="col"><span class="lbl">Open sessions</span><b>{n_active}</b></div>
        <div class="col"><span class="lbl">All sessions</span><b>{n_total:,}</b></div>
      </div>
    </div>
    """)


def _render_open(wl: pd.DataFrame) -> None:
    """Currently-open sessions. Sorted by days_held desc — the oldest open session
    is the one most worth a look, which a date sort buries."""
    open_s = wl[wl["status"] == "ACTIVE"].copy()
    if open_s.empty:
        st.info("No open sessions.")
        return
    open_s = open_s.sort_values("days_held", ascending=False, na_position="last")
    cols = {
        "ticker": finviz_ticker_col(pinned=True),
        "company_name": st.column_config.TextColumn("Name", width="medium"),
        "sector": st.column_config.TextColumn("Sector", width="small"),
        "entry_date": st.column_config.DateColumn("Opened", width="small"),
        "entry_price": st.column_config.NumberColumn("Entry", format="$%.2f", width="small"),
        "close_price": st.column_config.NumberColumn("Last", format="$%.2f", width="small"),
        "pct_return": _RET,
        "days_held": _DAYS,
    }
    open_s = open_s.assign(ticker=open_s["ticker"].apply(finviz_url))
    have = [c for c in cols if c in open_s.columns]
    st.dataframe(open_s[have], column_config=cols, width='stretch',
                 hide_index=True, height=min(60 + 35 * len(open_s), 560))
    st.caption(f"{len(open_s)} open session{'s' if len(open_s) != 1 else ''} · "
               "oldest first. Move % is the session's mark, not a realized trade.")


def _render_closed(days: int) -> None:
    exits = load_recent_exits(days=days)
    if exits.empty:
        st.info(f"No sessions closed in the last {days} days.")
        return
    cols = {
        "ticker": finviz_ticker_col(pinned=True),
        "company_name": st.column_config.TextColumn("Name", width="medium"),
        "sector": st.column_config.TextColumn("Sector", width="small"),
        "entry_date": st.column_config.DateColumn("Opened", width="small"),
        "exit_date": st.column_config.DateColumn("Closed", width="small"),
        "pct_return": _RET,
        "days_held": _DAYS,
    }
    exits = exits.assign(ticker=exits["ticker"].apply(finviz_url))
    have = [c for c in cols if c in exits.columns]
    st.dataframe(exits[have], column_config=cols, width='stretch',
                 hide_index=True, height=min(60 + 35 * len(exits), 520))
    win = float((exits["pct_return"] > 0).mean() * 100) if exits["pct_return"].notna().any() else float("nan")
    med = exits["pct_return"].median()
    st.caption(
        f"{len(exits)} closed · {win:.0f}% positive · median {med:+.1f}%. "
        "Descriptive only — a session is not a trade, and the median is the wrong "
        "lens on a tail strategy (see Model Lab)."
    )


def _render_feed(days: int) -> None:
    feed = load_activity_feed(days=days)
    if feed.empty:
        st.info(f"No activity in the last {days} days.")
        return
    types = sorted(feed["event_type"].unique())
    picked = st.multiselect("Event types", types, default=types,
                            format_func=lambda t: _EVENT_GLYPH.get(t, t),
                            key="sa_feed_types")
    view = feed[feed["event_type"].isin(picked)] if picked else feed
    disp = view.copy()
    disp["event_type"] = disp["event_type"].map(lambda t: _EVENT_GLYPH.get(t, t))
    cols = {
        "event_date": st.column_config.DateColumn("Date", width="small"),
        "ticker": finviz_ticker_col(pinned=True),
        "company_name": st.column_config.TextColumn("Name", width="medium"),
        "event_type": st.column_config.TextColumn("Event", width="small"),
        "detail": st.column_config.TextColumn("Detail", width="medium"),
    }
    disp = disp.assign(ticker=disp["ticker"].apply(finviz_url))
    have = [c for c in cols if c in disp.columns]
    st.dataframe(disp[have], column_config=cols, width='stretch',
                 hide_index=True, height=520)
    st.caption(f"{len(view)} event{'s' if len(view) != 1 else ''} in the last {days} days. "
               "Universe add/remove = the screener's tradable-universe membership "
               "flipping, independent of any session.")


def _render_lookup(version_id: str | None) -> None:
    tk = st.text_input("Ticker", "", placeholder="e.g. AAOI (press Enter)",
                       key="sa_ticker").strip().upper()
    if not tk:
        st.info("Enter a ticker to see every SEPA session it has run.")
        return
    hist = load_ticker_history(tk, version_id)
    if hist.empty:
        st.info(f"No sessions found for {tk}.")
        return
    h = hist.copy()
    # An ACTIVE row's exit_date is the as-of price date, not a realized close —
    # blank it so "Closed" never implies an exit that hasn't happened.
    if "status" in h.columns:
        h.loc[h["status"] == "ACTIVE", "exit_date"] = pd.NaT
    name = h["company_name"].dropna().iloc[0] if h["company_name"].notna().any() else ""
    st.markdown(f"**{tk}** — {name} · {len(h)} session{'s' if len(h) != 1 else ''}")
    cols = {
        "entry_date": st.column_config.DateColumn("Opened", width="small"),
        "entry_price": st.column_config.NumberColumn("Entry", format="$%.2f", width="small"),
        "entry_score": st.column_config.NumberColumn(
            "Score at open", format="%.3f", width="small",
            help="Prod-model RAW score as the signal fired — a rank, not odds. "
                 "NULL for sessions predating the scored window."),
        "exit_date": st.column_config.DateColumn("Closed", width="small"),
        "status": st.column_config.TextColumn("Status", width="small"),
        "close_price": st.column_config.NumberColumn("Last", format="$%.2f", width="small"),
        "pct_return": _RET,
        "days_held": _DAYS,
    }
    have = [c for c in cols if c in h.columns]
    st.dataframe(h[have], column_config=cols, width='stretch',
                 hide_index=True)


st.markdown("### Session activity")
st.caption("Every SEPA session the screener has opened and closed. "
           "**Sessions are not trades** — the real book is on Portfolio.")

wl = load_watchlist()
if wl is None or wl.empty:
    st.info("`screener_watchlist` is empty — run the daily pipeline to populate.")
    st.stop()

_header(wl)

version_id = load_prod_model_version_id()
tab_open, tab_closed, tab_feed, tab_lookup = st.tabs(
    ["Open sessions", "Recently closed", "Activity feed", "Ticker history"]
)

with tab_open:
    _render_open(wl)

with tab_closed:
    d = st.radio("Window", [7, 14, 30], index=1, horizontal=True,
                 format_func=lambda x: f"Last {x}d", key="sa_closed_window")
    _render_closed(int(d))

with tab_feed:
    d = st.radio("Window", [7, 14, 30], index=1, horizontal=True,
                 format_func=lambda x: f"Last {x}d", key="sa_feed_window")
    _render_feed(int(d))

with tab_lookup:
    _render_lookup(version_id)
