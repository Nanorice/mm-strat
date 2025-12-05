"""
Shared utility functions for the quantamental trading system.
"""
import pandas as pd
import pytz
from datetime import datetime, time


def get_latest_trading_day() -> pd.Timestamp:
    """
    Get the most recent completed trading day.

    Logic:
    - If current time is before 4:00 PM ET: use previous trading day
    - If current time is after 4:00 PM ET: use today (if it's a weekday)
    - Skip weekends automatically (Saturday -> Friday, Sunday -> Friday)

    Note: This does NOT account for market holidays (e.g., Thanksgiving, Christmas).
    For production use, consider integrating pandas_market_calendars.

    Returns:
        Timestamp of the most recent trading day
    """
    # Get current time in US/Eastern
    et_tz = pytz.timezone('US/Eastern')
    now_et = datetime.now(et_tz)
    market_close_time = time(16, 0)  # 4:00 PM ET

    # If before market close, use previous day
    if now_et.time() < market_close_time:
        current_date = now_et.date() - pd.Timedelta(days=1)
    else:
        current_date = now_et.date()

    # Convert to pandas Timestamp
    latest_date = pd.Timestamp(current_date)

    # If weekend, go back to Friday
    while latest_date.dayofweek >= 5:  # 5=Saturday, 6=Sunday
        latest_date -= pd.Timedelta(days=1)

    return latest_date
