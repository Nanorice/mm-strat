"""Smoke tests for src.analytics (§4.3)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.analytics import decile_analysis, rolling_ic, score_trajectory


# ----------------------------- rolling_ic -----------------------------


def _build_predictive_panel(n_days: int = 400, n_tickers: int = 50, signal: float = 0.8,
                            seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2022-01-03", periods=n_days)
    rows = []
    for d in dates:
        true_r = rng.normal(0, 1, n_tickers)
        score = signal * true_r + (1 - signal) * rng.normal(0, 1, n_tickers)
        for j in range(n_tickers):
            rows.append((d, f"T{j:03d}", score[j], true_r[j]))
    return pd.DataFrame(rows, columns=["date", "ticker", "score", "forward_return"])


def test_rolling_ic_returns_expected_columns():
    df = _build_predictive_panel(n_days=300, signal=0.6, seed=2)
    out = rolling_ic(df, window_days=60)
    assert set(out.columns) == {"ic", "n_daily_obs", "rolling_ic_mean", "rolling_ic_t_stat"}
    assert len(out) == 300


def test_rolling_ic_predictive_score_has_positive_mean():
    df = _build_predictive_panel(n_days=200, signal=0.7, seed=3)
    out = rolling_ic(df, window_days=60)
    last_mean = out["rolling_ic_mean"].dropna().iloc[-1]
    assert last_mean > 0.3, f"expected positive rolling IC, got {last_mean}"


def test_rolling_ic_random_score_has_zero_mean():
    df = _build_predictive_panel(n_days=200, signal=0.0, seed=4)
    out = rolling_ic(df, window_days=60)
    last_mean = out["rolling_ic_mean"].dropna().iloc[-1]
    assert abs(last_mean) < 0.15, f"expected near-zero IC for random, got {last_mean}"


def test_rolling_ic_predictive_t_stat_is_significant():
    df = _build_predictive_panel(n_days=300, signal=0.7, seed=5)
    out = rolling_ic(df, window_days=120, nw_lag=5)
    last_t = out["rolling_ic_t_stat"].dropna().iloc[-1]
    assert last_t > 2.0, f"expected t > 2 for strong signal, got {last_t}"


def test_rolling_ic_pearson_method_works():
    df = _build_predictive_panel(n_days=150, signal=0.6, seed=6)
    out = rolling_ic(df, window_days=50, method="pearson")
    assert out["rolling_ic_mean"].dropna().iloc[-1] > 0.2


def test_rolling_ic_rejects_unknown_method():
    df = _build_predictive_panel(n_days=30, signal=0.5, seed=7)
    with pytest.raises(ValueError, match="unknown method"):
        rolling_ic(df, window_days=10, method="kendall")  # type: ignore


def test_rolling_ic_raises_on_missing_column():
    df = _build_predictive_panel(n_days=30).drop(columns=["score"])
    with pytest.raises(KeyError, match="score"):
        rolling_ic(df, window_days=10)


# ----------------------------- decile_analysis -----------------------------


def test_decile_monotonic_when_signal_is_strong():
    df = _build_predictive_panel(n_days=100, signal=0.9, seed=10)
    out = decile_analysis(df, n_buckets=10)
    assert out["n_buckets"] == 10
    assert len(out["per_bucket"]) >= 5
    # Spearman should be near 1 — high score predicts high return.
    assert out["monotonicity_spearman"] > 0.5
    assert out["top_minus_bottom_return"] > 0.1


def test_decile_flat_when_signal_is_random():
    df = _build_predictive_panel(n_days=80, signal=0.0, seed=11)
    out = decile_analysis(df, n_buckets=10)
    # Random signal → monotonicity is unconstrained, but top-minus-bottom should be small.
    assert abs(out["top_minus_bottom_return"]) < 0.5


def test_decile_rejects_bad_n_buckets():
    df = _build_predictive_panel(n_days=10, signal=0.5)
    with pytest.raises(ValueError, match="n_buckets"):
        decile_analysis(df, n_buckets=1)


def test_decile_handles_empty_input():
    df = pd.DataFrame(columns=["date", "score", "forward_return"])
    out = decile_analysis(df, n_buckets=5)
    assert out["per_bucket"] == []
    assert np.isnan(out["monotonicity_spearman"])


# ----------------------------- score_trajectory -----------------------------


def _build_scores_and_events():
    """Simulate scores that rise into an event date, then drift back."""
    dates = pd.bdate_range("2022-01-03", periods=200)
    tickers = ["A", "B", "C"]
    rng = np.random.default_rng(42)
    rows = []
    for tk in tickers:
        # Score = noise around 50, plus a hump centered around day 100.
        base = 50 + 10 * np.exp(-0.5 * ((np.arange(200) - 100) / 8) ** 2)
        noise = rng.normal(0, 1, 200)
        for i, d in enumerate(dates):
            rows.append((d, tk, base[i] + noise[i]))
    scores = pd.DataFrame(rows, columns=["date", "ticker", "score"])

    events = pd.DataFrame({
        "ticker": tickers,
        "event_date": [dates[100]] * 3,
    })
    return scores, events


def test_score_trajectory_has_expected_shape():
    scores, events = _build_scores_and_events()
    out = score_trajectory(scores, events, window_before=10, window_after=10)
    assert len(out) == 21  # -10..+10 inclusive
    assert out["relative_day"].tolist() == list(range(-10, 11))
    assert out["n_events"].max() == 3


def test_score_trajectory_peaks_at_event():
    scores, events = _build_scores_and_events()
    out = score_trajectory(scores, events, window_before=20, window_after=20)
    # Peak should be at relative_day=0 (we built the hump there).
    peak_row = out.loc[out["mean_score"].idxmax()]
    assert abs(int(peak_row["relative_day"])) <= 3


def test_score_trajectory_skips_missing_tickers():
    scores, _ = _build_scores_and_events()
    events = pd.DataFrame({
        "ticker": ["XYZ_unknown"],
        "event_date": [pd.Timestamp("2022-03-01")],
    })
    out = score_trajectory(scores, events, window_before=5, window_after=5)
    # No matching ticker → all n_events = 0
    assert (out["n_events"] == 0).all()


def test_score_trajectory_raises_on_missing_column():
    scores = pd.DataFrame({"date": [], "ticker": [], "score": []})
    events = pd.DataFrame({"ticker": [], "event_date": []})
    scores_no_score = scores.drop(columns=["score"])
    with pytest.raises(KeyError, match="score"):
        score_trajectory(scores_no_score, events)
