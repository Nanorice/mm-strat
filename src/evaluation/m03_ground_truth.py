"""
M03 Ground Truth Data
=====================

Contains historical regime classifications for validating M03 regime calculator.
Data sourced from multiple financial research providers and hand-labeled based on
major market events.
"""

import pandas as pd
from datetime import datetime
from typing import List, Dict


# Ground truth regime periods from M03_evaluation_system.md
# Each period defines the consensus market regime based on historical analysis
GROUND_TRUTH_PERIODS: List[Dict] = [
    {"start_date": "2001-01-01", "end_date": "2002-10-09", "regime": "BEAR", "rationale": "Dot-Com Bust. Nasdaq -78%. S&P broke trend. Liquidity dried."},
    {"start_date": "2002-10-10", "end_date": "2007-10-09", "regime": "BULL", "rationale": "Housing Boom. Low rates. Strong Trend."},
    {"start_date": "2007-10-10", "end_date": "2009-03-09", "regime": "STRONG_BEAR", "rationale": "GFC. Subprime Crisis. Trend broken. Credit Spreads exploded."},
    {"start_date": "2009-03-10", "end_date": "2010-04-23", "regime": "BULL", "rationale": "Post-Crisis Recovery. QE1. Trend > 200 SMA."},
    {"start_date": "2010-04-24", "end_date": "2010-08-31", "regime": "NEUTRAL", "rationale": "Flash Crash (May 2010). Euro Crisis I. Choppy."},
    {"start_date": "2010-09-01", "end_date": "2011-07-31", "regime": "BULL", "rationale": "QE2 Rally."},
    {"start_date": "2011-08-01", "end_date": "2011-10-04", "regime": "BEAR", "rationale": "US Debt Downgrade. VIX Spike > 40. Trend broken."},
    {"start_date": "2011-10-05", "end_date": "2015-05-19", "regime": "BULL", "rationale": "Slow Grind Up. QE3."},
    {"start_date": "2015-05-20", "end_date": "2016-02-11", "regime": "NEUTRAL", "rationale": "China Devaluation / Oil Crash. Trend flat/broken."},
    {"start_date": "2016-02-12", "end_date": "2018-01-26", "regime": "STRONG_BULL", "rationale": "Trump Rally / Global Growth. Extremely low Vol."},
    {"start_date": "2018-01-27", "end_date": "2018-03-31", "regime": "NEUTRAL", "rationale": "Volmageddon (VIX ETN blowup)."},
    {"start_date": "2018-04-01", "end_date": "2018-09-20", "regime": "BULL", "rationale": "Recovery."},
    {"start_date": "2018-09-21", "end_date": "2018-12-24", "regime": "BEAR", "rationale": "Fed Tightening (Auto-pilot). Liquidity Drain."},
    {"start_date": "2018-12-26", "end_date": "2020-02-19", "regime": "BULL", "rationale": "Powell Pivot. 2019 Rally."},
    {"start_date": "2020-02-20", "end_date": "2020-03-23", "regime": "STRONG_BEAR", "rationale": "COVID Crash. Speed test (1 month drop)."},
    {"start_date": "2020-03-24", "end_date": "2021-12-31", "regime": "STRONG_BULL", "rationale": "Fed Stimulus. Tech Boom."},
    {"start_date": "2022-01-03", "end_date": "2022-10-12", "regime": "BEAR", "rationale": "Inflation / Rate Hikes. Tech Crash."},
    {"start_date": "2022-10-13", "end_date": "2023-02-28", "regime": "NEUTRAL", "rationale": "Bottoming Process."},
    {"start_date": "2023-03-01", "end_date": "2023-03-31", "regime": "BEAR", "rationale": "SVB Regional Bank Crisis. VIX Spike."},
    {"start_date": "2023-04-01", "end_date": "2023-07-31", "regime": "BULL", "rationale": "AI Rally (Nvidia)."},
    {"start_date": "2023-08-01", "end_date": "2023-10-27", "regime": "NEUTRAL", "rationale": "Higher for Longer (Yields > 5%)."},
    {"start_date": "2023-10-30", "end_date": "2024-03-31", "regime": "STRONG_BULL", "rationale": "Fed Pivot Rally."},
    {"start_date": "2024-04-01", "end_date": "2024-04-30", "regime": "NEUTRAL", "rationale": "Inflation Scare pullback."},
    {"start_date": "2024-05-01", "end_date": "2024-07-15", "regime": "BULL", "rationale": "Summer Rally."},
    {"start_date": "2024-07-16", "end_date": "2024-08-15", "regime": "BEAR", "rationale": "Yen Carry Trade Crash (VIX > 65)."},
    {"start_date": "2024-08-16", "end_date": "2025-12-31", "regime": "BULL", "rationale": "Election & Post-Election Rally. US Outperformance."},
    {"start_date": "2026-01-01", "end_date": "2026-01-31", "regime": "NEUTRAL", "rationale": "Current Evaluation Period."},
]


