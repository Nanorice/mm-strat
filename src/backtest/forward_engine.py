"""Forward step-engine — a synchronous mirror of SEPAHybridV1 for live shadowing.

BackTrader is an event-loop *replayer*: it can't step forward one calendar day
at a time as new data lands. The exit/entry rules in SEPAHybridV1 are pure, but
they're expressed through BackTrader primitives a nightly incremental doesn't
have (async orders + fill confirmation, feed `[0]` indexing, bar-count warmup).
This module re-expresses the *same rules* as a plain `step(day)` over one row
per ticker per day, reusing `PositionTracker` unchanged.

Fidelity to the backtest (what the parity test locks):
  - **Fill = next bar's open** (BackTrader market-order convention). An order
    decided on day T fills at day T+1's open. We mirror this with a one-day
    pending queue: `step(T)` first fills yesterday's queue at T's open, then
    decides T's orders into the queue for T+1.
  - Slippage 0.1% (buys up, sells down) + commission 0.1%, matching the broker.
  - Order sequence within a day is the exact `next()` order: regime-liquidate ->
    update stops -> stops -> targets -> trend -> entries.

ponytail: only the champion's live branches are ported. E2-delay, persistence,
score-drop, rank-exit, warmup and skip-top are asserted-off in `__init__` and
raise if a future config sets them — porting dead branches now just rots.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date as date_cls
from typing import Any, Dict, List, Optional

import pandas as pd

from .position_tracker import PositionTracker
from .score_lookup import ScoreLookup

logger = logging.getLogger(__name__)


def build_price_frame(price_df: pd.DataFrame, sma_period: int = 50) -> pd.DataFrame:
    """Per-(ticker, day) OHLCV + atr14 + sma50, matching the backtest feed exactly.

    This is the G2 fix: the forward engine must see the *same* ATR/SMA the
    BackTrader feed did, or entries/exits diverge. Definitions lifted verbatim
    from SEPABacktestRunner._add_price_feeds_from_duckdb:
      - atr14 = EWM(span=14, adjust=False) of true range,
      - the feed drops the leading NaN-atr row and skips tickers with <50 bars,
      - sma50 = rolling(50).mean() of close (bt SMA emits NaN until 50 bars).

    Input `price_df`: columns ticker, date, open, high, low, close, volume
    (already the backtest window, sorted by ticker,date). Returns the same rows
    minus the dropped NaN-atr leaders, with atr14 + sma50 columns added.
    """
    out: List[pd.DataFrame] = []
    for ticker, df in price_df.groupby("ticker"):
        df = df.sort_values("date").copy()
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ], axis=1).max(axis=1)
        df["atr14"] = tr.ewm(span=14, adjust=False).mean()
        df = df.dropna(subset=["atr14"])
        if len(df) < 50:
            continue  # feed skips these tickers entirely
        df["sma50"] = df["close"].rolling(sma_period).mean()
        out.append(df)
    if not out:
        return pd.DataFrame(columns=list(price_df.columns) + ["atr14", "sma50"])
    return pd.concat(out, ignore_index=True)

# Branches SEPAHybridV1 supports but the champion does not use. The forward
# engine is a faithful mirror *of the champion*; if a future book needs one of
# these, port it deliberately rather than shipping an untested path.
_UNSUPPORTED = {
    "entry_delay_days": 0,
    "warmup_days": 0,
    "min_hold_days": 0,
    "selection_skip_top": 0,
    "exit_use_percentile": False,
    "persistence_window_days": 0,
}


@dataclass
class Action:
    """One thing the book did on a day (mirrors a filled order)."""
    date: date_cls
    ticker: str
    kind: str          # 'enter' | 'target1' | 'target2' | 'stop' | 'trend' | 'regime_liquidation'
    shares: int
    price: float       # fill price (next-open * slippage)
    reason: str
    pnl_pct: Optional[float] = None  # realized, on the sold shares, vs entry


@dataclass
class _PendingOrder:
    ticker: str
    side: str          # 'buy' | 'sell'
    shares: int
    reason: str
    # entry-only intent, carried to confirm_entry on fill
    intent: Optional[Dict[str, Any]] = None


class ChampionBook:
    """A live shadow of one strategy config. Holds a `PositionTracker` and steps
    forward one trading day at a time. `step(day, scores, prices)` returns the
    Actions that filled today.

    `prices` is one row per ticker for `day`: open/high/low/close/volume + atr14
    + sma50, computed by `per_day_price_frame` (definitions match the backtest
    feed — the G2 fix). `scores` is the same DataFrame ScoreLookup indexes.
    """

    def __init__(self, strategy_kwargs: Dict[str, Any], scores_df: pd.DataFrame,
                 initial_cash: float = 25_000.0, commission: float = 0.001,
                 slippage_pct: float = 0.001):
        for k, forbidden_default in _UNSUPPORTED.items():
            v = strategy_kwargs.get(k, forbidden_default)
            if v != forbidden_default:
                raise NotImplementedError(
                    f"ChampionBook does not port the {k!r} branch (got {v!r}). "
                    f"The forward engine mirrors the champion only — add {k} deliberately."
                )
        self.k = strategy_kwargs
        self.tracker = PositionTracker()
        self.score_lookup = ScoreLookup(scores_df)
        self.cash = float(initial_cash)
        self.commission = commission
        self.slippage_pct = slippage_pct
        self._pending: List[_PendingOrder] = []   # decided yesterday, fill at today's open
        # SMA warmup: a position may only trend-exit once its SMA is defined.
        # (Entries need close+atr, which the price frame guarantees.)

    # --- broker helpers -------------------------------------------------------
    def portfolio_value(self, day_prices: pd.DataFrame) -> float:
        """Mark-to-market: cash + sum(remaining_shares * close)."""
        val = self.cash
        for tk, pos in self.tracker.positions.items():
            row = day_prices.loc[day_prices["ticker"] == tk]
            if not row.empty and pos.remaining_shares > 0:
                val += pos.remaining_shares * float(row["close"].iloc[0])
        return val

    def _buy_fill(self, px: float) -> float:
        return px * (1.0 + self.slippage_pct)

    def _sell_fill(self, px: float) -> float:
        return px * (1.0 - self.slippage_pct)

    # --- the step -------------------------------------------------------------
    def step(self, day: date_cls, day_scores_df: pd.DataFrame,
             day_prices: pd.DataFrame) -> List[Action]:
        """Advance one trading day. Returns Actions filled today.

        `day_prices`: rows for `day` (columns ticker, open/high/low/close/volume,
        atr14, sma50). `day_scores_df` is unused directly (ScoreLookup owns the
        full index) but kept in the signature so the caller passes today's slice
        for provenance / future per-day scoring.
        """
        px = {r["ticker"]: r for _, r in day_prices.iterrows()}
        actions: List[Action] = []

        # 1) Fill yesterday's queued orders at TODAY's open (next-open convention).
        actions += self._fill_pending(day, px)

        # 2) Regime gate — liquidate all on strong bear, no further action today.
        regime = self._regime(day)
        if regime == 0:
            self._queue_liquidation("regime_liquidation")
            return actions

        # 3) Update trailing stops (high-water; only trails after T1/T2).
        for tk, pos in self.tracker.positions.items():
            r = px.get(tk)
            if r is not None:
                self.tracker.update_stops(tk, float(r["atr14"]), float(r["high"]))

        # 4) Stops -> 5) targets -> 6) trend  (same order as next()).
        self._check_stops(px)
        self._check_targets(px)
        self._check_trend(px)

        # 7) Entries into free slots. Pass px so sizing marks the book to today's
        #    closes (== broker.getvalue() in the backtest).
        self._process_entries(regime, day, px)
        return actions

    def _broker_value(self, px: Dict[str, Any]) -> float:
        """broker.getvalue() equivalent: cash + held shares marked at today's
        close (falls back to entry_price if a held ticker has no bar today)."""
        val = self.cash
        for tk, pos in self.tracker.positions.items():
            if pos.remaining_shares <= 0:
                continue
            r = px.get(tk)
            close = float(r["close"]) if r is not None else pos.entry_price
            val += pos.remaining_shares * close
        return val

    # --- fills ----------------------------------------------------------------
    def _fill_pending(self, day: date_cls, px: Dict[str, Any]) -> List[Action]:
        acted: List[Action] = []
        still_pending: List[_PendingOrder] = []
        for o in self._pending:
            r = px.get(o.ticker)
            if r is None:
                # No bar today (holiday/halt) — carry the order to the next day,
                # matching BackTrader, which fills on the next available bar.
                still_pending.append(o)
                continue
            open_px = float(r["open"])
            if o.side == "buy":
                fill = self._buy_fill(open_px)
                cost = fill * o.shares * (1.0 + self.commission)
                self.cash -= cost
                self.tracker.confirm_entry(order_ref=id(o), executed_price=fill,
                                           executed_size=o.shares)
                # confirm_entry consumes a pending_entry keyed by order_ref; we
                # register it just-in-time so the tracker owns the intent.
                acted.append(Action(day, o.ticker, "enter", o.shares, fill, "entry"))
            else:
                fill = self._sell_fill(open_px)
                proceeds = fill * o.shares * (1.0 - self.commission)
                self.cash += proceeds
                pos = self.tracker.get_position(o.ticker)
                entry_px = pos.entry_price if pos else fill
                self.tracker.record_partial_exit(
                    ticker=o.ticker, shares_sold=o.shares, exit_price=fill,
                    exit_reason=o.reason, exit_date=day)
                pnl = (fill - entry_px) / entry_px * 100 if entry_px else None
                kind = o.reason if o.reason in ("target1", "target2") else o.reason
                acted.append(Action(day, o.ticker, kind, o.shares, fill, o.reason, pnl))
        self._pending = still_pending
        return acted

    def _queue_buy(self, ticker: str, shares: int, intent: Dict[str, Any]) -> None:
        o = _PendingOrder(ticker=ticker, side="buy", shares=shares, reason="entry",
                          intent=intent)
        # Register the intent so confirm_entry (on fill) can build the position.
        self.tracker.register_entry_intent(order_ref=id(o), intent=intent)
        self._pending.append(o)

    def _queue_sell(self, ticker: str, shares: int, reason: str) -> None:
        self._pending.append(_PendingOrder(ticker=ticker, side="sell",
                                           shares=shares, reason=reason))

    # --- exits (mirror the tracker-driven checks in next()) -------------------
    def _check_stops(self, px: Dict[str, Any]) -> None:
        for tk, pos in list(self.tracker.positions.items()):
            if pos.exit_pending:
                continue
            r = px.get(tk)
            if r is None:
                continue
            if self.tracker.check_stops(tk, float(r["low"])) and pos.remaining_shares > 0:
                self._queue_sell(tk, pos.remaining_shares, "stop")
                pos.exit_pending = True

    def _check_targets(self, px: Dict[str, Any]) -> None:
        for tk, pos in list(self.tracker.positions.items()):
            r = px.get(tk)
            if r is None:
                continue
            hit = self.tracker.check_targets(tk, float(r["high"]))
            if hit == "target1" and not pos.tranche1_sold and not pos.tranche1_pending \
                    and not pos.exit_pending:
                size = pos.tranche_size
                if 0 < size <= pos.remaining_shares:
                    self._queue_sell(tk, size, "target1")
                    pos.tranche1_pending = True
            elif hit == "target2" and not pos.tranche2_sold and not pos.tranche2_pending \
                    and not pos.exit_pending:
                size = pos.tranche_size
                if 0 < size <= pos.remaining_shares:
                    self._queue_sell(tk, size, "target2")
                    pos.tranche2_pending = True

    def _check_trend(self, px: Dict[str, Any]) -> None:
        independent = self.k.get("sma_exit_independent", False)
        for tk, pos in list(self.tracker.positions.items()):
            if pos.exit_pending:
                continue
            if not independent and not (pos.tranche1_sold and pos.tranche2_sold):
                continue
            r = px.get(tk)
            if r is None:
                continue
            sma = r["sma50"]
            if pd.isna(sma):
                continue  # SMA not warmed up yet -> no trend exit (bt emits NaN too)
            if float(r["close"]) < float(sma) and pos.remaining_shares > 0:
                self._queue_sell(tk, pos.remaining_shares, "trend")
                pos.exit_pending = True

    def _queue_liquidation(self, reason: str) -> None:
        for tk, pos in list(self.tracker.positions.items()):
            if pos.exit_pending or pos.remaining_shares <= 0:
                continue
            self._queue_sell(tk, pos.remaining_shares, reason)
            pos.exit_pending = True

    # --- entries --------------------------------------------------------------
    def _process_entries(self, regime: int, day: date_cls, px: Dict[str, Any]) -> None:
        max_pos = self.k["regime_max_pos"][regime]
        available = max_pos - self.tracker.get_open_count()
        if available <= 0:
            return
        candidates = self.score_lookup.get_candidates(
            day, min_score=self.k.get("min_score", 0),
            min_percentile=self.k.get("entry_percentile_min", 0.0),
            min_prob_elite=self.k.get("min_prob_elite", 0.0),
            rank_by=self.k.get("rank_by", "trailing"))
        if not candidates:
            return

        valid: List[tuple] = []
        for ticker, score, trailing_pct, prob_elite in candidates:
            if self.tracker.is_in_cooldown(ticker, day, self.k.get("cooldown_days", 3)):
                continue
            if self.tracker.has_position(ticker):
                continue
            r = px.get(ticker)
            if r is None:
                continue
            if float(r["close"]) < self.k.get("min_price", 1.0):
                continue
            if float(r["close"]) * float(r["volume"]) < self.k.get("min_dollar_volume", 0):
                continue
            valid.append((ticker, score, trailing_pct, r, prob_elite))

        pv = self._broker_value(px)
        for ticker, score, trailing_pct, r, prob_elite in valid[:available]:
            self._enter(ticker, score, trailing_pct, r, regime, day, pv)

    def _enter(self, ticker: str, score: float, trailing_pct: float,
               r: Any, regime: int, day: date_cls, pv: float) -> None:
        price = float(r["close"])          # decision price = today's close (bt uses close[0])
        atr = float(r["atr14"])
        size_pct = self._size_pct(regime)
        position_value = pv * size_pct
        available_cash = self.cash * 0.95
        if position_value > available_cash:
            position_value = available_cash
        shares = int(position_value / price)
        if shares < 3:
            return

        stop_atr = price - self.k.get("atr_stop_mult", 2.0) * atr
        stop_pct = price * (1 - self.k.get("max_stop_pct", 0.10))
        initial_stop = max(stop_atr, stop_pct)
        t1_atr = price + self.k.get("atr_target1_mult", 3.0) * atr
        t1_pct = price * (1 + self.k.get("min_target1_pct", 0.15))
        target1 = max(t1_atr, t1_pct)
        target2 = target1 + self.k.get("atr_target2_add", 2.0) * atr

        intent = {
            "ticker": ticker, "entry_date": day, "entry_atr": atr,
            "initial_size": shares, "initial_stop": initial_stop,
            "target1": target1, "target2": target2, "score": score,
            "trailing_pct": trailing_pct, "regime": regime,
        }
        self._queue_buy(ticker, shares, intent)

    def _size_pct(self, regime: int) -> float:
        mode = self.k.get("sizing_mode", "regime")
        if mode == "equal_weight":
            mp = self.k["regime_max_pos"].get(regime, 0)
            return 1.0 / mp if mp else 0.0
        return self.k.get("regime_sizes", {}).get(regime, 0.0)

    # --- regime ---------------------------------------------------------------
    def set_regime_series(self, regime_by_date: Dict[date_cls, int]) -> None:
        self._regime_map = regime_by_date

    def _regime(self, day: date_cls) -> int:
        return int(getattr(self, "_regime_map", {}).get(day, 2))  # default neutral


if __name__ == "__main__":
    # ponytail: self-check — one synthetic ticker, next-open fill + stop exit,
    # no DB. Proves the core step mechanics (queue -> next-open fill -> stop).
    from datetime import date

    days = [date(2024, 1, d) for d in range(2, 8)]  # 6 trading days
    # A ticker that qualifies day 1, rises then gaps below stop on day 4.
    prices = pd.DataFrame([
        # day, open, high, low, close
        (days[0], 10.0, 10.2, 9.9, 10.0),   # decision day -> queue buy
        (days[1], 10.0, 11.0, 10.0, 10.8),  # FILL here at open 10.0*1.001
        (days[2], 10.8, 12.0, 10.7, 11.9),
        (days[3], 11.9, 12.0, 7.0, 7.5),    # low 7.0 < stop(=8.5) -> queue sell
        (days[4], 7.5, 7.6, 7.0, 7.2),      # FILL sell at open 7.5*0.999
        (days[5], 7.2, 7.3, 7.0, 7.1),
    ], columns=["date", "open", "high", "low", "close"])
    prices["ticker"] = "TST"
    prices["volume"] = 1_000_000
    prices["atr14"] = 0.5
    prices["sma50"] = float("nan")  # no trend exit
    prices["date"] = pd.to_datetime(prices["date"])

    scores = pd.DataFrame({
        "date": pd.to_datetime(days), "ticker": "TST",
        "normalized_score": 50.0, "daily_pct_rank": 0.99,
        "trailing_pct": 0.99, "prob_elite": 0.9,
    })

    kw = {"entry_mode": "top_n", "entry_top_n": 5, "rank_by": "prob_elite",
          "min_prob_elite": 0.15, "sizing_mode": "equal_weight",
          "regime_max_pos": {0: 0, 1: 5, 2: 5, 3: 5, 4: 5},
          "atr_stop_mult": 2.0, "max_stop_pct": 0.15, "min_target1_pct": 0.10,
          "sma_exit_independent": True, "min_score": 0, "cooldown_days": 3}

    book = ChampionBook(kw, scores, initial_cash=25_000.0)
    book.set_regime_series({d: 3 for d in days})
    acts = []
    for d in days:
        acts += book.step(d, scores[pd.to_datetime(scores["date"]).dt.date == d],
                          prices[prices["date"].dt.date == d])

    kinds = [(a.kind, a.date) for a in acts]
    assert any(k == "enter" for k, _ in kinds), f"no entry: {kinds}"
    enter = next(a for a in acts if a.kind == "enter")
    assert abs(enter.price - 10.0 * 1.001) < 1e-6, enter.price   # next-open + slippage
    assert enter.date == days[1], enter.date                     # filled day AFTER decision
    stop = next(a for a in acts if a.kind == "stop")
    assert abs(stop.price - 7.5 * 0.999) < 1e-6, stop.price      # sell at next open - slippage
    assert stop.date == days[4], stop.date
    assert not book.tracker.get_all_open(), "position should be closed"
    print(f"OK — forward_engine self-check: entry@{enter.price:.3f} stop@{stop.price:.3f}, "
          f"{len(acts)} actions")
