"""
Shared utility functions for the quantamental trading system.
"""
import pandas as pd
import pytz
from datetime import datetime, time


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
