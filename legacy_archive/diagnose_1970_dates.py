"""
Diagnostic Script: Investigate 1970 Date Issues in Dataset A Pipeline

This script identifies the source of 1970 dates that appear when merging
price data with fundamentals. It checks:
1. Raw price data integrity
2. Fundamental data date columns
3. Date conversion/merging logic
"""

import pandas as pd
import sys
from pathlib import Path
from datetime import datetime
import logging

# Add src to path
sys.path.append(str(Path(__file__).parent))

import config
from src.data_engine import DataRepository
from src.fundamental_merger import FundamentalMerger

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def check_price_data_dates(ticker: str, data_repo: DataRepository):
    """Check if price data has any 1970 dates."""
    logger.info(f"\n{'='*80}")
    logger.info(f"CHECKING PRICE DATA: {ticker}")
    logger.info(f"{'='*80}")

    df = data_repo.get_ticker_data(ticker)

    if df is None or df.empty:
        logger.warning(f"No price data found for {ticker}")
        return

    # Check index
    if isinstance(df.index, pd.DatetimeIndex):
        date_col = df.index
        logger.info(f"Date is in INDEX")
    elif 'date' in df.columns:
        date_col = pd.to_datetime(df['date'], errors='coerce')
        logger.info(f"Date is in COLUMN 'date'")
    else:
        logger.warning(f"No date column or index found!")
        return

    # Check for 1970 dates
    dates_1970 = (date_col.year == 1970).sum() if hasattr(date_col, 'year') else 0

    logger.info(f"Total rows: {len(df)}")
    logger.info(f"Date range: {date_col.min()} to {date_col.max()}")
    logger.info(f"1970 dates in price data: {dates_1970}")

    if dates_1970 > 0:
        logger.error(f"⚠️  FOUND {dates_1970} rows with 1970 dates in PRICE DATA!")
        logger.error(f"Sample 1970 dates:")
        print(df[date_col.year == 1970].head(10))
    else:
        logger.info(f"✓ No 1970 dates in price data")

    return dates_1970


def check_fundamental_data_dates(ticker: str, fundamental_merger: FundamentalMerger):
    """Check if fundamental data has any 1970 dates."""
    logger.info(f"\n{'='*80}")
    logger.info(f"CHECKING FUNDAMENTAL DATA: {ticker}")
    logger.info(f"{'='*80}")

    try:
        # Get fundamental data directly from cache
        fundamental_data = fundamental_merger.get_ticker_fundamentals(ticker)

        if fundamental_data is None or fundamental_data.empty:
            logger.warning(f"No fundamental data found for {ticker}")
            return

        logger.info(f"Total fundamental rows: {len(fundamental_data)}")
        logger.info(f"Columns: {list(fundamental_data.columns)}")

        # Check all date-like columns
        date_columns = ['date', 'fiscal_date', 'filing_date', 'filing_date_matched',
                       'accepted_date', 'period_ending']

        total_1970 = 0
        for col in date_columns:
            if col in fundamental_data.columns:
                # Convert to datetime
                date_series = pd.to_datetime(fundamental_data[col], errors='coerce')
                dates_1970 = (date_series.dt.year == 1970).sum()

                logger.info(f"\n  Column '{col}':")
                logger.info(f"    Data type: {fundamental_data[col].dtype}")
                logger.info(f"    Non-null count: {fundamental_data[col].notna().sum()}")
                logger.info(f"    1970 dates: {dates_1970}")

                if dates_1970 > 0:
                    total_1970 += dates_1970
                    logger.error(f"    ⚠️  FOUND {dates_1970} rows with 1970 dates!")
                    logger.error(f"    Sample values:")
                    print(fundamental_data[date_series.dt.year == 1970][[col]].head(5))

                    # Show original values before conversion
                    mask = date_series.dt.year == 1970
                    logger.error(f"    Original values (before datetime conversion):")
                    print(fundamental_data.loc[mask, col].head(5))

        if total_1970 > 0:
            logger.error(f"\n⚠️  TOTAL 1970 dates in fundamental data: {total_1970}")
        else:
            logger.info(f"\n✓ No 1970 dates in fundamental data")

        return total_1970

    except Exception as e:
        logger.error(f"Error checking fundamental data: {e}", exc_info=True)
        return None


