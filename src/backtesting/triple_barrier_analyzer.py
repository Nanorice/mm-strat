"""
Triple Barrier Trade Analyzer

Extends TradeAnalyzer to use triple barrier exit points from D3 instead of SEPA exits.
Uses D2 trajectory data but exits based on D3's barrier outcomes.
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from typing import Optional
from tqdm import tqdm

from .vbt_engine import VectorBTBacktester


class TripleBarrierAnalyzer:
    """
    Backtesting analyzer using triple barrier exit logic.
    
    Combines:
    - D2 trajectory data (full price paths)
    - D3 labels (when to exit based on barrier touched)
    
    This simulates what would happen if we followed the barrier-based exits.
    """

    def __init__(
        self, 
        d2_path: str = 'data/ml/d2_fixed_horizon_90d.parquet',
        d3_path: str = 'data/ml/d3_triple_barrier_labels.parquet'
    ):
        """
        Args:
            d2_path: Path to rehydrated D2 with full trajectories
            d3_path: Path to D3 with triple barrier labels and exit info
        """
        print(f"Loading trajectory data: {d2_path}...")
        self.d2 = pd.read_parquet(d2_path)
        self.d2.columns = [c.lower() for c in self.d2.columns]
        
        print(f"Loading barrier labels: {d3_path}...")
        self.d3 = pd.read_parquet(d3_path)
        self.d3.columns = [c.lower() for c in self.d3.columns]
        
        print(f"D2: {len(self.d2):,} rows, {self.d2['trade_id'].nunique():,} trades")
        print(f"D3: {len(self.d3):,} trades with barrier outcomes")
        
        # Validate overlap
        d2_trades = set(self.d2['trade_id'].unique())
        d3_trades = set(self.d3['trade_id'].unique())
        self.valid_trades = d2_trades & d3_trades
        print(f"Valid trades (in both D2 & D3): {len(self.valid_trades):,}")
        
        # Storage for portfolios (for drill-down)
        self._portfolios = {}
        
        # Results DataFrame
        self.results: Optional[pd.DataFrame] = None

    def analyze_trade(self, trade_id: int) -> dict:
        """
        Analyze a single trade using triple barrier exit.
        
        Args:
            trade_id: ID of trade to analyze
            
        Returns:
            dict with comprehensive metrics including barrier outcome info
        """
        # Get D3 info for this trade (when to exit, why)
        d3_row = self.d3[self.d3['trade_id'] == trade_id]
        if len(d3_row) == 0:
            raise ValueError(f"Trade ID {trade_id} not found in D3")
        d3_row = d3_row.iloc[0]
        
        # Get D2 trajectory for this trade
        trade_data = self.d2[self.d2['trade_id'] == trade_id].copy()
        if len(trade_data) == 0:
            raise ValueError(f"Trade ID {trade_id} not found in D2")
        
        trade_data = trade_data.sort_values('date').reset_index(drop=True)
        
        # Truncate trajectory to barrier exit day
        days_to_outcome = int(d3_row['days_to_outcome'])
        # Ensure we have enough data (add 1 because day 0 = entry)
        exit_idx = min(days_to_outcome + 1, len(trade_data))
        trade_data_truncated = trade_data.iloc[:exit_idx].copy()
        
        if len(trade_data_truncated) < 2:
            # Need at least entry + 1 day for meaningful analysis
            return None
        
        # Get metadata
        first_row = trade_data_truncated.iloc[0]
        ticker = first_row['ticker']
        
        # Run VectorBT simulation on truncated trajectory
        try:
            backtester = VectorBTBacktester(trade_data_truncated)
            backtester.run_simulation(position_size=10000, fees=0.001)
            
            # Store portfolio for drill-down
            self._portfolios[trade_id] = backtester.portfolio
            
            # Get metrics
            metrics = backtester.get_metrics()
        except Exception as e:
            # If VBT fails, calculate basic metrics manually
            entry_price = trade_data_truncated.iloc[0]['close']
            exit_price = trade_data_truncated.iloc[-1]['close']
            total_return = (exit_price - entry_price) / entry_price * 100
            
            metrics = {
                'entry_date': trade_data_truncated.iloc[0]['date'],
                'exit_date': trade_data_truncated.iloc[-1]['date'],
                'days_held': len(trade_data_truncated) - 1,
                'sharpe': np.nan,
                'sortino': np.nan,
                'calmar': np.nan,
                'max_drawdown_pct': np.nan,
                'max_favorable_excursion_pct': np.nan,
                'total_return_pct': total_return,
                'win_rate': 1 if total_return > 0 else 0,
                'peak_date': None,
                'days_to_peak': np.nan,
            }
        
        # Combine with D3 barrier info
        result = {
            'trade_id': trade_id,
            'ticker': ticker,
            'entry_date': metrics.get('entry_date'),
            'exit_date': metrics.get('exit_date'),
            'days_held': metrics.get('days_held'),
            # Triple barrier info
            'y_meta': d3_row['y_meta'],
            'barrier_outcome': d3_row['barrier_outcome'],
            'days_to_outcome': d3_row['days_to_outcome'],
            'return_at_outcome': d3_row['return_at_outcome'] * 100,  # Convert to %
            # VBT metrics
            'sharpe': metrics.get('sharpe'),
            'sortino': metrics.get('sortino'),
            'calmar': metrics.get('calmar'),
            'max_dd_pct': metrics.get('max_drawdown_pct'),
            'max_fav_exc_pct': metrics.get('max_favorable_excursion_pct'),
            'total_return_pct': metrics.get('total_return_pct'),
            'win_rate': metrics.get('win_rate'),
            'peak_date': metrics.get('peak_date'),
            'days_to_peak': metrics.get('days_to_peak'),
        }
        
        # Add hybrid barrier details if available
        if 'barrier_stop_pct' in d3_row.index:
            result['barrier_stop_pct'] = d3_row['barrier_stop_pct'] * 100
            result['barrier_target_pct'] = d3_row['barrier_target_pct'] * 100
            result['barrier_time_days'] = d3_row['barrier_time_days']
        
        return result

    def run_batch_analysis(
        self,
        trade_ids: Optional[list[int]] = None,
        sample_size: Optional[int] = None,
        by_outcome: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Run analysis on multiple trades.
        
        Args:
            trade_ids: Specific trade IDs to analyze (None = all valid trades)
            sample_size: If provided, randomly sample N trades
            by_outcome: Filter by barrier outcome ('TP', 'SL', 'Time')
            
        Returns:
            DataFrame with one row per trade containing all metrics
        """
        # Determine which trades to analyze
        if trade_ids is not None:
            ids_to_analyze = [t for t in trade_ids if t in self.valid_trades]
        else:
            ids_to_analyze = list(self.valid_trades)
        
        # Filter by outcome if specified
        if by_outcome:
            outcome_trades = set(self.d3[self.d3['barrier_outcome'] == by_outcome]['trade_id'])
            ids_to_analyze = [t for t in ids_to_analyze if t in outcome_trades]
            print(f"Filtering to {by_outcome} outcomes: {len(ids_to_analyze):,} trades")
        
        # Sample if requested
        if sample_size is not None:
            ids_to_analyze = np.random.choice(
                ids_to_analyze, 
                size=min(sample_size, len(ids_to_analyze)), 
                replace=False
            ).tolist()
        
        print(f"Analyzing {len(ids_to_analyze):,} trades...")
        
        # Analyze each trade
        results = []
        for trade_id in tqdm(ids_to_analyze, desc="Processing trades"):
            try:
                result = self.analyze_trade(trade_id)
                if result is not None:
                    results.append(result)
            except Exception as e:
                # Skip errors silently
                continue
        
        # Convert to DataFrame
        self.results = pd.DataFrame(results)
        print(f"\nAnalysis complete: {len(self.results):,} trades processed")
        
        return self.results

    def get_portfolio(self, trade_id: int):
        """Retrieve the VectorBT Portfolio object for a specific trade."""
        return self._portfolios.get(trade_id, None)

    def generate_report(self, save_plots: bool = False, plot_dir: str = './backtest_results') -> None:
        """
        Generate comprehensive analysis report with statistics and visualizations.
        """
        if self.results is None or len(self.results) == 0:
            raise RuntimeError("No results available. Run run_batch_analysis() first.")
        
        print("\n" + "="*70)
        print("TRIPLE BARRIER BACKTESTING REPORT")
        print("="*70)
        
        # Overall statistics
        print("\n--- Overall Statistics ---")
        print(f"Total trades analyzed: {len(self.results):,}")
        print(f"Average return: {self.results['total_return_pct'].mean():.2f}%")
        print(f"Median return: {self.results['total_return_pct'].median():.2f}%")
        print(f"Average days held: {self.results['days_held'].mean():.1f}")
        
        if 'sharpe' in self.results.columns:
            valid_sharpe = self.results['sharpe'].dropna()
            if len(valid_sharpe) > 0:
                print(f"Average Sharpe: {valid_sharpe.mean():.2f}")
        
        if 'max_dd_pct' in self.results.columns:
            valid_dd = self.results['max_dd_pct'].dropna()
            if len(valid_dd) > 0:
                print(f"Average Max DD: {valid_dd.mean():.2f}%")
        
        # Barrier outcome breakdown
        print("\n--- Barrier Outcome Breakdown ---")
        outcome_stats = self.results.groupby('barrier_outcome').agg({
            'total_return_pct': ['mean', 'median', 'std', 'count'],
            'days_held': 'mean',
        }).round(2)
        print(outcome_stats)
        
        # Win rate by outcome
        print("\n--- Expectancy by Outcome ---")
        for outcome in ['TP', 'SL', 'Time']:
            subset = self.results[self.results['barrier_outcome'] == outcome]
            if len(subset) > 0:
                avg_ret = subset['total_return_pct'].mean()
                count = len(subset)
                pct = count / len(self.results) * 100
                print(f"  {outcome}: {count:,} trades ({pct:.1f}%), Avg Return: {avg_ret:+.2f}%")
        
        # Expectancy calculation
        total_expectancy = self.results['total_return_pct'].mean()
        print(f"\n  Overall Expectancy: {total_expectancy:+.2f}% per trade")
        
        # y_meta performance (model's target variable)
        print("\n--- y_meta (Model Target) Performance ---")
        tp_trades = self.results[self.results['y_meta'] == 1]
        other_trades = self.results[self.results['y_meta'] == 0]
        
        print(f"y_meta=1 (TP): {len(tp_trades):,} trades, Avg Return: {tp_trades['total_return_pct'].mean():.2f}%")
        print(f"y_meta=0 (SL/Time): {len(other_trades):,} trades, Avg Return: {other_trades['total_return_pct'].mean():.2f}%")
        
        # Hybrid barrier stats if available
        if 'barrier_target_pct' in self.results.columns:
            print("\n--- Hybrid Barrier Levels Used ---")
            print(f"  Avg Stop Loss: -{self.results['barrier_stop_pct'].mean():.2f}%")
            print(f"  Avg Target: +{self.results['barrier_target_pct'].mean():.2f}%")
            print(f"  Avg Time Barrier: {self.results['barrier_time_days'].mean():.1f} days")
        
        # Generate plots
        self._generate_plots(save_plots, plot_dir)

    def _generate_plots(self, save: bool, plot_dir: str) -> None:
        """Generate analysis plots."""
        if save:
            import os
            os.makedirs(plot_dir, exist_ok=True)
        
        sns.set_style("whitegrid")
        
        # 1. Return distribution by barrier outcome
        fig, axes = plt.subplots(1, 2, figsize=(14, 5))
        
        colors = {'TP': 'green', 'SL': 'red', 'Time': 'orange'}
        for outcome in ['TP', 'SL', 'Time']:
            subset = self.results[self.results['barrier_outcome'] == outcome]
            if len(subset) > 0:
                axes[0].hist(subset['total_return_pct'], bins=30, alpha=0.5, 
                           label=f'{outcome} ({len(subset)})', color=colors[outcome])
        
        axes[0].set_xlabel('Total Return (%)')
        axes[0].set_ylabel('Frequency')
        axes[0].set_title('Return Distribution by Barrier Outcome')
        axes[0].legend()
        axes[0].axvline(0, color='black', linestyle='--', linewidth=1)
        
        # 2. Days to outcome distribution
        if 'days_to_outcome' in self.results.columns:
            axes[1].hist(self.results['days_to_outcome'], bins=30, alpha=0.7, color='purple')
            axes[1].set_xlabel('Days to Exit')
            axes[1].set_ylabel('Frequency')
            axes[1].set_title('Holding Period Distribution (Barrier Exit)')
            axes[1].axvline(self.results['days_to_outcome'].median(), color='red', 
                          linestyle='--', label='Median')
            axes[1].legend()
        
        plt.tight_layout()
        if save:
            plt.savefig(f"{plot_dir}/triple_barrier_distributions.png", dpi=300, bbox_inches='tight')
            print(f"Saved: {plot_dir}/triple_barrier_distributions.png")
        else:
            plt.show()
        
        # 3. Return vs Days Held by outcome
        fig, ax = plt.subplots(figsize=(10, 6))
        for outcome in ['TP', 'SL', 'Time']:
            subset = self.results[self.results['barrier_outcome'] == outcome]
            if len(subset) > 0:
                ax.scatter(subset['days_held'], subset['total_return_pct'],
                          alpha=0.5, s=20, label=outcome, color=colors[outcome])
        
        ax.set_xlabel('Days Held')
        ax.set_ylabel('Total Return (%)')
        ax.set_title('Return vs Holding Period by Barrier Outcome')
        ax.axhline(0, color='black', linestyle='--', linewidth=1)
        ax.legend()
        
        plt.tight_layout()
        if save:
            plt.savefig(f"{plot_dir}/return_vs_days_by_outcome.png", dpi=300, bbox_inches='tight')
            print(f"Saved: {plot_dir}/return_vs_days_by_outcome.png")
        else:
            plt.show()
        
        print("\nPlot generation complete!")

    def compare_to_sepa_exits(self, sepa_d2_path: str = 'data/ml/d2_rehydrated.parquet') -> pd.DataFrame:
        """
        Compare triple barrier exits to original SEPA exits.
        
        Returns comparison DataFrame showing which exit strategy performed better.
        """
        print(f"Loading SEPA exits from {sepa_d2_path}...")
        sepa_d2 = pd.read_parquet(sepa_d2_path)
        sepa_d2.columns = [c.lower() for c in sepa_d2.columns]
        
        # Get SEPA exit returns (last row per trade)
        sepa_exits = sepa_d2.groupby('trade_id').agg({
            'close': ['first', 'last'],
            'date': ['first', 'last']
        })
        sepa_exits.columns = ['entry_price', 'exit_price', 'entry_date', 'exit_date']
        sepa_exits['sepa_return'] = (sepa_exits['exit_price'] - sepa_exits['entry_price']) / sepa_exits['entry_price'] * 100
        sepa_exits['sepa_days'] = (pd.to_datetime(sepa_exits['exit_date']) - pd.to_datetime(sepa_exits['entry_date'])).dt.days
        
        # Merge with our barrier results
        if self.results is None:
            raise RuntimeError("Run run_batch_analysis() first")
        
        comparison = self.results.merge(
            sepa_exits[['sepa_return', 'sepa_days']], 
            left_on='trade_id', 
            right_index=True,
            how='left'
        )
        
        comparison['barrier_better'] = comparison['total_return_pct'] > comparison['sepa_return']
        comparison['return_diff'] = comparison['total_return_pct'] - comparison['sepa_return']
        
        print("\n--- Triple Barrier vs SEPA Exit Comparison ---")
        print(f"Trades where barrier exit was better: {comparison['barrier_better'].sum():,} ({comparison['barrier_better'].mean()*100:.1f}%)")
        print(f"Avg return diff (barrier - SEPA): {comparison['return_diff'].mean():.2f}%")
        print(f"Avg barrier days: {comparison['days_held'].mean():.1f} vs SEPA days: {comparison['sepa_days'].mean():.1f}")
        
        return comparison


if __name__ == '__main__':
    """Demo: Triple barrier backtesting."""
    print("=== Triple Barrier Analyzer Demo ===\n")
    
    analyzer = TripleBarrierAnalyzer(
        d2_path='data/ml/d2_fixed_horizon_90d.parquet',
        d3_path='data/ml/d3_triple_barrier_labels.parquet'
    )
    
    # Run batch analysis on a sample
    print("\nRunning batch analysis on 500 random trades...")
    results = analyzer.run_batch_analysis(sample_size=500)
    
    # Generate report
    print("\nGenerating report...")
    analyzer.generate_report(save_plots=True, plot_dir='./backtest_results_barrier')
    
    # Compare to SEPA exits
    print("\nComparing to SEPA exits...")
    comparison = analyzer.compare_to_sepa_exits()
    
    # Save results
    output_path = 'backtest_results_barrier.csv'
    results.to_csv(output_path, index=False)
    print(f"\nResults saved to {output_path}")
