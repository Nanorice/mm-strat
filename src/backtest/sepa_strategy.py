"""
SEPA Hybrid V1 Strategy for BackTrader
======================================
Implements the SEPA Hybrid V1 strategy with:
- M01: Selection via "Top N Competition" (best trailing 10-day percentile)
- M03: Regime gating (no new entries in Strong Bear, liquidate all)
- 3-Tranche exit logic with trailing stops

Entry Selection (Top N Competition):
- No percentile hard gate—regime controls exposure
- Candidates sorted by 10-day trailing percentile (persistent strength)
- Fill available slots with best-ranked candidates above score floor

Key Design:
- PositionTracker is a READ-MODEL, only updated in notify_order()
- Orders are submitted with intent metadata
- Stop/target checks happen daily in next()
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from datetime import date as datetime_date
from pathlib import Path
from typing import Dict, List, Optional

import backtrader as bt
import pandas as pd

from .score_lookup import ScoreLookup
from .position_tracker import PositionTracker
from .earnings_calendar import next_earnings_within

logger = logging.getLogger(__name__)


@dataclass
class DailySnapshot:
    """Daily portfolio state for exposure tracking."""
    date: datetime
    portfolio_value: float
    cash: float
    position_value: float
    position_count: int
    regime: int


@dataclass
class SignalRejection:
    """Tracks why a signal was rejected."""
    date: datetime
    ticker: str
    score: float
    reason: str  # 'cooldown', 'earnings_blackout', 'already_holding', 'no_slots', 'daily_cap', 'low_liquidity', 'low_price', 'no_data'


class SEPAHybridV1(bt.Strategy):
    """
    SEPA Hybrid V1 BackTrader Strategy.

    Parameters:
        - regime_sizes: Position size % by regime (0-4)
        - regime_max_pos: Max positions by regime (0-4)
        - min_score: Minimum normalized M01 score (0-100) - absolute floor
        - entry_percentile_min: Minimum percentile for entry (0.0 = no gate, 0.60 = top 40%)
        - entry_mode: Entry mode ('percentile' or 'top_n')
        - entry_top_n: If entry_mode='top_n', take top N candidates (None = use percentile)
        - rank_by: 'trailing' (10-day cohort) or 'daily' (single-day)
        - min_price: Minimum stock price
        - min_dollar_volume: Minimum daily dollar volume
        - cooldown_days: Days to wait after stop-out before re-entry
        - atr_stop_mult: ATR multiplier for initial stop
        - max_stop_pct: Maximum stop loss percentage
        - atr_target1_mult: ATR multiplier for target 1
        - min_target1_pct: Minimum target 1 percentage
        - atr_target2_add: ATR to add for target 2 (from target 1)
        - sma_exit_period: SMA period for trend exit (tranche 3)
        - exit_percentile_max: Exit if percentile rank falls below this (0.40 = bottom 40%)
        - exit_use_percentile: Enable percentile-based exits (default: False)
        - sizing_mode: Position sizing mode ('regime', 'equal_weight', 'rank_weighted', 'score_weighted')
    """

    params = (
        # Regime sizing (from strategy spec)
        ('regime_sizes', {0: 0.0, 1: 0.025, 2: 0.05, 3: 0.075, 4: 0.10}),
        ('regime_max_pos', {0: 0, 1: 4, 2: 8, 3: 10, 4: 12}),

        # Entry filters (Top N Competition mode)
        # - min_score: absolute floor on M01 prediction quality
        # - entry_percentile_min: minimum percentile (0.0 = no gate, 0.60 = top 40%)
        # - entry_mode: 'percentile' (filter by percentile) or 'top_n' (take top N)
        # - entry_top_n: if entry_mode='top_n', take this many candidates (None = use percentile)
        # - rank_by: 'trailing' uses 10-day cohort percentile, 'daily' uses single-day
        # NOTE: Regime controls exposure; percentile is just a ranking metric now
        ('min_score', 30),  # Safety floor (scaled 0-100) - RS > 30
        ('entry_percentile_min', 0.0),  # Minimum percentile gate (0.0 = no gate)
        ('entry_mode', 'percentile'),  # 'percentile' or 'top_n'
        ('entry_top_n', None),  # Alternative: take top N candidates (None = use percentile)
        ('rank_by', 'trailing'),  # 'trailing' | 'daily' | 'prob_elite'
        ('min_prob_elite', 0.0),  # Min P(Class 3) for entry (e.g., 0.15)
        ('warmup_days', 0),  # Skip entries during initial warmup
        ('min_price', 1.0),
        ('min_dollar_volume', 0),
        ('cooldown_days', 3),

        # Exit params (stop-loss and targets)
        ('atr_stop_mult', 2.0),
        ('max_stop_pct', 0.10),
        ('atr_target1_mult', 3.0),
        ('min_target1_pct', 0.15),
        ('atr_target2_add', 2.0),
        # Tail-harvesting exit: no tranche take-profit at all. target1 is always
        # >= entry price (max of two price+... legs), so zeroing the legs fires T1
        # at entry instead of disabling it — the tranche can only be turned off
        # here. Runner then exits on the initial stop / independent SMA trend break.
        ('disable_tranches', False),
        # Rising trail from entry (0 = off). With disable_tranches the normal trail
        # never engages (it gates on tranche1_sold), leaving the runner on its fixed
        # initial stop — this protects the median path it otherwise bleeds (R3 §mechanism).
        ('trail_from_entry_atr', 0.0),
        ('sma_exit_period', 50),

        # Exit params (rank-based exits)
        ('exit_percentile_max', 0.40),  # Exit if rank falls below 40th percentile
        ('exit_use_percentile', False),  # Enable percentile-based exit

        # Minimum hold period (suppresses rank-based exits only; stop-loss /
        # SMA exits still fire because they represent real damage, not a
        # confidence dip). Capital-preservation lever for the strategy array
        # — avoids prematurely cutting winners that drop in cohort rank.
        ('min_hold_days', 0),

        # Persistence gate (S5 hybrid_persistent strategy). When all three are
        # set, candidates must have had `rank_by` >= `persistence_threshold`
        # for at least `persistence_min_count` of the last
        # `persistence_window_days` trading days. Default off.
        ('persistence_window_days', 0),
        ('persistence_min_count', 0),
        ('persistence_threshold', 0.7),

        # Position sizing mode
        ('sizing_mode', 'regime'),  # 'regime', 'equal_weight', 'rank_weighted', 'score_weighted'

        # --- Rotation extensions (default = no-op; S1..S5 unchanged) ---
        # E2 delayed conditional entry: buffer a candidate's first-qualifying
        # date, then enter on day N only if its return since that date is within
        # [entry_ret_lo, entry_ret_hi]. 0 = immediate entry (E1, the default).
        ('entry_delay_days', 0),
        ('entry_ret_lo', -1.0),   # fraction, e.g. -0.03 = down ≤3% ok
        ('entry_ret_hi', 1.0),    # fraction, e.g.  0.15 = up ≤15% ok (avoid the spent runner)
        # X2 score-drop exit: exit full position if today's prob_elite fell more
        # than score_drop_thresh below its entry value, OR below score_exit_floor.
        # None = disabled.
        ('score_drop_thresh', None),
        ('score_exit_floor', None),
        # X3 make SMA/trend exit fire independently of tranche state (your intent:
        # close<SMA => get out). Default False keeps the tranche-gated behaviour.
        ('sma_exit_independent', False),
        # Selection skip-top-K (A3 tail-pollution cap): drop the K highest-ranked
        # candidates each day before slot-filling, so entries come from ranks
        # K+1..K+slots. 0 = disabled (take the very top). Confirmed in the
        # vectorized sweep as a real edge on wide-spread signals (proto_cali),
        # neutral on compressed binary — the top-ranked names are "spent".
        ('selection_skip_top', 0),

        # Score data (DataFrame from UniverseScorer.score_from_t3())
        ('scores_df', None),

        # SPY-200d deploy gate (Thread E Q15): {date -> bool} of "SPY above 200d SMA".
        # When set and False for the current bar, block NEW entries (open positions
        # and exits run unchanged) — the ex-ante market filter, separate from M03
        # regime sizing. None = no gate (default). A missing date defaults to open.
        ('spy_deploy_gate', None),

        # Portfolio-level drawdown circuit breaker (Elder, *Trading for a Living*;
        # §1.1). Book-level brake distinct from the per-name stop and the SPY entry
        # gate: when the BOOK's peak-to-trough drawdown reaches dd_breaker_pct, stop
        # opening NEW positions (open positions & exits run unchanged — same brake
        # point as the SPY gate) until a release condition clears. All flexible:
        #   - dd_breaker_pct: trip level, e.g. 0.06 (6%). 0/None => breaker off.
        #   - dd_breaker_release_pct: recover to within this much of the peak to
        #     re-arm, e.g. 0.02 => equity back within 2% of the high-water mark.
        #   - dd_breaker_require_spy_uptrend: also require SPY>200d to release
        #     (needs spy_deploy_gate set). Combine the book cool-off with the market
        #     brake per the doc's open question. Default False (book-recovery alone).
        ('dd_breaker_pct', 0.0),
        ('dd_breaker_release_pct', 0.02),
        ('dd_breaker_require_spy_uptrend', False),

        # Earnings-proximity overlay (Minervini: never hold a binary gap you can't
        # stop out of). {ticker -> sorted np.array[datetime64[D]]} calendar, injected
        # per-window like spy_deploy_gate. earnings_blackout_days=0 => whole overlay
        # off (default). When set:
        #   - block NEW entries within N days before a scheduled earnings date;
        #   - N days out, trim held positions by earnings_exit_frac (1.0=full exit,
        #     0.5=half, 0.33=third), but ONLY if return-so-far >= earnings_exit_min_ret
        #     (protect gains, let underwater names ride to their own stop). min_ret=None
        #     => always trim regardless of P&L.
        ('earnings_calendar', None),
        ('earnings_blackout_days', 0),
        ('earnings_exit_frac', 1.0),
        ('earnings_exit_min_ret', None),

        # Progressive fills (Minervini scale-in) — the vectorized winner (M2 cone).
        # Enter a starter fraction of the target size, add the remainder once price
        # first clears +add_trigger_pct above entry. Path-dependent: losers that
        # never trigger stay small; winners scale to full. Tranche math keys off the
        # FINAL target size. Default off => existing strategies byte-identical.
        ('progressive_fills', False),
        ('starter_frac', 0.5),
        ('add_trigger_pct', 0.05),
    )

    def __init__(self):
        """Initialize strategy components."""
        if self.p.scores_df is None:
            raise ValueError("SEPAHybridV1 requires scores_df param (DataFrame from UniverseScorer)")
        self.score_lookup = ScoreLookup(self.p.scores_df)

        # Position tracker (READ-MODEL - only updated in notify_order)
        self.position_tracker = PositionTracker()

        # Regime feed is the first data feed
        self.regime_feed = self.datas[0]

        # Build dict of stock data feeds (skip regime feed)
        self.stock_feeds: Dict[str, bt.DataBase] = {}
        for data in self.datas[1:]:
            self.stock_feeds[data._name] = data

        # Pre-compute SMA50 for all stock feeds (for trend exit)
        self.sma50 = {}
        for name, data in self.stock_feeds.items():
            self.sma50[name] = bt.indicators.SMA(data.close, period=self.p.sma_exit_period)

        # Order tracking for notify_order
        self.pending_orders: Dict[int, dict] = {}

        # Exposure & equity tracking
        self.daily_snapshots: List[DailySnapshot] = []
        self.signal_rejections: List[SignalRejection] = []

        # Warmup bar counter (used to suppress entries during initial bars)
        self._bars_seen = 0

        # E2 delayed entry: ticker -> first date it qualified (watchlist-join proxy).
        self._first_qualified: Dict[str, datetime] = {}
        # entry prob_elite per held ticker, for the X2 score-drop exit.
        self._entry_prob_elite: Dict[str, float] = {}
        # tickers already partially trimmed for an upcoming earnings print (frac<1).
        self._earnings_trimmed: set = set()

        # DD circuit breaker state: running equity high-water mark + latch. Once
        # tripped, stays tripped until equity recovers within release_pct of peak.
        self._equity_peak: float = 0.0
        self._dd_breaker_tripped: bool = False

        logger.info(f"SEPA Strategy initialized with {len(self.stock_feeds)} stock feeds")

    def notify_order(self, order):
        """
        Handle order notifications.

        CRITICAL: This is the ONLY place where PositionTracker state is mutated.
        The broker is the source of truth - we only update our tracker when
        orders are actually executed (Completed), not when submitted.
        """
        if order.status in [order.Submitted, order.Accepted]:
            return  # Order pending, do nothing

        if order.status == order.Completed:
            ticker = order.data._name

            if order.isbuy():
                # A buy is either a progressive-fill ADD (tracked in pending_orders
                # with reason 'add') or a fresh ENTRY (has a pending entry intent).
                if self.pending_orders.get(order.ref, {}).get('reason') == 'add':
                    self.pending_orders.pop(order.ref, None)
                    self.position_tracker.confirm_add(
                        ticker=ticker,
                        executed_price=order.executed.price,
                        executed_size=int(order.executed.size),
                    )
                else:
                    # Entry order filled - NOW create position in tracker
                    self.position_tracker.confirm_entry(
                        order_ref=order.ref,
                        executed_price=order.executed.price,
                        executed_size=int(order.executed.size),
                    )
            else:
                # Exit order filled - NOW update tranche state
                exit_info = self.pending_orders.pop(order.ref, {})
                exit_reason = exit_info.get('reason', 'unknown')

                self.position_tracker.record_partial_exit(
                    ticker=ticker,
                    shares_sold=int(abs(order.executed.size)),
                    exit_price=order.executed.price,
                    exit_reason=exit_reason,
                    exit_date=self.datetime.date(),
                )

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            # Check if there was any partial execution before failure
            if order.executed.size:
                logger.warning(f"Order {order.status} but had partial execution: {order.executed.size}")
                
                if order.isbuy():
                    # Confirm entry for the partial amount
                    self.position_tracker.confirm_entry(
                        order_ref=order.ref,
                        executed_price=order.executed.price,
                        executed_size=int(order.executed.size),
                    )
                else:
                    # Record partial exit
                    exit_info = self.pending_orders.get(order.ref, {})
                    exit_reason = exit_info.get('reason', 'unknown')
                    
                    self.position_tracker.record_partial_exit(
                        ticker=order.data._name,
                        shares_sold=int(abs(order.executed.size)),
                        exit_price=order.executed.price,
                        exit_reason=exit_reason,
                        exit_date=self.datetime.date(),
                    )

            # Clean up pending flags/intents
            ticker = order.data._name
            if order.isbuy():
                # Only pop if not already consumed by partial confirm_entry above
                if order.ref in self.position_tracker.pending_entries:
                    self.position_tracker.pending_entries.pop(order.ref, None)
            else:
                exit_info = self.pending_orders.pop(order.ref, {})
                exit_reason = exit_info.get('reason', 'unknown')

                # Clear pending flags so we can retry (for the remaining portion)
                pos = self.position_tracker.get_position(ticker)
                if pos:
                    if exit_reason == 'target1':
                        pos.tranche1_pending = False
                    elif exit_reason == 'target2':
                        pos.tranche2_pending = False
                    elif exit_reason in ['stop', 'trend', 'regime_liquidation']:
                        pos.exit_pending = False

            logger.warning(f"Order failed for {ticker}: {order.status}")

    def next(self):
        """
        Main strategy logic executed each bar.

        Flow:
        1. Record daily snapshot (exposure tracking)
        2. Hard Gate: Liquidate all if Strong Bear (regime 0)
        3. Check gap-down exits (next-day open protection)
        4. Update trailing stops for open positions
        5. Check stop-outs
        6. Check profit targets
        7. Check trend exits (tranche 3)
        8. Process new entries
        """
        current_date = self.datetime.date()

        # Get current regime (0=strong_bear to 4=strong_bull)
        regime = int(self.regime_feed.regime_cat[0])

        # === RECORD DAILY SNAPSHOT (for exposure metrics) ===
        self._record_daily_snapshot(current_date, regime)

        # === HARD GATE: Liquidate all on Strong Bear ===
        if regime == 0:
            self._liquidate_all('regime_liquidation')
            return

        # === CHECK GAP-DOWN EXITS (before other checks) ===
        # self._check_gap_down_exits()

        # === PROGRESSIVE-FILL ADDS (before stops/targets; scale winners up) ===
        if self.p.progressive_fills:
            self._check_adds()

        # === UPDATE TRAILING STOPS ===
        self._update_all_stops()

        # === CHECK STOP-OUTS ===
        self._check_stops(current_date)

        # === CHECK PROFIT TARGETS ===
        self._check_targets()

        # === CHECK TREND EXITS (Tranche 3) ===
        self._check_trend_exits()

        # === CHECK RANK-BASED EXITS (Optional) ===
        if self.p.exit_use_percentile:
            self._check_rank_exits(current_date)

        # === CHECK SCORE-DROP EXITS (X2, optional) ===
        if self.p.score_drop_thresh is not None or self.p.score_exit_floor is not None:
            self._check_score_drop_exits(current_date)

        # === CHECK EARNINGS-PROXIMITY EXITS (trim before the print, optional) ===
        if self.p.earnings_blackout_days > 0 and self.p.earnings_calendar:
            self._check_earnings_exits(current_date)

        # === WARMUP CHECK ===
        # Skip entries during initial warmup bars (exits still run above).
        self._bars_seen += 1
        if self._bars_seen <= self.p.warmup_days:
            return

        # === ENTRY LOGIC ===
        self._process_entries(regime, current_date)

    def _record_daily_snapshot(self, current_date: datetime, regime: int):
        """Record daily portfolio state for exposure metrics."""
        portfolio_value = self.broker.getvalue()
        cash = self.broker.getcash()
        position_value = portfolio_value - cash
        position_count = self.position_tracker.get_open_count()

        # DD circuit breaker: update high-water mark + latch state each bar (uses
        # today's mark, known before entries run below in next()).
        self._update_dd_breaker(portfolio_value, current_date)

        self.daily_snapshots.append(DailySnapshot(
            date=current_date,
            portfolio_value=portfolio_value,
            cash=cash,
            position_value=position_value,
            position_count=position_count,
            regime=regime,
        ))

    def _liquidate_all(self, reason: str):
        """Liquidate all open positions."""
        for ticker, pos in list(self.position_tracker.positions.items()):
            # Skip if exit already pending
            if pos.exit_pending:
                continue

            if pos.remaining_shares > 0:
                data = self.stock_feeds.get(ticker)
                if data:
                    order = self.sell(data=data, size=pos.remaining_shares)
                    self.pending_orders[order.ref] = {'reason': reason, 'ticker': ticker}
                    pos.exit_pending = True  # Prevent duplicate orders
                    logger.info(f"Liquidating {ticker}: {pos.remaining_shares} shares ({reason})")

    def _check_gap_down_exits(self):
        """
        Check for gap-down exits: if open breaches stop level, exit at open.

        Uses the same stop criteria as regular stop-outs, but checks at open
        instead of low. This handles overnight gaps that blow through stops.
        """
        for ticker, pos in list(self.position_tracker.positions.items()):
            # Skip if exit already pending
            if pos.exit_pending:
                continue

            data = self.stock_feeds.get(ticker)
            if data is None:
                continue

            # Check if open is at or below the stop level
            today_open = data.open[0]
            if today_open <= pos.current_stop:
                if pos.remaining_shares > 0:
                    order = self.sell(data=data, size=pos.remaining_shares)
                    self.pending_orders[order.ref] = {'reason': 'gap_down', 'ticker': ticker}
                    pos.exit_pending = True
                    gap_pct = (pos.entry_price - today_open) / pos.entry_price * 100
                    logger.info(f"Gap-down exit {ticker}: Open {today_open:.2f} <= stop {pos.current_stop:.2f} "
                               f"({gap_pct:.1f}% below entry)")

    def _check_adds(self):
        """Progressive-fill scale-in: buy the remainder once price first clears
        the add trigger. Fires at most once per position (add_pending/added guard).
        """
        for ticker, pos in list(self.position_tracker.positions.items()):
            if pos.added or pos.add_pending or pos.exit_pending:
                continue
            if pos.add_target_shares <= 0:
                continue
            data = self.stock_feeds.get(ticker)
            if data is None:
                continue
            if data.high[0] >= pos.add_trigger_price:
                order = self.buy(data=data, size=pos.add_target_shares)
                self.pending_orders[order.ref] = {'reason': 'add', 'ticker': ticker}
                pos.add_pending = True
                logger.info(f"Progressive add {ticker}: +{pos.add_target_shares} shares "
                            f"(high {data.high[0]:.2f} >= trigger {pos.add_trigger_price:.2f})")

    def _update_all_stops(self):
        """Update trailing stops for all open positions."""
        for ticker, pos in self.position_tracker.positions.items():
            data = self.stock_feeds.get(ticker)
            if data is None:
                continue

            # Get current ATR and high
            current_atr = data.atr[0]
            current_high = data.high[0]

            # Update stop (high-water mark logic in tracker)
            self.position_tracker.update_stops(
                ticker, current_atr, current_high,
                trail_from_entry_atr=self.p.trail_from_entry_atr)

    def _check_stops(self, current_date: datetime):
        """Check and execute stop-outs."""
        for ticker, pos in list(self.position_tracker.positions.items()):
            # Skip if exit already pending
            if pos.exit_pending:
                continue

            data = self.stock_feeds.get(ticker)
            if data is None:
                continue

            # Check if stop was hit
            if self.position_tracker.check_stops(ticker, data.low[0]):
                # Sell all remaining shares
                if pos.remaining_shares > 0:
                    order = self.sell(data=data, size=pos.remaining_shares)
                    self.pending_orders[order.ref] = {'reason': 'stop', 'ticker': ticker}
                    pos.exit_pending = True  # Prevent duplicate orders
                    logger.info(f"Stop hit for {ticker} @ {pos.current_stop:.2f}")

    def _check_targets(self):
        """Check and execute profit target exits."""
        if self.p.disable_tranches:  # tail-harvesting exit: hold runner, no TP
            return
        for ticker, pos in list(self.position_tracker.positions.items()):
            data = self.stock_feeds.get(ticker)
            if data is None:
                continue

            # Check targets
            target_hit = self.position_tracker.check_targets(ticker, data.high[0])

            if target_hit == 'target1' and not pos.tranche1_sold and not pos.tranche1_pending and not pos.exit_pending:
                # Sell tranche 1 (1/3 of initial)
                sell_size = pos.tranche_size
                if sell_size > 0 and sell_size <= pos.remaining_shares:
                    order = self.sell(data=data, size=sell_size)
                    self.pending_orders[order.ref] = {'reason': 'target1', 'ticker': ticker}
                    pos.tranche1_pending = True  # Prevent duplicate orders
                    logger.info(f"Target 1 hit for {ticker}: selling {sell_size} shares")

            elif target_hit == 'target2' and not pos.tranche2_sold and not pos.tranche2_pending and not pos.exit_pending:
                # Sell tranche 2 (1/3 of initial)
                sell_size = pos.tranche_size
                if sell_size > 0 and sell_size <= pos.remaining_shares:
                    order = self.sell(data=data, size=sell_size)
                    self.pending_orders[order.ref] = {'reason': 'target2', 'ticker': ticker}
                    pos.tranche2_pending = True  # Prevent duplicate orders
                    logger.info(f"Target 2 hit for {ticker}: selling {sell_size} shares")

    def _check_trend_exits(self):
        """Check and execute trend breakdown exits (tranche 3)."""
        for ticker, pos in list(self.position_tracker.positions.items()):
            # Skip if exit already pending
            if pos.exit_pending:
                continue

            # Trend exit normally trails the runner (after both tranches sold).
            # sma_exit_independent=True fires it on any open position (X3 intent).
            if not self.p.sma_exit_independent and not (pos.tranche1_sold and pos.tranche2_sold):
                continue

            data = self.stock_feeds.get(ticker)
            if data is None:
                continue

            # Get SMA50
            sma = self.sma50.get(ticker)
            if sma is None:
                continue

            # Check trend breakdown: Close < SMA50
            if data.close[0] < sma[0]:
                if pos.remaining_shares > 0:
                    order = self.sell(data=data, size=pos.remaining_shares)
                    self.pending_orders[order.ref] = {'reason': 'trend', 'ticker': ticker}
                    pos.exit_pending = True  # Prevent duplicate orders
                    logger.info(f"Trend exit for {ticker}: Close {data.close[0]:.2f} < SMA50 {sma[0]:.2f}")

    def _check_rank_exits(self, current_date: datetime):
        """
        Check for rank-based exits: exit if percentile rank falls below threshold.

        This allows testing "momentum fade" exits where we exit positions that
        lose relative strength vs the universe (even if trend is intact).
        """
        for ticker, pos in list(self.position_tracker.positions.items()):
            # Skip if exit already pending
            if pos.exit_pending:
                continue

            # Respect min_hold_days — suppress rank exits during the hold window.
            # Stop-loss and SMA exits still fire because they represent real damage.
            if self.p.min_hold_days > 0:
                entry_date = pos.entry_date
                if hasattr(entry_date, "date"):
                    entry_date = entry_date.date()
                cur_date = current_date.date() if hasattr(current_date, "date") else current_date
                if (cur_date - entry_date).days < self.p.min_hold_days:
                    continue

            # Lookup current percentile rank — get_score returns
            # (normalized_score, daily_pct_rank, trailing_pct, prob_elite).
            score_data = self.score_lookup.get_score(current_date, ticker)
            if not score_data:
                continue
            _, _, trailing_pct, _ = score_data
            pct_rank = trailing_pct if trailing_pct is not None else 0.0

            # Exit if rank falls below threshold
            if pct_rank < self.p.exit_percentile_max:
                data = self.stock_feeds.get(ticker)
                if data and pos.remaining_shares > 0:
                    order = self.sell(data=data, size=pos.remaining_shares)
                    self.pending_orders[order.ref] = {'reason': 'low_rank', 'ticker': ticker}
                    pos.exit_pending = True
                    logger.info(f"Rank exit for {ticker}: percentile {pct_rank:.2f} < threshold {self.p.exit_percentile_max:.2f}")

    def _join_close(self, ticker: str, join_date: datetime) -> Optional[float]:
        """Close price on the ticker's first-qualified date (E2 return baseline).
        Reads the feed's backing DataFrame — O(1) dict lookup, no bt indexing."""
        data = self.stock_feeds.get(ticker)
        if data is None or not hasattr(data.p, 'dataname'):
            return None
        df = data.p.dataname
        key = pd.Timestamp(join_date.date() if hasattr(join_date, 'date') else join_date)
        try:
            return float(df.at[key, 'close'])
        except (KeyError, ValueError):
            return None

    def _check_score_drop_exits(self, current_date: datetime):
        """X2: exit if today's prob_elite dropped >score_drop_thresh below entry,
        or fell below score_exit_floor. Respects min_hold_days (a confidence dip,
        not real damage). Rotates capital out of decaying setups."""
        for ticker, pos in list(self.position_tracker.positions.items()):
            if pos.exit_pending:
                continue
            if self.p.min_hold_days > 0:
                entry_date = pos.entry_date
                if hasattr(entry_date, "date"):
                    entry_date = entry_date.date()
                cur = current_date.date() if hasattr(current_date, "date") else current_date
                if (cur - entry_date).days < self.p.min_hold_days:
                    continue

            sd = self.score_lookup.get_score(current_date, ticker)
            if not sd:
                continue
            prob_now = sd[3]
            if prob_now is None:
                continue
            entry_prob = self._entry_prob_elite.get(ticker)

            drop_hit = (
                self.p.score_drop_thresh is not None
                and entry_prob is not None
                and prob_now < entry_prob - self.p.score_drop_thresh
            )
            floor_hit = (
                self.p.score_exit_floor is not None
                and prob_now < self.p.score_exit_floor
            )
            if drop_hit or floor_hit:
                data = self.stock_feeds.get(ticker)
                if data and pos.remaining_shares > 0:
                    order = self.sell(data=data, size=pos.remaining_shares)
                    self.pending_orders[order.ref] = {'reason': 'score_drop', 'ticker': ticker}
                    pos.exit_pending = True
                    logger.info(f"Score-drop exit {ticker}: prob {prob_now:.3f} "
                                f"(entry {entry_prob}, floor {self.p.score_exit_floor})")

    def _check_earnings_exits(self, current_date: datetime):
        """Trim held positions N days before a scheduled earnings print (Minervini
        gap rule). frac=1.0 => full exit (sets exit_pending); frac<1 => partial trim,
        fired at most once per position via _earnings_trimmed. Gated on return-so-far:
        only trim winners (>= earnings_exit_min_ret); underwater names ride to their
        own stop. Runs in the exit block, before entries — same bar as the print - N."""
        n = self.p.earnings_blackout_days
        frac = self.p.earnings_exit_frac
        min_ret = self.p.earnings_exit_min_ret
        # Forget positions no longer held so a fresh re-entry can trim again.
        self._earnings_trimmed &= set(self.position_tracker.positions.keys())

        for ticker, pos in list(self.position_tracker.positions.items()):
            if pos.exit_pending or pos.remaining_shares <= 0:
                continue
            if frac < 1.0 and ticker in self._earnings_trimmed:
                continue  # already trimmed this position for its upcoming print
            if not next_earnings_within(self.p.earnings_calendar, ticker, current_date, n):
                continue

            data = self.stock_feeds.get(ticker)
            if data is None:
                continue

            if min_ret is not None:
                ret = (data.close[0] - pos.entry_price) / pos.entry_price
                if ret < min_ret:
                    continue  # not enough gain to protect — let it ride to its stop

            sell_size = pos.remaining_shares if frac >= 1.0 else int(pos.remaining_shares * frac)
            if sell_size <= 0:
                continue
            order = self.sell(data=data, size=sell_size)
            self.pending_orders[order.ref] = {'reason': 'earnings', 'ticker': ticker}
            if sell_size >= pos.remaining_shares:
                pos.exit_pending = True  # full close — block other orders on this name
            else:
                self._earnings_trimmed.add(ticker)
            logger.info(f"Earnings trim {ticker}: sold {sell_size}/{pos.remaining_shares} "
                        f"(<= {n}d to print, frac={frac})")

    def _update_dd_breaker(self, portfolio_value: float, current_date: datetime):
        """Update the book-level DD circuit-breaker latch (§1.1). Peak = running
        equity high-water mark; trip when peak-to-trough DD >= dd_breaker_pct;
        release when equity recovers within dd_breaker_release_pct of peak (and,
        if required, SPY>200d). No-op when dd_breaker_pct is 0/None."""
        if not self.p.dd_breaker_pct:
            return
        if portfolio_value > self._equity_peak:
            self._equity_peak = portfolio_value
        if self._equity_peak <= 0:
            return
        dd = 1.0 - portfolio_value / self._equity_peak
        if not self._dd_breaker_tripped:
            if dd >= self.p.dd_breaker_pct:
                self._dd_breaker_tripped = True
                logger.info(f"DD breaker TRIPPED {current_date}: book DD {dd:.1%} "
                            f">= {self.p.dd_breaker_pct:.1%} — new entries halted")
        else:
            recovered = dd <= self.p.dd_breaker_release_pct
            spy_ok = (not self.p.dd_breaker_require_spy_uptrend
                      or self.p.spy_deploy_gate is None
                      or self.p.spy_deploy_gate.get(current_date, True))
            if recovered and spy_ok:
                self._dd_breaker_tripped = False
                logger.info(f"DD breaker RELEASED {current_date}: book DD {dd:.1%} "
                            f"<= {self.p.dd_breaker_release_pct:.1%} — entries re-armed")

    def _process_entries(self, regime: int, current_date: datetime):
        """Process new entry signals with rejection tracking."""
        # Check position limits
        max_positions = self.p.regime_max_pos[regime]
        current_count = self.position_tracker.get_open_count()
        available_slots = max_positions - current_count

        # SPY-200d deploy gate: shut => no new entries this bar (existing no_slots
        # path below logs the rejects). Exits already ran; open positions untouched.
        if self.p.spy_deploy_gate is not None and not self.p.spy_deploy_gate.get(current_date, True):
            available_slots = 0

        # DD circuit breaker: book bled past the trip level => halt NEW entries
        # until it releases (same brake point as the SPY gate; exits untouched).
        if self._dd_breaker_tripped:
            available_slots = 0

        # Get candidates sorted by trailing percentile (Top N Competition)
        candidates = self.score_lookup.get_candidates(
            current_date,
            min_score=self.p.min_score,
            min_percentile=self.p.entry_percentile_min,
            min_prob_elite=self.p.min_prob_elite,
            rank_by=self.p.rank_by,
        )

        if not candidates:
            return

        # Filter candidates with rejection tracking
        valid_candidates = []
        for ticker, score, trailing_pct, prob_elite in candidates:
            # E2: anchor first-qualified date on true first sighting (before any
            # skip), so the delay window measures from watchlist-join, not re-entry.
            # ponytail: proxy for join date; exact would join the watchlist table.
            if self.p.entry_delay_days > 0:
                self._first_qualified.setdefault(ticker, current_date)

            # Skip if in cooldown
            if self.position_tracker.is_in_cooldown(ticker, current_date, self.p.cooldown_days):
                self.signal_rejections.append(SignalRejection(
                    date=current_date, ticker=ticker, score=score, reason='cooldown'
                ))
                continue

            # Earnings blackout: don't open a new position into an imminent print.
            if self.p.earnings_blackout_days > 0 and self.p.earnings_calendar and \
                    next_earnings_within(self.p.earnings_calendar, ticker, current_date,
                                         self.p.earnings_blackout_days):
                self.signal_rejections.append(SignalRejection(
                    date=current_date, ticker=ticker, score=score, reason='earnings_blackout'
                ))
                continue

            # Skip if already holding
            if self.position_tracker.has_position(ticker):
                # NOTE: We currently do NOT support "topping up" partial fills. 
                # If we bought 50/100, we stay with 50 until exit.
                self.signal_rejections.append(SignalRejection(
                    date=current_date, ticker=ticker, score=score, reason='already_holding'
                ))
                continue

            # Skip if no data feed
            data = self.stock_feeds.get(ticker)
            if data is None:
                self.signal_rejections.append(SignalRejection(
                    date=current_date, ticker=ticker, score=score, reason='no_data'
                ))
                continue

            # Check minimum price
            if data.close[0] < self.p.min_price:
                self.signal_rejections.append(SignalRejection(
                    date=current_date, ticker=ticker, score=score, reason='low_price'
                ))
                continue

            # Check minimum dollar volume
            dollar_volume = data.close[0] * data.volume[0]
            if dollar_volume < self.p.min_dollar_volume:
                self.signal_rejections.append(SignalRejection(
                    date=current_date, ticker=ticker, score=score, reason='low_liquidity'
                ))
                continue

            # Persistence gate (S5): require sustained high rank across recent
            # window before entry. Skipped when persistence_window_days <= 0.
            if self.p.persistence_window_days > 0 and self.p.persistence_min_count > 0:
                rank_field = 'trailing' if self.p.rank_by == 'trailing' else 'daily'
                persistent = self.score_lookup.check_persistence(
                    ticker=ticker,
                    date=current_date,
                    window_days=self.p.persistence_window_days,
                    min_count=self.p.persistence_min_count,
                    rank_threshold=self.p.persistence_threshold,
                    rank_field=rank_field,
                )
                if not persistent:
                    self.signal_rejections.append(SignalRejection(
                        date=current_date, ticker=ticker, score=score,
                        reason='not_persistent',
                    ))
                    continue

            # E2 delayed conditional entry: gate on days-since-first-qualified +
            # return band. entry_delay_days=0 -> immediate (E1), no-op.
            if self.p.entry_delay_days > 0:
                first = self._first_qualified[ticker]
                first_d = first.date() if hasattr(first, "date") else first
                cur_d = current_date.date() if hasattr(current_date, "date") else current_date
                if (cur_d - first_d).days < self.p.entry_delay_days:
                    continue  # still waiting out the delay window
                join_px = self._join_close(ticker, first)
                cur_px = data.close[0]
                if join_px and join_px > 0:
                    ret = (cur_px - join_px) / join_px
                    if not (self.p.entry_ret_lo <= ret <= self.p.entry_ret_hi):
                        self.signal_rejections.append(SignalRejection(
                            date=current_date, ticker=ticker, score=score,
                            reason='delay_band',
                        ))
                        continue

            valid_candidates.append((ticker, score, trailing_pct, data, prob_elite))

        # Selection skip-top-K: drop the K highest-ranked survivors so entries
        # come from ranks K+1.. (A3 tail-pollution cap). Rank order is preserved
        # from get_candidates. Dropped names are tracked as a distinct reason so
        # the rejection audit stays honest.
        if self.p.selection_skip_top > 0 and valid_candidates:
            skipped = valid_candidates[:self.p.selection_skip_top]
            for ticker, score, trailing_pct, data, prob_elite in skipped:
                self.signal_rejections.append(SignalRejection(
                    date=current_date, ticker=ticker, score=score, reason='skip_top',
                ))
            valid_candidates = valid_candidates[self.p.selection_skip_top:]

        # Track "no_slots" rejections for candidates that passed filters but couldn't enter
        if available_slots <= 0:
            for ticker, score, trailing_pct, data, prob_elite in valid_candidates:
                self.signal_rejections.append(SignalRejection(
                    date=current_date, ticker=ticker, score=score, reason='no_slots'
                ))
            return

        # Per-day entry cadence: entry_top_n caps NEW entries per bar (Q45 fix — the
        # param was declared but never enforced; entries were sliced by available_slots
        # only, so any arm with entry_top_n < max_pos was mislabeled).
        n_enter = available_slots
        if self.p.entry_mode == 'top_n' and self.p.entry_top_n is not None:
            n_enter = min(available_slots, self.p.entry_top_n)

        # Track "no_slots" for candidates beyond available slots
        for ticker, score, trailing_pct, data, prob_elite in valid_candidates[available_slots:]:
            self.signal_rejections.append(SignalRejection(
                date=current_date, ticker=ticker, score=score, reason='no_slots'
            ))
        # Within slots but beyond today's cadence cap — distinct audit reason
        for ticker, score, trailing_pct, data, prob_elite in valid_candidates[n_enter:available_slots]:
            self.signal_rejections.append(SignalRejection(
                date=current_date, ticker=ticker, score=score, reason='daily_cap'
            ))

        # Enter top N by trailing percentile (already sorted)
        for ticker, score, trailing_pct, data, prob_elite in valid_candidates[:n_enter]:
            self._entry_prob_elite[ticker] = prob_elite
            self._enter_position(ticker, score, trailing_pct, data, regime, current_date)

    def calculate_position_size(self, regime_cat: int, score: float, rank: float) -> float:
        """
        Calculate position size based on sizing mode.

        Args:
            regime_cat: M03 regime category (0-4)
            score: M01 normalized score (0-100)
            rank: Trailing 10-day percentile (0.0-1.0)

        Returns:
            Position size as fraction of portfolio (0.0-1.0)
        """
        mode = self.p.sizing_mode

        if mode == 'regime':
            # Original: regime-based sizing
            return self.p.regime_sizes.get(regime_cat, 0.0)

        elif mode == 'equal_weight':
            # Equal weight across all positions
            max_pos = self.p.regime_max_pos.get(regime_cat, 0)
            if max_pos == 0:
                return 0.0
            return 1.0 / max_pos  # e.g., 10 max pos → 10% each

        elif mode == 'rank_weighted':
            # Weight by percentile rank (top-ranked get more capital)
            base_size = self.p.regime_sizes.get(regime_cat, 0.0)
            # Scale by rank: 90th percentile (0.9) → 1.8x, 50th (0.5) → 1.0x, 10th (0.1) → 0.2x
            rank_multiplier = 0.5 + (rank * 1.5)
            return base_size * rank_multiplier

        elif mode == 'score_weighted':
            # Weight by M01 score (higher score = bigger position)
            base_size = self.p.regime_sizes.get(regime_cat, 0.0)
            # Scale by score: 100 → 2.0x, 50 → 1.0x, 0 → 0.0x
            score_multiplier = score / 50.0
            return base_size * score_multiplier

        else:
            raise ValueError(f"Unknown sizing_mode: {mode}")

    def _enter_position(
        self,
        ticker: str,
        score: float,
        trailing_pct: float,
        data: bt.DataBase,
        regime: int,
        current_date: datetime,
    ):
        """
        Submit entry order for a new position.

        NOTE: We do NOT add to PositionTracker here. We only register the INTENT.
        The actual position is created in notify_order() when the order is Completed.
        """
        price = data.close[0]
        atr = data.atr[0]

        # Position size based on sizing mode
        size_pct = self.calculate_position_size(regime, score, trailing_pct)
        position_value = self.broker.getvalue() * size_pct

        # Cap to available cash (leave 5% buffer for commissions/slippage)
        available_cash = self.broker.getcash() * 0.95
        if position_value > available_cash:
            position_value = available_cash

        shares = int(position_value / price)

        if shares < 3:  # Need at least 3 for 3 tranches
            return

        # Calculate initial stop: max(2*ATR, 10% of price) below entry
        stop_atr = price - (self.p.atr_stop_mult * atr)
        stop_pct = price * (1 - self.p.max_stop_pct)
        initial_stop = max(stop_atr, stop_pct)

        # Calculate target 1: max(3*ATR, 15%) above entry
        target1_atr = price + (self.p.atr_target1_mult * atr)
        target1_pct = price * (1 + self.p.min_target1_pct)
        target1 = max(target1_atr, target1_pct)

        # Calculate target 2: target1 + 2*ATR
        target2 = target1 + (self.p.atr_target2_add * atr)

        # Progressive fills: buy only the starter fraction now; the add fires later
        # when price clears +add_trigger_pct. full_target keeps tranche math right.
        if self.p.progressive_fills:
            starter = int(shares * self.p.starter_frac)
            if starter < 1:
                starter = shares  # too small to split — take it whole
            buy_size = starter
            add_trigger_price = price * (1.0 + self.p.add_trigger_pct)
        else:
            buy_size = shares
            add_trigger_price = 0.0

        # Submit market order
        order = self.buy(data=data, size=buy_size)

        # Register INTENT (not the actual position - that happens in notify_order)
        self.position_tracker.register_entry_intent(
            order_ref=order.ref,
            intent={
                'ticker': ticker,
                'entry_date': current_date,
                'entry_atr': atr,
                'initial_size': buy_size,
                'full_target_size': shares,
                'add_trigger_price': add_trigger_price,
                'initial_stop': initial_stop,
                'target1': target1,
                'target2': target2,
                'score': score,
                'trailing_pct': trailing_pct,
                'regime': regime,
            }
        )

        logger.info(f"Entry signal: {ticker} @ ~{price:.2f}, size={shares}, "
                   f"score={score:.1f}, trailing={trailing_pct:.3f}, "
                   f"stop={initial_stop:.2f}, T1={target1:.2f}")

    def stop(self):
        """Called at end of backtest."""
        stats = self.position_tracker.get_stats()
        logger.info(f"Backtest complete. Stats: {stats}")

    def get_exposure_stats(self) -> Dict:
        """Calculate exposure statistics from daily snapshots."""
        if not self.daily_snapshots:
            return {}

        exposures = []
        position_counts = []
        days_invested = 0

        for snap in self.daily_snapshots:
            exposure_pct = (snap.position_value / snap.portfolio_value * 100) if snap.portfolio_value > 0 else 0
            exposures.append(exposure_pct)
            position_counts.append(snap.position_count)
            if snap.position_count > 0:
                days_invested += 1

        return {
            'avg_exposure': sum(exposures) / len(exposures) if exposures else 0,
            'max_exposure': max(exposures) if exposures else 0,
            'min_exposure': min(exposures) if exposures else 0,
            'time_invested': (days_invested / len(self.daily_snapshots) * 100) if self.daily_snapshots else 0,
            'avg_positions': sum(position_counts) / len(position_counts) if position_counts else 0,
            'max_positions': max(position_counts) if position_counts else 0,
            'total_days': len(self.daily_snapshots),
            'days_invested': days_invested,
        }

    def get_signal_rejection_stats(self) -> Dict:
        """Summarize signal rejections by reason."""
        if not self.signal_rejections:
            return {'total_rejections': 0}

        by_reason: Dict[str, int] = {}
        for rej in self.signal_rejections:
            by_reason[rej.reason] = by_reason.get(rej.reason, 0) + 1

        return {
            'total_rejections': len(self.signal_rejections),
            'by_reason': by_reason,
        }

    def get_equity_curve(self) -> List[tuple]:
        """Return equity curve as list of (date, value) tuples."""
        return [(s.date, s.portfolio_value) for s in self.daily_snapshots]


