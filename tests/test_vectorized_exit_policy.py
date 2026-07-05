"""Smoke test: exit_policy switch in VectorizedSEPABacktest.

Synthetic 1-ticker price paths force each policy to fire its signature exit,
so a regression in the branch logic fails here rather than silently in a sweep.
"""
import numpy as np
import pandas as pd

from src.backtest.vectorized_backtest import VectorizedSEPABacktest


def _bt(prices: pd.DataFrame, scores: pd.DataFrame, **kw) -> VectorizedSEPABacktest:
    return VectorizedSEPABacktest(
        start_date="2020-01-01", end_date="2020-12-31",
        min_prob_elite=0.1, max_positions_per_day=1, warmup_days=0,
        commission_pct=0.0, slippage_pct=0.0,
        precomputed_scores=scores.copy(), precomputed_prices=prices.copy(), **kw,
    )


def _make(closes: list[float], highs=None, lows=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range("2020-01-01", periods=len(closes))
    highs = highs or [c * 1.001 for c in closes]
    lows = lows or [c * 0.999 for c in closes]
    prices = pd.DataFrame({
        "ticker": "AAA", "date": dates, "open": closes,
        "high": highs, "low": lows, "close": closes,
    })
    scores = pd.DataFrame({"date": [dates[0]], "ticker": ["AAA"],
                           "prob_elite": [0.9], "calibrated_score": [10.0]})
    return prices, scores


def test_nday_exits_after_n_bars():
    prices, scores = _make([100.0] * 30)  # flat: no stop, no trend break
    trades = _bt(prices, scores, exit_policy="nday", nday_hold=5).run()
    assert len(trades) == 1
    assert trades.iloc[0]["exit_reason"] == "nday_exit"
    assert trades.iloc[0]["holding_days"] >= 5


def test_stop_loss_fires_before_nday():
    closes = [100.0, 100.0, 80.0] + [100.0] * 10  # -20% on bar 3
    prices, scores = _make(closes, lows=[100, 100, 80] + [100] * 10)
    trades = _bt(prices, scores, exit_policy="nday", nday_hold=5, stop_loss_pct=0.10).run()
    assert trades.iloc[0]["exit_reason"] == "stop_loss"


def test_atr_trail_exits_on_pullback():
    # ramp up then sharp drop — trailing stop off the running high should fire.
    closes = [100 + i for i in range(15)] + [100.0] * 5
    prices, scores = _make(closes, lows=[c * 0.999 for c in closes])
    trades = _bt(prices, scores, exit_policy="atr_trail", atr_trail_mult=1.5).run()
    assert len(trades) == 1
    assert trades.iloc[0]["exit_reason"] in ("stop_loss", "max_hold", "held_open")


def test_bad_policy_raises():
    prices, scores = _make([100.0] * 5)
    try:
        _bt(prices, scores, exit_policy="tranche")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_capacity_gate_blocks_over_subscription():
    # 3 tickers each signalling on consecutive days, ~5-bar nday holds → they
    # overlap. With a 1-slot book only the first fits until it exits; the
    # capacity pass must drop the ones with no free slot.
    dates = pd.bdate_range("2020-01-01", periods=20)
    rows = []
    for k, tkr in enumerate(("AAA", "BBB", "CCC")):
        c = [100.0] * 20
        rows.append(pd.DataFrame({"ticker": tkr, "date": dates, "open": c,
                                  "high": c, "low": c, "close": c}))
    prices = pd.concat(rows, ignore_index=True)
    # entries on days 0, 1, 2 — all overlap a 5-bar hold
    scores = pd.DataFrame({
        "date": [dates[0], dates[1], dates[2]],
        "ticker": ["AAA", "BBB", "CCC"],
        "prob_elite": [0.9, 0.8, 0.7], "calibrated_score": [10.0, 9.0, 8.0],
    })
    kw = dict(start_date="2020-01-01", end_date="2020-12-31", min_prob_elite=0.1,
              max_positions_per_day=3, warmup_days=0, commission_pct=0.0,
              slippage_pct=0.0, exit_policy="nday", nday_hold=5)
    uncapped = VectorizedSEPABacktest(precomputed_scores=scores.copy(),
                                      precomputed_prices=prices.copy(), **kw).run()
    capped = VectorizedSEPABacktest(max_concurrent_positions=1,
                                    precomputed_scores=scores.copy(),
                                    precomputed_prices=prices.copy(), **kw).run()
    assert len(uncapped) == 3          # all three admitted without a cap
    assert len(capped) == 1            # 1-slot book: only the first fits
    assert capped.iloc[0]["ticker"] == "AAA"


if __name__ == "__main__":
    test_nday_exits_after_n_bars()
    test_stop_loss_fires_before_nday()
    test_atr_trail_exits_on_pullback()
    test_bad_policy_raises()
    test_capacity_gate_blocks_over_subscription()
    print("[OK] all exit_policy smoke checks passed")
