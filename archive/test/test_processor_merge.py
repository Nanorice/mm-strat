"""Test the fundamental processor merge logic"""
import pandas as pd
from src.fundamental_processor import FundamentalProcessor

# Load raw AAPL fundamental data
df = pd.read_parquet('data/fundamentals/AAPL.parquet')
print(f'Raw data: {len(df)} rows')
print(f'By type: {df["statement_type"].value_counts().to_dict()}')

# Process
processor = FundamentalProcessor()
processed = processor.process_ticker_fundamentals('AAPL', df)

print(f'\nProcessed: {len(processed)} rows')
print('\nFirst 3 rows:')
print(processed[['fiscal_date', 'filing_date', 'revenue', 'totalAssets']].head(3))

# Check if revenue and totalAssets are in same rows
print('\nRevenue populated:', processed['revenue'].notna().sum())
print('TotalAssets populated:', processed['totalAssets'].notna().sum())
print('\nBoth populated in same row:', 
      ((processed['revenue'].notna()) & (processed['totalAssets'].notna())).sum())
