"""
Score Lookup - Fast Daily Candidate Filtering
==============================================
Pre-loaded universe scores for fast daily candidate queries during backtest.

Handles calendar misalignment (holidays, data gaps) gracefully by returning
empty lists for dates without score data.
"""

import logging
from datetime import datetime
from typing import Dict, List, Literal, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


class ScoreLookup:
    """
    Pre-loaded universe scores for fast daily candidate filtering.

    Builds an in-memory index for O(1) date lookups.

    Usage:
        lookup = ScoreLookup(scores_df)
        candidates = lookup.get_candidates(date, min_score=30.0, min_percentile=0.95)
        # Returns: [(ticker, score, trailing_pct, prob_elite), ...] sorted by rank descending
    """

    def __init__(self, scores: pd.DataFrame):
        """
        Index universe scores produced by UniverseScorer.score_from_t3().

        Args:
            scores: DataFrame with columns date, ticker, normalized_score,
                    daily_pct_rank, trailing_pct, prob_elite.
        """
        self.df: pd.DataFrame = scores.copy()
        self._index: Dict[datetime, Dict[str, Tuple[float, float, float, float]]] = {}
        self._build_index()

    def _build_index(self):
        """Build date -> {ticker: (norm_score, daily_rank, trailing_pct, prob_elite)} index."""
        self.df['date'] = pd.to_datetime(self.df['date'])

        required = {'normalized_score', 'daily_pct_rank', 'trailing_pct', 'prob_elite'}
        missing = required - set(self.df.columns)
        if missing:
            raise ValueError(
                f"ScoreLookup missing required columns: {missing}. "
                "Re-score with UniverseScorer.score_from_t3()."
            )

        for date, group in self.df.groupby('date'):
            date_key = date.date() if hasattr(date, 'date') else date
            self._index[date_key] = {
                row['ticker']: (
                    row['normalized_score'],
                    row['daily_pct_rank'],
                    row['trailing_pct'],
                    row['prob_elite'],
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
        min_prob_elite: float = 0.0,
        rank_by: Literal['trailing', 'daily', 'prob_elite'] = 'trailing',
    ) -> List[Tuple[str, float, float, float]]:
        """
        Get tickers passing score floor, sorted by rank.

        Args:
            date: Trading date to query
            min_score: Minimum normalized score (0-100) - absolute floor
            min_percentile: Minimum percentile rank (0-1) - optional gate
            min_prob_elite: Minimum P(Class 3) Elite probability (0-1)
            rank_by: Sort key — 'trailing' | 'daily' | 'prob_elite'

        Returns:
            List of (ticker, normalized_score, trailing_pct, prob_elite) tuples,
            sorted by `rank_by` descending. Empty list if date has no scores.
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

        # Filter candidates by score floor, percentile gate, and elite threshold
        candidates = []
        for ticker, (score, daily_rank, trailing_rank, prob_elite) in day_data.items():
            if score < min_score:
                continue
            if prob_elite < min_prob_elite:
                continue

            rank_value = trailing_rank if rank_by == 'trailing' else daily_rank
            if rank_value < min_percentile:
                continue

            candidates.append((ticker, score, trailing_rank, daily_rank, prob_elite))

        # Sort by selected rank descending (best candidates first)
        if rank_by == 'prob_elite':
            candidates.sort(key=lambda x: -x[4])
        elif rank_by == 'trailing':
            candidates.sort(key=lambda x: -x[2])
        else:  # 'daily'
            candidates.sort(key=lambda x: -x[3])

        return [(ticker, score, trailing, prob_elite)
                for ticker, score, trailing, _, prob_elite in candidates]

    def get_score(
        self,
        date: datetime,
        ticker: str,
    ) -> Optional[Tuple[float, float, float, float]]:
        """
        Get score for a specific ticker on a specific date.

        Returns:
            Tuple of (normalized_score, daily_pct_rank, trailing_pct, prob_elite)
            or None if not found.
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
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO)

    from src.backtest.universe_scorer import UniverseScorer
    scorer = UniverseScorer(m01_path='models/m01_prototype/model.json')
    scores_df = scorer.score_from_t3('2024-01-01', '2024-03-31')
    lookup = ScoreLookup(scores_df)

    print("\nStats:")
    for k, v in lookup.get_stats().items():
        print(f"  {k}: {v}")

    dates = lookup.get_available_dates()
    if dates:
        test_date = dates[len(dates) // 2]
        candidates = lookup.get_candidates(
            test_date, min_score=30.0, min_percentile=0.0, rank_by='trailing'
        )
        print(f"\nCandidates for {test_date} (sorted by trailing pct):")
        for ticker, score, trailing, prob_elite in candidates[:10]:
            print(f"  {ticker}: score={score:.1f}, trailing_pct={trailing:.3f}, "
                  f"prob_elite={prob_elite:.3f}")
