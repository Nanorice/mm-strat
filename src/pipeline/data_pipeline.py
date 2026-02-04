"""
Data Pipeline - Orchestrates data generation for ML training
=============================================================

The DataPipeline class manages all data preparation steps:

    scan()     → d1.parquet  - SEPA trade candidates from screener
    features() → d2.parquet  - Trade entries enriched with features  
    hydrate()  → d2r_*.parquet - Multi-day price trajectories
    label()    → d3_*.parquet  - Triple barrier labels for M02

Data Flow:
    M01: scan → features → train
    M02: scan → hydrate → label → train
"""

import logging
import time
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import timedelta
from typing import Optional

logger = logging.getLogger("DataPipeline")


class DataPipeline:
    """
    Orchestrates data generation steps for ML training.
    
    Attributes:
        output_dir: Directory for saving data files (default: data/ml)
    """
    
    def __init__(self, output_dir: str = 'data/ml'):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    # =========================================================================
    # STEP 1: SCAN (Generate D1 - Trade Candidates)
    # =========================================================================
    def scan(
        self, 
        start_date: str, 
        end_date: str, 
        threshold: float = 15.0,
        save: bool = True
    ) -> pd.DataFrame:
        """
        Run SEPA screener to generate trade candidates (D1).
        
        Args:
            start_date: Start date for simulation (YYYY-MM-DD)
            end_date: End date for simulation (YYYY-MM-DD)
            threshold: Success threshold in % (default: 15.0)
            save: Save result to d1.parquet (default: True)
            
        Returns:
            DataFrame with columns: [date, ticker, label, return_pct, days_held, exit_reason]
        """
        from src.data_engine import DataRepository, CacheMode
        from src.features import FeatureEngineer
        from src.strategy import SEPAStrategy
        from src.trading_config import TradingConfig
        from src.utils import get_latest_trading_day
        from src.trade_simulator_fast import FastTradeSimulator
        
        logger.info(f"Step 1: SCAN - Simulating trades from {start_date} to {end_date}")
        start_time = time.time()
        
        # Calculate outcome window
        end_dt = pd.to_datetime(end_date)
        ideal_outcome_end = end_dt + timedelta(days=90)
        latest_available = get_latest_trading_day()
        outcome_end = min(ideal_outcome_end, latest_available).strftime('%Y-%m-%d')
        
        if ideal_outcome_end > latest_available:
            logger.warning(f"Outcome window capped at {outcome_end} (ideal: {ideal_outcome_end.strftime('%Y-%m-%d')})")
        
        # Initialize components
        data_repo = DataRepository()
        benchmark_data = data_repo.get_benchmark_data(mode=CacheMode.CACHE_ONLY)
        
        if benchmark_data is None:
            raise RuntimeError("Failed to load benchmark (SPY) data.")
        
        feature_engine = FeatureEngineer(benchmark_data=benchmark_data)
        strategy = SEPAStrategy(benchmark_data=benchmark_data)
        trading_config = TradingConfig(success_threshold_pct=threshold)
        
        simulator = FastTradeSimulator(
            data_repo=data_repo,
            strategy=strategy,
            feature_engine=feature_engine,
            start_date=start_date,
            end_date=end_date,
            outcome_end=outcome_end,
            config=trading_config
        )
        
        d1 = simulator.run_simulation(show_progress=True, n_jobs=-1)
        
        # Standardize column names
        d1 = d1.rename(columns={'entry_date': 'date'})
        d1['date'] = pd.to_datetime(d1['date'])
        
        elapsed = time.time() - start_time
        logger.info(f"   Generated {len(d1)} trades in {elapsed:.1f}s")
        logger.info(f"   Win rate: {d1['label'].mean():.1%} ({d1['label'].sum()} wins)")
        
        if save:
            path = self.output_dir / 'd1.parquet'
            d1.to_parquet(path, index=False)
            logger.info(f"   Saved to {path}")
        
        return d1
    
    # =========================================================================
    # STEP 2: FEATURES (Generate D2 - Feature Enrichment)
    # =========================================================================
    def features(
        self,
        d1: pd.DataFrame,
        n_jobs: int = -1,
        save: bool = True,
        include_m03: bool = True,
        apply_preprocessing: bool = True,
    ) -> pd.DataFrame:
        """
        Enrich D1 trades with ML features at entry date (D2).

        Args:
            d1: DataFrame from scan() step
            n_jobs: Parallel workers (-1 = all CPUs)
            save: Save result to d2.parquet (default: True)
            include_m03: Add M03 regime features (default: True)
            apply_preprocessing: Apply FeaturePreprocessor to generate log_* features (default: True)

        Returns:
            DataFrame with trade info + features
        """
        from joblib import Parallel, delayed
        from tqdm import tqdm
        from src.data_engine import DataRepository, CacheMode
        from src.features import FeatureEngineer
        from src.fundamental_merger import FundamentalMerger
        
        logger.info(f"Step 2: FEATURES - Enriching {len(d1)} trades")
        start_time = time.time()
        
        # Suppress verbose logging
        logging.getLogger('src.features').setLevel(logging.WARNING)
        logging.getLogger('src.fundamental_merger').setLevel(logging.WARNING)
        
        # Phase 1: Load price data
        data_repo = DataRepository()
        tickers = d1['ticker'].unique().tolist()
        
        logger.info(f"   Phase 1: Loading {len(tickers)} tickers...")
        price_cache = {}
        for ticker in tqdm(tickers, desc="Loading prices", unit="ticker"):
            try:
                df = data_repo.get_ticker_data(ticker, mode=CacheMode.CACHE_ONLY)
                if df is not None and not df.empty:
                    price_cache[ticker] = df
            except Exception:
                pass
        
        logger.info(f"   Loaded {len(price_cache)}/{len(tickers)} tickers")
        
        # Phase 2: Compute features in parallel
        benchmark_data = data_repo.get_benchmark_data(mode=CacheMode.CACHE_ONLY)
        
        def _compute_features(ticker: str, df: pd.DataFrame) -> tuple:
            try:
                feature_engine = FeatureEngineer(benchmark_data=benchmark_data)
                df_features = feature_engine.calculate_lightweight_features(df)
                
                try:
                    df_features = feature_engine.calculate_heavyweight_features(df_features, ticker)
                except Exception:
                    pass
                
                try:
                    fund_merger = FundamentalMerger(force_cache_only=True)
                    df_features = fund_merger.merge_ticker_data(ticker, df_features)
                except Exception:
                    pass
                
                return ticker, df_features, None
            except Exception as e:
                return ticker, None, str(e)
        
        logger.info(f"   Phase 2: Computing features (parallel)...")
        results = Parallel(n_jobs=n_jobs, prefer="processes")(
            delayed(_compute_features)(t, df)
            for t, df in tqdm(price_cache.items(), desc="Features", unit="ticker")
        )
        
        enriched_cache = {t: df for t, df, err in results if df is not None}
        logger.info(f"   Computed features for {len(enriched_cache)} tickers")
        
        # Phase 3: Extract trade rows
        logger.info(f"   Phase 3: Extracting trade rows...")
        trade_rows = []
        
        for _, trade in tqdm(d1.iterrows(), desc="Extracting", unit="trade", total=len(d1)):
            ticker = trade['ticker']
            trade_date = pd.to_datetime(trade['date'])
            
            if ticker not in enriched_cache:
                continue
            
            df = enriched_cache[ticker]
            
            # Ensure DatetimeIndex
            if not isinstance(df.index, pd.DatetimeIndex):
                if 'date' in df.columns:
                    df = df.set_index('date')
                else:
                    continue
            
            # Find row for trade date
            if trade_date in df.index:
                row = df.loc[trade_date].to_dict()
            else:
                available = df.index[df.index <= trade_date]
                if len(available) == 0:
                    continue
                closest = available[-1]
                if (trade_date - closest).days > 7:
                    continue
                row = df.loc[closest].to_dict()
            
            row['date'] = trade['date']
            row['ticker'] = ticker
            trade_rows.append(row)
        
        logger.info(f"   Extracted {len(trade_rows)}/{len(d1)} trades")
        
        if not trade_rows:
            raise RuntimeError("No features extracted. Check data availability.")
        
        # Merge with D1 labels
        d2 = pd.DataFrame(trade_rows)
        d1_keys = d1[['date', 'ticker', 'label', 'return_pct', 'days_held', 'exit_reason']]
        merged = pd.merge(d1_keys, d2, on=['date', 'ticker'], how='inner')
        
        # Phase 4: Add M03 regime features
        if include_m03:
            from src.pipeline.m03_regime import M03RegimeCalculator, verify_m03_features
            
            logger.info("   Phase 4: Adding M03 regime features...")
            
            m03_path = Path('models/m03_history.parquet')
            if m03_path.exists():
                try:
                    # Generate normalized features
                    calc = M03RegimeCalculator()
                    date_min = merged['date'].min().strftime('%Y-%m-%d')
                    date_max = merged['date'].max().strftime('%Y-%m-%d')
                    
                    m03_features = calc.generate_m01_features(
                        start_date=date_min,
                        end_date=date_max,
                    )
                    
                    # Merge by date
                    m03_features = m03_features.reset_index()
                    m03_features['date'] = pd.to_datetime(m03_features['date'])
                    merged = pd.merge(merged, m03_features, on='date', how='left')
                    
                    # Verify and report
                    verification = verify_m03_features(merged, raise_on_error=False)
                    n_m03_cols = len(M03RegimeCalculator.M01_FEATURE_COLUMNS)
                    
                    if verification['nulls']['total'] > 0:
                        null_pct = verification['nulls']['total'] / len(merged) / n_m03_cols * 100
                        logger.warning(f"   M03 features have {null_pct:.1f}% NaN (likely pre-2003 trades)")
                    
                    logger.info(f"   Added {n_m03_cols} M03 features")
                except Exception as e:
                    logger.warning(f"   Failed to add M03 features: {e}")
            else:
                logger.warning(f"   M03 history not found at {m03_path}, skipping")

        # Phase 5: Apply feature preprocessing (log transforms, winsorization)
        if apply_preprocessing:
            preprocessing_path = Path('models/preprocessing_config.json')
            if preprocessing_path.exists():
                try:
                    from src.feature_preprocessor import FeaturePreprocessor

                    logger.info("   Phase 5: Applying feature preprocessing...")
                    preprocessor = FeaturePreprocessor.load(str(preprocessing_path))
                    n_cols_before = len(merged.columns)
                    merged = preprocessor.transform(merged)
                    n_new_cols = len(merged.columns) - n_cols_before
                    logger.info(f"   Applied preprocessing: added {n_new_cols} log_* features")
                except Exception as e:
                    logger.warning(f"   Failed to apply preprocessing: {e}")
            else:
                logger.warning(f"   Preprocessing config not found at {preprocessing_path}, skipping")

        elapsed = time.time() - start_time
        logger.info(f"   Final: {len(merged)} rows, {len(merged.columns)} columns in {elapsed:.1f}s")

        if save:
            path = self.output_dir / 'd2.parquet'
            merged.to_parquet(path, index=False)
            logger.info(f"   Saved to {path}")

        return merged
    
    # =========================================================================
    # STEP 3: HYDRATE (Generate D2R - Multi-Day Trajectories)
    # =========================================================================
    def hydrate(
        self, 
        d1: pd.DataFrame, 
        horizon_days: Optional[int] = None,
        n_jobs: int = -1,
        save: bool = True
    ) -> pd.DataFrame:
        """
        Rehydrate D1 trades with multi-day price trajectories.
        
        Args:
            d1: DataFrame from scan() step
            horizon_days: Fixed horizon in days (None = use SEPA exit)
            n_jobs: Parallel workers (-1 = all CPUs)
            save: Save result to d2r_*.parquet (default: True)
            
        Returns:
            Long-format DataFrame with one row per trade-day
        """
        from src.data_engine import DataRepository, CacheMode
        from src.features import FeatureEngineer
        from src.fundamental_merger import FundamentalMerger
        from src.dataset_rehydrator import DatasetRehydrator
        
        mode = "horizon" if horizon_days else "sepa"
        logger.info(f"Step 3: HYDRATE - {len(d1)} trades ({mode} mode)")
        start_time = time.time()
        
        # Filter trades if using fixed horizon
        if horizon_days:
            end_date = d1['date'].max()
            cutoff = end_date - pd.Timedelta(days=horizon_days)
            d1_filtered = d1[d1['date'] <= cutoff].copy()
            logger.info(f"   Filtered to {len(d1_filtered)} trades (cutoff: {cutoff.strftime('%Y-%m-%d')})")
        else:
            d1_filtered = d1
        
        # Initialize components
        data_repo = DataRepository()
        benchmark_data = data_repo.get_benchmark_data(mode=CacheMode.CACHE_ONLY)
        feature_engine = FeatureEngineer(benchmark_data=benchmark_data)
        fund_merger = FundamentalMerger(force_cache_only=True)
        
        rehydrator = DatasetRehydrator(
            data_repo, feature_engine, fund_merger,
            horizon_days=horizon_days
        )
        d2r = rehydrator.rehydrate_trades(d1_filtered, n_jobs=n_jobs)
        
        elapsed = time.time() - start_time
        avg_days = len(d2r) / len(d1_filtered) if len(d1_filtered) > 0 else 0
        logger.info(f"   Generated {len(d2r):,} rows ({avg_days:.1f} days/trade) in {elapsed:.1f}s")
        
        if save:
            if horizon_days:
                path = self.output_dir / f'd2r_{horizon_days}d.parquet'
            else:
                path = self.output_dir / 'd2r_sepa.parquet'
            d2r.to_parquet(path, index=False)
            logger.info(f"   Saved to {path} ({path.stat().st_size / 1024 / 1024:.1f} MB)")
        
        return d2r
    
    # =========================================================================
    # STEP 4: LABEL (Generate D3 - Triple Barrier Labels)
    # =========================================================================
    def label(
        self,
        d2r: pd.DataFrame,
        k_sl: float = 1.0,
        k_tp: float = 4.0,
        min_tp: float = 0.20,
        max_time: int = 30,
        n_jobs: int = -1,
        save: bool = True,
        horizon_days: Optional[int] = None,
        include_m03: bool = True,
        apply_preprocessing: bool = True
    ) -> pd.DataFrame:
        """
        Apply triple barrier labels to rehydrated data (D3).

        Args:
            d2r: DataFrame from hydrate() step
            k_sl: Stop loss ATR multiplier (default: 1.0)
            k_tp: Target ATR multiplier (default: 4.0)
            min_tp: Minimum profit target (default: 0.20 = 20%)
            max_time: Maximum time barrier in days (default: 30)
            n_jobs: Parallel workers (-1 = all CPUs)
            save: Save result to d3_*.parquet (default: True)
            horizon_days: Horizon used for file naming (None = 120d default)
            include_m03: Add M03 regime features (default: True)
            apply_preprocessing: Apply FeaturePreprocessor to generate log_* features (default: True)

        Returns:
            DataFrame with y_meta labels (1 = TP hit, 0 = SL/Time hit)
        """
        from src.triple_barrier_labeler import (
            TripleBarrierLabeler,
            HybridBarrierParams,
            compute_expectancy
        )

        # Default horizon for file naming
        effective_horizon = horizon_days if horizon_days is not None else 120

        logger.info(f"Step 4: LABEL - Applying triple barriers")
        logger.info(f"   Params: k_sl={k_sl}, k_tp={k_tp}, min_tp={min_tp:.0%}, max_time={max_time}")
        start_time = time.time()

        params = HybridBarrierParams(
            k_sl=k_sl,
            k_tp=k_tp,
            min_tp=min_tp,
            max_time=max_time,
            min_time=20
        )

        d3 = TripleBarrierLabeler.label_dataset(
            d2_rehydrated=d2r,
            params=params,
            binary_labels=True,
            n_jobs=n_jobs,
            use_vectorized=True
        )

        # Add M03 regime features
        if include_m03:
            from src.pipeline.m03_regime import M03RegimeCalculator, verify_m03_features

            m03_path = Path('models/m03_history.parquet')
            if m03_path.exists():
                try:
                    calc = M03RegimeCalculator()

                    # D3 may have 'Date' (from D2R) instead of 'date'
                    date_col = 'date' if 'date' in d3.columns else 'Date'
                    date_min = d3[date_col].min()
                    date_max = d3[date_col].max()

                    # Handle both datetime and string formats
                    if hasattr(date_min, 'strftime'):
                        date_min = date_min.strftime('%Y-%m-%d')
                        date_max = date_max.strftime('%Y-%m-%d')

                    m03_features = calc.generate_m01_features(
                        start_date=date_min,
                        end_date=date_max,
                    )

                    # Merge by date - align column names
                    m03_features = m03_features.reset_index()
                    m03_features['date'] = pd.to_datetime(m03_features['date'])

                    # Create merge key in d3 if needed
                    if date_col == 'Date':
                        d3['_merge_date'] = pd.to_datetime(d3['Date'])
                        m03_features = m03_features.rename(columns={'date': '_merge_date'})
                        d3 = pd.merge(d3, m03_features, on='_merge_date', how='left')
                        d3 = d3.drop(columns=['_merge_date'])
                    else:
                        d3['date'] = pd.to_datetime(d3['date'])
                        d3 = pd.merge(d3, m03_features, on='date', how='left')

                    n_m03_cols = len(M03RegimeCalculator.M01_FEATURE_COLUMNS)
                    logger.info(f"   Added {n_m03_cols} M03 features to D3")
                except Exception as e:
                    logger.warning(f"   Failed to add M03 features: {e}")
            else:
                logger.warning(f"   M03 history not found at {m03_path}, skipping")

        # Apply feature preprocessing (log transforms, winsorization)
        if apply_preprocessing:
            preprocessing_path = Path('models/preprocessing_config.json')
            if preprocessing_path.exists():
                try:
                    from src.feature_preprocessor import FeaturePreprocessor

                    preprocessor = FeaturePreprocessor.load(str(preprocessing_path))
                    n_cols_before = len(d3.columns)
                    d3 = preprocessor.transform(d3)
                    n_new_cols = len(d3.columns) - n_cols_before
                    logger.info(f"   Applied preprocessing: added {n_new_cols} log_* features")
                except Exception as e:
                    logger.warning(f"   Failed to apply preprocessing: {e}")
            else:
                logger.warning(f"   Preprocessing config not found at {preprocessing_path}, skipping")

        # Calculate metrics
        metrics = compute_expectancy(d3)
        tp_rate = (d3['y_meta'] == 1).mean()

        elapsed = time.time() - start_time
        logger.info(f"   Labeled {len(d3):,} trades in {elapsed:.1f}s")
        logger.info(f"   TP rate: {tp_rate:.1%}, Expectancy: {metrics['expectancy']:.2%}")

        if save:
            path = self.output_dir / f'd3_{effective_horizon}d.parquet'
            d3.to_parquet(path, index=False)
            logger.info(f"   Saved to {path}")

            # Also save D3 summary JSON for dashboard (includes barrier params)
            barrier_params = {'k_sl': k_sl, 'k_tp': k_tp, 'min_tp': min_tp, 'max_time': max_time}
            self._save_d3_summary(d3, effective_horizon, barrier_params)

        return d3
    
    def _save_d3_summary(self, d3: pd.DataFrame, horizon_days: int, barrier_params: dict = None):
        """Save D3 summary JSON for fast dashboard loading."""
        import json

        # Calculate barrier outcome rates
        n_total = len(d3)

        if 'barrier_outcome' in d3.columns:
            outcome_counts = d3['barrier_outcome'].value_counts()
            tp_rate = outcome_counts.get('TP', 0) / n_total * 100
            sl_rate = outcome_counts.get('SL', 0) / n_total * 100
            time_rate = outcome_counts.get('Time', 0) / n_total * 100
        else:
            # Use y_meta for label-based calculation
            tp_rate = (d3['y_meta'] == 1).mean() * 100
            sl_rate = (d3['y_meta'] == 0).mean() * 100
            time_rate = 0

        summary = {
            'generated_at': pd.Timestamp.now().isoformat(),
            'horizon_days': horizon_days,
            'total_trades': n_total,
            'tp_rate': float(tp_rate),
            'sl_rate': float(sl_rate),
            'time_rate': float(time_rate),
            'expectancy': float((d3['return_at_outcome'].mean() if 'return_at_outcome' in d3.columns else 0))
        }

        # Include barrier params if provided
        if barrier_params:
            summary['barrier_params'] = barrier_params

        path = self.output_dir / 'd3_summary.json'
        with open(path, 'w') as f:
            json.dump(summary, f, indent=2)

        logger.info(f"   Saved D3 summary to {path}")
    
    # =========================================================================
    # STEP 5: REHYDRATE D3 (Trajectories with Barrier Exits)
    # =========================================================================
    def rehydrate_d3(
        self,
        d1: pd.DataFrame,
        d3: pd.DataFrame,
        n_jobs: int = -1,
        save: bool = True,
        horizon_days: int = 120
    ) -> pd.DataFrame:
        """
        Rehydrate D3 using barrier exit days instead of SEPA exits.
        
        Creates multi-day trajectories truncated to barrier outcomes for backtesting.
        
        Args:
            d1: D1 trades DataFrame
            d3: D3 labels DataFrame (with days_to_outcome)
            n_jobs: Parallel workers (-1 = all CPUs)
            save: Save result to d3r_*.parquet (default: True)
            horizon_days: Horizon used for file naming (default: 120)
            
        Returns:
            Rehydrated DataFrame with trajectories ending at barrier exit
        """
        from src.data_engine import DataRepository, CacheMode
        from src.features import FeatureEngineer
        from src.fundamental_merger import FundamentalMerger
        from src.dataset_rehydrator import DatasetRehydrator
        
        logger.info(f"Step 5: REHYDRATE D3 - {len(d3)} trades with barrier exits")
        start_time = time.time()
        
        # Filter D1 to only trades in D3
        d3_trade_ids = set(d3['trade_id'])
        d1_filtered = d1[d1['trade_id'].isin(d3_trade_ids)].copy()
        logger.info(f"   Filtered D1 to {len(d1_filtered):,} trades")
        
        # Initialize components
        data_repo = DataRepository()
        benchmark_data = data_repo.get_benchmark_data(mode=CacheMode.CACHE_ONLY)
        feature_engine = FeatureEngineer(benchmark_data=benchmark_data)
        fund_merger = FundamentalMerger(force_cache_only=True)
        
        # Rehydrate with D3 exits
        rehydrator = DatasetRehydrator(
            data_repo, feature_engine, fund_merger,
            d3_exits=d3  # Use barrier exits from D3
        )
        d3r = rehydrator.rehydrate_trades(d1_filtered, n_jobs=n_jobs)
        
        elapsed = time.time() - start_time
        avg_days = len(d3r) / len(d1_filtered) if len(d1_filtered) > 0 else 0
        logger.info(f"   Rehydrated: {len(d3r):,} rows ({avg_days:.1f} days/trade) in {elapsed:.1f}s")
        
        if save:
            path = self.output_dir / f'd3r_{horizon_days}d.parquet'
            d3r.to_parquet(path, index=False)
            logger.info(f"   Saved to {path} ({path.stat().st_size / 1024 / 1024:.1f} MB)")
        
        return d3r
    
    # =========================================================================
    # UTILITY: Load existing data files
    # =========================================================================
    def load_d1(self) -> pd.DataFrame:
        """Load existing D1 data."""
        path = self.output_dir / 'd1.parquet'
        if not path.exists():
            raise FileNotFoundError(f"D1 not found: {path}")
        return pd.read_parquet(path)
    
    def load_d2(self) -> pd.DataFrame:
        """Load existing D2 data."""
        path = self.output_dir / 'd2.parquet'
        if not path.exists():
            raise FileNotFoundError(f"D2 not found: {path}")
        return pd.read_parquet(path)
    
    def load_d2r(self, horizon_days: Optional[int] = None) -> pd.DataFrame:
        """Load existing D2R data."""
        if horizon_days:
            path = self.output_dir / f'd2r_{horizon_days}d.parquet'
        else:
            path = self.output_dir / 'd2r_sepa.parquet'
        if not path.exists():
            raise FileNotFoundError(f"D2R not found: {path}")
        return pd.read_parquet(path)
    
    def load_d3(self, horizon_days: Optional[int] = None) -> pd.DataFrame:
        """Load existing D3 data.
        
        Args:
            horizon_days: Horizon in days. If None, uses SEPA default (120d).
        """
        # Default to 120d (SEPA standard) when horizon not specified
        effective_horizon = horizon_days if horizon_days is not None else 120
        path = self.output_dir / f'd3_{effective_horizon}d.parquet'
        if not path.exists():
            raise FileNotFoundError(f"D3 not found: {path}")
        return pd.read_parquet(path)
