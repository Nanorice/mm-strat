"""
Build Dataset A - Daily Feature Snapshots for ML Training

Generates time-series of technical indicators and alpha factors for all tickers.
Each row represents features available for a specific ticker on a specific date.

Performance Note:
- Use --skip-updates flag when local cache is already up-to-date (e.g., after running daily scanner)
- This skips price and fundamental data updates, significantly reducing build time
- Data updates should be handled separately via scanner or dedicated update scripts
"""

import pandas as pd
import numpy as np
import argparse
import sys
from pathlib import Path
from datetime import datetime
import logging
from tqdm import tqdm
from typing import Optional
import time

# Add src to path
sys.path.append(str(Path(__file__).parent))

import config
from src.data_engine import DataRepository
from src.features import FeatureEngineer
from src.temporal_validator import TemporalValidator

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _process_ticker_for_dataset_a(
    ticker: str,
    df: pd.DataFrame,
    mode: str,
    benchmark_data: Optional[pd.Series] = None,
    include_fundamentals: bool = False,
    skip_data_updates: bool = True
) -> pd.DataFrame:
    """
    Process a single ticker - calculate features and prepare records.

    This function is designed to be pickle-safe for multiprocessing.
    It creates its own FeatureEngine and FundamentalMerger instances
    instead of receiving them as parameters (which would fail pickling).

    Args:
        ticker: Stock symbol
        df: Price dataframe
        mode: 'lightweight' or 'full'
        benchmark_data: Benchmark series for RS calculation
        include_fundamentals: Whether to include fundamental data
        skip_data_updates: Skip data cache updates

    Returns:
        DataFrame with features for this ticker
    """
    try:
        # Create fresh instances (pickle-safe)
        # Suppress initialization logs in worker processes to reduce noise
        import logging
        worker_logger = logging.getLogger('src.features')
        original_level = worker_logger.level
        worker_logger.setLevel(logging.WARNING)

        feature_engine = FeatureEngineer(benchmark_data=benchmark_data)

        worker_logger.setLevel(original_level)

        # Calculate lightweight features
        df_features = feature_engine.calculate_lightweight_features(df)

        # Calculate heavyweight features if requested
        if mode == 'full':
            df_features = feature_engine.calculate_heavyweight_features(df_features, ticker)

        # Merge fundamental data if requested
        if include_fundamentals:
            from src.fundamental_merger import FundamentalMerger
            fundamental_merger = FundamentalMerger(force_cache_only=skip_data_updates)
            df_features = fundamental_merger.merge_ticker_data(ticker, df_features)
        
        # OPTIMIZATION: Instead of looping through dates, just add ticker column
        # The dataframe already has all the dates as index
        df_features['ticker'] = ticker

        # Handle date column carefully to avoid duplicates
        # Use lowercase 'date' to match standard convention across codebase
        if 'date' not in df_features.columns:
            # If date doesn't exist as column, create it from index
            df_features['date'] = pd.to_datetime(df_features.index)
        elif df_features.index.name == 'date' or isinstance(df_features.index, pd.DatetimeIndex):
            # If date exists as column AND index is date, reset index (drop it)
            df_features = df_features.reset_index(drop=True)

        # Ensure date column is datetime type
        if 'date' in df_features.columns:
            df_features['date'] = pd.to_datetime(df_features['date'])

        # Check for duplicate columns before proceeding
        duplicate_cols = df_features.columns[df_features.columns.duplicated()].tolist()
        if duplicate_cols:
            logger.error(f"{ticker}: Duplicate columns detected: {duplicate_cols}")
            # Remove duplicate columns (keep first occurrence)
            df_features = df_features.loc[:, ~df_features.columns.duplicated()]

        # Reorder columns: date, ticker, Close, Volume, then features
        cols = ['date', 'ticker', 'Close', 'Volume']
        feature_cols = [c for c in df_features.columns if c not in cols + ['Open', 'High', 'Low']]
        df_features = df_features[cols + feature_cols]

        return df_features
        
    except Exception as e:
        logger.warning(f"Failed to process {ticker}: {e}")
        return pd.DataFrame()


def _process_ticker_for_dataset_a_wrapper(args):
    """
    Wrapper to unpack arguments for imap_unordered.

    imap_unordered passes single arguments, but our function expects multiple.
    This wrapper unpacks the tuple into individual arguments.

    Args:
        args: Tuple of (ticker, df, mode, benchmark_data, include_fundamentals, skip_data_updates)

    Returns:
        DataFrame with features for this ticker
    """
    return _process_ticker_for_dataset_a(*args)


