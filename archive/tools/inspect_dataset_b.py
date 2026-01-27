"""
Inspect Dataset B - ML Training Data Explorer
Analyze and explore labeled trade data for meta-labeling model training.
"""

import pandas as pd
import argparse
import sys
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.append(str(Path(__file__).parent))


def load_dataset_b(file_path: str) -> pd.DataFrame:
    """Load Dataset B from Parquet or CSV."""
    path = Path(file_path)
    
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {file_path}")
    
    if path.suffix == '.parquet':
        df = pd.read_parquet(file_path)
    elif path.suffix == '.csv':
        df = pd.read_csv(file_path)
    else:
        raise ValueError(f"Unsupported file format: {path.suffix}")
    
    # Convert date columns to datetime
    date_cols = ['entry_date', 'exit_date', 'simulation_start', 'simulation_end']
    for col in date_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col])
    
    return df


def print_overview(df: pd.DataFrame):
    """Print dataset overview."""
    print("\n" + "=" * 80)
    print(" DATASET B OVERVIEW")
    print("=" * 80)
    
    print(f"\n📊 Dataset Size:")
    print(f"   Total Trades: {len(df)}")
    print(f"   Date Range: {df['entry_date'].min().date()} to {df['exit_date'].max().date()}")
    print(f"   Unique Tickers: {df['ticker'].nunique()}")
    
    if 'simulation_start' in df.columns and 'simulation_end' in df.columns:
        sim_start = df['simulation_start'].iloc[0]
        sim_end = df['simulation_end'].iloc[0]
        print(f"   Simulation Period: {sim_start.date()} to {sim_end.date()}")
    
    if 'success_threshold_pct' in df.columns:
        threshold = df['success_threshold_pct'].iloc[0]
        print(f"   Success Threshold: {threshold}%")


def print_label_distribution(df: pd.DataFrame):
    """Print label distribution analysis."""
    print("\n" + "=" * 80)
    print(" LABEL DISTRIBUTION")
    print("=" * 80)
    
    label_counts = df['label'].value_counts().sort_index()
    total = len(df)
    
    print(f"\n🏷️  Labels:")
    for label, count in label_counts.items():
        label_name = "Success" if label == 1 else "Failure"
        pct = (count / total) * 100
        print(f"   {label_name} ({label}): {count:4d} trades ({pct:5.1f}%)")
    
    # Class imbalance ratio
    if 0 in label_counts and 1 in label_counts:
        imbalance_ratio = label_counts[0] / label_counts[1]
        print(f"\n   Class Imbalance Ratio: {imbalance_ratio:.2f}:1 (Failure:Success)")


def print_return_statistics(df: pd.DataFrame):
    """Print return distribution statistics."""
    print("\n" + "=" * 80)
    print(" RETURN STATISTICS")
    print("=" * 80)
    
    # Overall statistics
    print(f"\n💰 All Trades:")
    print(f"   Mean Return: {df['return_pct'].mean():7.2f}%")
    print(f"   Median Return: {df['return_pct'].median():7.2f}%")
    print(f"   Std Dev: {df['return_pct'].std():7.2f}%")
    print(f"   Min Return: {df['return_pct'].min():7.2f}%")
    print(f"   Max Return: {df['return_pct'].max():7.2f}%")
    
    # Winners
    winners = df[df['label'] == 1]
    if not winners.empty:
        print(f"\n✅ Winning Trades (Label=1):")
        print(f"   Count: {len(winners)}")
        print(f"   Mean Return: {winners['return_pct'].mean():7.2f}%")
        print(f"   Median Return: {winners['return_pct'].median():7.2f}%")
        print(f"   Min Return: {winners['return_pct'].min():7.2f}%")
        print(f"   Max Return: {winners['return_pct'].max():7.2f}%")
    
    # Losers
    losers = df[df['label'] == 0]
    if not losers.empty:
        print(f"\n❌ Losing Trades (Label=0):")
        print(f"   Count: {len(losers)}")
        print(f"   Mean Return: {losers['return_pct'].mean():7.2f}%")
        print(f"   Median Return: {losers['return_pct'].median():7.2f}%")
        print(f"   Min Return: {losers['return_pct'].min():7.2f}%")
        print(f"   Max Return: {losers['return_pct'].max():7.2f}%")


def print_duration_analysis(df: pd.DataFrame):
    """Print trade duration analysis."""
    print("\n" + "=" * 80)
    print(" DURATION ANALYSIS")
    print("=" * 80)
    
    print(f"\n⏱️  Days Held:")
    print(f"   Mean: {df['days_held'].mean():.1f} days")
    print(f"   Median: {df['days_held'].median():.1f} days")
    print(f"   Min: {df['days_held'].min()} days")
    print(f"   Max: {df['days_held'].max()} days")
    
    # Duration by label
    for label in sorted(df['label'].unique()):
        label_name = "Success" if label == 1 else "Failure"
        subset = df[df['label'] == label]
        print(f"   {label_name} (Label={label}): {subset['days_held'].mean():.1f} days avg")


