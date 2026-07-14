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

# Human glossary for the fingerprint families — rendered as a table in the dashboard
# so a reader can decode `E1.d0_X1.sl15_Xt.t1_10_X3.sma50_S0.top5` without the code.
KNOB_GLOSSARY: Dict[str, str] = {
    "E1": "Entry — immediate: buy on the day the name qualifies (delay 0).",
    "E2": "Entry — delayed N days: wait N sessions, enter only if still in the join-return band.",
    "X1": "Stop — whole-position hard stop at the given % (wider-of ATR/%; e.g. sl15 = 15%).",
    "Xt": "Take-profit — tranche T1 target at +N% (e.g. t1_10 = trim at +10%).",
    "X3": "Exit — decoupled SMA trend cross: close any open position on an SMA-N break (e.g. sma50).",
    "S0": "Selection — top-N daily by prob_elite (e.g. top5 = 5 highest-scored names/day).",
    "skip": "Selection — skip the top-K names each day (skip2 = drop the 2 hottest, take the next N).",
}


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
    # No Xt component when tranches are disabled (R3 trail-only arms) — the
    # fingerprint must not imply a take-profit the strategy won't take.
    if "min_target1_pct" in kwargs and not kwargs.get("disable_tranches"):
        parts.append(f"Xt.t1_{round(kwargs['min_target1_pct'] * 100)}")
    if kwargs.get("sma_exit_independent") and "sma_exit_period" in kwargs:
        parts.append(f"X3.sma{kwargs['sma_exit_period']}")
    # Rising trail from entry (R3b). Emit-only — no parse round-trip (research knob,
    # arms are built from kwargs not this fingerprint); keeps trail arms distinct.
    if kwargs.get("trail_from_entry_atr"):
        parts.append(f"Xtr.e{round(kwargs['trail_from_entry_atr'] * 10)}")
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


def _trail_only(base: Dict[str, Any]) -> Dict[str, Any]:
    # R3 tail-harvesting exit: disable the tranche take-profit entirely so the
    # runner breathes to full excursion. NB zeroing the target legs does NOT work
    # — target1 = max(price+atr*mult, price*(1+pct)) is always >= entry, so zeros
    # fire T1 at the entry price. disable_tranches is the only correct off-switch.
    # With no tranche sold, update_stops never trails (it gates on tranche1_sold)
    # → runner held by the fixed initial stop + independent SMA trend exit.
    return {**base, "disable_tranches": True,
            "sma_exit_independent": True, "sma_exit_period": 50}


# --- the registry -------------------------------------------------------------

STRATEGIES: Dict[str, StrategyDef] = {}


def _register(d: StrategyDef) -> None:
    STRATEGIES[d.name] = d


_register(StrategyDef(
    name="champion",
    signal="binary",
    strategy_kwargs=_champion_kwargs(),
    description="OOS-gated tranche champion (2026-07-05): 15% stop x +10% T1, decoupled SMA50, "
                "top-5. Demoted to candidate 2026-07-10 — champion_trail_spygate superseded it "
                "(R3 trail +0.21, deploy-gate re-confirm all-metric win).",
    status="candidate",
))

_register(StrategyDef(
    name="champion_spygate",
    signal="binary",
    # Same config as champion; the SPY-200d deploy gate is window-dependent so the
    # {date->bool} dict is injected at run time (run_starttime_sweep), not baked here.
    strategy_kwargs=_champion_kwargs(),
    description="Champion + SPY-200d ex-ante deploy gate (Thread E Q15): block new "
                "entries when SPY < 200d SMA. Gate dict injected per-window.",
    status="candidate",
))

_register(StrategyDef(
    name="champion_gated",
    signal="binary_gated",
    strategy_kwargs=_champion_kwargs(),
    description="Champion exits on the SEPA-gated FULL-SPAN cache (2003-2026) — the "
                "incumbent arm for the m01a M4 cone (post gate-fix population).",
    status="candidate",
))

_register(StrategyDef(
    name="rs_tail",
    signal="rs",
    # min_prob_elite here = per-date RS percentile floor over the trend_ok panel
    # (top decile), NOT a model probability — the m01a M3 verdict shipped the
    # one-column RS rule (ML tied it). Exits/slots identical to champion.
    strategy_kwargs={**_champion_kwargs(), "min_prob_elite": 0.90},
    description="m01a challenger: top-decile RS_Universe_Rank selection on the trend_ok "
                "panel x breakout trigger x champion exits (no model).",
    status="candidate",
))

