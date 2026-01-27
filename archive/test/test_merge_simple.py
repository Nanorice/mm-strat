"""Quick fundamental merge test"""
from src.fundamental_merger import FundamentalMerger
from src.data_engine import DataRepository

repo = DataRepository()
df = repo.get_ticker_data('AAPL')
print(f'Original: {df.shape[0]} rows, {df.shape[1]} columns')

merger = FundamentalMerger()
df_merged = merger.merge_ticker_data('AAPL', df)
print(f'Merged: {df_merged.shape[0]} rows, {df_merged.shape[1]} columns')
print(f'Added: {df_merged.shape[1] - df.shape[1]} columns')

if 'revenue' in df_merged.columns:
    rev_count = df_merged['revenue'].notna().sum()
    print(f'\nRevenue: {rev_count}/{len(df_merged)} populated')
    if rev_count > 0:
        print('\nFirst non-null revenue:')
        print(df_merged[df_merged['revenue'].notna()][['revenue', 'grossProfit']].head(3))
    else:
        print('ERROR: Revenue column exists but ALL NaN!')
        # Check if filing_date_matched has any values
        if 'filing_date_matched' in df_merged.columns:
            matched = df_merged['filing_date_matched'].notna().sum()
            print(f'filing_date_matched: {matched}/{len(df_merged)} populated')
            if matched == 0:
                print('ISSUE: No filing dates matched during merge!')
else:
    print('ERROR: No revenue column in merged data!')
