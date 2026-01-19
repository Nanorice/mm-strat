"""
Database Module - Watchlist and Trade Tracking
SQLite database for persistent storage of watchlist and trade history.
"""

import sqlite3
import pandas as pd
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path
import logging
import json

import sys
sys.path.append(str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Manages SQLite database for watchlist and trade logging.

    Tables:
    - watchlist: Tracks stocks in setup phase (days on watchlist)
    - trades: Historical trade log
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize database manager.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path or config.DB_PATH
        self._init_database()

    def _init_database(self):
        """Creates database tables if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Setup Watchlist table - tracks stocks in Stage 2 setup (not triggered yet)
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {config.WATCHLIST_TABLE} (
                ticker TEXT PRIMARY KEY,
                first_seen DATE NOT NULL,
                last_seen DATE NOT NULL,
                days_on_watchlist INTEGER DEFAULT 1,
                avg_rs REAL,
                avg_volume_ratio REAL,
                status TEXT DEFAULT 'active',
                notes TEXT
            )
        """)

        # Buy List table - tracks stocks with active buy signals (triggered)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS buy_list (
                ticker TEXT PRIMARY KEY,
                signal_date DATE NOT NULL,
                signal_price REAL NOT NULL,
                current_price REAL NOT NULL,
                entry_price REAL,
                stop_price REAL,
                target_price REAL,
                atr REAL,
                rs REAL,
                volume_ratio REAL,
                ma50 REAL,
                ma150 REAL,
                ma200 REAL,
                high_52w REAL,
                low_52w REAL,

                -- Lagged features (setup conditions at T-1)
                nATR_lag1 REAL,
                atr_lag1 REAL,
                vcp_ratio_lag1 REAL,
                consolidation_width_lag1 REAL,
                price_vs_sma50_lag1 REAL,
                price_vs_sma150_lag1 REAL,
                price_vs_sma200_lag1 REAL,
                rs_lag1 REAL,
                rs_ma_lag1 REAL,
                dry_up_volume_lag1 REAL,
                high_52w_lag1 REAL,
                low_52w_lag1 REAL,
                rsi14_lag1 REAL,
                dist_from_52w_high_lag1 REAL,

                ml_probability REAL,
                ml_expected_return REAL,
                ml_model_type TEXT,
                ml_rank INTEGER,
                ml_model_version TEXT,
                ml_score_date DATE,
                ml_features TEXT,
                last_updated DATE,
                status TEXT DEFAULT 'active',
                notes TEXT
            )
        """)

        # Buy List Activity table - tracks additions and removals
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS buy_list_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                action TEXT NOT NULL,
                action_date DATE NOT NULL,
                reason TEXT,
                entry_price REAL,
                stop_price REAL,
                target_price REAL,
                rs REAL,
                vol_ratio REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Trades table - historical trade log
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {config.TRADES_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                entry_date DATE NOT NULL,
                entry_price REAL NOT NULL,
                exit_date DATE,
                exit_price REAL,
                shares INTEGER NOT NULL,
                pnl_dollars REAL,
                pnl_percent REAL,
                exit_reason TEXT,
                stop_price REAL,
                target_price REAL,
                days_held INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        conn.close()

        # Ensure columns exist (flexible schema evolution)
        self._ensure_columns_exist('buy_list_activity', {'vol_ratio': 'REAL', 'volume_ratio': 'REAL'})

        # Ensure all lagged feature columns exist (for databases created before these were added)
        lagged_columns = {
            'nATR_lag1': 'REAL',
            'atr_lag1': 'REAL',
            'vcp_ratio_lag1': 'REAL',
            'consolidation_width_lag1': 'REAL',
            'price_vs_sma50_lag1': 'REAL',
            'price_vs_sma150_lag1': 'REAL',
            'price_vs_sma200_lag1': 'REAL',
            'rs_lag1': 'REAL',
            'rs_ma_lag1': 'REAL',
            'dry_up_volume_lag1': 'REAL',
            'high_52w_lag1': 'REAL',
            'low_52w_lag1': 'REAL',
            'rsi14_lag1': 'REAL',
            'dist_from_52w_high_lag1': 'REAL',
            'ml_features': 'TEXT',
            'ml_expected_return': 'REAL',
            'ml_model_type': 'TEXT'
        }
        self._ensure_columns_exist('buy_list', lagged_columns)

        logger.info(f"Database initialized at {self.db_path}")

    def _ensure_columns_exist(self, table_name: str, columns: Dict[str, str]):
        """
        Ensures that the specified columns exist in the table.
        Adds them if they are missing.
        
        Args:
            table_name: Name of the table
            columns: Dictionary of {column_name: sql_type}
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get existing columns
        try:
            cursor.execute(f"PRAGMA table_info({table_name})")
            existing_cols = {row[1] for row in cursor.fetchall()}
            
            for col_name, col_type in columns.items():
                if col_name not in existing_cols:
                    try:
                        logger.info(f"Adding missing column '{col_name}' to table '{table_name}'")
                        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}")
                    except sqlite3.OperationalError as e:
                        logger.warning(f"Could not add column {col_name}: {e}")
            
            conn.commit()
        except Exception as e:
            logger.error(f"Error checking columns for {table_name}: {e}")
        finally:
            conn.close()

    # ==================== WATCHLIST METHODS ====================

    def add_to_watchlist(self, ticker: str, current_date: str,
                        rs: Optional[float] = None, vol_ratio: Optional[float] = None):
        """
        Adds or updates a ticker on the watchlist.

        Args:
            ticker: Stock symbol
            current_date: Current date (YYYY-MM-DD)
            rs: Relative strength value
            vol_ratio: Volume ratio value
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Check if ticker already exists
        cursor.execute(f"SELECT first_seen FROM {config.WATCHLIST_TABLE} WHERE ticker = ?", (ticker,))
        result = cursor.fetchone()

        if result:
            # Update existing entry
            first_seen = result[0]
            days_on_watchlist = (pd.to_datetime(current_date) - pd.to_datetime(first_seen)).days + 1

            cursor.execute(f"""
                UPDATE {config.WATCHLIST_TABLE}
                SET last_seen = ?, days_on_watchlist = ?, avg_rs = ?, avg_volume_ratio = ?
                WHERE ticker = ?
            """, (current_date, days_on_watchlist, rs, vol_ratio, ticker))
        else:
            # Insert new entry
            cursor.execute(f"""
                INSERT INTO {config.WATCHLIST_TABLE}
                (ticker, first_seen, last_seen, days_on_watchlist, avg_rs, avg_volume_ratio)
                VALUES (?, ?, ?, 1, ?, ?)
            """, (ticker, current_date, current_date, rs, vol_ratio))

        conn.commit()
        conn.close()

    def remove_from_watchlist(self, ticker: str, reason: str = 'triggered'):
        """
        Removes a ticker from the watchlist (e.g., when trade is taken).

        Args:
            ticker: Stock symbol
            reason: Reason for removal (e.g., 'triggered', 'failed_setup')
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(f"""
            UPDATE {config.WATCHLIST_TABLE}
            SET status = 'removed', notes = ?
            WHERE ticker = ?
        """, (reason, ticker))

        conn.commit()
        conn.close()

    def get_watchlist(self, active_only: bool = True) -> pd.DataFrame:
        """
        Retrieves current watchlist.

        Args:
            active_only: If True, only returns active setups

        Returns:
            DataFrame of watchlist entries
        """
        conn = sqlite3.connect(self.db_path)

        query = f"SELECT * FROM {config.WATCHLIST_TABLE}"
        if active_only:
            query += " WHERE status = 'active'"
        query += " ORDER BY days_on_watchlist DESC"

        df = pd.read_sql_query(query, conn)
        conn.close()

        return df

    def clean_stale_watchlist(self, days_threshold: int = 30):
        """
        Removes watchlist entries older than threshold.

        Args:
            days_threshold: Max days a stock can remain on watchlist
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(f"""
            UPDATE {config.WATCHLIST_TABLE}
            SET status = 'stale'
            WHERE days_on_watchlist > ? AND status = 'active'
        """, (days_threshold,))

        removed_count = cursor.rowcount
        conn.commit()
        conn.close()

        logger.info(f"Marked {removed_count} stale watchlist entries")

    # ==================== BUY LIST METHODS ====================

    def add_to_buy_list(self, ticker: str, signal_date: str, signal_price: float,
                       current_price: float, entry_price: Optional[float] = None,
                       stop_price: Optional[float] = None, target_price: Optional[float] = None,
                       atr: Optional[float] = None, rs: Optional[float] = None,
                       vol_ratio: Optional[float] = None, ma50: Optional[float] = None,
                       ma150: Optional[float] = None, ma200: Optional[float] = None,
                       high_52w: Optional[float] = None, low_52w: Optional[float] = None,
                       # Lagged features (setup conditions at T-1)
                       nATR_lag1: Optional[float] = None, atr_lag1: Optional[float] = None,
                       vcp_ratio_lag1: Optional[float] = None, consolidation_width_lag1: Optional[float] = None,
                       price_vs_sma50_lag1: Optional[float] = None, price_vs_sma150_lag1: Optional[float] = None,
                       price_vs_sma200_lag1: Optional[float] = None, rs_lag1: Optional[float] = None,
                       rs_ma_lag1: Optional[float] = None, dry_up_volume_lag1: Optional[float] = None,
                       high_52w_lag1: Optional[float] = None, low_52w_lag1: Optional[float] = None,
                       rsi14_lag1: Optional[float] = None, dist_from_52w_high_lag1: Optional[float] = None,
                       # ML scores
                       ml_probability: Optional[float] = None, ml_expected_return: Optional[float] = None,
                       ml_model_type: Optional[str] = None, ml_rank: Optional[int] = None,
                       ml_model_version: Optional[str] = None, ml_score_date: Optional[str] = None,
                       ml_features: Optional[Dict] = None):
        """
        Adds or updates a ticker on the buy list (active buy signals).

        Args:
            ticker: Stock symbol
            signal_date: Date signal triggered
            signal_price: Price when signal triggered
            current_price: Current price
            entry_price: Planned entry price (optional)
            stop_price: Stop loss price (optional)
            target_price: Profit target price (optional)
            atr: ATR value
            rs: Relative strength
            vol_ratio: Volume ratio
            ma50: 50-day moving average
            ma150: 150-day moving average
            ma200: 200-day moving average
            high_52w: 52-week high
            low_52w: 52-week low
            nATR_lag1: Lagged normalized ATR (T-1)
            atr_lag1: Lagged ATR (T-1)
            vcp_ratio_lag1: Lagged VCP ratio (T-1)
            consolidation_width_lag1: Lagged consolidation width (T-1)
            price_vs_sma50_lag1: Lagged price vs SMA50 (T-1)
            price_vs_sma150_lag1: Lagged price vs SMA150 (T-1)
            price_vs_sma200_lag1: Lagged price vs SMA200 (T-1)
            rs_lag1: Lagged relative strength (T-1)
            rs_ma_lag1: Lagged RS moving average (T-1)
            dry_up_volume_lag1: Lagged dry up volume indicator (T-1)
            high_52w_lag1: Lagged 52-week high (T-1)
            low_52w_lag1: Lagged 52-week low (T-1)
            rsi14_lag1: Lagged RSI 14 (T-1)
            dist_from_52w_high_lag1: Lagged distance from 52W high (T-1)
            ml_probability: ML success probability (0.0-1.0) - for classification models
            ml_expected_return: ML expected return percentage - for regression models
            ml_model_type: Type of ML model used ('regression' or 'classification')
            ml_rank: ML rank (1=best)
            ml_model_version: Model version identifier
            ml_score_date: Date ML score was generated
            ml_features: Dictionary of ML model features (stored as JSON)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        last_updated = datetime.now().strftime('%Y-%m-%d')
        
        # Convert ml_features dict to JSON string if provided
        ml_features_json = json.dumps(ml_features) if ml_features else None

        cursor.execute("""
            INSERT OR REPLACE INTO buy_list
            (ticker, signal_date, signal_price, current_price, entry_price, stop_price,
             target_price, atr, rs, volume_ratio, ma50, ma150, ma200, high_52w, low_52w,
             nATR_lag1, atr_lag1, vcp_ratio_lag1, consolidation_width_lag1,
             price_vs_sma50_lag1, price_vs_sma150_lag1, price_vs_sma200_lag1,
             rs_lag1, rs_ma_lag1, dry_up_volume_lag1,
             high_52w_lag1, low_52w_lag1, rsi14_lag1, dist_from_52w_high_lag1,
             ml_probability, ml_expected_return, ml_model_type, ml_rank, ml_model_version, ml_score_date, ml_features,
             last_updated, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
        """, (ticker, signal_date, signal_price, current_price, entry_price, stop_price,
              target_price, atr, rs, vol_ratio, ma50, ma150, ma200, high_52w, low_52w,
              nATR_lag1, atr_lag1, vcp_ratio_lag1, consolidation_width_lag1,
              price_vs_sma50_lag1, price_vs_sma150_lag1, price_vs_sma200_lag1,
              rs_lag1, rs_ma_lag1, dry_up_volume_lag1,
              high_52w_lag1, low_52w_lag1, rsi14_lag1, dist_from_52w_high_lag1,
              ml_probability, ml_expected_return, ml_model_type, ml_rank, ml_model_version, ml_score_date, ml_features_json,
              last_updated))

        conn.commit()
        conn.close()

    def remove_from_buy_list(self, ticker: str, reason: str = 'executed'):
        """
        Removes a ticker from buy list and logs to activity table.

        Args:
            ticker: Stock symbol
            reason: Reason for removal
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get the signal_date before removing
        cursor.execute("""
            SELECT signal_date, entry_price, stop_price, target_price, rs, volume_ratio
            FROM buy_list
            WHERE ticker = ? AND status = 'active'
        """, (ticker,))
        row = cursor.fetchone()
        
        if row:
            signal_date, entry_price, stop_price, target_price, rs, vol_ratio = row
            
            # Log to activity table
            cursor.execute("""
                INSERT INTO buy_list_activity 
                (ticker, action, action_date, reason, entry_price, stop_price, target_price, rs, vol_ratio)
                VALUES (?, 'removed', DATE('now'), ?, ?, ?, ?, ?, ?)
            """, (ticker, reason, entry_price, stop_price, target_price, rs, vol_ratio))

        # Update buy_list to mark as removed
        cursor.execute("""
            UPDATE buy_list
            SET status = 'removed', notes = ?
            WHERE ticker = ?
        """, (reason, ticker))

        conn.commit()
        conn.close()

    def update_buy_list_metrics(self, ticker: str, scan_date: str, current_price: float,
                                rs: Optional[float] = None, vol_ratio: Optional[float] = None,
                                ma50: Optional[float] = None, ma150: Optional[float] = None,
                                ma200: Optional[float] = None, high_52w: Optional[float] = None,
                                low_52w: Optional[float] = None,
                                ml_probability: Optional[float] = None, ml_expected_return: Optional[float] = None,
                                ml_model_type: Optional[str] = None, ml_rank: Optional[int] = None,
                                ml_model_version: Optional[str] = None, ml_score_date: Optional[str] = None,
                                ml_features: Optional[str] = None):
        """
        Updates metrics for an existing buy list entry.

        Args:
            ticker: Stock symbol
            scan_date: Date of the update
            current_price: Current price
            rs: Relative strength
            vol_ratio: Volume ratio
            ma50: 50-day moving average
            ma150: 150-day moving average
            ma200: 200-day moving average
            high_52w: 52-week high
            low_52w: 52-week low
            ml_probability: ML model probability score (for classification)
            ml_expected_return: ML expected return percentage (for regression)
            ml_model_type: Type of ML model ('regression' or 'classification')
            ml_rank: ML rank among all active candidates
            ml_model_version: Version of the ML model used
            ml_score_date: Date when ML score was calculated
            ml_features: JSON string of feature values used for scoring
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Build dynamic SQL to only update provided ML fields
        sql = """
            UPDATE buy_list
            SET current_price = ?, rs = ?, volume_ratio = ?,
                ma50 = ?, ma150 = ?, ma200 = ?, high_52w = ?, low_52w = ?,
                last_updated = ?
        """
        params = [current_price, rs, vol_ratio, ma50, ma150, ma200, high_52w, low_52w, scan_date]
        
        # Add ML fields if provided
        if ml_probability is not None:
            sql += ", ml_probability = ?"
            params.append(ml_probability)
        if ml_expected_return is not None:
            sql += ", ml_expected_return = ?"
            params.append(ml_expected_return)
        if ml_model_type is not None:
            sql += ", ml_model_type = ?"
            params.append(ml_model_type)
        if ml_rank is not None:
            sql += ", ml_rank = ?"
            params.append(ml_rank)
        if ml_model_version is not None:
            sql += ", ml_model_version = ?"
            params.append(ml_model_version)
        if ml_score_date is not None:
            sql += ", ml_score_date = ?"
            params.append(ml_score_date)
        if ml_features is not None:
            sql += ", ml_features = ?"
            params.append(ml_features)
        
        sql += " WHERE ticker = ? AND status = 'active'"
        params.append(ticker)

        cursor.execute(sql, tuple(params))

        conn.commit()
        conn.close()

    def update_buy_list_ml_rank(self, ticker: str, ml_rank: int):
        """
        Updates only the ML rank for a ticker in buy_list.
        Used for recalculating ranks across entire buy list.

        Args:
            ticker: Stock symbol
            ml_rank: New ML rank (1=best)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE buy_list
            SET ml_rank = ?
            WHERE ticker = ? AND status = 'active'
        """, (ml_rank, ticker))

        conn.commit()
        conn.close()

    def batch_update_ml_scores(self, updates: List[Dict]):
        """
        Batch update ML scores for multiple tickers in a single transaction.
        Solves database locking issues by using one connection for all updates.

        Args:
            updates: List of dicts with keys:
                - ticker: Stock symbol
                - ml_probability: ML success probability (for classification)
                - ml_expected_return: ML expected return % (for regression)
                - ml_model_type: Type of model ('regression' or 'classification')
                - ml_rank: ML rank
                - ml_model_version: Model version
                - ml_score_date: Date ML score was calculated
                - ml_features: JSON string of features

        Returns:
            Number of successfully updated tickers
        """
        if not updates:
            return 0

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        update_count = 0

        try:
            for update in updates:
                ticker = update['ticker']
                ml_prob = update.get('ml_probability')
                ml_expected_return = update.get('ml_expected_return')
                ml_model_type = update.get('ml_model_type')
                ml_rank = update.get('ml_rank')
                ml_version = update.get('ml_model_version')
                ml_date = update.get('ml_score_date')
                ml_features = update.get('ml_features')

                cursor.execute("""
                    UPDATE buy_list
                    SET ml_probability = ?,
                        ml_expected_return = ?,
                        ml_model_type = ?,
                        ml_rank = ?,
                        ml_model_version = ?,
                        ml_score_date = ?,
                        ml_features = ?,
                        last_updated = ?
                    WHERE ticker = ? AND status = 'active'
                """, (ml_prob, ml_expected_return, ml_model_type, ml_rank, ml_version, ml_date, ml_features,
                      datetime.now().strftime('%Y-%m-%d'), ticker))

                if cursor.rowcount > 0:
                    update_count += 1

            conn.commit()
            logger.info(f"Batch updated ML scores for {update_count}/{len(updates)} tickers")

        except Exception as e:
            conn.rollback()
            logger.error(f"Batch update failed: {e}")
            raise
        finally:
            conn.close()

        return update_count


    def get_buy_list(self, active_only: bool = True, as_of_date: Optional[str] = None) -> pd.DataFrame:
        """
        Retrieves buy list, optionally filtered to a specific point in time.

        Args:
            active_only: If True, only returns active signals
            as_of_date: Optional date string (YYYY-MM-DD). If provided, returns buy list
                       as it would have appeared on that date (signal_date <= as_of_date)

        Returns:
            DataFrame of buy list entries
        """
        conn = sqlite3.connect(self.db_path)

        query = "SELECT * FROM buy_list"
        conditions = []
        
        if active_only:
            conditions.append("status = 'active'")
        
        if as_of_date:
            conditions.append(f"signal_date <= '{as_of_date}'")
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " ORDER BY signal_date DESC"

        df = pd.read_sql_query(query, conn)
        conn.close()
        
        # Parse ml_features JSON back to dict
        if not df.empty and 'ml_features' in df.columns:
            df['ml_features'] = df['ml_features'].apply(
                lambda x: json.loads(x) if x and isinstance(x, str) else None
            )

        return df

    def log_buy_list_activity(self, ticker: str, action: str, action_date: str,
                              reason: Optional[str] = None, entry_price: Optional[float] = None,
                              stop_price: Optional[float] = None, target_price: Optional[float] = None,
                              rs: Optional[float] = None, vol_ratio: Optional[float] = None):
        """
        Logs buy list activity (additions/removals) for historical tracking.
        Prevents duplicate entries for same ticker+action+date combination.

        Args:
            ticker: Stock symbol
            action: Action type ('ADDED' or 'REMOVED')
            action_date: Date of the action
            reason: Reason for the action
            entry_price: Entry price (for ADDED actions)
            stop_price: Stop price (for ADDED actions)
            target_price: Target price (for ADDED actions)
            rs: Relative strength
            vol_ratio: Volume ratio
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Check if this exact activity already exists (prevent duplicates when re-running same day)
        cursor.execute("""
            SELECT id FROM buy_list_activity
            WHERE ticker = ? AND action = ? AND action_date = ?
        """, (ticker, action, action_date))

        existing = cursor.fetchone()

        if existing:
            # Update existing activity record instead of inserting duplicate
            cursor.execute("""
                UPDATE buy_list_activity
                SET reason = ?, entry_price = ?, stop_price = ?, target_price = ?, rs = ?, vol_ratio = ?
                WHERE id = ?
            """, (reason, entry_price, stop_price, target_price, rs, vol_ratio, existing[0]))
        else:
            # Insert new activity record
            cursor.execute("""
                INSERT INTO buy_list_activity
                (ticker, action, action_date, reason, entry_price, stop_price, target_price, rs, vol_ratio)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (ticker, action, action_date, reason, entry_price, stop_price, target_price, rs, vol_ratio))

        conn.commit()
        conn.close()

    def clear_future_signals(self, cutoff_date: str) -> dict:
        """
        Clears buy_list entries and activity records that occur after the cutoff date.
        Used for backward scans to maintain temporal consistency.

        Args:
            cutoff_date: Date string (YYYY-MM-DD). Signals after this date will be removed.

        Returns:
            Dictionary with counts of deleted records
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Count what will be deleted (for reporting)
        cursor.execute("""
            SELECT COUNT(*) FROM buy_list WHERE signal_date > ?
        """, (cutoff_date,))
        buy_list_count = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) FROM buy_list_activity WHERE action_date > ?
        """, (cutoff_date,))
        activity_count = cursor.fetchone()[0]

        # Delete future signals from buy_list
        cursor.execute("""
            DELETE FROM buy_list WHERE signal_date > ?
        """, (cutoff_date,))

        # Delete future activity records
        cursor.execute("""
            DELETE FROM buy_list_activity WHERE action_date > ?
        """, (cutoff_date,))

        conn.commit()
        conn.close()

        logger.info(f"Cleared {buy_list_count} buy_list entries and {activity_count} activity records after {cutoff_date}")
        
        return {
            'buy_list_deleted': buy_list_count,
            'activity_deleted': activity_count
        }

    def clean_old_buy_signals(self, days_threshold: int = 7):
        """
        Marks buy signals older than threshold as stale.

        Args:
            days_threshold: Max days a buy signal stays active
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE buy_list
            SET status = 'expired'
            WHERE julianday('now') - julianday(signal_date) > ? AND status = 'active'
        """, (days_threshold,))

        removed_count = cursor.rowcount
        conn.commit()
        conn.close()

        logger.info(f"Marked {removed_count} expired buy signals")

    # ==================== TRADE LOG METHODS ====================

    def log_trade(self, ticker: str, entry_date: str, entry_price: float,
                 shares: int, stop_price: float, target_price: float):
        """
        Logs a new trade entry.

        Args:
            ticker: Stock symbol
            entry_date: Entry date (YYYY-MM-DD)
            entry_price: Entry price
            shares: Number of shares
            stop_price: Stop loss price
            target_price: Profit target price

        Returns:
            Trade ID
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(f"""
            INSERT INTO {config.TRADES_TABLE}
            (ticker, entry_date, entry_price, shares, stop_price, target_price)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (ticker, entry_date, entry_price, shares, stop_price, target_price))

        trade_id = cursor.lastrowid
        conn.commit()
        conn.close()

        logger.info(f"Logged trade entry: {ticker} @ ${entry_price}")
        return trade_id

    def close_trade(self, ticker: str, exit_date: str, exit_price: float, exit_reason: str):
        """
        Updates a trade with exit information.

        Args:
            ticker: Stock symbol
            exit_date: Exit date (YYYY-MM-DD)
            exit_price: Exit price
            exit_reason: Reason for exit
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Find the most recent open trade for this ticker
        cursor.execute(f"""
            SELECT id, entry_date, entry_price, shares
            FROM {config.TRADES_TABLE}
            WHERE ticker = ? AND exit_date IS NULL
            ORDER BY entry_date DESC
            LIMIT 1
        """, (ticker,))

        result = cursor.fetchone()

        if not result:
            logger.warning(f"No open trade found for {ticker}")
            conn.close()
            return

        trade_id, entry_date, entry_price, shares = result

        # Calculate P&L
        pnl_dollars = (exit_price - entry_price) * shares
        pnl_percent = ((exit_price - entry_price) / entry_price) * 100

        # Calculate days held
        days_held = (pd.to_datetime(exit_date) - pd.to_datetime(entry_date)).days

        # Update trade
        cursor.execute(f"""
            UPDATE {config.TRADES_TABLE}
            SET exit_date = ?, exit_price = ?, pnl_dollars = ?, pnl_percent = ?,
                exit_reason = ?, days_held = ?
            WHERE id = ?
        """, (exit_date, exit_price, pnl_dollars, pnl_percent, exit_reason, days_held, trade_id))

        conn.commit()
        conn.close()

        logger.info(f"Closed trade: {ticker} @ ${exit_price} ({pnl_percent:+.2f}%) - {exit_reason}")

    def get_trade_history(self, ticker: Optional[str] = None,
                         closed_only: bool = False) -> pd.DataFrame:
        """
        Retrieves trade history.

        Args:
            ticker: Optional ticker filter
            closed_only: If True, only returns closed trades

        Returns:
            DataFrame of trades
        """
        conn = sqlite3.connect(self.db_path)

        query = f"SELECT * FROM {config.TRADES_TABLE}"
        conditions = []

        if ticker:
            conditions.append(f"ticker = '{ticker}'")
        if closed_only:
            conditions.append("exit_date IS NOT NULL")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY entry_date DESC"

        df = pd.read_sql_query(query, conn)
        conn.close()

        return df

    def get_performance_summary(self) -> Dict:
        """
        Calculates summary statistics from trade log.

        Returns:
            Dictionary of performance metrics
        """
        conn = sqlite3.connect(self.db_path)

        # Get all closed trades
        query = f"SELECT * FROM {config.TRADES_TABLE} WHERE exit_date IS NOT NULL"
        df = pd.read_sql_query(query, conn)
        conn.close()

        if df.empty:
            return {}

        wins = df[df['pnl_percent'] > 0]
        losses = df[df['pnl_percent'] <= 0]

        return {
            'total_trades': len(df),
            'winning_trades': len(wins),
            'losing_trades': len(losses),
            'win_rate': len(wins) / len(df) if len(df) > 0 else 0,
            'total_pnl': df['pnl_dollars'].sum(),
            'avg_win': wins['pnl_percent'].mean() if not wins.empty else 0,
            'avg_loss': losses['pnl_percent'].mean() if not losses.empty else 0,
            'avg_days_held': df['days_held'].mean()
        }

    def export_to_csv(self, table_name: str, output_path: str):
        """
        Exports a table to CSV.

        Args:
            table_name: Name of table to export
            output_path: Path to save CSV
        """
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
        conn.close()

        df.to_csv(output_path, index=False)
        logger.info(f"Exported {table_name} to {output_path}")
