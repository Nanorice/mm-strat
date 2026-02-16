"""
DuckDB Migration Script - Phase 1

Reads existing parquet/CSV files and writes to DuckDB.
This script is the "single writer gatekeeper" during Phase 1.

Usage:
    python scripts/migrate_to_duckdb.py --mode initial  # One-time migration
    python scripts/migrate_to_duckdb.py --mode daily    # Daily incremental
"""

import argparse
from pathlib import Path
from datetime import datetime, timedelta
import duckdb
import pandas as pd
from typing import Optional
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "data" / "market_data.duckdb"
PRICE_DATA_DIR = PROJECT_ROOT / "data" / "price"  # Individual ticker parquet files
COMPANY_PROFILE_FILE = PROJECT_ROOT / "data" / "company_info" / "company_profiles.parquet"
EARNINGS_DIR = PROJECT_ROOT / "data" / "earnings"
MACRO_DIR = PROJECT_ROOT / "data" / "macro"


class DuckDBMigrator:
    """Single-writer gatekeeper for DuckDB operations."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn: Optional[duckdb.DuckDBPyConnection] = None

    def __enter__(self):
        """Context manager: open connection."""
        self.conn = duckdb.connect(str(self.db_path))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager: close connection."""
        if self.conn:
            self.conn.close()

    def initialize_schema(self):
        """Create tables if they don't exist."""
        logger.info("🔧 Initializing schema...")

        # Price data table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS price_data (
                ticker VARCHAR NOT NULL,
                date DATE NOT NULL,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume UBIGINT,
                adj_close DOUBLE,
                adj_factor DOUBLE,
                vwap DOUBLE,
                source VARCHAR,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ticker, date)
            )
        """)

        # Daily features table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_features (
                ticker VARCHAR NOT NULL,
                date DATE NOT NULL,
                sma_50 DOUBLE,
                sma_200 DOUBLE,
                ema_21 DOUBLE,
                atr_14 DOUBLE,
                vol_avg_50 DOUBLE,
                rs_rating DOUBLE,
                rs_vs_spy DOUBLE,
                high_52w DOUBLE,
                low_52w DOUBLE,
                pct_from_high_52w DOUBLE,
                vol_ratio_50 DOUBLE,
                feature_version VARCHAR,
                computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ticker, date)
            )
        """)

        # Company profiles table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS company_profiles (
                ticker VARCHAR PRIMARY KEY,
                name VARCHAR,
                sector VARCHAR,
                industry VARCHAR,
                market_cap DOUBLE,
                country VARCHAR,
                exchange VARCHAR,
                is_active BOOLEAN DEFAULT TRUE,
                listing_date DATE,
                delisting_date DATE,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Fundamentals table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS fundamentals (
                ticker VARCHAR NOT NULL,
                report_date DATE NOT NULL,
                filing_date DATE,
                period_type VARCHAR,
                fiscal_year INTEGER,
                revenue DOUBLE,
                net_income DOUBLE,
                eps_diluted DOUBLE,
                total_assets DOUBLE,
                total_equity DOUBLE,
                operating_cash_flow DOUBLE,
                raw_data JSON,
                source VARCHAR,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ticker, report_date, period_type)
            )
        """)

        # Buy list history
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS buy_list_history (
                scan_date DATE NOT NULL,
                ticker VARCHAR NOT NULL,
                rank INTEGER,
                score DOUBLE,
                reason VARCHAR,
                metadata JSON,
                PRIMARY KEY (scan_date, ticker)
            )
        """)

        # Macro data
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS macro_data (
                date DATE NOT NULL,
                symbol VARCHAR NOT NULL,
                close DOUBLE,
                volume UBIGINT,
                value DOUBLE,
                unit VARCHAR,
                PRIMARY KEY (date, symbol)
            )
        """)

        logger.info("✅ Schema initialized")

    def migrate_price_data(self, start_date: Optional[str] = None):
        """
        Migrate price data from individual ticker parquet files.

        Args:
            start_date: If provided, only migrate data from this date onwards (YYYY-MM-DD)
        """
        logger.info(f"📊 Migrating price data (start_date={start_date})...")

        if not PRICE_DATA_DIR.exists():
            logger.warning(f"⚠️  Price data directory not found at {PRICE_DATA_DIR}")
            return

        # Collect all ticker parquet files
        ticker_files = list(PRICE_DATA_DIR.glob("*.parquet"))
        logger.info(f"  Found {len(ticker_files)} ticker files")

        # Process in batches to manage memory
        batch_size = 100
        all_dfs = []

        for i, ticker_file in enumerate(ticker_files):
            try:
                ticker = ticker_file.stem
                df_ticker = pd.read_parquet(ticker_file)

                # Reset index if date is in index
                if df_ticker.index.name in ['Date', 'date']:
                    df_ticker = df_ticker.reset_index()

                # Add ticker column if missing
                if 'ticker' not in df_ticker.columns:
                    df_ticker['ticker'] = ticker

                # Rename Date to date if needed
                if 'Date' in df_ticker.columns:
                    df_ticker = df_ticker.rename(columns={'Date': 'date'})

                # Filter by date if specified
                if start_date and 'date' in df_ticker.columns:
                    df_ticker = df_ticker[df_ticker['date'] >= start_date]

                if len(df_ticker) > 0:
                    all_dfs.append(df_ticker)

                # Process batch
                if (i + 1) % batch_size == 0:
                    self._write_price_batch(all_dfs, i + 1 - batch_size, i + 1)
                    all_dfs = []

            except Exception as e:
                logger.error(f"  ❌ Error processing {ticker_file.name}: {e}")
                continue

        # Process remaining files
        if all_dfs:
            self._write_price_batch(all_dfs, len(ticker_files) - len(all_dfs), len(ticker_files))

        row_count = self.conn.execute("SELECT COUNT(*) FROM price_data").fetchone()[0]
        logger.info(f"✅ Price data migrated. Total rows: {row_count:,}")

    def _write_price_batch(self, dfs: list, start_idx: int, end_idx: int):
        """Helper to write a batch of price data."""
        if not dfs:
            return

        logger.info(f"  Processing batch {start_idx}-{end_idx}...")

        # Concatenate all dataframes
        df = pd.concat(dfs, ignore_index=True)

        # Normalize column names to lowercase
        df.columns = df.columns.str.lower()

        # Ensure required columns exist
        required_cols = ['ticker', 'date', 'close']
        if not all(col in df.columns for col in required_cols):
            logger.error(f"❌ Missing required columns. Found: {df.columns.tolist()}")
            return

        # Ensure date is datetime
        if not pd.api.types.is_datetime64_any_dtype(df['date']):
            df['date'] = pd.to_datetime(df['date'])

        # Remove rows with null dates or tickers
        df = df.dropna(subset=['date', 'ticker'])

        if len(df) == 0:
            logger.warning(f"  ⚠️  Batch {start_idx}-{end_idx} has no valid data after cleaning")
            return

        # Add source metadata
        if 'source' not in df.columns:
            df['source'] = 'yfinance'

        # CRITICAL: Sort by date, then ticker
        df = df.sort_values(['date', 'ticker'])

        # Use staging pattern: write to temp table, then insert
        # Drop staging table if it exists
        self.conn.execute("DROP TABLE IF EXISTS staging_price")

        # Get available columns that match price_data schema
        target_cols = ['ticker', 'date', 'open', 'high', 'low', 'close', 'volume',
                       'adj_close', 'adj_factor', 'vwap', 'source']
        available_cols = [col for col in target_cols if col in df.columns]

        # Select only matching columns
        df_insert = df[available_cols]

        self.conn.execute("CREATE TEMP TABLE staging_price AS SELECT * FROM df_insert")

        # Build dynamic upsert
        update_cols = [col for col in available_cols if col not in ['ticker', 'date']]
        if update_cols:
            update_set = ', '.join([f"{col} = EXCLUDED.{col}" for col in update_cols])
            update_query = f"""
                INSERT INTO price_data ({', '.join(available_cols)})
                SELECT {', '.join(available_cols)} FROM staging_price
                ON CONFLICT (ticker, date)
                DO UPDATE SET {update_set}
            """
        else:
            update_query = f"""
                INSERT INTO price_data ({', '.join(available_cols)})
                SELECT {', '.join(available_cols)} FROM staging_price
                ON CONFLICT (ticker, date) DO NOTHING
            """

        self.conn.execute(update_query)
        self.conn.execute("DROP TABLE staging_price")
        logger.info(f"  ✅ Batch written ({len(df):,} rows)")

    def migrate_company_profiles(self):
        """Migrate company profiles from parquet file."""
        logger.info("🏢 Migrating company profiles...")

        if not COMPANY_PROFILE_FILE.exists():
            logger.warning(f"⚠️  Company profiles not found at {COMPANY_PROFILE_FILE}")
            return

        # Load company profiles parquet
        df = pd.read_parquet(COMPANY_PROFILE_FILE)

        # Reset index if ticker is in index
        if df.index.name == 'ticker':
            df = df.reset_index()

        # Rename columns to match schema
        column_mapping = {
            'symbol': 'ticker',
            'companyName': 'name',
            'longName': 'name',
            'marketCap': 'market_cap',
            'mktCap': 'market_cap',
        }
        df = df.rename(columns=column_mapping)

        # Ensure required columns exist
        required_cols = ['ticker']
        for col in required_cols:
            if col not in df.columns:
                logger.error(f"❌ Missing required column: {col}")
                logger.error(f"   Available columns: {df.columns.tolist()}")
                return

        # Add default values for missing columns
        if 'is_active' not in df.columns:
            df['is_active'] = True

        # Select only relevant columns
        keep_cols = ['ticker', 'name', 'sector', 'industry', 'market_cap',
                     'country', 'exchange', 'is_active']
        df = df[[col for col in keep_cols if col in df.columns]]

        df = df.sort_values('ticker')

        # Get the list of columns from the target table
        target_cols_result = self.conn.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'company_profiles'
            AND column_name NOT IN ('updated_at', 'listing_date', 'delisting_date')
        """).fetchall()
        target_cols = [col[0] for col in target_cols_result]

        # Only keep columns that exist in both df and target table
        available_cols = [col for col in target_cols if col in df.columns]

        # Add missing required columns
        for col in target_cols:
            if col not in df.columns and col != 'ticker':
                df[col] = None

        # Select columns in order
        df_insert = df[[col for col in target_cols if col in df.columns]]

        self.conn.execute("CREATE TEMP TABLE staging_profiles AS SELECT * FROM df_insert")

        # Build dynamic upsert
        update_cols = [col for col in available_cols if col != 'ticker']
        if update_cols:
            update_set = ', '.join([f"{col} = EXCLUDED.{col}" for col in update_cols])
            update_query = f"""
                INSERT INTO company_profiles ({', '.join(available_cols)})
                SELECT {', '.join(available_cols)} FROM staging_profiles
                ON CONFLICT (ticker)
                DO UPDATE SET {update_set}
            """
        else:
            # No updateable columns, just insert
            update_query = f"""
                INSERT INTO company_profiles ({', '.join(available_cols)})
                SELECT {', '.join(available_cols)} FROM staging_profiles
                ON CONFLICT (ticker) DO NOTHING
            """

        self.conn.execute(update_query)
        self.conn.execute("DROP TABLE staging_profiles")

        count = self.conn.execute("SELECT COUNT(*) FROM company_profiles").fetchone()[0]
        logger.info(f"✅ Company profiles migrated. Total: {count:,}")

    def migrate_fundamentals(self):
        """Migrate fundamentals from earnings data."""
        logger.info("📈 Migrating fundamentals...")

        if not EARNINGS_DIR.exists():
            logger.warning(f"⚠️  Earnings directory not found at {EARNINGS_DIR}")
            return

        earnings_files = list(EARNINGS_DIR.glob("*.parquet"))
        logger.info(f"  Found {len(earnings_files)} earnings files")

        all_dfs = []
        batch_size = 100

        for i, earnings_file in enumerate(earnings_files):
            try:
                ticker = earnings_file.stem
                df_earnings = pd.read_parquet(earnings_file)

                if len(df_earnings) == 0:
                    continue

                # Map columns to fundamentals schema
                df_fundamental = pd.DataFrame({
                    'ticker': ticker,
                    'report_date': pd.to_datetime(df_earnings['date']),
                    'filing_date': pd.to_datetime(df_earnings.get('lastUpdated', df_earnings['date'])),
                    'period_type': 'Q',  # Assuming quarterly data
                    'fiscal_year': pd.to_datetime(df_earnings['date']).dt.year,
                    'revenue': df_earnings.get('revenueActual'),
                    'eps_diluted': df_earnings.get('epsActual'),
                    'source': 'earnings_parquet',
                })

                # Store full earnings data as JSON (DuckDB JSON type requires proper JSON strings)
                import json
                df_fundamental['raw_data'] = df_earnings.to_dict('records')
                df_fundamental['raw_data'] = df_fundamental['raw_data'].apply(
                    lambda x: json.dumps(x, default=str) if pd.notna(x) else None
                )

                all_dfs.append(df_fundamental)

                # Process batch
                if (i + 1) % batch_size == 0:
                    self._write_fundamentals_batch(all_dfs)
                    all_dfs = []

            except Exception as e:
                logger.error(f"  ❌ Error processing {earnings_file.name}: {e}")
                continue

        # Process remaining
        if all_dfs:
            self._write_fundamentals_batch(all_dfs)

        count = self.conn.execute("SELECT COUNT(*) FROM fundamentals").fetchone()[0]
        logger.info(f"✅ Fundamentals migrated. Total rows: {count:,}")

    def _write_fundamentals_batch(self, dfs: list):
        """Helper to write a batch of fundamentals data."""
        if not dfs:
            return

        df = pd.concat(dfs, ignore_index=True)
        df = df.sort_values(['ticker', 'report_date'])

        # Ensure date types
        if not pd.api.types.is_datetime64_any_dtype(df['report_date']):
            df['report_date'] = pd.to_datetime(df['report_date'])

        # Drop staging table if it exists
        self.conn.execute("DROP TABLE IF EXISTS staging_fundamentals")

        # Get available columns
        available_cols = [col for col in ['ticker', 'report_date', 'filing_date', 'period_type',
                                           'fiscal_year', 'revenue', 'net_income', 'eps_diluted',
                                           'total_assets', 'total_equity', 'operating_cash_flow',
                                           'raw_data', 'source'] if col in df.columns]

        df_insert = df[available_cols]

        self.conn.execute("CREATE TEMP TABLE staging_fundamentals AS SELECT * FROM df_insert")

        # Build dynamic upsert
        update_cols = [col for col in available_cols if col not in ['ticker', 'report_date', 'period_type']]
        if update_cols:
            update_set = ', '.join([f"{col} = EXCLUDED.{col}" for col in update_cols])
            update_query = f"""
                INSERT INTO fundamentals ({', '.join(available_cols)})
                SELECT {', '.join(available_cols)} FROM staging_fundamentals
                ON CONFLICT (ticker, report_date, period_type)
                DO UPDATE SET {update_set}
            """
        else:
            update_query = f"""
                INSERT INTO fundamentals ({', '.join(available_cols)})
                SELECT {', '.join(available_cols)} FROM staging_fundamentals
                ON CONFLICT (ticker, report_date, period_type) DO NOTHING
            """

        self.conn.execute(update_query)
        self.conn.execute("DROP TABLE staging_fundamentals")

    def migrate_macro_data(self):
        """Migrate macro data (VIX, SPY, economic indicators)."""
        logger.info("📉 Migrating macro data...")

        if not MACRO_DIR.exists():
            logger.warning(f"⚠️  Macro directory not found at {MACRO_DIR}")
            return

        macro_files = list(MACRO_DIR.glob("*.parquet"))
        logger.info(f"  Found {len(macro_files)} macro data files")

        all_dfs = []

        for macro_file in macro_files:
            try:
                symbol = macro_file.stem
                df_macro = pd.read_parquet(macro_file)

                # Check if index is date
                if df_macro.index.name == 'observation_date':
                    df_macro = df_macro.reset_index()

                # Rename observation_date to date if needed
                if 'observation_date' in df_macro.columns:
                    df_macro = df_macro.rename(columns={'observation_date': 'date'})

                # Reshape data to long format if needed
                if symbol in df_macro.columns:
                    df_long = pd.DataFrame({
                        'date': pd.to_datetime(df_macro['date']),
                        'symbol': symbol,
                        'close': df_macro[symbol] if symbol in df_macro.columns else None,
                    })
                else:
                    # Already in correct format
                    df_long = df_macro.copy()
                    if 'symbol' not in df_long.columns:
                        df_long['symbol'] = symbol

                # Ensure date column
                if 'date' not in df_long.columns and df_long.index.name:
                    df_long = df_long.reset_index()
                    df_long = df_long.rename(columns={df_long.columns[0]: 'date'})

                df_long['date'] = pd.to_datetime(df_long['date'])

                all_dfs.append(df_long)

            except Exception as e:
                logger.error(f"  ❌ Error processing {macro_file.name}: {e}")
                continue

        if not all_dfs:
            logger.warning("⚠️  No macro data to migrate")
            return

        # Combine all macro data
        df = pd.concat(all_dfs, ignore_index=True)
        df = df.sort_values(['date', 'symbol'])

        # Write to database
        # Select only columns that exist in the schema
        available_cols = ['date', 'symbol', 'close', 'volume', 'value', 'unit']
        df = df[[col for col in available_cols if col in df.columns]]

        # Ensure date is datetime
        if not pd.api.types.is_datetime64_any_dtype(df['date']):
            df['date'] = pd.to_datetime(df['date'])

        # Get columns available in both dataframe and target table
        available_cols = [col for col in ['date', 'symbol', 'close', 'volume', 'value', 'unit']
                          if col in df.columns]

        df_insert = df[available_cols]

        self.conn.execute("CREATE TEMP TABLE staging_macro AS SELECT * FROM df_insert")

        # Build dynamic upsert based on available columns
        update_cols = [col for col in available_cols if col not in ['date', 'symbol']]
        if update_cols:
            update_set = ', '.join([f"{col} = EXCLUDED.{col}" for col in update_cols])
            update_query = f"""
                INSERT INTO macro_data ({', '.join(available_cols)})
                SELECT {', '.join(available_cols)} FROM staging_macro
                ON CONFLICT (date, symbol)
                DO UPDATE SET {update_set}
            """
        else:
            update_query = f"""
                INSERT INTO macro_data ({', '.join(available_cols)})
                SELECT {', '.join(available_cols)} FROM staging_macro
                ON CONFLICT (date, symbol) DO NOTHING
            """

        self.conn.execute(update_query)
        self.conn.execute("DROP TABLE staging_macro")

        count = self.conn.execute("SELECT COUNT(*) FROM macro_data").fetchone()[0]
        logger.info(f"✅ Macro data migrated. Total rows: {count:,}")

    def compute_daily_features(self, start_date: Optional[str] = None):
        """
        Compute technical features from price data.

        This replaces the need to compute SMAs on-the-fly.
        """
        logger.info(f"🧮 Computing daily features (start_date={start_date})...")

        where_clause = ""
        if start_date:
            where_clause = f"WHERE date >= '{start_date}'"

        # Check if price data exists
        row_count = self.conn.execute("SELECT COUNT(*) FROM price_data").fetchone()[0]
        if row_count == 0:
            logger.warning("⚠️  No price data found. Skipping feature computation.")
            return

        # Compute features using SQL window functions
        logger.info("  Computing window functions (this may take a while)...")
        self.conn.execute(f"""
            INSERT INTO daily_features (
                ticker, date, sma_50, sma_200, ema_21, atr_14, vol_avg_50,
                rs_rating, rs_vs_spy, high_52w, low_52w, pct_from_high_52w,
                vol_ratio_50, feature_version
            )
            SELECT
                ticker,
                date,
                -- Moving averages
                AVG(close) OVER w20 as sma_20,
                AVG(close) OVER w50 as sma_50,
                AVG(close) OVER w200 as sma_200,
                CASE WHEN close > AVG(close) OVER w200 THEN TRUE ELSE FALSE END as close_above_sma200,

                NULL as ema_21,  -- TODO: Implement EMA
                
                -- Volatility
                NULL as atr_14,  -- TODO: Implement ATR
                AVG(volume) OVER w20 as vol_avg_20,
                AVG(volume) OVER w50 as vol_avg_50,

                -- Relative Strength (RS Line vs SPY)
                price_vs_spy,
                AVG(price_vs_spy) OVER w20 as price_vs_spy_ma20,
                AVG(price_vs_spy) OVER w50 as price_vs_spy_ma50,
                AVG(price_vs_spy) OVER w200 as price_vs_spy_ma200,
                CASE WHEN price_vs_spy > AVG(price_vs_spy) OVER w20 THEN TRUE ELSE FALSE END as rs_line_uptrend,
                LN(price_vs_spy) as rs_line_log,
                (price_vs_spy / LAG(price_vs_spy, 1) OVER ticker_date - 1) as rs_line_delta,
                LAG((price_vs_spy / LAG(price_vs_spy, 1) OVER ticker_date - 1), 1) OVER ticker_date as rs_line_lag_delta,

                -- 52-week metrics
                MAX(high) OVER w252 as high_52w,
                MIN(low) OVER w252 as low_52w,
                (close - MAX(high) OVER w252) / NULLIF(MAX(high) OVER w252, 0) as pct_from_high_52w,
                (close - MIN(low) OVER w252) / NULLIF(MIN(low) OVER w252, 0) as pct_above_low_52w,

                -- Volume ratio
                volume / NULLIF(AVG(volume) OVER w50, 0) as vol_ratio_50,
                AVG(volume) OVER w20 * close as dollar_volume_avg_20,

                -- Returns
                return_1d,
                return_5d,
                return_20d,
                return_60d,
                volatility_20d,

                -- Metadata
                'v2.0_phase1' as feature_version
            FROM price_features
            {where_clause}
            WINDOW
                w50 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW),
                w200 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW),
                w252 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW)
            ON CONFLICT (ticker, date)
            DO UPDATE SET
                sma_50 = EXCLUDED.sma_50,
                sma_200 = EXCLUDED.sma_200,
                vol_avg_50 = EXCLUDED.vol_avg_50,
                high_52w = EXCLUDED.high_52w,
                low_52w = EXCLUDED.low_52w,
                pct_from_high_52w = EXCLUDED.pct_from_high_52w,
                vol_ratio_50 = EXCLUDED.vol_ratio_50
        """)

        count = self.conn.execute("SELECT COUNT(*) FROM daily_features").fetchone()[0]
        logger.info(f"✅ Daily features computed. Total rows: {count:,}")

    def create_views(self):
        """Create analytical views."""
        logger.info("👁️  Creating views...")

        # SEPA candidates view
        self.conn.execute("""
            CREATE OR REPLACE VIEW v_sepa_candidates AS
            SELECT
                f.date,
                f.ticker,
                p.close,
                f.sma_50,
                f.sma_200,
                f.rs_rating,
                f.vol_avg_50,
                f.high_52w,
                f.pct_from_high_52w,
                c.sector,
                c.industry
            FROM daily_features f
            INNER JOIN price_data p
                ON f.ticker = p.ticker AND f.date = p.date
            INNER JOIN company_profiles c
                ON f.ticker = c.ticker
            WHERE
                p.close > f.sma_200
                AND f.sma_50 > f.sma_200
                AND f.pct_from_high_52w > -0.25
                AND c.is_active = TRUE
                AND f.vol_avg_50 > 500000
        """)

        logger.info("✅ Views created")


