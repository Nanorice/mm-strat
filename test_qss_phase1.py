"""
Test Script for QSS Phase 1 Implementation
Validates FeatureEngine, modular SEPAStrategy, and end-to-end integration.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

import pandas as pd
from src.data_engine import DataRepository
from src.features import FeatureEngineer
from src.strategy import SEPAStrategy

def test_feature_engine():
    """Test 1: FeatureEngine lightweight mode"""
    print("="*80)
    print("TEST 1: FeatureEngine Lightweight Mode")
    print("="*80)
    
    try:
        # Initialize components
        repo = DataRepository()
        spy = repo.get_benchmark_data()
        fe = FeatureEngineer(benchmark_data=spy)
        
        # Test single ticker
        print("\nTesting NVDA data processing...")
        nvda_data = repo.get_ticker_data('NVDA')
        
        if nvda_data is None:
            print("❌ FAILED: Could not load NVDA data")
            return False
        
        # Calculate lightweight features
        enriched = fe.calculate_lightweight_features(nvda_data)
        
        # Verify all lightweight indicators present
        required = ['SMA_50', 'SMA_150', 'SMA_200', 'ATR', 'RS', 'Vol_Ratio', 'Breakout']
        missing = [col for col in required if col not in enriched.columns]
        
        if missing:
            print(f"❌ FAILED: Missing lightweight features: {missing}")
            return False
        
        print(f"✅ PASSED: All lightweight features calculated")
        print(f"   Rows: {len(enriched)}, Columns: {len(enriched.columns)}")
        print(f"   Features: {', '.join(required)}")
        
        # Show feature summary
        summary = fe.get_feature_summary(enriched)
        print(f"\n   Feature Summary:")
        print(f"   - Date range: {summary['date_range']}")
        print(f"   - Validation: {'✅' if summary['lightweight_present'] else '❌'}")
        
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_modular_strategy():
    """Test 2: Modular SEPA Strategy"""
    print("\n" + "="*80)
    print("TEST 2: Modular SEPA Strategy")
    print("="*80)
    
    try:
        # Initialize components
        repo = DataRepository()
        spy = repo.get_benchmark_data()
        fe = FeatureEngineer(benchmark_data=spy)
        strategy = SEPAStrategy(benchmark_data=spy)
        
        # Test on known ticker
        print("\nTesting modular methods on NVDA...")
        nvda_data = repo.get_ticker_data('NVDA')
        enriched = fe.calculate_lightweight_features(nvda_data)
        latest = enriched.index[-1]
        
        # Test individual components
        print(f"\nLatest date: {latest.strftime('%Y-%m-%d')}")
        
        trend_ok, trend_meta = strategy.check_trend_template(enriched, latest)
        print(f"\n1. Trend Template: {'✅ PASS' if trend_ok else '❌ FAIL'}")
        print(f"   Price: ${trend_meta.get('price', 0):.2f}")
        print(f"   SMA 50/150/200: {trend_meta.get('sma_50', 0):.2f} / " + 
              f"{trend_meta.get('sma_150', 0):.2f} / {trend_meta.get('sma_200', 0):.2f}")
        
        vcp_ok, vcp_meta = strategy.check_vcp_structure(enriched, latest)
        print(f"\n2. VCP Structure: {'✅ PASS' if vcp_ok else '❌ FAIL'}")
        print(f"   ATR: ${vcp_meta.get('atr', 0):.2f} ({vcp_meta.get('atr_pct', 0):.2f}%)")
        
        trigger_ok, trigger_meta = strategy.check_trigger_conditions(enriched, latest)
        print(f"\n3. Trigger Conditions: {'✅ PASS' if trigger_ok else '❌ FAIL'}")
        print(f"   Breakout: {trigger_meta.get('breakout', False)}")
        print(f"   Volume Ratio: {trigger_meta.get('volume_ratio', 0):.2f}x")
        print(f"   RS Confirmed: {trigger_meta.get('rs_confirmed', False)}")
        
        # Test integrated signal generation
        signal = strategy.generate_signals(enriched, latest)
        print(f"\nIntegrated Signal: {'BUY ✅' if signal['buy'] else 'WAIT ⏸️'}")
        print(f"   Trend OK: {signal['metadata']['trend_ok']}")
        print(f"   VCP OK: {signal['metadata']['vcp_ok']}")
        print(f"   Trigger OK: {signal['metadata']['trigger_ok']}")
        
        print("\n✅ PASSED: Modular strategy methods working correctly")
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_batch_processing():
    """Test 3: Batch processing performance"""
    print("\n" + "="*80)
    print("TEST 3: Batch Processing Performance")
    print("="*80)
    
    try:
        import time
        
        # Initialize components
        repo = DataRepository()
        spy = repo.get_benchmark_data()
        fe = FeatureEngineer(benchmark_data=spy)
        
        # Get a small batch of tickers
        test_tickers = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'AMD']
        print(f"\nTesting batch processing on {len(test_tickers)} tickers...")
        
        # Load data
        ticker_data = {}
        for ticker in test_tickers:
            df = repo.get_ticker_data(ticker)
            if df is not None:
                ticker_data[ticker] = df
        
        print(f"Loaded {len(ticker_data)} tickers successfully")
        
        # Process batch
        start_time = time.time()
        enriched_batch = fe.process_universe_batch(ticker_data)
        elapsed = time.time() - start_time
        
        print(f"\n✅ PASSED: Batch processing completed")
        print(f"   Processed: {len(enriched_batch)}/{len(ticker_data)} tickers")
        print(f"   Time: {elapsed:.2f} seconds")
        print(f"   Rate: {len(enriched_batch)/elapsed:.1f} tickers/sec")
        
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("\n" + "🚀 QSS PHASE 1 VALIDATION SUITE")
    print("="*80)
    
    results = []
    
    # Run tests
    results.append(("FeatureEngine", test_feature_engine()))
    results.append(("Modular Strategy", test_modular_strategy()))
    results.append(("Batch Processing", test_batch_processing()))
    
    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name:.<40} {status}")
    
    total_passed = sum(passed for _, passed in results)
    total_tests = len(results)
    
    print(f"\nTotal: {total_passed}/{total_tests} tests passed")
    
    if total_passed == total_tests:
        print("\n🎉 ALL TESTS PASSED! QSS Phase 1 is ready.")
    else:
        print("\n⚠️  Some tests failed. Please review the errors above.")
