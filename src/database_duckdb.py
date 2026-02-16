"""
DuckDB Database Manager - Buy List Operations
==============================================
Drop-in replacement for SQLite DatabaseManager using DuckDB.

Manages buy_list table in market_data.duckdb with identical API to database.py.
Key differences from SQLite version:
1. Uses DuckDB's INSERT ... ON CONFLICT for upserts
2. Batch operations for better performance
3. Integrated with market_data.duckdb (same database as price/fundamental data)
"""

import duckdb
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

# Database path (shared with price/fundamental data)
DB_PATH = Path(__file__).parent.parent / "data" / "market_data.duckdb"


class DuckDBManager:
    """
    Manages DuckDB database for buy list tracking.

    Tables:
    - buy_list: Active buy signals with ML scores and features
    - buy_list_activity: Historical log of additions/removals
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize database manager.

        Args:
            db_path: Path to DuckDB database file
        """
        self.db_path = str(db_path or DB_PATH)
        self._init_database()

    def _init_database(self):
        """Creates database tables if they don't exist."""
        con = duckdb.connect(self.db_path)

        try:
            # Buy List table - active buy signals
            con.execute("""
                CREATE TABLE IF NOT EXISTS buy_list (
                    ticker VARCHAR PRIMARY KEY,
                    signal_date DATE NOT NULL,
                    signal_price DOUBLE NOT NULL,
                    current_price DOUBLE NOT NULL,
                    entry_price DOUBLE,
                    stop_price DOUBLE,
                    target_price DOUBLE,
                    atr DOUBLE,
                    rs DOUBLE,
                    volume_ratio DOUBLE,
                    ma50 DOUBLE,
                    ma150 DOUBLE,
                    ma200 DOUBLE,
                    high_52w DOUBLE,
                    low_52w DOUBLE,

                    -- Lagged features (setup conditions at T-1)
                    nATR_lag1 DOUBLE,
                    atr_lag1 DOUBLE,
                    vcp_ratio_lag1 DOUBLE,
                    consolidation_width_lag1 DOUBLE,
                    price_vs_sma50_lag1 DOUBLE,
                    price_vs_sma150_lag1 DOUBLE,
                    price_vs_sma200_lag1 DOUBLE,
                    rs_lag1 DOUBLE,
                    rs_ma_lag1 DOUBLE,
                    dry_up_volume_lag1 DOUBLE,
                    high_52w_lag1 DOUBLE,
                    low_52w_lag1 DOUBLE,
                    rsi14_lag1 DOUBLE,
                    dist_from_52w_high_lag1 DOUBLE,

                    -- ML scores (legacy single model)
                    ml_probability DOUBLE,
                    ml_expected_return DOUBLE,
                    ml_model_type VARCHAR,
                    ml_rank INTEGER,
                    ml_model_version VARCHAR,
                    ml_score_date DATE,
                    ml_features VARCHAR,

                    -- Dual-model columns (M01 + M02)
                    m01_expected_return DOUBLE,      -- M01 regressor output
                    m01_rank INTEGER,                -- M01 rank (1=best)
                    m01_3bar_prob DOUBLE,            -- Legacy M01_3BAR_V2 classifier (0-1)
                    m01_3bar_rank INTEGER,           -- Legacy M01_3BAR rank
                    m01_3bar_sl_price DOUBLE,        -- Stop loss price
                    m01_3bar_tp_price DOUBLE,        -- Target price
                    m02_loser_proba DOUBLE,          -- P(loser) from M02
                    m02_survival DOUBLE,             -- 1 - P(loser)
                    final_score DOUBLE,              -- M01_adj × m02_survival
                    final_score_rank INTEGER,        -- Final score rank (1=best)

                    -- M03 Regime columns
                    m03_regime_score DOUBLE,         -- 0-100 regime risk score
                    m03_regime_category VARCHAR,     -- strong_bull, bull, neutral, bear, strong_bear

                    last_updated DATE,
                    status VARCHAR DEFAULT 'active',
                    notes VARCHAR
                )
            """)

            # Buy List Activity table - historical log
            con.execute("""
                CREATE TABLE IF NOT EXISTS buy_list_activity (
                    id INTEGER PRIMARY KEY,
                    ticker VARCHAR NOT NULL,
                    action VARCHAR NOT NULL,
                    action_date DATE NOT NULL,
                    reason VARCHAR,
                    entry_price DOUBLE,
                    stop_price DOUBLE,
                    target_price DOUBLE,
                    rs DOUBLE,
                    vol_ratio DOUBLE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create sequence for activity ID (DuckDB doesn't have AUTOINCREMENT)
            con.execute("""
                CREATE SEQUENCE IF NOT EXISTS buy_list_activity_seq START 1
            """)

        finally:
            con.close()

        logger.info(f"DuckDB database initialized at {self.db_path}")

    def add_to_buy_list(
        self,
        ticker: str,
        signal_date: str,
        signal_price: float,
        current_price: float,
        entry_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        target_price: Optional[float] = None,
        atr: Optional[float] = None,
        rs: Optional[float] = None,
        vol_ratio: Optional[float] = None,
        ma50: Optional[float] = None,
        ma150: Optional[float] = None,
        ma200: Optional[float] = None,
        high_52w: Optional[float] = None,
        low_52w: Optional[float] = None,
        ml_probability: Optional[float] = None,
        ml_expected_return: Optional[float] = None,
        ml_model_type: Optional[str] = None,
        ml_model_version: Optional[str] = None,
        ml_score_date: Optional[str] = None,
        ml_features: Optional[Dict] = None,
        lagged_features: Optional[Dict] = None
    ):
        """
        Adds a ticker to the buy list or updates if it exists.

        Args:
            ticker: Stock symbol
            signal_date: Date signal was triggered
            signal_price: Price when signal triggered
            current_price: Current market price
            entry_price: Recommended entry price
            stop_price: Stop loss price
            target_price: Profit target price
            atr: Average True Range
            rs: Relative Strength score
            vol_ratio: Volume ratio
            ma50/ma150/ma200: Moving averages
            high_52w/low_52w: 52-week high/low
            ml_probability: ML model probability (if classifier)
            ml_expected_return: ML expected return (if regressor)
            ml_model_type: Type of ML model ('classifier' or 'regressor')
            ml_model_version: ML model version string
            ml_score_date: Date when ML score was computed
            ml_features: Dict of feature values used for ML scoring
            lagged_features: Dict of T-1 lagged features
        """
        con = duckdb.connect(self.db_path)

        try:
            # Serialize ml_features if provided
            ml_features_json = json.dumps(ml_features) if ml_features else None

            # Build lagged feature values
            lagged_vals = {}
            if lagged_features:
                for key in [
                    'nATR_lag1', 'atr_lag1', 'vcp_ratio_lag1', 'consolidation_width_lag1',
                    'price_vs_sma50_lag1', 'price_vs_sma150_lag1', 'price_vs_sma200_lag1',
                    'rs_lag1', 'rs_ma_lag1', 'dry_up_volume_lag1',
                    'high_52w_lag1', 'low_52w_lag1', 'rsi14_lag1', 'dist_from_52w_high_lag1'
                ]:
                    lagged_vals[key] = lagged_features.get(key)

            # INSERT or UPDATE
            con.execute("""
                INSERT INTO buy_list (
                    ticker, signal_date, signal_price, current_price, entry_price,
                    stop_price, target_price, atr, rs, volume_ratio,
                    ma50, ma150, ma200, high_52w, low_52w,
                    nATR_lag1, atr_lag1, vcp_ratio_lag1, consolidation_width_lag1,
                    price_vs_sma50_lag1, price_vs_sma150_lag1, price_vs_sma200_lag1,
                    rs_lag1, rs_ma_lag1, dry_up_volume_lag1,
                    high_52w_lag1, low_52w_lag1, rsi14_lag1, dist_from_52w_high_lag1,
                    ml_probability, ml_expected_return, ml_model_type,
                    ml_model_version, ml_score_date, ml_features,
                    last_updated, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, 'active')
                ON CONFLICT (ticker) DO UPDATE SET
                    signal_date = EXCLUDED.signal_date,
                    signal_price = EXCLUDED.signal_price,
                    current_price = EXCLUDED.current_price,
                    entry_price = EXCLUDED.entry_price,
                    stop_price = EXCLUDED.stop_price,
                    target_price = EXCLUDED.target_price,
                    atr = EXCLUDED.atr,
                    rs = EXCLUDED.rs,
                    volume_ratio = EXCLUDED.volume_ratio,
                    ma50 = EXCLUDED.ma50,
                    ma150 = EXCLUDED.ma150,
                    ma200 = EXCLUDED.ma200,
                    high_52w = EXCLUDED.high_52w,
                    low_52w = EXCLUDED.low_52w,
                    nATR_lag1 = EXCLUDED.nATR_lag1,
                    atr_lag1 = EXCLUDED.atr_lag1,
                    vcp_ratio_lag1 = EXCLUDED.vcp_ratio_lag1,
                    consolidation_width_lag1 = EXCLUDED.consolidation_width_lag1,
                    price_vs_sma50_lag1 = EXCLUDED.price_vs_sma50_lag1,
                    price_vs_sma150_lag1 = EXCLUDED.price_vs_sma150_lag1,
                    price_vs_sma200_lag1 = EXCLUDED.price_vs_sma200_lag1,
                    rs_lag1 = EXCLUDED.rs_lag1,
                    rs_ma_lag1 = EXCLUDED.rs_ma_lag1,
                    dry_up_volume_lag1 = EXCLUDED.dry_up_volume_lag1,
                    high_52w_lag1 = EXCLUDED.high_52w_lag1,
                    low_52w_lag1 = EXCLUDED.low_52w_lag1,
                    rsi14_lag1 = EXCLUDED.rsi14_lag1,
                    dist_from_52w_high_lag1 = EXCLUDED.dist_from_52w_high_lag1,
                    ml_probability = EXCLUDED.ml_probability,
                    ml_expected_return = EXCLUDED.ml_expected_return,
                    ml_model_type = EXCLUDED.ml_model_type,
                    ml_model_version = EXCLUDED.ml_model_version,
                    ml_score_date = EXCLUDED.ml_score_date,
                    ml_features = EXCLUDED.ml_features,
                    last_updated = EXCLUDED.last_updated,
                    status = 'active'
            """, (
                ticker, signal_date, signal_price, current_price, entry_price,
                stop_price, target_price, atr, rs, vol_ratio,
                ma50, ma150, ma200, high_52w, low_52w,
                lagged_vals.get('nATR_lag1'), lagged_vals.get('atr_lag1'),
                lagged_vals.get('vcp_ratio_lag1'), lagged_vals.get('consolidation_width_lag1'),
                lagged_vals.get('price_vs_sma50_lag1'), lagged_vals.get('price_vs_sma150_lag1'),
                lagged_vals.get('price_vs_sma200_lag1'), lagged_vals.get('rs_lag1'),
                lagged_vals.get('rs_ma_lag1'), lagged_vals.get('dry_up_volume_lag1'),
                lagged_vals.get('high_52w_lag1'), lagged_vals.get('low_52w_lag1'),
                lagged_vals.get('rsi14_lag1'), lagged_vals.get('dist_from_52w_high_lag1'),
                ml_probability, ml_expected_return, ml_model_type,
                ml_model_version, ml_score_date, ml_features_json,
                signal_date
            ))

            # Log to activity table
            con.execute("""
                INSERT INTO buy_list_activity (
                    id, ticker, action, action_date, reason,
                    entry_price, stop_price, target_price, rs, vol_ratio
                )
                VALUES (
                    nextval('buy_list_activity_seq'),
                    ?, 'added', ?, 'signal_triggered',
                    ?, ?, ?, ?, ?
                )
            """, (ticker, signal_date, entry_price, stop_price, target_price, rs, vol_ratio))

        finally:
            con.close()

        logger.info(f"Added {ticker} to buy list at ${signal_price:.2f}")

    def remove_from_buy_list(self, ticker: str, reason: str = 'executed'):
        """
        Removes a ticker from buy list and logs to activity table.

        Args:
            ticker: Stock symbol
            reason: Reason for removal ('executed', 'stop_loss', 'target_hit', 'signal_failed')
        """
        con = duckdb.connect(self.db_path)

        try:
            # Get current entry for activity log
            result = con.execute("""
                SELECT entry_price, stop_price, target_price, rs, volume_ratio
                FROM buy_list
                WHERE ticker = ?
            """, (ticker,)).fetchone()

            if result:
                entry_price, stop_price, target_price, rs, vol_ratio = result

                # Log removal
                con.execute("""
                    INSERT INTO buy_list_activity (
                        id, ticker, action, action_date, reason,
                        entry_price, stop_price, target_price, rs, vol_ratio
                    )
                    VALUES (
                        nextval('buy_list_activity_seq'),
                        ?, 'removed', CURRENT_DATE, ?,
                        ?, ?, ?, ?, ?
                    )
                """, (ticker, reason, entry_price, stop_price, target_price, rs, vol_ratio))

            # Remove from buy_list
            con.execute("DELETE FROM buy_list WHERE ticker = ?", (ticker,))

            logger.info(f"Removed {ticker} from buy list (reason: {reason})")

        finally:
            con.close()

    def update_buy_list_metrics(
        self,
        ticker: str,
        scan_date: str,
        current_price: float,
        rs: Optional[float] = None,
        vol_ratio: Optional[float] = None,
        ma50: Optional[float] = None,
        ma150: Optional[float] = None,
        ma200: Optional[float] = None,
        high_52w: Optional[float] = None,
        low_52w: Optional[float] = None,
        ml_probability: Optional[float] = None,
        ml_expected_return: Optional[float] = None,
        ml_model_type: Optional[str] = None,
        ml_model_version: Optional[str] = None,
        ml_score_date: Optional[str] = None,
        ml_features: Optional[Dict] = None
    ):
        """
        Updates metrics for an existing ticker in buy list.

        Args:
            ticker: Stock symbol
            scan_date: Date of update
            current_price: Current market price
            rs: Updated relative strength
            vol_ratio: Updated volume ratio
            ma50/ma150/ma200: Updated moving averages
            high_52w/low_52w: Updated 52-week high/low
            ml_probability: Updated ML probability
            ml_expected_return: Updated ML expected return
            ml_model_type: ML model type
            ml_model_version: ML model version
            ml_score_date: Date when ML score was computed
            ml_features: Dict of feature values
        """
        con = duckdb.connect(self.db_path)

        try:
            # Build dynamic update statement
            updates = ["current_price = ?", "last_updated = ?"]
            params = [current_price, scan_date]

            if rs is not None:
                updates.append("rs = ?")
                params.append(rs)
            if vol_ratio is not None:
                updates.append("volume_ratio = ?")
                params.append(vol_ratio)
            if ma50 is not None:
                updates.append("ma50 = ?")
                params.append(ma50)
            if ma150 is not None:
                updates.append("ma150 = ?")
                params.append(ma150)
            if ma200 is not None:
                updates.append("ma200 = ?")
                params.append(ma200)
            if high_52w is not None:
                updates.append("high_52w = ?")
                params.append(high_52w)
            if low_52w is not None:
                updates.append("low_52w = ?")
                params.append(low_52w)
            if ml_probability is not None:
                updates.append("ml_probability = ?")
                params.append(ml_probability)
            if ml_expected_return is not None:
                updates.append("ml_expected_return = ?")
                params.append(ml_expected_return)
            if ml_model_type is not None:
                updates.append("ml_model_type = ?")
                params.append(ml_model_type)
            if ml_model_version is not None:
                updates.append("ml_model_version = ?")
                params.append(ml_model_version)
            if ml_score_date is not None:
                updates.append("ml_score_date = ?")
                params.append(ml_score_date)
            if ml_features is not None:
                updates.append("ml_features = ?")
                params.append(json.dumps(ml_features))

            params.append(ticker)  # For WHERE clause

            sql = f"UPDATE buy_list SET {', '.join(updates)} WHERE ticker = ?"
            con.execute(sql, tuple(params))

        finally:
            con.close()

    def update_buy_list_column(self, ticker: str, column: str, value):
        """
        Update a single column for a ticker in buy_list.

        Args:
            ticker: Stock symbol
            column: Column name to update
            value: New value
        """
        con = duckdb.connect(self.db_path)

        try:
            con.execute(
                f"UPDATE buy_list SET {column} = ? WHERE ticker = ?",
                (value, ticker)
            )
        finally:
            con.close()

    def get_buy_list(self, active_only: bool = True, as_of_date: Optional[str] = None) -> pd.DataFrame:
        """
        Retrieves buy list, optionally filtered to a specific point in time.

        Args:
            active_only: If True, only returns active signals
            as_of_date: If provided, filters to signals active as of that date

        Returns:
            DataFrame with buy list entries
        """
        con = duckdb.connect(self.db_path)

        try:
            query = "SELECT * FROM buy_list"
            conditions = []

            if active_only:
                conditions.append("status = 'active'")

            if as_of_date:
                conditions.append(f"signal_date <= '{as_of_date}'")

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            df = con.execute(query).df()

            return df

        finally:
            con.close()

    def get_buy_list_activity(
        self,
        ticker: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Retrieves buy list activity log.

        Args:
            ticker: Filter to specific ticker
            start_date: Filter to activities on or after this date
            end_date: Filter to activities on or before this date

        Returns:
            DataFrame with activity log
        """
        con = duckdb.connect(self.db_path)

        try:
            query = "SELECT * FROM buy_list_activity WHERE 1=1"

            if ticker:
                query += f" AND ticker = '{ticker}'"
            if start_date:
                query += f" AND action_date >= '{start_date}'"
            if end_date:
                query += f" AND action_date <= '{end_date}'"

            query += " ORDER BY action_date DESC"

            df = con.execute(query).df()

            return df

        finally:
            con.close()

    def clear_buy_list(self):
        """
        Clears all entries from buy list.
        WARNING: This removes all active signals!
        """
        con = duckdb.connect(self.db_path)

        try:
            con.execute("DELETE FROM buy_list")
            logger.warning("Cleared all buy list entries")

        finally:
            con.close()

    def get_stats(self) -> Dict:
        """
        Get buy list statistics.

        Returns:
            Dict with statistics (total_active, avg_rs, avg_vol_ratio, etc.)
        """
        con = duckdb.connect(self.db_path)

        try:
            result = con.execute("""
                SELECT
                    COUNT(*) as total_active,
                    AVG(rs) as avg_rs,
                    AVG(volume_ratio) as avg_vol_ratio,
                    AVG(m01_expected_return) as avg_m01_return,
                    AVG(final_score) as avg_final_score
                FROM buy_list
                WHERE status = 'active'
            """).fetchone()

            return {
                'total_active': result[0] or 0,
                'avg_rs': result[1],
                'avg_vol_ratio': result[2],
                'avg_m01_return': result[3],
                'avg_final_score': result[4]
            }

        finally:
            con.close()
