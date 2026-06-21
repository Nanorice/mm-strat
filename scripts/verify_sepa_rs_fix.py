"""
Verification script for SEPA RS filter fix.

Tests:
1. price_vs_spy calculation in indicators.py
2. SEPA screening uses price_vs_spy for C9 (not rs_rating)
3. C12 is dropped (trigger has only C10 & C11)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from src.data_engine import DataRepository
from src.indicators import TechnicalAnalysis
from src.vectorized_screening import VectorizedSEPAScreener


def test_price_vs_spy_calculation():
    """Test that price_vs_spy features are calculated correctly."""
    print("\n" + "="*60)
    print("TEST 1: price_vs_spy Calculation")
    print("="*60)

    repo = DataRepository()

    # Get SPY and AAPL data
    spy_data = repo.get_ticker_data('SPY')
    aapl_data = repo.get_ticker_data('AAPL')

    if spy_data is None or aapl_data is None:
        print("[FAIL] Could not load SPY or AAPL data")
        return False

    # Calculate RS features
    ta = TechnicalAnalysis()
    aapl_enriched = ta.add_relative_strength(aapl_data, spy_data['Close'])

    # Check all required columns exist
    required_cols = ['rs_rating', 'price_vs_spy', 'price_vs_spy_ma63', 'rs_line_uptrend']
    missing_cols = [col for col in required_cols if col not in aapl_enriched.columns]

    if missing_cols:
        print(f"[FAIL] Missing columns: {missing_cols}")
        return False

    print("[PASS] All RS features calculated")

    # Verify calculation correctness
    latest_date = aapl_enriched.index[-1]
    latest = aapl_enriched.loc[latest_date]

    # Manual calculation
    spy_close = spy_data.loc[latest_date, 'Close']
    expected_price_vs_spy = latest['Close'] / spy_close

    if abs(latest['price_vs_spy'] - expected_price_vs_spy) > 1e-6:
        print(f"[FAIL] price_vs_spy calculation incorrect")
        print(f"   Expected: {expected_price_vs_spy:.6f}")
        print(f"   Got: {latest['price_vs_spy']:.6f}")
        return False

    print(f"[PASS] price_vs_spy calculated correctly: {latest['price_vs_spy']:.6f}")

    # Check MA63 calculation
    ma63_manual = aapl_enriched['price_vs_spy'].tail(63).mean()
    if abs(latest['price_vs_spy_ma63'] - ma63_manual) > 1e-6:
        print(f"[FAIL] price_vs_spy_ma63 calculation incorrect")
        return False

    print(f"[PASS] price_vs_spy_ma63 calculated correctly: {latest['price_vs_spy_ma63']:.6f}")

    # Check boolean flag
    expected_uptrend = latest['price_vs_spy'] > latest['price_vs_spy_ma63']
    if latest['rs_line_uptrend'] != expected_uptrend:
        print(f"[FAIL] rs_line_uptrend flag incorrect")
        return False

    print(f"[PASS] rs_line_uptrend flag correct: {latest['rs_line_uptrend']}")

    return True


def test_sepa_screening_uses_new_rs():
    """Test that SEPA screening uses price_vs_spy for C9."""
    print("\n" + "="*60)
    print("TEST 2: SEPA Screening Uses price_vs_spy for C9")
    print("="*60)

    repo = DataRepository()
    spy_data = repo.get_ticker_data('SPY')
    aapl_data = repo.get_ticker_data('AAPL')

    if spy_data is None or aapl_data is None:
        print("[FAIL] Could not load data")
        return False

    # Enrich AAPL with all indicators
    ta = TechnicalAnalysis()
    aapl_enriched = ta.add_sma(aapl_data, periods=[50, 150, 200])
    aapl_enriched = ta.add_relative_strength(aapl_enriched, spy_data['Close'])
    aapl_enriched = ta.add_52_week_highs_lows(aapl_enriched)

    # Run SEPA screening
    trend_ok, trigger_ok = VectorizedSEPAScreener.screen_single_ticker_split(aapl_enriched)

    # Check that trend_ok uses price_vs_spy (C9)
    # We'll manually verify by checking a specific date
    test_date = aapl_enriched.index[-100]  # Some historical date

    row = aapl_enriched.loc[test_date]

    # Manual C9 check using price_vs_spy
    c9_expected = row['price_vs_spy'] > row['price_vs_spy_ma63']

    # Manual C1-C8
    c1 = row['Close'] > row['SMA_150']
    c2 = row['Close'] > row['SMA_200']
    c3 = row['SMA_150'] > row['SMA_200']
    c4 = row['SMA_200'] > aapl_enriched.loc[:test_date, 'SMA_200'].shift(20).loc[test_date]
    c5 = row['SMA_50'] > row['SMA_150']
    c6 = row['Close'] > row['SMA_50']
    c7 = row['Close'] > row['Low_52W'] * 1.3
    c8 = row['Close'] > row['High_52W'] * 0.85

    expected_trend = c1 and c2 and c3 and c4 and c5 and c6 and c7 and c8 and c9_expected

    actual_trend = trend_ok.loc[test_date]

    if expected_trend != actual_trend:
        print(f"[FAIL] trend_ok calculation mismatch at {test_date}")
        print(f"   Expected: {expected_trend}")
        print(f"   Got: {actual_trend}")
        print(f"   C9 (price_vs_spy > ma63): {c9_expected}")
        return False

    print(f"[PASS] SEPA screening correctly uses price_vs_spy for C9")
    print(f"   Test date: {test_date}")
    print(f"   trend_ok: {actual_trend}")

    return True


def test_c12_dropped():
    """Test that C12 is no longer part of trigger logic."""
    print("\n" + "="*60)
    print("TEST 3: C12 Dropped from Trigger Logic")
    print("="*60)

    repo = DataRepository()
    spy_data = repo.get_ticker_data('SPY')
    aapl_data = repo.get_ticker_data('AAPL')

    if spy_data is None or aapl_data is None:
        print("[FAIL] Could not load data")
        return False

    # Enrich data
    ta = TechnicalAnalysis()
    aapl_enriched = ta.add_sma(aapl_data, periods=[50, 150, 200])
    aapl_enriched = ta.add_relative_strength(aapl_enriched, spy_data['Close'])
    aapl_enriched = ta.add_52_week_highs_lows(aapl_enriched)

    # Run SEPA screening
    trend_ok, trigger_ok = VectorizedSEPAScreener.screen_single_ticker_split(aapl_enriched)

    # Check trigger logic manually
    test_date = aapl_enriched.index[-50]
    row = aapl_enriched.loc[test_date]

    # Manual C10 & C11 (C12 should NOT be included)
    high_20d_prev = aapl_enriched.loc[:test_date, 'High'].shift(1).tail(20).max()
    c10 = row['Close'] > high_20d_prev

    vol_ma_50_prev = aapl_enriched.loc[:test_date, 'Volume'].shift(1).tail(50).mean()
    c11 = row['Volume'] / vol_ma_50_prev > 1.3

    expected_trigger = c10 and c11
    actual_trigger = trigger_ok.loc[test_date]

    # Note: C12 would be: rs_rating > rs_rating.rolling(63).mean()
    # We verify it's NOT affecting the result

    if expected_trigger != actual_trigger:
        print(f"[FAIL] trigger_ok calculation mismatch at {test_date}")
        print(f"   Expected (C10 & C11): {expected_trigger}")
        print(f"   Got: {actual_trigger}")
        return False

    print(f"[PASS] Trigger logic correctly uses only C10 & C11 (C12 dropped)")
    print(f"   Test date: {test_date}")
    print(f"   trigger_ok: {actual_trigger}")

    return True


def main():
    """Run all verification tests."""
    print("\n" + "="*60)
    print("SEPA RS FIX VERIFICATION")
    print("="*60)

    tests = [
        test_price_vs_spy_calculation,
        test_sepa_screening_uses_new_rs,
        test_c12_dropped,
    ]

    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as e:
            print(f"\n[EXCEPTION] in {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)

    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    passed = sum(results)
    total = len(results)

    print(f"Passed: {passed}/{total}")

    if passed == total:
        print("\n[SUCCESS] ALL TESTS PASSED")
        return 0
    else:
        print(f"\n[FAILED] {total - passed} TEST(S) FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
