"""
Test FMP Stock Screener Integration

This script tests the new FMP stock screener functionality.
It compares the universe sizes between S&P 500 and FMP screener.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent))

from src.data_engine import DataRepository
import config


def main():
    print("=" * 80)
    print("FMP Stock Screener Integration Test")
    print("=" * 80)
    print()
    
    # Initialize data repository
    repo = DataRepository()
    
    # Test 1: FMP Screener Universe
    print("Test 1: Fetching universe from FMP Stock Screener")
    print("-" * 80)
    print(f"Screener Filters:")
    print(f"  Market Cap: >= ${config.FMP_SCREENER_PARAMS['marketCapMoreThan']:,}")
    print(f"  Price: >= ${config.FMP_SCREENER_PARAMS['priceMoreThan']}")
    print(f"  Volume: >= {config.FMP_SCREENER_PARAMS['volumeMoreThan']:,} shares/day")
    print(f"  Exchanges: {config.FMP_SCREENER_PARAMS['exchange']}")
    print(f"  Country: {config.FMP_SCREENER_PARAMS['country']}")
    print(f"  Active Trading: {config.FMP_SCREENER_PARAMS['isActivelyTrading']}")
    print(f"  Exclude ETFs: {config.FMP_SCREENER_PARAMS['isEtf']}")
    print()
    
    screener_tickers = repo.get_screener_universe()
    
    if screener_tickers:
        print(f"✓ Successfully fetched {len(screener_tickers)} tickers from FMP screener")
        print(f"\nSample tickers (first 20):")
        for ticker in sorted(screener_tickers)[:20]:
            print(f"  {ticker}")
    else:
        print("✗ Failed to fetch tickers from FMP screener")
    print()
    
    # Test 2: S&P 500 Universe (SSGA)
    print("Test 2: Fetching universe from S&P 500 (SSGA)")
    print("-" * 80)
    
    sp500_tickers = repo.update_universe(source='SSGA')
    
    if sp500_tickers:
        print(f"✓ Successfully fetched {len(sp500_tickers)} tickers from S&P 500")
        print(f"\nSample tickers (first 20):")
        for ticker in sorted(sp500_tickers)[:20]:
            print(f"  {ticker}")
    else:
        print("✗ Failed to fetch tickers from S&P 500")
    print()
    
    # Test 3: Default Universe (from config)
    print("Test 3: Fetching universe using config default")
    print("-" * 80)
    print(f"Config default source: {config.UNIVERSE_SOURCE}")
    print()
    
    default_tickers = repo.update_universe()
    
    if default_tickers:
        print(f"✓ Successfully fetched {len(default_tickers)} tickers using default source")
    else:
        print("✗ Failed to fetch tickers using default source")
    print()
    
    # Summary
    print("=" * 80)
    print("Summary")
    print("=" * 80)
    print(f"FMP Screener: {len(screener_tickers) if screener_tickers else 0} tickers")
    print(f"S&P 500:      {len(sp500_tickers) if sp500_tickers else 0} tickers")
    print(f"Default:      {len(default_tickers) if default_tickers else 0} tickers")
    print()
    
    if screener_tickers and sp500_tickers:
        expansion_factor = len(screener_tickers) / len(sp500_tickers)
        print(f"Universe expansion: {expansion_factor:.1f}x larger than S&P 500")
        
        # Find tickers in screener but not in S&P 500
        screener_only = set(screener_tickers) - set(sp500_tickers)
        sp500_only = set(sp500_tickers) - set(screener_tickers)
        both = set(screener_tickers) & set(sp500_tickers)
        
        print()
        print(f"Overlap analysis:")
        print(f"  In both:         {len(both)} tickers")
        print(f"  Screener only:   {len(screener_only)} tickers")
        print(f"  S&P 500 only:    {len(sp500_only)} tickers")
        
        if screener_only:
            print(f"\nExample tickers in screener but not S&P 500 (sample of 10):")
            for ticker in sorted(screener_only)[:10]:
                print(f"  {ticker}")
    
    print()
    print("=" * 80)
    print("Test Complete")
    print("=" * 80)


if __name__ == "__main__":
    main()
