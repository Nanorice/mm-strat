"""SEPA entry-gate unit checks (no DB/model needed).

Guards the population-inflation fix: score_from_t3 scores the whole trend-active
panel, so candidate selection MUST gate on (trend_ok AND breakout_ok) — otherwise
the top-N is drawn from off-setup rows (a stock scored in a downtrend). These
tests pin the gate at both selection layers on synthetic frames.
"""
from __future__ import annotations

import pandas as pd

from src.backtest.score_lookup import ScoreLookup


def _frame() -> pd.DataFrame:
    # 3 tickers on one day: only AAA is a genuine breakout. BBB fails breakout_ok,
    # CCC fails trend_ok. BBB has the HIGHEST prob_elite — the inflation trap: an
    # ungated top-1 would pick the non-breakout.
    return pd.DataFrame({
        "date": pd.to_datetime(["2024-01-02"] * 3),
        "ticker": ["AAA", "BBB", "CCC"],
        "normalized_score": [60.0, 90.0, 80.0],
        "daily_pct_rank": [0.5, 0.9, 0.8],
        "trailing_pct": [0.5, 0.9, 0.8],
        "prob_elite": [0.40, 0.95, 0.85],
        "trend_ok": [True, True, False],
        "breakout_ok": [True, False, True],
    })


def test_gate_keeps_only_genuine_breakouts():
    lk = ScoreLookup(_frame())
    d = pd.Timestamp("2024-01-02")
    gated = lk.get_candidates(d, min_score=0.0, rank_by="prob_elite")
    assert [c[0] for c in gated] == ["AAA"], "only trend_ok AND breakout_ok survives"


def test_gate_off_returns_full_population():
    lk = ScoreLookup(_frame())
    d = pd.Timestamp("2024-01-02")
    ungated = lk.get_candidates(d, min_score=0.0, rank_by="prob_elite", require_sepa=False)
    # Ungated top pick is the highest prob_elite non-breakout — the very bug.
    assert ungated[0][0] == "BBB"
    assert len(ungated) == 3


def test_legacy_frame_without_flags_passes_through():
    df = _frame().drop(columns=["trend_ok", "breakout_ok"])
    lk = ScoreLookup(df)
    gated = lk.get_candidates(pd.Timestamp("2024-01-02"), min_score=0.0, rank_by="prob_elite")
    assert len(gated) == 3, "no flags => gate disabled (backward-compatible)"


def test_get_score_still_returns_4_tuple():
    lk = ScoreLookup(_frame())
    rec = lk.get_score(pd.Timestamp("2024-01-02"), "AAA")
    assert rec is not None and len(rec) == 4, "public contract must stay a 4-tuple"


if __name__ == "__main__":
    test_gate_keeps_only_genuine_breakouts()
    test_gate_off_returns_full_population()
    test_legacy_frame_without_flags_passes_through()
    test_get_score_still_returns_4_tuple()
    print("[OK] SEPA gate checks passed")