_register(StrategyDef(
    name="rs_tail_trail",
    signal="rs",
    # R3 arm C — THE test: RS-tail selection (top-decile RS on the trend_ok panel)
    # x tail-harvesting exit (no tranches, runner exits on SMA50 break / initial
    # stop). The one pair M4 left un-run. Isolates 'remove profit-taking' as the
    # single change vs rs_tail (arm B).
    strategy_kwargs=_trail_only({**_champion_kwargs(), "min_prob_elite": 0.90}),
    description="R3-C: top-decile RS selection x trend-exit-only (no tranche TP, SMA50 "
                "trend exit). Tests whether removing tranche truncation converts the tail.",
    status="candidate",
))

_register(StrategyDef(
    name="champion_trail",
    signal="binary_gated",
    # R3 arm D — control: champion selection x the same tail-harvesting exit.
    # Isolates the exit main effect from the selection x exit interaction: if D>A
    # but C is no better than B's tranche->trail lift, the trail helps ANY
    # selection and the selection question stays closed (meta-plan R3 branch 2).
    strategy_kwargs=_trail_only(_champion_kwargs()),
    description="R3-D: champion selection x trend-exit-only (no tranche TP, SMA50 trend "
                "exit) on the SEPA-gated full-span cache. Control for the exit main effect.",
    status="candidate",
))

# R3b — rising-trail-from-entry: champion selection (the R3 winner) x tail-harvesting
# exit WITH a stop that ratchets up from the first bar (trail_from_entry_atr), to
# protect the median path champion_trail bled (R3 §mechanism). Ex-ante tight/wide
# pair, no post-hoc sweeping. SMA50 trend exit still active as the trend backstop.
# R3 deploy-gate re-confirm: champion_trail (R3 arm D, the +0.21 winner) + the
# SPY-200d ex-ante gate that M4 confirmed on the tranche exit. Tests whether the
# gate stacks additively on the trail exit the same way it did on tranche. Gate
# dict is window-dependent → injected per-cell in run_starttime_sweep (see the
# spy_deploy_gate sentinel), not baked here (same pattern as champion_spygate).
_register(StrategyDef(
    name="champion_trail_spygate",
    signal="binary_gated",
    strategy_kwargs={**_trail_only(_champion_kwargs()), "spy_deploy_gate": {}},
    description="CHAMPION (2026-07-10): champion selection x trend-exit-only (R3 arm D, trail) + "
                "SPY-200d deploy gate. C3-validated all-metric win over the tranche champion "
                "(floor +0.68, median +0.29, %neg -5pp, era-robust). Gate dict injected per-window.",
    status="champion",
))

# Thread L (2026-07-13) — binary-vs-4class confirm ON THE CHAMPION TRAIL EXIT.
# Same deployment config as the champion (trail + SPY-200d gate), but selection runs
# the 4-class PROD prototype (prob_class_3) instead of binary. Gate = 0.60 (NOT the
# binary 0.15: prob_class_3 lives on a different scale — median 0.24, max 0.81 — so
# 0.60 is a deliberate ~96th-pctile HIGH-CONVICTION gate, tight capacity by design).
# The binary champion cone (median 0.76) is the A/B reference. Caveat carried in the
# verdict: this compares each model at its OWN gate, not a shared absolute cut.
_register(StrategyDef(
    name="champion_trail_spygate_4cls",
    signal="proto_cali_gated",
    strategy_kwargs={**_trail_only(_champion_kwargs()),
                     "spy_deploy_gate": {}, "min_prob_elite": 0.60},
    description="Thread-L confirm: champion trail-exit + SPY-200d gate, but 4-class prod "
                "prototype selection @ gate 0.60 (high-conviction, prob_class_3 scale). "
                "A/B vs the binary champion_trail_spygate cone.",
    status="candidate",
))

# Thread J Q46 — capacity: the Q44 rotation anatomy priced the no_slots queue at
# near-book quality (fwd100 +5.7% vs +6.4%), so slot COUNT is the honest capacity
# lever. ONE ex-ante arm (10 slots @ 10% sizing, same exits/gate/pool) — no sweep,
# cone-fitting guard. NOT the closed Q14 (same-day top-10 widening): this deepens
# the book ACROSS days, drawing from the queue.
# Gate-sensitivity arms (2026-07-11) — the champion at a TIGHTER calibrated prob_elite
# floor. The 0.15 base is the model's ~coin-flip line; a higher floor refuses the
# 'best-of-a-bad-lot' famine-day entries (0.20 removes ~20% of entries, 0.25 ~26%,
# 0.30 ~76%). RESULT (verdicts/2026-07-11_prob_elite_gate_sensitivity.md, OPEN): raising
# the gate is a VARIANCE knob — 0.15 wins the median-Sharpe cone (0.59 vs 0.46/0.51/0.35);
# higher gates buy floor/%neg, cost median/tail (EDA's label-tail is discarded by the exit).
# g0.25 is a defensive-variant candidate only; champion stays at 0.15. Kept for replication.
# Everything else IS the champion — only min_prob_elite changes.
for _gate in (0.20, 0.25, 0.30):
    _register(StrategyDef(
        name=f"champion_trail_spygate_g{round(_gate * 100)}",
        signal="binary_gated",
        strategy_kwargs={**_trail_only(_champion_kwargs()),
                         "spy_deploy_gate": {}, "min_prob_elite": _gate},
        description=f"Gate-sensitivity (OPEN): champion_trail_spygate at min_prob_elite={_gate} "
                    f"(base 0.15). Variance knob — 0.15 wins median-Sharpe cone; higher = "
                    f"floor/%neg up, median/tail down. See gate_sensitivity verdict.",
        status="candidate",
    ))

