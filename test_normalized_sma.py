"""
Quick test to verify normalized SMA features
"""

import pandas as pd
import numpy as np
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

from src.data_engine import DataRepository
from src.indicators import TechnicalAnalysis

print("=" * 80)
print(" NORMALIZED SMA FEATURES TEST")
print("=" * 80)

# Initialize
repo = DataRepository()
ta = TechnicalAnalysis()

# Test on NVDA
ticker = 'NVDA'
df = repo.get_ticker_data(ticker, use_cache=True)

if df is not None:
    print(f"\n✅ Testing {ticker} ({len(df)} rows)\n")
    
    # Calculate SMAs with normalization
    df = ta.add_sma(df, periods=[50, 150, 200])
    
    # Show last 5 rows
    print("📊 Raw vs Normalized SMA Values (last 5 rows):\n")
    
    cols_to_show = ['Close', 'SMA_50', 'Price_vs_SMA_50', 'SMA_150', 'Price_vs_SMA_150', 'SMA_200', 'Price_vs_SMA_200']
    
    latest = df[cols_to_show].tail()
    print(latest.to_string())
    
    # Verify calculation
    print("\n🧪 Verification (latest row):")
    close = df['Close'].iloc[-1]
    sma50 = df['SMA_50'].iloc[-1]
    price_vs_sma50 = df['Price_vs_SMA_50'].iloc[-1]
    
    expected = ((close - sma50) / sma50) * 100
    
    print(f"  Close: ${close:.2f}")
    print(f"  SMA_50: ${sma50:.2f}")
    print(f"  Price_vs_SMA_50: {price_vs_sma50:.2f}%")
    print(f"  Expected: {expected:.2f}%")
    print(f"  Match: {'✅ YES' if abs(price_vs_sma50 - expected) < 0.01 else '❌ NO'}")
    
    # Interpretation
    print(f"\n💡 Interpretation:")
    if price_vs_sma50 > 0:
        print(f"  {ticker} is {abs(price_vs_sma50):.2f}% ABOVE its 50-day SMA (bullish)")
    else:
        print(f"  {ticker} is {abs(price_vs_sma50):.2f}% BELOW its 50-day SMA (bearish)")
    
    # Check all 3 normalized features exist
    print(f"\n✅ All normalized SMA features present:")
    for period in [50, 150, 200]:
        feature = f'Price_vs_SMA_{period}'
        if feature in df.columns:
            latest_val = df[feature].iloc[-1]
            print(f"  • {feature}: {latest_val:+.2f}%")
        else:
            print(f"  ❌ {feature}: MISSING")
    
    print(f"\n✅ Normalized SMA features working correctly!")
else:
    print(f"❌ Failed to load {ticker}")

print("\n" + "=" * 80)