def detect_memory_mode() -> str:
    """
    Detect optimal memory mode based on available RAM.

    Returns:
        'high' for systems with 12GB+ available RAM (fast, in-memory processing)
        'low' for systems with <12GB available RAM (memory-efficient, disk-based processing)
    """
    try:
        import psutil
        available_gb = psutil.virtual_memory().available / (1024**3)

        if available_gb >= 12:
            return 'high'
        else:
            return 'low'
    except ImportError:
        # If psutil not available, default to low (safe mode)
        logger.warning("psutil not installed. Defaulting to 'low' memory mode. Install psutil for auto-detection.")
        return 'low'


def build_dataset_a(
    start_date: str,
    end_date: str,
    mode: str = 'lightweight',
    tickers: list = None,
    validate_temporal: bool = True,
    include_fundamentals: bool = False,
    include_cross_sectional: bool = False,
    n_jobs: int = 1,
    skip_data_updates: bool = True,
    memory_mode: str = 'auto'
) -> pd.DataFrame:
    """
    Build Dataset A - daily feature snapshots.

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        mode: 'lightweight' or 'full' (includes heavyweight alphas)
        tickers: Optional list of tickers (default: use universe)
        validate_temporal: If True, run temporal validation checks
        include_fundamentals: If True, merge fundamental data (growth, ratios, P/E, etc.)
        include_cross_sectional: If True, add cross-sectional features
        n_jobs: Number of parallel jobs (1 = sequential, -1 = all CPUs)
        skip_data_updates: If True, skip price and fundamental data cache updates (default: True)
                          For training datasets, data should already be up-to-date in cache.
                          Set to False only if you need to fetch fresh market data.
        memory_mode: Memory processing mode ('auto', 'low', 'high')
                    'auto' = detect based on available RAM
                    'low' = disk-based (8GB systems, slower but safe)
                    'high' = in-memory (16GB+ systems, faster)

    Returns:
        DataFrame with columns: date, ticker, Close, Volume, features...
    """
    # Resolve memory mode
    if memory_mode == 'auto':
        memory_mode = detect_memory_mode()
        logger.info(f"Auto-detected memory mode: {memory_mode}")
    else:
        logger.info(f"Memory mode: {memory_mode} (user-specified)")

    logger.info(f"Building Dataset A from {start_date} to {end_date}")
    logger.info(f"Mode: {mode}")
    logger.info(f"Parallel jobs: {n_jobs}")

    # Initialize components
    data_repo = DataRepository()

    # Parse end_date for validation
    end_date_timestamp = pd.Timestamp(end_date)

    # Load benchmark with end_date validation and force_cache_only
    benchmark_data = data_repo.get_benchmark_data(
        required_end_date=end_date_timestamp,
        force_cache_only=skip_data_updates
    )

    if benchmark_data is None:
        logger.error("Failed to load benchmark data!")
        return pd.DataFrame()
    
    feature_engine = FeatureEngineer(benchmark_data=benchmark_data)
    
    # Initialize fundamental merger if requested
    fundamental_merger = None
    if include_fundamentals:
        from src.fundamental_merger import FundamentalMerger
        fundamental_merger = FundamentalMerger(force_cache_only=skip_data_updates)
        logger.info("Fundamental enrichment enabled")
        if skip_data_updates:
            logger.info("Cache-only mode enabled for fundamentals (no API updates)")
    
    if validate_temporal:
        validator = TemporalValidator()
    
    # Get tickers to process
    if tickers is None:
        # Default: use full universe from FMP screener (~1730 tickers)
        logger.info("No tickers specified - loading full universe from FMP screener...")
        tickers = data_repo.update_universe()
        logger.info(f"Loaded {len(tickers)} tickers from FMP stock screener")
    
    logger.info(f"Processing {len(tickers)} tickers")

    # Update cache for all tickers (unless skip_data_updates is True)
    if skip_data_updates:
        logger.info("Skipping price data cache update (using existing cache)")
    else:
        logger.info("Updating price data cache...")
        data_repo.update_cache(tickers, force=False)

    # Load all ticker data
    logger.info("Loading ticker data...")
    ticker_data = data_repo.get_batch_data(
        tickers,
        show_progress=True,
        required_end_date=end_date_timestamp,
        force_cache_only=skip_data_updates
    )
    logger.info(f"Successfully loaded {len(ticker_data)}/{len(tickers)} tickers")

    # Report tickers that don't cover the end_date
    if len(ticker_data) < len(tickers):
        missing_tickers = set(tickers) - set(ticker_data.keys())
        logger.warning(f"\n{'='*80}")
        logger.warning(f"COVERAGE GAP REPORT")
        logger.warning(f"{'='*80}")
        logger.warning(f"{len(missing_tickers)} tickers don't cover end_date {end_date}:")

        # Show sample with actual date ranges
        sample_missing = sorted(list(missing_tickers))[:20]
        for ticker in sample_missing:
            cache_file = data_repo.price_dir / f"{ticker}.parquet"
            if cache_file.exists():
                try:
                    df = pd.read_parquet(cache_file)
                    cache_end = df.index.max()
                    logger.warning(f"  {ticker}: Latest data {cache_end.date()} (need {end_date})")
                except:
                    logger.warning(f"  {ticker}: Cache exists but unreadable")
            else:
                logger.warning(f"  {ticker}: No cached data")

        if len(missing_tickers) > 20:
            logger.warning(f"  ... and {len(missing_tickers) - 20} more")
        logger.warning(f"{'='*80}\n")

    # Generate business day range
    date_range = pd.bdate_range(start_date, end_date)
    logger.info(f"Processing {len(date_range)} trading days")
    
    # Process tickers (sequential or parallel)
    if n_jobs == 1:
        # Sequential processing - use pre-created instances for efficiency
        logger.info("Processing tickers sequentially...")
        results = []
        with tqdm(total=len(ticker_data), desc="Building Dataset A", unit="ticker") as pbar:
            for ticker, df in ticker_data.items():
                try:
                    # Calculate lightweight features
                    df_features = feature_engine.calculate_lightweight_features(df)

                    # Calculate heavyweight features if requested
                    if mode == 'full':
                        df_features = feature_engine.calculate_heavyweight_features(df_features, ticker)

                    # Merge fundamental data if requested
                    if fundamental_merger is not None:
                        df_features = fundamental_merger.merge_ticker_data(ticker, df_features)

                    # Add ticker column
                    df_features['ticker'] = ticker

                    # Handle date column carefully to avoid duplicates
                    if 'date' not in df_features.columns:
                        df_features['date'] = pd.to_datetime(df_features.index)
                    elif df_features.index.name == 'date' or isinstance(df_features.index, pd.DatetimeIndex):
                        df_features = df_features.reset_index(drop=True)

                    # Ensure date column is datetime type
                    if 'date' in df_features.columns:
                        df_features['date'] = pd.to_datetime(df_features['date'])

                    # Check for duplicate columns
                    duplicate_cols = df_features.columns[df_features.columns.duplicated()].tolist()
                    if duplicate_cols:
                        logger.error(f"{ticker}: Duplicate columns detected: {duplicate_cols}")
                        df_features = df_features.loc[:, ~df_features.columns.duplicated()]

                    # Reorder columns
                    cols = ['date', 'ticker', 'Close', 'Volume']
                    feature_cols = [c for c in df_features.columns if c not in cols + ['Open', 'High', 'Low']]
                    df_features = df_features[cols + feature_cols]

                    if not df_features.empty:
                        results.append(df_features)
                except Exception as e:
                    logger.warning(f"Failed to process {ticker}: {e}")

                pbar.update(1)
    else:
        # Parallel processing - pass pickle-safe parameters
        from multiprocessing import Pool, cpu_count

        if n_jobs == -1:
            n_jobs = cpu_count()

        logger.info(f"Processing tickers in parallel using {n_jobs} workers...")

        # Prepare arguments: (ticker, df, mode, benchmark_data, include_fundamentals, skip_data_updates)
        args_list = [
            (ticker, df, mode, benchmark_data, include_fundamentals, skip_data_updates)
            for ticker, df in ticker_data.items()
        ]

        # Calculate optimal chunksize for load balancing
        # Balance between progress smoothness and overhead
        optimal_chunksize = max(1, len(args_list) // (n_jobs * 4))
        chunksize = min(optimal_chunksize, 10)  # Cap at 10 for smooth progress

        logger.info(f"Using chunksize={chunksize} for {len(args_list)} tickers")

        # Choose parallel processing strategy based on memory mode
        if memory_mode == 'low':
            # LOW MEMORY MODE: Stream results to disk instead of accumulating in memory
            import tempfile
            import os
            temp_dir = tempfile.mkdtemp(prefix='dataset_a_parallel_')
            logger.info(f"LOW MEMORY MODE: Streaming results to disk: {temp_dir}")

            # Use multiprocessing Pool with imap_unordered for real-time progress updates
            pool = None
            chunk_files = []
            try:
                pool = Pool(processes=n_jobs)
                results = []
                chunk_counter = 0
                STREAM_BATCH_SIZE = 50  # Write to disk every 50 tickers

                with tqdm(total=len(args_list), desc="Building Dataset A", unit="ticker") as pbar:
                    # imap_unordered yields results as they complete (lazy evaluation)
                    for result in pool.imap_unordered(
                        _process_ticker_for_dataset_a_wrapper,
                        args_list,
                        chunksize=chunksize
                    ):
                        if not result.empty:
                            results.append(result)

                            # When we accumulate enough results, write to disk and clear memory
                            if len(results) >= STREAM_BATCH_SIZE:
                                chunk_df = pd.concat(results, ignore_index=True)
                                chunk_file = os.path.join(temp_dir, f'stream_chunk_{chunk_counter:04d}.parquet')
                                chunk_df.to_parquet(chunk_file, index=False, compression='snappy')
                                chunk_files.append(chunk_file)
                                logger.debug(f"Wrote stream chunk {chunk_counter} ({len(results)} tickers) to disk")
                                chunk_counter += 1

                                # Clear memory
                                results.clear()
                                del chunk_df

                        pbar.update(1)

                # Write any remaining results
                if results:
                    chunk_df = pd.concat(results, ignore_index=True)
                    chunk_file = os.path.join(temp_dir, f'stream_chunk_{chunk_counter:04d}.parquet')
                    chunk_df.to_parquet(chunk_file, index=False, compression='snappy')
                    chunk_files.append(chunk_file)
                    logger.debug(f"Wrote final stream chunk {chunk_counter} ({len(results)} tickers) to disk")
                    results.clear()
                    del chunk_df

                logger.info(f"Parallel processing complete. Created {len(chunk_files)} stream chunks.")

                # MEMORY OPTIMIZATION: Don't load all chunks into memory at once
                # Instead, keep file paths and read them later in batches during concatenation
                # This avoids loading 49 large DataFrames into memory simultaneously
                logger.info(f"Stream chunks will be processed in batches during concatenation")

                # Store file paths instead of DataFrames
                results = chunk_files  # List of file paths, not DataFrames
                streaming_temp_dir = temp_dir  # Save for cleanup later

            finally:
                # Properly clean up pool to prevent semaphore leaks
                if pool is not None:
                    pool.close()
                    pool.join()

                # DON'T clean up temp_dir yet - files are still needed for concatenation
                # Will be cleaned up after concatenation is complete
        else:
            # HIGH MEMORY MODE: Fast in-memory accumulation (requires 16GB+ RAM)
            logger.info(f"HIGH MEMORY MODE: In-memory processing (fast)")

            pool = None
            try:
                pool = Pool(processes=n_jobs)
                results = []

                with tqdm(total=len(args_list), desc="Building Dataset A", unit="ticker") as pbar:
                    for result in pool.imap_unordered(
                        _process_ticker_for_dataset_a_wrapper,
                        args_list,
                        chunksize=chunksize
                    ):
                        if not result.empty:
                            results.append(result)
                        pbar.update(1)

                logger.info(f"Parallel processing complete. Collected {len(results)} DataFrames in memory")

            finally:
                # Properly clean up pool to prevent semaphore leaks
                if pool is not None:
                    pool.close()
                    pool.join()
    
    # Concatenate all results
    logger.info("Concatenating results...")
    if not results:
        logger.error("No data generated!")
        return pd.DataFrame()

    # Check if results are file paths (from low memory streaming) or DataFrames
    results_are_files = isinstance(results, list) and len(results) > 0 and isinstance(results[0], str)

    # Track streaming temp dir for cleanup after concatenation
    streaming_temp_dir_to_cleanup = None
    if results_are_files and 'streaming_temp_dir' in locals():
        streaming_temp_dir_to_cleanup = streaming_temp_dir

    if not results_are_files:
        # Convert categorical and problematic object columns to string to avoid ordering issues
        for df in results:
            # Convert categorical columns
            for col in df.select_dtypes(include=['category']).columns:
                df[col] = df[col].astype(str)

            # Also convert object columns that might have mixed types (except date/ticker)
            for col in df.select_dtypes(include=['object']).columns:
                if col not in ['date', 'ticker']:
                    try:
                        df[col] = df[col].astype(str)
                    except:
                        pass  # Skip if conversion fails

    # MEMORY FIX: Choose concatenation strategy based on memory mode and result count
    # High memory mode or few results: fast in-memory concat
    # Low memory mode with many results: disk-based hierarchical merge

    if (memory_mode == 'high' or len(results) <= 10) and not results_are_files:
        # HIGH MEMORY or few chunks - safe to concatenate in memory
        logger.info(f"Concatenating {len(results)} DataFrames in memory...")
        dataset_a = pd.concat(results, ignore_index=True)
        results.clear()
        del results
    else:
        # Many chunks - use disk-based incremental concatenation
        logger.info(f"Concatenating {len(results)} items using disk-based approach...")

        import tempfile
        import os

        # Determine if results are file paths or DataFrames
        if results_are_files:
            # Results are already file paths from streaming - use them directly
            logger.info(f"Using {len(results)} pre-existing stream chunk files")
            chunk_files = results
            temp_dir = None  # No new temp dir needed
        else:
            # Results are DataFrames - need to write them to disk first
            temp_dir = tempfile.mkdtemp(prefix='dataset_a_chunks_')
            logger.info(f"Using temporary directory: {temp_dir}")

            CHUNK_SIZE = 50  # Smaller chunks for memory-constrained systems
            total_chunks = (len(results) - 1) // CHUNK_SIZE + 1
            chunk_files = []

            # Write chunks to disk incrementally
            for i in range(0, len(results), CHUNK_SIZE):
                chunk_dfs = results[i:i + CHUNK_SIZE]
                chunk_df = pd.concat(chunk_dfs, ignore_index=True)

                # Write to temporary parquet file
                chunk_file = os.path.join(temp_dir, f'chunk_{len(chunk_files):04d}.parquet')
                chunk_df.to_parquet(chunk_file, index=False, compression='snappy')
                chunk_files.append(chunk_file)

                logger.info(f"  Wrote chunk {len(chunk_files)}/{total_chunks} ({len(chunk_dfs)} DataFrames) to disk")

                # Aggressively free memory
                del chunk_dfs, chunk_df

            # Clear original results list
            results.clear()
            del results

        # Read chunks back and concatenate in batches (further reduces memory pressure)
        logger.info(f"Reading {len(chunk_files)} chunk files and concatenating in batches...")
        BATCH_SIZE = 2  # Extremely small batch size for memory-constrained 8GB systems

        # Create temp dir for intermediate files if not exists
        if temp_dir is None:
            temp_dir = tempfile.mkdtemp(prefix='dataset_a_merge_')

        intermediate_files = []

        try:
            # First pass: merge small chunks into intermediate chunks
            for batch_idx in range(0, len(chunk_files), BATCH_SIZE):
                batch = chunk_files[batch_idx:batch_idx + BATCH_SIZE]
                batch_df = pd.concat([pd.read_parquet(f) for f in batch], ignore_index=True)

                intermediate_file = os.path.join(temp_dir, f'intermediate_{len(intermediate_files):04d}.parquet')
                batch_df.to_parquet(intermediate_file, index=False, compression='snappy')
                intermediate_files.append(intermediate_file)

                logger.info(f"  Merged batch {len(intermediate_files)}/{(len(chunk_files)-1)//BATCH_SIZE + 1}")
                del batch_df

            # Multiple merge passes to keep reducing file count down to 1
            pass_number = 2
            current_files = intermediate_files

            while len(current_files) > 1:
                logger.info(f"Merge pass {pass_number} for {len(current_files)} files...")
                next_pass_files = []

                for batch_idx in range(0, len(current_files), BATCH_SIZE):
                    batch = current_files[batch_idx:batch_idx + BATCH_SIZE]
                    batch_df = pd.concat([pd.read_parquet(f) for f in batch], ignore_index=True)

                    pass_file = os.path.join(temp_dir, f'pass{pass_number}_{len(next_pass_files):04d}.parquet')
                    batch_df.to_parquet(pass_file, index=False, compression='snappy')
                    next_pass_files.append(pass_file)

                    logger.info(f"  Pass {pass_number} batch {len(next_pass_files)}/{(len(current_files)-1)//BATCH_SIZE + 1}")
                    del batch_df

                current_files = next_pass_files
                pass_number += 1

            # Final result: single file remaining
            logger.info(f"Merge complete! Reading final result from disk...")
            dataset_a = pd.read_parquet(current_files[0])

        finally:
            # Clean up temporary files
            logger.info("Cleaning up temporary chunk files...")
            import shutil
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
                logger.info(f"Removed temporary directory: {temp_dir}")

            # Also clean up streaming temp directory if it exists
            if streaming_temp_dir_to_cleanup and os.path.exists(streaming_temp_dir_to_cleanup):
                shutil.rmtree(streaming_temp_dir_to_cleanup)
                logger.info(f"Removed streaming temporary directory: {streaming_temp_dir_to_cleanup}")

    # CRITICAL: Ensure proper data types before sorting to avoid comparison errors
    # Convert ticker to string and date to datetime
    dataset_a['ticker'] = dataset_a['ticker'].astype(str)
    dataset_a['date'] = pd.to_datetime(dataset_a['date'])

    # CRITICAL: Sort by ticker AND date before shifting to ensure proper groupby boundaries
    dataset_a = dataset_a.sort_values(['ticker', 'date']).reset_index(drop=True)

    # Apply lagged features using groupby to respect ticker boundaries
    logger.info("\n" + "="*80)
    logger.info(" APPLYING LAGGED FEATURES (Setup Conditions at T-1)")
    logger.info("="*80)
    logger.info("Creating lagged features with groupby to prevent cross-ticker contamination...")
    lag_start = time.time()

    FEATURES_TO_LAG = [
        'nATR', 'ATR', 'VCP_Ratio', 'Consolidation_Width',
        'Price_vs_SMA_50', 'Price_vs_SMA_150', 'Price_vs_SMA_200',
        'RS', 'RS_MA', 'Dry_Up_Volume',
        'High_52W', 'Low_52W', 'RSI_14', 'Dist_From_52W_High'
    ]

    lagged_count = 0
    for feature in FEATURES_TO_LAG:
        if feature in dataset_a.columns:
            lag_col_name = f"{feature}_Lag1"
            dataset_a[lag_col_name] = dataset_a.groupby('ticker')[feature].shift(1)
            lagged_count += 1
            logger.debug(f"  Added {lag_col_name}")
        else:
            logger.warning(f"  Feature '{feature}' not found in dataset. Skipping lag.")

    lag_time = time.time() - lag_start
    logger.info(f"Created {lagged_count}/{len(FEATURES_TO_LAG)} lagged features in {lag_time:.1f}s")

    # Validation: Check first row per ticker has NaN lags (prevents data leakage)
    logger.info("Validating groupby boundaries (first row per ticker should have NaN lags)...")
    sample_tickers = dataset_a['ticker'].unique()[:3]
    lag_cols = [c for c in dataset_a.columns if c.endswith('_Lag1')]

    validation_passed = True
    for ticker in sample_tickers:
        ticker_data = dataset_a[dataset_a['ticker'] == ticker].sort_values('date')
        if len(ticker_data) > 0:
            first_row = ticker_data.iloc[0]
            nan_lags = first_row[lag_cols].isna().sum()

            if nan_lags == len(lag_cols):
                logger.debug(f"  ✓ {ticker}: First row has NaN lags (correct)")
            else:
                logger.warning(f"  ✗ {ticker}: First row has {len(lag_cols) - nan_lags}/{len(lag_cols)} non-NaN lags (DATA LEAK!)")
                validation_passed = False

    if validation_passed:
        logger.info("✓ Lag validation passed: No cross-ticker contamination detected")
    else:
        logger.warning("✗ Lag validation FAILED: Potential data leakage detected!")

    # Re-sort by date and ticker for consistency with expected output format
    dataset_a = dataset_a.sort_values(['date', 'ticker']).reset_index(drop=True)

    # Summary statistics
    logger.info(f"\nDataset A Summary:")
    logger.info(f"  Total rows: {len(dataset_a):,}")
    logger.info(f"  Date range: {dataset_a['date'].min()} to {dataset_a['date'].max()}")
    logger.info(f"  Tickers: {dataset_a['ticker'].nunique()}")
    logger.info(f"  Features: {len(dataset_a.columns) - 2}")  # Exclude date, ticker
    logger.info(f"  Missing values: {dataset_a.isnull().sum().sum()} ({dataset_a.isnull().sum().sum() / dataset_a.size * 100:.2f}%)")
    
    # Add cross-sectional features if requested (post-processing after concatenation)
    if include_cross_sectional:
        logger.info("\n" + "="*80)
        logger.info(" POST-PROCESSING: CROSS-SECTIONAL FEATURES")
        logger.info("="*80)
        
        try:
            from src.cross_sectional_features import add_cross_sectional_features
            
            dataset_a = add_cross_sectional_features(
                dataset_a,
                company_profile_path='data/company_info/company_profiles.parquet',
                rs_column='RS'
            )
            
            # Update feature count
            logger.info(f"\nUpdated Dataset A Summary:")
            logger.info(f"  Total features: {len(dataset_a.columns) - 2}")  # Exclude date, ticker
            logger.info(f"  New cross-sectional features: RS_Universe_Rank, Sector_Momentum, Industry_Momentum")
            
        except Exception as e:
            logger.error(f"Failed to add cross-sectional features: {e}")
            logger.warning("Continuing without cross-sectional features...")
    
    return dataset_a


def main():
    """Main entry point for Dataset A builder."""
    parser = argparse.ArgumentParser(
        description="Build Dataset A - Daily Feature Snapshots for ML Training"
    )
    
    parser.add_argument(
        '--start',
        type=str,
        required=True,
        help='Start date for dataset (YYYY-MM-DD)'
    )
    
    parser.add_argument(
        '--end',
        type=str,
        required=True,
        help='End date for dataset (YYYY-MM-DD)'
    )
    
    parser.add_argument(
        '--mode',
        type=str,
        choices=['lightweight', 'full'],
        default='lightweight',
        help='Feature mode: lightweight (fast) or full (includes heavyweight alphas)'
    )
    
    parser.add_argument(
        '--output',
        type=str,
        default='data/ml/dataset_a.parquet',
        help='Output path for Dataset A (default: data/ml/dataset_a.parquet)'
    )
    
    parser.add_argument(
        '--format',
        type=str,
        choices=['parquet', 'csv', 'both'],
        default='parquet',
        help='Output format (default: parquet)'
    )
    
    parser.add_argument(
        '--tickers',
        type=str,
        nargs='+',
        default=None,
        help='Optional: Specific tickers to process (e.g., AAPL MSFT TSLA)'
    )
    
    parser.add_argument(
        '--from-price-cache',
        action='store_true',
        help='Use tickers from price cache folder (data/price/*.parquet) instead of full universe'
    )

    parser.add_argument(
        '--from-dataset-b',
        type=str,
        default=None,
        help='Use tickers from existing Dataset B file (e.g., data/ml/dataset_b.parquet)'
    )

    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit number of tickers to process (useful for testing)'
    )
    
    parser.add_argument(
        '--no-validate',
        action='store_true',
        help='Skip temporal validation checks'
    )
    
    parser.add_argument(
        '--include-fundamentals',
        action='store_true',
        help='Include fundamental data (growth metrics, ratios, P/E, etc.)'
    )
    
    parser.add_argument(
        '--include-cross-sectional',
        action='store_true',
        help='Add cross-sectional features (RS_Universe_Rank, Sector/Industry_Momentum)'
    )
    
    parser.add_argument(
        '--n-jobs',
        type=int,
        default=1,
        help='Number of parallel jobs (1=sequential, -1=use all CPUs, default: 1)'
    )

    parser.add_argument(
        '--update-cache',
        action='store_true',
        help='Force price and fundamental data cache updates (default: skip updates and use existing cache)'
    )

    parser.add_argument(
        '--memory-mode',
        type=str,
        choices=['auto', 'low', 'high'],
        default='auto',
        help='Memory mode: auto (detect RAM), low (8GB, disk-based), high (16GB+, in-memory for speed)'
    )

    args = parser.parse_args()
    
    print("=" * 80)
    print(" DATASET A BUILDER - Daily Feature Snapshots")
    print("=" * 80)
    print(f"\n📅 Date Range: {args.start} to {args.end}")
    print(f"⚙️  Mode: {args.mode}")
    print(f"💾 Output: {args.output}")
    if args.n_jobs != 1:
        print(f"⚡ Parallel Jobs: {args.n_jobs if args.n_jobs > 0 else 'ALL CPUs'}")

    # Resolve memory mode
    memory_mode = args.memory_mode
    if memory_mode == 'auto':
        memory_mode = detect_memory_mode()
        print(f"🧠 Memory Mode: {memory_mode} (auto-detected)")
    else:
        print(f"🧠 Memory Mode: {memory_mode} (user-specified)")

    # Determine ticker list
    tickers = args.tickers

    if tickers:
        # User specified explicit tickers
        print(f"🎯 Using {len(tickers)} user-specified tickers: {', '.join(tickers[:5])}{' ...' if len(tickers) > 5 else ''}")
    elif args.from_dataset_b:
        # Load from existing Dataset B
        dataset_b_path = Path(args.from_dataset_b)
        if dataset_b_path.exists():
            print(f"📊 Loading tickers from Dataset B: {args.from_dataset_b}")
            dataset_b = pd.read_parquet(dataset_b_path)
            tickers = sorted(dataset_b['ticker'].unique().tolist())
            print(f"🎯 Found {len(tickers)} tickers in Dataset B")
            if len(tickers) > 0:
                print(f"   Sample tickers: {', '.join(tickers[:5])}{' ...' if len(tickers) > 5 else ''}")
        else:
            print(f"❌ Dataset B file not found: {args.from_dataset_b}")
            print(f"   Falling back to full universe")
            tickers = None
    elif args.from_price_cache:
        # Load from price cache folder
        price_cache_dir = Path('data/price')
        if price_cache_dir.exists():
            # Get all .parquet files and extract ticker names
            price_files = list(price_cache_dir.glob('*.parquet'))
            tickers = sorted([f.stem for f in price_files])  # .stem removes the .parquet extension
            print(f"🎯 Using {len(tickers)} tickers from price cache (data/price/)")
            if len(tickers) > 0:
                print(f"   Sample tickers: {', '.join(tickers[:5])}{' ...' if len(tickers) > 5 else ''}")
            else:
                print(f"⚠️  No price files found in data/price/")
                print(f"   Falling back to full universe")
                tickers = None
        else:
            print(f"❌ Price cache directory not found: data/price/")
            print(f"   Falling back to full universe")
            tickers = None
    else:
        # Default: Use full universe
        print(f"🌍 Using FMP stock screener universe (~1,730 tickers)")
        tickers = None

    # Apply limit if specified
    if args.limit and tickers:
        original_count = len(tickers)
        tickers = tickers[:args.limit]
        print(f"⚠️  Limiting to first {args.limit} tickers (out of {original_count})")

    # Create output directory
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Build Dataset A
    print("\n🚀 Starting dataset generation...")
    print("   (This may take several minutes depending on date range and mode)\n")
    
    dataset_a = build_dataset_a(
        start_date=args.start,
        end_date=args.end,
        mode=args.mode,
        tickers=tickers,
        validate_temporal=not args.no_validate,
        include_fundamentals=args.include_fundamentals,
        include_cross_sectional=args.include_cross_sectional,
        n_jobs=args.n_jobs,
        skip_data_updates=not args.update_cache,  # Inverted: skip by default unless --update-cache is used
        memory_mode=memory_mode
    )
    
    if dataset_a.empty:
        print("\n❌ No data generated!")
        return
    
    # Save to file
    print("\n💾 Saving Dataset A...")
    
    if args.format in ['parquet', 'both']:
        parquet_path = output_path if output_path.suffix == '.parquet' else output_path.with_suffix('.parquet')
        dataset_a.to_parquet(parquet_path, index=False, compression='snappy')
        print(f"   ✅ Saved to: {parquet_path}")
        
        # Print file size
        file_size_mb = parquet_path.stat().st_size / (1024 * 1024)
        print(f"   📊 File size: {file_size_mb:.2f} MB")
    
    if args.format in ['csv', 'both']:
        csv_path = output_path.with_suffix('.csv') if output_path.suffix == '.parquet' else output_path
        dataset_a.to_csv(csv_path, index=False)
        print(f"   ✅ Saved to: {csv_path}")
    
    # Feature summary
    print(f"\n📋 Feature Summary:")
    feature_cols = [col for col in dataset_a.columns if col not in ['date', 'ticker', 'Close', 'Volume']]
    print(f"   Total features: {len(feature_cols)}")
    
    # Group by type
    lightweight = [col for col in feature_cols if not col.startswith('alpha')]
    heavyweight = [col for col in feature_cols if col.startswith('alpha')]
    
    if lightweight:
        print(f"   Lightweight: {len(lightweight)} features")
        print(f"      {', '.join(lightweight[:5])}{' ...' if len(lightweight) > 5 else ''}")
    
    if heavyweight:
        print(f"   Heavyweight (Alphas): {len(heavyweight)} features")
        print(f"      {', '.join(heavyweight)}")
    
    print("\n" + "=" * 80)
    print(f"✅ Dataset A generation complete!")
    print(f"   {len(dataset_a):,} rows | {len(feature_cols)} features | {dataset_a['ticker'].nunique()} tickers")
    
    # Show source of tickers
    if args.tickers:
        print(f"   Source: User-specified tickers")
    elif args.from_price_cache:
        print(f"   Source: Tickers from price cache (data/price/)")
    else:
        print(f"   Source: FMP Stock Screener Universe")
    
    print("=" * 80 + "\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Dataset generation interrupted by user.")
    except Exception as e:
        logger.error(f"Dataset generation failed: {e}", exc_info=True)
        print(f"\n❌ ERROR: {e}")
        sys.exit(1)