def main():
    parser = argparse.ArgumentParser(description="DuckDB Migration Script")
    parser.add_argument(
        '--mode',
        choices=['initial', 'daily'],
        required=True,
        help='Migration mode: initial (full) or daily (incremental)'
    )
    parser.add_argument(
        '--start-date',
        help='Start date for incremental migration (YYYY-MM-DD)'
    )
    args = parser.parse_args()

    # Ensure data directory exists
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with DuckDBMigrator(DB_PATH) as migrator:
        # Always initialize schema (idempotent)
        migrator.initialize_schema()

        if args.mode == 'initial':
            logger.info("🚀 Running INITIAL migration (full data)")
            migrator.migrate_company_profiles()
            migrator.migrate_macro_data()
            migrator.migrate_price_data()
            migrator.migrate_fundamentals()
            migrator.compute_daily_features()
            migrator.create_views()

        elif args.mode == 'daily':
            # Incremental: only migrate recent data
            start_date = args.start_date or (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
            logger.info(f"📅 Running DAILY migration (from {start_date})")
            migrator.migrate_company_profiles()  # Always update (upsert)
            migrator.migrate_macro_data()  # Always update (small dataset)
            migrator.migrate_price_data(start_date=start_date)
            migrator.compute_daily_features(start_date=start_date)

    logger.info("✅ Migration complete")


if __name__ == "__main__":
    main()
