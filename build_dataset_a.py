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


def build_dataset_a(
    start_date: str,
    end_date: str,
    mode: str = 'lightweight',
    tickers: list = None,
    validate_temporal: bool = True
) -> pd.DataFrame:
    """
    Build Dataset A - daily feature snapshots.
    
    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        mode: 'lightweight' or 'full' (includes heavyweight alphas)
        tickers: Optional list of tickers (default: use universe)
        validate_temporal: If True, run temporal validation checks
    
    Returns:
        DataFrame with columns: date, ticker, Close, Volume, features...
    """
    logger.info(f"Building Dataset A from {start_date} to {end_date}")
    logger.info(f"Mode: {mode}")
    
    # Initialize components
    data_repo = DataRepository()
    benchmark_data = data_repo.get_benchmark_data()
    
    if benchmark_data is None:
        logger.error("Failed to load benchmark data!")
        return pd.DataFrame()
    
    feature_engine = FeatureEngineer(benchmark_data=benchmark_data)
    
    if validate_temporal:
        validator = TemporalValidator()
    
    # Get tickers to process
    if tickers is None:
        # Default: use tickers from Dataset B (not entire universe)
        logger.info("No tickers specified - loading from Dataset B...")
        try:
            dataset_b_path = Path('data/ml/dataset_b_2025.parquet')
            if not dataset_b_path.exists():
                dataset_b_path = Path('data/ml/dataset_b.parquet')
            
            if dataset_b_path.exists():
                dataset_b = pd.read_parquet(dataset_b_path)
                tickers = sorted(dataset_b['ticker'].unique().tolist())
                logger.info(f"Loaded {len(tickers)} tickers from {dataset_b_path}")
            else:
                logger.warning("Dataset B not found, loading entire universe")
                tickers = data_repo.update_universe()
        except Exception as e:
            logger.error(f"Failed to load Dataset B: {e}")
            logger.info("Falling back to entire universe")
            tickers = data_repo.update_universe()
    
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
    
    # Build feature snapshots
    rows = []
    total_iterations = len(ticker_data) * len(date_range)
    
    with tqdm(total=total_iterations, desc="Building Dataset A") as pbar:
        for ticker, df in ticker_data.items():
            # Calculate features once for entire history
            try:
                # Calculate lightweight features
                df_features = feature_engine.calculate_lightweight_features(df)
                
                # Calculate heavyweight features if requested
                if mode == 'full':
                    df_features = feature_engine.calculate_heavyweight_features(df_features, ticker)
                
                # Extract daily snapshots
                for date in date_range:
                    # Get data available up to this date
                    df_subset = df_features[df_features.index <= date]
                    
                    if len(df_subset) == 0:
                        pbar.update(1)
                        continue
                    
                    # Extract last row (features as of 'date')
                    last_row = df_subset.iloc[-1]
                    
                    # Create record
                    record = {
                        'date': date,
                        'ticker': ticker,
                        'Close': last_row['Close'],
                        'Volume': last_row['Volume'],
                    }
                    
                    # Add all feature columns
                    for col in df_features.columns:
                        if col not in ['Open', 'High', 'Low']:  # Already have Close/Volume
                            record[col] = last_row.get(col, np.nan)
                    
                    rows.append(record)
                    pbar.update(1)
                
            except Exception as e:
                logger.warning(f"Failed to process {ticker}: {e}")
                pbar.update(len(date_range))
                continue
    
    # Convert to DataFrame
    logger.info("Converting to DataFrame...")
    dataset_a = pd.DataFrame(rows)
    
    if len(dataset_a) == 0:
        logger.error("No data generated!")
        return dataset_a
    
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
        help='Optional: Specific tickers to process (default: tickers from Dataset B)'
    )
    
    parser.add_argument(
        '--use-universe',
        action='store_true',
        help='Use entire S&P 500 universe instead of Dataset B tickers'
    )
    
    parser.add_argument(
        '--from-dataset-b',
        type=str,
        default=None,
        help='Path to Dataset B parquet file (default: auto-detect data/ml/dataset_b*.parquet)'
    )
    
    parser.add_argument(
        '--no-validate',
        action='store_true',
        help='Skip temporal validation checks'
    )
    
    args = parser.parse_args()
    
    print("=" * 80)
    print(" DATASET A BUILDER - Daily Feature Snapshots")
    print("=" * 80)
    print(f"\n📅 Date Range: {args.start} to {args.end}")
    print(f"⚙️  Mode: {args.mode}")
    print(f"💾 Output: {args.output}")
    
    # Determine ticker list
    tickers = args.tickers
    if tickers is None and not args.use_universe:
        # Load from Dataset B
        dataset_b_path = args.from_dataset_b
        if dataset_b_path is None:
            # Auto-detect
            for candidate in ['data/ml/dataset_b_2025.parquet', 'data/ml/dataset_b.parquet']:
                if Path(candidate).exists():
                    dataset_b_path = candidate
                    break
        
        if dataset_b_path and Path(dataset_b_path).exists():
            dataset_b = pd.read_parquet(dataset_b_path)
            tickers = sorted(dataset_b['ticker'].unique().tolist())
            print(f"🎯 Using {len(tickers)} tickers from {dataset_b_path}")
        else:
            print(f"⚠️  Dataset B not found, using entire universe")
            tickers = None
    elif tickers:
        print(f"🎯 Tickers: {', '.join(tickers[:5])}{' ...' if len(tickers) > 5 else ''}")
    else:
        print(f"🌍 Using entire S&P 500 universe (~500 tickers)")
    
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
        tickers=args.tickers,
        validate_temporal=not args.no_validate
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
    elif not args.use_universe:
        print(f"   Source: Tickers from Dataset B ({dataset_b_path})")
    else:
        print(f"   Source: Full S&P 500 Universe")
    
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
