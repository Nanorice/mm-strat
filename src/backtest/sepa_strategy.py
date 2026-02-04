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

from .score_lookup import ScoreLookup
from .position_tracker import PositionTracker

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
    reason: str  # 'cooldown', 'already_holding', 'no_slots', 'low_liquidity', 'low_price', 'no_data'


class SEPAHybridV1(bt.Strategy):
    """
    SEPA Hybrid V1 BackTrader Strategy.

    Parameters:
        - regime_sizes: Position size % by regime (0-4)
        - regime_max_pos: Max positions by regime (0-4)
        - min_score: Minimum normalized M01 score (0-100) - absolute floor
        - min_percentile: Percentile gate (0.0 = no gate, 0.95 = top 5%)
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
    """

    params = (
        # Regime sizing (from strategy spec)
        ('regime_sizes', {0: 0.0, 1: 0.025, 2: 0.05, 3: 0.075, 4: 0.10}),
        ('regime_max_pos', {0: 0, 1: 4, 2: 8, 3: 10, 4: 12}),

        # Entry filters (Top N Competition mode)
        # - min_score: absolute floor on M01 prediction quality
        # - min_percentile: set to 0.0 for "Top N Competition" (no hard gate)
        # - rank_by: 'trailing' uses 10-day cohort percentile, 'daily' uses single-day
        # NOTE: Regime controls exposure; percentile is just a ranking metric now
        ('min_score', 30.0),  # Safety floor (scaled 0-100) - very permissive
        ('min_percentile', 0.0),  # 0.0 = no gate (Top N Competition mode)
        ('rank_by', 'trailing'),  # 'trailing' = 10-day cohort, 'daily' = single-day
        ('min_price', 1.0),
        ('min_dollar_volume', 0),
        ('cooldown_days', 3),

        # Exit params
        ('atr_stop_mult', 2.0),
        ('max_stop_pct', 0.10),
        ('atr_target1_mult', 3.0),
        ('min_target1_pct', 0.15),
        ('atr_target2_add', 2.0),
        ('sma_exit_period', 50),

        # Score lookup path
        ('scores_path', 'data/backtest/universe_scores.parquet'),
    )

    def __init__(self):
        """Initialize strategy components."""
        # Score lookup for candidate filtering
        self.score_lookup = ScoreLookup(self.p.scores_path)

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
            # Order failed - clean up pending flags
            ticker = order.data._name
            if order.isbuy():
                self.position_tracker.pending_entries.pop(order.ref, None)
            else:
                exit_info = self.pending_orders.pop(order.ref, {})
                exit_reason = exit_info.get('reason', 'unknown')

                # Clear pending flags so we can retry
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
        3. Update trailing stops for open positions
        4. Check stop-outs
        5. Check profit targets
        6. Check trend exits (tranche 3)
        7. Process new entries
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

        # === UPDATE TRAILING STOPS ===
        self._update_all_stops()

        # === CHECK STOP-OUTS ===
        self._check_stops(current_date)

        # === CHECK PROFIT TARGETS ===
        self._check_targets()

        # === CHECK TREND EXITS (Tranche 3) ===
        self._check_trend_exits()

        # === ENTRY LOGIC ===
        self._process_entries(regime, current_date)

    def _record_daily_snapshot(self, current_date: datetime, regime: int):
        """Record daily portfolio state for exposure metrics."""
        portfolio_value = self.broker.getvalue()
        cash = self.broker.getcash()
        position_value = portfolio_value - cash
        position_count = self.position_tracker.get_open_count()

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
            self.position_tracker.update_stops(ticker, current_atr, current_high)

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
        for ticker, pos in list(self.position_tracker.positions.items()):
            data = self.stock_feeds.get(ticker)
            if data is None:
                continue

            # Check targets
            target_hit = self.position_tracker.check_targets(ticker, data.high[0])

            if target_hit == 'target1' and not pos.tranche1_sold and not pos.tranche1_pending:
                # Sell tranche 1 (1/3 of initial)
                sell_size = pos.tranche_size
                if sell_size > 0 and sell_size <= pos.remaining_shares:
                    order = self.sell(data=data, size=sell_size)
                    self.pending_orders[order.ref] = {'reason': 'target1', 'ticker': ticker}
                    pos.tranche1_pending = True  # Prevent duplicate orders
                    logger.info(f"Target 1 hit for {ticker}: selling {sell_size} shares")

            elif target_hit == 'target2' and not pos.tranche2_sold and not pos.tranche2_pending:
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

            # Only check trend exit after T1 and T2 are sold
            if not (pos.tranche1_sold and pos.tranche2_sold):
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

    def _process_entries(self, regime: int, current_date: datetime):
        """Process new entry signals with rejection tracking."""
        # Check position limits
        max_positions = self.p.regime_max_pos[regime]
        current_count = self.position_tracker.get_open_count()
        available_slots = max_positions - current_count

        # Get candidates sorted by trailing percentile (Top N Competition)
        candidates = self.score_lookup.get_candidates(
            current_date,
            min_score=self.p.min_score,
            min_percentile=self.p.min_percentile,
            rank_by=self.p.rank_by,
        )
        
        if not candidates:
            return

        # Filter candidates with rejection tracking
        valid_candidates = []
        for ticker, score, trailing_pct in candidates:
            # Skip if in cooldown
            if self.position_tracker.is_in_cooldown(ticker, current_date, self.p.cooldown_days):
                self.signal_rejections.append(SignalRejection(
                    date=current_date, ticker=ticker, score=score, reason='cooldown'
                ))
                continue

            # Skip if already holding
            if self.position_tracker.has_position(ticker):
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

            valid_candidates.append((ticker, score, trailing_pct, data))

        # Track "no_slots" rejections for candidates that passed filters but couldn't enter
        if available_slots <= 0:
            for ticker, score, trailing_pct, data in valid_candidates:
                self.signal_rejections.append(SignalRejection(
                    date=current_date, ticker=ticker, score=score, reason='no_slots'
                ))
            return

        # Track "no_slots" for candidates beyond available slots
        for ticker, score, trailing_pct, data in valid_candidates[available_slots:]:
            self.signal_rejections.append(SignalRejection(
                date=current_date, ticker=ticker, score=score, reason='no_slots'
            ))

        # Enter top N by trailing percentile (already sorted)
        for ticker, score, trailing_pct, data in valid_candidates[:available_slots]:
            self._enter_position(ticker, score, trailing_pct, data, regime, current_date)

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

        # Position size based on regime
        size_pct = self.p.regime_sizes[regime]
        position_value = self.broker.getvalue() * size_pct
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

        # Submit market order
        order = self.buy(data=data, size=shares)

        # Register INTENT (not the actual position - that happens in notify_order)
        self.position_tracker.register_entry_intent(
            order_ref=order.ref,
            intent={
                'ticker': ticker,
                'entry_date': current_date,
                'entry_atr': atr,
                'initial_size': shares,
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
