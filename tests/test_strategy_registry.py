"""Phase 1 guard: registry round-trips + every config is a valid SEPAHybridV1 kwargs set."""
from __future__ import annotations

from src.backtest import strategy_registry as reg
from src.backtest.sepa_strategy import SEPAHybridV1


def _declared_params() -> set[str]:
    return set(SEPAHybridV1.params._getkeys())


def test_every_kwarg_is_a_declared_param():
    """A typo'd kwarg would be silently dropped by BackTrader — catch it here."""
    declared = _declared_params()
    for d in reg.STRATEGIES.values():
        unknown = set(d.strategy_kwargs) - declared
        assert not unknown, f"{d.name}: unknown SEPAHybridV1 params {unknown}"


def test_champion_fingerprint_roundtrips():
    champ = reg.get("champion")
    assert champ.fingerprint == "E1.d0_X1.sl15_Xt.t1_10_X3.sma50_S0.top5"
    rt = reg.parse_fingerprint(champ.fingerprint)
    for k in ("max_stop_pct", "min_target1_pct", "sma_exit_independent", "entry_top_n"):
        assert rt[k] == champ.strategy_kwargs[k], k


def test_fingerprint_roundtrip_stable():
    for name in ("champion", "e1_seed"):
        d = reg.get(name)
        assert reg.to_fingerprint(reg.parse_fingerprint(d.fingerprint)) == d.fingerprint


def test_s_series_present():
    assert reg.get("S1_baseline_top3").strategy_kwargs["entry_top_n"] == 3
    assert len([d for d in reg.STRATEGIES.values() if d.status == "baseline"]) >= 6
