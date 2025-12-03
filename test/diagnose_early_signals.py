"""
Diagnostic script to investigate why no signals are generated in early 2020.

This script checks:
1. Data availability for early 2020
2. Benchmark (SPY) data coverage
3. Feature calculation completeness
4. Strategy signal generation for sample dates
"""

import pandas as pd
import numpy as np
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.append(str(Path(__file__).parent))

from src.data_engine import DataRepository
from src.strategy import SEPAStrategy
from src.features import FeatureEngineer

def check_data_availability(repo, start_date='2020-01-01', sample_size=10):
    """Check if we have price data for early 2020."""
    print("=" * 80)
    print("1. CHECKING DATA AVAILABILITY")
    print("=" * 80)
    
    # Get a sample of tickers
    tickers = repo.update_universe()[:sample_size]
    print(f"\nChecking {sample_size} sample tickers...")
    
    start = pd.to_datetime(start_date)
    issues = []
    
    for ticker in tickers:
        df = repo.get_price_data(ticker)
        if df is None or len(df) == 0:
            issues.append(f"{ticker}: No data at all")
            continue
        
        min_date = df.index.min()
        if min_date > start:
            issues.append(f"{ticker}: Data starts {min_date.date()} (after {start.date()})")
        
        # Check data around early 2020
        early_2020 = df[(df.index >= '2020-01-01') & (df.index < '2020-06-01')]
        if len(early_2020) == 0:
            issues.append(f"{ticker}: No data in early 2020")
        else:
            print(f"  ✅ {ticker}: {len(early_2020)} days in early 2020, starts {min_date.date()}")
    
    if issues:
        print("\n⚠️  Data Issues Found:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("\n✅ All sample tickers have data for early 2020")
    
    return len(issues) == 0


def check_benchmark_data(repo, start_date='2020-01-01'):
    """Check SPY benchmark data."""
    print("\n" + "=" * 80)
    print("2. CHECKING BENCHMARK (SPY) DATA")
    print("=" * 80)
    
    benchmark = repo.get_benchmark_data()
    
    if benchmark is None:
        print("❌ No benchmark data loaded!")
        return False
    
    start = pd.to_datetime(start_date)
    min_date = benchmark.index.min()
    max_date = benchmark.index.max()
    
    print(f"\nBenchmark date range: {min_date.date()} to {max_date.date()}")
    
    if min_date > start:
        print(f"⚠️  Benchmark starts AFTER {start.date()} - this will cause issues!")
        return False
    
    # Check early 2020 coverage
    early_2020 = benchmark[(benchmark.index >= '2020-01-01') & (benchmark.index < '2020-06-01')]
    print(f"✅ Benchmark has {len(early_2020)} days in early 2020")
    
    # Check for NaN values
    nan_count = benchmark['Close'].isnull().sum()
    if nan_count > 0:
        print(f"⚠️  Benchmark has {nan_count} NaN values")
        return False
    
    return True


def check_feature_warmup(repo, ticker='AAPL', target_date='2020-11-01'):
    """Check how many days of history are needed for features."""
    print("\n" + "=" * 80)
    print("3. CHECKING FEATURE WARM-UP REQUIREMENTS")
    print("=" * 80)
    
    df = repo.get_price_data(ticker)
    if df is None:
        print(f"❌ Could not load {ticker}")
        return
    
    benchmark = repo.get_benchmark_data()
    feature_engine = FeatureEngineer(benchmark_data=benchmark)
    
    target = pd.to_datetime(target_date)
    
    print(f"\nTesting feature calculation for {ticker} on {target.date()}")
    print(f"Available data starts: {df.index.min().date()}")
    
    # Calculate features
    try:
        df_features = feature_engine.calculate_lightweight_features(df)
        
        # Check how much data we have by target date
        df_at_target = df_features[df_features.index <= target]
        
        if len(df_at_target) == 0:
            print(f"❌ No data available by {target.date()}")
            return
        
        last_row = df_at_target.iloc[-1]
        
        # Check which features are NaN
        feature_cols = [col for col in df_features.columns if col not in ['Open', 'High', 'Low', 'Close', 'Volume']]
        nan_features = [col for col in feature_cols if pd.isna(last_row.get(col))]
        
        print(f"\n✅ Features calculated for {len(df_at_target)} days by {target.date()}")
        print(f"   Features with NaN: {len(nan_features)}/{len(feature_cols)}")
        
        if nan_features:
            print("\n⚠️  NaN Features (likely need more history):")
            for feat in nan_features[:10]:  # Show first 10
                print(f"   - {feat}")
        
        # Calculate days needed
        # SMA_200 needs 200 days minimum
        days_available = len(df[df.index <= target])
        print(f"\n📊 Days of price history by {target.date()}: {days_available}")
        print(f"   Minimum needed for SMA_200: 200 days")
        print(f"   Minimum needed for RS (relative strength): ~50-100 days")
        
        if days_available < 250:
            print(f"\n⚠️  WARNING: Only {days_available} days available - may not be enough for all indicators!")
            warmup_date = df.index.min() + timedelta(days=250)
            print(f"   Recommended start date for strategy: {warmup_date.date()}")
        
    except Exception as e:
        print(f"❌ Feature calculation failed: {e}")
        import traceback
        traceback.print_exc()


def check_strategy_signals(repo, test_date='2020-11-01', sample_size=5):
    """Check if strategy generates signals on a specific date."""
    print("\n" + "=" * 80)
    print("4. CHECKING STRATEGY SIGNAL GENERATION")
    print("=" * 80)
    
    benchmark = repo.get_benchmark_data()
    strategy = SEPAStrategy(benchmark_data=benchmark)
    feature_engine = FeatureEngineer(benchmark_data=benchmark)
    
    test_date = pd.to_datetime(test_date)
    print(f"\nTesting signal generation for {test_date.date()}")
    
    tickers = repo.update_universe()[:sample_size]
    signals_found = 0
    
    for ticker in tickers:
        df = repo.get_price_data(ticker)
        if df is None:
            continue
        
        # Get data up to test date
        df_hist = df[df.index <= test_date]
        if len(df_hist) < 200:  # Need enough history
            print(f"  ⚠️  {ticker}: Only {len(df_hist)} days - SKIPPING")
            continue
        
        # Calculate features
        try:
            df_features = feature_engine.calculate_lightweight_features(df_hist)
            
            # Generate signals
            signals = strategy.generate_signals(ticker, df_features, current_date=test_date)
            
            if signals.get('sepa_qualifying', False):
                print(f"  ✅ {ticker}: SEPA QUALIFYING!")
                if signals.get('volume_dry_up', False):
                    print(f"     🎯 BUY SIGNAL at ${signals.get('close', 0):.2f}")
                    signals_found += 1
                else:
                    print(f"     ⏳ Waiting for volume dry up")
            else:
                reason = signals.get('rejection_reason', 'Unknown')
                print(f"  ❌ {ticker}: Not qualifying - {reason}")
        
        except Exception as e:
            print(f"  ❌ {ticker}: Error - {e}")
    
    print(f"\n📊 Summary: {signals_found} buy signals from {sample_size} tickers")
    
    if signals_found == 0:
        print("\n⚠️  No signals generated - this explains Dataset B issue!")
        print("   Possible causes:")
        print("   1. Insufficient warm-up period (need more historical data)")
        print("   2. Market conditions don't fit SEPA criteria (COVID crash)")
        print("   3. Benchmark calculation issues")


def main():
    print("=" * 80)
    print(" DIAGNOSTIC: EARLY 2020 SIGNAL GENERATION")
    print("=" * 80)
    print("\nInvestigating why no signals in first ~300 days from 2020-01-01\n")
    
    repo = DataRepository()
    
    # Run diagnostics
    data_ok = check_data_availability(repo, start_date='2019-01-01', sample_size=10)
    benchmark_ok = check_benchmark_data(repo, start_date='2019-01-01')
    
    if data_ok and benchmark_ok:
        check_feature_warmup(repo, ticker='AAPL', target_date='2020-11-01')
        check_strategy_signals(repo, test_date='2020-11-01', sample_size=10)
    
    # Recommendation
    print("\n" + "=" * 80)
    print(" RECOMMENDATIONS")
    print("=" * 80)
    
    print("\n1. If data starts from 2020-01-01:")
    print("   Problem: Need ~250 trading days for indicator warm-up")
    print("   Solution: Start price data from 2019-01-01 or earlier")
    print("   Command: python initialise_price_data.py")
    
    print("\n2. First viable signal date:")
    print("   2020-01-01 + 250 trading days ≈ 2020-11-15")
    print("   This matches your observation of ~300 calendar days")
    
    print("\n3. For Dataset B training:")
    print("   Option A: Accept that training data starts from ~Nov 2020")
    print("   Option B: Extend price data back to 2018 for earlier signals")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
