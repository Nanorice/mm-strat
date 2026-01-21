"""
Dataset Rehydrator - Expand d2 snapshots to multi-day trajectories
Phase 1A: Basic rehydration with SEPA exits (NO Triple Barrier yet)

This module rehydrates d1 trades from single entry-day snapshots to full
multi-day trajectories (entry → exit), enabling:
- Max drawdown & max favorable excursion analysis
- Feature evolution tracking during holding period
- Backtesting of alternative exit strategies
"""

from src.data_engine import DataRepository, CacheMode
from src.features import FeatureEngineer
from src.fundamental_merger import FundamentalMerger
from joblib import Parallel, delayed
import pandas as pd
import numpy as np
from tqdm import tqdm
import logging

logger = logging.getLogger(__name__)


class DatasetRehydrator:
    """
    Rehydrates d1 trades from single snapshots to multi-day trajectories.

    Phase 1A: Uses SEPA exit dates (from d1) as ground truth.
    Phase 2 (future): Will add Triple Barrier Method.

    Output schema matches d2 columns + adds: trade_id, day_in_trade, is_exit_day,
    max_drawdown_pct, max_favorable_excursion_pct
    """

    def __init__(
        self,
        data_repo: DataRepository,
        feature_engine: FeatureEngineer,
        fund_merger: FundamentalMerger,
        horizon_days: int = None,
        d3_exits: pd.DataFrame = None
    ):
        """
        Initialize the rehydrator.

        Args:
            data_repo: DataRepository for price data
            feature_engine: FeatureEngineer for technical features
            fund_merger: FundamentalMerger for fundamental features
            horizon_days: Optional fixed horizon (None = use SEPA exit, else fixed horizon)
            d3_exits: Optional D3 dataframe with triple barrier exits (days_to_outcome per trade)
                      If provided, overrides horizon_days with trade-specific exit days.
        """
        self.data_repo = data_repo
        self.feature_engine = feature_engine
        self.fund_merger = fund_merger
        self.horizon_days = horizon_days
        
        # D3-based exit lookup (trade_id -> exit info)
        self.d3_exits = None
        if d3_exits is not None:
            # Normalize column names and create lookup
            d3_exits = d3_exits.copy()
            d3_exits.columns = [c.lower() for c in d3_exits.columns]
            self.d3_exits = d3_exits.set_index('trade_id')[['days_to_outcome', 'barrier_outcome', 'y_meta']].to_dict('index')

    def rehydrate_trades(
        self,
        d1_trades: pd.DataFrame,
        n_jobs: int = -1
    ) -> pd.DataFrame:
        """
        Main entry point: Rehydrate all trades from d1.

        Args:
            d1_trades: D1 trades DataFrame (from simulate_trades)
            n_jobs: Number of parallel workers (-1 = all CPUs)

        Returns:
            Long-format DataFrame (d2_rehydrated) with multi-day trajectories
        """
        logger.info(f"Rehydrating {len(d1_trades)} trades...")

        # Phase 1: Pre-load all price data (I/O bound, sequential)
        tickers = d1_trades['ticker'].unique()
        price_cache = self._preload_price_data(tickers)

        # Phase 2: Compute features per ticker (CPU bound, parallel)
        enriched_cache = self._compute_features_parallel(price_cache, n_jobs)

        # Phase 3: Rehydrate each trade (sequential - avoids pickling issues)
        logger.info(f"Rehydrating trades...")
        results = []
        for _, trade in tqdm(d1_trades.iterrows(), total=len(d1_trades), desc="Rehydrating"):
            result = self._rehydrate_single_trade(trade, enriched_cache)
            if not result.empty:
                results.append(result)

        # Phase 4: Concatenate and validate
        d2_rehydrated = pd.concat(results, ignore_index=True)
        self._validate_output(d2_rehydrated, d1_trades)

        logger.info(f"Rehydration complete: {len(d2_rehydrated):,} rows")
        return d2_rehydrated

    def _preload_price_data(self, tickers: list) -> dict:
        """Load price data for all tickers (reuse model_trainer pattern)."""
        logger.info(f"Loading price data for {len(tickers)} tickers...")
        price_cache = {}

        for ticker in tqdm(tickers, desc="Loading prices", unit="ticker"):
            try:
                df = self.data_repo.get_ticker_data(ticker, mode=CacheMode.CACHE_ONLY)
                if df is not None and not df.empty:
                    price_cache[ticker] = df
            except Exception as e:
                logger.debug(f"Failed to load {ticker}: {e}")

        logger.info(f"Loaded {len(price_cache)}/{len(tickers)} tickers")
        return price_cache

    def _compute_features_parallel(self, price_cache: dict, n_jobs: int) -> dict:
        """
        Compute all features per ticker in parallel.
        REUSES EXACT SAME LOGIC AS model_trainer.py::enrich_with_features
        """
        logger.info(f"Computing features for {len(price_cache)} tickers (parallel)...")

        # Get benchmark data to pass to workers (avoid pickling FeatureEngine)
        benchmark_data = self.feature_engine.benchmark_data

        def _compute_ticker_features(ticker: str, df: pd.DataFrame, benchmark: pd.Series) -> tuple:
            """Worker function (same as model_trainer.py)."""
            try:
                # Create engines inside worker (avoid pickling issues)
                from src.features import FeatureEngineer
                from src.fundamental_merger import FundamentalMerger

                feature_engine = FeatureEngineer(benchmark_data=benchmark)
                fund_merger = FundamentalMerger(force_cache_only=True)

                # Lightweight features (technical)
                df_features = feature_engine.calculate_lightweight_features(df)

                # Heavyweight features (alpha factors)
                try:
                    df_features = feature_engine.calculate_heavyweight_features(df_features, ticker)
                except Exception as e:
                    pass  # Silent fail for alpha factors

                # Fundamental features
                try:
                    df_enriched = fund_merger.merge_ticker_data(ticker, df_features)
                except Exception as e:
                    df_enriched = df_features  # Fall back to technical-only

                return ticker, df_enriched, None
            except Exception as e:
                return ticker, None, str(e)

        # Parallel execution
        results = Parallel(n_jobs=n_jobs, prefer="processes")(
            delayed(_compute_ticker_features)(ticker, df, benchmark_data)
            for ticker, df in tqdm(price_cache.items(), desc="Computing features", unit="ticker")
        )

        # Collect results
        enriched_cache = {}
        for ticker, df_enriched, error in results:
            if error:
                logger.warning(f"Feature computation failed for {ticker}: {error}")
            else:
                enriched_cache[ticker] = df_enriched

        logger.info(f"Features computed for {len(enriched_cache)}/{len(price_cache)} tickers")
        return enriched_cache

    def _rehydrate_single_trade(
        self,
        trade: pd.Series,
        enriched_cache: dict
    ) -> pd.DataFrame:
        """
        Rehydrate single trade → multi-row trajectory (entry to SEPA exit or fixed horizon).

        Phase 1A: Uses SEPA exit date from d1 (NO Triple Barrier).
        Phase 1B: Uses fixed horizon if horizon_days is set.

        Returns:
            DataFrame with d2 schema + trade_id, day_in_trade, is_exit_day, MDD, MFE
        """
        # 1. Extract trade metadata
        trade_id = trade['trade_id']
        ticker = trade['ticker']
        entry_date = pd.to_datetime(trade['date'])

        # 1B. Determine exit date based on exit mode
        # Priority: D3 exits > fixed horizon > SEPA exit
        if self.d3_exits is not None and trade_id in self.d3_exits:
            # D3 mode: Use trade-specific barrier exit
            d3_info = self.d3_exits[trade_id]
            days_to_exit = int(d3_info['days_to_outcome'])
            exit_date = entry_date + pd.Timedelta(days=days_to_exit)
        elif self.horizon_days is not None:
            # Phase 1B behavior: fixed horizon from entry
            exit_date = entry_date + pd.Timedelta(days=self.horizon_days)
        else:
            # Phase 1A behavior: use SEPA exit
            exit_date = pd.to_datetime(trade['exit_date'])

        # 2. Get enriched ticker data (OHLCV + all features)
        if ticker not in enriched_cache:
            logger.warning(f"Ticker {ticker} not in enriched cache, skipping trade {trade_id}")
            return pd.DataFrame()  # Return empty

        ticker_data = enriched_cache[ticker]

        # 3. Extract trajectory (entry_date to exit_date, inclusive)
        try:
            trajectory = ticker_data.loc[entry_date:exit_date].copy()
        except KeyError:
            logger.warning(f"Date range {entry_date} to {exit_date} not in data for {ticker}")
            return pd.DataFrame()

        if trajectory.empty:
            logger.warning(f"Empty trajectory for trade {trade_id} ({ticker})")
            return pd.DataFrame()

        # 4. Reset index to make 'date' a column (matches d2 schema)
        trajectory.reset_index(inplace=True)  # 'date' becomes column

        # 5. Add ONLY trade_id (keeps dataset clean for M02)
        # All other metadata can be derived:
        # - day_in_trade: can derive from (trade_id, date) groupby + rank
        # - is_exit_day: last row per trade_id
        # - MDD/MFE: belongs in backtesting, not dataset
        trajectory['trade_id'] = trade_id

        # 6. Broadcast d1 metadata to all rows (matches d2 schema)
        # NOTE: ticker already exists in trajectory
        trajectory['label'] = trade['label']
        trajectory['return_pct'] = trade['return_pct']
        trajectory['days_held'] = trade['days_held']
        trajectory['exit_reason'] = trade['exit_reason']
        
        # 7. Add D3 barrier info if available
        if self.d3_exits is not None and trade_id in self.d3_exits:
            d3_info = self.d3_exits[trade_id]
            trajectory['barrier_outcome'] = d3_info['barrier_outcome']
            trajectory['y_meta'] = d3_info['y_meta']

        return trajectory

    def _validate_output(self, df: pd.DataFrame, d1: pd.DataFrame):
        """Validate rehydrated dataset (simplified - no redundant columns)."""
        logger.info("Validating rehydrated dataset...")

        # 1. Trade ID coverage
        rehydrated_trades = set(df['trade_id'].unique())
        d1_trades = set(d1['trade_id'])
        missing = d1_trades - rehydrated_trades
        if missing:
            logger.warning(f"{len(missing)} trades missing from rehydrated dataset")

        # 2. Column count check (d2 + trade_id only)
        expected_cols = 129  # 128 from d2 + 1 (trade_id)
        if len(df.columns) != expected_cols:
            logger.warning(f"Column count: {len(df.columns)} (expected {expected_cols})")

        # 3. Chronological ordering (sample check on Date column)
        date_col = 'Date' if 'Date' in df.columns else 'date'
        for trade_id in df['trade_id'].unique()[:100]:
            trade_df = df[df['trade_id'] == trade_id]
            if not trade_df[date_col].is_monotonic_increasing:
                logger.error(f"Trade {trade_id} not chronologically ordered!")

        logger.info("✓ Validation complete")