class SEPAFlatV1(SEPAHybridV1):
    """
    Flat-sizing variant of the SEPA strategy.

    Differences from SEPAHybridV1:
        - Equal-weight position sizing (no regime-based scaling)
        - Flat percentage stop loss (no ATR-based stops)
        - Uniform position limits across regimes (still liquidates on Strong Bear)
        - Higher prob_elite threshold (sweep-optimized default)

    All exit mechanics (3-tranche targets, SMA trend break) are inherited.
    """

    params = (
        # Override regime to flat: same limits in all non-bear regimes
        ('regime_sizes', {0: 0.0, 1: 0.10, 2: 0.10, 3: 0.10, 4: 0.10}),
        ('regime_max_pos', {0: 0, 1: 10, 2: 10, 3: 10, 4: 10}),

        # Entry: sweep-optimized defaults
        ('min_score', 30),
        ('entry_percentile_min', 0.0),
        ('entry_mode', 'percentile'),
        ('entry_top_n', None),
        ('rank_by', 'trailing'),
        ('min_price', 5.0),
        ('min_dollar_volume', 0),
        ('cooldown_days', 3),
        ('min_prob_elite', 0.25),

        # Flat stop: disable ATR, rely on max_stop_pct
        ('atr_stop_mult', 0.0),
        ('max_stop_pct', 0.12),

        # Targets (inherited, kept for tranche exits)
        ('atr_target1_mult', 3.0),
        ('min_target1_pct', 0.15),
        ('atr_target2_add', 2.0),
        ('sma_exit_period', 50),

        # Rank exits
        ('exit_percentile_max', 0.40),
        ('exit_use_percentile', False),

        # Equal-weight sizing
        ('sizing_mode', 'equal_weight'),

        # Score lookup (required by parent)
        ('scores_df', None),

        # Warmup
        ('warmup_days', 10),
    )

