"""
Backtesting Engine - Event-Driven Simulation
Handles position management, portfolio constraints, and trade execution.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import logging

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
import config
from src.strategy import SEPAStrategy

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """
    Represents a single open trade position.
    """
    ticker: str
    entry_date: pd.Timestamp
    entry_price: float
    stop_price: float
    target_price: float
    shares: int
    position_value: float
    status: str = 'open'  # 'open' or 'closed'

    # Exit tracking
    exit_date: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None

    def pnl(self, current_price: float = None) -> float:
        """Calculate profit/loss in dollars."""
        if self.status == 'closed' and self.exit_price:
            return (self.exit_price - self.entry_price) * self.shares
        elif current_price:
            return (current_price - self.entry_price) * self.shares
        return 0.0

    def pnl_pct(self, current_price: float = None) -> float:
        """Calculate profit/loss as percentage."""
        if self.status == 'closed' and self.exit_price:
            return ((self.exit_price - self.entry_price) / self.entry_price) * 100
        elif current_price:
            return ((current_price - self.entry_price) / self.entry_price) * 100
        return 0.0

    def close_position(self, exit_date: pd.Timestamp, exit_price: float, reason: str):
        """Mark position as closed."""
        self.status = 'closed'
        self.exit_date = exit_date
        self.exit_price = exit_price
        self.exit_reason = reason


class PortfolioManager:
    """
    Manages portfolio state, position sizing, and risk constraints.

    Key Responsibilities:
    - Enforce max position limit
    - Calculate position sizes
    - Track cash and equity
    - Manage open positions
    """

    def __init__(self, initial_capital: float = None, max_positions: int = None):
        """
        Initialize portfolio manager.

        Args:
            initial_capital: Starting cash
            max_positions: Maximum concurrent positions
        """
        self.initial_capital = initial_capital or config.INITIAL_CAPITAL
        self.max_positions = max_positions or config.MAX_POSITIONS

        self.cash = self.initial_capital
        self.positions: Dict[str, Position] = {}  # ticker -> Position
        self.closed_trades: List[Position] = []
        self.equity_curve: List[Tuple[pd.Timestamp, float]] = []

    def get_position_size(self, price: float) -> int:
        """
        Calculate number of shares to buy based on fixed fractional sizing.

        Args:
            price: Entry price per share

        Returns:
            Number of shares to buy
        """
        position_value = self.cash * config.POSITION_SIZE_PCT
        shares = int(position_value / price)
        return max(shares, 0)

    def can_open_position(self) -> bool:
        """Check if we can open a new position (under max limit and have cash)."""
        return len(self.positions) < self.max_positions and self.cash > 0

    def open_position(self, ticker: str, entry_date: pd.Timestamp,
                     entry_price: float, stop_price: float, target_price: float) -> Optional[Position]:
        """
        Opens a new position if capacity and cash available.

        Args:
            ticker: Stock symbol
            entry_date: Entry date
            entry_price: Entry price
            stop_price: Stop loss price
            target_price: Profit target price

        Returns:
            Position object if opened, None if rejected
        """
        if not self.can_open_position():
            logger.debug(f"Cannot open {ticker}: Max positions reached or no cash")
            return None

        shares = self.get_position_size(entry_price)
        if shares == 0:
            logger.debug(f"Cannot open {ticker}: Insufficient cash")
            return None

        position_value = shares * entry_price

        # Check if we have enough cash
        if position_value > self.cash:
            logger.debug(f"Cannot open {ticker}: Insufficient cash ({self.cash} < {position_value})")
            return None

        # Create position
        position = Position(
            ticker=ticker,
            entry_date=entry_date,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            shares=shares,
            position_value=position_value
        )

        # Deduct cash
        self.cash -= position_value

        # TODO: Deduct commission/slippage here when implemented
        # self.cash -= config.COMMISSION_PER_TRADE
        # actual_entry = entry_price * (1 + config.SLIPPAGE_PCT)

        # Add to open positions
        self.positions[ticker] = position

        logger.info(f"OPENED {ticker}: {shares} shares @ ${entry_price:.2f} (Stop: ${stop_price:.2f})")
        return position

    def close_position(self, ticker: str, exit_date: pd.Timestamp,
                      exit_price: float, reason: str) -> Optional[Position]:
        """
        Closes an open position.

        Args:
            ticker: Stock symbol
            exit_date: Exit date
            exit_price: Exit price
            reason: Exit reason (e.g., 'Stop Loss', 'Trend Break')

        Returns:
            Closed Position object
        """
        if ticker not in self.positions:
            return None

        position = self.positions[ticker]
        position.close_position(exit_date, exit_price, reason)

        # Return cash
        proceeds = position.shares * exit_price
        self.cash += proceeds

        # TODO: Deduct commission/slippage here when implemented
        # self.cash -= config.COMMISSION_PER_TRADE

        # Move to closed trades
        self.closed_trades.append(position)
        del self.positions[ticker]

        pnl_pct = position.pnl_pct()
        logger.info(f"CLOSED {ticker}: ${exit_price:.2f} ({pnl_pct:+.2f}%) - {reason}")

        return position

    def update_positions(self, date: pd.Timestamp, price_data: Dict[str, pd.DataFrame],
                        strategy: SEPAStrategy) -> List[Position]:
        """
        Checks all open positions for exit signals.

        Args:
            date: Current date
            price_data: Dict of ticker -> DataFrame with price data
            strategy: Strategy instance for exit logic

        Returns:
            List of closed positions
        """
        closed = []
        positions_to_close = []  # Store (ticker, exit_price, exit_reason) tuples

        # First pass: identify positions to close (don't modify dict yet)
        for ticker, position in list(self.positions.items()):  # Use list() to create a copy
            if ticker not in price_data:
                continue

            df = price_data[ticker]
            if date not in df.index:
                continue

            # Check exit signal
            should_exit, exit_reason = strategy.check_exit_signal(
                df, date, position.entry_price, position.stop_price
            )

            if should_exit:
                exit_price = df.loc[date, 'Close']

                # If stop loss, use stop price (assumes we got stopped out)
                if 'Stop Loss' in exit_reason:
                    exit_price = position.stop_price

                positions_to_close.append((ticker, exit_price, exit_reason))

        # Second pass: actually close the positions
        for ticker, exit_price, exit_reason in positions_to_close:
            closed_pos = self.close_position(ticker, date, exit_price, exit_reason)
            if closed_pos:
                closed.append(closed_pos)

        return closed

    def get_total_equity(self, current_prices: Dict[str, float]) -> float:
        """
        Calculate total portfolio equity (cash + open positions).

        Args:
            current_prices: Dict of ticker -> current price

        Returns:
            Total equity
        """
        equity = self.cash

        for ticker, position in self.positions.items():
            if ticker in current_prices:
                equity += position.shares * current_prices[ticker]
            else:
                # Use entry price if current price unavailable
                equity += position.position_value

        return equity

    def record_equity(self, date: pd.Timestamp, equity: float):
        """Record equity for given date."""
        self.equity_curve.append((date, equity))

    def get_equity_series(self) -> pd.Series:
        """Returns equity curve as a pandas Series."""
        if not self.equity_curve:
            return pd.Series()
        dates, values = zip(*self.equity_curve)
        return pd.Series(values, index=dates)

    def get_holdings_summary(self) -> pd.DataFrame:
        """Returns summary of current open positions."""
        if not self.positions:
            return pd.DataFrame()

        data = []
        for ticker, pos in self.positions.items():
            data.append({
                'Ticker': ticker,
                'Shares': pos.shares,
                'Entry Price': pos.entry_price,
                'Stop Price': pos.stop_price,
                'Target Price': pos.target_price,
                'Entry Date': pos.entry_date,
                'Position Value': pos.position_value
            })

        return pd.DataFrame(data)


class BacktestEngine:
    """
    Event-driven backtesting engine.
    Simulates day-by-day trading with realistic constraints.
    """

    def __init__(self, strategy: SEPAStrategy, portfolio: PortfolioManager):
        """
        Initialize backtest engine.

        Args:
            strategy: Trading strategy instance
            portfolio: Portfolio manager instance
        """
        self.strategy = strategy
        self.portfolio = portfolio

    def run(self, price_data: Dict[str, pd.DataFrame], start_date: str = None,
            end_date: str = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Runs the backtest over historical data.

        Args:
            price_data: Dict of ticker -> DataFrame with OHLCV + indicators
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            Tuple of (closed_trades_df, equity_curve_series)
        """
        start_date = pd.to_datetime(start_date or config.BACKTEST_START_DATE)
        end_date = pd.to_datetime(end_date or datetime.now())

        logger.info(f"Starting backtest from {start_date} to {end_date}")
        logger.info(f"Initial capital: ${self.portfolio.initial_capital:,.0f}")

        # Get all unique dates across all tickers
        all_dates = set()
        for df in price_data.values():
            all_dates.update(df.index)

        trading_dates = sorted([d for d in all_dates if start_date <= d <= end_date])

        logger.info(f"Simulating {len(trading_dates)} trading days...")

        for i, date in enumerate(trading_dates):
            # Progress indicator
            if i % 50 == 0:
                logger.info(f"Progress: {i}/{len(trading_dates)} days ({i/len(trading_dates)*100:.1f}%)")

            # Step 1: Check exits for existing positions
            self.portfolio.update_positions(date, price_data, self.strategy)

            # Step 2: Generate new signals and rank candidates
            candidates = []
            for ticker, df in price_data.items():
                if date not in df.index:
                    continue

                # Skip if already holding
                if ticker in self.portfolio.positions:
                    continue

                # Generate signal
                signal = self.strategy.generate_signals(df, date)

                if signal['buy'] and self.portfolio.can_open_position():
                    trade_plan = self.strategy.calculate_trade_plan(df, date)
                    if trade_plan:
                        candidates.append({
                            'ticker': ticker,
                            'signal_strength': signal['signal_strength'],
                            'trade_plan': trade_plan
                        })

            # Step 3: Rank and take top candidates (if more signals than capacity)
            if candidates:
                # Sort by signal strength (highest first)
                # TODO: Can add additional ranking factors (RS, volume, etc.)
                candidates = sorted(candidates, key=lambda x: x['signal_strength'], reverse=True)

                # Take positions up to max capacity
                for candidate in candidates:
                    if not self.portfolio.can_open_position():
                        break

                    ticker = candidate['ticker']
                    plan = candidate['trade_plan']

                    self.portfolio.open_position(
                        ticker=ticker,
                        entry_date=date,
                        entry_price=plan['entry_price'],
                        stop_price=plan['stop_price'],
                        target_price=plan['target_price']
                    )

            # Step 4: Record equity
            current_prices = {}
            for ticker, df in price_data.items():
                if date in df.index:
                    current_prices[ticker] = df.loc[date, 'Close']

            equity = self.portfolio.get_total_equity(current_prices)
            self.portfolio.record_equity(date, equity)

        # Backtest complete
        logger.info("Backtest complete!")
        logger.info(f"Total trades: {len(self.portfolio.closed_trades)}")
        logger.info(f"Open positions: {len(self.portfolio.positions)}")
        logger.info(f"Final equity: ${self.portfolio.get_total_equity(current_prices):,.0f}")

        # Convert results to DataFrames
        trades_df = self._trades_to_dataframe()
        equity_series = self.portfolio.get_equity_series()

        return trades_df, equity_series

    def _trades_to_dataframe(self) -> pd.DataFrame:
        """Converts closed trades to DataFrame for analysis."""
        if not self.portfolio.closed_trades:
            return pd.DataFrame()

        data = []
        for trade in self.portfolio.closed_trades:
            data.append({
                'Ticker': trade.ticker,
                'Entry Date': trade.entry_date,
                'Exit Date': trade.exit_date,
                'Entry Price': trade.entry_price,
                'Exit Price': trade.exit_price,
                'Shares': trade.shares,
                'PnL $': trade.pnl(),
                'PnL %': trade.pnl_pct(),
                'Exit Reason': trade.exit_reason,
                'Position Value': trade.position_value
            })

        return pd.DataFrame(data)
