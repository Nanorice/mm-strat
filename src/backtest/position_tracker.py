"""
Position Tracker - Multi-Tranche Position State Management
==========================================================
Tracks SEPA positions with 3-tranche exit logic and trailing stops.

CRITICAL DESIGN PRINCIPLE:
This class is a READ-MODEL synchronized via notify_order().
- State mutations happen ONLY when orders are Completed
- Never mutate state based on order submission
- BackTrader's broker is the source of truth
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SEPAPosition:
    """
    Tracks a single SEPA position with 3-tranche exit logic.

    Lifecycle:
    1. Entry: Created when entry order is FILLED (not submitted)
    2. Tranche 1: Sell 33% when target1 is hit, move stop to breakeven+
    3. Tranche 2: Sell 33% when target2 is hit, tighten trailing stop
    4. Tranche 3: Sell remaining when Close < SMA(50) or stopped out
    """

    ticker: str
    entry_date: datetime
    entry_price: float
    entry_atr: float
    initial_size: int
    score: float
    regime: int

    # Calculated at entry
    initial_stop: float = 0.0
    target1: float = 0.0
    target2: float = 0.0

    # Tranche tracking (updated via notify_order)
    tranche1_sold: bool = False
    tranche2_sold: bool = False
    remaining_shares: int = 0

    # Pending order flags (prevent duplicate orders)
    tranche1_pending: bool = False
    tranche2_pending: bool = False
    exit_pending: bool = False  # For stop/trend/liquidation exits

    # Stop tracking (high-water mark - never moves down)
    current_stop: float = 0.0

    # Exit tracking
    exit_date: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None  # Final exit reason (stop, trend, etc.)

    # Max progression tracking (for accurate exit reason reporting)
    # Records the highest target level reached before final exit
    max_progression: int = 0  # 0=none, 1=hit T1, 2=hit T2

    # Calculated fields
    def __post_init__(self):
        self.remaining_shares = self.initial_size
        self.current_stop = self.initial_stop

    @property
    def is_closed(self) -> bool:
        """Position is fully closed when no shares remain."""
        return self.remaining_shares <= 0

    @property
    def tranche_size(self) -> int:
        """Size of one tranche (1/3 of initial)."""
        return max(1, self.initial_size // 3)

    @property
    def pnl_percent(self) -> Optional[float]:
        """P&L percentage if closed."""
        if self.exit_price is None:
            return None
        return (self.exit_price - self.entry_price) / self.entry_price * 100

    @property
    def effective_exit_reason(self) -> Optional[str]:
        """
        Get the effective exit reason accounting for max progression.

        A trade that hit T1, then T2, then stopped out should be classified
        based on max progression, not just the final event.

        Returns:
            - 'target2_then_stop': Hit T2, final exit was stop (trailing profit)
            - 'target1_then_stop': Hit T1 only, final exit was stop
            - 'target2': Exited at T2 (T3 via trend or liquidation)
            - 'target1': Exited at T1 only
            - exit_reason: Original reason if no targets were hit
        """
        if self.exit_reason is None:
            return None

        # If final exit was stop/trend/liquidation but we hit targets first
        if self.exit_reason in ('stop', 'trend', 'regime_liquidation'):
            if self.max_progression == 2:
                return 'target2_then_stop'  # Trailing profit (hit T2)
            elif self.max_progression == 1:
                return 'target1_then_stop'  # Partial win (hit T1)

        # No progression modification needed
        return self.exit_reason

    def update_stop(self, new_stop: float) -> bool:
        """
        Update stop price (high-water mark logic - never moves down).

        Args:
            new_stop: Proposed new stop price

        Returns:
            True if stop was updated, False if ignored (would move down)
        """
        if new_stop > self.current_stop:
            self.current_stop = new_stop
            return True
        return False


class PositionTracker:
    """
    Manages all open positions and cooldown logic.

    IMPORTANT: This class is a READ-MODEL synchronized via notify_order().
    - add_position() is called ONLY when entry order is Completed
    - record_partial_exit() is called ONLY when exit order is Completed
    - Never mutate state based on order submission, only on execution

    Usage in strategy:
        def notify_order(self, order):
            if order.status == order.Completed:
                if order.isbuy():
                    intent = self.position_tracker.pending_entries.pop(order.ref)
                    self.position_tracker.confirm_entry(order.ref, order.executed.price, order.executed.size)
                else:
                    self.position_tracker.record_partial_exit(ticker, shares, price, reason)
    """

    def __init__(self):
        self.positions: Dict[str, SEPAPosition] = {}
        self.closed_positions: List[SEPAPosition] = []
        self.cooldowns: Dict[str, datetime] = {}  # ticker -> stopped_out_date
        self.pending_entries: Dict[int, dict] = {}  # order_ref -> entry intent

    def register_entry_intent(self, order_ref: int, intent: dict):
        """
        Register intent to open a position (called when order is submitted).

        Args:
            order_ref: BackTrader order reference
            intent: Dict with entry parameters (ticker, entry_date, atr, etc.)

        Note:
            This does NOT create the position. The position is created in
            confirm_entry() when the order is actually filled.
        """
        self.pending_entries[order_ref] = intent
        logger.debug(f"Registered entry intent for {intent['ticker']} (order_ref={order_ref})")

    def confirm_entry(
        self,
        order_ref: int,
        executed_price: float,
        executed_size: int,
    ) -> Optional[SEPAPosition]:
        """
        Confirm position entry when order is FILLED.

        Called from notify_order() when entry order status is Completed.

        Args:
            order_ref: BackTrader order reference
            executed_price: Actual fill price
            executed_size: Actual fill size

        Returns:
            Created SEPAPosition or None if no pending intent
        """
        intent = self.pending_entries.pop(order_ref, None)
        if intent is None:
            logger.warning(f"No pending intent for order_ref={order_ref}")
            return None

        ticker = intent['ticker']

        # Create position with executed values
        pos = SEPAPosition(
            ticker=ticker,
            entry_date=intent['entry_date'],
            entry_price=executed_price,
            entry_atr=intent['entry_atr'],
            initial_size=executed_size,
            score=intent['score'],
            regime=intent['regime'],
            initial_stop=intent['initial_stop'],
            target1=intent['target1'],
            target2=intent['target2'],
        )

        self.positions[ticker] = pos
        logger.info(f"Opened position: {ticker} @ {executed_price:.2f}, "
                   f"size={executed_size}, stop={pos.current_stop:.2f}")

        return pos

    def record_partial_exit(
        self,
        ticker: str,
        shares_sold: int,
        exit_price: float,
        exit_reason: str,
        exit_date: Optional[datetime] = None,
    ) -> bool:
        """
        Record a partial or full exit when sell order is FILLED.

        Called from notify_order() when exit order status is Completed.

        Args:
            ticker: Stock ticker
            shares_sold: Number of shares sold
            exit_price: Actual fill price
            exit_reason: 'stop', 'target1', 'target2', 'trend', 'liquidation'
            exit_date: Date of exit (optional)

        Returns:
            True if position was updated, False if ticker not found
        """
        pos = self.positions.get(ticker)
        if pos is None:
            logger.warning(f"No position found for {ticker}")
            return False

        pos.remaining_shares -= shares_sold

        # Track exit info
        pos.exit_price = exit_price
        pos.exit_reason = exit_reason
        if exit_date:
            pos.exit_date = exit_date

        # Update tranche flags and max progression based on reason
        if exit_reason == 'target1':
            pos.tranche1_sold = True
            pos.max_progression = max(pos.max_progression, 1)
        elif exit_reason == 'target2':
            pos.tranche2_sold = True
            pos.max_progression = max(pos.max_progression, 2)

        logger.info(f"Exit {ticker}: sold {shares_sold} @ {exit_price:.2f} "
                   f"({exit_reason}), remaining={pos.remaining_shares}")

        # If fully closed, move to closed list and set cooldown if stopped
        if pos.is_closed:
            self._close_position(ticker, exit_reason, exit_date)

        return True

    def _close_position(
        self,
        ticker: str,
        exit_reason: str,
        exit_date: Optional[datetime] = None,
    ):
        """Move position to closed list and handle cooldown."""
        pos = self.positions.pop(ticker, None)
        if pos is None:
            return

        self.closed_positions.append(pos)
        logger.info(f"Closed position: {ticker}, reason={exit_reason}, "
                   f"PnL={pos.pnl_percent:.1f}%" if pos.pnl_percent else "")

        # Set cooldown if stopped out
        if exit_reason == 'stop' and exit_date:
            self.cooldowns[ticker] = exit_date
            logger.debug(f"Set cooldown for {ticker} starting {exit_date}")

    def is_in_cooldown(
        self,
        ticker: str,
        current_date: datetime,
        cooldown_days: int = 3,
    ) -> bool:
        """
        Check if ticker is in stop-out cooldown period.

        Args:
            ticker: Stock ticker
            current_date: Current trading date
            cooldown_days: Days to wait after stop-out

        Returns:
            True if ticker is still in cooldown
        """
        stopped_date = self.cooldowns.get(ticker)
        if stopped_date is None:
            return False

        # Normalize to date objects
        if hasattr(current_date, 'date'):
            current_date = current_date.date()
        if hasattr(stopped_date, 'date'):
            stopped_date = stopped_date.date()

        days_since = (current_date - stopped_date).days
        return days_since < cooldown_days

    def get_position(self, ticker: str) -> Optional[SEPAPosition]:
        """Get position for a ticker (None if not held)."""
        return self.positions.get(ticker)

    def has_position(self, ticker: str) -> bool:
        """Check if holding a position in ticker."""
        return ticker in self.positions

    def get_open_count(self) -> int:
        """Get number of open positions."""
        return len(self.positions)

    def get_all_open(self) -> List[SEPAPosition]:
        """Get all open positions."""
        return list(self.positions.values())

    def get_all_closed(self) -> List[SEPAPosition]:
        """Get all closed positions."""
        return self.closed_positions

    def update_stops(
        self,
        ticker: str,
        current_atr: float,
        current_high: float,
    ) -> Optional[float]:
        """
        Update trailing stop for a position.

        The stop logic depends on tranche state:
        - Before T1: Don't trail (stay at initial stop)
        - After T1: Moderate trail (1.5 * ATR from high)
        - After T2: Tight trail (1.0 * ATR from high)

        Args:
            ticker: Stock ticker
            current_atr: Current 14-day ATR
            current_high: Today's high price

        Returns:
            New stop price if updated, None if not found or not moved
        """
        pos = self.positions.get(ticker)
        if pos is None:
            return None

        # Calculate new potential stop based on tranche state
        if pos.tranche2_sold:
            # Tight trail after T2
            new_stop = current_high - (1.0 * current_atr)
        elif pos.tranche1_sold:
            # Moderate trail after T1
            new_stop = current_high - (1.5 * current_atr)
        else:
            # No trailing before T1 - keep initial stop
            return None

        # High-water mark: only move up
        if pos.update_stop(new_stop):
            logger.debug(f"Updated stop for {ticker}: {pos.current_stop:.2f}")
            return pos.current_stop

        return None

    def check_stops(
        self,
        ticker: str,
        current_low: float,
    ) -> bool:
        """
        Check if stop was hit.

        Args:
            ticker: Stock ticker
            current_low: Today's low price

        Returns:
            True if stop was hit (current_low <= stop)
        """
        pos = self.positions.get(ticker)
        if pos is None:
            return False

        return current_low <= pos.current_stop

    def check_targets(
        self,
        ticker: str,
        current_high: float,
    ) -> Optional[str]:
        """
        Check if a profit target was hit.

        Args:
            ticker: Stock ticker
            current_high: Today's high price

        Returns:
            'target1', 'target2', or None
        """
        pos = self.positions.get(ticker)
        if pos is None:
            return None

        if not pos.tranche1_sold and current_high >= pos.target1:
            return 'target1'

        if not pos.tranche2_sold and current_high >= pos.target2:
            return 'target2'

        return None

    def get_stats(self) -> Dict:
        """Get summary statistics with detailed exit reason breakdown."""
        all_closed = self.closed_positions

        if not all_closed:
            return {
                'open_positions': len(self.positions),
                'closed_positions': 0,
            }

        wins = [p for p in all_closed if p.pnl_percent and p.pnl_percent > 0]
        losses = [p for p in all_closed if p.pnl_percent and p.pnl_percent <= 0]

        # Exit reason breakdown using effective_exit_reason
        exit_reasons: Dict[str, int] = {}
        for p in all_closed:
            reason = p.effective_exit_reason or 'unknown'
            exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

        # Distinguish true stop losses from trailing profit stops
        true_stop_losses = [
            p for p in all_closed
            if p.effective_exit_reason == 'stop' and p.pnl_percent and p.pnl_percent <= 0
        ]
        trailing_profit_stops = [
            p for p in all_closed
            if p.effective_exit_reason in ('target1_then_stop', 'target2_then_stop')
        ]

        return {
            'open_positions': len(self.positions),
            'closed_positions': len(all_closed),
            'win_count': len(wins),
            'loss_count': len(losses),
            'win_rate': len(wins) / len(all_closed) if all_closed else 0,
            'avg_win': sum(p.pnl_percent for p in wins) / len(wins) if wins else 0,
            'avg_loss': sum(p.pnl_percent for p in losses) / len(losses) if losses else 0,
            'exit_reasons': exit_reasons,
            'true_stop_losses': len(true_stop_losses),
            'trailing_profit_stops': len(trailing_profit_stops),
        }
