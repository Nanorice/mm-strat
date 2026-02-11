"""
Data Pipeline Test - Optimized D1/D2 Generation using Universe Parquet
=======================================================================

This is a TEST version of DataPipeline that uses pre-computed features
from the Universe Parquet file instead of re-computing them.

Key changes from data_pipeline.py:
1. scan() - Loads from Universe Parquet, applies C9 Top 30% filter (strict)
2. features() - Reuses lightweight features from Universe, only computes heavyweight
3. C11 filter - Uses VOL_SPIKE_THRESHOLD (1.3) to match production VCP standards

Output files are named with _test suffix to avoid overwriting production data.
"""

import logging
import time
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import timedelta
from typing import Optional, Dict

import config

logger = logging.getLogger("DataPipelineTest")


class DataPipelineTest:
    """
    Optimized data pipeline that uses Universe Parquet for pre-computed features.
    
    Output files:
        - d1_test.parquet: Trade candidates with C9 Top 30% filter
        - d2_test.parquet: Trade entries enriched with features
    """
    
    def __init__(self, output_dir: str = 'data/ml'):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    # =========================================================================
    # STEP 1: SCAN (Generate D1 - Trade Candidates) - OPTIMIZED
    # =========================================================================
    def scan(
        self, 
        start_date: str, 
        end_date: str, 
        threshold: float = 15.0,
        save: bool = True
    ) -> pd.DataFrame:
        """
        Run SEPA screener using Universe Parquet (D1 TEST).
        
        OPTIMIZATION: Loads pre-computed features from Universe instead of
        re-computing them. Uses vectorized screening across all tickers.
        
        C9 FIX: Enforces Top 30% RS rating filter (cross-sectional ranking).
        
        Args:
            start_date: Start date for simulation (YYYY-MM-DD)
            end_date: End date for simulation (YYYY-MM-DD)
            threshold: Success threshold in % (default: 15.0)
            save: Save result to d1_test.parquet (default: True)
            
        Returns:
            DataFrame with columns: [date, ticker, label, return_pct, days_held, exit_reason]
        """
        from src.universe_engine import UniverseEngine
        from src.data_engine import DataRepository, CacheMode
        from src.vectorized_screening import VectorizedSEPAScreener
        from src.trading_config import TradingConfig
        from src.utils import get_latest_trading_day
        
        logger.info(f"Step 1: SCAN (TEST) - Simulating trades from {start_date} to {end_date}")
        start_time = time.time()
        
        # Calculate outcome window
        end_dt = pd.to_datetime(end_date)
        ideal_outcome_end = end_dt + timedelta(days=90)
        latest_available = get_latest_trading_day()
        outcome_end = min(ideal_outcome_end, latest_available)
        outcome_end_str = outcome_end.strftime('%Y-%m-%d')
        
        if ideal_outcome_end > latest_available:
            logger.warning(f"Outcome window capped at {outcome_end_str}")
        
        # ====================================================================
        # Phase 1: Load Universe Data (Pre-computed Features)
        # ====================================================================
        logger.info("   Phase 1: Loading Universe Parquet...")
        universe_engine = UniverseEngine()
        
        # Load data for full outcome window (start_date to outcome_end)
        # We need lookback for SMA_200 trend check (C4)
        lookback_start = (pd.to_datetime(start_date) - timedelta(days=30)).strftime('%Y-%m-%d')
        
        df_universe = universe_engine._load_segments_for_range(lookback_start, outcome_end_str)
        
        if df_universe is None or len(df_universe) == 0:
            raise RuntimeError(f"No universe data found for {start_date} to {outcome_end_str}")
        
        # Reset index for processing
        df_universe = df_universe.reset_index()
        logger.info(f"   Loaded {len(df_universe):,} rows from Universe")
        
        # ====================================================================
        # Phase 2: Apply C1-C9 (Trend) + C10-C12 (Breakout) SEPA Screening
        # ====================================================================
        logger.info("   Phase 2: Applying SEPA filter (C1-C9 trend + C10-C12 breakout)...")
        
        # Normalize column names (universe uses lowercase)
        col_map = {
            'close': 'Close', 'high': 'High', 'low': 'Low',
            'open': 'Open', 'volume': 'Volume'
        }
        df_universe = df_universe.rename(columns=col_map)
        
        # Ensure required columns exist
        required = ['Close', 'SMA_50', 'SMA_150', 'SMA_200', 'High_52W', 'Low_52W', 'rs_rating']
        missing = [c for c in required if c not in df_universe.columns]
        if missing:
            raise ValueError(f"Missing columns in universe: {missing}")
        
        # Apply vectorized SEPA status (C1-C9 trend via cross-sectional rank)
        df_matrix = VectorizedSEPAScreener.add_sepa_status_column(df_universe)
        
        # ====================================================================
        # Phase 2b: Add C10-C12 Breakout Conditions
        # ====================================================================
        # C10: Close > 20-day high (breakout)
        df_matrix = df_matrix.sort_values(['ticker', 'date'])
        consolidation_period = 20
        
        df_matrix['High_20D'] = df_matrix.groupby('ticker')['High'].transform(
            lambda x: x.shift(1).rolling(consolidation_period).max()
        )
        c10 = df_matrix['Close'] > df_matrix['High_20D']
        
        # C11: Volume > 1.3x 50-day average (volume spike confirmation)
        # Match production VCP filter: Vol_Ratio > VOL_SPIKE_THRESHOLD (1.3)
        df_matrix['Vol_MA_50'] = df_matrix.groupby('ticker')['Volume'].transform(
            lambda x: x.shift(1).rolling(50).mean()
        )
        df_matrix['Vol_Ratio'] = df_matrix['Volume'] / df_matrix['Vol_MA_50']
        c11 = df_matrix['Vol_Ratio'] > config.VOL_SPIKE_THRESHOLD
        
        # C12: RS confirmation using rs_rating (momentum-based, not benchmark RS)
        if 'rs_rating' in df_matrix.columns:
            df_matrix['RS_MA_63'] = df_matrix.groupby('ticker')['rs_rating'].transform(
                lambda x: x.rolling(63).mean()
            )
            c12 = df_matrix['rs_rating'] > df_matrix['RS_MA_63']
        else:
            c12 = pd.Series(True, index=df_matrix.index)
        
        # Breakout status = C10 AND C11 AND C12
        df_matrix['Breakout_Status'] = c10 & c11 & c12
        
        # Entry signal = Trend OK (C1-C9) AND Breakout OK (C10-C12)
        # But we need to detect 0→1 transitions on the FULL signal
        df_matrix['SEPA_Full'] = df_matrix['SEPA_Status'] & df_matrix['Breakout_Status']
        
        # Replace SEPA_Status with the full signal for transition detection
        df_matrix['SEPA_Status'] = df_matrix['SEPA_Full']
        
        logger.info(f"   Trend OK (C1-C9): {df_matrix['SEPA_Full'].sum():,} / {len(df_matrix):,} rows")
        
        # ====================================================================
        # Phase 3: Detect Entry Signals (0→1 transitions on FULL SEPA)
        # ====================================================================
        logger.info("   Phase 3: Detecting entry signals (0→1 transitions)...")
        
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        
        buy_signals, _ = VectorizedSEPAScreener.find_signal_transitions(
            df_matrix,
            date_range_start=start_dt,
            date_range_end=end_dt
        )
        
        logger.info(f"   Found {len(buy_signals)} entry signals")
        
        if len(buy_signals) == 0:
            logger.warning("No entry signals found!")
            return pd.DataFrame()
        
        # ====================================================================
        # Phase 4: Simulate Trades (Forward Simulation for Labels)
        # ====================================================================
        logger.info("   Phase 4: Simulating trades for labels...")
        
        data_repo = DataRepository()
        trading_config = TradingConfig(success_threshold_pct=threshold)
        
        trades = []
        trade_id = 0
        
        # Group signals by ticker for efficient processing
        for ticker, ticker_signals in buy_signals.groupby('ticker'):
            try:
                # Load full price data for this ticker (for exit simulation)
                ticker_df = data_repo.get_ticker_data(ticker, mode=CacheMode.CACHE_ONLY)
                if ticker_df is None or len(ticker_df) < 50:
                    continue

                # Get SEPA status from our matrix for exit detection
                ticker_matrix = df_matrix[df_matrix['ticker'] == ticker].set_index('date')

                # Track active trade and cooldown for overlap prevention
                active_trade = None
                last_exit_date = None

                # Sort signals chronologically
                ticker_signals_sorted = ticker_signals.sort_values('date')

                for _, signal in ticker_signals_sorted.iterrows():
                    entry_date = signal['date']
                    entry_price = signal['Close']

                    # Check re-entry cooldown
                    if last_exit_date is not None:
                        if not trading_config.allow_reentry:
                            continue  # Skip all future entries

                        days_since_exit = (entry_date - last_exit_date).days
                        if days_since_exit < trading_config.reentry_cooldown_days:
                            continue  # Still in cooldown

                    # Skip if already in trade (prevent overlapping positions)
                    if active_trade is not None:
                        continue

                    # Find exit (trend break or end of outcome window)
                    exit_info = self._find_exit(
                        ticker_df, ticker_matrix, entry_date, entry_price,
                        outcome_end, trading_config
                    )

                    if exit_info is None:
                        continue

                    exit_date, exit_price, exit_reason = exit_info

                    # Calculate return and label
                    return_pct = (exit_price / entry_price - 1) * 100
                    label = 1 if return_pct >= trading_config.success_threshold_pct else 0
                    days_held = (exit_date - entry_date).days

                    trade_id += 1
                    trade_record = {
                        'trade_id': trade_id,
                        'ticker': ticker,
                        'date': entry_date,
                        'entry_price': entry_price,
                        'exit_date': exit_date,
                        'exit_price': exit_price,
                        'return_pct': return_pct,
                        'days_held': days_held,
                        'label': label,
                        'exit_reason': exit_reason
                    }
                    trades.append(trade_record)

                    # Update tracking for cooldown enforcement
                    # NOTE: active_trade is NOT set here - we allow immediate re-entry
                    # after trade completes (cooldown is handled by last_exit_date check)
                    last_exit_date = exit_date

            except Exception as e:
                logger.warning(f"Failed to process {ticker}: {e}")
                continue
        
        if not trades:
            logger.warning("No trades completed!")
            return pd.DataFrame()
        
        d1 = pd.DataFrame(trades)
        d1['date'] = pd.to_datetime(d1['date'])
        
        elapsed = time.time() - start_time
        logger.info(f"   Generated {len(d1)} trades in {elapsed:.1f}s")
        logger.info(f"   Win rate: {d1['label'].mean():.1%} ({d1['label'].sum()} wins)")
        
        if save:
            path = self.output_dir / 'd1_test.parquet'
            d1.to_parquet(path, index=False)
            logger.info(f"   Saved to {path}")
        
        return d1
    
    def _find_exit(
        self,
        ticker_df: pd.DataFrame,
        ticker_matrix: pd.DataFrame,
        entry_date: pd.Timestamp,
        entry_price: float,
        outcome_end: pd.Timestamp,
        config
    ):
        """Find exit date using Trend status (C1-C8 only) from pre-computed matrix."""
        # Get dates after entry
        future_dates = ticker_df.index[
            (ticker_df.index > entry_date) & (ticker_df.index <= outcome_end)
        ]

        if len(future_dates) == 0:
            return None

        # Check for trend break using Trend_Status column (C1-C8 only, excludes C9 RS)
        # Exit should be based on trend structure, not RS ranking
        if config.exit_on_trend_break:
            # Use Trend_Status if available (C1-C8 only), fallback to SEPA_Status
            status_col = 'Trend_Status' if 'Trend_Status' in ticker_matrix.columns else 'SEPA_Status'
            if status_col in ticker_matrix.columns:
                for date in future_dates:
                    if date in ticker_matrix.index:
                        if not ticker_matrix.loc[date, status_col]:
                            exit_price = ticker_df.loc[date, 'Close']
                            return (date, exit_price, 'trend_break')
        
        # Check stop loss
        if config.exit_on_stop_loss:
            stop_price = entry_price * (1 - config.stop_loss_pct / 100)
            for date in future_dates:
                if ticker_df.loc[date, 'Close'] <= stop_price:
                    exit_price = ticker_df.loc[date, 'Close']
                    return (date, exit_price, 'stop_loss')
        
        # Hold until outcome end
        if outcome_end in ticker_df.index:
            exit_price = ticker_df.loc[outcome_end, 'Close']
            return (outcome_end, exit_price, 'end_of_outcome_window')
        
        # Use last available date
        last_date = future_dates[-1]
        exit_price = ticker_df.loc[last_date, 'Close']
        return (last_date, exit_price, 'end_of_data')
    
    # =========================================================================
    # STEP 2: FEATURES (Generate D2 - Feature Enrichment) - OPTIMIZED
    # =========================================================================
    def features(
        self,
        d1: pd.DataFrame = None,
        n_jobs: int = -1,
        save: bool = True,
        include_m03: bool = True,
        apply_preprocessing: bool = True,
    ) -> pd.DataFrame:
        """
        Enrich D1 trades with ML features at entry date (D2 TEST).
        
        OPTIMIZATION: Reuses lightweight features from Universe Parquet.
        Only computes heavyweight (Alpha) features and fundamentals.
        
        Args:
            d1: DataFrame from scan() step (loads d1_test.parquet if None)
            n_jobs: Parallel workers (-1 = all CPUs)
            save: Save result to d2_test.parquet (default: True)
            include_m03: Add M03 regime features (default: True)
            apply_preprocessing: Apply FeaturePreprocessor (default: True)
            
        Returns:
            DataFrame with trade info + features
        """
        from tqdm import tqdm
        from src.universe_engine import UniverseEngine
        from src.data_engine import DataRepository, CacheMode
        from src.features import FeatureEngineer
        from src.fundamental_merger import FundamentalMerger
        
        # Load D1 if not provided
        if d1 is None:
            d1_path = self.output_dir / 'd1_test.parquet'
            if not d1_path.exists():
                raise FileNotFoundError(f"D1 test file not found: {d1_path}")
            d1 = pd.read_parquet(d1_path)
        
        logger.info(f"Step 2: FEATURES (TEST) - Enriching {len(d1)} trades")
        start_time = time.time()
        
        # Suppress verbose logging
        logging.getLogger('src.features').setLevel(logging.WARNING)
        logging.getLogger('src.fundamental_merger').setLevel(logging.WARNING)
        
        # ====================================================================
        # Phase 1: Load Lightweight Features from Universe
        # ====================================================================
        logger.info("   Phase 1: Loading lightweight features from Universe...")
        universe_engine = UniverseEngine()
        
        # Get date range from D1 trades
        date_min = d1['date'].min()
        date_max = d1['date'].max()
        
        # Load universe data for the full date range (batch load)
        df_universe = universe_engine._load_segments_for_range(
            date_min.strftime('%Y-%m-%d'),
            date_max.strftime('%Y-%m-%d')
        )
        
        if df_universe is None or len(df_universe) == 0:
            raise RuntimeError("No universe data found for trade dates!")
        
        # Reset index to get date and ticker as columns
        df_universe = df_universe.reset_index()
        logger.info(f"   Loaded {len(df_universe):,} rows from Universe")
        
        # Filter to only the (ticker, date) pairs we need
        trade_keys = d1[['ticker', 'date']].drop_duplicates()
        trade_keys['date'] = pd.to_datetime(trade_keys['date'])
        df_universe['date'] = pd.to_datetime(df_universe['date'])
        
        # Merge to get only the rows we need
        df_lightweight = df_universe.merge(trade_keys, on=['ticker', 'date'], how='inner')
        logger.info(f"   Matched {len(df_lightweight)} lightweight feature rows")
        
        # ====================================================================
        # Phase 2: Compute Heavyweight Features (Alpha Factors)
        # ====================================================================
        logger.info("   Phase 2: Computing heavyweight features...")
        
        data_repo = DataRepository()
        benchmark_data = data_repo.get_benchmark_data(mode=CacheMode.CACHE_ONLY)
        
        # Get tickers that need alpha calculation
        tickers = df_lightweight['ticker'].unique().tolist()
        
        # Load price data for heavyweight calculation
        logger.info(f"   Loading price data for {len(tickers)} tickers...")
        price_cache = {}
        for ticker in tqdm(tickers, desc="Loading prices"):
            try:
                df = data_repo.get_ticker_data(ticker, mode=CacheMode.CACHE_ONLY)
                if df is not None and len(df) >= 50:
                    price_cache[ticker] = df
            except Exception:
                pass
        
        # Compute heavyweight features in parallel
        def compute_heavyweight(ticker: str, df: pd.DataFrame):
            try:
                fe = FeatureEngineer(benchmark_data=benchmark_data)
                # Only compute heavyweight (alphas) - skip lightweight
                df_heavy = fe.calculate_heavyweight_features(df, ticker)
                return ticker, df_heavy, None
            except Exception as e:
                return ticker, None, str(e)
        
        logger.info("   Computing alpha factors...")
        
        # Use joblib for true multiprocessing (faster for CPU-bound work)
        from joblib import Parallel, delayed
        
        results = Parallel(n_jobs=n_jobs, prefer="processes")(
            delayed(compute_heavyweight)(t, df)
            for t, df in tqdm(price_cache.items(), desc="Alphas")
        )
        
        heavy_cache = {t: df for t, df, err in results if df is not None}
        logger.info(f"   Computed heavyweight for {len(heavy_cache)} tickers")
        
        # ====================================================================
        # Phase 3: Merge Lightweight + Heavyweight + Fundamentals
        # ====================================================================
        logger.info("   Phase 3: Merging features...")
        
        fund_merger = FundamentalMerger(force_cache_only=True)
        
        trade_rows = []
        for _, row in tqdm(d1.iterrows(), total=len(d1), desc="Merging"):
            ticker = row['ticker']
            trade_date = pd.to_datetime(row['date'])
            
            # Start with lightweight from universe
            lw_match = df_lightweight[
                (df_lightweight['ticker'] == ticker) &
                (df_lightweight['date'] == trade_date)
            ]
            
            if len(lw_match) == 0:
                continue
            
            merged = lw_match.iloc[0].to_dict()
            
            # Add heavyweight features
            if ticker in heavy_cache:
                heavy_df = heavy_cache[ticker]
                if isinstance(heavy_df.index, pd.DatetimeIndex) and trade_date in heavy_df.index:
                    heavy_row = heavy_df.loc[trade_date]
                    # Only add alpha columns
                    for col in heavy_row.index:
                        if col.startswith('alpha') and col not in merged:
                            merged[col] = heavy_row[col]
            
            # Add fundamental features
            try:
                fund_data = fund_merger.get_features_at_date(ticker, trade_date)
                if fund_data:
                    for k, v in fund_data.items():
                        if k not in merged:
                            merged[k] = v
            except Exception:
                pass
            
            # Add D1 labels
            merged['label'] = row['label']
            merged['return_pct'] = row['return_pct']
            merged['days_held'] = row['days_held']
            merged['exit_reason'] = row['exit_reason']
            merged['trade_id'] = row['trade_id']
            
            trade_rows.append(merged)
        
        if not trade_rows:
            raise RuntimeError("No features merged!")
        
        d2 = pd.DataFrame(trade_rows)
        
        # ====================================================================
        # Phase 4: Add M03 Regime Features (Optional)
        # ====================================================================
        if include_m03:
            try:
                from src.pipeline.m03_regime import M03RegimeCalculator
                
                m03_path = Path('models/m03_history.parquet')
                if m03_path.exists():
                    logger.info("   Phase 4: Adding M03 features...")
                    calc = M03RegimeCalculator()
                    
                    date_min = d2['date'].min().strftime('%Y-%m-%d')
                    date_max = d2['date'].max().strftime('%Y-%m-%d')
                    
                    m03_features = calc.generate_m01_features(date_min, date_max)
                    m03_features = m03_features.reset_index()
                    m03_features['date'] = pd.to_datetime(m03_features['date'])
                    
                    d2 = pd.merge(d2, m03_features, on='date', how='left')
                    logger.info(f"   Added M03 features")
            except Exception as e:
                logger.warning(f"   Failed to add M03: {e}")
        
        # ====================================================================
        # Phase 5: Apply Preprocessing (Optional)
        # ====================================================================
        if apply_preprocessing:
            preprocessing_path = Path('models/preprocessing_config.json')
            if preprocessing_path.exists():
                try:
                    from src.feature_preprocessor import FeaturePreprocessor
                    
                    logger.info("   Phase 5: Applying preprocessing...")
                    preprocessor = FeaturePreprocessor.load(str(preprocessing_path))
                    n_before = len(d2.columns)
                    d2 = preprocessor.transform(d2)
                    logger.info(f"   Added {len(d2.columns) - n_before} log_* features")
                except Exception as e:
                    logger.warning(f"   Preprocessing failed: {e}")
        
        elapsed = time.time() - start_time
        logger.info(f"   Final: {len(d2)} rows, {len(d2.columns)} columns in {elapsed:.1f}s")
        
        if save:
            path = self.output_dir / 'd2_test.parquet'
            d2.to_parquet(path, index=False)
            logger.info(f"   Saved to {path}")
        
        return d2
    
    # =========================================================================
    # UTILITY: Load existing data files
    # =========================================================================
    def load_d1(self) -> pd.DataFrame:
        """Load existing D1 test data."""
        path = self.output_dir / 'd1_test.parquet'
        if not path.exists():
            raise FileNotFoundError(f"D1 test not found: {path}")
        return pd.read_parquet(path)
    
    def load_d2(self) -> pd.DataFrame:
        """Load existing D2 test data."""
        path = self.output_dir / 'd2_test.parquet'
        if not path.exists():
            raise FileNotFoundError(f"D2 test not found: {path}")
        return pd.read_parquet(path)