def check_merged_data_dates(ticker: str, data_repo: DataRepository, fundamental_merger: FundamentalMerger):
    """Check if merged data produces 1970 dates."""
    logger.info(f"\n{'='*80}")
    logger.info(f"CHECKING MERGED DATA: {ticker}")
    logger.info(f"{'='*80}")

    try:
        # Get price data
        df = data_repo.get_ticker_data(ticker)
        if df is None or df.empty:
            logger.warning(f"No price data for {ticker}")
            return

        # Ensure date is a column
        if 'date' not in df.columns and isinstance(df.index, pd.DatetimeIndex):
            df['date'] = df.index

        df['date'] = pd.to_datetime(df['date'], errors='coerce')

        logger.info(f"Price data before merge:")
        logger.info(f"  Rows: {len(df)}")
        logger.info(f"  Date range: {df['date'].min()} to {df['date'].max()}")
        logger.info(f"  1970 dates: {(df['date'].dt.year == 1970).sum()}")

        # Merge with fundamentals
        df_merged = fundamental_merger.merge_ticker_data(ticker, df.copy())

        logger.info(f"\nMerged data after merge:")
        logger.info(f"  Rows: {len(df_merged)}")
        logger.info(f"  Columns added: {len(df_merged.columns) - len(df.columns)}")

        # Check main date column
        if 'date' in df_merged.columns:
            df_merged['date'] = pd.to_datetime(df_merged['date'], errors='coerce')
            dates_1970_main = (df_merged['date'].dt.year == 1970).sum()
            logger.info(f"  1970 dates in 'date' column: {dates_1970_main}")

            if dates_1970_main > 0:
                logger.error(f"  ⚠️  'date' column has {dates_1970_main} rows with 1970 dates!")
                logger.error(f"  Sample rows:")
                print(df_merged[df_merged['date'].dt.year == 1970][['date', 'ticker', 'Close']].head(10))

        # Check all datetime columns
        datetime_cols = ['fiscal_date', 'filing_date_matched', 'accepted_date']
        total_1970 = 0
        for col in datetime_cols:
            if col in df_merged.columns:
                col_data = pd.to_datetime(df_merged[col], errors='coerce')
                dates_1970 = (col_data.dt.year == 1970).sum()

                logger.info(f"  Column '{col}': {dates_1970} rows with 1970 dates")

                if dates_1970 > 0:
                    total_1970 += dates_1970
                    logger.error(f"    ⚠️  Sample values:")
                    print(df_merged[col_data.dt.year == 1970][[col]].head(5))

        if total_1970 > 0:
            logger.error(f"\n⚠️  TOTAL 1970 dates in merged data: {total_1970}")
        else:
            logger.info(f"\n✓ No 1970 dates in merged data")

        return total_1970

    except Exception as e:
        logger.error(f"Error checking merged data: {e}", exc_info=True)
        return None


def main():
    """Run diagnostic checks."""
    print("="*80)
    print(" 1970 DATE DIAGNOSTIC TOOL")
    print("="*80)

    # Test with a ticker that shows the warning
    test_ticker = "NMRK"  # From your warning message

    logger.info(f"\nTesting with ticker: {test_ticker}")
    logger.info(f"This ticker showed '254 rows with 1970 dates' in the warning\n")

    # Initialize components
    data_repo = DataRepository()
    fundamental_merger = FundamentalMerger(force_cache_only=True)

    # Run checks
    price_1970 = check_price_data_dates(test_ticker, data_repo)
    fund_1970 = check_fundamental_data_dates(test_ticker, fundamental_merger)
    merged_1970 = check_merged_data_dates(test_ticker, data_repo, fundamental_merger)

    # Summary
    print("\n" + "="*80)
    print(" DIAGNOSTIC SUMMARY")
    print("="*80)
    print(f"Ticker: {test_ticker}")
    print(f"1970 dates in price data: {price_1970 if price_1970 is not None else 'ERROR'}")
    print(f"1970 dates in fundamental data: {fund_1970 if fund_1970 is not None else 'ERROR'}")
    print(f"1970 dates in merged data: {merged_1970 if merged_1970 is not None else 'ERROR'}")
    print("="*80)

    # Test with a few more tickers
    print("\n\nTesting additional tickers to confirm pattern...")
    additional_tickers = ["AAPL", "MSFT", "TSLA"]

    for ticker in additional_tickers:
        try:
            logger.info(f"\n--- Quick check: {ticker} ---")
            df = data_repo.get_ticker_data(ticker)
            if df is not None:
                df_merged = fundamental_merger.merge_ticker_data(ticker, df.copy())
                if 'date' in df_merged.columns:
                    df_merged['date'] = pd.to_datetime(df_merged['date'], errors='coerce')
                    dates_1970 = (df_merged['date'].dt.year == 1970).sum()
                    if dates_1970 > 0:
                        logger.error(f"  ⚠️  {ticker}: {dates_1970} rows with 1970 dates")
                    else:
                        logger.info(f"  ✓ {ticker}: No 1970 dates")
        except Exception as e:
            logger.error(f"  Error with {ticker}: {e}")


if __name__ == "__main__":
    main()
