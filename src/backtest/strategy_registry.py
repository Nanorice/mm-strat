"""Named, versioned strategy registry + fingerprint parser.

A strategy is not a subclass — it's a bundle of `SEPAHybridV1` kwargs behind a
stable name and a human-readable fingerprint. The registry is the single source
of truth for the champion, the S-series array, and the experiment arms; the
fingerprint (`<Entry>_<Stop>_<TP>_<Selection>`) is a lossy human label whose
canonical form round-trips through `parse_fingerprint`/`to_fingerprint`.

Scheme (docs/session_logs/sprint_13/strategy_exploration_summary.md §fingerprint):
    Entry     E1.d0            immediate entry, delay 0
              E2.d3            delayed N days
    Stop      X1.sl15          wider-of(ATR, %) whole-position stop @ 15%
    TP        Xt.t1_10         tranche T1 at +10%
              X3.sma50         decoupled SMA50 trend exit
    Selection S0.top5          top-5 by score
              (skipK)          selection_skip_top=K

Only the components a config actually sets appear in its fingerprint.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

Status = str  # 'champion' | 'candidate' | 'baseline' | 'retired'


@dataclass(frozen=True)
class StrategyDef:
    name: str
    signal: str  # 'binary' | 'proto_cali'
    strategy_kwargs: Dict[str, Any]
    description: str
    status: Status
    fingerprint: str = ""  # canonical; derived if left blank

    def __post_init__(self):
        if not self.fingerprint:
            object.__setattr__(self, "fingerprint", to_fingerprint(self.strategy_kwargs))


# --- fingerprint <-> kwargs --------------------------------------------------
# One component = (family-index, dotted suffix). The suffix carries the knob.
# parse is deliberately narrow: it handles the components the summary defines and
# raises on anything unknown rather than silently dropping it.

_FAMILIES = ("E1", "E2", "X1", "Xt", "X3", "S0", "skip")


def parse_fingerprint(fp: str) -> Dict[str, Any]:
    """`E1.d0_X1.sl15_Xt.t1_10_X3.sma50_S0.top5` -> strategy_kwargs.

    `_` is both the component separator AND appears inside a suffix (`t1_10`), so
    split on `_` then re-join tokens that don't start a new family index."""
    kwargs: Dict[str, Any] = {}
    comps: List[str] = []
    for tok in fp.split("_"):
        if any(tok.startswith(f) for f in _FAMILIES) or not comps:
            comps.append(tok)
        else:  # continuation of the previous component's suffix (e.g. the '10' in t1_10)
            comps[-1] += "_" + tok
    for comp in comps:
        comp = comp.strip()
        if not comp:
            continue
        idx, _, suffix = comp.partition(".")
        _apply_component(idx, suffix, comp, kwargs)
    return kwargs


def _apply_component(idx: str, suffix: str, comp: str, kwargs: Dict[str, Any]) -> None:
    if idx == "E1":  # immediate entry
        kwargs["entry_delay_days"] = 0
    elif idx == "E2":  # E2.dN delayed
        kwargs["entry_delay_days"] = int(suffix.lstrip("d"))
    elif idx == "X1":  # X1.slNN whole-position % stop (ATR mult inert -> not set)
        kwargs["max_stop_pct"] = int(suffix.lstrip("sl")) / 100.0
    elif idx == "Xt":  # Xt.t1_NN tranche T1 target at +NN%
        kwargs["min_target1_pct"] = int(suffix.split("_")[-1]) / 100.0
    elif idx == "X3":  # X3.smaNN decoupled SMA trend exit
        kwargs["sma_exit_period"] = int(suffix.lstrip("sma"))
        kwargs["sma_exit_independent"] = True
    elif idx == "S0":  # S0.topN
        kwargs["entry_mode"] = "top_n"
        kwargs["entry_top_n"] = int(suffix.lstrip("top"))
        kwargs["rank_by"] = "prob_elite"
    elif idx.startswith("skip"):  # selection skip-top-K
        kwargs["selection_skip_top"] = int(idx.lstrip("skip"))
    else:
        raise ValueError(f"Unknown fingerprint component: {comp!r}")


def to_fingerprint(kwargs: Dict[str, Any]) -> str:
    """Canonical fingerprint for the components this registry names. Kwargs the
    scheme has no token for (regime maps, sizing, cooldown) are omitted — the
    fingerprint is a label, `strategy_kwargs` is the ground truth."""
    parts: List[str] = []
    delay = kwargs.get("entry_delay_days", 0)
    parts.append("E1.d0" if delay == 0 else f"E2.d{delay}")
    if "max_stop_pct" in kwargs:
        parts.append(f"X1.sl{round(kwargs['max_stop_pct'] * 100)}")
    if "min_target1_pct" in kwargs:
        parts.append(f"Xt.t1_{round(kwargs['min_target1_pct'] * 100)}")
    if kwargs.get("sma_exit_independent") and "sma_exit_period" in kwargs:
        parts.append(f"X3.sma{kwargs['sma_exit_period']}")
    if kwargs.get("entry_mode") == "top_n" and kwargs.get("entry_top_n"):
        parts.append(f"S0.top{kwargs['entry_top_n']}")
    if kwargs.get("selection_skip_top"):
        parts.append(f"skip{kwargs['selection_skip_top']}")
    return "_".join(parts)


# --- shared building block ----------------------------------------------------
# Equal-weight slot book, top-N by prob_elite, decoupled SMA50 exit, whole-%
# stop. regime_max_pos = N slots; regime 0 liquidates (M03 strong-bear gate).
# Lifted verbatim from run_strategy_confirm._base_kwargs — the registry now owns it.

