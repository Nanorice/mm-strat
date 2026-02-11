"""
Universe Engine - Consolidated Market Data for Cross-Sectional Analysis
========================================================================
Builds and maintains universe parquet files - a single source of truth for
universe-wide ranking and cross-sectional features.

Architecture:
- Orchestrator only - calls existing DataRepository and FeatureEngineer
- Star Schema: universe_*.parquet (facts) + company_profiles.parquet (dimensions)
- 5-year segments: universe_2000_2004.parquet, universe_2005_2009.parquet, etc.
- Smart rebuild: only rebuilds segments that overlap with requested date range

Usage:
    engine = UniverseEngine()
    engine.build_universe()  # Full rebuild all segments
    engine.build_universe(start_date='2020-01-01')  # Only rebuild 2020-2024 segment
    snapshot = engine.get_snapshot(date)  # Get all tickers for a date
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple
import logging
from tqdm import tqdm

import sys
sys.path.append(str(Path(__file__).parent.parent))
import config
from src.data_engine import DataRepository, CacheMode
from src.features import FeatureEngineer
from src.cross_sectional_features import add_cross_sectional_features

logger = logging.getLogger(__name__)


class UniverseEngine:
    """
    Builds and queries segmented universe parquet files.

    File Structure:
        data/price/universe_2000_2004.parquet
        data/price/universe_2005_2009.parquet
        data/price/universe_2010_2014.parquet
        data/price/universe_2015_2019.parquet
        data/price/universe_2020_2024.parquet
        data/price/universe_2025_2029.parquet

    Schema (MultiIndex: date, ticker):
        Base: open, high, low, close, volume
        Liquidity: turnover, turnover_ma20
        Volume: vol_ma20, vol_ma50
        Momentum: mom_21d, mom_63d, mom_126d, mom_189d, mom_252d
        RS Rating: rs_rating (Minervini-style weighted momentum)
    """

    # 5-year segment boundaries
    SEGMENT_YEARS = 5

    # Columns to keep in universe.parquet (Float32 for compression)
    UNIVERSE_COLUMNS = [
        # Base OHLCV
        'open', 'high', 'low', 'close', 'volume',
        # Liquidity
        'turnover', 'turnover_ma20',
        # Volume MAs
        'vol_ma20', 'vol_ma50',
        # Momentum
        'mom_21d', 'mom_63d', 'mom_126d', 'mom_189d', 'mom_252d',
        # RS Rating & Relative Strength
        'rs_rating', 'RS', 'RS_MA',
        # SEPA Trend Template (SMAs)
        'SMA_50', 'SMA_150', 'SMA_200',
        # SEPA 52-Week Range
        'High_52W', 'Low_52W',
        # SEPA Breakout Detection
        'High_20D', 'Breakout',
        # Volume Ratio for SEPA
        'Vol_MA', 'Vol_Ratio',
        # ATR for trade planning
        'ATR',
    ]

    def __init__(self, universe_dir: Path = None, profiles_path: Path = None):
        """
        Initialize the Universe Engine.

        Args:
            universe_dir: Directory for universe segment files (default: data/price/)
            profiles_path: Path to company_profiles.parquet
        """
        self.universe_dir = universe_dir or config.PRICE_DATA_DIR
        self.profiles_path = profiles_path or Path('data/company_info/company_profiles.parquet')

        # Lazy-loaded DataFrames
        self._universe_cache: Dict[str, pd.DataFrame] = {}  # segment_name -> DataFrame
        self._profiles: Optional[pd.DataFrame] = None

        # Reuse existing infrastructure
        self.data_repo = DataRepository(enable_validation=False)

    def _get_segment_name(self, year: int) -> str:
        """Get segment filename for a given year."""
        segment_start = (year // self.SEGMENT_YEARS) * self.SEGMENT_YEARS
        segment_end = segment_start + self.SEGMENT_YEARS - 1
        return f"universe_{segment_start}_{segment_end}"

    def _get_segment_path(self, segment_name: str) -> Path:
        """Get full path for a segment file."""
        return self.universe_dir / f"{segment_name}.parquet"

    def _get_segments_for_range(self, start_date: str, end_date: str) -> List[str]:
        """Get list of segment names that cover a date range."""
        start_year = int(start_date[:4])
        end_year = int(end_date[:4])

        segments = set()
        for year in range(start_year, end_year + 1):
            segments.add(self._get_segment_name(year))

        return sorted(segments)

    def _list_existing_segments(self) -> List[str]:
        """List all existing universe segment files."""
        pattern = "universe_*_*.parquet"
        files = list(self.universe_dir.glob(pattern))
        return [f.stem for f in files]

    def _load_segment(self, segment_name: str) -> pd.DataFrame:
        """Load a single segment file."""
        if segment_name in self._universe_cache:
            return self._universe_cache[segment_name]

        path = self._get_segment_path(segment_name)
        if path.exists():
            df = pd.read_parquet(path)
            if not isinstance(df.index, pd.MultiIndex):
                if 'date' in df.columns and 'ticker' in df.columns:
                    df = df.set_index(['date', 'ticker'])
            self._universe_cache[segment_name] = df
            return df
        return pd.DataFrame()

    def _load_segments_for_range(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Load and concatenate all segments covering a date range."""
        segments = self._get_segments_for_range(start_date, end_date)
        frames = []

        for seg in segments:
            df = self._load_segment(seg)
            if len(df) > 0:
                frames.append(df)

        if not frames:
            return pd.DataFrame()

        combined = pd.concat(frames).sort_index()
        # Filter to exact date range
        combined = combined.loc[start_date:end_date]
        return combined

    @property
    def universe(self) -> pd.DataFrame:
        """Load all existing universe segments combined."""
        segments = self._list_existing_segments()
        if not segments:
            return pd.DataFrame()

        frames = []
        for seg in segments:
            df = self._load_segment(seg)
            if len(df) > 0:
                frames.append(df)

        if not frames:
            return pd.DataFrame()

        return pd.concat(frames).sort_index()

    @property
    def profiles(self) -> pd.DataFrame:
        """Lazy-load company profiles DataFrame."""
        if self._profiles is None:
            if self.profiles_path.exists():
                self._profiles = pd.read_parquet(self.profiles_path)
            else:
                logger.warning(f"Profiles file not found: {self.profiles_path}")
                self._profiles = pd.DataFrame()
        return self._profiles

    def build_universe(self, start_date: str = '2000-01-01', end_date: str = None,
                       max_workers: int = 8, batch_size: int = 100) -> Dict[str, int]:
        """
        Build universe segment files from individual ticker parquets.

        Smart rebuild: Only rebuilds segments that overlap with the date range.
        For example, start_date='2020-01-01' only rebuilds universe_2020_2024.parquet.

        Workflow:
        1. Determine which 5-year segments need rebuilding
        2. Load all ticker data once
        3. Split by segment and save each segment file

        Args:
            start_date: Start date (default: 2000-01-01)
            end_date: End date (default: today)
            max_workers: Parallel workers for loading (default: 8)
            batch_size: Tickers per batch (default: 100)

        Returns:
            Dict mapping segment_name -> row count
        """
        end_date = end_date or datetime.now().strftime('%Y-%m-%d')
        segments_to_build = self._get_segments_for_range(start_date, end_date)

        logger.info(f"Building universe from {start_date} to {end_date}")
        logger.info(f"Segments to build: {segments_to_build}")

        # Get ticker list from price folder
        tickers = self.data_repo.update_universe(source='PRICE_FOLDER')
        logger.info(f"Found {len(tickers)} tickers in universe")

        # Load benchmark for RS calculation
        benchmark_data = self.data_repo.get_benchmark_data(mode=CacheMode.CACHE_ONLY)
        if benchmark_data is None:
            raise ValueError("Cannot build universe without benchmark (SPY) data")

        # Initialize feature engine with benchmark
        feature_engine = FeatureEngineer(benchmark_data=benchmark_data)

        # Process in batches - collect all data first
        all_frames = []
        num_batches = (len(tickers) + batch_size - 1) // batch_size

        for batch_idx in tqdm(range(num_batches), desc="Processing tickers"):
            batch_start = batch_idx * batch_size
            batch_end = min(batch_start + batch_size, len(tickers))
            batch_tickers = tickers[batch_start:batch_end]

            # Load batch data
            batch_data = self.data_repo.get_batch_data(
                tickers=batch_tickers,
                max_workers=max_workers,
                mode=CacheMode.CACHE_ONLY,
                show_progress=False
            )

            # Process each ticker
            for ticker, df in batch_data.items():
                try:
                    # Filter date range
                    df = df.loc[start_date:end_date].copy()
                    if len(df) < 50:
                        continue

                    # Calculate features
                    df = feature_engine.calculate_lightweight_features(df)

                    # Rename columns to lowercase
                    df = df.rename(columns={
                        'Open': 'open', 'High': 'high', 'Low': 'low',
                        'Close': 'close', 'Volume': 'volume'
                    })

                    df['ticker'] = ticker
                    available_cols = [c for c in self.UNIVERSE_COLUMNS if c in df.columns]
                    df = df[available_cols + ['ticker']].copy()

                    df = df.reset_index()
                    if 'Date' in df.columns:
                        df = df.rename(columns={'Date': 'date'})

                    all_frames.append(df)

                except Exception as e:
                    logger.warning(f"Failed to process {ticker}: {e}")
                    continue

        if not all_frames:
            raise ValueError("No valid ticker data found")

        # Concatenate all frames
        logger.info(f"Concatenating {len(all_frames)} ticker DataFrames...")
        universe_df = pd.concat(all_frames, ignore_index=True)
        universe_df['date'] = pd.to_datetime(universe_df['date'])

        # Convert to Float32
        for col in self.UNIVERSE_COLUMNS:
            if col in universe_df.columns and universe_df[col].dtype == 'float64':
                universe_df[col] = universe_df[col].astype('float32')

        # Split by segment and save
        results = {}
        for segment_name in segments_to_build:
            # Parse segment years
            parts = segment_name.split('_')
            seg_start_year = int(parts[1])
            seg_end_year = int(parts[2])

            seg_start = f"{seg_start_year}-01-01"
            seg_end = f"{seg_end_year}-12-31"

            # Filter to segment date range
            mask = (universe_df['date'] >= seg_start) & (universe_df['date'] <= seg_end)
            segment_df = universe_df[mask].copy()

            if len(segment_df) == 0:
                logger.info(f"Segment {segment_name}: No data, skipping")
                continue

            # Set index and save
            segment_df = segment_df.set_index(['date', 'ticker']).sort_index()
            self._save_segment(segment_name, segment_df)
            results[segment_name] = len(segment_df)

            # Update cache
            self._universe_cache[segment_name] = segment_df

        total_rows = sum(results.values())
        logger.info(f"Universe built: {total_rows:,} rows across {len(results)} segments")
        return results

    def _save_segment(self, segment_name: str, df: pd.DataFrame) -> None:
        """Save a segment DataFrame to parquet with Snappy compression."""
        self.universe_dir.mkdir(parents=True, exist_ok=True)
        path = self._get_segment_path(segment_name)
        df.to_parquet(path, compression='snappy')
        file_size_mb = path.stat().st_size / 1e6
        logger.info(f"Saved {segment_name}: {len(df):,} rows, {file_size_mb:.1f} MB")

    def append_daily(self, new_data: Dict[str, pd.DataFrame]) -> None:
        """
        Append new daily data to universe (incremental update).

        Automatically determines which segment(s) to update based on dates.
        Handles deduplication: if dates already exist, they are replaced.

        Args:
            new_data: Dict mapping ticker -> DataFrame with new rows
        """
        if not new_data:
            logger.warning("No new data to append")
            return

        # Load benchmark for feature calculation
        benchmark_data = self.data_repo.get_benchmark_data(mode=CacheMode.CACHE_ONLY)
        feature_engine = FeatureEngineer(benchmark_data=benchmark_data)

        # Process new data
        new_frames = []
        for ticker, df in new_data.items():
            try:
                df = feature_engine.calculate_lightweight_features(df)
                df = df.rename(columns={
                    'Open': 'open', 'High': 'high', 'Low': 'low',
                    'Close': 'close', 'Volume': 'volume'
                })
                df['ticker'] = ticker
                available_cols = [c for c in self.UNIVERSE_COLUMNS if c in df.columns]
                df = df[available_cols + ['ticker']].reset_index()
                if 'Date' in df.columns:
                    df = df.rename(columns={'Date': 'date'})
                new_frames.append(df)
            except Exception as e:
                logger.warning(f"Failed to process {ticker}: {e}")

        if not new_frames:
            return

        new_df = pd.concat(new_frames, ignore_index=True)
        new_df['date'] = pd.to_datetime(new_df['date'])

        # Convert to Float32
        for col in self.UNIVERSE_COLUMNS:
            if col in new_df.columns and new_df[col].dtype == 'float64':
                new_df[col] = new_df[col].astype('float32')

        # Group by segment and append to each
        new_df['year'] = new_df['date'].dt.year
        new_df['segment'] = new_df['year'].apply(self._get_segment_name)

        total_appended = 0
        for segment_name, segment_data in new_df.groupby('segment'):
            segment_data = segment_data.drop(columns=['year', 'segment'])
            segment_data = segment_data.set_index(['date', 'ticker']).sort_index()

            # Load existing segment
            existing = self._load_segment(segment_name)

            if len(existing) > 0:
                # Remove rows for dates we're updating
                dates_to_update = segment_data.index.get_level_values('date').unique()
                mask = ~existing.index.get_level_values('date').isin(dates_to_update)
                existing = existing.loc[mask]
                # Concatenate
                updated = pd.concat([existing, segment_data]).sort_index()
            else:
                updated = segment_data

            # Save
            self._save_segment(segment_name, updated)
            self._universe_cache[segment_name] = updated
            total_appended += len(segment_data)

        logger.info(f"Appended {total_appended} rows to universe")

    def get_snapshot(self, query_date: date) -> pd.DataFrame:
        """
        Get universe snapshot for a single date.

        Returns all tickers with their features for the given date.
        Use this for daily scanning and ranking.

        Args:
            query_date: Date to query

        Returns:
            DataFrame with all tickers for that date (ticker as index)
        """
        # Convert to Timestamp if needed
        if isinstance(query_date, date) and not isinstance(query_date, datetime):
            query_date = pd.Timestamp(query_date)

        # Load only the relevant segment
        year = query_date.year
        segment_name = self._get_segment_name(year)
        segment_df = self._load_segment(segment_name)

        if len(segment_df) == 0:
            logger.warning(f"No data for segment {segment_name}")
            return pd.DataFrame()

        try:
            snapshot = segment_df.loc[query_date].copy()
            return snapshot
        except KeyError:
            logger.warning(f"No data for date {query_date}")
            return pd.DataFrame()

    def get_cross_sectional_features(self, query_date: date,
                                      tickers: List[str]) -> pd.DataFrame:
        """
        Get cross-sectional ranks for specific tickers on a date.

        Computes universe-level, sector-level, and industry-level ranks
        using the full universe as reference.

        Args:
            query_date: Date to query
            tickers: List of tickers to get features for

        Returns:
            DataFrame with cross-sectional features for requested tickers
        """
        # Get full snapshot for the date
        snapshot = self.get_snapshot(query_date)
        if len(snapshot) == 0:
            return pd.DataFrame()

        # Add sector/industry from profiles
        if len(self.profiles) > 0:
            snapshot = snapshot.reset_index()
            snapshot = snapshot.merge(
                self.profiles[['ticker', 'sector_id', 'industry_id']],
                on='ticker', how='left'
            )
            snapshot['sector_id'] = snapshot['sector_id'].fillna(-1).astype(int)
            snapshot['industry_id'] = snapshot['industry_id'].fillna(-1).astype(int)
        else:
            snapshot = snapshot.reset_index()
            snapshot['sector_id'] = -1
            snapshot['industry_id'] = -1

        # Add date column for cross_sectional_features
        snapshot['date'] = query_date

        # Compute cross-sectional features using existing function
        # Uses rs_rating for ranking (Minervini-style)
        if 'rs_rating' in snapshot.columns:
            snapshot['RS'] = snapshot['rs_rating']  # Use rs_rating as RS for ranking

        snapshot = add_cross_sectional_features(snapshot)

        # Filter to requested tickers
        result = snapshot[snapshot['ticker'].isin(tickers)].copy()
        return result.set_index('ticker')

    def get_date_range(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        """
        Get evolving features for a single ticker over a date range.

        Use this for backtesting to get daily feature evolution during a trade.

        Args:
            ticker: Ticker symbol
            start: Start date
            end: End date

        Returns:
            DataFrame with daily features for the ticker
        """
        # Convert dates
        start_str = start.strftime('%Y-%m-%d') if isinstance(start, date) else start
        end_str = end.strftime('%Y-%m-%d') if isinstance(end, date) else end

        # Load relevant segments
        combined = self._load_segments_for_range(start_str, end_str)

        if len(combined) == 0:
            logger.warning(f"No data for range {start_str} to {end_str}")
            return pd.DataFrame()

        try:
            ticker_data = combined.xs(ticker, level='ticker')
            return ticker_data
        except KeyError:
            logger.warning(f"No data for {ticker} in range {start_str} to {end_str}")
            return pd.DataFrame()

    def get_universe_stats(self) -> Dict:
        """Get summary statistics about the universe."""
        segments = self._list_existing_segments()

        if not segments:
            return {'status': 'empty'}

        # Collect stats from each segment
        total_rows = 0
        all_tickers = set()
        min_date = None
        max_date = None
        total_size_mb = 0

        segment_stats = {}
        for seg in segments:
            path = self._get_segment_path(seg)
            if path.exists():
                df = self._load_segment(seg)
                if len(df) > 0:
                    dates = df.index.get_level_values('date')
                    tickers = df.index.get_level_values('ticker').unique()

                    segment_stats[seg] = {
                        'rows': len(df),
                        'tickers': len(tickers),
                        'date_range': f"{dates.min().date()} to {dates.max().date()}",
                        'size_mb': path.stat().st_size / 1e6
                    }

                    total_rows += len(df)
                    all_tickers.update(tickers)
                    total_size_mb += path.stat().st_size / 1e6

                    if min_date is None or dates.min() < min_date:
                        min_date = dates.min()
                    if max_date is None or dates.max() > max_date:
                        max_date = dates.max()

        if total_rows == 0:
            return {'status': 'empty'}

        return {
            'total_rows': total_rows,
            'unique_tickers': len(all_tickers),
            'date_range': f"{min_date.date()} to {max_date.date()}",
            'total_size_mb': total_size_mb,
            'segments': segment_stats,
            'columns': self.UNIVERSE_COLUMNS,
        }


if __name__ == '__main__':
    # Quick test
    logging.basicConfig(level=logging.INFO)

    engine = UniverseEngine()
    stats = engine.get_universe_stats()

    print("Universe Stats:")
    if stats.get('status') == 'empty':
        print("  Status: empty")
        print("\nTo build, run: python data_curator.py --universe")
    else:
        print(f"  Total rows: {stats['total_rows']:,}")
        print(f"  Unique tickers: {stats['unique_tickers']}")
        print(f"  Date range: {stats['date_range']}")
        print(f"  Total size: {stats['total_size_mb']:.1f} MB")
        print(f"\n  Segments:")
        for seg, seg_stats in stats.get('segments', {}).items():
            print(f"    {seg}: {seg_stats['rows']:,} rows, {seg_stats['size_mb']:.1f} MB")
