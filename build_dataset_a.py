"""
Build Dataset A - Daily Feature Snapshots for ML Training

Generates time-series of technical indicators and alpha factors for all tickers.
Each row represents features available for a specific ticker on a specific date.
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
    feature_engine: FeatureEngineer,
    fundamental_merger: Optional['FundamentalMerger']
) -> pd.DataFrame:
    """
    Process a single ticker - calculate features and prepare records.
    
    Args:
        ticker: Stock symbol
        df: Price dataframe
        mode: 'lightweight' or 'full'
        feature_engine: Feature engine instance
        fundamental_merger: Optional fundamental merger instance
        
    Returns:
        DataFrame with features for this ticker
    """
    try:
        # Calculate lightweight features
        df_features = feature_engine.calculate_lightweight_features(df)
        
        # Calculate heavyweight features if requested
        if mode == 'full':
            df_features = feature_engine.calculate_heavyweight_features(df_features, ticker)
        
        # Merge fundamental data if requested
        if fundamental_merger is not None:
            df_features = fundamental_merger.merge_ticker_data(ticker, df_features)
        
        # OPTIMIZATION: Instead of looping through dates, just add ticker column
        # The dataframe already has all the dates as index
        df_features['ticker'] = ticker
        df_features['date'] = df_features.index
        
        # Reorder columns: date, ticker, Close, Volume, then features
        cols = ['date', 'ticker', 'Close', 'Volume']
        feature_cols = [c for c in df_features.columns if c not in cols + ['Open', 'High', 'Low']]
        df_features = df_features[cols + feature_cols]
        
        return df_features
        
    except Exception as e:
        logger.warning(f"Failed to process {ticker}: {e}")
        return pd.DataFrame()


def build_dataset_a(
    start_date: str,
    end_date: str,
    mode: str = 'lightweight',
    tickers: list = None,
    validate_temporal: bool = True,
    include_fundamentals: bool = False,
    n_jobs: int = 1
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
        n_jobs: Number of parallel jobs (1 = sequential, -1 = all CPUs)
    
    Returns:
        DataFrame with columns: date, ticker, Close, Volume, features...
    """
    logger.info(f"Building Dataset A from {start_date} to {end_date}")
    logger.info(f"Mode: {mode}")
    logger.info(f"Parallel jobs: {n_jobs}")
    
    # Initialize components
    data_repo = DataRepository()
    benchmark_data = data_repo.get_benchmark_data()
    
    if benchmark_data is None:
        logger.error("Failed to load benchmark data!")
        return pd.DataFrame()
    
    feature_engine = FeatureEngineer(benchmark_data=benchmark_data)
    
    # Initialize fundamental merger if requested
    fundamental_merger = None
    if include_fundamentals:
        from src.fundamental_merger import FundamentalMerger
        fundamental_merger = FundamentalMerger()
        logger.info("Fundamental enrichment enabled")
    
    if validate_temporal:
        validator = TemporalValidator()
    
    # Get tickers to process
    if tickers is None:
        # Default: use full universe from FMP screener (~1730 tickers)
        logger.info("No tickers specified - loading full universe from FMP screener...")
        tickers = data_repo.update_universe()
        logger.info(f"Loaded {len(tickers)} tickers from FMP stock screener")
    
    logger.info(f"Processing {len(tickers)} tickers")
    
    # Update cache for all tickers
    logger.info("Updating price data cache...")
    data_repo.update_cache(tickers, force=False)
    
    # Load all ticker data
    logger.info("Loading ticker data...")
    ticker_data = data_repo.get_batch_data(tickers)
    logger.info(f"Successfully loaded {len(ticker_data)}/{len(tickers)} tickers")
    
    # Generate business day range
    date_range = pd.bdate_range(start_date, end_date)
    logger.info(f"Processing {len(date_range)} trading days")
    
    # Process tickers (sequential or parallel)
    if n_jobs == 1:
        # Sequential processing
        logger.info("Processing tickers sequentially...")
        results = []
        with tqdm(total=len(ticker_data), desc="Building Dataset A", unit="ticker") as pbar:
            for ticker, df in ticker_data.items():
                result = _process_ticker_for_dataset_a(
                    ticker, df, mode, feature_engine, fundamental_merger
                )
                if not result.empty:
                    results.append(result)
                pbar.update(1)
    else:
        # Parallel processing
        from multiprocessing import Pool, cpu_count
        
        if n_jobs == -1:
            n_jobs = cpu_count()
        
        logger.info(f"Processing tickers in parallel using {n_jobs} workers...")
        
        # Prepare arguments: (ticker, df, mode, feature_engine, fundamental_merger)
        args_list = [
            (ticker, df, mode, feature_engine, fundamental_merger)
            for ticker, df in ticker_data.items()
        ]
        
        # Use multiprocessing Pool
        with Pool(processes=n_jobs) as pool:
            results = []
            with tqdm(total=len(args_list), desc="Building Dataset A", unit="ticker") as pbar:
                for result in pool.starmap(_process_ticker_for_dataset_a, args_list):
                    if not result.empty:
                        results.append(result)
                    pbar.update(1)
    
    # Concatenate all results
    logger.info("Concatenating results...")
    if not results:
        logger.error("No data generated!")
        return pd.DataFrame()
    
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
    
    dataset_a = pd.concat(results, ignore_index=True)
    
    # Sort by date and ticker
    dataset_a = dataset_a.sort_values(['date', 'ticker']).reset_index(drop=True)
    
    # Summary statistics
    logger.info(f"\nDataset A Summary:")
    logger.info(f"  Total rows: {len(dataset_a):,}")
    logger.info(f"  Date range: {dataset_a['date'].min()} to {dataset_a['date'].max()}")
    logger.info(f"  Tickers: {dataset_a['ticker'].nunique()}")
    logger.info(f"  Features: {len(dataset_a.columns) - 2}")  # Exclude date, ticker
    logger.info(f"  Missing values: {dataset_a.isnull().sum().sum()} ({dataset_a.isnull().sum().sum() / dataset_a.size * 100:.2f}%)")
    
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
        '--n-jobs',
        type=int,
        default=1,
        help='Number of parallel jobs (1=sequential, -1=use all CPUs, default: 1)'
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
    
    # Determine ticker list
    tickers = args.tickers

    if tickers:
        # User specified explicit tickers
        print(f"🎯 Using {len(tickers)} user-specified tickers: {', '.join(tickers[:5])}{' ...' if len(tickers) > 5 else ''}")
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
        n_jobs=args.n_jobs
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
