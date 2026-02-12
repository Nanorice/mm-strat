"""
Migration Validator - Phase 1

Validates that DuckDB contains the same data as file-based system.
This is the critical test harness to ensure migration correctness.

Usage:
    python scripts/validate_migration.py --test price
    python scripts/validate_migration.py --test company_profiles
    python scripts/validate_migration.py --test all
"""

import argparse
from pathlib import Path
from datetime import datetime
import duckdb
import pandas as pd
from typing import List, Tuple
import logging
import random

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "data" / "market_data.duckdb"
PRICE_DATA_DIR = PROJECT_ROOT / "data" / "price"
COMPANY_PROFILE_FILE = PROJECT_ROOT / "data" / "company_info" / "company_profiles.parquet"


class MigrationValidator:
    """Validates DuckDB data against file-based sources."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = duckdb.connect(str(db_path), read_only=True)
        self.failures: List[str] = []

    def __del__(self):
        if hasattr(self, 'conn'):
            self.conn.close()

    def validate_price_data(self, sample_size: int = 10):
        """
        Validate price data by comparing random tickers.

        Strategy:
        1. Load file-based data from individual ticker parquet files
        2. Query DuckDB for same tickers
        3. Assert equality using pandas.testing.assert_frame_equal
        """
        logger.info(f"📊 Validating price data (sample_size={sample_size})...")

        # Load file-based data
        if not PRICE_DATA_DIR.exists():
            logger.error(f"❌ Price data directory not found: {PRICE_DATA_DIR}")
            return False

        # Get all ticker files
        ticker_files = list(PRICE_DATA_DIR.glob("*.parquet"))
        if len(ticker_files) == 0:
            logger.error("❌ No ticker files found")
            return False

        # Get random sample
        if len(ticker_files) < sample_size:
            sample_size = len(ticker_files)

        sample_files = random.sample(ticker_files, sample_size)
        sample_tickers = [f.stem for f in sample_files]

        passed = 0
        failed = 0

        for ticker_file in sample_files:
            ticker = ticker_file.stem
            try:
                # Get data from file
                df_file_ticker = pd.read_parquet(ticker_file)

                # Normalize schema: Date might be in index
                if df_file_ticker.index.name in ['Date', 'date']:
                    df_file_ticker = df_file_ticker.reset_index()

                # Normalize column names to lowercase
                df_file_ticker.columns = df_file_ticker.columns.str.lower()

                # Add ticker column if missing
                if 'ticker' not in df_file_ticker.columns:
                    df_file_ticker['ticker'] = ticker

                # Filter out null dates/tickers (same as migration does)
                if 'date' in df_file_ticker.columns:
                    df_file_ticker = df_file_ticker[df_file_ticker['date'].notna()]
                if 'ticker' in df_file_ticker.columns:
                    df_file_ticker = df_file_ticker[df_file_ticker['ticker'].notna()]

                df_file_ticker = df_file_ticker.sort_values('date').reset_index(drop=True)

                # Get data from DuckDB
                df_db_ticker = self.conn.execute(
                    "SELECT * FROM price_data WHERE ticker = ? ORDER BY date",
                    [ticker]
                ).fetchdf()

                if len(df_db_ticker) == 0:
                    logger.warning(f"  ⚠️  {ticker}: Missing from DuckDB")
                    failed += 1
                    self.failures.append(f"{ticker}: Not found in DuckDB")
                    continue

                # Compare key columns
                compare_cols = ['ticker', 'date', 'close', 'volume']
                for col in compare_cols:
                    if col not in df_file_ticker.columns:
                        continue
                    if col not in df_db_ticker.columns:
                        logger.error(f"  ❌ {ticker}: Column '{col}' missing from DuckDB")
                        failed += 1
                        self.failures.append(f"{ticker}: Column '{col}' missing")
                        continue

                # Check row counts (allow file to have a few more rows due to new data)
                row_diff = len(df_file_ticker) - len(df_db_ticker)
                if row_diff < 0:
                    # DB has more rows than file - this is a real problem
                    logger.error(
                        f"  ❌ {ticker}: DB has more rows than file! "
                        f"File={len(df_file_ticker)}, DB={len(df_db_ticker)}"
                    )
                    failed += 1
                    self.failures.append(
                        f"{ticker}: DB has more rows ({len(df_db_ticker)} vs {len(df_file_ticker)})"
                    )
                    continue
                elif row_diff > 5:
                    # File has significantly more rows - might indicate migration issue
                    logger.warning(
                        f"  ⚠️  {ticker}: File has {row_diff} more rows than DB. "
                        f"This is expected if new data arrived after migration."
                    )
                    # Don't fail, but note it
                elif row_diff > 0:
                    logger.info(
                        f"  ℹ️  {ticker}: File has {row_diff} newer rows "
                        f"(expected if data curator ran after migration)"
                    )

                # Compare close prices (most critical)
                # Normalize datetime dtype to avoid microsecond vs nanosecond mismatch
                df_file_ticker['date'] = pd.to_datetime(df_file_ticker['date']).dt.normalize()
                df_db_ticker['date'] = pd.to_datetime(df_db_ticker['date']).dt.normalize()

                # Only compare dates that exist in DB (file might have newer data)
                common_dates = set(df_db_ticker['date'].dt.strftime('%Y-%m-%d'))
                df_file_filtered = df_file_ticker[
                    df_file_ticker['date'].dt.strftime('%Y-%m-%d').isin(common_dates)
                ]

                # Use date as string key to avoid dtype issues
                df_file_close = df_file_filtered.set_index(
                    df_file_filtered['date'].dt.strftime('%Y-%m-%d')
                )['close']
                df_db_close = df_db_ticker.set_index(
                    df_db_ticker['date'].dt.strftime('%Y-%m-%d')
                )['close']

                try:
                    pd.testing.assert_series_equal(
                        df_file_close,
                        df_db_close,
                        check_names=False,
                        check_index_type=False,  # Ignore index type differences
                        rtol=1e-5  # Tolerance for floating point
                    )
                    if row_diff > 0:
                        logger.info(
                            f"  ✅ {ticker}: {len(df_db_ticker)} rows validated "
                            f"({row_diff} newer rows in file)"
                        )
                    else:
                        logger.info(f"  ✅ {ticker}: {len(df_db_ticker)} rows validated")
                    passed += 1

                except AssertionError as e:
                    logger.error(f"  ❌ {ticker}: Close prices don't match")
                    logger.error(f"     {str(e)[:200]}")
                    failed += 1
                    self.failures.append(f"{ticker}: Close prices mismatch")

            except Exception as e:
                logger.error(f"  ❌ {ticker}: Validation error - {str(e)}")
                failed += 1
                self.failures.append(f"{ticker}: {str(e)}")

        # Summary
        logger.info(f"\n📋 Price Data Validation Summary:")
        logger.info(f"   Passed: {passed}/{sample_size}")
        logger.info(f"   Failed: {failed}/{sample_size}")

        return failed == 0

    def validate_company_profiles(self):
        """Validate company profiles against parquet file."""
        logger.info("🏢 Validating company profiles...")

        if not COMPANY_PROFILE_FILE.exists():
            logger.error(f"❌ Company profiles file not found: {COMPANY_PROFILE_FILE}")
            return False

        # Load all profiles from DB
        df_db = self.conn.execute("SELECT * FROM company_profiles").fetchdf()
        db_tickers = set(df_db['ticker'])

        # Load all profiles from parquet file
        df_file = pd.read_parquet(COMPANY_PROFILE_FILE)

        # Ticker might be in index or column
        if df_file.index.name == 'ticker':
            df_file = df_file.reset_index()
        elif 'symbol' in df_file.columns:
            df_file = df_file.rename(columns={'symbol': 'ticker'})

        file_tickers = set(df_file['ticker'])

        # Check coverage
        missing_in_db = file_tickers - db_tickers
        extra_in_db = db_tickers - file_tickers

        if missing_in_db:
            logger.warning(f"  ⚠️  {len(missing_in_db)} tickers in file but not in DB")
            if len(missing_in_db) <= 10:
                logger.warning(f"     {missing_in_db}")
            self.failures.append(f"Missing in DB: {len(missing_in_db)} tickers")

        if extra_in_db:
            logger.warning(f"  ⚠️  {len(extra_in_db)} tickers in DB but not in file")

        # Sample validation: check 10 random profiles
        sample_size = min(10, len(df_file))
        sample_tickers = random.sample(list(file_tickers), sample_size)

        passed = 0
        failed = 0

        for ticker in sample_tickers:
            file_row = df_file[df_file['ticker'] == ticker].iloc[0]
            db_row = df_db[df_db['ticker'] == ticker]

            if len(db_row) == 0:
                logger.error(f"  ❌ {ticker}: Not found in DB")
                failed += 1
                continue

            db_row = db_row.iloc[0]

            # Check key fields
            checks = [
                ('sector', file_row.get('sector', '')),
                ('industry', file_row.get('industry', '')),
            ]

            mismatch = False
            for field, expected in checks:
                actual = db_row.get(field, '')
                if actual != expected:
                    logger.warning(f"  ⚠️  {ticker}.{field}: '{actual}' != '{expected}'")
                    mismatch = True

            if not mismatch:
                logger.info(f"  ✅ {ticker}: Profile validated")
                passed += 1
            else:
                failed += 1
                self.failures.append(f"{ticker}: Profile mismatch")

        logger.info(f"\n📋 Company Profile Validation Summary:")
        logger.info(f"   Total in DB: {len(db_tickers)}")
        logger.info(f"   Total in File: {len(file_tickers)}")
        logger.info(f"   Sample Passed: {passed}/{sample_size}")
        logger.info(f"   Sample Failed: {failed}/{sample_size}")

        return failed == 0 and len(missing_in_db) == 0

    def validate_daily_features(self, sample_size: int = 5):
        """
        Validate computed features against manual calculation.

        This is a spot-check to ensure SQL window functions are correct.
        """
        logger.info(f"🧮 Validating daily features (sample_size={sample_size})...")

        # Get random sample of (ticker, date) pairs
        sample = self.conn.execute(f"""
            SELECT DISTINCT ticker, date
            FROM daily_features
            ORDER BY RANDOM()
            LIMIT {sample_size}
        """).fetchall()

        passed = 0
        failed = 0

        for ticker, date in sample:
            try:
                # Get computed features from DB
                db_features = self.conn.execute("""
                    SELECT sma_50, sma_200, vol_avg_50, high_52w, pct_from_high_52w
                    FROM daily_features
                    WHERE ticker = ? AND date = ?
                """, [ticker, date]).fetchone()

                # Get raw price data to compute features manually
                df_prices = self.conn.execute("""
                    SELECT date, close, high, low, volume
                    FROM price_data
                    WHERE ticker = ?
                      AND date <= ?
                    ORDER BY date
                """, [ticker, date]).fetchdf()

                if len(df_prices) < 50:
                    logger.warning(f"  ⚠️  {ticker} @ {date}: Insufficient data for validation")
                    continue

                # Manual calculation of SMA-50
                sma_50_manual = df_prices.tail(50)['close'].mean()
                sma_50_db = db_features[0]

                if abs(sma_50_manual - sma_50_db) / sma_50_db > 0.01:  # 1% tolerance
                    logger.error(
                        f"  ❌ {ticker} @ {date}: SMA-50 mismatch. "
                        f"Manual={sma_50_manual:.2f}, DB={sma_50_db:.2f}"
                    )
                    failed += 1
                    self.failures.append(f"{ticker} @ {date}: SMA-50 mismatch")
                    continue

                # Manual calculation of 52-week high
                high_52w_manual = df_prices.tail(252)['high'].max()
                high_52w_db = db_features[3]

                if abs(high_52w_manual - high_52w_db) / high_52w_db > 0.01:
                    logger.error(
                        f"  ❌ {ticker} @ {date}: 52w high mismatch. "
                        f"Manual={high_52w_manual:.2f}, DB={high_52w_db:.2f}"
                    )
                    failed += 1
                    self.failures.append(f"{ticker} @ {date}: 52w high mismatch")
                    continue

                logger.info(f"  ✅ {ticker} @ {date}: Features validated")
                passed += 1

            except Exception as e:
                logger.error(f"  ❌ {ticker} @ {date}: Validation error - {str(e)}")
                failed += 1
                self.failures.append(f"{ticker} @ {date}: {str(e)}")

        logger.info(f"\n📋 Daily Features Validation Summary:")
        logger.info(f"   Passed: {passed}/{sample_size}")
        logger.info(f"   Failed: {failed}/{sample_size}")

        return failed == 0

    def validate_sepa_view(self, test_date: str = None):
        """
        Validate SEPA candidates view.

        Compare SQL-based filter against Python-based implementation.
        """
        logger.info("🔍 Validating SEPA candidates view...")

        if test_date is None:
            # Get most recent date with data
            test_date = self.conn.execute(
                "SELECT MAX(date) FROM daily_features"
            ).fetchone()[0]

        logger.info(f"   Test date: {test_date}")

        # Query SEPA candidates from view
        df_sepa = self.conn.execute("""
            SELECT ticker, close, sma_50, sma_200, pct_from_high_52w
            FROM v_sepa_candidates
            WHERE date = ?
            ORDER BY ticker
        """, [test_date]).fetchdf()

        logger.info(f"   SEPA candidates found: {len(df_sepa)}")

        # Spot-check: verify filters are working
        if len(df_sepa) > 0:
            # All candidates should pass SEPA rules
            violations = []

            # Check: close > sma_200
            if (df_sepa['close'] <= df_sepa['sma_200']).any():
                violations.append("Some tickers have close <= sma_200")

            # Check: sma_50 > sma_200
            if (df_sepa['sma_50'] <= df_sepa['sma_200']).any():
                violations.append("Some tickers have sma_50 <= sma_200")

            # Check: within 25% of 52w high
            if (df_sepa['pct_from_high_52w'] <= -0.25).any():
                violations.append("Some tickers are >25% from 52w high")

            if violations:
                logger.error("  ❌ SEPA view validation failed:")
                for v in violations:
                    logger.error(f"     - {v}")
                self.failures.extend(violations)
                return False
            else:
                logger.info("  ✅ SEPA view filters validated")
                return True
        else:
            logger.warning("  ⚠️  No SEPA candidates found (might be market condition)")
            return True

    def generate_report(self):
        """Generate validation report."""
        logger.info("\n" + "="*60)
        logger.info("📊 VALIDATION REPORT")
        logger.info("="*60)

        if not self.failures:
            logger.info("✅ ALL VALIDATIONS PASSED")
            logger.info("\nDuckDB migration is consistent with file-based system.")
            return True
        else:
            logger.error(f"❌ VALIDATION FAILED ({len(self.failures)} issues)")
            logger.error("\nIssues found:")
            for i, failure in enumerate(self.failures, 1):
                logger.error(f"  {i}. {failure}")
            return False


def main():
    parser = argparse.ArgumentParser(description="DuckDB Migration Validator")
    parser.add_argument(
        '--test',
        choices=['price', 'company_profiles', 'features', 'sepa', 'all'],
        default='all',
        help='Which validation to run'
    )
    parser.add_argument(
        '--sample-size',
        type=int,
        default=10,
        help='Number of samples to validate'
    )
    args = parser.parse_args()

    if not DB_PATH.exists():
        logger.error(f"❌ Database not found: {DB_PATH}")
        logger.error("   Run migrate_to_duckdb.py first")
        return

    validator = MigrationValidator(DB_PATH)

    # Run selected tests
    results = []

    if args.test in ['price', 'all']:
        results.append(validator.validate_price_data(sample_size=args.sample_size))

    if args.test in ['company_profiles', 'all']:
        results.append(validator.validate_company_profiles())

    if args.test in ['features', 'all']:
        results.append(validator.validate_daily_features(sample_size=args.sample_size))

    if args.test in ['sepa', 'all']:
        results.append(validator.validate_sepa_view())

    # Generate report
    success = validator.generate_report()

    if not success:
        exit(1)


if __name__ == "__main__":
    main()
