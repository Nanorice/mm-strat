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

import shutil
import gc

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

# Define features to lag globally or pass them in
FEATURES_TO_LAG = [
    'nATR', 'ATR', 'VCP_Ratio', 'Consolidation_Width',
    'Price_vs_SMA_50', 'Price_vs_SMA_150', 'Price_vs_SMA_200',
    'RS', 'RS_MA', 'Dry_Up_Volume',
    'High_52W', 'Low_52W', 'RSI_14', 'Dist_From_52W_High'
]

def _process_ticker_for_dataset_a(
    ticker: str,
    df: pd.DataFrame,
    mode: str,
    benchmark_data: Optional[pd.Series] = None,
    include_fundamentals: bool = False,
    skip_data_updates: bool = True
) -> pd.DataFrame:
    try:
        # --- Existing Feature Engineering Logic ---
        # Suppress logging...
        import logging
        worker_logger = logging.getLogger('src.features')
        original_level = worker_logger.level
        worker_logger.setLevel(logging.WARNING)

        feature_engine = FeatureEngineer(benchmark_data=benchmark_data)
        worker_logger.setLevel(original_level)

        # Calculate base features
        df_features = feature_engine.calculate_lightweight_features(df)

        if mode == 'full':
            df_features = feature_engine.calculate_heavyweight_features(df_features, ticker)

        if include_fundamentals:
            from src.fundamental_merger import FundamentalMerger
            fundamental_merger = FundamentalMerger(force_cache_only=skip_data_updates)
            df_features = fundamental_merger.merge_ticker_data(ticker, df_features)
        
        # --- Standardize Columns ---
        df_features['ticker'] = ticker
        
        # Handle date index/column
        if 'date' not in df_features.columns:
            df_features['date'] = pd.to_datetime(df_features.index)
        elif df_features.index.name == 'date':
            df_features = df_features.reset_index(drop=True)
            
        if 'date' in df_features.columns:
            df_features['date'] = pd.to_datetime(df_features['date'])

        # --- OPTIMIZATION: Calculate Lags Here (Per Ticker) ---
        # Instead of doing this globally later, we do it here while the data is small
        df_features = df_features.sort_values('date') # Ensure time order
        
        for feature in FEATURES_TO_LAG:
            if feature in df_features.columns:
                df_features[f"{feature}_Lag1"] = df_features[feature].shift(1)

        # --- Cleanup ---
        # Remove duplicates
        df_features = df_features.loc[:, ~df_features.columns.duplicated()]

        # Reorder
        cols = ['date', 'ticker', 'Close', 'Volume']
        feature_cols = [c for c in df_features.columns if c not in cols + ['Open', 'High', 'Low']]
        
        # Return final ordered dataframe
        return df_features[cols + feature_cols]
        
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
    memory_mode: str = 'auto' # Kept for signature compatibility, but now implicitly 'efficient'
) -> pd.DataFrame:
    
    logger.info(f"Building Dataset A from {start_date} to {end_date}")
    
    # 1. Setup Output Directory (Partitioned Dataset)
    # We will write to a folder: data/ml/dataset_a_interim/
    # This allows appending without loading the whole file.
    output_dir = Path("data/ml/dataset_a_interim")
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 2. Initialize Components
    data_repo = DataRepository()
    end_date_timestamp = pd.Timestamp(end_date)
    
    benchmark_data = data_repo.get_benchmark_data(
        required_end_date=end_date_timestamp,
        force_cache_only=skip_data_updates
    )

    if tickers is None:
        logger.info("Loading universe...")
        tickers = data_repo.update_universe()
        
    # 3. Batch Processing Loop
    # Process 100 tickers at a time to keep RAM low
    BATCH_SIZE = 100 
    total_processed = 0
    
    # Split tickers into chunks
    ticker_chunks = [tickers[i:i + BATCH_SIZE] for i in range(0, len(tickers), BATCH_SIZE)]
    logger.info(f"Processing {len(tickers)} tickers in {len(ticker_chunks)} batches...")

    from multiprocessing import Pool, cpu_count
    
    if n_jobs == -1:
        n_jobs = cpu_count()

    # Create pool once (or recreate per batch if you suspect memory leaks)
    pool = Pool(processes=n_jobs) if n_jobs > 1 else None

    try:
        for i, chunk in enumerate(tqdm(ticker_chunks, desc="Processing Batches")):
            
            # A. Load ONLY this batch of data
            chunk_data = data_repo.get_batch_data(
                chunk, 
                show_progress=False,
                required_end_date=end_date_timestamp,
                force_cache_only=skip_data_updates
            )
            
            if not chunk_data:
                continue

            # B. Process Batch
            batch_results = []
            
            args_list = [
                (t, df, mode, benchmark_data, include_fundamentals, skip_data_updates)
                for t, df in chunk_data.items()
            ]

            if pool:
                # Parallel
                for result in pool.imap_unordered(_process_ticker_for_dataset_a_wrapper, args_list):
                    if not result.empty:
                        batch_results.append(result)
            else:
                # Sequential
                for args in args_list:
                    result = _process_ticker_for_dataset_a(*args)
                    if not result.empty:
                        batch_results.append(result)

            # C. Write Batch Immediately
            if batch_results:
                df_batch = pd.concat(batch_results, ignore_index=True)
                
                # Standardize types before writing
                df_batch['ticker'] = df_batch['ticker'].astype(str)
                # Convert object cols to string (except date)
                for col in df_batch.select_dtypes(include=['object']).columns:
                    if col != 'date':
                        df_batch[col] = df_batch[col].astype(str)

                # Write to parquet partition
                # Files named part_0.parquet, part_1.parquet, etc.
                batch_file = output_dir / f"part_{i}.parquet"
                df_batch.to_parquet(batch_file, index=False, compression='snappy')
                
                total_processed += len(df_batch)

            # D. Aggressive Memory Cleanup
            del chunk_data
            del batch_results
            if 'df_batch' in locals(): del df_batch
            gc.collect()

    finally:
        if pool:
            pool.close()
            pool.join()

    logger.info(f"Batch processing complete. Total rows generated: {total_processed:,}")

    # 4. Finalizing
    # If include_cross_sectional is True, we must now load the data (or process efficiently)
    # Since cross-sectional needs ALL data for a specific date, this is tricky for OOM.
    # However, usually we can load the columns needed for ranking, rank them, and merge back.
    # For now, let's just return the directory path logic or a pyarrow table.
    
    logger.info("Reading consolidated dataset from disk...")
    
    # Use PyArrow to read the dataset (efficiently handles partitioned folders)
    try:
        full_df = pd.read_parquet(output_dir)
        
        # Sort finally (this might spike RAM, but it's cleaner than before)
        full_df = full_df.sort_values(['date', 'ticker']).reset_index(drop=True)
        
        if include_cross_sectional:
            # Add cross sectional features now that we have the full frame
            # (Note: if this crashes RAM, you need a different strategy for XS features)
            from src.cross_sectional_features import add_cross_sectional_features
            full_df = add_cross_sectional_features(
                full_df,
                company_profile_path='data/company_info/company_profiles.parquet',
                rs_column='RS'
            )
            
        return full_df

    except Exception as e:
        logger.error(f"Could not load final dataframe into memory: {e}")
        logger.info(f"Data is safely saved in {output_dir}")
        # Return empty DF to signal "Check disk", or throw error
        return pd.DataFrame()

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
