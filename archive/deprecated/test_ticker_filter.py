"""Test ticker filter functionality."""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from src.ticker_filter import TickerFilter

def main():
    """Test the ticker filter."""
    print("="*80)
    print(" TICKER FILTER TEST")
    print("="*80)

    filter_obj = TickerFilter()
    filter_obj.load_profiles()

    # Test with known good and bad tickers
    test_tickers = [
        # Real stocks (should KEEP)
        'AAPL', 'MSFT', 'TSLA', 'NVDA', 'GOOGL',
        'BLK', 'BX', 'APO', 'ARES',  # Real asset management companies

        # Funds/Trusts (should EXCLUDE)
        'BDJ', 'BGR', 'BGY', 'BOE', 'PCN',
        'ASGI', 'DLY', 'ECAT', 'FSCO', 'MEGI',
    ]

    print(f"\nTesting {len(test_tickers)} tickers...\n")

    # Test each ticker
    print("Individual ticker tests:")
    print(f"{'Ticker':<10} {'Company Name':<50} {'Result':<15}")
    print("-" * 80)

    for ticker in test_tickers:
        is_fund = filter_obj.is_fund_or_trust(ticker)
        if ticker in filter_obj.profiles.index:
            company_name = filter_obj.profiles.loc[ticker, 'companyName']
        else:
            company_name = "NOT FOUND"

        result = "EXCLUDE (Fund)" if is_fund else "KEEP (Stock)"
        print(f"{ticker:<10} {company_name:<50} {result:<15}")

    # Filter the list
    print("\n" + "="*80)
    print("Filtering results:")
    print("="*80 + "\n")

    filtered = filter_obj.filter_stocks_only(test_tickers, verbose=True)

    print(f"\nKept tickers ({len(filtered)}):")
    print(", ".join(filtered))

    excluded_breakdown = filter_obj.get_excluded_tickers(test_tickers)
    print(f"\nExcluded funds ({len(excluded_breakdown['funds'])}):")
    print(", ".join(excluded_breakdown['funds']))

    # Validate results
    print("\n" + "="*80)
    print("VALIDATION:")
    print("="*80)

    expected_keep = {'AAPL', 'MSFT', 'TSLA', 'NVDA', 'GOOGL', 'BLK', 'BX', 'APO', 'ARES'}
    expected_exclude = {'BDJ', 'BGR', 'BGY', 'BOE', 'PCN', 'ASGI', 'DLY', 'ECAT', 'FSCO', 'MEGI'}

    kept_set = set(filtered)
    excluded_set = set(excluded_breakdown['funds'])

    if kept_set == expected_keep:
        print("✅ PASS: All expected stocks were kept")
    else:
        print("❌ FAIL: Stock filtering incorrect")
        print(f"   Expected: {expected_keep}")
        print(f"   Got:      {kept_set}")

    if excluded_set == expected_exclude:
        print("✅ PASS: All expected funds were excluded")
    else:
        print("❌ FAIL: Fund filtering incorrect")
        print(f"   Expected: {expected_exclude}")
        print(f"   Got:      {excluded_set}")

    print("\n✅ Test complete!\n")


if __name__ == "__main__":
    main()