def print_exit_reasons(df: pd.DataFrame):
    """Print exit reason breakdown."""
    print("\n" + "=" * 80)
    print(" EXIT REASONS")
    print("=" * 80)
    
    exit_counts = df['exit_reason'].value_counts()
    total = len(df)
    
    print(f"\n🚪 Exit Breakdown:")
    for reason, count in exit_counts.items():
        pct = (count / total) * 100
        print(f"   {reason}: {count:4d} trades ({pct:5.1f}%)")


def print_enhanced_metrics(df: pd.DataFrame):
    """Print enhanced performance metrics analysis."""
    # Check if enhanced metrics exist
    enhanced_cols = ['max_drawdown_pct', 'max_favorable_excursion_pct', 'r_multiple', 'sharpe_ratio', 'initial_risk_pct']
    has_enhanced = any(col in df.columns for col in enhanced_cols)
    
    if not has_enhanced:
        return  # Skip if no enhanced metrics
    
    print("\n" + "=" * 80)
    print(" ENHANCED METRICS")
    print("=" * 80)
    
    # Filter to trades with non-null metrics
    df_with_metrics = df.dropna(subset=[col for col in enhanced_cols if col in df.columns], how='all')
    
    if df_with_metrics.empty:
        print("\n⚠️  No enhanced metrics calculated (all None)")
        return
    
    print(f"\n📈 Trades with Enhanced Metrics: {len(df_with_metrics)} / {len(df)}")
    
    # Max Drawdown Analysis
    if 'max_drawdown_pct' in df.columns:
        mdd = df_with_metrics['max_drawdown_pct'].dropna()
        if not mdd.empty:
            print(f"\n💧 Max Drawdown (worst intra-trade loss):")
            print(f"   Mean: {mdd.mean():.2f}%")
            print(f"   Median: {mdd.median():.2f}%")
            print(f"   Worst: {mdd.min():.2f}%")
            print(f"   Best (smallest drawdown): {mdd.max():.2f}%")
    
    # Max Favorable Excursion Analysis
    if 'max_favorable_excursion_pct' in df.columns:
        mfe = df_with_metrics['max_favorable_excursion_pct'].dropna()
        if not mfe.empty:
            print(f"\n🚀 Max Favorable Excursion (best intra-trade gain):")
            print(f"   Mean: {mfe.mean():.2f}%")
            print(f"   Median: {mfe.median():.2f}%")
            print(f"   Best: {mfe.max():.2f}%")
            print(f"   Worst: {mfe.min():.2f}%")
    
    # R-Multiple Analysis
    if 'r_multiple' in df.columns:
        r_mult = df_with_metrics['r_multiple'].dropna()
        if not r_mult.empty:
            print(f"\n📊 R-Multiple (risk-adjusted return):")
            print(f"   Mean: {r_mult.mean():.2f}R")
            print(f"   Median: {r_mult.median():.2f}R")
            print(f"   Best: {r_mult.max():.2f}R")
            print(f"   Worst: {r_mult.min():.2f}R")
            # Count positive R-multiples
            positive_r = (r_mult > 0).sum()
            print(f"   Positive R: {positive_r} / {len(r_mult)} ({positive_r/len(r_mult)*100:.1f}%)")
    
    # Sharpe Ratio Analysis
    if 'sharpe_ratio' in df.columns:
        sharpe = df_with_metrics['sharpe_ratio'].dropna()
        if not sharpe.empty:
            print(f"\n📉 Sharpe Ratio (annualized risk-adjusted return):")
            print(f"   Mean: {sharpe.mean():.2f}")
            print(f"   Median: {sharpe.median():.2f}")
            print(f"   Best: {sharpe.max():.2f}")
            print(f"   Worst: {sharpe.min():.2f}")
    
    # Initial Risk Analysis
    if 'initial_risk_pct' in df.columns:
        risk = df_with_metrics['initial_risk_pct'].dropna()
        if not risk.empty:
            print(f"\n🎯 Initial Risk (2.5x ATR stop distance):")
            print(f"   Mean: {risk.mean():.2f}%")
            print(f"   Median: {risk.median():.2f}%")
            print(f"   Min: {risk.min():.2f}%")
            print(f"   Max: {risk.max():.2f}%")



def print_top_performers(df: pd.DataFrame, n: int = 10):
    """Print best and worst trades."""
    print("\n" + "=" * 80)
    print(f" TOP {n} PERFORMERS")
    print("=" * 80)
    
    # Best trades
    print(f"\n🏆 Best {n} Trades:")
    best = df.nlargest(n, 'return_pct')[['ticker', 'entry_date', 'exit_date', 'return_pct', 'days_held', 'label']]
    best['entry_date'] = best['entry_date'].dt.date
    best['exit_date'] = best['exit_date'].dt.date
    print(best.to_string(index=False))
    
    # Worst trades
    print(f"\n💥 Worst {n} Trades:")
    worst = df.nsmallest(n, 'return_pct')[['ticker', 'entry_date', 'exit_date', 'return_pct', 'days_held', 'label']]
    worst['entry_date'] = worst['entry_date'].dt.date
    worst['exit_date'] = worst['exit_date'].dt.date
    print(worst.to_string(index=False))


