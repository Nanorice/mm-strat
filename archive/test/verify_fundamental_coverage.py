"""Verify fundamental data coverage for 2021-2025"""
import pandas as pd

df = pd.read_parquet('data/fundamentals/AAPL.parquet')

# Filter to 2021-2025 period
df_period = df[(df['filing_date'] >= '2021-01-01') & (df['filing_date'] <= '2025-12-31')]

print('=' * 80)
print('AAPL FUNDAMENTAL DATA - 2021-2025 PERIOD')
print('=' * 80)
print(f'\nTotal quarters in 2021-2025: {len(df_period)}')
print(f'\nDate range:')
print(f'  Fiscal: {df_period["fiscal_date"].min()} to {df_period["fiscal_date"].max()}')
print(f'  Filing: {df_period["filing_date"].min()} to {df_period["filing_date"].max()}')

print(f'\n2021-2025 Quarterly Data:')
print(df_period[['fiscal_date', 'filing_date', 'revenue', 'grossProfit', 'netIncome']].sort_values('filing_date'))

print(f'\nData completeness:')
print(df_period[['revenue', 'grossProfit', 'netIncome', 'totalAssets']].notna().sum())

# Check income statement vs balance sheet
income_rows = df_period[df_period['statement_type'] == 'income']
balance_rows = df_period[df_period['statement_type'] == 'balance_sheet']
print(f'\nStatement breakdown:')
print(f'  Income statements: {len(income_rows)}')
print(f'  Balance sheets: {len(balance_rows)}')

print('\n' + '=' * 80)
print('CONCLUSION')
print('=' * 80)
if len(df_period) >= 16:  # ~4 quarters per year × 4 years
    print('✅ Sufficient fundamental data for 2021-2025 training period')
    print(f'✅ {len(df_period)} quarters available')
else:
    print(f'⚠️  Only {len(df_period)} quarters - may need more historical data')