def _base_kwargs(n: int) -> Dict[str, Any]:
    return {
        "entry_mode": "top_n",
        "entry_top_n": n,
        "rank_by": "prob_elite",
        "min_prob_elite": 0.15,
        "sizing_mode": "equal_weight",
        "regime_sizes": {0: 0.0, 1: 1.0 / n, 2: 1.0 / n, 3: 1.0 / n, 4: 1.0 / n},
        "regime_max_pos": {0: 0, 1: n, 2: n, 3: n, 4: n},
        "atr_stop_mult": 2.0,
        "max_stop_pct": 0.10,
        "sma_exit_period": 50,
        "sma_exit_independent": True,
        "min_score": 0,
        "cooldown_days": 3,
    }


def _champion_kwargs() -> Dict[str, Any]:
    # E1.d0_X1.sl15_Xt.t1_10_X3.sma50_S0.top5 — the 2026-07-05 OOS-gated champion.
    # atr_stop_mult stays at the base 2.0 but is INERT (10-15% floor always wins).
    return {**_base_kwargs(5), "max_stop_pct": 0.15, "min_target1_pct": 0.10}


# --- the registry -------------------------------------------------------------

STRATEGIES: Dict[str, StrategyDef] = {}


def _register(d: StrategyDef) -> None:
    STRATEGIES[d.name] = d


_register(StrategyDef(
    name="champion",
    signal="binary",
    strategy_kwargs=_champion_kwargs(),
    description="OOS-gated champion (2026-07-05): 15% stop x +10% T1, decoupled SMA50, top-5.",
    status="champion",
))

_register(StrategyDef(
    name="e1_seed",
    signal="binary",
    strategy_kwargs=_base_kwargs(5),
    description="E1 seed (pre-exit-grid baseline): 10% stop, default TP, decoupled SMA50, top-5.",
    status="baseline",
))

# proto cap_skip2 @ N=10 — the vectorized winner that BackTrader down-ranked
# (mid-pack 0.59); kept as a retired reference / DD-lever example.
_register(StrategyDef(
    name="proto_skip2_n10",
    signal="proto_cali",
    strategy_kwargs={**_base_kwargs(10), "selection_skip_top": 2},
    description="proto skip-top-2 @ N=10 — vec winner, retired (lost the BackTrader confirm).",
    status="retired",
))


# --- S-series array (migrated from run_strategy_array.STRATEGY_ARRAY) ----------
# Single source of truth now lives here; run_strategy_array imports it.
_S_ARRAY = {
    "S1_baseline_top3": (
        "Baseline: top-3 daily, regime caps, default exits.",
        {"entry_mode": "top_n", "entry_top_n": 3, "rank_by": "daily"},
    ),
    "S2_trailing10_top5": (
        "10-day trailing percentile, up to 5 entries/day, regime caps.",
        {"entry_mode": "top_n", "entry_top_n": 5, "rank_by": "trailing"},
    ),
    "S3_prob_threshold_5pos": (
        "Calibrated P(>30%) >= 0.30 entry gate, fixed 5-position cap.",
        {"entry_mode": "top_n", "entry_top_n": 5, "rank_by": "prob_elite",
         "min_prob_elite": 0.30, "regime_max_pos": {0: 0, 1: 5, 2: 5, 3: 5, 4: 5}},
    ),
    "S4_trailing20_regime_aware": (
        "20-day trailing percentile + min_prob_elite=0.25.",
        {"entry_mode": "top_n", "entry_top_n": 5, "rank_by": "trailing", "min_prob_elite": 0.25},
    ),
    "S5_hybrid_persistent": (
        "Persistence-gated entry (top-30% trailing rank, 3 of last 5 days), 8-cap, 10d min hold.",
        {"entry_mode": "top_n", "entry_top_n": 8, "rank_by": "trailing",
         "regime_max_pos": {0: 0, 1: 8, 2: 8, 3: 8, 4: 8}, "persistence_window_days": 5,
         "persistence_min_count": 3, "persistence_threshold": 0.7, "min_hold_days": 10},
    ),
}
for _name, (_desc, _kw) in _S_ARRAY.items():
    _register(StrategyDef(name=_name, signal="binary", strategy_kwargs=_kw,
                          description=_desc, status="baseline"))


def get(name: str) -> StrategyDef:
    if name not in STRATEGIES:
        raise KeyError(f"Unknown strategy {name!r}. Known: {sorted(STRATEGIES)}")
    return STRATEGIES[name]


def by_status(status: Status) -> List[StrategyDef]:
    return [d for d in STRATEGIES.values() if d.status == status]


if __name__ == "__main__":
    # ponytail: self-check — round-trip the champion fingerprint + registry sanity.
    champ = get("champion")
    assert champ.fingerprint == "E1.d0_X1.sl15_Xt.t1_10_X3.sma50_S0.top5", champ.fingerprint
    rt = parse_fingerprint(champ.fingerprint)
    for k in ("max_stop_pct", "min_target1_pct", "sma_exit_independent", "entry_top_n"):
        assert rt[k] == champ.strategy_kwargs[k], (k, rt[k], champ.strategy_kwargs[k])
    assert get("e1_seed").fingerprint == "E1.d0_X1.sl10_X3.sma50_S0.top5", get("e1_seed").fingerprint
    assert "S1_baseline_top3" in STRATEGIES and len(by_status("baseline")) >= 6
    print(f"OK — {len(STRATEGIES)} strategies. champion = {champ.fingerprint}")
