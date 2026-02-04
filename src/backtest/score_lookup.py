"""
Score Lookup - Fast Daily Candidate Filtering
==============================================
Pre-loaded universe scores for fast daily candidate queries during backtest.

Handles calendar misalignment (holidays, data gaps) gracefully by returning
empty lists for dates without score data.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


class ScoreLookup:
    """
    Pre-loaded universe scores for fast daily candidate filtering.

    Builds an in-memory index for O(1) date lookups.

    Usage:
        lookup = ScoreLookup('data/backtest/universe_scores.parquet')
        candidates = lookup.get_candidates(date, min_score=30.0, min_percentile=0.95)
        # Returns: [(ticker, score), ...] sorted by daily rank descending
    """

    def __init__(self, scores_path: str):
        """
        Load and index universe scores.

        Args:
            scores_path: Path to universe_scores.parquet
        """
        self.scores_path = Path(scores_path)
        self.df: Optional[pd.DataFrame] = None
        self._index: Dict[datetime, Dict[str, Tuple[float, float]]] = {}
        self._load_and_index()

    def _load_and_index(self):
        """Load parquet and build date -> {ticker: (norm_score, daily_rank)} index."""
        if not self.scores_path.exists():
            raise FileNotFoundError(f"Scores file not found: {self.scores_path}")

        logger.info(f"Loading scores from {self.scores_path}")
        self.df = pd.read_parquet(self.scores_path)

        # Ensure date is datetime
        self.df['date'] = pd.to_datetime(self.df['date'])

        # Build index
        logger.info("Building score index...")

        # Check if trailing_10d_pct exists (new format)
        has_trailing = 'trailing_10d_pct' in self.df.columns

        for date, group in self.df.groupby('date'):
            # Convert to datetime.date for consistent lookup
            date_key = date.date() if hasattr(date, 'date') else date

            if has_trailing:
                # New format: include trailing percentile
                self._index[date_key] = {
                    row['ticker']: (
                        row['normalized_score'],
                        row['daily_pct_rank'],
                        row['trailing_10d_pct'],
                    )
                    for _, row in group.iterrows()
                }
            else:
                # Legacy format: pad with daily_pct_rank for backwards compatibility
                self._index[date_key] = {
                    row['ticker']: (
                        row['normalized_score'],
                        row['daily_pct_rank'],
                        row['daily_pct_rank'],  # Fallback to daily
                    )
                    for _, row in group.iterrows()
                }

        logger.info(f"Indexed {len(self._index)} dates, "
                   f"{self.df['ticker'].nunique()} unique tickers")

    def get_candidates(
        self,
        date: datetime,
        min_score: float = 30.0,
        min_percentile: float = 0.0,
        rank_by: Literal['trailing', 'daily'] = 'trailing',
    ) -> List[Tuple[str, float, float]]:
        """
        Get tickers passing score floor, sorted by rank.

        Args:
            date: Trading date to query
            min_score: Minimum normalized score (0-100) - absolute floor
            min_percentile: Minimum percentile rank (0-1) - optional gate
                           0.0 = no gate (Top N Competition mode)
                           0.95 = top 5% filter (legacy mode)
            rank_by: Which percentile to use for sorting:
                    'trailing' = 10-day cohort percentile (recommended)
                    'daily' = single-day cross-sectional rank

        Returns:
            List of (ticker, normalized_score, trailing_pct) tuples,
            sorted by selected rank descending.
            Returns empty list if no scores exist for the date (holiday, data gap).

        Note:
            The "Top N Competition" approach uses min_percentile=0.0 and fills
            available slots with the best-ranked candidates. This avoids the
            double-gating problem (percentile gate + regime gate).
        """
        # Normalize date to date object
        if hasattr(date, 'date'):
            date_key = date.date()
        else:
            date_key = date

        # Handle missing dates gracefully
        day_data = self._index.get(date_key)
        if day_data is None:
            logger.debug(f"No scores for {date_key}, skipping entry logic")
            return []

        # Filter candidates by score floor and optional percentile gate
        candidates = []
        for ticker, (score, daily_rank, trailing_rank) in day_data.items():
            if score < min_score:
                continue

            # Use selected rank for filtering
            rank_value = trailing_rank if rank_by == 'trailing' else daily_rank
            if rank_value < min_percentile:
                continue

            candidates.append((ticker, score, trailing_rank, daily_rank))

        # Sort by selected rank descending (best candidates first)
        sort_idx = 2 if rank_by == 'trailing' else 3
        candidates.sort(key=lambda x: -x[sort_idx])

        # Return (ticker, score, trailing_pct) for strategy use
        return [(ticker, score, trailing) for ticker, score, trailing, _ in candidates]

    def get_score(
        self,
        date: datetime,
        ticker: str,
    ) -> Optional[Tuple[float, float, float]]:
        """
        Get score for a specific ticker on a specific date.

        Args:
            date: Trading date
            ticker: Stock ticker

        Returns:
            Tuple of (normalized_score, daily_pct_rank, trailing_10d_pct)
            or None if not found
        """
        if hasattr(date, 'date'):
            date_key = date.date()
        else:
            date_key = date

        day_data = self._index.get(date_key)
        if day_data is None:
            return None

        return day_data.get(ticker)

    def get_available_dates(self) -> List[datetime]:
        """Get all dates with score data."""
        return sorted(self._index.keys())

    def get_date_range(self) -> Tuple[datetime, datetime]:
        """Get the date range of available scores."""
        dates = self.get_available_dates()
        return (dates[0], dates[-1]) if dates else (None, None)

    def get_stats(self) -> Dict:
        """Get summary statistics about the score data."""
        if self.df is None:
            return {}

        return {
            'total_scores': len(self.df),
            'unique_tickers': self.df['ticker'].nunique(),
            'unique_dates': len(self._index),
            'date_range': self.get_date_range(),
            'avg_scores_per_day': len(self.df) / len(self._index) if self._index else 0,
            'score_mean': self.df['normalized_score'].mean(),
            'score_std': self.df['normalized_score'].std(),
        }


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    # Test lookup
    lookup = ScoreLookup('data/backtest/universe_scores.parquet')

    print("\nStats:")
    for k, v in lookup.get_stats().items():
        print(f"  {k}: {v}")

    # Test candidate lookup
    dates = lookup.get_available_dates()
    if dates:
        test_date = dates[len(dates) // 2]  # Middle date

        # Top N Competition mode (no percentile gate)
        candidates = lookup.get_candidates(
            test_date, min_score=30.0, min_percentile=0.0, rank_by='trailing'
        )
        print(f"\nTop N Competition for {test_date} (sorted by 10-day trailing pct):")
        for ticker, score, trailing in candidates[:10]:
            print(f"  {ticker}: score={score:.1f}, trailing_pct={trailing:.3f}")
