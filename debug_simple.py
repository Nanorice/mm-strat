"""
Simplified debug - just check the critical issue
"""
import pandas as pd
from src.fundamental_merger import FundamentalMerger
from src.fundamental_engine import FundamentalEngine
from src.data_engine import DataRepository

# Load AAPL fundament data
fund_engine = FundamentalEngine()
fund_raw = fund_engine.get_ticker_fundamentals('AAPL')

print("AAPL raw fundamental data:")
print(f"  Rows: {len(fund_raw)}")
print(f"  EPS values (first 5): {fund_raw['eps'].head(5).tolist()}")
print(f"  Filing dates (first 5): {fund_raw['filing_date'].head(5).tolist()}")
print()

# Load price data
repo = DataRepository()
price_df = repo.get_ticker_data('AAPL')
test_price_df = price_df.loc['2024-01-01':'2024-03-31'].copy()

print("AAPL price data (Q1 2024):")
print(f"  Rows: {len(test_price_df)}")
print(f"  Date range: {test_price_df.index.min()} to {test_price_df.index.max()}")
print()

# Merge
merger = FundamentalMerger()
merged_df = merger.merge_ticker_data('AAPL', test_price_df)

print("Merged result:")
print(f"  Rows: {len(merged_df)}")
print(f"  EPS values (first 10): {merged_df['eps'].head(10).tolist() if 'eps' in merged_df.columns else 'N/A'}")
print(f"  Revenue values (first 10): {merged_df['revenue'].head(10).tolist() if 'revenue' in merged_df.columns else 'N/A'}")
print(f"  Filing dates (first 10): {merged_df['filing_date_matched'].dropna().head(10).tolist() if 'filing_date_matched' in merged_df.columns else 'N/A'}")
print()

# Check if all zeros
if 'eps' in merged_df.columns:
    all_zero = (merged_df['eps'] == 0.0).all()
    some_nonzero = (merged_df['eps'] != 0.0).any()
    print(f"EPS check:")
    print(f"  All zeros: {all_zero}")
    print(f"  Has non-zero: {some_nonzero}")
    if not some_nonzero:
        print("  ❌ PROBLEM: All EPS values are 0!")