# Critical crash periods that require fast detection (< 7 days)
CRITICAL_CRASH_PERIODS = [
    {
        "name": "COVID Crash",
        "start_date": "2020-02-20",
        "max_lag_days": 7,  # Must detect by Feb 27
        "description": "Fastest crash in history - 1 month drop"
    },
    {
        "name": "Yen Carry Trade",
        "start_date": "2024-07-16",
        "max_lag_days": 7,  # Must detect by ~Aug 7 (accounting for weekends)
        "description": "VIX spiked to 65"
    },
    {
        "name": "GFC Bear Market Start",
        "start_date": "2007-10-10",
        "max_lag_days": 14,  # Slower developing crisis
        "description": "Subprime crisis beginning"
    },
]


def load_ground_truth_df(
    start_date: str = None,
    end_date: str = None,
    freq: str = 'D'
) -> pd.DataFrame:
    """
    Expand ground truth periods into a daily DataFrame.
    
    Args:
        start_date: Start date filter (YYYY-MM-DD)
        end_date: End date filter (YYYY-MM-DD)
        freq: Frequency - 'D' for daily, 'B' for business days
    
    Returns:
        DataFrame with columns:
        - date (index): DatetimeIndex
        - ground_truth_regime: str ('STRONG_BEAR', 'BEAR', 'NEUTRAL', 'BULL', 'STRONG_BULL')
        - rationale: str
    """
    rows = []
    
    for period in GROUND_TRUTH_PERIODS:
        period_start = pd.to_datetime(period['start_date'])
        period_end = pd.to_datetime(period['end_date'])
        
        # Generate all dates in the period
        dates = pd.date_range(start=period_start, end=period_end, freq=freq)
        
        for date in dates:
            rows.append({
                'date': date,
                'ground_truth_regime': period['regime'],
                'rationale': period['rationale']
            })
    
    df = pd.DataFrame(rows)
    df = df.set_index('date').sort_index()
    
    # Remove duplicates (periods might overlap on boundary dates)
    df = df[~df.index.duplicated(keep='last')]
    
    # Apply date filters
    if start_date:
        df = df[df.index >= pd.to_datetime(start_date)]
    if end_date:
        df = df[df.index <= pd.to_datetime(end_date)]
    
    return df


def get_strong_bear_periods() -> List[Dict]:
    """Get all STRONG_BEAR periods for crash capture analysis."""
    return [p for p in GROUND_TRUTH_PERIODS if p['regime'] == 'STRONG_BEAR']


def get_strong_bull_periods() -> List[Dict]:
    """Get all STRONG_BULL periods for false alarm analysis."""
    return [p for p in GROUND_TRUTH_PERIODS if p['regime'] == 'STRONG_BULL']


def get_regime_ordinal(regime: str) -> int:
    """
    Convert regime string to ordinal value for analysis.
    
    0 = STRONG_BEAR (worst)
    4 = STRONG_BULL (best)
    """
    mapping = {
        'STRONG_BEAR': 0,
        'BEAR': 1,
        'NEUTRAL': 2,
        'BULL': 3,
        'STRONG_BULL': 4
    }
    return mapping.get(regime.upper(), 2)  # Default to NEUTRAL


def get_critical_crash_info(crash_name: str) -> Dict:
    """Get info for a specific critical crash period."""
    for crash in CRITICAL_CRASH_PERIODS:
        if crash['name'].lower() == crash_name.lower():
            return crash
    return None
