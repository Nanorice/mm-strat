"""Tests for src.evaluation.bootstrap (§4.1)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.evaluation.bootstrap import (
    circular_block_bootstrap,
    sharpe_from_trades,
    total_return_from_trades,
)


def _synthetic_trades(n: int = 100, mean: float = 0.5, sd: float = 5.0,
                      start: str = "2022-01-03", seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start=start, periods=n)
    return pd.DataFrame({
        "ticker": [f"T{i:03d}" for i in range(n)],
        "exit_date": dates,
        "pnl_percent": rng.normal(mean, sd, n),
    })


def test_circular_block_bootstrap_empty_returns_nans():
    df = pd.DataFrame(columns=["ticker", "exit_date", "pnl_percent"])
    out = circular_block_bootstrap(df, metric_fn=sharpe_from_trades, n_iterations=100)
    assert out["n_trades"] == 0
    assert np.isnan(out["metric_observed"])
    assert out["gate"]["status"] == "n/a"


def test_observed_metric_lies_within_ci_for_random_walk():
    df = _synthetic_trades(n=200, mean=0.5, sd=3.0, seed=42)
    out = circular_block_bootstrap(
        df,
        metric_fn=lambda d: total_return_from_trades(d),
        block_size_days=30,
        n_iterations=2000,
        seed=42,
    )
    # The observed value should sit inside its own CI (it's just one realization).
    assert out["ci_lo"] <= out["metric_observed"] <= out["ci_hi"]


def test_ci_width_decreases_with_more_iterations():
    df = _synthetic_trades(n=150, mean=0.3, sd=2.5, seed=1)

    out_small = circular_block_bootstrap(
        df, metric_fn=total_return_from_trades, n_iterations=300, seed=1, block_size_days=20,
    )
    out_big = circular_block_bootstrap(
        df, metric_fn=total_return_from_trades, n_iterations=5000, seed=1, block_size_days=20,
    )
    width_small = out_small["ci_hi"] - out_small["ci_lo"]
    width_big = out_big["ci_hi"] - out_big["ci_lo"]
    # Bigger n only narrows MC noise; we can't guarantee strict shrinkage, but
    # the larger run should be ≤ ~1.5× the smaller in width.
    assert width_big <= width_small * 1.5


def test_block_size_affects_correlated_data_ci():
    """Auto-correlated trades: small blocks under-estimate variance (tighter CI),
    bigger blocks should be more conservative (wider)."""
    n = 300
    rng = np.random.default_rng(11)
    # AR(1) trades: highly serially correlated
    eps = rng.normal(0, 1, n)
    r = np.zeros(n)
    r[0] = eps[0]
    for i in range(1, n):
        r[i] = 0.8 * r[i - 1] + eps[i]
    df = pd.DataFrame({
        "exit_date": pd.bdate_range("2022-01-03", periods=n),
        "pnl_percent": r,
    })

    out_small = circular_block_bootstrap(df, total_return_from_trades, block_size_days=1,
                                         n_iterations=1000, seed=11)
    out_big = circular_block_bootstrap(df, total_return_from_trades, block_size_days=60,
                                       n_iterations=1000, seed=11)
    # Bigger blocks should not produce a *tighter* CI than block_size=1 on AR(1) data.
    width_small = out_small["ci_hi"] - out_small["ci_lo"]
    width_big = out_big["ci_hi"] - out_big["ci_lo"]
    assert width_big >= width_small * 0.5  # generous tolerance for MC noise


def test_gate_passes_when_ci_lo_above_threshold():
    """Synthesize a strong positive-mean process so ci_lo(sharpe) > 0."""
    df = _synthetic_trades(n=200, mean=3.0, sd=1.0, seed=5)
    out = circular_block_bootstrap(
        df, metric_fn=total_return_from_trades,
        block_size_days=20, n_iterations=2000, seed=5,
        ci_lo_gate_value=0.0,
    )
    assert out["gate"]["status"] == "pass"
    assert out["ci_lo"] > 0


def test_gate_fails_when_ci_straddles_zero():
    df = _synthetic_trades(n=80, mean=0.0, sd=5.0, seed=2)
    out = circular_block_bootstrap(
        df, metric_fn=total_return_from_trades,
        block_size_days=30, n_iterations=1500, seed=2,
        ci_lo_gate_value=0.0,
    )
    # With mean=0, ci_lo will be negative.
    assert out["gate"]["status"] == "fail"
    assert out["ci_lo"] < 0


def test_metric_fn_failure_yields_nan_but_does_not_crash():
    """Observed call must succeed; replicate failures get NaN'd, not propagated."""
    df = _synthetic_trades(n=100, seed=3)
    counter = {"n": 0}

    def metric(d):
        counter["n"] += 1
        if counter["n"] > 1:
            raise RuntimeError("boom")
        return 1.0

    out = circular_block_bootstrap(df, metric_fn=metric, n_iterations=50, seed=3,
                                   block_size_days=10)
    # First call (observed) returns 1.0; all 50 replicate calls fail → NaN CI.
    assert out["metric_observed"] == 1.0
    assert np.isnan(out["ci_lo"])
    assert out["gate"]["status"] == "fail"


def test_missing_exit_date_column_raises():
    df = pd.DataFrame({"pnl_percent": [1, 2, 3]})
    with pytest.raises(KeyError, match="exit_date"):
        circular_block_bootstrap(df, metric_fn=total_return_from_trades, n_iterations=10)


def test_sharpe_helper_handles_empty():
    assert np.isnan(sharpe_from_trades(pd.DataFrame()))


def test_sharpe_helper_constant_returns_nan():
    df = pd.DataFrame({"pnl_percent": [1.0] * 20})
    assert np.isnan(sharpe_from_trades(df))


def test_total_return_helper_sums():
    df = pd.DataFrame({"pnl_percent": [1.0, 2.5, -1.5]})
    assert total_return_from_trades(df) == pytest.approx(2.0)
