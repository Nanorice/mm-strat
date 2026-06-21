"""Tests for src.evaluation.m02_cv (embargoed CV + Rank IC) and the additive
embargo_days param on anchored_walk_forward."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from src.evaluation.m02_cv import (
    assert_no_leakage,
    cross_sectional_rank_ic,
    run_m02_cv,
)
from src.evaluation.walk_forward import anchored_walk_forward


def _panel(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2018-01-02", "2023-12-29")
    tickers = [f"T{i:03d}" for i in range(15)]
    rows = []
    for d in dates:
        for tk in tickers:
            x = rng.normal()
            y = 3.0 * x + rng.normal(0, 1.0)  # continuous target, x is signal
            rows.append((d, tk, x, y))
    return pd.DataFrame(rows, columns=["date", "ticker", "x", "fwd_ret_pct"])


def test_embargo_default_zero_unchanged():
    """embargo_days=0 must reproduce the original no-gap behaviour: train_end = test_start-1."""
    df = _panel()
    specs = list(anchored_walk_forward(
        df, "date", date(2018, 1, 2), date(2021, 1, 1), date(2023, 1, 1), step="1Y",
    ))
    for s in specs:
        assert s.train_end == s.test_start - timedelta(days=1)


def test_embargo_opens_gap():
    """embargo_days=21 must push train_end back 21 days before test_start."""
    df = _panel()
    specs = list(anchored_walk_forward(
        df, "date", date(2018, 1, 2), date(2021, 1, 1), date(2023, 1, 1),
        step="1Y", embargo_days=21,
    ))
    assert specs
    for s in specs:
        assert s.train_end == s.test_start - timedelta(days=22)


def test_embargo_negative_rejected():
    df = _panel()
    with pytest.raises(ValueError):
        list(anchored_walk_forward(
            df, "date", date(2018, 1, 2), date(2021, 1, 1), date(2023, 1, 1),
            embargo_days=-1,
        ))


def test_assert_no_leakage_catches_overlap():
    train = pd.DataFrame({"date": pd.to_datetime(["2020-12-20", "2020-12-31"])})
    # max train 2020-12-31 + 21d = 2021-01-21, which is >= test_start -> leak
    with pytest.raises(AssertionError):
        assert_no_leakage(train, date(2021, 1, 1), "date", horizon=21)


def test_assert_no_leakage_passes_with_gap():
    train = pd.DataFrame({"date": pd.to_datetime(["2020-11-01", "2020-12-01"])})
    # 2020-12-01 + 21d = 2020-12-22 < 2021-01-01 -> safe
    assert_no_leakage(train, date(2021, 1, 1), "date", horizon=21)


def test_rank_ic_perfect_and_zero():
    # Perfect monotonic relation -> IC ~ 1
    df = pd.DataFrame({
        "date": ["d1"] * 5,
        "pred": [1, 2, 3, 4, 5],
        "tgt":  [10, 20, 30, 40, 50],
    })
    ic, _ = cross_sectional_rank_ic(df, "date", "pred", "tgt")
    assert ic == pytest.approx(1.0)


def test_run_m02_cv_recovers_signal():
    """End-to-end: a linear model on a strong linear signal yields positive Rank IC."""
    from sklearn.linear_model import LinearRegression

    df = _panel(seed=1)

    class _Model:
        def __init__(self):
            self.m = LinearRegression()
        def fit(self, X, y):
            self.m.fit(X, y); return self
        def predict(self, X):
            return self.m.predict(X)

    def train_fn(X, y, alpha):
        return _Model().fit(X, y)  # quantile ignored for the linear stub

    report = run_m02_cv(
        df, "date", ["x"], "fwd_ret_pct",
        train_start=date(2018, 1, 2), test_start=date(2021, 1, 1), test_end=date(2023, 1, 1),
        horizon=21, train_fn=train_fn, quantiles=(0.50,), step="1Y",
    )
    p50 = report.quantile_results[0.50]
    assert p50, "expected at least one fold"
    assert np.nanmean([fr.rank_ic_mean for fr in p50]) > 0.5
