"""
View Fundamental Data - Interactive viewer for cached fundamental data.
"""

import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

import pandas as pd
from src.fundamental_engine import FundamentalEngine
import config


def format_large_number(value):
    """Format large numbers in billions/millions."""
    if pd.isna(value):
        return "N/A"
    if abs(value) >= 1e9:
        return f"${value/1e9:.2f}B"
    elif abs(value) >= 1e6:
        return f"${value/1e6:.2f}M"
    else:
        return f"${value:,.0f}"


def display_ticker_summary(ticker: str, df: pd.DataFrame):
    """Display summary of fundamental data for a ticker."""
    print("\n" + "=" * 80)
    print(f" {ticker} - Fundamental Data Summary")
    print("=" * 80)
    
    # Overall stats
    print(f"\nTotal records: {len(df)}")
    print(f"Date range: {df['fiscal_date'].min().strftime('%Y-%m-%d')} to {df['fiscal_date'].max().strftime('%Y-%m-%d')}")
    
    income_count = len(df[df['statement_type'] == 'income'])
    balance_count = len(df[df['statement_type'] == 'balance_sheet'])
    print(f"Income statements: {income_count}")
    print(f"Balance sheets: {balance_count}")
    
    return df


def display_income_statement(ticker: str, df: pd.DataFrame, limit: int = 5):
    """Display income statement data."""
    income_df = df[df['statement_type'] == 'income'].copy()
    
    if income_df.empty:
        print("\nNo income statement data available")
        return
    
    # Sort by date (most recent first)
    income_df = income_df.sort_values('fiscal_date', ascending=False)
    
    print("\n" + "-" * 80)
    print(f" Income Statement (Last {min(limit, len(income_df))} Periods)")
    print("-" * 80)
    
    # Select key columns
    display_cols = ['fiscal_date', 'filing_date', 'fiscal_period']
    financial_cols = []
    
    # Add available financial columns
    for col in ['revenue', 'costOfRevenue', 'grossProfit', 'operatingIncome', 
                'netIncome', 'eps', 'ebitda']:
        if col in income_df.columns:
            financial_cols.append(col)
    
    # Display data
    for idx, row in income_df.head(limit).iterrows():
        print(f"\n📅 Period: {row['fiscal_period']} ending {row['fiscal_date'].strftime('%Y-%m-%d')}")
        print(f"   Filed: {row['filing_date'].strftime('%Y-%m-%d')}")
        print()
        
        if 'revenue' in row:
            print(f"   Revenue:          {format_large_number(row.get('revenue', None))}")
        if 'costOfRevenue' in row:
            print(f"   Cost of Revenue:  {format_large_number(row.get('costOfRevenue', None))}")
        if 'grossProfit' in row:
            print(f"   Gross Profit:     {format_large_number(row.get('grossProfit', None))}")
            if 'revenue' in row and row['revenue'] > 0:
                margin = (row.get('grossProfit', 0) / row['revenue']) * 100
                print(f"   Gross Margin:     {margin:.2f}%")
        if 'operatingIncome' in row:
            print(f"   Operating Income: {format_large_number(row.get('operatingIncome', None))}")
        if 'netIncome' in row:
            print(f"   Net Income:       {format_large_number(row.get('netIncome', None))}")
        if 'eps' in row:
            print(f"   EPS:              ${row.get('eps', 0):.2f}")
        if 'ebitda' in row:
            print(f"   EBITDA:           {format_large_number(row.get('ebitda', None))}")


def display_balance_sheet(ticker: str, df: pd.DataFrame, limit: int = 5):
    """Display balance sheet data."""
    balance_df = df[df['statement_type'] == 'balance_sheet'].copy()
    
    if balance_df.empty:
        print("\nNo balance sheet data available")
        return
    
    # Sort by date (most recent first)
    balance_df = balance_df.sort_values('fiscal_date', ascending=False)
    
    print("\n" + "-" * 80)
    print(f" Balance Sheet (Last {min(limit, len(balance_df))} Periods)")
    print("-" * 80)
    
    # Display data
    for idx, row in balance_df.head(limit).iterrows():
        print(f"\n📅 Period: {row['fiscal_period']} ending {row['fiscal_date'].strftime('%Y-%m-%d')}")
        print(f"   Filed: {row['filing_date'].strftime('%Y-%m-%d')}")
        print()
        
        if 'totalAssets' in row:
            print(f"   Total Assets:           {format_large_number(row.get('totalAssets', None))}")
        if 'totalLiabilities' in row:
            print(f"   Total Liabilities:      {format_large_number(row.get('totalLiabilities', None))}")
        if 'totalStockholdersEquity' in row:
            equity = row.get('totalStockholdersEquity', None)
            print(f"   Shareholder Equity:     {format_large_number(equity)}")
        if 'cashAndCashEquivalents' in row:
            print(f"   Cash:                   {format_large_number(row.get('cashAndCashEquivalents', None))}")
        if 'totalDebt' in row:
            debt = row.get('totalDebt', None)
            print(f"   Total Debt:             {format_large_number(debt)}")
            # Debt to equity ratio
            equity = row.get('totalStockholdersEquity', None)
            if equity and debt and equity > 0:
                de_ratio = debt / equity
                print(f"   Debt/Equity:            {de_ratio:.2f}x")
        if 'totalCurrentAssets' in row:
            print(f"   Current Assets:         {format_large_number(row.get('totalCurrentAssets', None))}")
        if 'totalCurrentLiabilities' in row:
            current_liab = row.get('totalCurrentLiabilities', None)
            print(f"   Current Liabilities:    {format_large_number(current_liab)}")
            # Current ratio
            current_assets = row.get('totalCurrentAssets', None)
            if current_assets and current_liab and current_liab > 0:
                current_ratio = current_assets / current_liab
                print(f"   Current Ratio:          {current_ratio:.2f}x")


