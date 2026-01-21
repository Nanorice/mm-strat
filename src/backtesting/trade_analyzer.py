"""
Batch trade analysis using VectorBT engine.
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from typing import Optional
from tqdm import tqdm

from .vbt_engine import VectorBTBacktester


class TradeAnalyzer:
    """
    Batch analysis of SEPA trades from d2_rehydrated.

    Orchestrates VectorBTBacktester across multiple trades and aggregates results
    for exploratory analysis.
    """

    def __init__(self, d2_path: str = 'data/ml/d2_rehydrated.parquet'):
        """
        Args:
            d2_path: Path to d2_rehydrated.parquet file
        """
        print(f"Loading {d2_path}...")
        self.d2 = pd.read_parquet(d2_path)

        # Normalize column names to lowercase
        self.d2.columns = [c.lower() for c in self.d2.columns]

        print(f"Loaded {len(self.d2):,} rows, {self.d2['trade_id'].nunique():,} unique trades")

        # Storage for portfolios (for drill-down)
        self._portfolios = {}

        # Results DataFrame
        self.results: Optional[pd.DataFrame] = None

    def analyze_trade(self, trade_id: int) -> dict:
        """
        Analyze a single trade.

        Args:
            trade_id: ID of trade to analyze

        Returns:
            dict with comprehensive metrics including:
            - trade_id, ticker, entry_date, exit_date, days_held
            - label, return_pct, exit_reason (from d2)
            - sharpe, sortino, calmar, max_dd_pct, max_fav_exc_pct
            - peak_date, days_to_peak
        """
        # Extract trade data
        trade_data = self.d2[self.d2['trade_id'] == trade_id].copy()

        if len(trade_data) == 0:
            raise ValueError(f"Trade ID {trade_id} not found")

        # Get metadata from first row
        first_row = trade_data.iloc[0]
        ticker = first_row['ticker']
        label = first_row.get('label', None)
        return_pct = first_row.get('return_pct', None)
        exit_reason = first_row.get('exit_reason', None)

        # Run VectorBT simulation
        backtester = VectorBTBacktester(trade_data)
        backtester.run_simulation(position_size=10000, fees=0.001)

        # Store portfolio for drill-down
        self._portfolios[trade_id] = backtester.portfolio

        # Get metrics
        metrics = backtester.get_metrics()

        # Combine with metadata
        result = {
            'trade_id': trade_id,
            'ticker': ticker,
            'entry_date': metrics['entry_date'],
            'exit_date': metrics['exit_date'],
            'days_held': metrics['days_held'],
            'label': label,
            'return_pct': return_pct,
            'exit_reason': exit_reason,
            'sharpe': metrics['sharpe'],
            'sortino': metrics['sortino'],
            'calmar': metrics['calmar'],
            'max_dd_pct': metrics['max_drawdown_pct'],
            'max_fav_exc_pct': metrics['max_favorable_excursion_pct'],
            'total_return_pct': metrics['total_return_pct'],
            'win_rate': metrics['win_rate'],
            'peak_date': metrics['peak_date'],
            'days_to_peak': metrics['days_to_peak'],
        }

        return result

    def run_batch_analysis(
        self,
        trade_ids: Optional[list[int]] = None,
        sample_size: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Run analysis on multiple trades.

        Args:
            trade_ids: Specific trade IDs to analyze (None = all trades)
            sample_size: If provided, randomly sample N trades instead of all

        Returns:
            DataFrame with one row per trade containing all metrics
        """
        # Determine which trades to analyze
        if trade_ids is not None:
            ids_to_analyze = trade_ids
        elif sample_size is not None:
            all_ids = self.d2['trade_id'].unique()
            ids_to_analyze = np.random.choice(all_ids, size=min(sample_size, len(all_ids)), replace=False)
        else:
            ids_to_analyze = self.d2['trade_id'].unique()

        print(f"Analyzing {len(ids_to_analyze):,} trades...")

        # Analyze each trade
        results = []
        for trade_id in tqdm(ids_to_analyze, desc="Processing trades"):
            try:
                result = self.analyze_trade(trade_id)
                results.append(result)
            except Exception as e:
                print(f"Error analyzing trade {trade_id}: {e}")
                continue

        # Convert to DataFrame
        self.results = pd.DataFrame(results)
        print(f"\nAnalysis complete: {len(self.results):,} trades processed")

        return self.results

    def get_portfolio(self, trade_id: int):
        """
        Retrieve the VectorBT Portfolio object for a specific trade.

        Args:
            trade_id: ID of trade

        Returns:
            vbt.Portfolio object (or None if not found)
        """
        return self._portfolios.get(trade_id, None)

    def generate_report(self, save_plots: bool = False, plot_dir: str = './backtest_results') -> None:
        """
        Generate comprehensive analysis report with statistics and visualizations.

        Args:
            save_plots: If True, save plots to disk instead of displaying
            plot_dir: Directory to save plots (only used if save_plots=True)
        """
        if self.results is None or len(self.results) == 0:
            raise RuntimeError("No results available. Run run_batch_analysis() first.")

        print("\n" + "="*60)
        print("BACKTESTING REPORT")
        print("="*60)

        # Overall statistics
        print("\n--- Overall Statistics ---")
        print(f"Total trades analyzed: {len(self.results):,}")
        print(f"Average return: {self.results['total_return_pct'].mean():.2f}%")
        print(f"Median return: {self.results['total_return_pct'].median():.2f}%")
        print(f"Win rate: {self.results['win_rate'].mean()*100:.1f}%")
        print(f"Average Sharpe: {self.results['sharpe'].mean():.2f}")
        print(f"Average Sortino: {self.results['sortino'].mean():.2f}")
        print(f"Average Max DD: {self.results['max_dd_pct'].mean():.2f}%")
        print(f"Average Max Fav Exc: {self.results['max_fav_exc_pct'].mean():.2f}%")
        print(f"Average days held: {self.results['days_held'].mean():.1f}")
        print(f"Average days to peak: {self.results['days_to_peak'].mean():.1f}")

        # Winners vs Losers
        if 'label' in self.results.columns and self.results['label'].notna().any():
            print("\n--- Winners (label=1) vs Losers (label=0) ---")
            winners = self.results[self.results['label'] == 1]
            losers = self.results[self.results['label'] == 0]

            print(f"\nWinners ({len(winners):,} trades):")
            print(f"  Avg return: {winners['total_return_pct'].mean():.2f}%")
            print(f"  Avg Max DD: {winners['max_dd_pct'].mean():.2f}%")
            print(f"  Avg Max Fav Exc: {winners['max_fav_exc_pct'].mean():.2f}%")
            print(f"  Avg Sharpe: {winners['sharpe'].mean():.2f}")
            print(f"  Avg days to peak: {winners['days_to_peak'].mean():.1f}")

            print(f"\nLosers ({len(losers):,} trades):")
            print(f"  Avg return: {losers['total_return_pct'].mean():.2f}%")
            print(f"  Avg Max DD: {losers['max_dd_pct'].mean():.2f}%")
            print(f"  Avg Max Fav Exc: {losers['max_fav_exc_pct'].mean():.2f}%")
            print(f"  Avg Sharpe: {losers['sharpe'].mean():.2f}")
            print(f"  Avg days to peak: {losers['days_to_peak'].mean():.1f}")

        # Exit reason breakdown
        if 'exit_reason' in self.results.columns and self.results['exit_reason'].notna().any():
            print("\n--- Exit Reason Breakdown ---")
            exit_stats = self.results.groupby('exit_reason').agg({
                'total_return_pct': ['mean', 'median', 'count'],
                'max_dd_pct': 'mean',
                'sharpe': 'mean',
            }).round(2)
            print(exit_stats)

        # Regret Analysis: High MFE but low final return
        self.results['regret'] = self.results['max_fav_exc_pct'] - self.results['total_return_pct']
        high_regret = self.results.nlargest(10, 'regret')
        print("\n--- Top 10 'Regret' Trades (High MFE but exited poorly) ---")
        print(high_regret[['trade_id', 'ticker', 'max_fav_exc_pct', 'total_return_pct', 'regret', 'days_to_peak', 'days_held']])

        # Generate plots
        self._generate_plots(save_plots, plot_dir)

    def _generate_plots(self, save: bool, plot_dir: str) -> None:
        """
        Generate analysis plots.

        Args:
            save: If True, save to disk; otherwise display
            plot_dir: Directory to save plots
        """
        if save:
            import os
            os.makedirs(plot_dir, exist_ok=True)

        # Set style
        sns.set_style("whitegrid")

        # 1. Return distribution (Winners vs Losers)
        fig, axes = plt.subplots(1, 2, figsize=(14, 5))

        if 'label' in self.results.columns:
            winners = self.results[self.results['label'] == 1]
            losers = self.results[self.results['label'] == 0]

            axes[0].hist(winners['total_return_pct'], bins=50, alpha=0.6, label='Winners', color='green')
            axes[0].hist(losers['total_return_pct'], bins=50, alpha=0.6, label='Losers', color='red')
            axes[0].set_xlabel('Total Return (%)')
            axes[0].set_ylabel('Frequency')
            axes[0].set_title('Return Distribution: Winners vs Losers')
            axes[0].legend()
            axes[0].axvline(0, color='black', linestyle='--', linewidth=1)

        # 2. Max Drawdown distribution
        axes[1].hist(self.results['max_dd_pct'], bins=50, alpha=0.7, color='orange')
        axes[1].set_xlabel('Max Drawdown (%)')
        axes[1].set_ylabel('Frequency')
        axes[1].set_title('Max Drawdown Distribution')
        axes[1].axvline(self.results['max_dd_pct'].median(), color='red', linestyle='--', label='Median')
        axes[1].legend()

        plt.tight_layout()
        if save:
            plt.savefig(f"{plot_dir}/return_and_dd_distribution.png", dpi=300, bbox_inches='tight')
            print(f"Saved: {plot_dir}/return_and_dd_distribution.png")
        else:
            plt.show()

        # 3. Return vs Max DD scatter
        fig, ax = plt.subplots(figsize=(10, 6))
        scatter = ax.scatter(
            self.results['max_dd_pct'],
            self.results['total_return_pct'],
            c=self.results['label'] if 'label' in self.results.columns else 'blue',
            cmap='RdYlGn',
            alpha=0.5,
            s=20
        )
        ax.set_xlabel('Max Drawdown (%)')
        ax.set_ylabel('Total Return (%)')
        ax.set_title('Return vs Max Drawdown')
        ax.axhline(0, color='black', linestyle='--', linewidth=1)
        ax.axvline(0, color='black', linestyle='--', linewidth=1)
        if 'label' in self.results.columns:
            plt.colorbar(scatter, label='Label (0=Loser, 1=Winner)')

        plt.tight_layout()
        if save:
            plt.savefig(f"{plot_dir}/return_vs_dd_scatter.png", dpi=300, bbox_inches='tight')
            print(f"Saved: {plot_dir}/return_vs_dd_scatter.png")
        else:
            plt.show()

        # 4. Days to peak analysis
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.hist(self.results['days_to_peak'].dropna(), bins=50, alpha=0.7, color='purple')
        ax.set_xlabel('Days to Peak')
        ax.set_ylabel('Frequency')
        ax.set_title('Distribution of Days to Peak')
        ax.axvline(self.results['days_to_peak'].median(), color='red', linestyle='--', label='Median')
        ax.legend()

        plt.tight_layout()
        if save:
            plt.savefig(f"{plot_dir}/days_to_peak_distribution.png", dpi=300, bbox_inches='tight')
            print(f"Saved: {plot_dir}/days_to_peak_distribution.png")
        else:
            plt.show()

        # 5. Days held vs Return
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.scatter(
            self.results['days_held'],
            self.results['total_return_pct'],
            c=self.results['label'] if 'label' in self.results.columns else 'blue',
            cmap='RdYlGn',
            alpha=0.5,
            s=20
        )
        ax.set_xlabel('Days Held')
        ax.set_ylabel('Total Return (%)')
        ax.set_title('Holding Period vs Return')
        ax.axhline(0, color='black', linestyle='--', linewidth=1)

        plt.tight_layout()
        if save:
            plt.savefig(f"{plot_dir}/holding_period_vs_return.png", dpi=300, bbox_inches='tight')
            print(f"Saved: {plot_dir}/holding_period_vs_return.png")
        else:
            plt.show()

        print(f"\nPlot generation complete!")


if __name__ == '__main__':
    """
    Demo: Batch analysis of trades.
    """
    print("=== TradeAnalyzer Demo ===\n")

    # Initialize analyzer
    analyzer = TradeAnalyzer(d2_path='data/ml/d2_rehydrated.parquet')

    # Run batch analysis on a sample
    print("\nRunning batch analysis on 100 random trades...")
    results = analyzer.run_batch_analysis(sample_size=100)

    # Display sample results
    print("\n--- Sample Results ---")
    print(results.head(10))

    # Generate report
    print("\nGenerating report...")
    analyzer.generate_report(save_plots=False)

    # Example: Drill down into specific trade
    print("\n--- Example: Drill down into first trade ---")
    first_trade_id = results['trade_id'].iloc[0]
    portfolio = analyzer.get_portfolio(first_trade_id)
    if portfolio:
        print(f"Portfolio for trade {first_trade_id}:")
        print(f"  Total return: {portfolio.total_return()*100:.2f}%")
        print(f"  Final value: ${portfolio.final_value():.2f}")

    # Save results to CSV
    output_path = 'backtest_results.csv'
    results.to_csv(output_path, index=False)
    print(f"\nResults saved to {output_path}")
