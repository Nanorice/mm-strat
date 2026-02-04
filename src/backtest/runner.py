"""
SEPA Backtest Runner
====================
Orchestrates backtest execution with BackTrader.

Handles:
- Loading and configuring data feeds
- Broker configuration (cash, commission, slippage)
- Strategy instantiation
- Analyzer attachment
- Results extraction
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

import backtrader as bt
import pandas as pd

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
import config

from .feeds import SEPAStockFeed, M03RegimeFeed
from .sepa_strategy import SEPAHybridV1
from .price_feed import list_prepared_tickers, get_qualifying_tickers
from .report import generate_report

logger = logging.getLogger(__name__)

BACKTEST_DATA_DIR = config.DATA_DIR / 'backtest'


class SEPABacktestRunner:
    """
    Orchestrates SEPA backtest execution.

    Usage:
        runner = SEPABacktestRunner()
        runner.setup()
        results = runner.run()
        runner.print_results()
    """

    def __init__(
        self,
        start_date: str = '2020-01-01',
        end_date: str = '2025-01-01',
        initial_cash: float = 100_000,
        commission: float = 0.005,  # $0.005 per share
        slippage_pct: float = 0.001,  # 0.1%
        regime_path: Optional[str] = None,
        prices_dir: Optional[str] = None,
        scores_path: Optional[str] = None,
    ):
        """
        Initialize backtest runner.

        Args:
            start_date: Backtest start date (YYYY-MM-DD)
            end_date: Backtest end date (YYYY-MM-DD)
            initial_cash: Starting capital
            commission: Commission per share
            slippage_pct: Slippage as percentage
            regime_path: Path to M03 regime parquet
            prices_dir: Directory containing price parquets
            scores_path: Path to universe scores parquet
        """
        self.start_date = pd.to_datetime(start_date)
        self.end_date = pd.to_datetime(end_date)
        self.initial_cash = initial_cash
        self.commission = commission
        self.slippage_pct = slippage_pct

        # Paths
        self.regime_path = Path(regime_path) if regime_path else BACKTEST_DATA_DIR / 'm03_feed.parquet'
        self.prices_dir = Path(prices_dir) if prices_dir else BACKTEST_DATA_DIR / 'prices'
        self.scores_path = Path(scores_path) if scores_path else BACKTEST_DATA_DIR / 'universe_scores.parquet'
        
        # Filtering defaults
        self.stock_min_score = 30.0
        self.stock_min_percentile = 0.0

        self.cerebro: Optional[bt.Cerebro] = None
        self.results: Optional[List] = None
        self.strategy: Optional[SEPAHybridV1] = None

        # Tracking data for analysis
        self.regime_df: Optional[pd.DataFrame] = None  # For regime overlay plotting

    def setup(self, max_tickers: Optional[int] = None, specific_tickers: List[str] = None):
        """
        Set up Cerebro with data feeds, broker, and strategy.

        Args:
            max_tickers: Limit number of tickers loaded (for testing)
            specific_tickers: A list of specific tickers to include.
        """
        logger.info("Setting up backtest...")

        self.cerebro = bt.Cerebro()

        # === ADD M03 REGIME FEED (must be first) ===
        if not self.regime_path.exists():
            raise FileNotFoundError(f"Regime data not found: {self.regime_path}")
            
        regime_df = pd.read_parquet(self.regime_path)
        regime_df = self._filter_date_range(regime_df)
        # Filter out weekends (Saturday=5, Sunday=6) to prevent backfill distortion
        regime_df = regime_df[regime_df.index.dayofweek < 5]
        self.regime_df = regime_df.copy()  # Store for plotting

        regime_feed = M03RegimeFeed(
            dataname=regime_df,
            name='regime',
            fromdate=self.start_date,
            todate=self.end_date,
        )
        self.cerebro.adddata(regime_feed, name='regime')
        logger.info(f"Added regime feed ({len(regime_df)} bars)")

        # === ADD STOCK FEEDS ===
        # Get qualifying tickers from scores
        tickers = get_qualifying_tickers(
            self.scores_path,
            min_score=self.stock_min_score,
            min_percentile=self.stock_min_percentile
        )
        
        # Apply filters
        if specific_tickers:
            # Filter to specific whitelist
            tickers = [t for t in tickers if t in specific_tickers]
            logger.info(f"Filtered to {len(tickers)} specific tickers")
        elif max_tickers:
            # Random sample (deterministic via sort)
            tickers = sorted(list(tickers))[:max_tickers]
            logger.info(f"Limited to top {max_tickers} tickers by sort order")
            
        if not tickers:
            raise ValueError("No qualifying tickers found! Check constraints.")

        self._add_price_feeds(tickers)

        # === CONFIGURE BROKER ===
        self.cerebro.broker.setcash(self.initial_cash)
        self.cerebro.broker.setcommission(
             commission=self.commission,
             commtype=bt.CommInfoBase.COMM_FIXED,
        )
        self.cerebro.broker.set_slippage_perc(perc=self.slippage_pct)

    def _add_price_feeds(self, tickers: List[str]):
        """Adds stock price data feeds for the given tickers to cerebro."""
        if not tickers:
            logger.warning("No tickers provided to add price feeds.")
            return

        loaded_count = 0
        for ticker in tickers:
            try:
                price_path = self.prices_dir / f'{ticker}.parquet'
                if not price_path.exists():
                    logger.debug(f"Price data not found for {ticker} at {price_path}. Skipping.")
                    continue

                df = pd.read_parquet(price_path)
                df = self._filter_date_range(df)

                if len(df) < 50:  # Skip tickers with insufficient data
                    logger.debug(f"Skipping {ticker}: insufficient data ({len(df)} bars).")
                    continue

                feed = SEPAStockFeed(
                    dataname=df,
                    name=ticker,
                    fromdate=self.start_date,
                    todate=self.end_date,
                )
                self.cerebro.adddata(feed, name=ticker)
                loaded_count += 1

            except Exception as e:
                logger.debug(f"Failed to load {ticker}: {e}")
                continue

        logger.info(f"Added {loaded_count} stock feeds")

        # === CONFIGURE BROKER ===
        self.cerebro.broker.setcash(self.initial_cash)

        # Commission: fixed per share
        self.cerebro.broker.setcommission(
            commission=self.commission,
            commtype=bt.CommInfoBase.COMM_FIXED,
        )

        # Slippage: percentage-based
        self.cerebro.broker.set_slippage_perc(
            perc=self.slippage_pct,
            slip_open=True,
            slip_limit=True,
            slip_match=True,
            slip_out=False,
        )

        logger.info(f"Broker configured: cash=${self.initial_cash:,.0f}, "
                   f"commission=${self.commission}/share, slippage={self.slippage_pct*100:.1f}%")

        # === ADD STRATEGY ===
        self.cerebro.addstrategy(
            SEPAHybridV1,
            scores_path=str(self.scores_path),
        )

        # === ADD ANALYZERS ===
        self.cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe',
                                  timeframe=bt.TimeFrame.Days, annualize=True)
        self.cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        self.cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
        self.cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
        self.cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')

        logger.info("Setup complete")

    def _filter_date_range(self, df: pd.DataFrame) -> pd.DataFrame:
        """Filter DataFrame to backtest date range."""
        if df.index.name != 'date':
            df = df.set_index('date')
        df.index = pd.to_datetime(df.index)
        return df[(df.index >= self.start_date) & (df.index <= self.end_date)]

    def run(self) -> Dict[str, Any]:
        """
        Execute the backtest.

        Returns:
            Dict with backtest results and metrics
        """
        if self.cerebro is None:
            raise RuntimeError("Call setup() before run()")

        logger.info(f"Running backtest: {self.start_date.date()} to {self.end_date.date()}")

        starting_value = self.cerebro.broker.getvalue()
        self.results = self.cerebro.run()
        self.strategy = self.results[0]
        ending_value = self.cerebro.broker.getvalue()

        # Extract metrics
        metrics = self._extract_metrics()
        metrics['starting_value'] = starting_value
        metrics['ending_value'] = ending_value
        metrics['total_return'] = (ending_value - starting_value) / starting_value * 100

        logger.info(f"Backtest complete. Final value: ${ending_value:,.2f} "
                   f"({metrics['total_return']:+.1f}%)")

        return metrics

    def _extract_metrics(self) -> Dict[str, Any]:
        """Extract metrics from analyzers."""
        if self.strategy is None:
            return {}

        metrics = {}

        # Sharpe Ratio
        try:
            sharpe = self.strategy.analyzers.sharpe.get_analysis()
            metrics['sharpe_ratio'] = sharpe.get('sharperatio', None)
        except Exception:
            metrics['sharpe_ratio'] = None

        # Drawdown
        try:
            dd = self.strategy.analyzers.drawdown.get_analysis()
            metrics['max_drawdown'] = dd.get('max', {}).get('drawdown', 0)
            metrics['max_drawdown_len'] = dd.get('max', {}).get('len', 0)
        except Exception:
            metrics['max_drawdown'] = None
            metrics['max_drawdown_len'] = None

        # Trade Analysis
        try:
            trades = self.strategy.analyzers.trades.get_analysis()
            metrics['total_trades'] = trades.get('total', {}).get('total', 0)
            metrics['won_trades'] = trades.get('won', {}).get('total', 0)
            metrics['lost_trades'] = trades.get('lost', {}).get('total', 0)

            if metrics['total_trades'] > 0:
                metrics['win_rate'] = metrics['won_trades'] / metrics['total_trades'] * 100
            else:
                metrics['win_rate'] = 0

            # PnL
            pnl = trades.get('pnl', {})
            metrics['gross_profit'] = pnl.get('gross', {}).get('total', 0)
            metrics['net_profit'] = pnl.get('net', {}).get('total', 0)
        except Exception:
            metrics['total_trades'] = 0
            metrics['win_rate'] = 0

        # Returns
        try:
            returns = self.strategy.analyzers.returns.get_analysis()
            metrics['avg_return'] = returns.get('ravg', 0) * 100
        except Exception:
            metrics['avg_return'] = None

        # SQN (System Quality Number)
        try:
            sqn = self.strategy.analyzers.sqn.get_analysis()
            metrics['sqn'] = sqn.get('sqn', None)
        except Exception:
            metrics['sqn'] = None

        # Position tracker stats
        try:
            tracker_stats = self.strategy.position_tracker.get_stats()
            metrics['tracker_stats'] = tracker_stats
        except Exception:
            metrics['tracker_stats'] = {}

        # Exposure stats
        try:
            exposure_stats = self.strategy.get_exposure_stats()
            metrics['exposure_stats'] = exposure_stats
        except Exception:
            metrics['exposure_stats'] = {}

        # Signal rejection stats
        try:
            rejection_stats = self.strategy.get_signal_rejection_stats()
            metrics['rejection_stats'] = rejection_stats
        except Exception:
            metrics['rejection_stats'] = {}

        return metrics

    def get_equity_curve_dataframe(self) -> Optional[pd.DataFrame]:
        """
        Get daily equity curve as DataFrame.

        Returns:
            DataFrame with date index and columns: value, cash, position_value, position_count, regime
        """
        if self.strategy is None:
            return None

        snapshots = self.strategy.daily_snapshots
        if not snapshots:
            return None

        records = []
        for snap in snapshots:
            records.append({
                'date': snap.date,
                'value': snap.portfolio_value,
                'cash': snap.cash,
                'position_value': snap.position_value,
                'position_count': snap.position_count,
                'regime': snap.regime,
            })

        df = pd.DataFrame(records)
        df['date'] = pd.to_datetime(df['date'])
        return df.set_index('date')

    def get_trade_dataframe(self) -> Optional[pd.DataFrame]:
        """
        Convert closed positions to DataFrame for report generation.

        Returns:
            DataFrame with trade details or None if no strategy run yet
        """
        if self.strategy is None:
            return None

        closed = self.strategy.position_tracker.closed_positions
        if not closed:
            return None

        records = []
        for pos in closed:
            records.append({
                'ticker': pos.ticker,
                'entry_date': pos.entry_date,
                'entry_price': pos.entry_price,
                'exit_date': pos.exit_date,
                'exit_price': pos.exit_price,
                'exit_reason': pos.exit_reason,
                'entry_regime': pos.regime,
                'entry_score': pos.score,
                'initial_size': pos.initial_size,
                'pnl_percent': pos.pnl_percent,
                'holding_days': (pos.exit_date - pos.entry_date).days if pos.exit_date and pos.entry_date else 0,
            })

        return pd.DataFrame(records)

    def save_report(self, metrics: Dict[str, Any], output_dir: Optional[Path] = None) -> str:
        """
        Generate and save markdown report.

        Args:
            metrics: Dict from run() with backtest metrics
            output_dir: Directory to save report (default: data/backtest/reports/)

        Returns:
            Path to saved report
        """
        if output_dir is None:
            output_dir = BACKTEST_DATA_DIR / 'reports'

        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')
        report_path = output_dir / f'backtest_report_{timestamp}.md'

        trade_df = self.get_trade_dataframe()
        equity_curve = self.get_equity_curve_dataframe()

        # Extract strategy params if available
        strategy_params = {}
        if self.strategy is not None:
            strategy_params = {
                'min_score': self.strategy.p.min_score,
                'min_percentile': self.strategy.p.min_percentile,
                'atr_stop_mult': self.strategy.p.atr_stop_mult,
                'atr_target1_mult': self.strategy.p.atr_target1_mult,
            }

        generate_report(
            metrics=metrics,
            trade_df=trade_df,
            equity_curve=equity_curve,
            output_path=str(report_path),
            start_date=str(self.start_date.date()),
            end_date=str(self.end_date.date()),
            initial_cash=self.initial_cash,
            strategy_params=strategy_params,
        )

        return str(report_path)

    def print_results(self, metrics: Optional[Dict] = None):
        """Print formatted backtest results."""
        if metrics is None:
            metrics = self._extract_metrics()

        print("\n" + "=" * 60)
        print("SEPA HYBRID V1 BACKTEST RESULTS")
        print("=" * 60)

        print(f"\nPeriod: {self.start_date.date()} to {self.end_date.date()}")
        print(f"Starting Capital: ${self.initial_cash:,.0f}")

        print("\n--- PERFORMANCE ---")
        print(f"Final Value:     ${metrics.get('ending_value', 0):,.2f}")
        print(f"Total Return:    {metrics.get('total_return', 0):+.2f}%")
        print(f"Sharpe Ratio:    {metrics.get('sharpe_ratio', 'N/A')}")
        print(f"SQN:             {metrics.get('sqn', 'N/A')}")

        print("\n--- RISK ---")
        print(f"Max Drawdown:    {metrics.get('max_drawdown', 0):.2f}%")
        print(f"Max DD Length:   {metrics.get('max_drawdown_len', 0)} bars")

        print("\n--- TRADES ---")
        print(f"Total Trades:    {metrics.get('total_trades', 0)}")
        print(f"Win Rate:        {metrics.get('win_rate', 0):.1f}%")
        print(f"Won/Lost:        {metrics.get('won_trades', 0)}/{metrics.get('lost_trades', 0)}")
        print(f"Net Profit:      ${metrics.get('net_profit', 0):,.2f}")

        # Exposure stats
        exposure = metrics.get('exposure_stats', {})
        if exposure:
            print("\n--- EXPOSURE ---")
            print(f"Avg Exposure:    {exposure.get('avg_exposure', 0):.1f}%")
            print(f"Max Exposure:    {exposure.get('max_exposure', 0):.1f}%")
            print(f"Time Invested:   {exposure.get('time_invested', 0):.1f}%")
            print(f"Avg Positions:   {exposure.get('avg_positions', 0):.1f}")

        # Signal rejection stats
        rejections = metrics.get('rejection_stats', {})
        if rejections and rejections.get('total_rejections', 0) > 0:
            print("\n--- SIGNAL REJECTIONS ---")
            print(f"Total Rejected:  {rejections['total_rejections']:,}")
            by_reason = rejections.get('by_reason', {})
            top_reasons = sorted(by_reason.items(), key=lambda x: -x[1])[:3]
            for reason, count in top_reasons:
                print(f"  - {reason}: {count:,}")

        print("\n" + "=" * 60)

    def plot(self, save_path: Optional[str] = None, **kwargs):
        """
        Plot comprehensive backtest results with diagnostics.

        Generates a 3x2 panel with:
        1. Equity curve with regime overlay
        2. Underwater (drawdown) plot
        3. Monthly returns heatmap
        4. PnL distribution
        5. Performance by regime
        6. Exit reason breakdown

        Args:
            save_path: If provided, save plot to this path instead of displaying
        """
        if self.strategy is None:
            raise RuntimeError("No backtest to plot. Run backtest first.")

        try:
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
            from matplotlib.patches import Patch
        except ImportError:
            logger.error("matplotlib required for plotting. Install with: pip install matplotlib")
            return

        # Get closed trades for analysis
        trade_df = self.get_trade_dataframe()
        if trade_df is None or len(trade_df) == 0:
            logger.warning("No closed trades to plot")
            return

        fig, axes = plt.subplots(3, 2, figsize=(16, 14))
        fig.suptitle('SEPA Hybrid V1 Backtest Results', fontsize=14, fontweight='bold')

        trade_df_sorted = trade_df.sort_values('exit_date').copy()
        trade_df_sorted['exit_date'] = pd.to_datetime(trade_df_sorted['exit_date'])
        trade_df_sorted['cumulative_pnl'] = trade_df_sorted['pnl_percent'].cumsum()

        # === 1. EQUITY CURVE WITH REGIME OVERLAY ===
        ax1 = axes[0, 0]
        self._plot_equity_with_regime(ax1, trade_df_sorted)

        # === 2. UNDERWATER (DRAWDOWN) PLOT ===
        ax2 = axes[0, 1]
        self._plot_underwater(ax2, trade_df_sorted)

        # === 3. MONTHLY RETURNS HEATMAP ===
        ax3 = axes[1, 0]
        self._plot_monthly_heatmap(ax3, trade_df_sorted)

        # === 4. PNL DISTRIBUTION ===
        ax4 = axes[1, 1]
        colors = ['green' if x > 0 else 'red' for x in trade_df_sorted['pnl_percent']]
        ax4.bar(range(len(trade_df_sorted)), trade_df_sorted['pnl_percent'], color=colors, alpha=0.7)
        ax4.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        ax4.axhline(y=-10, color='red', linestyle='--', linewidth=1, alpha=0.7, label='10% Hard Stop')
        ax4.set_title('Individual Trade PnL %')
        ax4.set_xlabel('Trade #')
        ax4.set_ylabel('PnL %')
        ax4.legend(loc='lower left')
        ax4.grid(True, alpha=0.3)

        # === 5. PERFORMANCE BY REGIME ===
        ax5 = axes[2, 0]
        regime_names = {0: 'Strong Bear', 1: 'Bear', 2: 'Neutral', 3: 'Bull', 4: 'Strong Bull'}
        regime_stats = trade_df.groupby('entry_regime')['pnl_percent'].agg(['mean', 'count'])
        regime_labels = [regime_names.get(r, f'R{r}') for r in regime_stats.index]
        bars = ax5.bar(regime_labels, regime_stats['mean'], color='steelblue', alpha=0.7)
        ax5.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        ax5.set_title('Avg PnL % by Entry Regime')
        ax5.set_ylabel('Avg PnL %')
        for bar, count in zip(bars, regime_stats['count']):
            ax5.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                    f'n={int(count)}', ha='center', va='bottom', fontsize=9)
        ax5.grid(True, alpha=0.3)

        # === 6. EXIT REASON BREAKDOWN ===
        ax6 = axes[2, 1]
        exit_counts = trade_df['exit_reason'].value_counts()
        colors_exit = ['#ff6b6b', '#4ecdc4', '#45b7d1', '#96ceb4', '#ffeaa7', '#dfe6e9']
        ax6.pie(exit_counts.values, labels=exit_counts.index, autopct='%1.1f%%',
                colors=colors_exit[:len(exit_counts)])
        ax6.set_title('Exit Reasons')

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            logger.info(f"Plot saved to {save_path}")
            plt.close(fig)
        else:
            plt.show()

    def _plot_equity_with_regime(self, ax, trade_df: pd.DataFrame):
        """Plot equity curve with regime background colors."""
        from matplotlib.patches import Patch

        # Plot cumulative PnL
        ax.plot(trade_df['exit_date'], trade_df['cumulative_pnl'], 'b-', linewidth=1.5, zorder=3)
        ax.axhline(y=0, color='gray', linestyle='--', alpha=0.5, zorder=2)

        # Add regime overlay if available
        if self.regime_df is not None and len(self.regime_df) > 0:
            regime_colors = {
                0: '#ffcccc',  # Strong Bear - light red
                1: '#ffe6cc',  # Bear - light orange
                2: '#ffffcc',  # Neutral - light yellow
                3: '#ccffcc',  # Bull - light green
                4: '#ccffdd',  # Strong Bull - bright green
            }

            dates = self.regime_df.index.to_pydatetime()
            regimes = self.regime_df['regime_cat'].values

            # Create regime spans
            i = 0
            while i < len(dates) - 1:
                regime = regimes[i]
                start = dates[i]
                # Find end of this regime period
                j = i + 1
                while j < len(dates) and regimes[j] == regime:
                    j += 1
                end = dates[j - 1] if j < len(dates) else dates[-1]

                ax.axvspan(start, end, alpha=0.3, color=regime_colors.get(regime, 'white'), zorder=1)
                i = j

            # Legend for regimes
            legend_elements = [
                Patch(facecolor='#ffcccc', alpha=0.5, label='Strong Bear'),
                Patch(facecolor='#ffe6cc', alpha=0.5, label='Bear'),
                Patch(facecolor='#ffffcc', alpha=0.5, label='Neutral'),
                Patch(facecolor='#ccffcc', alpha=0.5, label='Bull'),
                Patch(facecolor='#ccffdd', alpha=0.5, label='Strong Bull'),
            ]
            ax.legend(handles=legend_elements, loc='upper left', fontsize=7)

        ax.set_title('Equity Curve with Regime Overlay')
        ax.set_xlabel('Date')
        ax.set_ylabel('Cumulative PnL %')
        ax.grid(True, alpha=0.3, zorder=0)

    def _plot_underwater(self, ax, trade_df: pd.DataFrame):
        """Plot underwater (drawdown) chart."""
        cumulative = trade_df['cumulative_pnl'].values
        running_max = pd.Series(cumulative).cummax().values
        drawdown = cumulative - running_max

        ax.fill_between(trade_df['exit_date'], 0, drawdown, color='red', alpha=0.5)
        ax.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        ax.set_title('Underwater Plot (Drawdown from Peak)')
        ax.set_xlabel('Date')
        ax.set_ylabel('Drawdown %')
        ax.grid(True, alpha=0.3)

        # Annotate max drawdown
        min_dd = drawdown.min()
        min_dd_idx = drawdown.argmin()
        min_dd_date = trade_df['exit_date'].iloc[min_dd_idx]
        ax.annotate(f'Max DD: {min_dd:.1f}%',
                   xy=(min_dd_date, min_dd),
                   xytext=(10, 10), textcoords='offset points',
                   fontsize=9, color='red',
                   arrowprops=dict(arrowstyle='->', color='red', lw=0.5))

    def _plot_monthly_heatmap(self, ax, trade_df: pd.DataFrame):
        """Plot monthly returns heatmap."""
        # Group by year-month
        trade_df = trade_df.copy()
        trade_df['exit_date'] = pd.to_datetime(trade_df['exit_date'])
        trade_df['year'] = trade_df['exit_date'].dt.year
        trade_df['month'] = trade_df['exit_date'].dt.month

        monthly = trade_df.groupby(['year', 'month'])['pnl_percent'].sum().unstack(fill_value=0)

        # Create heatmap
        import numpy as np

        if len(monthly) == 0:
            ax.text(0.5, 0.5, 'Insufficient data for heatmap',
                   ha='center', va='center', transform=ax.transAxes)
            ax.set_title('Monthly Returns Heatmap')
            return

        im = ax.imshow(monthly.values, cmap='RdYlGn', aspect='auto',
                      vmin=-10, vmax=10)

        # Labels
        month_labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                       'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

        ax.set_xticks(range(len(monthly.columns)))
        ax.set_xticklabels([month_labels[m-1] for m in monthly.columns], fontsize=8)
        ax.set_yticks(range(len(monthly.index)))
        ax.set_yticklabels(monthly.index, fontsize=8)

        # Add text annotations
        for i in range(len(monthly.index)):
            for j in range(len(monthly.columns)):
                val = monthly.iloc[i, j]
                color = 'white' if abs(val) > 5 else 'black'
                ax.text(j, i, f'{val:.1f}', ha='center', va='center',
                       fontsize=7, color=color)

        ax.set_title('Monthly Returns Heatmap (%)')
        import matplotlib.pyplot as plt
        plt.colorbar(im, ax=ax, shrink=0.8)


def run_backtest(
    start_date: str = '2020-01-01',
    end_date: str = '2025-01-01',
    initial_cash: float = 100_000,
    max_tickers: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Convenience function to run a backtest.

    Args:
        start_date: Start date
        end_date: End date
        initial_cash: Starting capital
        max_tickers: Limit tickers (for testing)

    Returns:
        Dict with backtest metrics
    """
    runner = SEPABacktestRunner(
        start_date=start_date,
        end_date=end_date,
        initial_cash=initial_cash,
    )
    runner.setup(max_tickers=max_tickers)
    metrics = runner.run()
    runner.print_results(metrics)
    return metrics


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    run_backtest()
