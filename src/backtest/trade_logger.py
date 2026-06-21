"""
Trade Logger - Detailed Trade Event Logging
============================================
Logs every trade for post-analysis, including entry/exit details,
P&L, and exit reasons.
"""

import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class TradeLog:
    """
    Complete record of a single trade.

    Captures entry, exit, and performance details for post-analysis.
    """
    # Entry info
    ticker: str
    entry_date: datetime
    entry_price: float
    entry_score: float
    entry_regime: int
    entry_atr: float
    initial_size: int
    initial_stop: float
    target1: float
    target2: float

    # Exit info
    exit_date: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None  # 'stop', 'target1', 'target2', 'trend', 'liquidation'
    final_size: int = 0  # Remaining shares at close

    # Performance
    pnl_dollars: float = 0.0
    pnl_percent: float = 0.0
    holding_days: int = 0

    # Tranche details
    tranche1_date: Optional[datetime] = None
    tranche1_price: Optional[float] = None
    tranche2_date: Optional[datetime] = None
    tranche2_price: Optional[float] = None

    @property
    def is_winner(self) -> bool:
        """Trade was profitable."""
        return self.pnl_percent > 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class TradeLogger:
    """
    Logs and manages trade records.

    Usage:
        logger = TradeLogger()
        logger.log_entry(...)
        logger.log_partial_exit(...)
        logger.save('trades.parquet')
    """

    def __init__(self):
        self.trades: Dict[str, TradeLog] = {}  # ticker -> active trade
        self.closed_trades: List[TradeLog] = []

    def log_entry(
        self,
        ticker: str,
        entry_date: datetime,
        entry_price: float,
        entry_score: float,
        entry_regime: int,
        entry_atr: float,
        initial_size: int,
        initial_stop: float,
        target1: float,
        target2: float,
    ):
        """Log a new trade entry."""
        trade = TradeLog(
            ticker=ticker,
            entry_date=entry_date,
            entry_price=entry_price,
            entry_score=entry_score,
            entry_regime=entry_regime,
            entry_atr=entry_atr,
            initial_size=initial_size,
            initial_stop=initial_stop,
            target1=target1,
            target2=target2,
        )
        self.trades[ticker] = trade
        logger.debug(f"Logged entry: {ticker} @ {entry_price:.2f}")

    def log_partial_exit(
        self,
        ticker: str,
        exit_date: datetime,
        exit_price: float,
        shares_sold: int,
        exit_reason: str,
    ):
        """Log a partial or full exit."""
        trade = self.trades.get(ticker)
        if trade is None:
            logger.warning(f"No active trade for {ticker}")
            return

        # Track tranche exits
        if exit_reason == 'target1':
            trade.tranche1_date = exit_date
            trade.tranche1_price = exit_price
        elif exit_reason == 'target2':
            trade.tranche2_date = exit_date
            trade.tranche2_price = exit_price

        # Update final exit info
        trade.exit_date = exit_date
        trade.exit_price = exit_price
        trade.exit_reason = exit_reason
        trade.final_size = trade.initial_size - shares_sold

        # If fully closed, calculate final stats
        if trade.final_size <= 0:
            self._finalize_trade(trade)

    def _finalize_trade(self, trade: TradeLog):
        """Calculate final P&L and move to closed trades."""
        # Calculate holding period
        if trade.exit_date and trade.entry_date:
            trade.holding_days = (trade.exit_date - trade.entry_date).days

        # Calculate P&L (simplified - actual calc would track partial exits)
        if trade.exit_price and trade.entry_price:
            trade.pnl_percent = (trade.exit_price - trade.entry_price) / trade.entry_price * 100
            trade.pnl_dollars = (trade.exit_price - trade.entry_price) * trade.initial_size

        # Move to closed
        self.closed_trades.append(trade)
        del self.trades[trade.ticker]

        logger.debug(f"Closed trade: {trade.ticker}, PnL={trade.pnl_percent:.1f}%")

    def get_open_trades(self) -> List[TradeLog]:
        """Get all open trades."""
        return list(self.trades.values())

    def get_closed_trades(self) -> List[TradeLog]:
        """Get all closed trades."""
        return self.closed_trades

    def to_dataframe(self) -> pd.DataFrame:
        """Convert closed trades to DataFrame."""
        if not self.closed_trades:
            return pd.DataFrame()

        records = [t.to_dict() for t in self.closed_trades]
        return pd.DataFrame(records)

    def save(self, path: str):
        """Save closed trades to parquet."""
        df = self.to_dataframe()
        if len(df) > 0:
            df.to_parquet(path, index=False)
            logger.info(f"Saved {len(df)} trades to {path}")

    def load(self, path: str):
        """Load trades from parquet."""
        if not Path(path).exists():
            return

        df = pd.read_parquet(path)
        self.closed_trades = [
            TradeLog(**row.to_dict())
            for _, row in df.iterrows()
        ]
        logger.info(f"Loaded {len(self.closed_trades)} trades from {path}")

    def get_stats(self) -> Dict[str, Any]:
        """Calculate trade statistics."""
        if not self.closed_trades:
            return {}

        winners = [t for t in self.closed_trades if t.is_winner]
        losers = [t for t in self.closed_trades if not t.is_winner]

        return {
            'total_trades': len(self.closed_trades),
            'winners': len(winners),
            'losers': len(losers),
            'win_rate': len(winners) / len(self.closed_trades) * 100 if self.closed_trades else 0,
            'avg_win': sum(t.pnl_percent for t in winners) / len(winners) if winners else 0,
            'avg_loss': sum(t.pnl_percent for t in losers) / len(losers) if losers else 0,
            'avg_holding_days': sum(t.holding_days for t in self.closed_trades) / len(self.closed_trades),
            'total_pnl': sum(t.pnl_dollars for t in self.closed_trades),
            'largest_win': max((t.pnl_percent for t in winners), default=0),
            'largest_loss': min((t.pnl_percent for t in losers), default=0),
        }

    def get_exit_breakdown(self) -> Dict[str, int]:
        """Count trades by exit reason."""
        reasons = {}
        for trade in self.closed_trades:
            reason = trade.exit_reason or 'unknown'
            reasons[reason] = reasons.get(reason, 0) + 1
        return reasons

    def get_regime_breakdown(self) -> Dict[int, Dict[str, float]]:
        """Analyze performance by entry regime."""
        by_regime = {}
        for trade in self.closed_trades:
            regime = trade.entry_regime
            if regime not in by_regime:
                by_regime[regime] = {'trades': 0, 'wins': 0, 'total_pnl': 0}

            by_regime[regime]['trades'] += 1
            if trade.is_winner:
                by_regime[regime]['wins'] += 1
            by_regime[regime]['total_pnl'] += trade.pnl_percent

        # Calculate win rates
        for regime in by_regime:
            stats = by_regime[regime]
            stats['win_rate'] = stats['wins'] / stats['trades'] * 100 if stats['trades'] > 0 else 0
            stats['avg_pnl'] = stats['total_pnl'] / stats['trades'] if stats['trades'] > 0 else 0

        return by_regime
