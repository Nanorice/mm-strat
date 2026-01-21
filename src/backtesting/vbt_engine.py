"""
VectorBT-based backtesting engine for individual trade analysis.
"""

import pandas as pd
import numpy as np
import vectorbt as vbt
from typing import Optional


class VectorBTBacktester:
    """
    Analyzes a single trade's actual trajectory using VectorBT.

    Takes a trade's complete OHLCV trajectory and simulates the entry/exit
    to calculate proper performance metrics (Sharpe, Sortino, drawdowns).
    """

    def __init__(self, trade_data: pd.DataFrame, freq: str = '1D'):
        """
        Args:
            trade_data: Subset of d2_rehydrated for ONE trade_id
                       Must have columns: date, open, high, low, close, volume
            freq: Time frequency for VectorBT (default '1D' for daily)
        """
        # Normalize column names to lowercase
        trade_data.columns = [c.lower() for c in trade_data.columns]

        # Validate required columns
        required = ['date', 'open', 'high', 'low', 'close', 'volume']
        missing = [c for c in required if c not in trade_data.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        # Store trade data with date as index
        self.data = trade_data.copy()
        if 'date' in self.data.columns:
            self.data['date'] = pd.to_datetime(self.data['date'])
            self.data.set_index('date', inplace=True)

        self.freq = freq
        self.portfolio: Optional[vbt.Portfolio] = None

        # Store metadata
        self.trade_id = trade_data['trade_id'].iloc[0] if 'trade_id' in trade_data.columns else None
        self.ticker = trade_data['ticker'].iloc[0] if 'ticker' in trade_data.columns else None
        self.entry_date = self.data.index[0]
        self.exit_date = self.data.index[-1]
        self.days_held = len(self.data)

    def run_simulation(
        self,
        position_size: float = 10000,
        fees: float = 0.001,
    ) -> vbt.Portfolio:
        """
        Simulates the actual trade using VectorBT.

        Entry: Uses 'open' price of first row (T+1 open, assuming T close = T+1 open)
        Exit: Uses 'close' price of last row (actual exit date)

        Args:
            position_size: Dollar amount to invest (default $10k)
            fees: Trading fees as decimal (default 0.001 = 0.1%)

        Returns:
            VectorBT Portfolio object
        """
        # Create entry/exit signals
        entries = pd.Series(False, index=self.data.index)
        exits = pd.Series(False, index=self.data.index)

        entries.iloc[0] = True  # Enter on first day
        exits.iloc[-1] = True   # Exit on last day

        # Price arrays for execution
        # Entry: use 'open' of first day, then 'close' for rest
        # Exit: use 'close'
        entry_price = self.data['close'].copy()
        entry_price.iloc[0] = self.data['open'].iloc[0]  # Override first day with open

        exit_price = self.data['close'].copy()

        # Run VectorBT simulation
        self.portfolio = vbt.Portfolio.from_signals(
            close=self.data['close'],
            entries=entries,
            exits=exits,
            price=entry_price,  # Use for entry execution
            freq=self.freq,
            fees=fees,
            size=position_size,
            size_type='value',  # Fixed dollar amount
            init_cash=position_size,  # Ensure we have enough cash
        )

        return self.portfolio

    def get_metrics(self) -> dict:
        """
        Extract comprehensive metrics from the portfolio.

        Returns:
            dict with keys: sharpe, sortino, max_drawdown_pct, max_favorable_excursion_pct,
                           total_return_pct, calmar, win_rate, peak_date, days_to_peak
        """
        if self.portfolio is None:
            raise RuntimeError("Must run run_simulation() first")

        # Get equity curve
        equity = self.portfolio.value()
        initial_value = equity.iloc[0]

        # Calculate MDD and MFE
        running_max = equity.expanding().max()
        drawdown = (equity - running_max) / running_max * 100
        max_drawdown_pct = drawdown.min()

        favorable_excursion = (equity - initial_value) / initial_value * 100
        max_fav_exc_pct = favorable_excursion.max()

        # Find peak date
        peak_idx = equity.idxmax()
        peak_date = peak_idx
        days_to_peak = (peak_idx - self.entry_date).days if isinstance(peak_idx, pd.Timestamp) else None

        # Total return
        total_return_pct = self.portfolio.total_return() * 100

        # Get VectorBT stats (handle cases where stats might not be available)
        try:
            sharpe = self.portfolio.sharpe_ratio()
        except:
            sharpe = None

        try:
            sortino = self.portfolio.sortino_ratio()
        except:
            sortino = None

        try:
            calmar = self.portfolio.calmar_ratio()
        except:
            calmar = None

        # Win rate (1.0 if positive return, 0.0 if negative)
        win_rate = 1.0 if total_return_pct > 0 else 0.0

        return {
            'sharpe': sharpe,
            'sortino': sortino,
            'calmar': calmar,
            'max_drawdown_pct': max_drawdown_pct,
            'max_favorable_excursion_pct': max_fav_exc_pct,
            'total_return_pct': total_return_pct,
            'win_rate': win_rate,
            'peak_date': peak_date,
            'days_to_peak': days_to_peak,
            'days_held': self.days_held,
            'entry_date': self.entry_date,
            'exit_date': self.exit_date,
        }

    def plot_equity_curve(self, title: Optional[str] = None) -> None:
        """
        Plots the equity curve for this trade.

        Args:
            title: Optional custom title (default uses ticker and trade_id)
        """
        if self.portfolio is None:
            raise RuntimeError("Must run run_simulation() first")

        if title is None:
            title = f"Equity Curve - {self.ticker} (Trade {self.trade_id})" if self.ticker else "Equity Curve"

        self.portfolio.plot(title=title).show()

    def plot_drawdown(self, title: Optional[str] = None) -> None:
        """
        Plots the underwater drawdown chart.

        Args:
            title: Optional custom title
        """
        if self.portfolio is None:
            raise RuntimeError("Must run run_simulation() first")

        if title is None:
            title = f"Drawdown - {self.ticker} (Trade {self.trade_id})" if self.ticker else "Drawdown"

        self.portfolio.plot_drawdowns(title=title).show()


if __name__ == '__main__':
    """
    Demo: Analyze a single trade from d2_rehydrated.
    """
    print("=== VectorBTBacktester Demo ===\n")

    # Load d2_rehydrated
    d2_path = 'data/ml/d2_rehydrated.parquet'
    print(f"Loading {d2_path}...")
    d2 = pd.read_parquet(d2_path)

    # Get first trade
    trade_id = d2['trade_id'].iloc[0]
    print(f"Analyzing trade_id={trade_id}")

    trade_data = d2[d2['trade_id'] == trade_id].copy()
    print(f"Trade duration: {len(trade_data)} days")
    print(f"Ticker: {trade_data['ticker'].iloc[0]}")

    # Initialize backtester
    backtester = VectorBTBacktester(trade_data)

    # Run simulation
    print("\nRunning simulation...")
    portfolio = backtester.run_simulation(position_size=10000, fees=0.001)

    # Get metrics
    metrics = backtester.get_metrics()
    print("\n=== Metrics ===")
    for key, value in metrics.items():
        if isinstance(value, float):
            print(f"{key}: {value:.2f}")
        else:
            print(f"{key}: {value}")

    # Optional: Plot (comment out if running headless)
    # print("\nGenerating plots...")
    # backtester.plot_equity_curve()
    # backtester.plot_drawdown()

    print("\nDemo complete!")
