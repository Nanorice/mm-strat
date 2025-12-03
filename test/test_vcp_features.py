"""
Test script for new VCP features
Tests the 4 new lightweight features and alpha009 integration
"""

import pandas as pd
import numpy as np
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

from src.data_engine import DataRepository
from src.features import FeatureEngineer
from src.indicators import TechnicalAnalysis

def test_vcp_features():
    """Test VCP features on real ticker data."""
    print("=" * 80)
    print(" VCP FEATURES TEST")
    print("=" * 80)
    
    # Initialize components
    repo = DataRepository()
    ta = TechnicalAnalysis()
    
    # Test on a few tickers
    test_tickers = ['NVDA', 'AAPL', 'MSFT']
    
    for ticker in test_tickers:
        print(f"\n\n📊 Testing {ticker}...")
        print("-" * 80)
        
        try:
            # Load price data
            df = repo.get_ticker_data(ticker, use_cache=True)
            
            if df is None or len(df) < 100:
                print(f"  ❌ Insufficient data for {ticker}")
                continue
            
            print(f"  ✅ Loaded {len(df)} rows")
            
            # Test individual VCP features
            print(f"\n  🧪 Testing VCP Features:")
            
            # 1. nATR
            df = ta.add_atr(df, period=14)
            df = ta.add_normalized_atr(df, period=14)
            latest_natr = df['nATR'].iloc[-1]
            print(f"    • nATR (latest): {latest_natr:.2f}%")
            
            # 2. VCP Ratio
            df = ta.add_vcp_ratio(df, short=10, long=50)
            latest_vcp = df['VCP_Ratio'].iloc[-1]
            print(f"    • VCP_Ratio (latest): {latest_vcp:.3f}")
            if latest_vcp < 0.7:
                print(f"      → 🎯 Strong contraction detected!")
            elif latest_vcp < 1.0:
                print(f"      → ⚠️  Moderate tightening")
            else:
                print(f"      → ❌ Expanding volatility")
            
            # 3. Consolidation Width
            df = ta.add_consolidation_width(df, period=20)
            latest_width = df['Consolidation_Width'].iloc[-1]
            print(f"    • Consolidation_Width (latest): {latest_width:.2f}%")
            if latest_width < 5:
                print(f"      → 🎯 Very tight base!")
            elif latest_width < 10:
                print(f"      → ⚠️  Decent consolidation")
            else:
                print(f"      → ❌ Too loose")
            
            # 4. Dry Up Volume
            df = ta.add_dry_up_volume(df, short=5, long=50)
            latest_dryup = df['Dry_Up_Volume'].iloc[-1]
            print(f"    • Dry_Up_Volume (latest): {latest_dryup:.3f}")
            if latest_dryup < 0.5:
                print(f"      → 🎯 Very low volume (sellers exhausted)")
            elif latest_dryup < 0.8:
                print(f"      → ⚠️  Below average")
            else:
                print(f"      → ❌ High volume")
            
            # Check for NaN/inf values
            vcp_cols = ['nATR', 'VCP_Ratio', 'Consolidation_Width', 'Dry_Up_Volume']
            nan_counts = df[vcp_cols].isnull().sum()
            inf_counts = df[vcp_cols].apply(lambda x: np.isinf(x).sum())
            
            print(f"\n  📈 Data Quality:")
            print(f"    • Total rows: {len(df)}")
            print(f"    • NaN counts: {dict(nan_counts)}")
            print(f"    • Inf counts: {dict(inf_counts)}")
            
            # Show last 5 rows
            print(f"\n  📋 Last 5 rows:")
            print(df[['Close'] + vcp_cols].tail().to_string())
            
        except Exception as e:
            print(f"  ❌ Error testing {ticker}: {e}")
            import traceback
            traceback.print_exc()

def test_feature_engineer():
    """Test FeatureEngineer integration."""
    print("\n\n" + "=" * 80)
    print(" FEATURE ENGINEER INTEGRATION TEST")
    print("=" * 80)
    
    repo = DataRepository()
    benchmark_data = repo.get_benchmark_data()
    fe = FeatureEngineer(benchmark_data=benchmark_data)
    
    # Test lightweight features
    print(f"\n📊 Testing Lightweight Features...")
    
    try:
        df = repo.get_ticker_data('NVDA', use_cache=True)
        
        if df is None:
            print("  ❌ Failed to load NVDA data")
            return
        
        print(f"  ✅ Loaded {len(df)} rows for NVDA")
        
        # Calculate lightweight features
        df_enriched = fe.calculate_lightweight_features(df)
        
        print(f"\n  📋 Feature List ({len(fe.lightweight_features)} features):")
        for i, feature in enumerate(fe.lightweight_features, 1):
            if feature in df_enriched.columns:
                latest_value = df_enriched[feature].iloc[-1]
                print(f"    {i:2d}. {feature:22s} = {latest_value:10.3f}")
            else:
                print(f"    {i:2d}. {feature:22s} = ❌ MISSING")
        
        # Verify all VCP features present
        vcp_features = ['nATR', 'VCP_Ratio', 'Consolidation_Width', 'Dry_Up_Volume']
        missing_vcp = [f for f in vcp_features if f not in df_enriched.columns]
        
        if missing_vcp:
            print(f"\n  ❌ Missing VCP features: {missing_vcp}")
        else:
            print(f"\n  ✅ All VCP features present!")
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()

