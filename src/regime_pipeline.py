"""
Regime Pipeline - Computes M03 market regime scores and writes to DuckDB

This module orchestrates M03 regime score calculation and storage in the t2_regime_scores table.
Uses the existing M03RegimeCalculator from src/pipeline/m03_regime.py.

Architecture:
- Reads from t1_macro table (SPY/QQQ/VIX data)
- Computes M03 scores using vectorized M03RegimeCalculator
- Writes to t2_regime_scores table (replaces parquet file approach)
"""

import logging
import duckdb
import pandas as pd
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta

import sys
sys.path.append(str(Path(__file__).parent.parent))
import config
from src.pipeline.m03_regime import M03RegimeCalculator

logging.basicConfig(level=getattr(logging, config.LOG_LEVEL))
logger = logging.getLogger(__name__)


class RegimePipeline:
    """
    M03 Regime Score Pipeline for DuckDB v2 Architecture.

    Responsibilities:
    1. Read SPY/QQQ/VIX from t1_macro table
    2. Compute M03 scores using M03RegimeCalculator
    3. Write results to t2_regime_scores table

    Note:
    - Replaces parquet file approach (data/regime_scores.parquet)
    - Idempotent: can be re-run safely with INSERT OR REPLACE
    - Vectorized: computes entire date range in one pass for efficiency
    """

    def __init__(self, db_path: str = None, config_path: str = None):
        """
        Initialize Regime Pipeline.

        Args:
            db_path: Path to DuckDB database
            config_path: Path to M03 config JSON file
        """
        self.db_path = db_path or 'data/market_data.duckdb'
        self.config_path = config_path or 'models/m03_config.json'
        self.calculator = M03RegimeCalculator(config_path=self.config_path)

    def _ensure_table_exists(self, con: duckdb.DuckDBPyConnection) -> None:
        """Create t2_regime_scores table if not exists."""
        con.execute("""
            CREATE TABLE IF NOT EXISTS t2_regime_scores (
                date DATE PRIMARY KEY,

                -- M03 Outputs
                m03_score DOUBLE,            -- Composite regime score (0-100)
                m03_pillar_trend DOUBLE,     -- Trend strength pillar (0-100)
                m03_pillar_liq DOUBLE,       -- Liquidity/breadth pillar (0-100)
                m03_pillar_risk DOUBLE,      -- Risk/volatility pillar (0-100)

                -- Derived Features (computed during feature engineering)
                m03_delta_5d DOUBLE,         -- 5-day change in m03_score
                m03_delta_20d DOUBLE,        -- 20-day change
                m03_regime_vol DOUBLE,       -- Volatility of regime transitions

                -- Metadata
                model_version VARCHAR DEFAULT 'v1.1.0',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Create index
        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_t2_regime_date
            ON t2_regime_scores(date);
        """)

        logger.info("t2_regime_scores table ready")

    def compute_m03_history(
        self,
        start_date: str = '2020-01-01',
        end_date: str = None,
        freq: str = 'D'
    ) -> pd.DataFrame:
        """
        Compute M03 regime scores over a date range.

        Uses M03RegimeCalculator.calculate_history_vectorized() for efficiency.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (defaults to yesterday)
            freq: Frequency ('D' for daily)

        Returns:
            DataFrame with M03 scores and pillar breakdowns
        """
        end_date = end_date or (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

        logger.info(f"Computing M03 regime history ({start_date} -> {end_date})")

        # Use vectorized calculation (includes T+1 lag handling automatically)
        df = self.calculator.calculate_history_vectorized(
            start_date=start_date,
            end_date=end_date,
            freq=freq
        )

        if df.empty:
            logger.warning("M03 calculation returned empty DataFrame")
            return pd.DataFrame()

        # Select columns for t2_regime_scores table
        result = pd.DataFrame({
            'date': df.index,
            'm03_score': df['score'],
            'm03_pillar_trend': df['trend_score'],
            'm03_pillar_liq': df['liquidity_score'],
            'm03_pillar_risk': df['risk_appetite_score'],
        })

        # Compute derived features
        result['m03_delta_5d'] = df['score'].diff(5)
        result['m03_delta_20d'] = df['score'].diff(20)
        result['m03_regime_vol'] = df['score'].rolling(10, min_periods=1).std()

        # Fill NaNs (early dates with insufficient lookback)
        result['m03_delta_5d'] = result['m03_delta_5d'].fillna(0)
        result['m03_delta_20d'] = result['m03_delta_20d'].fillna(0)
        result['m03_regime_vol'] = result['m03_regime_vol'].fillna(0)

        logger.info(f"Computed {len(result)} M03 regime scores")
        return result

    def write_to_db(
        self,
        df: pd.DataFrame,
        mode: str = 'replace'
    ) -> int:
        """
        Write regime scores to t2_regime_scores table.

        Args:
            df: DataFrame with M03 scores
            mode: 'replace' (INSERT OR REPLACE) or 'ignore' (INSERT OR IGNORE)

        Returns:
            Number of rows written
        """
        if df.empty:
            logger.warning("Empty DataFrame, nothing to write")
            return 0

        con = duckdb.connect(self.db_path)
        try:
            # Ensure table exists
            self._ensure_table_exists(con)

            # Register DataFrame
            con.register('regime_feed', df)

            # Count before
            before = con.execute("SELECT COUNT(*) FROM t2_regime_scores").fetchone()[0]

            # Insert based on mode
            insert_clause = "INSERT OR REPLACE" if mode == 'replace' else "INSERT OR IGNORE"
            con.execute(f"""
                {insert_clause} INTO t2_regime_scores (
                    date,
                    m03_score,
                    m03_pillar_trend,
                    m03_pillar_liq,
                    m03_pillar_risk,
                    m03_delta_5d,
                    m03_delta_20d,
                    m03_regime_vol
                )
                SELECT
                    date,
                    m03_score,
                    m03_pillar_trend,
                    m03_pillar_liq,
                    m03_pillar_risk,
                    m03_delta_5d,
                    m03_delta_20d,
                    m03_regime_vol
                FROM regime_feed
            """)

            # Count after
            after = con.execute("SELECT COUNT(*) FROM t2_regime_scores").fetchone()[0]
            written = after - before

            logger.info(f"Written {written} regime scores to t2_regime_scores (total: {after})")
            return written

        finally:
            con.close()

    def update_incremental(self) -> int:
        """
        Update regime scores incrementally from last date in table.

        Returns:
            Number of new rows written
        """
        con = duckdb.connect(self.db_path)
        try:
            # Ensure table exists
            self._ensure_table_exists(con)

            # Get last date in table
            max_date_result = con.execute("SELECT MAX(date) FROM t2_regime_scores").fetchone()

            if max_date_result[0]:
                last_date = pd.to_datetime(max_date_result[0])
                start_date = (last_date + timedelta(days=1)).strftime('%Y-%m-%d')
            else:
                # Table empty, backfill from 2020
                start_date = '2020-01-01'

        finally:
            con.close()

        # Compute new scores
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

        if start_date > yesterday:
            logger.info("No new regime scores to compute (already up-to-date)")
            return 0

        logger.info(f"Computing incremental regime scores from {start_date}")
        # Pad by 250 days so SMA-200 and rolling windows have enough warmup history.
        # Only dates >= start_date are written to avoid overwriting existing rows.
        warmup_start = (pd.to_datetime(start_date) - timedelta(days=250)).strftime('%Y-%m-%d')
        df = self.compute_m03_history(start_date=warmup_start)
        if not df.empty:
            df = df[df['date'] >= start_date]

        # Write to DB
        return self.write_to_db(df, mode='replace')

    def backfill(
        self,
        start_date: str = '2020-01-01',
        force: bool = False
    ) -> int:
        """
        Backfill regime scores from start_date to present.

        Args:
            start_date: Start date (YYYY-MM-DD)
            force: If True, overwrites existing data (INSERT OR REPLACE)

        Returns:
            Number of rows written
        """
        mode = 'replace' if force else 'ignore'

        logger.info(f"Backfilling regime scores from {start_date} (mode={mode})")
        df = self.compute_m03_history(start_date=start_date)

        return self.write_to_db(df, mode=mode)

    def validate_parity(self, parquet_path: str = 'models/m03_history.parquet') -> dict:
        """
        Validate DuckDB scores match parquet file values.

        Args:
            parquet_path: Path to legacy parquet file

        Returns:
            Dict with validation results
        """
        parquet_file = Path(parquet_path)
        if not parquet_file.exists():
            logger.warning(f"Parquet file not found: {parquet_path}")
            return {'status': 'skipped', 'reason': 'parquet_not_found'}

        # Load parquet
        parquet_df = pd.read_parquet(parquet_file)
        logger.info(f"Loaded {len(parquet_df)} rows from parquet")

        # Load from DuckDB
        con = duckdb.connect(self.db_path)
        try:
            db_df = con.execute("""
                SELECT date, m03_score
                FROM t2_regime_scores
                ORDER BY date
            """).df()
        finally:
            con.close()

        logger.info(f"Loaded {len(db_df)} rows from DuckDB")

        # Merge on date
        comparison = parquet_df.merge(
            db_df,
            left_on='date' if 'date' in parquet_df.columns else parquet_df.index,
            right_on='date',
            suffixes=('_parquet', '_db'),
            how='inner'
        )

        if comparison.empty:
            return {'status': 'fail', 'reason': 'no_matching_dates'}

        # Compute variance
        score_col_parquet = 'score' if 'score' in comparison.columns else 'm03_score_parquet'
        variance = (comparison[score_col_parquet] - comparison['m03_score']).abs()

        max_variance = variance.max()
        mean_variance = variance.mean()

        result = {
            'status': 'pass' if max_variance < 0.1 else 'fail',
            'rows_compared': len(comparison),
            'max_variance': float(max_variance),
            'mean_variance': float(mean_variance),
            'samples': comparison.sample(min(10, len(comparison)))[
                ['date', score_col_parquet, 'm03_score']
            ].to_dict('records')
        }

        if result['status'] == 'pass':
            logger.info(f"Validation PASSED: max variance = {max_variance:.4f}")
        else:
            logger.error(f"Validation FAILED: max variance = {max_variance:.4f}")

        return result


if __name__ == '__main__':
    """
    Standalone execution for testing.

    Usage:
        python src/regime_pipeline.py --backfill
        python src/regime_pipeline.py --update
        python src/regime_pipeline.py --validate
    """
    import argparse

    parser = argparse.ArgumentParser(description='M03 Regime Pipeline')
    parser.add_argument('--backfill', action='store_true', help='Backfill from 2020-01-01')
    parser.add_argument('--update', action='store_true', help='Incremental update')
    parser.add_argument('--validate', action='store_true', help='Validate vs parquet file')
    parser.add_argument('--start', type=str, default='2020-01-01', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--db', type=str, help='Database path (optional)')

    args = parser.parse_args()

    pipeline = RegimePipeline(db_path=args.db)

    if args.backfill:
        rows = pipeline.backfill(start_date=args.start, force=True)
        print(f"✅ Backfilled {rows} regime scores")

    elif args.update:
        rows = pipeline.update_incremental()
        print(f"✅ Updated {rows} new regime scores")

    elif args.validate:
        result = pipeline.validate_parity()
        print(f"Validation: {result['status'].upper()}")
        print(f"  Rows compared: {result.get('rows_compared', 0)}")
        print(f"  Max variance: {result.get('max_variance', 'N/A')}")

    else:
        parser.print_help()
