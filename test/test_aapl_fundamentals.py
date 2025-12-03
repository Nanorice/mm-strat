"""Test AAPL fundamental data fetch"""
from src.fundamental_engine import FundamentalEngine

fe = FundamentalEngine()
print('Fetching AAPL fundamentals with force=True...')
df = fe.get_ticker_fundamentals('AAPL', use_cache=False)

if df is not None:
    print(f'\nShape: {df.shape[0]} rows, {df.shape[1]} columns')
    print(f'\nDate range:')
    print(f'Filing dates: {df["filing_date"].min()} to {df["filing_date"].max()}')
    print(f'Fiscal dates: {df["fiscal_date"].min()} to {df["fiscal_date"].max()}')
    print(f'\nFirst 5 fiscal periods (oldest):')
    print(df[["fiscal_date", "filing_date", "revenue"]].tail(5))
    print(f'\nLast 5 fiscal periods (newest):')
    print(df[["fiscal_date", "filing_date", "revenue"]].head(5))
    
    # Check date coverage
    import pandas as pd
    filing_years = df['filing_date'].dt.year.unique()
    print(f'\nFiling years covered: {sorted(filing_years)}')
    print(f'Covers 2021-2025? {all(y in filing_years for y in [2021, 2022, 2023, 2024, 2025])}')
else:
    print('Failed to fetch data!')