# Earnings-proximity overlay (2026-07-13, Thread M §3 IMMEDIATE). Champion trail +
# SPY-200d gate + block entry / force-exit within 5 calendar days of a scheduled
# earnings print (Minervini: never hold a binary gap you can't stop out of; the 15%
# stop understates gap loss). Calendar {ticker->dates} is window-independent →
# injected once in run_starttime_sweep (earnings_calendar sentinel = None). Headline
# arm force-exits full (frac=1.0); the frac/min_ret knobs exist for trim variants.
_register(StrategyDef(
    name="champion_trail_spygate_earn5",
    signal="binary_gated",
    strategy_kwargs={**_trail_only(_champion_kwargs()), "spy_deploy_gate": {},
                     "earnings_calendar": None, "earnings_blackout_days": 5,
                     "earnings_exit_frac": 1.0},
    description="Earnings-proximity overlay: champion_trail_spygate + block entry / "
                "force-exit within 5 days of a scheduled earnings print. Falsifiable "
                "on the start-time cone vs champion_trail_spygate (floor-lift test).",
    status="candidate",
))

# Portfolio-level DD circuit breaker (2026-07-13, Thread M §1.1; Elder, *Trading
# for a Living*). Champion trail + SPY-200d gate + book-level brake: when the book's
# peak-to-trough DD hits 6%, halt NEW entries until equity recovers within 2% of the
# high-water mark (open positions & exits untouched). Distinct from the per-name stop
# (caps one trade) and the SPY gate (caps by market trend) — this halts the SEQUENCE
# of failing entries the gate lets through in chop (§0.3). Falsifiable on the cone:
# does it lift the FLOOR without killing the median (the recurring variance test)?
_register(StrategyDef(
    name="champion_trail_spygate_ddbrake6",
    signal="binary_gated",
    strategy_kwargs={**_trail_only(_champion_kwargs()), "spy_deploy_gate": {},
                     "dd_breaker_pct": 0.06, "dd_breaker_release_pct": 0.02},
    description="DD circuit breaker: champion_trail_spygate + book-level brake — halt "
                "new entries when book DD hits 6%, re-arm within 2% of peak (Elder). "
                "Floor-lift test on the start-time cone vs champion_trail_spygate.",
    status="candidate",
))

# Trip-threshold sweep (10/15/20/30%): looser brakes fire only on deeper bleeds.
# Maps the full threshold curve to settle threshold-vs-mechanism for the 6%
# rejection (RESEARCH_LOG Q67). All differ from ddbrake6 only by dd_breaker_pct.
for _pct in (0.10, 0.15, 0.20, 0.30):
    _register(StrategyDef(
        name=f"champion_trail_spygate_ddbrake{int(_pct*100)}",
        signal="binary_gated",
        strategy_kwargs={**_trail_only(_champion_kwargs()), "spy_deploy_gate": {},
                         "dd_breaker_pct": _pct, "dd_breaker_release_pct": 0.02},
        description=f"DD circuit breaker, {int(_pct*100)}% trip variant of "
                    "champion_trail_spygate_ddbrake6 — threshold-vs-mechanism sweep.",
        status="candidate",
    ))

_register(StrategyDef(
    name="champion_trail_spygate_n10",
    signal="binary_gated",
    strategy_kwargs={**_trail_only({**_base_kwargs(10), "max_stop_pct": 0.15,
                                    "min_target1_pct": 0.10}), "spy_deploy_gate": {}},
    description="Q46 capacity arm: champion_trail_spygate at 10 slots / 10% sizing. "
                "Tests whether doubling the book dilutes (queue quality says it shouldn't).",
    status="candidate",
))

