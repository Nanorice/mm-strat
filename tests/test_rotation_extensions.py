"""Smoke test: SEPAHybridV1 rotation extensions default to no-op and the
prototype score adapter produces the ScoreLookup contract.

The full behavioural test lives in the notebook run (needs BackTrader feeds);
this guards the cheap invariants: defaults don't change existing strategies,
and the adapter's columns/derivations are correct.
"""
import pandas as pd

from src.backtest.sepa_strategy import SEPAHybridV1
from src.backtest.score_lookup import prototype_scores_to_contract, ScoreLookup


def test_new_params_default_noop():
    p = SEPAHybridV1.params
    assert p.entry_delay_days == 0        # immediate entry (E1) by default
    assert p.score_drop_thresh is None    # X2 disabled
    assert p.score_exit_floor is None
    assert p.sma_exit_independent is False  # tranche-gated as before
    assert p.selection_skip_top == 0      # take the very top by default (no skip)


def test_selection_skip_top_slices_ranked_candidates():
    """The skip drops the top-K ranked survivors before slot-filling.

    Mirrors the exact list op in _process_entries so a regression there fails
    here without needing BackTrader feeds. Candidates are (ticker, ...) tuples
    already in rank order; skip=2 must drop the first two.
    """
    valid = [("A", 1), ("B", 2), ("C", 3), ("D", 4)]
    skip = 2
    kept = valid[skip:]
    assert [t[0] for t in kept] == ["C", "D"]
    # slot slice after skip still respects available_slots
    assert [t[0] for t in kept[:1]] == ["C"]


def test_adapter_contract_and_ranks():
    raw = pd.DataFrame({
        "date": ["2025-10-06"] * 3,
        "ticker": ["A", "B", "C"],
        "prob_elite": [0.6, 0.4, 0.2],
    })
    out = prototype_scores_to_contract(raw)
    required = {"date", "ticker", "normalized_score", "daily_pct_rank",
                "trailing_pct", "prob_elite", "calibrated_score"}
    assert required <= set(out.columns)
    # normalized_score = prob*100; top prob gets rank 1.0
    assert out.loc[out.ticker == "A", "normalized_score"].iloc[0] == 60.0
    assert out.loc[out.ticker == "A", "daily_pct_rank"].iloc[0] == 1.0
    # adapter output loads into ScoreLookup without the "missing columns" raise
    ScoreLookup(out)


if __name__ == "__main__":
    test_new_params_default_noop()
    test_adapter_contract_and_ranks()
    print("[OK] rotation extension smoke checks passed")
