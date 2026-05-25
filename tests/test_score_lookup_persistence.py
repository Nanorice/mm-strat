"""Tests for ScoreLookup.check_persistence (added for S5 hybrid strategy)."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from src.backtest.score_lookup import ScoreLookup


def _build_scores(rows):
    """rows = list of dicts with keys date, ticker, daily_pct_rank, trailing_pct."""
    df = pd.DataFrame(rows)
    df["normalized_score"] = 50.0
    df["prob_elite"] = df.get("prob_elite", 0.3)
    return df


def _trading_days(start: date, n: int):
    out = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def test_persistence_passes_when_consistently_above_threshold():
    days = _trading_days(date(2024, 1, 1), 10)
    rows = [
        {"date": d, "ticker": "AAPL", "daily_pct_rank": 0.85, "trailing_pct": 0.82}
        for d in days
    ]
    lookup = ScoreLookup(_build_scores(rows))
    # 10 days at 0.82 trailing >= 0.7 → 10 hits, min_count=3 satisfied.
    assert lookup.check_persistence("AAPL", days[-1],
                                    window_days=5, min_count=3, rank_threshold=0.7) is True


def test_persistence_fails_when_below_threshold():
    days = _trading_days(date(2024, 1, 1), 10)
    rows = [
        {"date": d, "ticker": "XYZ", "daily_pct_rank": 0.4, "trailing_pct": 0.4}
        for d in days
    ]
    lookup = ScoreLookup(_build_scores(rows))
    assert lookup.check_persistence("XYZ", days[-1],
                                    window_days=5, min_count=3, rank_threshold=0.7) is False


def test_persistence_partial_hits_pass_when_min_count_met():
    days = _trading_days(date(2024, 1, 1), 5)
    # Pattern: high, low, high, low, high  → 3 hits in last 5 days.
    ranks = [0.9, 0.3, 0.85, 0.2, 0.95]
    rows = [
        {"date": d, "ticker": "MIX", "daily_pct_rank": r, "trailing_pct": r}
        for d, r in zip(days, ranks)
    ]
    lookup = ScoreLookup(_build_scores(rows))
    assert lookup.check_persistence("MIX", days[-1],
                                    window_days=5, min_count=3, rank_threshold=0.7) is True
    assert lookup.check_persistence("MIX", days[-1],
                                    window_days=5, min_count=4, rank_threshold=0.7) is False


def test_persistence_uses_trailing_field_by_default():
    days = _trading_days(date(2024, 1, 1), 5)
    rows = [
        {"date": d, "ticker": "T", "daily_pct_rank": 0.95, "trailing_pct": 0.1}
        for d in days
    ]
    lookup = ScoreLookup(_build_scores(rows))
    assert lookup.check_persistence("T", days[-1],
                                    window_days=5, min_count=3, rank_threshold=0.5,
                                    rank_field='trailing') is False
    assert lookup.check_persistence("T", days[-1],
                                    window_days=5, min_count=3, rank_threshold=0.5,
                                    rank_field='daily') is True


def test_persistence_skips_calendar_gaps():
    # If ticker is missing on some days inside the window, only indexed obs count.
    days = _trading_days(date(2024, 1, 1), 10)
    # AAPL on 5 days only, but each of those 5 is above threshold.
    rows = [
        {"date": d, "ticker": "AAPL", "daily_pct_rank": 0.9, "trailing_pct": 0.9}
        for d in days[::2]
    ]
    # ANCHOR ticker on all days to make sure ScoreLookup indexes the full date span.
    rows += [
        {"date": d, "ticker": "ANCHOR", "daily_pct_rank": 0.5, "trailing_pct": 0.5}
        for d in days
    ]
    lookup = ScoreLookup(_build_scores(rows))
    # Window of 10 trading days: AAPL has 5 indexed obs, all hits → pass min_count=3.
    assert lookup.check_persistence("AAPL", days[-1],
                                    window_days=10, min_count=3, rank_threshold=0.7) is True
    # min_count=6 fails because only 5 obs available.
    assert lookup.check_persistence("AAPL", days[-1],
                                    window_days=10, min_count=6, rank_threshold=0.7) is False


def test_persistence_returns_false_for_unknown_ticker():
    days = _trading_days(date(2024, 1, 1), 5)
    rows = [
        {"date": d, "ticker": "AAA", "daily_pct_rank": 0.9, "trailing_pct": 0.9}
        for d in days
    ]
    lookup = ScoreLookup(_build_scores(rows))
    assert lookup.check_persistence("UNKNOWN", days[-1],
                                    window_days=5, min_count=1, rank_threshold=0.5) is False
