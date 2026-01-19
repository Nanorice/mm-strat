"""
Diagnose Cache Corruption - Root Cause Analysis
Tests fresh downloads and compares with cached data.
"""

import pandas as pd
import requests
import sys
from pathlib import Path

sys.path.append('.')
import config


def test_fmp_download(ticker: str):
    """Test fresh download from FMP API."""
    url = f"{config.FMP_BASE_URL}/historical-price-eod/full"
    params = {
        'symbol': ticker,
        'from': '1990-01-01',
        'apikey': config.FMP_API_KEY
    }

    try:
        response = requests.get(url, params=params, timeout=30)

        if response.status_code == 200:
            data = response.json()

            # Handle both dict and list responses
            historical = None
            if isinstance(data, dict) and 'historical' in data:
                historical = data['historical']
            elif isinstance(data, list):
                historical = data

            if historical and len(historical) > 0:
                df = pd.DataFrame(historical)
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date')
                return df, data.get('symbol', ticker) if isinstance(data, dict) else ticker

        return None, None
    except Exception as e:
        print(f"Error downloading {ticker}: {e}")
        return None, None


def get_company_profile(ticker: str):
    """Fetch company profile including IPO date."""
    url = f"{config.FMP_BASE_URL}/profile/{ticker}"
    params = {'apikey': config.FMP_API_KEY}

    try:
        response = requests.get(url, params=params, timeout=30)

        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                return data[0]
    except Exception as e:
        print(f"Error fetching profile for {ticker}: {e}")

    return None


def diagnose_ticker(ticker: str):
    """Complete diagnosis for a single ticker."""

    print(f"\n{'='*80}")
    print(f" DIAGNOSING: {ticker}")
    print(f"{'='*80}\n")

    # 1. Check cached file
    cache_file = Path(f'data/price/{ticker}.parquet')
    if cache_file.exists():
        cached_df = pd.read_parquet(cache_file)
        cached_start = cached_df.index.min()
        cached_end = cached_df.index.max()

        print(f"CACHED DATA:")
        print(f"  File: {cache_file}")
        print(f"  Date range: {cached_start} to {cached_end}")
        print(f"  Rows: {len(cached_df)}")
        print(f"\n  First 5 rows:")
        print(cached_df.head().to_string())
    else:
        print(f"No cached file found for {ticker}")
        return

    # 2. Get company profile (IPO date)
    print(f"\nCOMPANY PROFILE:")
    profile = get_company_profile(ticker)

    if profile:
        ipo_date = profile.get('ipoDate', 'N/A')
        print(f"  Company: {profile.get('companyName', 'N/A')}")
        print(f"  IPO Date: {ipo_date}")
        print(f"  Exchange: {profile.get('exchangeShortName', 'N/A')}")

        # Check if cached data predates IPO
        if ipo_date and ipo_date != 'N/A':
            ipo_dt = pd.to_datetime(ipo_date)
            if cached_start < ipo_dt:
                years_before = (ipo_dt - cached_start).days / 365.25
                print(f"\n  *** PROBLEM: Cached data starts {years_before:.1f} years BEFORE IPO! ***")
    else:
        print(f"  Could not fetch profile")

    # 3. Test fresh download
    print(f"\nFRESH FMP DOWNLOAD:")
    fresh_df, returned_symbol = test_fmp_download(ticker)

    if fresh_df is not None:
        fresh_start = fresh_df['date'].min()
        fresh_end = fresh_df['date'].max()

        print(f"  Symbol returned: {returned_symbol}")
        print(f"  Date range: {fresh_start} to {fresh_end}")
        print(f"  Rows: {len(fresh_df)}")
        print(f"\n  First 5 rows:")
        print(fresh_df.head().to_string())

        # 4. Compare cached vs fresh
        print(f"\nCOMPARISON:")

        if returned_symbol != ticker:
            print(f"  *** SYMBOL MISMATCH: Requested {ticker}, got {returned_symbol} ***")

        cached_start_dt = pd.to_datetime(cached_start)
        fresh_start_dt = pd.to_datetime(fresh_start)

        if cached_start_dt < fresh_start_dt:
            years_diff = (fresh_start_dt - cached_start_dt).days / 365.25
            print(f"  *** CACHED DATA CORRUPTED ***")
            print(f"      Cached starts {years_diff:.1f} years earlier than FMP returns today")
            print(f"      Cached: {cached_start}")
            print(f"      Fresh:  {fresh_start}")
        elif cached_start_dt > fresh_start_dt:
            print(f"  Cached data starts later than FMP (possibly trimmed)")
        else:
            print(f"  Cached and fresh data have same start date - VALID")
    else:
        print(f"  Failed to download fresh data")

    print(f"\n{'='*80}\n")


def main():
    """Run diagnosis on all problematic tickers."""

    problematic_tickers = [
        'RIVN',   # IPO 2021-11-10, cache starts 1994
        'SNOW',   # IPO 2020-09-16, cache starts 1980
        'RKLB',   # IPO 2021-08-25, cache starts 1994
        'U',      # IPO 2019-04-18, cache starts 1984
        'RITM',   # IPO 2015-06-25, cache starts 1994
        'RKT',    # IPO 2020-08-06, cache starts 1994
    ]

    print("="*80)
    print(" CACHE CORRUPTION ROOT CAUSE ANALYSIS")
    print("="*80)
    print(f"\nTesting {len(problematic_tickers)} problematic tickers...")
    print("This will compare cached data vs fresh FMP downloads.")

    input("\nPress Enter to continue...")

    for ticker in problematic_tickers:
        diagnose_ticker(ticker)

    # Check if multiple tickers share identical data
    print("\n" + "="*80)
    print(" CHECKING FOR IDENTICAL DATA ACROSS TICKERS")
    print("="*80 + "\n")

    check_date = '2003-04-02'
    comparison_tickers = ['RITM', 'RIVN', 'RJF', 'RKLB', 'RKT', 'RL']

    print(f"Checking if tickers have identical prices on {check_date}:\n")

    prices = {}
    for ticker in comparison_tickers:
        cache_file = Path(f'data/price/{ticker}.parquet')
        if cache_file.exists():
            df = pd.read_parquet(cache_file)
            if check_date in df.index:
                close_price = df.loc[check_date, 'Close']
                prices[ticker] = close_price
                print(f"  {ticker}: ${close_price:.6f}")

    # Check if all prices are identical
    if prices:
        unique_prices = set(prices.values())
        if len(unique_prices) == 1:
            print(f"\n  *** ALL TICKERS HAVE IDENTICAL PRICE: This confirms data duplication! ***")
        else:
            print(f"\n  Tickers have different prices ({len(unique_prices)} unique values)")


if __name__ == "__main__":
    main()
