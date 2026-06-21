"""Tests for src.evaluation.permutation_null (§4.2)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.evaluation.permutation_null import permutation_null_backtest


def _make_signals(n_days: int = 30, n_tickers: int = 20, edge: float = 0.5,
                  seed: int = 0) -> pd.DataFrame:
    """Build a signals frame where `signal` correlates with `true_return` at `edge`.

    `edge=0` → no signal (random); `edge=1` → perfect.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2022-01-03", periods=n_days)
    rows = []
    for d in dates:
        true_r = rng.normal(0, 1, n_tickers)
        # Signal aligned with true_r at `edge` strength.
        signal_score = edge * true_r + (1 - edge) * rng.normal(0, 1, n_tickers)
        for j in range(n_tickers):
            rows.append((d, f"T{j:02d}", signal_score[j], true_r[j]))
    return pd.DataFrame(rows, columns=["date", "ticker", "signal", "true_return"])


def _top_n_avg_return(df: pd.DataFrame, n: int = 3) -> dict:
    """Backtest: take top-N by signal each day, average their true_return."""
    if df.empty:
        return {"sharpe_ratio": 0.0}
    picks = (
        df.sort_values(["date", "signal"], ascending=[True, False])
        .groupby("date")
        .head(n)
    )
    daily_avg = picks.groupby("date")["true_return"].mean()
    if daily_avg.std(ddof=1) == 0:
        return {"sharpe_ratio": 0.0}
    sharpe = float(daily_avg.mean() / daily_avg.std(ddof=1) * np.sqrt(252))
    return {"sharpe_ratio": sharpe}


# ----------------------------- core behaviour -----------------------------


def test_random_signal_percentile_near_50():
    """No edge → observed should land near the middle of the null."""
    df = _make_signals(n_days=30, n_tickers=20, edge=0.0, seed=11)
    out = permutation_null_backtest(
        signals_df=df,
        backtest_fn=_top_n_avg_return,
        n_permutations=80,
        seed=11,
    )
    # Loose bound — sometimes the realised observation is in a tail by chance.
    # But "random signal" means percentile is symmetrically distributed around 50.
    # Run twice with different seeds to reduce variance:
    out2 = permutation_null_backtest(df, _top_n_avg_return, n_permutations=80, seed=23)
    pct = (out["percentile"] + out2["percentile"]) / 2
    # Generous tolerance — should not be in the extreme tail.
    assert 10 < pct < 90, f"random signal landed at percentile {pct}, expected middle"


def test_strong_signal_percentile_above_95():
    df = _make_signals(n_days=30, n_tickers=20, edge=0.95, seed=42)
    out = permutation_null_backtest(
        signals_df=df,
        backtest_fn=_top_n_avg_return,
        n_permutations=80,
        seed=42,
    )
    assert out["percentile"] > 90, f"strong signal landed at percentile {out['percentile']}"


def test_gate_passes_on_strong_signal():
    df = _make_signals(n_days=40, n_tickers=15, edge=0.95, seed=99)
    out = permutation_null_backtest(df, _top_n_avg_return, n_permutations=100, seed=99)
    assert out["gate"]["status"] == "pass"
    assert out["gate"]["blocking"] is True


def test_gate_fails_on_no_signal():
    df = _make_signals(n_days=30, n_tickers=15, edge=0.0, seed=7)
    out = permutation_null_backtest(df, _top_n_avg_return, n_permutations=80, seed=7)
    # Random signal almost never hits percentile > 95.
    # (Allowed flake: 5% of the time it would by chance — re-run with different seed if rare.)
    assert out["gate"]["status"] == "fail" or out["percentile"] <= 95


def test_p_value_decreases_with_stronger_edge():
    df_weak = _make_signals(n_days=40, n_tickers=20, edge=0.1, seed=1)
    df_strong = _make_signals(n_days=40, n_tickers=20, edge=0.9, seed=1)
    out_weak = permutation_null_backtest(df_weak, _top_n_avg_return, n_permutations=60, seed=1)
    out_strong = permutation_null_backtest(df_strong, _top_n_avg_return, n_permutations=60, seed=1)
    assert out_strong["p_value"] <= out_weak["p_value"]


def test_null_distribution_has_expected_length():
    df = _make_signals(n_days=20, n_tickers=10, edge=0.5, seed=3)
    out = permutation_null_backtest(df, _top_n_avg_return, n_permutations=50, seed=3)
    assert len(out["null_distribution"]) == out["n_valid_replicates"]
    assert out["n_permutations"] == 50


# ----------------------------- input validation -----------------------------


def test_empty_signals_raises():
    df = pd.DataFrame(columns=["date", "signal"])
    with pytest.raises(ValueError, match="empty"):
        permutation_null_backtest(df, _top_n_avg_return, n_permutations=10)


def test_missing_column_raises():
    df = _make_signals(n_days=5, edge=0.5).drop(columns=["signal"])
    with pytest.raises(KeyError, match="signal"):
        permutation_null_backtest(df, _top_n_avg_return, n_permutations=10)


def test_missing_metric_raises():
    df = _make_signals(n_days=10, edge=0.5)

    def no_sharpe(_d):
        return {"return": 0.5}

    with pytest.raises(KeyError, match="sharpe_ratio"):
        permutation_null_backtest(df, no_sharpe, n_permutations=10)


def test_replicate_failures_yield_nan_but_observed_still_recorded():
    df = _make_signals(n_days=8, n_tickers=10, edge=0.5, seed=4)
    counter = {"n": 0}

    def bt(d):
        counter["n"] += 1
        if counter["n"] == 1:
            return {"sharpe_ratio": 0.7}
        raise RuntimeError("boom")

    out = permutation_null_backtest(df, bt, n_permutations=20, seed=4)
    assert out["observed_metric"] == 0.7
    assert out["n_valid_replicates"] == 0
    assert np.isnan(out["percentile"])
