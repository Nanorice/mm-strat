"""Phase 2 guard: the prod OOS-gate entrypoint is wired to the champion config.

The full re-gate is a minutes-long BackTrader run (needs DB + score caches) — an
operator command, not CI. This test guards the cheap invariants: the prod
entrypoint drives the SAME locked config that produced the recorded 1.47 gate,
and the fold plan is unchanged. If someone edits the champion kwargs, this fails
loudly before a stale gate artifact can mislead a promotion.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.backtest import strategy_registry as reg

REPO_ROOT = Path(__file__).resolve().parent.parent
RECORDED = REPO_ROOT / "data" / "selection_sweep" / "wfo_gate" / "T3_sl15_tpTight.json"

# Kwargs the gate exercises but the fingerprint has no token for (regime maps,
# sizing, cooldown) still matter for reproducibility — compare the full config.
_IGNORE = set()


def test_champion_config_matches_recorded_gate():
    """The registry champion == the config that produced the recorded 1.47 OOS."""
    if not RECORDED.exists():
        import pytest
        pytest.skip("recorded gate artifact absent")
    recorded = json.loads(RECORDED.read_text())["config"]
    champ = reg.get("champion").strategy_kwargs
    # regime maps come back from JSON with string keys — normalise before compare.
    def _norm(d):
        return {k: ({int(kk): vv for kk, vv in v.items()} if isinstance(v, dict) else v)
                for k, v in d.items()}
    assert _norm(champ) == _norm(recorded), "champion drifted from the gated config"


def test_recorded_gate_still_passes_bar():
    """The recorded champion OOS Sharpe is the promotion bar — guard it doesn't rot."""
    if not RECORDED.exists():
        import pytest
        pytest.skip("recorded gate artifact absent")
    agg = json.loads(RECORDED.read_text())["aggregate_oos"]
    assert agg["sharpe"] > 1.0, agg["sharpe"]


def test_prod_gate_reproduces_recorded_sharpe():
    """If the prod entrypoint has been run (champion.json exists), its aggregate
    OOS Sharpe must match the recorded reference within tolerance — the whole
    point of a reproducible gate."""
    prod = REPO_ROOT / "data" / "selection_sweep" / "wfo_gate" / "champion.json"
    if not (prod.exists() and RECORDED.exists()):
        import pytest
        pytest.skip("run scripts/run_oos_gate.py --strategy champion to populate")
    got = json.loads(prod.read_text())["aggregate_oos"]["sharpe"]
    ref = json.loads(RECORDED.read_text())["aggregate_oos"]["sharpe"]
    assert abs(got - ref) < 0.05, (got, ref)


def test_gate_folds_are_deterministic():
    from scripts.run_strategy_wfo import make_folds
    folds = make_folds("2021-01-01", "2026-05-31",
                       pd.DateOffset(years=2), pd.DateOffset(years=1), anchored=False)
    assert len(folds) == 3  # 3 rolling folds — matches the recorded gate
