"""
Buy List Manager - Tracks SEPA candidates dynamically with performance metrics and change history.

This module manages two CSV files:
1. buy_list.csv - Current snapshot of active candidates with performance tracking
2. buy_list_history.csv - Complete audit trail of all ADDED/REMOVED events
"""

import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
from typing import Dict, Set, Optional
import logging

from src.indicators import TechnicalAnalysis
from config import DATA_DIR

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BuyListManager:
    """
    Manages dynamic buy_list and tracks historical changes.
    
    Features:
    - Automatic add/remove detection
    - Performance tracking since first_added date
    - Re-entry handling (new entry on re-add)
    - Backfill capability for historical analysis
    - Complete audit trail
    """
    
    def __init__(self, 
                 buy_list_path: str = None,
                 history_path: str = None):
        """
        Initialize Buy List Manager.
        
        Args:
            buy_list_path: Path to active buy_list CSV (default: data/buy_list.csv)
            history_path: Path to history log CSV (default: data/buy_list_history.csv)
        """
        self.buy_list_path = buy_list_path or Path(DATA_DIR) / 'buy_list.csv'
        self.history_path = history_path or Path(DATA_DIR) / 'buy_list_history.csv'
        
        # Ensure paths are Path objects
        self.buy_list_path = Path(self.buy_list_path)
        self.history_path = Path(self.history_path)
        
        # Create data directory if needed
        self.buy_list_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize empty files if they don't exist
        self._initialize_files()
    
    def _initialize_files(self):
        """Create empty CSV files with headers if they don't exist."""
        if not self.buy_list_path.exists():
            buy_list_columns = [
                'ticker', 'first_added', 'entry_price', 'current_price',
                'return_since_added', 'days_on_list', 'rs_rank', 
                'distance_52w_high', 'avg_volume_ratio', 'atr_percent',
                'last_updated'
            ]
            pd.DataFrame(columns=buy_list_columns).to_csv(self.buy_list_path, index=False)
            logger.info(f"Initialized buy_list at {self.buy_list_path}")
        
        if not self.history_path.exists():
            history_columns = ['date', 'ticker', 'event', 'close_price', 'reason']
            pd.DataFrame(columns=history_columns).to_csv(self.history_path, index=False)
            logger.info(f"Initialized history log at {self.history_path}")
    
    def _load_buy_list(self) -> pd.DataFrame:
        """Load current buy_list from CSV."""
        if self.buy_list_path.exists():
            df = pd.read_csv(self.buy_list_path)
            if not df.empty:
                # Handle various datetime formats
                df['first_added'] = pd.to_datetime(df['first_added'], format='mixed').dt.date
                df['last_updated'] = pd.to_datetime(df['last_updated'], format='mixed').dt.date
            return df
        return pd.DataFrame()
    
    def _save_buy_list(self, df: pd.DataFrame):
        """Save buy_list to CSV."""
        df.to_csv(self.buy_list_path, index=False)
    
    def _log_event(self, ticker: str, event: str, date: datetime, 
                   close_price: float, reason: str = ''):
        """
        Log an ADDED or REMOVED event to history.
        
        Args:
            ticker: Stock symbol
            event: 'ADDED' or 'REMOVED'
            date: Event date
            close_price: Close price on event date
            reason: Optional reason for removal
        """
        event_data = {
            'date': date.strftime('%Y-%m-%d'),
            'ticker': ticker,
            'event': event,
            'close_price': close_price,
            'reason': reason
        }
        
        # Append to history file
        event_df = pd.DataFrame([event_data])
        if self.history_path.exists():
            event_df.to_csv(self.history_path, mode='a', header=False, index=False)
        else:
            event_df.to_csv(self.history_path, index=False)
        
        logger.info(f"{event}: {ticker} at ${close_price:.2f} on {date.strftime('%Y-%m-%d')}")
    
    def update_buy_list(self, current_signals: pd.DataFrame, current_date: datetime):
        """
        Update buy_list with new signals and track changes.
        
        Args:
            current_signals: DataFrame with columns ['ticker', 'close', 'volume', ...]
            current_date: Current date for this update
        
        Returns:
            dict: Summary of changes (added, removed, continuing)
        """
        # Load existing buy_list
        old_list = self._load_buy_list()
        old_tickers = set(old_list['ticker']) if not old_list.empty else set()
        new_tickers = set(current_signals['ticker'])
        
        # Detect changes
        removed = old_tickers - new_tickers
        added = new_tickers - old_tickers
        continuing = old_tickers & new_tickers
        
        # Process removals
        for ticker in removed:
            old_row = old_list[old_list['ticker'] == ticker].iloc[0]
            self._log_event(ticker, 'REMOVED', current_date, 
                          old_row['current_price'], reason='')
        
        # Process additions
        new_rows = []
        for ticker in added:
            signal_row = current_signals[current_signals['ticker'] == ticker].iloc[0]
            new_row = self._create_new_entry(ticker, signal_row, current_date)
            new_rows.append(new_row)
            self._log_event(ticker, 'ADDED', current_date, 
                          signal_row['Close'], reason='')
        
        # Update continuing tickers
        updated_rows = []
        for ticker in continuing:
            old_row = old_list[old_list['ticker'] == ticker].iloc[0]
            signal_row = current_signals[current_signals['ticker'] == ticker].iloc[0]
            updated_row = self._update_existing_entry(old_row, signal_row, current_date)
            updated_rows.append(updated_row)
        
        # Combine and save
        new_buy_list = pd.DataFrame(new_rows + updated_rows)
        if not new_buy_list.empty:
            self._save_buy_list(new_buy_list)
        else:
            # Empty buy_list
            self._save_buy_list(pd.DataFrame(columns=old_list.columns if not old_list.empty else []))
        
        summary = {
            'active_count': len(new_buy_list),
            'added_today': len(added),
            'removed_today': len(removed),
            'continuing': len(continuing)
        }
        
        logger.info(f"Buy List updated: {summary['active_count']} active | "
                   f"+{summary['added_today']} added, -{summary['removed_today']} removed")
        
        return summary
    
    def _create_new_entry(self, ticker: str, signal_row: pd.Series, 
                         current_date: datetime) -> Dict:
        """Create a new buy_list entry for a newly added ticker."""
        entry_price = signal_row['Close']
        
        return {
            'ticker': ticker,
            'first_added': current_date.strftime('%Y-%m-%d'),
            'entry_price': entry_price,
            'current_price': entry_price,
            'return_since_added': 0.0,
            'days_on_list': 1,
            'rs_rank': signal_row.get('rs_rank', 0.0),
            'distance_52w_high': self._calculate_distance_52w_high(signal_row),
            'avg_volume_ratio': signal_row.get('volume_ratio', 1.0),
            'atr_percent': self._calculate_atr_percent(signal_row),
            'last_updated': current_date.strftime('%Y-%m-%d')
        }
    
    def _update_existing_entry(self, old_row: pd.Series, signal_row: pd.Series,
                              current_date: datetime) -> Dict:
        """Update metrics for a continuing ticker."""
        current_price = signal_row['Close']
        entry_price = old_row['entry_price']
        
        # Handle first_added as date object or string
        if isinstance(old_row['first_added'], str):
            first_added = pd.to_datetime(old_row['first_added']).date()
        else:
            first_added = old_row['first_added']
        
        # Ensure current_date is date object
        current_date_obj = current_date.date() if isinstance(current_date, datetime) else current_date
        
        days_on_list = (current_date_obj - first_added).days + 1
        return_since_added = (current_price - entry_price) / entry_price * 100
        
        return {
            'ticker': old_row['ticker'],
            'first_added': str(first_added),
            'entry_price': entry_price,
            'current_price': current_price,
            'return_since_added': return_since_added,
            'days_on_list': days_on_list,
            'rs_rank': signal_row.get('rs_rank', old_row.get('rs_rank', 0.0)),
            'distance_52w_high': self._calculate_distance_52w_high(signal_row),
            'avg_volume_ratio': signal_row.get('volume_ratio', 1.0),
            'atr_percent': self._calculate_atr_percent(signal_row),
            'last_updated': current_date.strftime('%Y-%m-%d')
        }
    
    def _calculate_distance_52w_high(self, signal_row: pd.Series) -> float:
        """Calculate % distance from 52-week high."""
        if 'High_52w' in signal_row and signal_row['High_52w'] > 0:
            return (signal_row['Close'] - signal_row['High_52w']) / signal_row['High_52w'] * 100
        return 0.0
    
    def _calculate_atr_percent(self, signal_row: pd.Series) -> float:
        """Calculate ATR as % of current price."""
        if 'ATR' in signal_row and signal_row['Close'] > 0:
            return signal_row['ATR'] / signal_row['Close'] * 100
        return 0.0
    
    def get_summary(self) -> Dict:
        """
        Get current buy_list summary statistics.
        
        Returns:
            dict: Summary with active_count, top_performer, recent_add, etc.
        """
        buy_list = self._load_buy_list()
        
        if buy_list.empty:
            return {
                'active_count': 0,
                'top_performer': None,
                'worst_performer': None,
                'avg_return': 0.0,
                'avg_days_on_list': 0
            }
        
        top_idx = buy_list['return_since_added'].idxmax()
        worst_idx = buy_list['return_since_added'].idxmin()
        
        return {
            'active_count': len(buy_list),
            'top_performer': {
                'ticker': buy_list.loc[top_idx, 'ticker'],
                'return': buy_list.loc[top_idx, 'return_since_added'],
                'days': buy_list.loc[top_idx, 'days_on_list']
            },
            'worst_performer': {
                'ticker': buy_list.loc[worst_idx, 'ticker'],
                'return': buy_list.loc[worst_idx, 'return_since_added'],
                'days': buy_list.loc[worst_idx, 'days_on_list']
            },
            'avg_return': buy_list['return_since_added'].mean(),
            'avg_days_on_list': buy_list['days_on_list'].mean()
        }
    
    def backfill(self, start_date: str, end_date: str, data_repo=None, strategy=None):
        """
        Backfill buy_list history by running scanner on historical dates.
        
        This allows reconstructing the complete event log for historical analysis
        and ML training data generation.
        
        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            data_repo: DataRepository instance for fetching data
            strategy: Strategy instance for signal generation
        
        Example:
            >>> from src.data_engine import DataRepository
            >>> from src.strategy import SEPAStrategy
            >>> data_repo = DataRepository()
            >>> strategy = SEPAStrategy()
            >>> manager = BuyListManager()
            >>> history = manager.backfill('2025-11-01', '2025-11-26', data_repo, strategy)
        """
        if data_repo is None or strategy is None:
            raise ValueError("Both data_repo and strategy are required for backfill")
        
        logger.info(f"Starting backfill from {start_date} to {end_date}...")
        
        # Clear existing files for clean backfill
        if self.buy_list_path.exists():
            self.buy_list_path.unlink()
        if self.history_path.exists():
            self.history_path.unlink()
        self._initialize_files()
        
        # Get universe
        logger.info("Fetching ticker universe...")
        tickers = data_repo.update_universe()
        logger.info(f"Will backfill {len(tickers)} tickers")
        
        # Load benchmark data for RS calculations
        logger.info("Loading benchmark (SPY) data...")
        benchmark_data = data_repo.get_benchmark_data()
        if benchmark_data is not None:
            strategy.benchmark_data = benchmark_data
            logger.info("Benchmark data loaded successfully")
        else:
            logger.warning("No benchmark data - RS calculations will be skipped")
        
        # Generate date range (business days only)
        dates = pd.date_range(start_date, end_date, freq='B')
        logger.info(f"Processing {len(dates)} business days...")
        
        total_signals_found = 0
        for i, date in enumerate(dates):
            if i % 5 == 0:
                logger.info(f"Backfill progress: {i}/{len(dates)} dates ({date.strftime('%Y-%m-%d')})")
            
            try:
                # Scan all tickers for this date (like daily scanner)
                daily_signals = []
                tickers_scanned = 0
                
                for ticker in tickers:
                    # Load ticker data
                    df = data_repo.get_ticker_data(ticker, use_cache=True)
                    if df is None or len(df) < 200:
                        continue
                    
                    # CRITICAL: Cut off data at backfill date to prevent look-ahead bias
                    df = df.loc[:date]
                    
                    # Ensure data is available up to this date
                    if date not in df.index:
                        continue
                    
                    tickers_scanned += 1
                    
                    # Prepare indicators
                    try:
                        df = strategy.prepare_data(df)
                    except Exception:
                        continue
                    
                    # Generate signal
                    signal = strategy.generate_signals(df, date)
                    
                    # Track ALL stocks that meet SEPA trend criteria (persist beyond trigger day)
                    # if signal['metadata'].get('trend_ok', False):
                    if signal['buy']:
                        daily_signals.append({
                            'ticker': ticker,
                            'Close': df.loc[date, 'Close'],
                            'rs_rank': df.loc[date, 'rs_rating'] if 'rs_rating' in df.columns else 0.0,
                            'volume_ratio': df.loc[date, 'Vol_Ratio'] if 'Vol_Ratio' in df.columns else 1.0,
                            'ATR': df.loc[date, 'ATR'] if 'ATR' in df.columns else 0.0,
                            'High_52w': df['High'].rolling(252).max().loc[date] if date in df.index else df.loc[date, 'Close']
                        })
                
                # Log daily results
                if i % 5 == 0:
                    logger.info(f"  Day {date.strftime('%Y-%m-%d')}: Scanned {tickers_scanned} tickers, found {len(daily_signals)} signals")
                
                total_signals_found += len(daily_signals)
                
                # Update buy_list with this day's signals
                if daily_signals:
                    signals_df = pd.DataFrame(daily_signals)
                    self.update_buy_list(signals_df, date)
                else:
                    # Even with no signals, update to detect removals
                    empty_df = pd.DataFrame(columns=['ticker', 'Close', 'rs_rank', 'volume_ratio'])
                    self.update_buy_list(empty_df, date)
            
            except Exception as e:
                logger.warning(f"Error processing {date}: {e}")
                continue
        
        # Load final history
        history = pd.read_csv(self.history_path)
        logger.info(f"Backfill complete! {len(history)} events logged.")
        logger.info(f"Total signals found across all dates: {total_signals_found}")
        logger.info(f"Total unique tickers tracked: {history['ticker'].nunique()}")
        
        return history
    
    def get_buy_list(self) -> pd.DataFrame:
        """Get current active buy_list."""
        return self._load_buy_list()
    
    def get_history(self) -> pd.DataFrame:
        """Get complete change history."""
        if self.history_path.exists():
            df = pd.read_csv(self.history_path)
            if not df.empty:
                df['date'] = pd.to_datetime(df['date'])
            return df
        return pd.DataFrame()
