"""
Vectorized SEPA Screening Module
Shared between FastTradeSimulator and optimized_scanner for performance.

This module provides high-performance SEPA (Specific Entry Point Analysis) 
screening using vectorized numpy/pandas operations instead of loops.

Usage:
    from src.vectorized_screening import VectorizedSEPAScreener
    
    # Screen single ticker across all dates
    sepa_mask = VectorizedSEPAScreener.screen_single_ticker(df)
    
    # Screen at specific date
    is_qualified = VectorizedSEPAScreener.screen_at_date(df, date)
    
    # Batch screen universe at specific date
    qualifying, triggers = VectorizedSEPAScreener.batch_screen_universe(
        enriched_data, scan_date
    )
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
import logging

import config

logger = logging.getLogger(__name__)
consolidation_period = 20

class VectorizedSEPAScreener:
    """
    High-performance SEPA screening using vectorized operations.

    Implements Mark Minervini's SEPA (Specific Entry Point Analysis) criteria
    using numpy/pandas vectorized operations for optimal performance.

    Stage 2 Trend Template (C1-C9, all must be True):
    C1. Price > 150 SMA
    C2. Price > 200 SMA
    C3. 150 SMA > 200 SMA
    C4. 200 SMA trending up (> 200 SMA from 20 days ago)
    C5. 50 SMA > 150 SMA
    C6. Price > 50 SMA
    C7. Price > 30% above 52-week low (> Low_52W * 1.3)
    C8. Price within 15% of 52-week high (> High_52W * 0.85)
    C9. rs_rating in top 30% of universe (or rs_rating > 0 for single-ticker)

    Breakout Trigger (C10-C12):
    C10. Close > 20-day high (breakout)
    C11. Volume > 50-day average volume (volume spike)
    C12. RS > 63-day RS MA (relative strength confirmation)
    """
    
    @staticmethod
    def screen_single_ticker_split(df: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
        """
        Vectorized SEPA screening with separate trend and breakout masks.

        This method processes the entire time series at once using vectorized
        operations, returning BOTH trend and breakout signals separately.

        Args:
            df: DataFrame with OHLCV + indicators

        Returns:
            Tuple of (trend_ok, breakout_ok) boolean Series
            - trend_ok: C1-C9 (9 Stage 2 uptrend conditions including rs_rating)
            - breakout_ok: C10-C12 (3 breakout/volume/RS conditions)

        Example:
            >>> trend_mask, breakout_mask = VectorizedSEPAScreener.screen_single_ticker_split(aapl_df)
            >>> trend_mask.loc['2024-01-03']    # True if uptrend
            >>> breakout_mask.loc['2024-01-03'] # True if breaking out
        """
        # Check required columns
        required_cols = ['Close', 'SMA_150', 'SMA_200', 'SMA_50', 'High_52W', 'Low_52W', 'High', 'Volume']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            logger.warning(f"Missing columns for SEPA screening: {missing_cols}")
            return pd.Series(False, index=df.index), pd.Series(False, index=df.index)

        # Trend conditions (C1-C9) - Stage 2 uptrend
        c1 = df['Close'] > df['SMA_150']
        c2 = df['Close'] > df['SMA_200']
        c3 = df['SMA_150'] > df['SMA_200']
        c4 = df['SMA_200'] > df['SMA_200'].shift(consolidation_period)
        c5 = df['SMA_50'] > df['SMA_150']
        c6 = df['Close'] > df['SMA_50']
        c7 = df['Close'] > df['Low_52W'] * 1.3  # Above 52W low by 30%
        c8 = df['Close'] > df['High_52W'] * 0.85  # Within 15% of 52W high
        # C9: rs_rating > 0 (positive momentum proxy for single-ticker screening)
        # True cross-sectional rank is computed in batch_screen_universe()
        if 'rs_rating' in df.columns:
            c9 = df['rs_rating'] > 0
        else:
            c9 = pd.Series(True, index=df.index)  # Skip if not available
        trend_ok = c1 & c2 & c3 & c4 & c5 & c6 & c7 & c8 & c9

        # Breakout conditions (C10-C12) - Breakout trigger
        c10 = df['Close'] > df['High'].shift(1).rolling(consolidation_period).max()

        # C11: Volume spike confirmation (must exceed 1.3x average)
        vol_ma_50 = df['Volume'].shift(1).rolling(50).mean()
        vol_ratio = df['Volume'] / vol_ma_50
        c11 = vol_ratio > config.VOL_SPIKE_THRESHOLD

        # C12: RS confirmation using rs_rating (momentum-based)
        # Check if current rs_rating exceeds its 63-day moving average
        if 'rs_rating' in df.columns:
            c12 = df['rs_rating'] > df['rs_rating'].rolling(63).mean()
        else:
            c12 = pd.Series(True, index=df.index)  # Skip if not available

        breakout_ok = c10 & c11 & c12

        return trend_ok, breakout_ok

    @staticmethod
    def screen_single_ticker_trend_only(df: pd.DataFrame) -> pd.Series:
        """
        Vectorized trend screening using ONLY C1-C8 (excludes C9 RS ranking).

        This is used for EXIT detection where we only care about trend structure,
        not relative strength ranking. RS ranking (C9) should only affect ENTRY.

        Args:
            df: DataFrame with OHLCV + indicators

        Returns:
            Boolean Series indicating trend qualification (C1-C8 only)
        """
        # Check required columns
        required_cols = ['Close', 'SMA_150', 'SMA_200', 'SMA_50', 'High_52W', 'Low_52W']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            logger.warning(f"Missing columns for trend screening: {missing_cols}")
            return pd.Series(False, index=df.index)

        # Trend conditions (C1-C8) ONLY - excludes C9 RS ranking
        c1 = df['Close'] > df['SMA_150']
        c2 = df['Close'] > df['SMA_200']
        c3 = df['SMA_150'] > df['SMA_200']
        c4 = df['SMA_200'] > df['SMA_200'].shift(consolidation_period)
        c5 = df['SMA_50'] > df['SMA_150']
        c6 = df['Close'] > df['SMA_50']
        c7 = df['Close'] > df['Low_52W'] * 1.3  # Above 52W low by 30%
        c8 = df['Close'] > df['High_52W'] * 0.85  # Within 15% of 52W high

        # NO C9 for exits - RS ranking should not trigger exits
        trend_ok = c1 & c2 & c3 & c4 & c5 & c6 & c7 & c8

        return trend_ok

    @staticmethod
    def screen_single_ticker(df: pd.DataFrame) -> pd.Series:
        """
        Vectorized SEPA screening for a single ticker across all dates.

        This method processes the entire time series at once using vectorized
        operations, which is ~100x faster than looping through dates.

        Returns full SEPA qualification (trend AND breakout).

        Args:
            df: DataFrame with OHLCV + indicators (must have: Close, SMA_50,
                SMA_150, SMA_200, High_52W, RS)

        Returns:
            Boolean Series indexed by date where True = SEPA qualified

        Example:
            >>> sepa_mask = VectorizedSEPAScreener.screen_single_ticker(aapl_df)
            >>> sepa_mask
            2024-01-01    False
            2024-01-02    False
            2024-01-03    True   # Qualified on this date
            2024-01-04    True
            dtype: bool
        """
        trend_ok, breakout_ok = VectorizedSEPAScreener.screen_single_ticker_split(df)
        return trend_ok & breakout_ok
    
    @staticmethod
    def screen_at_date(df: pd.DataFrame, date: pd.Timestamp) -> bool:
        """
        Check SEPA qualification for a single ticker at a specific date.
        
        This is a convenience method that wraps screen_single_ticker() for
        checking a single date. For checking multiple dates, use 
        screen_single_ticker() directly for better performance.
        
        Args:
            df: DataFrame with indicators
            date: Date to check
        
        Returns:
            True if SEPA qualified at the given date, False otherwise
        
        Example:
            >>> is_qualified = VectorizedSEPAScreener.screen_at_date(
            ...     aapl_df, pd.Timestamp('2024-01-15')
            ... )
            >>> print(is_qualified)
            True
        """
        if date not in df.index:
            return False
        
        # Use vectorized method and extract single date
        sepa_mask = VectorizedSEPAScreener.screen_single_ticker(df)
        return bool(sepa_mask.loc[date]) if date in sepa_mask.index else False
    
    @staticmethod
    def batch_screen_universe(enriched_data: Dict[str, pd.DataFrame],
                             scan_date: pd.Timestamp) -> Tuple[List[str], List[str], List[str]]:
        """
        Screen multiple tickers with separate trend and breakout tracking.

        This method uses vectorized SEPA screening for each ticker's full
        history, then extracts results for the scan_date. Returns 3 lists
        for different use cases.

        Includes cross-sectional C9 check: rs_rating must be in top 30% of universe.

        Args:
            enriched_data: Dict mapping ticker -> DataFrame with indicators
            scan_date: Date to scan (will use nearest date before if not found)

        Returns:
            Tuple of (trend_ok_tickers, breakout_tickers, new_trigger_tickers)
            - trend_ok_tickers: Pass C1-C9 (use for REMOVAL decisions)
            - breakout_tickers: Pass C10-C12 (informational)
            - new_trigger_tickers: Pass ALL C1-C12 + 0->1 transition (use for ADDITION)

        Example:
            >>> trend_ok, breakout, triggers = VectorizedSEPAScreener.batch_screen_universe(
            ...     enriched_data, pd.Timestamp('2024-01-15')
            ... )
            >>> print(f"Trend OK: {len(trend_ok)}, Breakout: {len(breakout)}, New triggers: {len(triggers)}")
            Trend OK: 150, Breakout: 45, New triggers: 12
        """
        # Phase 1: Collect rs_rating for all tickers at scan_date for cross-sectional ranking
        rs_ratings = {}
        ticker_dates = {}
        for ticker, df in enriched_data.items():
            try:
                if scan_date in df.index:
                    ticker_date = scan_date
                else:
                    available = df.index[df.index <= scan_date]
                    if len(available) == 0:
                        continue
                    ticker_date = available[-1]
                ticker_dates[ticker] = ticker_date

                if 'rs_rating' in df.columns and ticker_date in df.index:
                    rs_val = df.loc[ticker_date, 'rs_rating']
                    if pd.notna(rs_val):
                        rs_ratings[ticker] = rs_val
            except Exception:
                continue

        # Compute top 30% threshold (70th percentile)
        if rs_ratings:
            rs_values = np.array(list(rs_ratings.values()))
            rs_threshold = np.percentile(rs_values, 70)  # Top 30% = above 70th percentile
            top_30_tickers = {t for t, v in rs_ratings.items() if v >= rs_threshold}
            logger.debug(f"RS rank: {len(top_30_tickers)}/{len(rs_ratings)} tickers in top 30% (threshold: {rs_threshold:.4f})")
        else:
            top_30_tickers = set()
            logger.warning("No rs_rating data available for cross-sectional ranking")

        # Phase 2: Screen each ticker
        trend_ok_tickers = []
        breakout_tickers = []
        new_trigger_tickers = []

        for ticker, df in enriched_data.items():
            try:
                ticker_date = ticker_dates.get(ticker)
                if ticker_date is None:
                    continue

                # Get split masks (C1-C8 trend, C10-C12 breakout)
                trend_mask, breakout_mask = VectorizedSEPAScreener.screen_single_ticker_split(df)

                # Apply cross-sectional C9 filter (top 30% rs_rating)
                passes_c9 = ticker in top_30_tickers
                trend_with_c9 = trend_mask & passes_c9 if passes_c9 else pd.Series(False, index=trend_mask.index)
                full_sepa_mask = trend_with_c9 & breakout_mask

                # Check trend_ok at scan_date (C1-C9)
                if ticker_date in trend_with_c9.index and trend_with_c9.loc[ticker_date]:
                    trend_ok_tickers.append(ticker)

                # Check breakout_ok at scan_date (C10-C12)
                if ticker_date in breakout_mask.index and breakout_mask.loc[ticker_date]:
                    breakout_tickers.append(ticker)

                # Check if fully qualified (C1-C12) for new trigger detection
                if ticker_date in full_sepa_mask.index and full_sepa_mask.loc[ticker_date]:
                    # Check if this is a new trigger (0->1 transition)
                    if ticker_date in df.index:
                        ticker_idx = df.index.get_loc(ticker_date)

                        if ticker_idx > 0:
                            prev_date = df.index[ticker_idx - 1]

                            # Check if previous date was NOT qualified
                            if prev_date in full_sepa_mask.index:
                                was_qualified_prev = full_sepa_mask.loc[prev_date]

                                if not was_qualified_prev:
                                    # Was False yesterday, True today = new trigger
                                    new_trigger_tickers.append(ticker)
                        else:
                            # First date in series, count as new trigger if qualified
                            new_trigger_tickers.append(ticker)

            except Exception as e:
                logger.debug(f"Error screening {ticker}: {e}")
                continue

        logger.info(f"Batch screen: {len(trend_ok_tickers)} trend OK (C1-C9), "
                   f"{len(breakout_tickers)} breakout OK (C10-C12), "
                   f"{len(new_trigger_tickers)} new triggers")

        return trend_ok_tickers, breakout_tickers, new_trigger_tickers
    
    @staticmethod
    def find_entry_signals(df: pd.DataFrame, 
                          start_date: Optional[pd.Timestamp] = None,
                          end_date: Optional[pd.Timestamp] = None) -> pd.DatetimeIndex:
        """
        Find all entry signals (0->1 SEPA transitions) in a date range.
        
        This is useful for historical backtesting to find all dates where
        SEPA criteria were newly met.
        
        Args:
            df: DataFrame with indicators
            start_date: Optional start date (inclusive)
            end_date: Optional end date (inclusive)
        
        Returns:
            DatetimeIndex of all dates with new SEPA signals
        
        Example:
            >>> signals = VectorizedSEPAScreener.find_entry_signals(
            ...     aapl_df, 
            ...     start_date=pd.Timestamp('2024-01-01'),
            ...     end_date=pd.Timestamp('2024-12-31')
            ... )
            >>> print(f"Found {len(signals)} entry signals in 2024")
            Found 5 entry signals in 2024
        """
        # Get SEPA mask for full time series
        sepa_mask = VectorizedSEPAScreener.screen_single_ticker(df)
        
        # Filter to date range if specified
        if start_date is not None:
            sepa_mask = sepa_mask[sepa_mask.index >= start_date]
        if end_date is not None:
            sepa_mask = sepa_mask[sepa_mask.index <= end_date]
        
        # Find 0->1 transitions
        sepa_prev = sepa_mask.shift(1, fill_value=False)
        new_triggers = sepa_mask & ~sepa_prev
        
        # Return dates where new_triggers is True
        return sepa_mask.index[new_triggers]
    
    @staticmethod
    def find_exit_signals(df: pd.DataFrame,
                         entry_date: pd.Timestamp,
                         end_date: Optional[pd.Timestamp] = None) -> Optional[pd.Timestamp]:
        """
        Find the first exit signal (1->0 SEPA transition) after entry.
        
        This is used for trade exit detection when SEPA criteria are no longer met.
        
        Args:
            df: DataFrame with indicators
            entry_date: Entry date for the trade
            end_date: Optional end date to search until
        
        Returns:
            Date of first exit signal, or None if SEPA criteria still met
        
        Example:
            >>> exit_date = VectorizedSEPAScreener.find_exit_signals(
            ...     aapl_df,
            ...     entry_date=pd.Timestamp('2024-01-15'),
            ...     end_date=pd.Timestamp('2024-06-30')
            ... )
            >>> print(f"Exit signal on: {exit_date}")
            Exit signal on: 2024-03-20
        """
        # Get SEPA mask for dates after entry
        future_df = df[df.index > entry_date]
        
        if end_date is not None:
            future_df = future_df[future_df.index <= end_date]
        
        if future_df.empty:
            return None
        
        # Get SEPA status for future dates
        sepa_mask = VectorizedSEPAScreener.screen_single_ticker(future_df)
        
        # Find first False (exit signal)
        exit_mask = ~sepa_mask
        
        if exit_mask.any():
            # Return first date where SEPA is False
            exit_idx = exit_mask.to_numpy().argmax()
            return future_df.index[exit_idx]
        
        return None
    
    # ====================================================================
    # 2D MATRIX METHODS - For Date-Range Vectorization
    # ====================================================================
    
    @staticmethod
    def build_2d_matrix(ticker_data: Dict[str, pd.DataFrame],
                       start_date: pd.Timestamp,
                       end_date: pd.Timestamp) -> pd.DataFrame:
        """
        Build 2D matrix of all tickers × all dates in range.
        
        This creates a "long format" DataFrame where each row represents
        one ticker on one date, enabling vectorized operations across
        both dimensions (tickers and time).
        
        Args:
            ticker_data: Dict mapping ticker -> DataFrame with features
            start_date: Start date (inclusive, typically lookback_date)
            end_date: End date (inclusive)
        
        Returns:
            DataFrame with columns: ticker, date, Close, SMA_50, SMA_150, etc.
            Shape: (num_tickers * num_dates, num_features)
        
        Example:
            >>> # Build matrix for 500 tickers over 17 days
            >>> df_matrix = VectorizedSEPAScreener.build_2d_matrix(
            ...     ticker_data,
            ...     start_date=pd.Timestamp('2024-11-16'),  # 1 day lookback
            ...     end_date=pd.Timestamp('2024-12-03')
            ... )
            >>> print(df_matrix.shape)
            (9000, 20)  # 500 tickers × 18 days × ~20 features
        """
        rows = []
        
        for ticker, df in ticker_data.items():
            if df is None or df.empty:
                continue
            
            # Filter to date range
            mask = (df.index >= start_date) & (df.index <= end_date)
            df_range = df[mask].copy()
            
            if df_range.empty:
                continue
            
            # Add ticker and date columns
            df_range['ticker'] = ticker
            df_range['date'] = df_range.index
            
            rows.append(df_range)
        
        if not rows:
            return pd.DataFrame()
        
        # Concatenate all tickers into single DataFrame
        df_matrix = pd.concat(rows, ignore_index=True)
        
        logger.info(f"Built 2D matrix: {df_matrix.shape[0]} rows "
                   f"({len(ticker_data)} tickers × {(end_date - start_date).days + 1} dates)")
        
        return df_matrix
    
    @staticmethod
    def add_sepa_status_column(df_matrix: pd.DataFrame) -> pd.DataFrame:
        """
        Add SEPA_Status column to entire 2D matrix using vectorized operations.
        
        This computes SEPA qualification for ALL ticker-date combinations
        in a single vectorized operation, much faster than looping.
        
        Args:
            df_matrix: 2D DataFrame from build_2d_matrix()
        
        Returns:
            DataFrame with SEPA_Status column added (True/False per row)
        
        Example:
            >>> df_matrix = build_2d_matrix(ticker_data, start, end)
            >>> df_matrix = add_sepa_status_column(df_matrix)
            >>> print(df_matrix[['ticker', 'date', 'SEPA_Status']].head())
            ticker       date  SEPA_Status
            AAPL   2024-11-17         True
            AAPL   2024-11-18         True
            MSFT   2024-11-17        False
            ...
        """
        # Check for required columns
        required_cols = ['Close', 'SMA_150', 'SMA_200', 'SMA_50', 'High_52W', 'Low_52W']
        missing_cols = [col for col in required_cols if col not in df_matrix.columns]

        if missing_cols:
            logger.warning(f"Missing columns for SEPA screening: {missing_cols}")
            df_matrix['SEPA_Status'] = False
            return df_matrix

        # 9 SEPA trend conditions (C1-C9) - vectorized across ENTIRE matrix at once!
        df_matrix = df_matrix.sort_values(['ticker', 'date'])

        c1 = df_matrix['Close'] > df_matrix['SMA_150']
        c2 = df_matrix['Close'] > df_matrix['SMA_200']
        c3 = df_matrix['SMA_150'] > df_matrix['SMA_200']

        # C4: SMA_200 trending up (> 20 days ago per ticker)
        df_matrix['SMA_200_20d_ago'] = df_matrix.groupby('ticker')['SMA_200'].shift(20)
        c4 = df_matrix['SMA_200'] > df_matrix['SMA_200_20d_ago']

        c5 = df_matrix['SMA_50'] > df_matrix['SMA_150']
        c6 = df_matrix['Close'] > df_matrix['SMA_50']
        c7 = df_matrix['Close'] > df_matrix['Low_52W'] * 1.3  # 30% above 52W low
        c8 = df_matrix['Close'] > df_matrix['High_52W'] * 0.85  # Within 15% of 52W high

        # C9: rs_rating in top 30% per date (cross-sectional) AND positive
        if 'rs_rating' in df_matrix.columns:
            # Compute 70th percentile per date
            df_matrix['rs_pct70'] = df_matrix.groupby('date')['rs_rating'].transform(
                lambda x: x.quantile(0.70)
            )
            # Require BOTH top 30% AND positive momentum
            c9 = (df_matrix['rs_rating'] >= df_matrix['rs_pct70']) & (df_matrix['rs_rating'] > 0)
            df_matrix = df_matrix.drop(columns=['rs_pct70'])
        else:
            c9 = pd.Series(True, index=df_matrix.index)

        # Combine all conditions for ENTRY (includes C9)
        df_matrix['SEPA_Status'] = c1 & c2 & c3 & c4 & c5 & c6 & c7 & c8 & c9

        # Add Trend_Status for EXITS (C1-C8 only, excludes C9 RS ranking)
        # RS ranking should not trigger exits - only trend structure matters
        df_matrix['Trend_Status'] = c1 & c2 & c3 & c4 & c5 & c6 & c7 & c8

        # Clean up temporary column
        df_matrix = df_matrix.drop(columns=['SMA_200_20d_ago'])

        logger.info(f"SEPA status computed for {len(df_matrix)} rows")

        return df_matrix
    
    @staticmethod
    def find_signal_transitions(df_matrix: pd.DataFrame,
                               date_range_start: pd.Timestamp,
                               date_range_end: pd.Timestamp) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Find all buy (0->1) and sell (1->0) signal transitions in the matrix.
        
        Uses groupby + shift to detect transitions per ticker, ensuring proper
        boundary detection (1-day lookback prevents false positives).
        
        CRITICAL: Only returns transitions that occur WITHIN the scan range.
        Transitions on the lookback day are excluded to avoid tagging tickers
        that triggered before the scan period.
        
        Args:
            df_matrix: 2D DataFrame with SEPA_Status column added
            date_range_start: Start of actual scan range (excludes lookback day)
            date_range_end: End of scan range
        
        Returns:
            Tuple of (buy_signals_df, sell_signals_df)
            Each DataFrame contains rows where transition occurred
        
        Example:
            >>> # Matrix includes lookback (Nov 16) + scan range (Nov 17-Dec 3)
            >>> buy_signals, sell_signals = find_signal_transitions(
            ...     df_matrix,
            ...     date_range_start=pd.Timestamp('2024-11-17'),  # Excludes Nov 16
            ...     date_range_end=pd.Timestamp('2024-12-03')
            ... )
            >>> print(f"Buy signals: {len(buy_signals)}")
            >>> print(f"Sell signals: {len(sell_signals)}")
        """
        # Ensure sorted by ticker and date for shift to work correctly
        df_sorted = df_matrix.sort_values(['ticker', 'date']).copy()
        
        # Get previous day's SEPA status (per ticker using groupby)
        df_sorted['SEPA_prev'] = df_sorted.groupby('ticker')['SEPA_Status'].shift(1)
        
        # Buy signal: False -> True (0 -> 1 transition)
        # Current day is True AND previous day is False
        df_sorted['is_buy'] = (df_sorted['SEPA_Status'] == True) & (df_sorted['SEPA_prev'] == False)
        
        # Sell signal: True -> False (1 -> 0 transition)
        # Current day is False AND previous day is True
        df_sorted['is_sell'] = (df_sorted['SEPA_Status'] == False) & (df_sorted['SEPA_prev'] == True)
        
        # CRITICAL FILTER: Only include signals within the actual scan range
        # This excludes transitions on the lookback day
        in_range = (df_sorted['date'] >= date_range_start) & (df_sorted['date'] <= date_range_end)
        
        buy_signals = df_sorted[df_sorted['is_buy'] & in_range].copy()
        sell_signals = df_sorted[df_sorted['is_sell'] & in_range].copy()
        
        logger.info(f"Found {len(buy_signals)} buy signals and {len(sell_signals)} sell signals "
                   f"in range {date_range_start.date()} to {date_range_end.date()}")
        
        return buy_signals, sell_signals
