"""
Optimized Trade Simulator - Vectorized & Parallelized Implementation

This is a high-performance version of TradeSimulator that uses:
1. Vectorized operations (numpy/pandas) instead of loops
2. Parallel processing for per-ticker simulation
3. Batch SEPA screening across all tickers/dates at once

Performance: ~10-20x faster than event-driven simulator for large datasets.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import logging
from pathlib import Path
from multiprocessing import Pool, cpu_count
from functools import partial

from src.data_engine import DataRepository
from src.strategy import SEPAStrategy
from src.features import FeatureEngineer
from src.trade_simulator import Trade, TradeSimulator
from src.trading_config import TradingConfig
from src.vectorized_screening import VectorizedSEPAScreener

logger = logging.getLogger(__name__)


class FastTradeSimulator(TradeSimulator):
    """
    Vectorized trade simulator for fast Dataset B generation.

    Inherits from TradeSimulator but overrides run_simulation() with
    a vectorized implementation that's 10-20x faster.
    """

    def run_simulation(self, show_progress=True, n_jobs=1) -> pd.DataFrame:
        """
        Runs vectorized simulation with optional parallelization.

        Args:
            show_progress: If True, displays progress bar
            n_jobs: Number of parallel workers (1=sequential, -1=all CPUs)

        Returns:
            DataFrame with completed trades (Dataset B)
        """
        logger.info("Starting FAST vectorized simulation...")

        # Step 1: Load and prepare data (same as original)
        logger.info("Loading price data for universe...")
        tickers = self.data_repo.update_universe()

        # Skip cache update - just load existing cached data directly
        # (Cache validation is slow for large universes - update cache separately if needed)
        logger.info(f"Loading cached data for {len(tickers)} tickers (skipping cache update)...")
        ticker_data = self.data_repo.get_batch_data(tickers)

        # Filter valid data
        valid_ticker_data = {
            t: df for t, df in ticker_data.items()
            if df is not None and len(df) >= 200
        }
        logger.info(f"Loaded {len(valid_ticker_data)} tickers with sufficient data")

        # Step 2: Calculate features for all tickers (batch processing)
        if show_progress:
            print("Computing features for all tickers...")
        logger.info("Calculating features in batch...")
        enriched_data = self.feature_engine.process_universe_batch(valid_ticker_data, show_progress=show_progress)
        logger.info(f"Features calculated for {len(enriched_data)} tickers")

        # Step 3: SEPA signal detection using strategy (same as original)
        if show_progress:
            print("Detecting SEPA signals...")
        logger.info("Detecting SEPA signals...")
        all_signals = self._detect_signals_using_strategy(enriched_data, show_progress=show_progress)
        if show_progress:
            print(f"Found {len(all_signals)} SEPA signals\n")
        logger.info(f"Found {len(all_signals)} total SEPA signals across all dates")

        # Step 4: Simulate trades (parallel or sequential)
        if all_signals.empty:
            logger.warning("No SEPA signals detected - no trades to simulate")
            all_trades = []
        elif n_jobs == 1:
            # Sequential processing
            logger.info("Simulating trades sequentially...")
            all_trades = self._simulate_trades_sequential(all_signals, enriched_data, show_progress)
        else:
            # Parallel processing
            if n_jobs == -1:
                n_jobs = cpu_count()
            logger.info(f"Simulating trades in parallel ({n_jobs} workers)...")
            all_trades = self._simulate_trades_parallel(all_signals, enriched_data, n_jobs, show_progress)

        logger.info(f"Simulation complete! Generated {len(all_trades)} trades")

        # Step 5: Convert to DataFrame
        if not all_trades:
            logger.warning("No trades generated!")
            return pd.DataFrame()

        # Step 6: Sort trades chronologically and assign sequential IDs
        # This ensures trade_ids are globally unique and ordered by entry_date
        logger.info("Assigning chronological trade IDs...")
        all_trades.sort(key=lambda t: t.entry_date)
        
        # Reassign trade IDs in chronological order
        for idx, trade in enumerate(all_trades, start=1):
            trade.trade_id = idx
        
        dataset_b = pd.DataFrame([trade.to_dict() for trade in all_trades])

        # Verify IDs are sequential
        assert dataset_b['trade_id'].nunique() == len(dataset_b), "Trade IDs are not unique!"
        assert dataset_b['trade_id'].min() == 1, "Trade IDs should start at 1"
        assert dataset_b['trade_id'].max() == len(dataset_b), "Trade IDs should be sequential"

        return dataset_b

    def _detect_signals_using_strategy(self, enriched_data: Dict[str, pd.DataFrame], show_progress: bool = True) -> pd.DataFrame:
        """
        Detect SEPA signals using vectorized screening per ticker.
        
        This optimized version processes each ticker once (vectorized) instead of
        scanning all tickers for each day sequentially.
        
        Additionally, this method now adds a 'SEPA_Status' column to each ticker's
        dataframe for the full outcome window, enabling vectorized exit detection.
        
        Returns DataFrame with columns: ticker, entry_date, entry_price, ...
        """
        all_signals = []
        
        # Try to show progress
        if show_progress:
            try:
                from tqdm import tqdm
                ticker_iterator = tqdm(enriched_data.items(), desc="Detecting Signals", unit="ticker",
                                     total=len(enriched_data))
            except ImportError:
                ticker_iterator = enriched_data.items()
                logger.info(f"Processing {len(enriched_data)} tickers...")
        else:
            ticker_iterator = enriched_data.items()
        
        # Suppress strategy logging during batch scans when showing progress bar
        strategy_logger = logging.getLogger('src.strategy')
        original_level = strategy_logger.level
        if show_progress:
            strategy_logger.setLevel(logging.WARNING)
        
        # Process each ticker once (vectorized)
        for ticker, df in ticker_iterator:
            # OPTIMIZATION: Calculate SEPA status for the FULL outcome window
            # This allows vectorized exit detection later
            df_outcome_window = df[(df.index >= self.start_date) & (df.index <= self.outcome_end)]
            
            if df_outcome_window.empty:
                continue
            
            # Vectorized SEPA screening for all dates at once
            sepa_mask_full = self._vectorized_sepa_screen(df_outcome_window)
            
            # Add SEPA_Status column to the original dataframe for vectorized exit detection
            df.loc[df_outcome_window.index, 'SEPA_Status'] = sepa_mask_full
            
            # Filter to entry period for signal detection
            df_entry_period = df_outcome_window[(df_outcome_window.index <= self.end_date)]
            sepa_mask = sepa_mask_full[df_outcome_window.index <= self.end_date]
            
            # Find new triggers (SEPA = True today, SEPA = False yesterday)
            sepa_prev = sepa_mask.shift(1, fill_value=False)
            new_triggers = sepa_mask & ~sepa_prev
            
            # Extract trigger dates
            trigger_dates = df_entry_period.index[new_triggers].tolist()
            
            for date in trigger_dates:
                all_signals.append({
                    'ticker': ticker,
                    'entry_date': date,
                    'entry_price': df_entry_period.loc[date, 'Close']
                })
        
        # Restore original logging level
        strategy_logger.setLevel(original_level)
        
        return pd.DataFrame(all_signals)

    def _vectorized_signal_detection_OLD(self, enriched_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """
        Vectorized SEPA signal detection across all tickers and dates.

        Returns DataFrame with columns: date, ticker, entry_price, ...
        """
        all_signals = []

        # Debug: Check first ticker's columns
        first_ticker = list(enriched_data.keys())[0] if enriched_data else None
        if first_ticker:
            logger.debug(f"Sample ticker {first_ticker} columns: {enriched_data[first_ticker].columns.tolist()}")

        for ticker, df in enriched_data.items():
            # Filter to entry period only
            df_entry_period = df[(df.index >= self.start_date) & (df.index <= self.end_date)]

            if df_entry_period.empty:
                continue

            # Vectorized SEPA screening for all dates at once
            sepa_mask = self._vectorized_sepa_screen(df_entry_period)

            # Find new triggers (SEPA = True today, SEPA = False yesterday)
            sepa_prev = sepa_mask.shift(1, fill_value=False)
            new_triggers = sepa_mask & ~sepa_prev

            # Extract trigger dates
            trigger_dates = df_entry_period.index[new_triggers].tolist()

            for date in trigger_dates:
                all_signals.append({
                    'ticker': ticker,
                    'entry_date': date,
                    'entry_price': df_entry_period.loc[date, 'Close'],
                    'rs': df_entry_period.loc[date, 'RS'] if 'RS' in df_entry_period.columns else np.nan,
                    'volume_ratio': df_entry_period.loc[date, 'Vol_Ratio'] if 'Vol_Ratio' in df_entry_period.columns else np.nan
                })

        return pd.DataFrame(all_signals)

    def _vectorized_sepa_screen(self, df: pd.DataFrame) -> pd.Series:
        """
        Vectorized SEPA screening (all dates at once).
        
        Now delegates to the shared VectorizedSEPAScreener for consistency
        across the codebase.

        Returns boolean Series indicating SEPA qualification at each date.
        """
        return VectorizedSEPAScreener.screen_single_ticker(df)

    def _simulate_trades_sequential(self, signals: pd.DataFrame, enriched_data: Dict[str, pd.DataFrame],
                                   show_progress: bool) -> List[Trade]:
        """Sequential trade simulation (one ticker at a time)."""
        all_trades = []

        try:
            from tqdm import tqdm
            ticker_groups = tqdm(signals.groupby('ticker'), desc="Simulating Trades",
                               disable=not show_progress, total=signals['ticker'].nunique())
        except ImportError:
            ticker_groups = signals.groupby('ticker')

        for ticker, ticker_signals in ticker_groups:
            ticker_trades = self._simulate_ticker_trades(
                ticker, ticker_signals, enriched_data[ticker]
            )
            all_trades.extend(ticker_trades)

        return all_trades

    def _simulate_trades_parallel(self, signals: pd.DataFrame, enriched_data: Dict[str, pd.DataFrame],
                                 n_jobs: int, show_progress: bool) -> List[Trade]:
        """Parallel trade simulation (multiple tickers simultaneously)."""
        # Prepare arguments for parallel processing
        ticker_groups = [
            (ticker, ticker_signals, enriched_data[ticker])
            for ticker, ticker_signals in signals.groupby('ticker')
        ]

        # Use multiprocessing Pool
        with Pool(processes=n_jobs) as pool:
            results = pool.starmap(self._simulate_ticker_trades, ticker_groups)

        # Flatten results
        all_trades = [trade for ticker_trades in results for trade in ticker_trades]

        return all_trades

    def _simulate_ticker_trades(self, ticker: str, signals: pd.DataFrame,
                               ticker_df: pd.DataFrame) -> List[Trade]:
        """
        Simulate all trades for a single ticker.

        Args:
            ticker: Stock symbol
            signals: DataFrame of entry signals for this ticker
            ticker_df: Enriched price data for this ticker

        Returns:
            List of completed Trade objects
        """
        trades = []
        active_trade = None
        last_exit_date = None

        # Process signals chronologically
        for _, signal in signals.iterrows():
            entry_date = signal['entry_date']

            # Check re-entry cooldown
            if last_exit_date is not None:
                if not self.config.allow_reentry:
                    continue  # Skip all future entries

                days_since_exit = (entry_date - last_exit_date).days
                if days_since_exit < self.config.reentry_cooldown_days:
                    continue  # Still in cooldown

            # Skip if already in trade
            if active_trade is not None:
                continue

            # Open trade
            entry_price = signal['entry_price']

            # Find exit using vectorized search
            exit_info = self._find_exit_vectorized(
                ticker_df, entry_date, entry_price
            )

            if exit_info is None:
                # Trade never exited (still open at outcome_end)
                continue

            exit_date, exit_price, exit_reason = exit_info

            # Create Trade object (ID will be assigned chronologically later)
            trade = Trade(
                trade_id=0,  # Placeholder - assigned chronologically in run_simulation()
                ticker=ticker,
                entry_date=entry_date,
                entry_price=entry_price
            )

            # Close trade
            trade.close(
                exit_date=exit_date,
                exit_price=exit_price,
                exit_reason=exit_reason,
                ticker_df=ticker_df,
                labeling_function=self.config.labeling_function
            )

            trades.append(trade)
            last_exit_date = exit_date

        return trades

    def _find_exit_vectorized(self, ticker_df: pd.DataFrame, entry_date: pd.Timestamp,
                              entry_price: float) -> Optional[Tuple[pd.Timestamp, float, str]]:
        """
        FULLY vectorized exit detection for a single trade.
        
        Uses precomputed SEPA_Status column to eliminate sequential loops.
        This provides 2-3x speedup compared to the previous implementation.

        Returns: (exit_date, exit_price, exit_reason) or None if no exit
        """
        # Get data from entry onwards until outcome_end
        future_df = ticker_df[(ticker_df.index > entry_date) & (ticker_df.index <= self.outcome_end)]

        if future_df.empty:
            return None

        # Exit Rule 1: Trend break (FULLY VECTORIZED using SEPA_Status column)
        if self.config.exit_on_trend_break:
            if 'SEPA_Status' in future_df.columns:
                # Vectorized search: Find first date where SEPA_Status becomes False
                trend_break_mask = ~future_df['SEPA_Status']
                
                if trend_break_mask.any():
                    # argmax() returns index of first True value (first SEPA=False)
                    exit_idx = trend_break_mask.to_numpy().argmax()
                    exit_date = future_df.index[exit_idx]
                    exit_price = future_df.loc[exit_date, 'Close']
                    return (exit_date, exit_price, 'trend_break')
            else:
                # Fallback to old method if SEPA_Status column is missing
                # (This should never happen with the optimized signal detection)
                logger.warning(f"SEPA_Status column missing for exit detection - using fallback")
                for date in future_df.index:
                    if not self.strategy.screen_candidates(ticker_df, date):
                        exit_date = date
                        exit_price = future_df.loc[exit_date, 'Close']
                        return (exit_date, exit_price, 'trend_break')

        # Exit Rule 2: Stop loss (already vectorized)
        if self.config.exit_on_stop_loss:
            stop_price = entry_price * (1 - self.config.stop_loss_pct / 100)
            stop_hit = future_df['Close'] <= stop_price

            if stop_hit.any():
                # argmax() returns index of first True value
                stop_idx = stop_hit.to_numpy().argmax()
                exit_date = future_df.index[stop_idx]
                exit_price = future_df.loc[exit_date, 'Close']
                return (exit_date, exit_price, 'stop_loss')

        # No exit found - hold until outcome_end
        if self.outcome_end in future_df.index:
            exit_date = self.outcome_end
            exit_price = future_df.loc[exit_date, 'Close']
            return (exit_date, exit_price, 'end_of_outcome_window')

        return None
