"""
Shared utility functions for the quantamental trading system.
"""
import pandas as pd
import pytz
from datetime import datetime, time
from pathlib import Path
from typing import List, Set
import logging

logger = logging.getLogger(__name__)


def get_latest_trading_day() -> pd.Timestamp:
    """
    Get the most recent completed trading day, accounting for market holidays.

    Logic:
    - If current time is before 4:00 PM ET: use previous trading day
    - If current time is after 4:00 PM ET: use today (if market is open)
    - Uses NYSE calendar to skip weekends and market holidays

    Returns:
        Timestamp of the most recent completed trading day
    """
    try:
        import pandas_market_calendars as mcal

        # Get NYSE calendar
        nyse = mcal.get_calendar('NYSE')

        # Get current time in US/Eastern
        et_tz = pytz.timezone('US/Eastern')
        now_et = datetime.now(et_tz)
        market_close_time = time(16, 0)  # 4:00 PM ET

        # Determine candidate date
        if now_et.time() < market_close_time:
            # Market hasn't closed yet, use previous trading day
            candidate_date = now_et.date() - pd.Timedelta(days=1)
        else:
            # Market has closed, use today
            candidate_date = now_et.date()

        # Get valid trading days up to candidate date
        # Look back 10 days to ensure we catch the last trading day
        start_date = candidate_date - pd.Timedelta(days=10)
        schedule = nyse.schedule(start_date=start_date, end_date=candidate_date)

        if schedule.empty:
            # Fallback if calendar fails
            raise ValueError("No trading days found in schedule")

        # Get the most recent trading day
        latest_trading_day = schedule.index[-1].date()
        return pd.Timestamp(latest_trading_day)

    except (ImportError, Exception) as e:
        # Fallback to simple logic if pandas_market_calendars not available
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"pandas_market_calendars not available ({e}), using simple weekend-only logic")

        et_tz = pytz.timezone('US/Eastern')
        now_et = datetime.now(et_tz)
        market_close_time = time(16, 0)

        if now_et.time() < market_close_time:
            current_date = now_et.date() - pd.Timedelta(days=1)
        else:
            current_date = now_et.date()

        latest_date = pd.Timestamp(current_date)

        # Skip weekends only
        while latest_date.dayofweek >= 5:
            latest_date -= pd.Timedelta(days=1)

        return latest_date


def load_etf_exclusion_list(filepath: str = 'data/etf_fund_tickers.txt') -> Set[str]:
    """
    Load ETF/Fund exclusion list from file.

    Args:
        filepath: Path to ETF/fund ticker list file

    Returns:
        Set of ticker symbols to exclude from processing
    """
    filepath = Path(filepath)

    if not filepath.exists():
        logger.warning(f"ETF/Fund exclusion list not found: {filepath}")
        logger.warning(f"Run 'python identify_etfs.py' to generate it")
        return set()

    etf_fund_tickers = set()

    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if line.startswith('#') or not line:
                continue
            # Extract ticker (before tab or comment)
            ticker = line.split()[0]  # First word is the ticker
            etf_fund_tickers.add(ticker)

    logger.info(f"Loaded {len(etf_fund_tickers)} ETF/fund tickers to exclude")

    return etf_fund_tickers


