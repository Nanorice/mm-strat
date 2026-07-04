import numpy as np
import pandas as pd
import pytest

from src.features.trend_segments import (
    compute_trend_segments,
    compute_market_stage,
    PRIOR_WINDOW,
)


def _path(seg_slopes, n_each, start=100.0):
    p, s = start, []
    for sl in seg_slopes:
        for _ in range(n_each):
            p *= (1 + sl)
            s.append(p)
    return s


def _frame(ticker, prices, dates):
    df = pd.DataFrame({"ticker": [ticker] * len(prices), "date": dates[:len(prices)], "close": prices})
    df["atr_14"] = df["close"] * 0.02
    return df


def test_prior_slope_sign_separates_base_from_top():
    """A flat base after a decline is negative; a flat top after an advance is positive."""
    dates = pd.date_range("2019-01-01", periods=600, freq="B")
    base = _frame("BASE", _path([-0.01, 0.0], 150), dates)   # decline -> flat
    top = _frame("TOP", _path([0.01, 0.0], 150), dates)      # advance -> flat
    res = compute_trend_segments(pd.concat([base, top], ignore_index=True))
    tail = res.groupby("ticker").tail(1).set_index("ticker")
    assert tail.loc["BASE", "prior_slope_sign"] < 0
    assert tail.loc["TOP", "prior_slope_sign"] > 0


def test_pivots_detected_on_zigzag():
    dates = pd.date_range("2019-01-01", periods=200, freq="B")
    df = _frame("ZZ", _path([0.01, -0.01, 0.01], 40), dates)
    res = compute_trend_segments(df)
    assert res["pivot_high"].any()
    assert res["pivot_low"].any()


def test_slope_sign_tracks_direction():
    dates = pd.date_range("2019-01-01", periods=200, freq="B")
    up = compute_trend_segments(_frame("UP", _path([0.01], 150), dates))
    down = compute_trend_segments(_frame("DN", _path([-0.01], 150), dates))
    assert up["slope_63d"].dropna().iloc[-1] > 0
    assert down["slope_63d"].dropna().iloc[-1] < 0


def test_clean_trend_has_high_r2():
    """A straight-line trend is high R2; alternating noise is low R2."""
    dates = pd.date_range("2019-01-01", periods=200, freq="B")
    clean = compute_trend_segments(_frame("CLN", _path([0.005], 150), dates))
    assert clean["slope_r2_63d"].dropna().iloc[-1] > 0.9


def test_prior_slope_sign_nan_during_warmup():
    dates = pd.date_range("2019-01-01", periods=PRIOR_WINDOW - 10, freq="B")
    res = compute_trend_segments(_frame("W", _path([0.01], PRIOR_WINDOW - 10), dates))
    assert res["prior_slope_sign"].isna().all()


def test_missing_column_raises():
    with pytest.raises(ValueError, match="missing columns"):
        compute_trend_segments(pd.DataFrame({"ticker": ["X"], "date": [pd.Timestamp("2020-01-01")]}))


# --- Phase 2: market_stage classifier ---

def _stage_row(trend_ok, prior, slope):
    df = pd.DataFrame({"trend_ok": [trend_ok], "prior_slope_sign": [prior], "slope_63d": [slope]})
    return compute_market_stage(df).iloc[0]


def test_stage2_iff_trend_ok():
    assert _stage_row(True, -1.0, -0.01) == 2   # trend_ok wins regardless of other cols
    assert _stage_row(True, 1.0, 0.01) == 2


def test_stage3_top_from_prior_advance():
    # came from an advance, template lost -> top, even if slope still flat/positive
    assert _stage_row(False, 1.0, 0.001) == 3
    assert _stage_row(False, 1.0, -0.01) == 3


def test_stage4_declining():
    assert _stage_row(False, -1.0, -0.01) == 4


def test_stage1_base_from_prior_decline_flattening():
    assert _stage_row(False, -1.0, 0.0) == 1
    assert _stage_row(False, -1.0, 0.005) == 1


def test_prior_up_never_becomes_base():
    """The costly error guard: a name that came from an advance must never be labelled Stage 1."""
    for slope in (-0.02, 0.0, 0.02):
        assert _stage_row(False, 1.0, slope) != 1


def test_stage_null_during_warmup():
    assert pd.isna(_stage_row(False, np.nan, 0.01))
    assert _stage_row(True, np.nan, 0.01) == 2   # trend_ok still classifiable without prior


def test_stages_are_mece_on_real_shaped_data():
    """Every non-warmup row gets exactly one stage in {1,2,3,4}."""
    dates = pd.date_range("2018-01-01", periods=700, freq="B")
    px = _path([0.008, -0.005, 0.0, 0.006], 175)
    df = _frame("MECE", px, dates)
    res = compute_trend_segments(df)
    res["trend_ok"] = res["slope_63d"] > 0.004   # crude synthetic template
    res["market_stage"] = compute_market_stage(res)
    classified = res.dropna(subset=["market_stage"])
    assert classified["market_stage"].isin([1, 2, 3, 4]).all()
    assert classified["market_stage"].notna().all()