# Thread J Q45 — temporal breadth: identical book (5 slots, 20% sizing, trail exit,
# SPY-200d gate) but at most ONE new entry per day (top-1 by prob_elite). Staggers the
# fill across days instead of same-day top-5: tests whether entry-cadence diversification
# beats the instant fill on the start-date cone. Pool/exits/sizing unchanged.
_register(StrategyDef(
    name="champion_trail_spygate_top1",
    signal="binary_gated",
    strategy_kwargs={**_trail_only(_champion_kwargs()), "spy_deploy_gate": {},
                     "entry_top_n": 1},
    description="Q45 temporal-breadth arm: champion_trail_spygate with max 1 new position "
                "per day (top-1 by score). Same 5-slot book — only the entry cadence changes.",
    status="candidate",
))

_register(StrategyDef(
    name="champion_trail_e25",
    signal="binary_gated",
    strategy_kwargs={**_trail_only(_champion_kwargs()), "trail_from_entry_atr": 2.5},
    description="R3b-wide: champion x trend-exit + 2.5xATR rising trail from entry. "
                "Lets the runner breathe while ratcheting the stop up.",
    status="candidate",
))

_register(StrategyDef(
    name="champion_trail_e15",
    signal="binary_gated",
    strategy_kwargs={**_trail_only(_champion_kwargs()), "trail_from_entry_atr": 1.5},
    description="R3b-tight: champion x trend-exit + 1.5xATR rising trail from entry. "
                "Protects the median path harder; likelier to clip the tail.",
    status="candidate",
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
    # R3 trail arms: tranches OFF, no Xt in fingerprint, and structurally distinct
    # from their tranche partners (the M4 no-op trap — guard it here).
    for trail, base in (("rs_tail_trail", "rs_tail"), ("champion_trail", "champion_gated")):
        t = get(trail)
        assert t.strategy_kwargs.get("disable_tranches") is True, trail
        assert "Xt" not in t.fingerprint, t.fingerprint
        assert t.strategy_kwargs != get(base).strategy_kwargs, f"{trail} == {base} (no-op!)"
    # champion_trail_spygate = champion_trail + gate sentinel ONLY (trail preserved).
    cts = get("champion_trail_spygate")
    assert cts.strategy_kwargs.get("disable_tranches") is True, "spygate arm lost the trail"
    assert "spy_deploy_gate" in cts.strategy_kwargs, "gate sentinel missing"
    assert {k: v for k, v in cts.strategy_kwargs.items() if k != "spy_deploy_gate"} \
        == get("champion_trail").strategy_kwargs, "spygate arm differs from champion_trail beyond the gate"
    # Q45 drip arm = champion_trail_spygate with ONLY the entry cadence changed.
    top1 = get("champion_trail_spygate_top1")
    assert top1.strategy_kwargs["entry_top_n"] == 1 and \
        top1.strategy_kwargs["regime_max_pos"][1] == 5, "top1 arm must keep the 5-slot book"
    _strip = lambda kw: {k: v for k, v in kw.items() if k != "entry_top_n"}
    assert _strip(top1.strategy_kwargs) == _strip(cts.strategy_kwargs), \
        "top1 arm differs from champion beyond entry_top_n"
    # Thread-L 4-class arm = binary champion config with signal + gate swapped ONLY.
    fourc = get("champion_trail_spygate_4cls")
    assert fourc.signal == "proto_cali_gated" and fourc.strategy_kwargs["min_prob_elite"] == 0.60, fourc
    _strip_gate = lambda kw: {k: v for k, v in kw.items() if k != "min_prob_elite"}
    assert _strip_gate(fourc.strategy_kwargs) == _strip_gate(cts.strategy_kwargs), \
        "4cls arm differs from champion beyond the gate"
    # Earnings arm = champion_trail_spygate + the earnings overlay ONLY.
    earn = get("champion_trail_spygate_earn5")
    assert earn.strategy_kwargs["earnings_blackout_days"] == 5, earn
    assert earn.strategy_kwargs.get("earnings_calendar") is None, "calendar must be a run-time sentinel"
    _strip_earn = lambda kw: {k: v for k, v in kw.items()
                              if k not in ("earnings_calendar", "earnings_blackout_days", "earnings_exit_frac")}
    assert _strip_earn(earn.strategy_kwargs) == cts.strategy_kwargs, \
        "earn5 arm differs from champion_trail_spygate beyond the earnings overlay"
    # DD-breaker arm = champion_trail_spygate + the book-level brake ONLY.
    ddb = get("champion_trail_spygate_ddbrake6")
    assert ddb.strategy_kwargs["dd_breaker_pct"] == 0.06, ddb
    _strip_ddb = lambda kw: {k: v for k, v in kw.items()
                             if k not in ("dd_breaker_pct", "dd_breaker_release_pct")}
    assert _strip_ddb(ddb.strategy_kwargs) == cts.strategy_kwargs, \
        "ddbrake6 arm differs from champion_trail_spygate beyond the DD breaker"
    print(f"OK — {len(STRATEGIES)} strategies. champion = {champ.fingerprint}")