def filter_etfs(tickers: List[str], etf_list_path: str = 'data/etf_fund_tickers.txt',
                filter_spacs: bool = True) -> List[str]:
    """
    Filter out ETFs, funds, SPACs, and other non-operating companies from ticker list.

    Args:
        tickers: List of ticker symbols
        etf_list_path: Path to ETF/fund exclusion list
        filter_spacs: If True, also filter SPACs and shell companies (default: True)

    Returns:
        Filtered list of tickers (operating companies only)
    """
    # Step 1: Filter using ETF exclusion list
    etf_exclusion = load_etf_exclusion_list(etf_list_path)

    if not etf_exclusion:
        logger.warning("No ETF exclusion list loaded, skipping ETF/fund filtering")
        etf_filtered = tickers
    else:
        etf_filtered = [t for t in tickers if t not in etf_exclusion]
        etf_excluded = len(tickers) - len(etf_filtered)
        logger.info(f"ETF/Fund filtering: {len(tickers)} → {len(etf_filtered)} tickers ({etf_excluded} excluded)")

    # Step 2: Filter SPACs, shell companies, units, warrants
    # Only check suspicious tickers (ending with U/W/R or containing 'acqu') to save time
    if not filter_spacs:
        return etf_filtered

    try:
        from src.company_profile_engine import CompanyProfileEngine
        profile_engine = CompanyProfileEngine()

        spac_excluded = []
        final_filtered = []
        suspicious_count = 0

        for ticker in etf_filtered:
            should_exclude = False

            # Quick check: only load profile for suspicious tickers
            ticker_lower = ticker.lower()
            is_suspicious = (
                (ticker.endswith(('U', 'W', 'R')) and len(ticker) > 2) or
                ('acquisition' in ticker_lower) or
                ('acqu' in ticker_lower) or
                ('mesh' in ticker_lower and 'acquisition' in ticker_lower) or  # Catches MESHU
                (ticker_lower.startswith('sv') and ticker_lower.endswith('u'))  # SVxxU pattern
            )

            if is_suspicious:
                suspicious_count += 1
                profile = profile_engine.get_ticker_profile(ticker)
                if profile is not None:
                    industry = str(profile.get('industry', '')).lower()
                    company_name = str(profile.get('companyName', '')).lower()

                    # Check for units, warrants, rights
                    if any(kw in company_name for kw in ['units', 'unit', 'warrant', 'rights']):
                        should_exclude = True
                    # Check for SPACs and shell companies (in industry OR company name)
                    elif 'acquisition' in industry or 'shell' in industry or 'acquisition corp' in company_name:
                        should_exclude = True

            if should_exclude:
                spac_excluded.append(ticker)
            else:
                final_filtered.append(ticker)

        if spac_excluded:
            logger.info(f"SPAC/Shell filtering: Checked {suspicious_count} suspicious tickers, excluded {len(spac_excluded)} (Final: {len(final_filtered)} tickers)")

        return final_filtered

    except Exception as e:
        logger.warning(f"SPAC filtering failed: {e}, skipping")
        return etf_filtered


def get_model_features(model_name: str = 'M01', db_path: str = 'data/market_data.duckdb') -> List[str]:
    """Return the feature list for a model from the model_feature_sets table.

    Queries the prod model version for model_name and returns its registered features
    in ordinal order.

    Args:
        model_name: Prefix to match against version_id (e.g., 'M01' matches 'M01_baseline_v0.1').
        db_path: Path to DuckDB database.

    Returns:
        Ordered list of feature names.

    Raises:
        RuntimeError: If model_feature_sets table is empty or no prod model found.
    """
    import duckdb as _duckdb

    con = _duckdb.connect(db_path)
    try:
        result = con.execute(
            """
            SELECT feature_set_id FROM models
            WHERE status_flag = 'prod' AND version_id LIKE ?
            ORDER BY created_at DESC LIMIT 1
            """,
            [f"{model_name}%"],
        ).fetchone()

        if not result:
            raise RuntimeError(
                f"No prod model found for '{model_name}'. "
                "Run scripts/populate_feature_catalog.py first."
            )

        feature_set_id = result[0]
        if not feature_set_id:
            raise RuntimeError(
                f"Prod model for '{model_name}' has no feature_set_id. "
                "Run scripts/populate_feature_catalog.py first."
            )

        rows = con.execute(
            """
            SELECT feature_name FROM model_feature_sets
            WHERE feature_set_id = ?
            ORDER BY ordinal
            """,
            [feature_set_id],
        ).fetchall()

        if not rows:
            raise RuntimeError(
                f"model_feature_sets is empty for feature_set_id='{feature_set_id}'. "
                "Run scripts/populate_feature_catalog.py first."
            )

        return [r[0] for r in rows]
    finally:
        con.close()
