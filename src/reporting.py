"""
Performance Reporting - PerformanceReporter Class
Calculates metrics and generates visualizations for backtest results.
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from typing import Dict, Optional, Tuple
import logging
from pathlib import Path

import sys
sys.path.append(str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)

# Set style
sns.set_style('darkgrid')
plt.rcParams['figure.figsize'] = (12, 8)


class PerformanceReporter:
    """
    Calculates performance metrics and generates reports.
    """

    def __init__(self, trades_df: pd.DataFrame, equity_series: pd.Series,
                 initial_capital: float = None):
        """
        Initialize performance reporter.

        Args:
            trades_df: DataFrame of closed trades
            equity_series: Time series of portfolio equity
            initial_capital: Starting capital
        """
        self.trades = trades_df
        self.equity = equity_series
        self.initial_capital = initial_capital or config.INITIAL_CAPITAL

    def calculate_metrics(self) -> Dict:
        """
        Calculates comprehensive performance metrics.

        Returns:
            Dictionary of all performance metrics
        """
        if self.trades.empty:
            logger.warning("No trades to analyze")
            return {}

        metrics = {}

        # Basic Stats
        metrics['total_trades'] = len(self.trades)
        wins = self.trades[self.trades['PnL %'] > 0]
        losses = self.trades[self.trades['PnL %'] <= 0]

        metrics['winning_trades'] = len(wins)
        metrics['losing_trades'] = len(losses)
        metrics['win_rate'] = len(wins) / len(self.trades) if len(self.trades) > 0 else 0

        # P&L Stats
        metrics['total_pnl'] = self.trades['PnL $'].sum()
        metrics['avg_win'] = wins['PnL %'].mean() if not wins.empty else 0
        metrics['avg_loss'] = losses['PnL %'].mean() if not losses.empty else 0
        metrics['largest_win'] = wins['PnL %'].max() if not wins.empty else 0
        metrics['largest_loss'] = losses['PnL %'].min() if not losses.empty else 0

        # Profit Factor
        gross_profit = wins['PnL $'].sum() if not wins.empty else 0
        gross_loss = abs(losses['PnL $'].sum()) if not losses.empty else 0
        metrics['profit_factor'] = gross_profit / gross_loss if gross_loss > 0 else np.inf

        # Expectancy
        metrics['expectancy'] = self.trades['PnL %'].mean()

        # Equity Curve Metrics
        if not self.equity.empty:
            final_equity = self.equity.iloc[-1]
            metrics['final_equity'] = final_equity
            metrics['total_return'] = (final_equity / self.initial_capital) - 1
            metrics['total_return_pct'] = metrics['total_return'] * 100

            # Drawdown
            running_max = self.equity.cummax()
            drawdown = (self.equity - running_max) / running_max
            metrics['max_drawdown'] = drawdown.min()
            metrics['max_drawdown_pct'] = metrics['max_drawdown'] * 100

            # Sharpe Ratio (annualized)
            returns = self.equity.pct_change().dropna()
            if len(returns) > 0:
                excess_returns = returns - (config.RISK_FREE_RATE / 252)  # Daily risk-free rate
                if excess_returns.std() > 0:
                    metrics['sharpe_ratio'] = np.sqrt(252) * (excess_returns.mean() / excess_returns.std())
                else:
                    metrics['sharpe_ratio'] = 0

                # Sortino Ratio (uses only downside deviation)
                downside_returns = returns[returns < 0]
                if len(downside_returns) > 0 and downside_returns.std() > 0:
                    metrics['sortino_ratio'] = np.sqrt(252) * (returns.mean() / downside_returns.std())
                else:
                    metrics['sortino_ratio'] = 0
            else:
                metrics['sharpe_ratio'] = 0
                metrics['sortino_ratio'] = 0

            # CAGR (Compound Annual Growth Rate)
            years = (self.equity.index[-1] - self.equity.index[0]).days / 365.25
            if years > 0:
                metrics['cagr'] = ((final_equity / self.initial_capital) ** (1 / years)) - 1
            else:
                metrics['cagr'] = 0

        return metrics

    def print_summary(self):
        """Prints a formatted performance summary to console."""
        metrics = self.calculate_metrics()

        if not metrics:
            print("No performance data available.")
            return

        print("\n" + "=" * 70)
        print(" SEPA STRATEGY PERFORMANCE REPORT")
        print("=" * 70)

        print(f"\n[TRADING STATISTICS]")
        print(f"   Total Trades:        {metrics['total_trades']}")
        print(f"   Winning Trades:      {metrics['winning_trades']}")
        print(f"   Losing Trades:       {metrics['losing_trades']}")
        print(f"   Win Rate:            {metrics['win_rate']:.1%}")

        print(f"\n[PROFIT & LOSS]")
        print(f"   Total P&L:           ${metrics['total_pnl']:,.2f}")
        print(f"   Avg Win:             {metrics['avg_win']:.2f}%")
        print(f"   Avg Loss:            {metrics['avg_loss']:.2f}%")
        print(f"   Largest Win:         {metrics['largest_win']:.2f}%")
        print(f"   Largest Loss:        {metrics['largest_loss']:.2f}%")
        print(f"   Profit Factor:       {metrics['profit_factor']:.2f}")
        print(f"   Expectancy:          {metrics['expectancy']:.2f}%")

        if 'final_equity' in metrics:
            print(f"\n[PORTFOLIO PERFORMANCE]")
            print(f"   Initial Capital:     ${self.initial_capital:,.0f}")
            print(f"   Final Equity:        ${metrics['final_equity']:,.0f}")
            print(f"   Total Return:        {metrics['total_return_pct']:.2f}%")
            print(f"   CAGR:                {metrics.get('cagr', 0):.2f}%")
            print(f"   Max Drawdown:        {metrics['max_drawdown_pct']:.2f}%")
            print(f"   Sharpe Ratio:        {metrics['sharpe_ratio']:.2f}")
            print(f"   Sortino Ratio:       {metrics['sortino_ratio']:.2f}")

        print("=" * 70 + "\n")

    def plot_performance(self, save_path: Optional[str] = None):
        """
        Creates comprehensive performance visualizations.

        Args:
            save_path: Optional path to save the figure
        """
        if self.trades.empty or self.equity.empty:
            logger.warning("Insufficient data for plotting")
            return

        fig, axes = plt.subplots(3, 2, figsize=(15, 12))
        fig.suptitle('SEPA Strategy Performance Analysis', fontsize=16, fontweight='bold')

        # 1. Equity Curve
        ax1 = axes[0, 0]
        ax1.plot(self.equity.index, self.equity.values, color='blue', linewidth=2)
        ax1.axhline(y=self.initial_capital, color='red', linestyle='--', alpha=0.5, label='Start')
        ax1.set_title('Equity Curve')
        ax1.set_ylabel('Portfolio Value ($)')
        ax1.grid(True, alpha=0.3)
        ax1.legend()
        ax1.ticklabel_format(style='plain', axis='y')

        # 2. Drawdown (Underwater Plot)
        ax2 = axes[0, 1]
        running_max = self.equity.cummax()
        drawdown = (self.equity - running_max) / running_max
        ax2.fill_between(drawdown.index, drawdown.values * 100, 0, color='red', alpha=0.3)
        ax2.plot(drawdown.index, drawdown.values * 100, color='red', linewidth=1)
        ax2.set_title('Drawdown')
        ax2.set_ylabel('Drawdown %')
        ax2.grid(True, alpha=0.3)

        # 3. PnL Distribution
        ax3 = axes[1, 0]
        sns.histplot(self.trades['PnL %'], bins=30, kde=True, ax=ax3, color='green')
        ax3.axvline(0, color='black', linestyle='--', linewidth=1)
        ax3.set_title('Trade PnL Distribution')
        ax3.set_xlabel('PnL %')
        ax3.set_ylabel('Frequency')

        # 4. Cumulative Returns
        ax4 = axes[1, 1]
        cumulative_returns = (self.equity / self.initial_capital - 1) * 100
        ax4.plot(cumulative_returns.index, cumulative_returns.values, color='green', linewidth=2)
        ax4.axhline(0, color='black', linestyle='-', linewidth=0.5)
        ax4.set_title('Cumulative Returns')
        ax4.set_ylabel('Return %')
        ax4.grid(True, alpha=0.3)

        # 5. Monthly Returns Heatmap
        ax5 = axes[2, 0]
        try:
            returns = self.equity.pct_change()
            monthly_returns = returns.resample('M').apply(lambda x: (1 + x).prod() - 1) * 100
            monthly_pivot = monthly_returns.to_frame('Return')
            monthly_pivot['Year'] = monthly_pivot.index.year
            monthly_pivot['Month'] = monthly_pivot.index.month
            pivot_table = monthly_pivot.pivot(index='Year', columns='Month', values='Return')

            sns.heatmap(pivot_table, annot=True, fmt='.1f', cmap='RdYlGn', center=0,
                       ax=ax5, cbar_kws={'label': 'Return %'})
            ax5.set_title('Monthly Returns Heatmap')
        except Exception as e:
            logger.debug(f"Could not create monthly heatmap: {e}")
            ax5.text(0.5, 0.5, 'Insufficient data', ha='center', va='center')
            ax5.set_title('Monthly Returns Heatmap')

        # 6. Win/Loss Breakdown
        ax6 = axes[2, 1]
        wins = len(self.trades[self.trades['PnL %'] > 0])
        losses = len(self.trades[self.trades['PnL %'] <= 0])
        ax6.bar(['Wins', 'Losses'], [wins, losses], color=['green', 'red'], alpha=0.7)
        ax6.set_title('Win/Loss Distribution')
        ax6.set_ylabel('Number of Trades')
        for i, v in enumerate([wins, losses]):
            ax6.text(i, v + 0.5, str(v), ha='center', fontweight='bold')

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            logger.info(f"Performance chart saved to {save_path}")

        plt.show()

    def get_top_trades(self, n: int = 5) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Returns top N winners and losers.

        Args:
            n: Number of trades to return

        Returns:
            Tuple of (top_winners, top_losers) DataFrames
        """
        if self.trades.empty:
            return pd.DataFrame(), pd.DataFrame()

        winners = self.trades.sort_values('PnL %', ascending=False).head(n)
        losers = self.trades.sort_values('PnL %', ascending=True).head(n)

        return winners, losers

    def export_trades(self, file_path: str):
        """
        Exports trade log to CSV.

        Args:
            file_path: Path to save CSV file
        """
        if self.trades.empty:
            logger.warning("No trades to export")
            return

        self.trades.to_csv(file_path, index=False)
        logger.info(f"Trades exported to {file_path}")

    def generate_html_report(self, output_path: str):
        """
        Generates an HTML performance report.

        Args:
            output_path: Path to save HTML file
        """
        metrics = self.calculate_metrics()
        winners, losers = self.get_top_trades(5)

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>SEPA Strategy Performance Report</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h1 {{ color: #333; }}
                h2 {{ color: #666; margin-top: 30px; }}
                table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
                th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
                th {{ background-color: #4CAF50; color: white; }}
                .metric {{ font-weight: bold; }}
                .positive {{ color: green; }}
                .negative {{ color: red; }}
            </style>
        </head>
        <body>
            <h1>SEPA Strategy Performance Report</h1>
            <p>Generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

            <h2>Summary Metrics</h2>
            <table>
                <tr><td class="metric">Total Trades</td><td>{metrics.get('total_trades', 0)}</td></tr>
                <tr><td class="metric">Win Rate</td><td>{metrics.get('win_rate', 0):.1%}</td></tr>
                <tr><td class="metric">Profit Factor</td><td>{metrics.get('profit_factor', 0):.2f}</td></tr>
                <tr><td class="metric">Total Return</td><td class="{'positive' if metrics.get('total_return', 0) > 0 else 'negative'}">{metrics.get('total_return_pct', 0):.2f}%</td></tr>
                <tr><td class="metric">Max Drawdown</td><td class="negative">{metrics.get('max_drawdown_pct', 0):.2f}%</td></tr>
                <tr><td class="metric">Sharpe Ratio</td><td>{metrics.get('sharpe_ratio', 0):.2f}</td></tr>
            </table>

            <h2>Top 5 Winners</h2>
            {winners.to_html(index=False)}

            <h2>Top 5 Losers</h2>
            {losers.to_html(index=False)}
        </body>
        </html>
        """

        with open(output_path, 'w') as f:
            f.write(html)

        logger.info(f"HTML report saved to {output_path}")
