"""
Universe Scorer - Optimized Batch M01 Scoring for Backtesting
==============================================================
Pre-computes M01 calibrated scores using D2 dataset (pre-computed features).

Key Optimization: D2 contains 19,484 trade candidates with all features already
computed. Instead of iterating through each ticker and recomputing features,
we perform vectorized scoring on the entire dataset in one pass.

Output:
- Calibrated M01 score per (date, ticker)
- Normalized score: percentile rank within each ticker's signal history
- Daily percentile rank (for top 5% filtering)
"""

import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

import config
from src.feature_config import get_model_features

logger = logging.getLogger(__name__)

BACKTEST_DATA_DIR = config.DATA_DIR / 'backtest'
D2_PATH = config.DATA_DIR / 'ml' / 'd2.parquet'


class UniverseScorer:
    """
    Vectorized scorer using D2 dataset.

    D2 contains SEPA trade candidates with pre-computed features.
    This is orders of magnitude faster than per-ticker feature computation.
    """

    def __init__(
        self,
        m01_path: str = 'models/m01.json',
        calibration_path: str = 'models/m01_calibration.json',
    ):
        self.m01_path = Path(m01_path)
        self.calibration_path = Path(calibration_path)
        self.m01_model = None
        self.calibration_bins = None
        self.calibration_values = None
        self._m01_features: list[str] = []

    def load_model(self):
        """Load M01 model and calibration table."""
        import xgboost as xgb

        if not self.m01_path.exists():
            raise FileNotFoundError(f"M01 model not found: {self.m01_path}")

        self.m01_model = xgb.XGBRegressor()
        self.m01_model.load_model(str(self.m01_path))
        logger.info(f"Loaded M01 from {self.m01_path}")

        if self.calibration_path.exists():
            with open(self.calibration_path) as f:
                cal_data = json.load(f)
            deciles = cal_data.get('deciles', [])
            if deciles:
                # Build bins for pd.cut: [-inf, pred_max_1, pred_max_2, ..., inf]
                bins = [-np.inf]
                values = []
                for d in deciles:
                    bins.append(d['pred_max'])
                    values.append(d['calibrated_mean'])
                self.calibration_bins = bins
                self.calibration_values = values
                logger.info(f"Loaded calibration table with {len(deciles)} deciles")
        else:
            logger.warning(f"No calibration table at {self.calibration_path}")

        # Load features from model config (source of truth) instead of feature_config
        # Support both flat layout (models/m01_config.json) and folder layout (models/m01_v2/config.json)
        m01_config_path = self.m01_path.with_name('config.json')  # Folder layout
        if not m01_config_path.exists():
            m01_config_path = self.m01_path.with_name('m01_config.json')  # Flat layout

        if m01_config_path.exists():
            with open(m01_config_path) as f:
                m01_config = json.load(f)
            self._m01_features = m01_config.get('feature_columns', [])
            logger.info(f"M01 uses {len(self._m01_features)} features (from config)")
        else:
            # Fallback to feature_config if no model config
            self._m01_features = get_model_features('M01')
            logger.info(f"M01 uses {len(self._m01_features)} features (from feature_config)")

    def _merge_m03_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Merge M03 regime features from m03_feed.parquet if needed."""
        m03_features_needed = [f for f in self._m01_features if f.startswith('m03_')]
        if not m03_features_needed:
            return df

        # Check which features are already present
        missing_m03 = [f for f in m03_features_needed if f not in df.columns]
        if not missing_m03:
            logger.info("All M03 features already present in data")
            return df

        # Load M03 feed
        m03_path = BACKTEST_DATA_DIR / 'm03_feed.parquet'
        if not m03_path.exists():
            logger.warning(f"M03 feed not found at {m03_path}, cannot add regime features")
            return df

        logger.info(f"Loading M03 feed from {m03_path}")
        m03_df = pd.read_parquet(m03_path)

        # Map column names to expected M01 feature names
        column_map = {
            'composite_score': 'm03_score',
            'risk_pillar': 'm03_pillar_risk',
            'trend_pillar': 'm03_pillar_trend',
            'liq_pillar': 'm03_pillar_liq',
            'regime_cat': 'm03_regime_vol',  # Ordinal regime category
        }
        m03_df = m03_df.rename(columns=column_map)

        # Compute delta features (change over N days)
        m03_df = m03_df.sort_index()
        m03_df['m03_delta_5d'] = m03_df['m03_score'].diff(5)
        m03_df['m03_delta_20d'] = m03_df['m03_score'].diff(20)

        # Reset index for merge (date becomes a column)
        m03_df = m03_df.reset_index()

        # Ensure date columns are compatible
        df['date'] = pd.to_datetime(df['date'])
        m03_df['date'] = pd.to_datetime(m03_df['date'])

        # Merge on date (M03 is market-level, not ticker-level)
        m03_cols = ['date'] + [c for c in m03_df.columns if c.startswith('m03_')]
        df = df.merge(m03_df[m03_cols], on='date', how='left')

        present = [f for f in m03_features_needed if f in df.columns]
        still_missing = [f for f in m03_features_needed if f not in df.columns]
        logger.info(f"Added {len(present)} M03 features: {present}")
        if still_missing:
            logger.warning(f"Still missing M03 features: {still_missing}")

        return df

    def _compute_trailing_percentile(
        self,
        df: pd.DataFrame,
        window: int = 10,
    ) -> pd.Series:
        """
        Compute trailing N-day cohort percentile for each row.

        For each (date, ticker), calculate: what percentile is this score
        relative to ALL scores from the past N trading days?

        This captures persistent strength over a rolling window, not just
        single-day ranking which can be noisy.

        Args:
            df: DataFrame with 'date', 'ticker', 'calibrated_score' columns
            window: Number of trading days to include (default: 10)

        Returns:
            Series of trailing percentile ranks (0-1)
        """
        # Get unique trading dates sorted
        unique_dates = sorted(df['date'].unique())
        date_to_idx = {d: i for i, d in enumerate(unique_dates)}

        # Pre-build lookup: for each date, what are the past N dates?
        date_to_window_dates = {}
        for i, d in enumerate(unique_dates):
            start_idx = max(0, i - window + 1)
            date_to_window_dates[d] = unique_dates[start_idx:i + 1]

        # For each date, get all scores in the window
        results = []
        for date, group in df.groupby('date'):
            window_dates = date_to_window_dates[date]
            # Get all scores in the window (all tickers, all dates in window)
            window_mask = df['date'].isin(window_dates)
            window_scores = df.loc[window_mask, 'calibrated_score'].values

            # For each ticker today, compute percentile vs window scores
            for idx, row in group.iterrows():
                score = row['calibrated_score']
                # Percentile: proportion of window scores <= this score
                pct = (window_scores <= score).sum() / len(window_scores)
                results.append((idx, pct))

        # Convert to Series aligned with original index
        result_series = pd.Series(dict(results))
        return result_series.reindex(df.index)

    def _calibrate_vectorized(self, raw_scores: np.ndarray) -> np.ndarray:
        """Vectorized calibration using pd.cut."""
        if self.calibration_bins is None:
            return raw_scores

        # Use pd.cut to bin scores and map to calibrated values
        binned = pd.cut(
            raw_scores,
            bins=self.calibration_bins,
            labels=self.calibration_values,
            include_lowest=True,
        )
        # pd.cut returns Categorical; convert to float array
        return pd.Series(binned).astype(float).values

    def score_universe(
        self,
        start_date: str,
        end_date: str,
        output_path: Optional[Path] = None,
    ) -> pd.DataFrame:
        """
        Score the entire D2 universe with vectorized operations.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            output_path: Where to save (default: data/backtest/universe_scores.parquet)

        Returns:
            DataFrame with columns:
            - date, ticker: Row identifiers
            - calibrated_score: Raw calibrated M01 score
            - normalized_score: Percentile rank within ticker's history (0-100)
            - daily_pct_rank: Daily percentile rank (0-1)
        """
        if output_path is None:
            output_path = BACKTEST_DATA_DIR / 'universe_scores.parquet'
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if self.m01_model is None:
            self.load_model()

        # Load D2 (Hydrated)
        # We prefer using d2r_sepa.parquet if available as it provides DAILY M01 scores (hydrated)
        # rather than just sparse signals. This allows tracking score evolution.
        d2r_path = config.DATA_DIR / 'ml' / 'd2r_sepa.parquet'

        if d2r_path.exists():
            logger.info(f"Loading d2r (hydrated) from {d2r_path}")
            df = pd.read_parquet(d2r_path)
            # Normalize column names: d2r uses Title Case (Date, Ticker), d2 uses lower (date, ticker)
            df = df.rename(columns={'Date': 'date', 'Ticker': 'ticker'})
        else:
            logger.warning(f"d2r not found, falling back to sparse d2 at {D2_PATH}")
            df = pd.read_parquet(D2_PATH)

        logger.info(f"Loaded {len(df)} rows")

        # Merge M03 regime features if needed
        df = self._merge_m03_features(df)
        if not df.empty:
            logger.info(f"Date column dtype: {df['date'].dtype}")
            logger.info(f"Date range in file: {df['date'].min()} to {df['date'].max()}")

        # Filter date range
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        df = df[(df['date'] >= start_dt) & (df['date'] <= end_dt)]
        logger.info(f"After date filter ({start_date} to {end_date}): {len(df)} rows")

        if df.empty:
            raise ValueError("No data in specified date range")

        # Prepare feature matrix
        missing_features = [f for f in self._m01_features if f not in df.columns]
        if missing_features:
            # Try to generate missing log_* features inline
            # Log transform: sign(x) * log(1 + |x|)
            log_missing = [f for f in missing_features if f.startswith('log_')]
            if log_missing:
                logger.info(f"Generating {len(log_missing)} log-transformed features inline")
                for log_feat in log_missing:
                    base_feat = log_feat[4:]  # Remove 'log_' prefix
                    if base_feat in df.columns:
                        df[log_feat] = np.sign(df[base_feat]) * np.log1p(np.abs(df[base_feat]))
                    else:
                        logger.debug(f"Base feature {base_feat} not found for {log_feat}")
                # Re-check missing
                missing_features = [f for f in self._m01_features if f not in df.columns]

            # Try preprocessor for remaining features
            if missing_features:
                from src.feature_preprocessor import FeaturePreprocessor
                preproc_path = Path('models/preprocessing_config.json')

                if preproc_path.exists():
                    logger.info(f"Applying feature preprocessing from {preproc_path}")
                    try:
                        preprocessor = FeaturePreprocessor.load(str(preproc_path))
                        df = preprocessor.transform(df)
                        missing_features = [f for f in self._m01_features if f not in df.columns]
                    except Exception as e:
                        logger.error(f"Preprocessing failed: {e}")

        if missing_features:
            logger.warning(f"Missing features even after preprocessing: {missing_features}")
            for f in missing_features:
                df[f] = np.nan

        X = df[self._m01_features].copy()
        logger.info(f"Feature matrix shape: {X.shape}")

        # Convert categorical features to category dtype (required by XGBoost)
        categorical_cols = ['industry_id', 'sector_id']
        for col in categorical_cols:
            if col in X.columns:
                X[col] = X[col].fillna(-1).astype(int).astype('category')

        # Handle missing values - drop rows with too many NaNs
        nan_counts = X.isna().sum(axis=1)
        valid_mask = nan_counts < len(self._m01_features) * 0.2  # Allow up to 20% missing
        logger.info(f"Valid rows (<=20% missing): {valid_mask.sum()}/{len(df)}")

        # Fill remaining NaNs with column median for prediction (skip categoricals)
        numeric_cols = X.select_dtypes(include=[np.number]).columns
        X_filled = X.copy()
        X_filled[numeric_cols] = X_filled[numeric_cols].fillna(X[numeric_cols].median())

        # Vectorized prediction
        logger.info("Running M01 prediction (vectorized)...")
        raw_scores = self.m01_model.predict(X_filled)
        logger.info(f"Raw score range: {raw_scores.min():.3f} to {raw_scores.max():.3f}")

        # Vectorized calibration
        logger.info("Calibrating scores...")
        calibrated_scores = self._calibrate_vectorized(raw_scores)
        valid_cal = calibrated_scores[~np.isnan(calibrated_scores)]
        logger.info(f"Calibrated range: {valid_cal.min():.3f} to {valid_cal.max():.3f}")

        # Build result DataFrame
        result = pd.DataFrame({
            'date': df['date'].values,
            'ticker': df['ticker'].values,
            'calibrated_score': calibrated_scores,
        })

        # Mark invalid rows (too many missing features)
        result.loc[~valid_mask.values, 'calibrated_score'] = np.nan
        result = result.dropna(subset=['calibrated_score'])
        logger.info(f"After dropping invalid: {len(result)} rows")

        # Daily percentile rank: cross-sectional rank per day (0-1 scale)
        result['daily_pct_rank'] = result.groupby('date')['calibrated_score'].transform(
            lambda x: x.rank(pct=True)
        )

        # 10-Day Trailing Percentile: rolling cohort rank over past 10 trading days
        # This is the PRIMARY ranking metric for entry selection
        # Captures persistent strength, not just single-day spikes
        logger.info("Calculating 10-day trailing percentile...")
        result = result.sort_values(['date', 'ticker'])

        # For each row, we need the percentile of this stock's score vs ALL scores
        # in the past 10 trading days (including today)
        result['trailing_10d_pct'] = self._compute_trailing_percentile(result, window=10)

        # Normalized score: keep calibrated score scaled to 0-100 for human readability
        # This represents the M01 model's actual prediction (not a relative rank)
        # Used as an absolute floor filter to avoid buying truly weak candidates
        cal_min = result['calibrated_score'].min()
        cal_max = result['calibrated_score'].max()
        result['normalized_score'] = (
            (result['calibrated_score'] - cal_min) / (cal_max - cal_min) * 100
        )

        # Sort by date, daily rank desc (best candidates first)
        result = result.sort_values(['date', 'daily_pct_rank'], ascending=[True, False])

        # Save
        result.to_parquet(output_path, index=False)
        logger.info(f"Saved {len(result)} scores to {output_path}")

        # Statistics
        logger.info(f"Date range: {result['date'].min()} to {result['date'].max()}")
        logger.info(f"Unique tickers: {result['ticker'].nunique()}")
        logger.info(f"Unique dates: {result['date'].nunique()}")
        if result['date'].nunique() > 0:
            logger.info(f"Avg signals per day: {len(result) / result['date'].nunique():.1f}")
        else:
            logger.info("Avg signals per day: 0.0")
        logger.info(f"Normalized score: mean={result['normalized_score'].mean():.1f}, "
                    f"std={result['normalized_score'].std():.1f}")

        return result


def score_universe(
    start_date: str,
    end_date: str,
    output_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Convenience function to score the universe."""
    scorer = UniverseScorer()
    return scorer.score_universe(start_date, end_date, output_path)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    df = score_universe('2015-01-01', '2025-12-31')
    print(f"\nSample (last 20 rows):\n{df.tail(20)}")