def display_raw_data(ticker: str, df: pd.DataFrame, statement_type: str = None):
    """Display raw DataFrame for inspection."""
    if statement_type:
        df = df[df['statement_type'] == statement_type]
        print(f"\n{ticker} - {statement_type.upper()} RAW DATA")
    else:
        print(f"\n{ticker} - ALL RAW DATA")
    
    print("=" * 80)
    print(f"Shape: {df.shape}")
    print(f"\nColumns ({len(df.columns)}):")
    print(df.columns.tolist())
    print("\nFirst 10 rows:")
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', None)
    print(df.head(10))


def main():
    parser = argparse.ArgumentParser(
        description='View cached fundamental data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all cached tickers
  python view_fundamentals.py --list
  
  # View AAPL fundamentals (formatted)
  python view_fundamentals.py AAPL
  
  # View last 10 periods
  python view_fundamentals.py AAPL --periods 10
  
  # View only income statement
  python view_fundamentals.py AAPL --income
  
  # View only balance sheet
  python view_fundamentals.py AAPL --balance
  
  # View raw data (all columns)
  python view_fundamentals.py AAPL --raw
        """
    )
    
    parser.add_argument(
        'ticker',
        nargs='?',
        help='Ticker symbol to view'
    )
    
    parser.add_argument(
        '--list',
        action='store_true',
        help='List all cached tickers'
    )
    
    parser.add_argument(
        '--periods',
        type=int,
        default=5,
        help='Number of periods to display (default: 5)'
    )
    
    parser.add_argument(
        '--income',
        action='store_true',
        help='Show only income statement'
    )
    
    parser.add_argument(
        '--balance',
        action='store_true',
        help='Show only balance sheet'
    )
    
    parser.add_argument(
        '--raw',
        action='store_true',
        help='Show raw data (all columns)'
    )
    
    args = parser.parse_args()
    
    # Initialize engine
    engine = FundamentalEngine()
    
    # List cached tickers
    if args.list:
        tickers = engine.get_available_tickers()
        stats = engine.get_cache_stats()
        
        print("=" * 80)
        print(" CACHED FUNDAMENTAL DATA")
        print("=" * 80)
        print(f"\nTotal tickers: {len(tickers)}")
        print(f"Total cache size: {stats['total_size_mb']:.2f} MB")
        print(f"Average size: {stats['avg_size_kb']:.2f} KB/ticker")
        if stats['oldest_cache']:
            print(f"Oldest cache: {stats['oldest_cache'].strftime('%Y-%m-%d %H:%M')}")
            print(f"Newest cache: {stats['newest_cache'].strftime('%Y-%m-%d %H:%M')}")
        
        print(f"\nAvailable tickers ({len(tickers)}):")
        # Print in columns
        cols = 8
        for i in range(0, len(tickers), cols):
            row = tickers[i:i+cols]
            print("  " + "  ".join(f"{t:6}" for t in row))
        
        print("\nUse 'python view_fundamentals.py TICKER' to view specific ticker")
        return
    
    # Require ticker if not listing
    if not args.ticker:
        print("Error: Please specify a ticker or use --list")
        print("Usage: python view_fundamentals.py TICKER")
        print("   or: python view_fundamentals.py --list")
        sys.exit(1)
    
    ticker = args.ticker.upper()
    
    # Load data
    df = engine.get_ticker_fundamentals(ticker)
    
    if df is None or df.empty:
        print(f"❌ No fundamental data found for {ticker}")
        print("\nAvailable tickers:")
        tickers = engine.get_available_tickers()
        print(", ".join(tickers[:20]))
        if len(tickers) > 20:
            print(f"... and {len(tickers) - 20} more")
        sys.exit(1)
    
    # Display based on flags
    if args.raw:
        statement_type = None
        if args.income:
            statement_type = 'income'
        elif args.balance:
            statement_type = 'balance_sheet'
        display_raw_data(ticker, df, statement_type)
    else:
        display_ticker_summary(ticker, df)
        
        if not args.balance:
            display_income_statement(ticker, df, args.periods)
        
        if not args.income:
            display_balance_sheet(ticker, df, args.periods)
    
    print("\n" + "=" * 80)
    print(f"💡 Tip: Use --raw to see all {len(df.columns)} columns")
    print("=" * 80)
    print()


if __name__ == "__main__":
    main()
