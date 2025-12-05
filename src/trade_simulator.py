"""
Trade Simulator - Historical Trade Simulation for Dataset B Construction
Event-driven simulation of SEPA strategy to generate labeled training data.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import logging

import sys
sys.path.append(str(Path(__file__).parent.parent))

import config
from src.data_engine import DataRepository
from src.strategy import SEPAStrategy
from src.features import FeatureEngineer
from src.trading_config import TradingConfig

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    """
    Represents a single trade for Dataset B.
    
    This is the core unit for ML training data. Each completed trade becomes
    one row in Dataset B (Events Log).
    """
    trade_id: int
    ticker: str
    entry_date: pd.Timestamp
    entry_price: float
    
    # Exit Information (None until trade closes)
    exit_date: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    return_pct: Optional[float] = None
    days_held: Optional[int] = None
    exit_reason: Optional[str] = None
    
    # Entry Indicators (for merging with Dataset A later)
    entry_indicators: Dict = field(default_factory=dict)
    
    # Enhanced Performance Metrics (calculated at exit)
    max_drawdown_pct: Optional[float] = None  # Worst intra-trade drawdown
    max_favorable_excursion_pct: Optional[float] = None  # Best intra-trade gain
    r_multiple: Optional[float] = None  # Return / initial risk
    sharpe_ratio: Optional[float] = None  # Risk-adjusted return
    initial_risk_pct: Optional[float] = None  # Entry to stop distance
    
    # Label (assigned at exit)
    label: Optional[int] = None
    
    def close(self, exit_date: pd.Timestamp, exit_price: float, 
              exit_reason: str, ticker_df: Optional[pd.DataFrame] = None,
              labeling_function: Optional[callable] = None):
        """
        Closes the trade and calculates returns and enhanced metrics.
        
        Args:
            exit_date: Exit date
            exit_price: Exit price
            exit_reason: Reason for exit
            ticker_df: Full price DataFrame for intra-trade analysis
            labeling_function: Custom labeling function (trade -> int)
        """
        self.exit_date = exit_date
        self.exit_price = exit_price
        self.exit_reason = exit_reason
        
        # Calculate basic returns
        self.return_pct = ((exit_price - self.entry_price) / self.entry_price) * 100
        self.days_held = (exit_date - self.entry_date).days
        
        # Calculate enhanced metrics if price data available
        if ticker_df is not None and not ticker_df.empty:
            try:
                # Get price data during trade period
                trade_period = ticker_df.loc[self.entry_date:exit_date]
                
                if len(trade_period) > 0:
                    # Max Drawdown: Worst % drop from entry during trade
                    lowest_price = trade_period['Low'].min()
                    self.max_drawdown_pct = ((lowest_price - self.entry_price) / self.entry_price) * 100
                    
                    # Max Favorable Excursion: Best % gain from entry during trade
                    highest_price = trade_period['High'].max()
                    self.max_favorable_excursion_pct = ((highest_price - self.entry_price) / self.entry_price) * 100
                    
                    # R-Multiple: Risk-adjusted return
                    if self.initial_risk_pct and self.initial_risk_pct != 0:
                        self.r_multiple = self.return_pct / abs(self.initial_risk_pct)
                    
                    # Sharpe Ratio: Annualized risk-adjusted return
                    if len(trade_period) > 1:
                        daily_returns = trade_period['Close'].pct_change().dropna()
                        if len(daily_returns) > 0 and daily_returns.std() != 0:
                            self.sharpe_ratio = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
            except Exception as e:
                # Silently skip if metric calculation fails
                logger.debug(f"Could not calculate enhanced metrics for {self.ticker}: {e}")
        
        # Apply labeling function
        if labeling_function:
            self.label = labeling_function(self)
        else:
            # Default: Binary threshold on return_pct
            self.label = 1 if self.return_pct >= 15.0 else 0
    
    def to_dict(self) -> dict:
        """Convert trade to dictionary for DataFrame export."""
        return {
            'trade_id': self.trade_id,
            'ticker': self.ticker,
            'entry_date': self.entry_date.strftime('%Y-%m-%d'),
            'entry_price': self.entry_price,
            'exit_date': self.exit_date.strftime('%Y-%m-%d') if self.exit_date else None,
            'exit_price': self.exit_price,
            'return_pct': self.return_pct,
            'days_held': self.days_held,
            'exit_reason': self.exit_reason,
            'label': self.label,
            # Enhanced metrics
            'max_drawdown_pct': self.max_drawdown_pct,
            'max_favorable_excursion_pct': self.max_favorable_excursion_pct,
            'r_multiple': self.r_multiple,
            'sharpe_ratio': self.sharpe_ratio,
            'initial_risk_pct': self.initial_risk_pct,
            # Entry indicators
            **{f'entry_{k}': v for k, v in self.entry_indicators.items()}
        }


class TradeSimulator:
    """
    Event-driven trade simulator for Dataset B construction.
    
    Simulates running SEPA strategy over historical data, tracking trades
    from entry (signal trigger) to exit (trend break), and labeling outcomes.
    
    Usage:
        simulator = TradeSimulator(
            data_repo=DataRepository(),
            strategy=SEPAStrategy(),
            start_date='2020-01-01',
            end_date='2023-12-31',
            config=TradingConfig.default()
        )
        dataset_b = simulator.run_simulation()
    """
    
    def __init__(self,
                 data_repo: DataRepository,
                 strategy: SEPAStrategy,
                 feature_engine: FeatureEngineer,
                 start_date: str,
                 end_date: str,
                 config: Optional[TradingConfig] = None,
                 outcome_end: Optional[str] = None):
        """
        Initialize trade simulator.

        Args:
            data_repo: Data repository for loading price data
            strategy: SEPA strategy instance
            feature_engine: Feature engineer for indicators
            start_date: Simulation start date (YYYY-MM-DD)
            end_date: Simulation end date (for new entries, YYYY-MM-DD)
            config: Trading configuration (default: TradingConfig.default())
            outcome_end: Extended end date for natural trade exits (YYYY-MM-DD).
                        If provided, new entries stop at end_date but existing trades
                        can exit naturally until outcome_end. Prevents artificial
                        end-of-period exits that don't happen in real trading.
        """
        self.data_repo = data_repo
        self.strategy = strategy
        self.feature_engine = feature_engine
        self.start_date = pd.Timestamp(start_date)
        self.end_date = pd.Timestamp(end_date)
        self.outcome_end = pd.Timestamp(outcome_end) if outcome_end else self.end_date
        self.config = config or TradingConfig.default()
        
        # State tracking
        self.active_trades: Dict[str, Trade] = {}  # ticker -> Trade
        self.completed_trades: List[Trade] = []
        self.trade_counter = 0
        
        # Re-entry tracking
        self.last_exit_date: Dict[str, pd.Timestamp] = {}  # ticker -> last exit date
        
        logger.info(f"Initialized TradeSimulator from {start_date} to {end_date}")
        logger.info(f"Configuration:\n{self.config}")
    
    def run_simulation(self, show_progress=True) -> pd.DataFrame:
        """
        Runs the event-driven simulation.
        
        Args:
            show_progress: If True, displays progress bar (default: True)
        
        Returns:
            DataFrame with completed trades (Dataset B)
        """
        logger.info("Starting trade simulation...")
        
        # Step 1: Load universe and price data
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
        
        # Step 2: Calculate features for all tickers
        logger.info("Calculating features...")
        enriched_data = self.feature_engine.process_universe_batch(valid_ticker_data, show_progress=show_progress)
        logger.info(f"Features calculated for {len(enriched_data)} tickers")
        
        # Step 3: Get all unique trading dates
        all_dates = set()
        for df in enriched_data.values():
            all_dates.update(df.index)
        
        # Use outcome_end for simulation range (allows natural exits after end_date)
        trading_dates = sorted([
            d for d in all_dates
            if self.start_date <= d <= self.outcome_end
        ])
        
        logger.info(f"Simulating {len(trading_dates)} trading days...")
        
        # Track statistics for progress display
        stats = {
            'total_signals': 0,
            'signals_added': 0,
            'signals_removed': 0,
            'last_update': 0
        }
        
        # Step 4: Day-by-day simulation loop with progress bar
        try:
            from tqdm import tqdm
            iterator = tqdm(trading_dates, desc="Trading Days", disable=not show_progress, 
                          bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]')
        except ImportError:
            iterator = trading_dates
            logger.warning("tqdm not installed, progress bar disabled")
        
        for i, date in enumerate(iterator):
            # Track active trades before this day
            trades_before = len(self.active_trades)
            
            # Check exits first (path dependency: exits before new entries)
            self._check_for_exits(date, enriched_data)
            
            # Track removals
            exits_this_day = trades_before - len(self.active_trades)
            stats['signals_removed'] += exits_this_day
            
            # Check for new entries (only until end_date, not outcome_end)
            trades_before_entry = len(self.active_trades)
            if date <= self.end_date:
                self._check_for_entries(date, enriched_data)
            
            # Track additions
            entries_this_day = len(self.active_trades) - trades_before_entry
            stats['signals_added'] += entries_this_day
            stats['total_signals'] = len(self.completed_trades) + len(self.active_trades)
            
            # Update progress bar postfix every 10 days
            if show_progress and hasattr(iterator, 'set_postfix') and i - stats['last_update'] >= 10:
                iterator.set_postfix({
                    'Signals': stats['total_signals'],
                    'Added': stats['signals_added'],
                    'Removed': stats['signals_removed'],
                    'Active': len(self.active_trades)
                })
                stats['last_update'] = i
        
        # Step 5: Close any remaining open trades at end of outcome window
        if self.active_trades:
            logger.info(f"Closing {len(self.active_trades)} open positions at end of outcome window")
            for ticker, trade in list(self.active_trades.items()):
                ticker_df = enriched_data.get(ticker)
                if ticker_df is not None and self.outcome_end in ticker_df.index:
                    exit_price = ticker_df.loc[self.outcome_end, 'Close']
                    self._close_trade(trade, self.outcome_end, exit_price, 'end_of_outcome_window', enriched_data)
        
        logger.info(f"Simulation complete! Generated {len(self.completed_trades)} trades")
        logger.info(f"  Total signals processed: {stats['total_signals']}")
        logger.info(f"  Signals added: {stats['signals_added']}")
        logger.info(f"  Signals removed: {stats['signals_removed']}")
        
        # Convert to DataFrame
        return self.get_dataset_b()
    
    def _check_for_entries(self, date: pd.Timestamp, enriched_data: Dict[str, pd.DataFrame]):
        """
        Checks for new SEPA signals on given date.
        
        Args:
            date: Current simulation date
            enriched_data: Dict of ticker -> enriched DataFrame
        """
        # Use strategy's batch scan to find signals
        scan_results = self.strategy.batch_scan_universe(enriched_data, scan_date=date)
        new_triggers = scan_results['new_triggers']
        
        for trigger in new_triggers:
            ticker = trigger['ticker']
            
            # Skip if already holding
            if ticker in self.active_trades:
                continue
            
            # Check re-entry cooldown
            if not self.config.allow_reentry:
                if ticker in self.last_exit_date:
                    continue  # Never re-enter
            else:
                if ticker in self.last_exit_date:
                    days_since_exit = (date - self.last_exit_date[ticker]).days
                    if days_since_exit < self.config.reentry_cooldown_days:
                        continue  # Still in cooldown
            
            # Open new trade
            self._open_trade(ticker, date, trigger, enriched_data)
    
    def _check_for_exits(self, date: pd.Timestamp, enriched_data: Dict[str, pd.DataFrame]):
        """
        Checks active trades for exit signals.
        
        Args:
            date: Current simulation date
            enriched_data: Dict of ticker -> enriched DataFrame
        """
        for ticker, trade in list(self.active_trades.items()):
            ticker_df = enriched_data.get(ticker)
            
            if ticker_df is None or date not in ticker_df.index:
                continue
            
            # Get current price
            current_price = ticker_df.loc[date, 'Close']
            
            # Check exit conditions based on config
            should_exit = False
            exit_reason = None
            
            # Exit Rule 1: Trend Break (SEPA no longer qualifying)
            if self.config.exit_on_trend_break:
                if not self.strategy.screen_candidates(ticker_df, date):
                    should_exit = True
                    exit_reason = 'trend_break'
            
            # Exit Rule 2: Stop Loss (if enabled)
            if self.config.exit_on_stop_loss and not should_exit:
                stop_price = trade.entry_price * (1 - self.config.stop_loss_pct / 100)
                if current_price <= stop_price:
                    should_exit = True
                    exit_reason = 'stop_loss'
            
            # Execute exit
            if should_exit:
                self._close_trade(trade, date, current_price, exit_reason, enriched_data)
    
    def _open_trade(self, ticker: str, date: pd.Timestamp, 
                    trigger: dict, enriched_data: Dict[str, pd.DataFrame]):
        """
        Opens a new trade.
        
        Args:
            ticker: Stock symbol
            date: Entry date
            trigger: Trigger metadata from strategy
            enriched_data: Enriched data dict
        """
        self.trade_counter += 1
        
        #Extract entry indicators for Dataset A merge later
        ticker_df = enriched_data.get(ticker)
        entry_indicators = {}
        initial_risk_pct = None
        
        if ticker_df is not None and date in ticker_df.index:
            row = ticker_df.loc[date]
            entry_indicators = {
                'ma50': row.get('SMA_50'),
                'ma150': row.get('SMA_150'),
                'ma200': row.get('SMA_200'),
                'rs': row.get('RS'),
                'vol_ratio': row.get('Vol_Ratio'),  # Changed from Volume_Ratio to Vol_Ratio
                'high_52w': row.get('High_52W'),
                'low_52w': row.get('Low_52W'),
            }
            
            # Calculate initial risk (2.5x ATR for stop distance)
            atr = row.get('ATR')
            if atr and not pd.isna(atr) and trigger['entry_price'] > 0:
                stop_distance = 2.5 * atr
                initial_risk_pct = (stop_distance / trigger['entry_price']) * 100
        
        # Create trade
        trade = Trade(
            trade_id=self.trade_counter,
            ticker=ticker,
            entry_date=date,
            entry_price=trigger['entry_price'],
            entry_indicators=entry_indicators,
            initial_risk_pct=initial_risk_pct  # NEW
        )
        
        self.active_trades[ticker] = trade
        logger.debug(f"Opened trade #{trade.trade_id}: {ticker} @ ${trade.entry_price:.2f} on {date.date()}")
    
    def _close_trade(self, trade: Trade, exit_date: pd.Timestamp, 
                     exit_price: float, exit_reason: str,
                     enriched_data: Dict[str, pd.DataFrame]):
        """
        Closes an active trade.
        
        Args:
            trade: Trade to close
            exit_date: Exit date
            exit_price: Exit price
            exit_reason: Reason for exit
            enriched_data: Enriched data for intra-trade analysis
        """
        # Get ticker's full price history for metric calculation
        ticker_df = enriched_data.get(trade.ticker)
        
        # Close the trade with enhanced metrics and custom labeling
        trade.close(
            exit_date=exit_date,
            exit_price=exit_price,
            exit_reason=exit_reason,
            ticker_df=ticker_df,
            labeling_function=self.config.labeling_function
        )
        
        # Move to completed trades
        self.completed_trades.append(trade)
        del self.active_trades[trade.ticker]
        
        # Track exit date for re-entry logic
        self.last_exit_date[trade.ticker] = exit_date
        
        logger.debug(
            f"Closed trade #{trade.trade_id}: {trade.ticker} "
            f"@ ${exit_price:.2f} ({trade.return_pct:+.2f}%) - {exit_reason}"
        )
    
    def get_dataset_b(self) -> pd.DataFrame:
        """
        Returns Dataset B as a DataFrame.
        
        Returns:
            DataFrame with one row per completed trade
        """
        if not self.completed_trades:
            logger.warning("No completed trades to export")
            return pd.DataFrame()
        
        # Convert trades to DataFrame
        df = pd.DataFrame([trade.to_dict() for trade in self.completed_trades])
        
        # Add metadata columns
        df['simulation_start'] = self.start_date.strftime('%Y-%m-%d')
        df['simulation_end'] = self.end_date.strftime('%Y-%m-%d')
        df['success_threshold_pct'] = self.config.success_threshold_pct
        
        return df
    
    def get_summary_statistics(self) -> dict:
        """
        Returns summary statistics of simulation.
        
        Returns:
            Dictionary with statistics
        """
        if not self.completed_trades:
            return {}
        
        df = self.get_dataset_b()
        
        wins = df[df['label'] == 1]
        losses = df[df['label'] == 0]
        
        return {
            'total_trades': len(df),
            'winning_trades': len(wins),
            'losing_trades': len(losses),
            'win_rate': len(wins) / len(df) if len(df) > 0 else 0,
            'avg_return': df['return_pct'].mean(),
            'avg_win': wins['return_pct'].mean() if not wins.empty else 0,
            'avg_loss': losses['return_pct'].mean() if not losses.empty else 0,
            'avg_days_held': df['days_held'].mean(),
            'max_win': df['return_pct'].max(),
            'max_loss': df['return_pct'].min(),
            'label_distribution': df['label'].value_counts().to_dict(),
            'exit_reasons': df['exit_reason'].value_counts().to_dict()
        }
