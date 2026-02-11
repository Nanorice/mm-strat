"""
Strategy Module - SEPA Strategy Implementation
Implements Minervini's SEPA (Specific Entry Point Analysis) methodology.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from abc import ABC, abstractmethod
import logging

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
import config
from src.indicators import TechnicalAnalysis
from src.vectorized_screening import VectorizedSEPAScreener

logger = logging.getLogger(__name__)


class AlphaModel(ABC):
    """
    Abstract base class for trading strategies.
    Defines the interface for entry/exit signal generation.
    """

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame, date: pd.Timestamp) -> Dict:
        """
        Generate buy/sell signals for a given date.

        Args:
            df: DataFrame with OHLCV + indicators
            date: Current date for signal generation

        Returns:
            Dict with 'buy', 'sell', and metadata
        """
        pass


class SEPAStrategy(AlphaModel):
    """
    Implements Mark Minervini's SEPA methodology.

    Signal Generation Pipeline:
    1. Trend Filter (Stage 2 Uptrend)
    2. Structure (VCP Setup)
    3. Trigger (Breakout + Volume)
    4. Confirmation (Relative Strength)
    """

    def __init__(self, benchmark_data: Optional[pd.Series] = None):
        """
        Initialize SEPA strategy.

        Args:
            benchmark_data: Benchmark (SPY) close prices for RS calculation
        """
        self.benchmark_data = benchmark_data
        self.ta = TechnicalAnalysis()

    def prepare_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds all required indicators to raw OHLCV data.

        Args:
            df: Raw OHLCV DataFrame

        Returns:
            DataFrame with all indicators calculated
        """
        return self.ta.calculate_all_indicators(df, self.benchmark_data)

    def screen_candidates(self, df: pd.DataFrame, date: pd.Timestamp) -> bool:
        """
        Step 1: Broad screening for Stage 2 uptrend (Trend Template).

        Args:
            df: DataFrame with indicators
            date: Current date

        Returns:
            True if stock meets trend criteria
        """
        if date not in df.index:
            return False

        try:
            stage2 = self.ta.detect_stage2_uptrend(df)
            return stage2.loc[date] if date in stage2.index else False
        except Exception as e:
            logger.debug(f"Stage 2 detection failed: {e}")
            return False

    def check_trigger(self, df: pd.DataFrame, date: pd.Timestamp) -> bool:
        """
        Step 2: Check for VCP breakout trigger.

        Args:
            df: DataFrame with indicators
            date: Current date

        Returns:
            True if breakout + volume spike detected
        """
        if date not in df.index:
            return False

        try:
            vcp = self.ta.detect_vcp_setup(df)
            return vcp.loc[date] if date in vcp.index else False
        except Exception as e:
            logger.debug(f"VCP detection failed: {e}")
            return False

    def check_relative_strength(self, df: pd.DataFrame, date: pd.Timestamp) -> bool:
        """
        Step 3: Confirm relative strength vs benchmark.

        Args:
            df: DataFrame with indicators
            date: Current date

        Returns:
            True if RS is strong
        """
        if date not in df.index or self.benchmark_data is None:
            return True  # Skip RS check if no benchmark

        try:
            rs_strong = self.ta.detect_relative_strength(df)
            return rs_strong.loc[date] if date in rs_strong.index else False
        except Exception as e:
            logger.debug(f"RS detection failed: {e}")
            return False

    def check_exit_signal(self, df: pd.DataFrame, date: pd.Timestamp,
                         entry_price: float, stop_price: float) -> Tuple[bool, str]:
        """
        Checks for exit conditions:
        1. Stop loss hit (price drops below stop)
        2. Trend break (close below 50 SMA)

        Args:
            df: DataFrame with indicators
            date: Current date
            entry_price: Entry price of the trade
            stop_price: Stop loss price

        Returns:
            Tuple of (should_exit: bool, exit_reason: str)
        """
        if date not in df.index:
            return False, ''

        row = df.loc[date]

        # Check stop loss (using intraday low)
        if 'Low' in df.columns and row['Low'] < stop_price:
            return True, 'Stop Loss'

        # Check trend break (close below 50 SMA)
        if 'SMA_50' in df.columns and pd.notna(row['SMA_50']):
            if row['Close'] < row['SMA_50']:
                return True, 'Trend Break (50 SMA)'

        return False, ''
    
    def extract_sepa_criteria(self, df: pd.DataFrame, date: pd.Timestamp) -> Dict[str, int]:
        """
        Extracts individual SEPA criteria for database storage.

        Returns 9 individual trend checks as integers (1=True, 0=False):
        C1. price_above_ma150
        C2. price_above_ma200
        C3. ma150_above_ma200
        C4. ma200_trending_up
        C5. ma50_above_ma150
        C6. price_above_ma50
        C7. price_above_52w_low_30pct
        C8. price_within_15pct_of_52w_high
        C9. rs_rating_positive (proxy for top 30% - cross-sectional rank computed elsewhere)

        Args:
            df: DataFrame with indicators
            date: Date to extract criteria for

        Returns:
            Dict with 9 criteria as integers (1/0)
        """
        empty_result = {
            'price_above_ma150': 0,
            'price_above_ma200': 0,
            'ma150_above_ma200': 0,
            'ma200_trending_up': 0,
            'ma50_above_ma150': 0,
            'price_above_ma50': 0,
            'price_above_52w_low_30pct': 0,
            'price_within_15pct_of_52w_high': 0,
            'rs_rating_positive': 0
        }

        if date not in df.index:
            return empty_result

        try:
            row = df.loc[date]
            price = row['Close']
            ma50 = row.get('SMA_50', 0)
            ma150 = row.get('SMA_150', 0)
            ma200 = row.get('SMA_200', 0)
            high_52w = row.get('High_52W', 0)
            low_52w = row.get('Low_52W', 0)
            rs_rating = row.get('rs_rating', None)

            # Calculate 9 individual checks (C1-C9)
            criteria = {
                'price_above_ma150': 1 if price > ma150 else 0,
                'price_above_ma200': 1 if price > ma200 else 0,
                'ma150_above_ma200': 1 if ma150 > ma200 else 0,
                'ma200_trending_up': 0,  # Calculate below
                'ma50_above_ma150': 1 if ma50 > ma150 else 0,
                'price_above_ma50': 1 if price > ma50 else 0,
                'price_above_52w_low_30pct': 1 if price > low_52w * 1.30 else 0,
                'price_within_15pct_of_52w_high': 1 if price > high_52w * 0.85 else 0,
                'rs_rating_positive': 1 if (rs_rating is not None and pd.notna(rs_rating) and rs_rating > 0) else 0
            }

            # MA200 trending up (current > 20 days ago)
            if len(df) > 20 and 'SMA_200' in df.columns:
                ma200_prev = df['SMA_200'].shift(20).loc[date] if pd.notna(df['SMA_200'].shift(20).loc[date]) else ma200
                criteria['ma200_trending_up'] = 1 if ma200 > ma200_prev else 0

            return criteria

        except Exception as e:
            logger.debug(f"Error extracting SEPA criteria: {e}")
            return empty_result

    def generate_signals(self, df: pd.DataFrame, date: pd.Timestamp) -> Dict:
        """
        Main signal generation method.
        Combines all SEPA components.

        Args:
            df: DataFrame with OHLCV + indicators
            date: Current date

        Returns:
            Dict with:
                - 'buy': Boolean
                - 'sell': Boolean
                - 'signal_strength': Float (0-1) - placeholder for ML
                - 'metadata': Dict with details
        """
        if date not in df.index:
            return {'buy': False, 'sell': False, 'signal_strength': 0.0, 'metadata': {}}

        # Ensure indicators are calculated
        if 'SMA_50' not in df.columns:
            df = self.prepare_data(df)

        # Check all buy criteria
        trend_ok = self.screen_candidates(df, date)
        trigger_ok = self.check_trigger(df, date)
        rs_ok = self.check_relative_strength(df, date)

        buy_signal = trend_ok and trigger_ok and rs_ok

        # Sell signal (trend break)
        sell_signal = False
        if 'SMA_50' in df.columns and date in df.index:
            sell_signal = df.loc[date, 'Close'] < df.loc[date, 'SMA_50']

        # Signal strength (placeholder - can integrate ML here later)
        signal_strength = 1.0 if buy_signal else 0.0

        # Metadata for logging
        metadata = {
            'trend_ok': trend_ok,
            'trigger_ok': trigger_ok,
            'rs_ok': rs_ok,
            'price': df.loc[date, 'Close'] if date in df.index else None,
            'volume_ratio': df.loc[date, 'Vol_Ratio'] if 'Vol_Ratio' in df.columns and date in df.index else None
        }

        return {
            'buy': buy_signal,
            'sell': sell_signal,
            'signal_strength': signal_strength,
            'metadata': metadata
        }

    def calculate_trade_plan(self, df: pd.DataFrame, date: pd.Timestamp) -> Optional[Dict]:
        """
        Calculates entry, stop, and target prices for a trade.

        Uses fixed percentage stop loss (from config).

        Args:
            df: DataFrame with indicators
            date: Entry date

        Returns:
            Dict with trade plan details, or None if data missing
        """
        if date not in df.index:
            return None

        row = df.loc[date]
        entry_price = row['Close']

        # Fixed percentage stop
        stop_price = entry_price * (1 - config.STOP_LOSS_PCT)
        risk = entry_price - stop_price

        # Profit target (R-multiple)
        target_price = entry_price + (risk * config.PROFIT_TARGET_R)

        # Position sizing (fixed fractional)
        position_size_pct = config.POSITION_SIZE_PCT

        # ATR for reference (optional)
        atr = row['ATR'] if 'ATR' in df.columns and pd.notna(row['ATR']) else None

        return {
            'entry_price': round(entry_price, 2),
            'stop_price': round(stop_price, 2),
            'target_price': round(target_price, 2),
            'risk_per_share': round(risk, 2),
            'risk_pct': round(config.STOP_LOSS_PCT * 100, 2),
            'reward_pct': round(config.STOP_LOSS_PCT * config.PROFIT_TARGET_R * 100, 2),
            'position_size_pct': round(position_size_pct * 100, 1),
            'atr': round(atr, 2) if atr else None
        }
    
    def batch_scan_universe(self, enriched_data_dict: Dict[str, pd.DataFrame],
                           scan_date: Optional[pd.Timestamp] = None) -> Dict:
        """
        Batch scan multiple tickers for SEPA signals using vectorized operations.

        PERFORMANCE NOTE: Now uses vectorized SEPA screening (5-10x faster than
        the previous sequential implementation).

        Args:
            enriched_data_dict: Dict mapping ticker -> enriched DataFrame (with lightweight features)
            scan_date: Optional specific date to scan. If None, uses latest date from each ticker

        Returns:
            Dict with:
                'trend_ok_stocks': List of stocks with trend_ok = True (C1-C8)
                'breakout_stocks': List of stocks with breakout_ok = True (C9-C11)
                'qualifying_stocks': List of stocks with full SEPA (trend + breakout) - backward compat
                'new_triggers': List of stocks with buy = True (triggered on scan_date)
                'summary': Dict with counts and statistics
        """
        trend_ok_stocks = []
        breakout_stocks = []
        qualifying_stocks = []  # Backward compatibility
        new_triggers = []
        latest_date = None

        # Use vectorized SEPA screening if scan_date is provided
        if scan_date is not None:
            # VECTORIZED PATH - 5-10x faster
            # Now returns 3 lists: trend_ok, breakout, new_triggers
            trend_ok_tickers, breakout_tickers, new_trigger_tickers = \
                VectorizedSEPAScreener.batch_screen_universe(
                    enriched_data_dict, scan_date
                )

            # Build results for trend_ok stocks (C1-C8)
            for ticker in trend_ok_tickers:
                df = enriched_data_dict[ticker]

                # Find the actual date used
                if scan_date in df.index:
                    ticker_date = scan_date
                else:
                    available = df.index[df.index <= scan_date]
                    if len(available) == 0:
                        continue
                    ticker_date = available[-1]

                # Track latest date
                if latest_date is None or ticker_date > latest_date:
                    latest_date = ticker_date

                # Extract metrics
                row = df.loc[ticker_date]
                rs_value = row.get('RS')
                vol_ratio = row.get('Vol_Ratio')
                atr_value = row.get('ATR')
                price = row['Close']

                # Check if also has breakout and is new trigger
                has_breakout = ticker in breakout_tickers
                is_new_trigger = ticker in new_trigger_tickers

                stock_data = {
                    'ticker': ticker,
                    'date': ticker_date,
                    'price': price,
                    'rs': rs_value,
                    'vol_ratio': vol_ratio,
                    'atr': atr_value,
                    'trend_ok': True,
                    'breakout_ok': has_breakout,
                    'is_new_trigger': is_new_trigger,
                    'signal_strength': 1.0 if is_new_trigger else 0.5,
                }

                trend_ok_stocks.append(stock_data)

                # If also has breakout, add to breakout_stocks
                if has_breakout:
                    breakout_stocks.append(stock_data.copy())

                # If has BOTH trend + breakout, add to qualifying_stocks (backward compat)
                if has_breakout:
                    qualifying_stocks.append(stock_data.copy())

            # Build new_triggers list (only those with BOTH + 0->1 transition)
            for ticker in new_trigger_tickers:
                df = enriched_data_dict[ticker]

                # Find the actual date used
                if scan_date in df.index:
                    ticker_date = scan_date
                else:
                    available = df.index[df.index <= scan_date]
                    if len(available) == 0:
                        continue
                    ticker_date = available[-1]

                # Calculate trade plan
                trade_plan = self.calculate_trade_plan(df, ticker_date)
                if trade_plan:
                    row = df.loc[ticker_date]
                    trigger_data = {
                        'ticker': ticker,
                        'date': ticker_date,
                        'entry_price': trade_plan['entry_price'],
                        'stop_price': trade_plan['stop_price'],
                        'target_price': trade_plan['target_price'],
                        'risk_pct': trade_plan['risk_pct'],
                        'reward_pct': trade_plan['reward_pct'],
                        'atr': trade_plan['atr'],
                        'rs': row.get('RS'),
                        'vol_ratio': row.get('Vol_Ratio'),
                        'signal_strength': 1.0
                    }
                    new_triggers.append(trigger_data)
        
        else:
            # FALLBACK PATH - for backward compatibility when scan_date is None
            # Process all tickers
            for ticker, df in enriched_data_dict.items():
                try:
                    # Use latest date
                    ticker_date = df.index[-1]
                    
                    # Track latest date across all tickers
                    if latest_date is None or ticker_date > latest_date:
                        latest_date = ticker_date
                    
                    # Generate signal (this is fast - mostly boolean operations)
                    signal = self.generate_signals(df, ticker_date)
                    
                    # Extract metrics
                    row = df.loc[ticker_date]
                    rs_value = row.get('RS')
                    vol_ratio = row.get('Vol_Ratio')
                    atr_value = row.get('ATR')
                    price = row['Close']
                    
                    # Check if qualifying (trend_ok = True)
                    if signal['metadata'].get('trend_ok', False):
                        stock_data = {
                            'ticker': ticker,
                            'date': ticker_date,
                            'price': price,
                            'rs': rs_value,
                            'vol_ratio': vol_ratio,
                            'atr': atr_value,
                            'is_new_trigger': signal['buy'],
                            'signal_strength': signal['signal_strength'],
                            'trend_ok': signal['metadata'].get('trend_ok'),
                            'vcp_ok': signal['metadata'].get('trigger_ok'),
                            'trigger_ok': signal['metadata'].get('trigger_ok')
                        }
                        
                        qualifying_stocks.append(stock_data)
                        
                        # If triggered, calculate trade plan
                        if signal['buy']:
                            trade_plan = self.calculate_trade_plan(df, ticker_date)
                            if trade_plan:
                                trigger_data = {
                                    'ticker': ticker,
                                    'date': ticker_date,
                                    'entry_price': trade_plan['entry_price'],
                                    'stop_price': trade_plan['stop_price'],
                                    'target_price': trade_plan['target_price'],
                                    'risk_pct': trade_plan['risk_pct'],
                                    'reward_pct': trade_plan['reward_pct'],
                                    'atr': trade_plan['atr'],
                                    'rs': rs_value,
                                    'vol_ratio': vol_ratio,
                                    'signal_strength': signal['signal_strength']
                                }
                                new_triggers.append(trigger_data)
                
                except Exception as e:
                    logger.debug(f"Error processing {ticker}: {e}")
                    continue
        
        # Build summary
        summary = {
            'total_scanned': len(enriched_data_dict),
            'trend_ok_count': len(trend_ok_stocks),
            'breakout_count': len(breakout_stocks),
            'qualifying_count': len(qualifying_stocks),  # Backward compat
            'new_triggers_count': len(new_triggers),
            'latest_date': latest_date,
            'qualification_rate': len(qualifying_stocks) / len(enriched_data_dict) if enriched_data_dict else 0,
            'trigger_rate': len(new_triggers) / len(enriched_data_dict) if enriched_data_dict else 0
        }

        logger.info(f"Batch scan: {summary['trend_ok_count']} trend OK, "
                   f"{summary['breakout_count']} breakout OK, "
                   f"{summary['new_triggers_count']} new triggers")

        return {
            'trend_ok_stocks': trend_ok_stocks,
            'breakout_stocks': breakout_stocks,
            'qualifying_stocks': qualifying_stocks,  # Backward compat
            'new_triggers': new_triggers,
            'summary': summary
        }

    # TODO: Future enhancement - integrate ML-based signal scoring
    def score_signal_ml(self, df: pd.DataFrame, date: pd.Timestamp) -> float:
        """
        Placeholder for ML-based signal scoring (Meta-Labeling).

        When implemented, this will use a trained Random Forest to predict
        probability of trade success.

        Args:
            df: DataFrame with indicators
            date: Current date

        Returns:
            Confidence score (0.0 to 1.0)
        """
        # TODO: Extract features, load model, predict probability
        # For now, return 1.0 (full confidence) for rule-based signals
        return 1.0
