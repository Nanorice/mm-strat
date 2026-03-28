"""
Custom BackTrader Analyzers for SEPA Backtest
==============================================
Provides additional performance metrics beyond built-in analyzers.
"""

import backtrader as bt


class CalmarRatio(bt.Analyzer):
    """
    Calmar Ratio = Annualized Return / Max Drawdown

    Measures return per unit of downside risk.
    Higher is better (>3.0 is excellent, >1.0 is good).

    Named after Terry W. Young's "California Managed Account Reports" newsletter.
    Commonly used in hedge fund performance evaluation.
    """

    def __init__(self):
        super().__init__()
        self._initial_value = None
        self._current_value = None
        self.calmar = 0.0
        self.annualized_return = 0.0
        self.max_dd = 0.0

    def start(self):
        """Initialize tracking at backtest start."""
        self._initial_value = self.strategy.broker.getvalue()

    def next(self):
        """Track portfolio value each day."""
        self._current_value = self.strategy.broker.getvalue()

    def stop(self):
        """Calculate final Calmar ratio at backtest end."""
        if self._initial_value is None or self._current_value is None:
            # No data - backtest didn't run
            self.calmar = 0.0
            self.annualized_return = 0.0
            self.max_dd = 0.0
            return

        # Get max drawdown from DrawDown analyzer (must be added before this analyzer)
        dd_analyzer = self.strategy.analyzers.getbyname('drawdown')
        if dd_analyzer:
            dd_analysis = dd_analyzer.get_analysis()
            # DrawDown returns percentage (e.g., 25.5 for 25.5%), convert to decimal
            self.max_dd = dd_analysis.get('max', {}).get('drawdown', 0.0) / 100.0
        else:
            self.max_dd = 0.0

        # Calculate total return
        total_return = (self._current_value - self._initial_value) / self._initial_value

        # Annualize based on backtest duration
        start_dt = self.strategy.datetime.date(ago=-len(self.strategy.data))
        end_dt = self.strategy.datetime.date()
        days = (end_dt - start_dt).days
        years = days / 365.25

        if years > 0:
            # Compound annual growth rate (CAGR)
            self.annualized_return = (1 + total_return) ** (1 / years) - 1
        else:
            self.annualized_return = 0.0

        # Calmar = Annualized Return / Max Drawdown
        if self.max_dd > 0:
            self.calmar = self.annualized_return / self.max_dd
        else:
            # No drawdown case
            if self.annualized_return > 0:
                self.calmar = float('inf')  # Infinite Calmar (perfect)
            else:
                self.calmar = 0.0  # No return, no drawdown

    def get_analysis(self):
        """Return Calmar ratio and components."""
        return {
            'calmar_ratio': self.calmar,
            'annualized_return': self.annualized_return,
            'max_drawdown': self.max_dd,
        }
