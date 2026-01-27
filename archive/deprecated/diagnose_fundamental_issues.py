"""
Diagnostic Script: Investigate Fundamental Data Issues

1. Check why filing_date is missing in fundamental data
2. Profile the fundamental merge performance bottleneck
"""

import pandas as pd
import sys
from pathlib import Path
import logging
import time

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


def check_raw_fundamental_data(ticker: str):
    """Check the raw fundamental data cached files for missing filing_date."""
    logger.info(f"\n{'='*80}")
    logger.info(f"CHECKING RAW FUNDAMENTAL DATA: {ticker}")
    logger.info(f"{'='*80}")

    # Check all fundamental data files
    fundamental_files = {
        'income': Path(f'data/fundamentals/{ticker}_income.parquet'),
        'balance': Path(f'data/fundamentals/{ticker}_balance.parquet'),
        'cashflow': Path(f'data/fundamentals/{ticker}_cashflow.parquet'),
        'ratios': Path(f'data/fundamentals/{ticker}_ratios.parquet'),
    }

    for file_type, file_path in fundamental_files.items():
        if file_path.exists():
            df = pd.read_parquet(file_path)
            logger.info(f"\n{file_type.upper()} Statement:")
            logger.info(f"  Total rows: {len(df)}")
            logger.info(f"  Columns: {list(df.columns)[:10]}...")

            # Check for filing_date
            if 'filing_date' in df.columns:
                null_count = df['filing_date'].isna().sum()
                logger.info(f"  filing_date: {len(df) - null_count}/{len(df)} non-null")

                if null_count > 0:
                    logger.warning(f"  ⚠️  {null_count} rows with NULL filing_date!")
                    logger.warning(f"  Sample rows with null filing_date:")
                    print(df[df['filing_date'].isna()][['date', 'acceptedDate', 'calendarYear']].head())

                    # Check if acceptedDate exists as alternative
                    if 'acceptedDate' in df.columns:
                        logger.info(f"  acceptedDate availability: {df['acceptedDate'].notna().sum()} rows")
            else:
                logger.error(f"  ❌ NO filing_date column found!")
                logger.info(f"  Available date columns: {[c for c in df.columns if 'date' in c.lower()]}")
        else:
            logger.info(f"\n{file_type.upper()}: File not found - {file_path}")


def profile_fundamental_merge(ticker: str):
    """Profile the performance of fundamental merge operation."""
    logger.info(f"\n{'='*80}")
    logger.info(f"PROFILING FUNDAMENTAL MERGE: {ticker}")
    logger.info(f"{'='*80}")

    # Get price data
    data_repo = DataRepository()
    df_price = data_repo.get_ticker_data(ticker)

    if df_price is None or df_price.empty:
        logger.error(f"No price data for {ticker}")
        return

    logger.info(f"Price data: {len(df_price)} rows")

    # Profile the merge
    fundamental_merger = FundamentalMerger(force_cache_only=True)

    start_time = time.time()
    df_merged = fundamental_merger.merge_ticker_data(ticker, df_price.copy())
    merge_time = time.time() - start_time

    logger.info(f"\nMerge Performance:")
    logger.info(f"  Time taken: {merge_time:.2f} seconds")
    logger.info(f"  Rows before: {len(df_price)}")
    logger.info(f"  Rows after: {len(df_merged)}")
    logger.info(f"  Columns added: {len(df_merged.columns) - len(df_price.columns)}")
    logger.info(f"  Throughput: {len(df_price) / merge_time:.0f} rows/sec")

    # Check if there's data duplication
    if len(df_merged) != len(df_price):
        logger.warning(f"  ⚠️  Row count changed! Possible duplicate rows created.")

    return merge_time


def check_fundamental_merger_internals():
    """Check what the FundamentalMerger is doing internally."""
    logger.info(f"\n{'='*80}")
    logger.info(f"CHECKING FUNDAMENTAL MERGER INTERNALS")
    logger.info(f"{'='*80}")

    from src.fundamental_merger import FundamentalMerger
    import inspect

    # Get the merge_ticker_data method source
    source = inspect.getsource(FundamentalMerger.merge_ticker_data)

    # Count number of operations
    operations = []
    for line in source.split('\n'):
        line = line.strip()
        if 'merge' in line.lower() and not line.startswith('#'):
            operations.append(line)
        elif 'join' in line.lower() and not line.startswith('#'):
            operations.append(line)
        elif 'concat' in line.lower() and not line.startswith('#'):
            operations.append(line)

    logger.info(f"Found {len(operations)} merge/join/concat operations:")
    for i, op in enumerate(operations, 1):
        logger.info(f"  {i}. {op[:80]}...")


def main():
    """Run diagnostics."""
    print("="*80)
    print(" FUNDAMENTAL DATA DIAGNOSTIC TOOL")
    print("="*80)

    # Test with a ticker that shows the warning
    test_ticker = "BDJ"  # From your warning message

    logger.info(f"\nTesting with ticker: {test_ticker}")

    # Check 1: Raw data quality
    check_raw_fundamental_data(test_ticker)

    # Check 2: Merge performance
    merge_time = profile_fundamental_merge(test_ticker)

    # Check 3: What is the merger doing?
    check_fundamental_merger_internals()

    # Test with multiple tickers to see pattern
    print("\n" + "="*80)
    print(" PERFORMANCE TEST: Multiple Tickers")
    print("="*80)

    test_tickers = ["AAPL", "MSFT", "NMRK", "BDJ"]
    total_time = 0

    for ticker in test_tickers:
        try:
            data_repo = DataRepository()
            df_price = data_repo.get_ticker_data(ticker)

            if df_price is not None and not df_price.empty:
                fundamental_merger = FundamentalMerger(force_cache_only=True)

                start = time.time()
                df_merged = fundamental_merger.merge_ticker_data(ticker, df_price.copy())
                elapsed = time.time() - start
                total_time += elapsed

                logger.info(f"{ticker}: {elapsed:.2f}s for {len(df_price)} rows ({len(df_price)/elapsed:.0f} rows/sec)")
        except Exception as e:
            logger.error(f"{ticker}: Error - {e}")

    avg_time = total_time / len(test_tickers)
    logger.info(f"\nAverage merge time: {avg_time:.2f}s per ticker")
    logger.info(f"Estimated time for 1730 tickers: {avg_time * 1730 / 60:.1f} minutes")


if __name__ == "__main__":
    main()
