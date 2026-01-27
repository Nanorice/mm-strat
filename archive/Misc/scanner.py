import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

import pandas as pd
from datetime import datetime
from src.data_engine import DataRepository
from src.features import FeatureEngineer
from src.strategy import SEPAStrategy

date = pd.Timestamp('2025-11-26')

print("\n[1/4] Initializing components...")
repo = DataRepository()
spy = repo.get_benchmark_data()
feature_engine = FeatureEngineer(benchmark_data=spy)
strategy = SEPAStrategy(benchmark_data=spy)

# Define cutoff date
cutoff_date = date  # Change this to any date you want to analyze
print(f"\n[2/4] Cutoff date: {cutoff_date.strftime('%Y-%m-%d')}")

# Get universe (or use a subset for testing)
print("\n[3/4] Loading ticker data...")
tickers = repo.update_universe()

# Load data for each ticker
ticker_data = {}
for ticker in tickers:
    df = repo.get_ticker_data(ticker, use_cache=True)
    if df is not None:
        ticker_data[ticker] = df

buy_signals = strategy.scan_universe_for_date(
    ticker_data_dict=ticker_data,
    cutoff_date=cutoff_date,
    feature_engine=feature_engine
)

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
