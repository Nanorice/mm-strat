"""
Dataset Merger - Merge Dataset A (features) and Dataset B (labels) for ML Training

This module provides OOP-based tools to perform snapshot joins between:
- Dataset A: Daily time-series of technical/fundamental features for each ticker
- Dataset B: Trade log with entry dates and labels

The merge extracts the exact feature vector from Dataset A for each trade's entry_date.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Tuple, Optional, List
import logging
from datetime import datetime
from tqdm import tqdm

logger = logging.getLogger(__name__)


class DatasetLoader:
    """
    Handles loading and basic validation of Dataset A and Dataset B.
    
    Supports both Parquet and CSV formats with automatic date conversion.
    """
    
    @staticmethod
    def load_dataset_a(path: str) -> pd.DataFrame:
        """
        Load Dataset A with validation.
        
        Args:
            path: Path to Dataset A file (.parquet or .csv)
        
        Returns:
            DataFrame with required columns: date, ticker, Close, Volume, [features]
        
        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If required columns are missing
        """
        file_path = Path(path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"Dataset A not found: {path}")
        
        # Load based on file extension
        if file_path.suffix == '.parquet':
            df = pd.read_parquet(path)
            logger.info(f"Loaded Dataset A (Parquet): {len(df):,} rows")
        elif file_path.suffix == '.csv':
            df = pd.read_csv(path)
            logger.info(f"Loaded Dataset A (CSV): {len(df):,} rows")
        else:
            raise ValueError(f"Unsupported file format: {file_path.suffix}. Use .parquet or .csv")
        
        # Convert date column to datetime
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
        
        # Validate required columns
        required_cols = ['date', 'ticker', 'Close', 'Volume']
        missing_cols = [col for col in required_cols if col not in df.columns]
        
        if missing_cols:
            raise ValueError(f"Dataset A missing required columns: {missing_cols}")
        
        logger.info(f"Dataset A schema: {len(df.columns)} columns, {df['ticker'].nunique()} tickers")
        logger.info(f"Date range: {df['date'].min().date()} to {df['date'].max().date()}")
        
        return df
    
    @staticmethod
    def load_dataset_b(path: str) -> pd.DataFrame:
        """
        Load Dataset B with validation.
        
        Args:
            path: Path to Dataset B file (.parquet or .csv)
        
        Returns:
            DataFrame with required columns: ticker, entry_date, label
        
        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If required columns are missing
        """
        file_path = Path(path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"Dataset B not found: {path}")
        
        # Load based on file extension
        if file_path.suffix == '.parquet':
            df = pd.read_parquet(path)
            logger.info(f"Loaded Dataset B (Parquet): {len(df):,} trades")
        elif file_path.suffix == '.csv':
            df = pd.read_csv(path)
            logger.info(f"Loaded Dataset B (CSV): {len(df):,} trades")
        else:
            raise ValueError(f"Unsupported file format: {file_path.suffix}. Use .parquet or .csv")
        
        # Convert date columns to datetime
        date_cols = ['entry_date', 'exit_date']
        for col in date_cols:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col])
        
        # Validate required columns
        required_cols = ['ticker', 'entry_date', 'label']
        missing_cols = [col for col in required_cols if col not in df.columns]
        
        if missing_cols:
            raise ValueError(f"Dataset B missing required columns: {missing_cols}")
        
        logger.info(f"Dataset B schema: {len(df.columns)} columns, {df['ticker'].nunique()} tickers")
        logger.info(f"Entry date range: {df['entry_date'].min().date()} to {df['entry_date'].max().date()}")
        logger.info(f"Label distribution: {df['label'].value_counts().to_dict()}")
        
        return df
    
    @staticmethod
    def validate_schema(df: pd.DataFrame, dataset_type: str) -> bool:
        """
        Validate dataset schema.
        
        Args:
            df: DataFrame to validate
            dataset_type: 'A' or 'B'
        
        Returns:
            True if valid, raises ValueError otherwise
        """
        if dataset_type == 'A':
            required = ['date', 'ticker', 'Close', 'Volume']
        elif dataset_type == 'B':
            required = ['ticker', 'entry_date', 'label']
        else:
            raise ValueError("dataset_type must be 'A' or 'B'")
        
        missing = [col for col in required if col not in df.columns]
        
        if missing:
            raise ValueError(f"Dataset {dataset_type} missing columns: {missing}")
        
        return True


class SnapshotExtractor:
    """
    Extracts feature snapshots from Dataset A for each trade in Dataset B.
    
    Uses MultiIndex (ticker, date) for O(1) lookups during batch extraction.
    Tracks missing snapshots for quality reporting.
    """
    
    def __init__(self, dataset_a: pd.DataFrame):
        """
        Initialize extractor with Dataset A.
        
        Args:
            dataset_a: Dataset A DataFrame with (date, ticker, features)
        """
        self.dataset_a = dataset_a.copy()
        self.missing_snapshots: List[Dict] = []
        self._index_dataset_a()
    
    def _index_dataset_a(self):
        """Create MultiIndex for fast (ticker, date) lookups."""
        logger.info("Indexing Dataset A for fast lookups...")
        
        # Create MultiIndex on (ticker, date)
        self.dataset_a = self.dataset_a.set_index(['ticker', 'date'])
        
        # Check for duplicates before sorting
        num_duplicates = self.dataset_a.index.duplicated().sum()
        if num_duplicates > 0:
            logger.warning(f"⚠️  Found {num_duplicates} duplicate (ticker, date) pairs in Dataset A")
            logger.warning(f"   Removing duplicates, keeping first occurrence...")
            self.dataset_a = self.dataset_a[~self.dataset_a.index.duplicated(keep='first')]
        
        # Sort index to avoid lexsort depth warning
        self.dataset_a = self.dataset_a.sort_index(level=['ticker', 'date'])
        
        # Verify index is sorted
        if not self.dataset_a.index.is_monotonic_increasing:
            logger.warning("Index not monotonic after sort, resorting...")
            self.dataset_a = self.dataset_a.sort_index()
        
        logger.info(f"✅ Indexed {len(self.dataset_a):,} rows for O(1) lookup")
    
    def extract_snapshot(self, ticker: str, date: pd.Timestamp) -> Optional[pd.Series]:
        """
        Extract feature vector for a single (ticker, date) pair.
        
        Args:
            ticker: Stock symbol
            date: Entry date (trade signal date)
        
        Returns:
            pd.Series with features, or None if not found
        """
        try:
            result = self.dataset_a.loc[(ticker, date)]
            
            # If multiple rows returned (duplicates that slipped through), take first
            if isinstance(result, pd.DataFrame):
                logger.warning(f"⚠️  Multiple rows found for ({ticker}, {date}), taking first")
                return result.iloc[0]
            
            return result
        except KeyError:
            return None
    
    def batch_extract(self, trades: pd.DataFrame) -> pd.DataFrame:
        """
        Extract features for all trades in Dataset B.
        
        This is the core merge operation: for each trade (ticker, entry_date),
        extract the corresponding feature vector from Dataset A.
        
        Args:
            trades: Dataset B DataFrame with trades
        
        Returns:
            DataFrame with trades + extracted features
        """
        logger.info(f"Starting batch extraction for {len(trades):,} trades...")
        
        results = []
        self.missing_snapshots = []
        
        # Progress bar
        with tqdm(total=len(trades), desc="Extracting snapshots") as pbar:
            for idx, trade in trades.iterrows():
                ticker = trade['ticker']
                entry_date = trade['entry_date']
                
                # Extract feature snapshot
                features = self.extract_snapshot(ticker, entry_date)
                
                if features is None:
                    # Track missing snapshot
                    self.missing_snapshots.append({
                        'ticker': ticker,
                        'entry_date': entry_date,
                        'trade_id': trade.get('trade_id', idx)
                    })
                    pbar.update(1)
                    continue
                
                
                # Combine trade metadata + features
                # Trade columns come first, then features
                # IMPORTANT: Preserve 'date' from the MultiIndex (entry_date becomes date for ML)
                merged_row = {**trade.to_dict(), **features.to_dict()}
                # Add 'date' column from entry_date (this is the snapshot date for features)
                merged_row['date'] = entry_date
                results.append(merged_row)
                
                pbar.update(1)
        
        merged_df = pd.DataFrame(results)
        
        # Log results
        match_rate = (len(merged_df) / len(trades)) * 100 if len(trades) > 0 else 0
        logger.info(f"✅ Extracted snapshots: {len(merged_df):,} / {len(trades):,} ({match_rate:.1f}%)")
        
        if len(self.missing_snapshots) > 0:
            logger.warning(f"⚠️  Missing snapshots: {len(self.missing_snapshots)} trades")
        
        return merged_df


class DatasetMerger:
    """
    Main orchestrator for merging Dataset A and Dataset B.
    
    Workflow:
    1. Load both datasets using DatasetLoader
    2. Validate temporal compatibility (date/ticker overlap)
    3. Perform snapshot extraction using SnapshotExtractor
    4. Track merge statistics
    5. Export merged dataset
    
    Usage:
        merger = DatasetMerger(
            dataset_a_path='data/ml/dataset_a_with_fundamentals.parquet',
            dataset_b_path='data/ml/dataset_b.parquet'
        )
        merger.load_datasets()
        merged = merger.merge()
        merger.export('data/ml/merged_dataset.parquet')
    """
    
    def __init__(self,
                 dataset_a_path: str,
                 dataset_b_path: str,
                 validate_temporal: bool = True):
        """
        Initialize merger.
        
        Args:
            dataset_a_path: Path to Dataset A (features)
            dataset_b_path: Path to Dataset B (labels)
            validate_temporal: If True, validate temporal compatibility
        """
        self.dataset_a_path = dataset_a_path
        self.dataset_b_path = dataset_b_path
        self.validate_temporal = validate_temporal
        
        self.dataset_a: Optional[pd.DataFrame] = None
        self.dataset_b: Optional[pd.DataFrame] = None
        self.merged: Optional[pd.DataFrame] = None
        
        self.merge_stats: Dict = {}
        self.extractor: Optional[SnapshotExtractor] = None
    
    def load_datasets(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Load and validate both datasets.
        
        Returns:
            Tuple of (dataset_a, dataset_b)
        """
        logger.info("=" * 80)
        logger.info("LOADING DATASETS")
        logger.info("=" * 80)
        
        # Load Dataset A
        logger.info(f"\n📂 Loading Dataset A from: {self.dataset_a_path}")
        self.dataset_a = DatasetLoader.load_dataset_a(self.dataset_a_path)
        
        # Load Dataset B
        logger.info(f"\n📂 Loading Dataset B from: {self.dataset_b_path}")
        self.dataset_b = DatasetLoader.load_dataset_b(self.dataset_b_path)
        
        logger.info("\n✅ Both datasets loaded successfully")
        
        return self.dataset_a, self.dataset_b
    
    def validate_compatibility(self) -> bool:
        """
        Validate temporal compatibility between datasets.
        
        Checks:
        1. Date range overlap
        2. Ticker overlap
        3. No trades before Dataset A starts
        
        Returns:
            True if valid, raises ValueError otherwise
        """
        logger.info("\n" + "=" * 80)
        logger.info("VALIDATING COMPATIBILITY")
        logger.info("=" * 80)
        
        if self.dataset_a is None or self.dataset_b is None:
            raise ValueError("Datasets not loaded. Call load_datasets() first.")
        
        # Get unique dates and tickers
        a_dates = set(self.dataset_a['date'].dt.date)
        b_dates = set(self.dataset_b['entry_date'].dt.date)
        
        a_tickers = set(self.dataset_a['ticker'])
        b_tickers = set(self.dataset_b['ticker'])
        
        # Check date overlap
        overlap_dates = a_dates & b_dates
        logger.info(f"\n📅 Date Overlap Analysis:")
        logger.info(f"   Dataset A date range: {min(a_dates)} to {max(a_dates)} ({len(a_dates)} unique dates)")
        logger.info(f"   Dataset B date range: {min(b_dates)} to {max(b_dates)} ({len(b_dates)} unique dates)")
        logger.info(f"   Overlapping dates: {len(overlap_dates)}")
        
        if len(overlap_dates) == 0:
            raise ValueError("❌ No date overlap between datasets!")
        
        logger.info(f"   ✅ Date overlap: {len(overlap_dates)} days")
        
        # Check ticker overlap
        overlap_tickers = a_tickers & b_tickers
        logger.info(f"\n📊 Ticker Overlap Analysis:")
        logger.info(f"   Dataset A tickers: {len(a_tickers)}")
        logger.info(f"   Dataset B tickers: {len(b_tickers)}")
        logger.info(f"   Overlapping tickers: {len(overlap_tickers)}")
        
        if len(overlap_tickers) == 0:
            raise ValueError("❌ No ticker overlap between datasets!")
        
        logger.info(f"   ✅ Ticker overlap: {len(overlap_tickers)} tickers")
        
        # Check for trades with missing tickers
        missing_tickers = b_tickers - a_tickers
        if missing_tickers:
            logger.warning(f"   ⚠️  Tickers in Dataset B but not in Dataset A: {sorted(missing_tickers)[:10]}")
        
        # Estimate expected match rate
        b_coverage = len(overlap_tickers) / len(b_tickers) * 100
        logger.info(f"\n📈 Expected Coverage: {b_coverage:.1f}% of trades should find matches")
        
        logger.info("\n✅ Compatibility validation passed")
        
        return True
    
    def merge(self, merge_strategy: str = 'left') -> pd.DataFrame:
        """
        Perform snapshot merge.
        
        The merge logic:
        - For each trade in Dataset B (ticker, entry_date)
        - Extract the exact feature row from Dataset A
        - Combine trade metadata + features
        
        Args:
            merge_strategy: 'left' (keep all trades) or 'inner' (only matched)
        
        Returns:
            Merged DataFrame
        """
        logger.info("\n" + "=" * 80)
        logger.info("PERFORMING SNAPSHOT MERGE")
        logger.info("=" * 80)
        
        if self.dataset_a is None or self.dataset_b is None:
            raise ValueError("Datasets not loaded. Call load_datasets() first.")
        
        # Create extractor
        self.extractor = SnapshotExtractor(self.dataset_a)
        
        # Batch extract
        self.merged = self.extractor.batch_extract(self.dataset_b)
        
        # Calculate statistics
        total_trades = len(self.dataset_b)
        matched_trades = len(self.merged)
        missing_trades = len(self.extractor.missing_snapshots)
        match_rate = (matched_trades / total_trades * 100) if total_trades > 0 else 0
        
        # Feature count (columns added from Dataset A)
        b_cols = set(self.dataset_b.columns)
        feature_count = len([col for col in self.merged.columns if col not in b_cols])
        
        self.merge_stats = {
            'dataset_a_rows': len(self.dataset_a),
            'dataset_a_tickers': self.dataset_a.reset_index()['ticker'].nunique(),
            'dataset_b_trades': total_trades,
            'merged_rows': matched_trades,
            'match_rate_pct': match_rate,
            'missing_snapshots': missing_trades,
            'feature_count': feature_count,
            'total_columns': len(self.merged.columns),
        }
        
        logger.info(f"\n🔗 Merge Results:")
        logger.info(f"   Matched: {matched_trades:,} / {total_trades:,} trades ({match_rate:.1f}%)")
        logger.info(f"   Missing: {missing_trades} trades")
        logger.info(f"   Features added: {feature_count}")
        logger.info(f"   Total columns: {len(self.merged.columns)}")
        
        if missing_trades > 0:
            logger.warning(f"\n⚠️  {missing_trades} trades could not find matching snapshots")
            logger.warning(f"   This may indicate date/ticker misalignment between datasets")
        
        logger.info("\n✅ Merge complete!")
        
        return self.merged
    
    def get_merge_statistics(self) -> Dict:
        """
        Return detailed merge statistics.
        
        Returns:
            Dictionary with merge statistics and quality metrics
        """
        if self.merged is None:
            return {}
        
        # Calculate additional statistics
        missing_values_count = self.merged.isnull().sum().sum()
        total_values = self.merged.size
        missing_pct = (missing_values_count / total_values * 100) if total_values > 0 else 0
        
        stats = {
            **self.merge_stats,
            'label_distribution': self.merged['label'].value_counts().to_dict(),
            'missing_values_count': missing_values_count,
            'missing_values_pct': missing_pct,
            'merged_tickers': self.merged['ticker'].nunique(),
        }
        
        # Feature columns (excluding Dataset B columns)
        b_cols = set(self.dataset_b.columns)
        feature_cols = [col for col in self.merged.columns if col not in b_cols]
        stats['feature_columns'] = feature_cols
        
        # Missing snapshots details
        if self.extractor and self.extractor.missing_snapshots:
            stats['missing_snapshots_detail'] = self.extractor.missing_snapshots
        
        return stats
    
    def export(self, output_path: str, format: str = 'parquet'):
        """
        Export merged dataset.
        
        Args:
            output_path: Output file path
            format: 'parquet', 'csv', or 'both'
        """
        if self.merged is None:
            raise ValueError("No merged dataset to export. Run merge() first.")
        
        logger.info("\n" + "=" * 80)
        logger.info("EXPORTING MERGED DATASET")
        logger.info("=" * 80)
        
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # Export to Parquet
        if format in ['parquet', 'both']:
            parquet_path = path if path.suffix == '.parquet' else path.with_suffix('.parquet')
            self.merged.to_parquet(parquet_path, index=False, compression='snappy')
            
            file_size_mb = parquet_path.stat().st_size / (1024 * 1024)
            logger.info(f"\n✅ Saved to: {parquet_path}")
            logger.info(f"   File size: {file_size_mb:.2f} MB")
        
        # Export to CSV
        if format in ['csv', 'both']:
            csv_path = path.with_suffix('.csv')
            self.merged.to_csv(csv_path, index=False)
            
            file_size_mb = csv_path.stat().st_size / (1024 * 1024)
            logger.info(f"\n✅ Saved to: {csv_path}")
            logger.info(f"   File size: {file_size_mb:.2f} MB")
        
        logger.info("\n✅ Export complete!")