def test_heavyweight_features():
    """Test heavyweight features with alpha009."""
    print("\n\n" + "=" * 80)
    print(" HEAVYWEIGHT FEATURES TEST (with alpha009)")
    print("=" * 80)
    
    repo = DataRepository()
    benchmark_data = repo.get_benchmark_data()
    fe = FeatureEngineer(benchmark_data=benchmark_data)
    
    print(f"\n📊 Testing Alpha Factors...")
    
    try:
        df = repo.get_ticker_data('NVDA', use_cache=True)
        
        if df is None:
            print("  ❌ Failed to load NVDA data")
            return
        
        print(f"  ✅ Loaded {len(df)} rows for NVDA")
        
        # Calculate lightweight first
        df = fe.calculate_lightweight_features(df)
        
        # Calculate heavyweight (alphas)
        df = fe.calculate_heavyweight_features(df, 'NVDA')
        
        # Check for alpha columns
        expected_alphas = ['alpha001', 'alpha006', 'alpha009', 'alpha012', 'alpha041', 'alpha101']
        
        print(f"\n  📋 Alpha Factors:")
        for alpha in expected_alphas:
            if alpha in df.columns:
                latest_value = df[alpha].iloc[-1]
                nan_count = df[alpha].isnull().sum()
                print(f"    • {alpha}: {latest_value:10.3f} (NaN count: {nan_count})")
            else:
                print(f"    • {alpha}: ❌ MISSING")
        
        # Verify alpha009 specifically
        if 'alpha009' in df.columns:
            print(f"\n  ✅ alpha009 successfully integrated!")
            print(f"    Stats:")
            print(f"      - Mean: {df['alpha009'].mean():.3f}")
            print(f"      - Std:  {df['alpha009'].std():.3f}")
            print(f"      - Min:  {df['alpha009'].min():.3f}")
            print(f"      - Max:  {df['alpha009'].max():.3f}")
        else:
            print(f"\n  ❌ alpha009 NOT FOUND!")
        
        # Show last 5 rows of alphas
        print(f"\n  📋 Last 5 rows of alphas:")
        alpha_cols = [col for col in df.columns if col.startswith('alpha')]
        print(df[alpha_cols].tail().to_string())
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()

def test_dataset_a_compatibility():
    """Test that new features work in Dataset A generation flow."""
    print("\n\n" + "=" * 80)
    print(" DATASET A COMPATIBILITY TEST")
    print("=" * 80)
    
    from src.data_engine import DataRepository
    from src.features import FeatureEngineer
    
    repo = DataRepository()
    benchmark_data = repo.get_benchmark_data()
    fe = FeatureEngineer(benchmark_data=benchmark_data)
    
    # Simulate Dataset A generation for a few tickers
    test_tickers = ['NVDA', 'AAPL']
    
    print(f"\n📊 Simulating Dataset A generation for {len(test_tickers)} tickers...")
    
    all_features_count = 0
    
    for ticker in test_tickers:
        try:
            df = repo.get_ticker_data(ticker, use_cache=True)
            
            if df is None:
                continue
            
            # Lightweight features
            df = fe.calculate_lightweight_features(df)
            
            # Heavyweight features
            df = fe.calculate_heavyweight_features(df, ticker)
            
            # Count total features
            feature_cols = [col for col in df.columns if col not in ['Open', 'High', 'Low', 'Close', 'Volume']]
            all_features_count = len(feature_cols)
            
            print(f"  ✅ {ticker}: {len(df)} rows × {all_features_count} features")
            
        except Exception as e:
            print(f"  ❌ {ticker}: {e}")
    
    print(f"\n  📊 Total feature count: {all_features_count}")
    print(f"     Expected: 22 (16 lightweight + 6 alphas)")
    
    if all_features_count == 22:
        print(f"  ✅ Feature count matches expectation!")
    else:
        print(f"  ⚠️  Feature count mismatch (expected 22, got {all_features_count})")

if __name__ == '__main__':
    print("\n🧪 VCP FEATURES IMPLEMENTATION TEST\n")
    
    # Run all tests
    test_vcp_features()
    test_feature_engineer()
    test_heavyweight_features()
    test_dataset_a_compatibility()
    
    print("\n\n" + "=" * 80)
    print(" TEST COMPLETE")
    print("=" * 80)
    print("\n✨ All VCP features tested!\n")