def print_ticker_analysis(df: pd.DataFrame, n: int = 10):
    """Print analysis by ticker."""
    print("\n" + "=" * 80)
    print(" TICKER ANALYSIS")
    print("=" * 80)
    
    ticker_stats = df.groupby('ticker').agg({
        'trade_id': 'count',
        'return_pct': ['mean', 'sum'],
        'label': 'sum'
    }).round(2)
    
    ticker_stats.columns = ['trades', 'avg_return', 'total_return', 'wins']
    ticker_stats['win_rate'] = (ticker_stats['wins'] / ticker_stats['trades'] * 100).round(1)
    ticker_stats = ticker_stats.sort_values('trades', ascending=False)
    
    print(f"\n📈 Top {n} Most Traded Tickers:")
    print(ticker_stats.head(n).to_string())


def print_sample_trades(df: pd.DataFrame, n: int = 5):
    """Print sample trades."""
    print("\n" + "=" * 80)
    print(f" SAMPLE TRADES (Random {n})")
    print("=" * 80)
    
    sample = df.sample(min(n, len(df)))
    
    cols_to_show = ['ticker', 'entry_date', 'exit_date', 'entry_price', 'exit_price', 
                    'return_pct', 'days_held', 'exit_reason', 'label']
    
    display_df = sample[cols_to_show].copy()
    display_df['entry_date'] = display_df['entry_date'].dt.date
    display_df['exit_date'] = display_df['exit_date'].dt.date
    
    print("\n" + display_df.to_string(index=False))


def inspect_interactive(df: pd.DataFrame):
    """Interactive inspection mode."""
    print("\n" + "=" * 80)
    print(" INTERACTIVE MODE")
    print("=" * 80)
    print("\nAvailable commands:")
    print("  filter <column> <value>  - Filter dataset")
    print("  sort <column>            - Sort by column")
    print("  head <n>                 - Show first n rows")
    print("  tail <n>                 - Show last n rows")
    print("  describe                 - Show statistics")
    print("  columns                  - List all columns")
    print("  quit                     - Exit interactive mode")
    
    current_df = df.copy()
    
    while True:
        try:
            cmd = input("\n> ").strip().split()
            if not cmd:
                continue
            
            action = cmd[0].lower()
            
            if action == 'quit':
                break
            elif action == 'columns':
                print("\nColumns:", ', '.join(current_df.columns))
            elif action == 'describe':
                print("\n", current_df.describe())
            elif action == 'head':
                n = int(cmd[1]) if len(cmd) > 1 else 10
                print("\n", current_df.head(n).to_string())
            elif action == 'tail':
                n = int(cmd[1]) if len(cmd) > 1 else 10
                print("\n", current_df.tail(n).to_string())
            elif action == 'filter' and len(cmd) >= 3:
                col, val = cmd[1], cmd[2]
                if col in current_df.columns:
                    current_df = current_df[current_df[col] == val]
                    print(f"\nFiltered to {len(current_df)} rows")
                else:
                    print(f"\nColumn '{col}' not found")
            elif action == 'sort' and len(cmd) >= 2:
                col = cmd[1]
                if col in current_df.columns:
                    current_df = current_df.sort_values(col)
                    print(f"\nSorted by '{col}'")
                else:
                    print(f"\nColumn '{col}' not found")
            else:
                print("\nUnknown command")
        except Exception as e:
            print(f"\nError: {e}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Inspect Dataset B for ML meta-labeling training"
    )
    
    parser.add_argument(
        'file',
        type=str,
        help='Path to Dataset B file (Parquet or CSV)'
    )
    
    parser.add_argument(
        '--top',
        type=int,
        default=10,
        help='Number of top/bottom items to show (default: 10)'
    )
    
    parser.add_argument(
        '--sample',
        type=int,
        default=5,
        help='Number of sample trades to show (default: 5)'
    )
    
    parser.add_argument(
        '--interactive',
        action='store_true',
        help='Enter interactive inspection mode'
    )
    
    parser.add_argument(
        '--export-summary',
        type=str,
        help='Export summary statistics to CSV'
    )
    
    args = parser.parse_args()
    
    # Load dataset
    print(f"\n📂 Loading Dataset B from: {args.file}")
    df = load_dataset_b(args.file)
    print(f"   ✅ Loaded {len(df)} trades")
    
    # Print all analyses
    print_overview(df)
    print_label_distribution(df)
    print_return_statistics(df)
    print_duration_analysis(df)
    print_exit_reasons(df)
    print_enhanced_metrics(df)  # NEW: Show enhanced metrics
    print_top_performers(df, n=args.top)
    print_ticker_analysis(df, n=args.top)
    print_sample_trades(df, n=args.sample)
    
    # Export summary if requested
    if args.export_summary:
        summary = df.describe()
        summary.to_csv(args.export_summary)
        print(f"\n   ✅ Summary exported to: {args.export_summary}")
    
    # Interactive mode
    if args.interactive:
        inspect_interactive(df)
    
    print("\n" + "=" * 80)
    print("✅ Inspection complete!")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Inspection interrupted by user.")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        sys.exit(1)
