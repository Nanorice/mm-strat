"""
Example: Using scan_universe_for_date method
Demonstrates how to scan for Active Buy Signals on a specific historical date.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

import pandas as pd
from datetime import datetime
from src.data_engine import DataRepository
from src.features import FeatureEngineer
from src.strategy import SEPAStrategy

def example_scan_for_date():
    """
    Example: Scan S&P 500 for buy signals on a specific date.
    """
    print("=" * 80)
    print("EXAMPLE: Scanning for Active Buy Signals on a Specific Date")
    print("=" * 80)
    
    # Initialize components
    print("\n[1/4] Initializing components...")
    repo = DataRepository()
    spy = repo.get_benchmark_data()
    feature_engine = FeatureEngineer(benchmark_data=spy)
    strategy = SEPAStrategy(benchmark_data=spy)
    
    # Define cutoff date
    cutoff_date = pd.Timestamp('2024-11-15')  # Change this to any date you want to analyze
    print(f"\n[2/4] Cutoff date: {cutoff_date.strftime('%Y-%m-%d')}")
    
    # Get universe (or use a subset for testing)
    print("\n[3/4] Loading ticker data...")
    # For demo, using a small subset. For full scan, use: tickers = repo.update_universe()
    test_tickers = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'AMD', 
                    'PLTR', 'SMCI', 'NFLX', 'CRM', 'AVGO', 'ORCL', 'ADBE']
    
    # Load data for each ticker
    ticker_data = {}
    for ticker in test_tickers:
        df = repo.get_ticker_data(ticker, use_cache=True)
        if df is not None:
            ticker_data[ticker] = df
    
    print(f"       Loaded data for {len(ticker_data)} tickers")
    
    # Scan for Active Buy Signals
    print(f"\n[4/4] Scanning for buy signals on {cutoff_date.strftime('%Y-%m-%d')}...")
    buy_signals = strategy.scan_universe_for_date(
        ticker_data_dict=ticker_data,
        cutoff_date=cutoff_date,
        feature_engine=feature_engine
    )
    
    # Display results
    print("\n" + "=" * 80)
    print(f"RESULTS: {len(buy_signals)} Active Buy Signals Found")
    print("=" * 80)
    
    if buy_signals:
        # Convert to DataFrame for nice display
        df_signals = pd.DataFrame(buy_signals)
        
        # Select key columns for display
        display_cols = ['ticker', 'date', 'price', 'stop_price', 'target_price', 
                       'risk_pct', 'reward_pct', 'volume_ratio', 'rs']
        
        print("\n")
        print(df_signals[display_cols].to_string(index=False))
        
        print("\n" + "-" * 80)
        print("Trade Details:")
        for i, signal in enumerate(buy_signals, 1):
            print(f"\n{i}. {signal['ticker']} - ${signal['price']:.2f}")
            print(f"   Entry: ${signal['price']:.2f}")
            print(f"   Stop:  ${signal['stop_price']:.2f} ({signal['risk_pct']:.1f}% risk)")
            print(f"   Target: ${signal['target_price']:.2f} ({signal['reward_pct']:.1f}% reward)")
            print(f"   Volume Ratio: {signal['volume_ratio']:.2f}x" if signal['volume_ratio'] else "   Volume Ratio: N/A")
            print(f"   Relative Strength: {signal['rs']:.4f}" if signal['rs'] else "   Relative Strength: N/A")
    else:
        print("\nNo active buy signals found on this date.")
        print("This could mean:")
        print("  - Market was in consolidation/correction")
        print("  - No stocks met the strict SEPA criteria")
        print("  - Try a different date when market was stronger")
    
    print("\n" + "=" * 80)
    return buy_signals


def example_scan_multiple_dates():
    """
    Example: Scan for buy signals across multiple dates (mini backtest).
    """
    print("\n\n" + "=" * 80)
    print("EXAMPLE: Scanning Multiple Dates")
    print("=" * 80)
    
    # Initialize
    repo = DataRepository()
    spy = repo.get_benchmark_data()
    feature_engine = FeatureEngineer(benchmark_data=spy)
    strategy = SEPAStrategy(benchmark_data=spy)
    
    # Define date range
    dates_to_scan = pd.date_range(start='2024-10-01', end='2024-11-15', freq='W-FRI')
    
    # Load data once
    test_tickers = ['NVDA', 'SMCI', 'PLTR', 'AMD', 'AVGO']
    ticker_data = {t: repo.get_ticker_data(t, use_cache=True) for t in test_tickers 
                   if repo.get_ticker_data(t, use_cache=True) is not None}
    
    print(f"\nScanning {len(dates_to_scan)} dates for {len(ticker_data)} tickers...\n")
    
    # Scan each date
    results_by_date = {}
    for date in dates_to_scan:
        signals = strategy.scan_universe_for_date(ticker_data, date, feature_engine)
        results_by_date[date] = signals
        
        signal_tickers = [s['ticker'] for s in signals]
        print(f"{date.strftime('%Y-%m-%d')}: {len(signals)} signals - {', '.join(signal_tickers) if signal_tickers else 'None'}")
    
    # Summary
    total_signals = sum(len(signals) for signals in results_by_date.values())
    print(f"\nTotal signals across all dates: {total_signals}")
    
    return results_by_date


if __name__ == "__main__":
    # Run example 1: Single date scan
    signals = example_scan_for_date()
    
    # Uncomment to run example 2: Multiple dates
    # results = example_scan_multiple_dates()
    
    print("\n✅ Example complete!")
    print("\nTo use in your own code:")
    print("  signals = strategy.scan_universe_for_date(ticker_data, cutoff_date, feature_engine)")
