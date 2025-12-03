"""
Test script for FundamentalEngine - verify FMP API integration.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from src.fundamental_engine import FundamentalEngine
import pandas as pd

def main():
    print("=" * 80)
    print(" FUNDAMENTAL ENGINE TEST")
    print("=" * 80)
    print()
    
    try:
        # Initialize engine
        print("1. Initializing FundamentalEngine...")
        engine = FundamentalEngine()
        print("   ✓ Engine initialized successfully")
        print(f"   API Key: {engine.api_key[:10]}..." if engine.api_key else "   API Key: NOT SET")
        print(f"   Cache dir: {engine.fundamentals_dir}")
        print()
        
        # Test with AAPL
        test_ticker = 'AAPL'
        print(f"2. Fetching fundamental data for {test_ticker}...")
        
        # Fetch income statement
        print(f"   Fetching income statement...")
        income_df = engine.fetch_income_statement(test_ticker)
        if income_df is not None:
            print(f"   ✓ Income statement: {len(income_df)} records")
            print(f"     Columns: {list(income_df.columns[:10])} ...")
        else:
            print(f"   ✗ Failed to fetch income statement")
            return
        
        # Fetch balance sheet
        print(f"   Fetching balance sheet...")
        balance_df = engine.fetch_balance_sheet(test_ticker)
        if balance_df is not None:
            print(f"   ✓ Balance sheet: {len(balance_df)} records")
            print(f"     Columns: {list(balance_df.columns[:10])} ...")
        else:
            print(f"   ✗ Failed to fetch balance sheet")
            return
        
        print()
        
        # Fetch combined
        print(f"3. Fetching combined fundamentals...")
        fund_df = engine.get_ticker_fundamentals(test_ticker, use_cache=False)
        if fund_df is not None:
            print(f"   ✓ Combined data: {len(fund_df)} records")
            print(f"   Columns: {len(fund_df.columns)}")
            print()
            
            # Show sample
            print("   Sample data:")
            display_cols = ['ticker', 'fiscal_date', 'filing_date', 'fiscal_period', 'statement_type']
            # Add some financial columns if they exist
            for col in ['revenue', 'netIncome', 'totalAssets', 'totalDebt']:
                if col in fund_df.columns:
                    display_cols.append(col)
            
            print(fund_df[display_cols].head(10).to_string())
            print()
            
            # Verify cache was created
            cache_file = engine.fundamentals_dir / f"{test_ticker}.parquet"
            if cache_file.exists():
                size_kb = cache_file.stat().st_size / 1024
                print(f"   ✓ Cache file created: {cache_file}")
                print(f"   File size: {size_kb:.2f} KB")
            else:
                print(f"   ✗ Cache file not created")
            
            print()
            
        else:
            print(f"   ✗ Failed to fetch combined data")
            return
        
        # Test cache stats
        print("4. Cache statistics:")
        stats = engine.get_cache_stats()
        print(f"   Total tickers: {stats['total_tickers']}")
        print(f"   Total size: {stats['total_size_mb']:.2f} MB")
        if stats['total_tickers'] > 0:
            print(f"   Avg size: {stats['avg_size_kb']:.2f} KB/ticker")
        print()
        
        print("=" * 80)
        print(" ✅ ALL TESTS PASSED")
        print("=" * 80)
        print()
        print("Next steps:")
        print("  1. Run: python build_fundamentals.py --tickers AAPL MSFT GOOGL")
        print("  2. Run: python build_fundamentals.py (fetch all tickers)")
        print()
        
    except ValueError as e:
        print(f"\n❌ Configuration Error: {e}")
        print("\nPlease set FMP_API_KEY in your .env file")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Test Failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
