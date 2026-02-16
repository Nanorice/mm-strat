"""
Quick test to verify Python RS Line feature calculations.

Tests that the new derived features are calculated correctly:
- rs_line_log
- rs_line_delta
- rs_line_lag_delta

Usage:
    python scripts/test_python_rs_features.py
"""
import sys
from pathlib import Path
import pandas as pd
import numpy as np

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from indicators import TechnicalAnalysis


def test_rs_line_features():
    """Test that all RS Line features are calculated correctly."""
    print("=" * 60)
    print("Python RS Line Features Test")
    print("=" * 60)

    # Create test data
    dates = pd.date_range('2023-01-01', periods=100, freq='D')

    # Stock price: starts at 100, grows to 150
    stock_close = np.linspace(100, 150, 100)

    # SPY price: starts at 400, grows to 420
    spy_close = np.linspace(400, 420, 100)

    # Create DataFrames
    stock_df = pd.DataFrame({
        'Date': dates,
        'Close': stock_close
    }).set_index('Date')

    spy_series = pd.Series(spy_close, index=dates, name='Close')

    # Apply RS calculation
    result = TechnicalAnalysis.add_relative_strength(stock_df, spy_series)

    # Check that all expected columns exist
    expected_cols = [
        'price_vs_spy',
        'price_vs_spy_ma63',
        'rs_line_uptrend',
        'rs_line_log',
        'rs_line_delta',
        'rs_line_lag_delta',
        'rs_rating',
        'RS',
        'RS_MA'
    ]

    print("\n[TEST 1] Column Existence Check")
    print("-" * 60)
    missing = []
    for col in expected_cols:
        if col in result.columns:
            print(f"   [OK] {col}")
        else:
            print(f"   [FAIL] {col} MISSING")
            missing.append(col)

    if missing:
        print(f"\n[FAIL] Missing columns: {missing}")
        return False

    # Check calculations
    print("\n[TEST 2] Calculation Verification")
    print("-" * 60)

    # Test price_vs_spy calculation
    expected_ratio = stock_close / spy_close
    actual_ratio = result['price_vs_spy'].values

    if np.allclose(expected_ratio, actual_ratio, rtol=1e-10):
        print("   [OK] price_vs_spy = Close / SPY")
    else:
        print("   [FAIL] price_vs_spy calculation incorrect")
        return False

    # Test rs_line_log (should be log of ratio)
    # Skip NaN values
    valid_mask = ~result['rs_line_log'].isna()
    expected_log = np.log(result.loc[valid_mask, 'price_vs_spy'])
    actual_log = result.loc[valid_mask, 'rs_line_log']

    if np.allclose(expected_log, actual_log, rtol=1e-10):
        print("   [OK] rs_line_log = ln(price_vs_spy)")
    else:
        print("   [FAIL] rs_line_log calculation incorrect")
        return False

    # Test rs_line_delta (should be pct_change)
    expected_delta = result['price_vs_spy'].pct_change(1)
    actual_delta = result['rs_line_delta']

    # Compare non-NaN values
    valid_mask = ~expected_delta.isna() & ~actual_delta.isna()
    if np.allclose(expected_delta[valid_mask], actual_delta[valid_mask], rtol=1e-10):
        print("   [OK] rs_line_delta = price_vs_spy.pct_change(1)")
    else:
        print("   [FAIL] rs_line_delta calculation incorrect")
        return False

    # Test rs_line_lag_delta (should be shifted delta)
    expected_lag_delta = result['rs_line_delta'].shift(1)
    actual_lag_delta = result['rs_line_lag_delta']

    valid_mask = ~expected_lag_delta.isna() & ~actual_lag_delta.isna()
    if np.allclose(expected_lag_delta[valid_mask], actual_lag_delta[valid_mask], rtol=1e-10):
        print("   [OK] rs_line_lag_delta = rs_line_delta.shift(1)")
    else:
        print("   [FAIL] rs_line_lag_delta calculation incorrect")
        return False

    # Show sample output
    print("\n[TEST 3] Sample Output (last 5 rows)")
    print("-" * 60)
    sample_cols = ['Close', 'price_vs_spy', 'rs_line_log', 'rs_line_delta', 'rs_line_lag_delta']
    print(result[sample_cols].tail(5).to_string())

    print("\n" + "=" * 60)
    print("[OK] All Tests Passed")
    print("=" * 60)
    return True


if __name__ == "__main__":
    try:
        success = test_rs_line_features()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n[ERROR] Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
