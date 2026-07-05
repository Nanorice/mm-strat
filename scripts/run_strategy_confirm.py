"""BackTrader confirm of the fixed-vec selection sweep — parallel across arms.

The vectorized sweep (data/selection_sweep/summary_fixed.parquet) is a *relative*
screen. This runs the shortlisted arms through BackTrader — the fidelity engine
that enforces a real slot book, 3-tranche TP, and next-open fills — to get the
capital-honest verdict against the prior champion (binary E1, WFO OOS 0.84).

Parallelism: BackTrader is sequential *within* an arm (event loop, temporal
order — the fidelity we want). Arms are independent, so we fan out ACROSS arms
with a ProcessPoolExecutor: each worker runs one arm end-to-end. DuckDB is
read-only so concurrent price-feed reads are safe.

Population (5 arms) — see docs/session_logs/sprint_13/strategy_exploration_summary.md:
    binary  E1 top-5           — the incumbent (prior BackTrader champion / seed)
    proto   top-5              — signal-swap control at fixed N
    proto   top-10             — "hold wide", no skip (isolates the skip's effect)
    proto   skip-2 @ N=10      — THE vec winner (0.80 / +217% / -32% DD)
    proto   skip-2 @ N=8       — robustness of the skip across N

Usage:
    python scripts/run_strategy_confirm.py --start 2021-01-01 --end 2026-05-31
    python scripts/run_strategy_confirm.py --smoke   # 2024 only, serial, 1 arm
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

from src.backtest.runner import SEPABacktestRunner
from src.backtest.score_lookup import prototype_scores_to_contract
from src.backtest.strategy_registry import _base_kwargs
from src.backtest.population_runner import Job, run_population
from scripts.run_strategy_array import _render_comparison_md

DB_PATH = REPO_ROOT / "data" / "market_data.duckdb"
CACHE = {
    "binary": REPO_ROOT / "data" / "score_cache" / "binary_2021_2026.parquet",
    "proto_cali": REPO_ROOT / "data" / "score_cache" / "proto_cali_2021_2026.parquet",
}
MODEL = {  # for provenance in artifacts; scores come from cache, not re-scored
    "binary": ("m01_binary", "v1"),
    "proto_cali": ("m01_prototype_cali", "v1"),
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class Arm:
    id: str
    signal: str  # 'binary' | 'proto_cali'
    description: str
    strategy_kwargs: Dict[str, Any] = field(default_factory=dict)


# _base_kwargs now lives in src/backtest/strategy_registry.py (single source of
# truth): equal-weight slot book, top-N by prob_elite, decoupled SMA50, 10% stop.

POPULATION: List[Arm] = [
    Arm("A1_binary_top5", "binary", "SEED: binary E1 top-5 (prior BackTrader champion)",
        _base_kwargs(5)),
    Arm("A2_proto_top5", "proto_cali", "proto top-5 — signal swap at fixed N",
        _base_kwargs(5)),
    Arm("A3_proto_top10", "proto_cali", "proto top-10 — hold wide, no skip",
        _base_kwargs(10)),
    Arm("A4_proto_skip2_N10", "proto_cali", "VEC WINNER: proto skip-top-2, N=10",
        {**_base_kwargs(10), "selection_skip_top": 2}),
    Arm("A5_proto_skip2_N8", "proto_cali", "proto skip-top-2, N=8 — skip robustness",
        {**_base_kwargs(8), "selection_skip_top": 2}),
]


def _exit_grid() -> List[Arm]:
    """Exit grid off the champion (binary top-5, sl10/atr2, sma50 decoupled, tranche).

    Entry + selection axes are falsified for binary-E1 (delay/persistence/score-drop/
    wide-N/skip-on-binary all dead) — the untested territory is STOP + TAKE-PROFIT.
    Each arm is ONE knob off the champion so the table reads as a clean ablation.
    Tier 3 (stop×TP interaction) is defined AFTER these name the winners — it needs
    a WFO gate (joint tuning on one window overfits: IS 1.22 → OOS −0.17 precedent).
    """
    base = _base_kwargs(5)  # champion = A1
    G = lambda over: {**base, **over}
    arms = [
        Arm("G0_champion", "binary", "BASELINE champion: sl10 atr2 sma50 decoupled tranche", G({})),
        # --- Tier 1: STOP (X1 % floor + ATR mult; X4 = pure ATR) ---
        Arm("G_sl08", "binary", "T1 stop: tighter 8% floor", G({"max_stop_pct": 0.08})),
        Arm("G_sl12", "binary", "T1 stop: wider 12% floor", G({"max_stop_pct": 0.12})),
        Arm("G_sl15", "binary", "T1 stop: widest 15% floor", G({"max_stop_pct": 0.15})),
        Arm("G_atr2p5", "binary", "T1 stop: wider ATR 2.5", G({"atr_stop_mult": 2.5})),
        Arm("G_atr3", "binary", "T1 stop: widest ATR 3.0", G({"atr_stop_mult": 3.0})),
        # X4 pure-ATR: let ATR dominate. initial_stop=max(price-mult*ATR, price*(1-pct))
        # picks the TIGHTER (higher) stop, so max_stop_pct must be LOOSE (wide) — a
        # small pct is a tight CAP, not a floor (the −69% G7 bug). 0.30 = a wide net
        # that only fires on extreme ATR; ATR is the live stop otherwise.
        Arm("G_x4_atr2", "binary", "T1 X4 pure-ATR 2.0 (30% wide safety net)",
            G({"atr_stop_mult": 2.0, "max_stop_pct": 0.30})),
        Arm("G_x4_atr2p5", "binary", "T1 X4 pure-ATR 2.5 (30% wide safety net)",
            G({"atr_stop_mult": 2.5, "max_stop_pct": 0.30})),
        # --- Tier 2: TAKE-PROFIT (X3 SMA period; Xt tranche targets) ---
        Arm("G_sma20", "binary", "T2 TP: faster SMA20 trend exit", G({"sma_exit_period": 20})),
        Arm("G_sma100", "binary", "T2 TP: slower SMA100 trend exit", G({"sma_exit_period": 100})),
        Arm("G_tp_tight", "binary", "T2 TP: earlier T1 (+10%)", G({"min_target1_pct": 0.10})),
        Arm("G_tp_wide", "binary", "T2 TP: later T1 (+20%)", G({"min_target1_pct": 0.20})),
        Arm("G_tp_t1atr2", "binary", "T2 TP: tighter ATR target (2×)", G({"atr_target1_mult": 2.0})),
        Arm("G_tp_t1atr4", "binary", "T2 TP: wider ATR target (4×)", G({"atr_target1_mult": 4.0})),
        Arm("G_tp_gated", "binary", "T2 TP: tranche-GATED SMA (decoupled OFF)",
            G({"sma_exit_independent": False})),
        # SMA-only, no tranche: push targets unreachable so SMA trend break is the sole TP
        Arm("G_tp_notranche", "binary", "T2 TP: SMA-only, tranche disabled",
            G({"min_target1_pct": 10.0, "atr_target1_mult": 100.0})),
    ]
    return arms


def _tier3_grid() -> List[Arm]:
    """Tier 3: stop-width × TP-timing interaction, from the Tier 1/2 winners.

    Live axes only: stop ∈ {10%, 15%} × TP ∈ {champion-default, t1atr2, t1_tight}.
    ATR-mult excluded (Tier 1 proved it inert), X4 excluded (harness bug). 6 arms.
    CANDIDATE-ONLY: joint tuning on one window overfits — WFO-gate the winner.
    """
    base = _base_kwargs(5)
    G = lambda over: {**base, **over}
    tps = {
        "tpDflt": {},                         # champion TP (T1 = max(+15%, 3·ATR))
        "tpATR2": {"atr_target1_mult": 2.0},  # tighter ATR target (Tier2 #4, 0.79)
        "tpTight": {"min_target1_pct": 0.10}, # earlier T1 +10% (Tier2 #5, 0.76)
    }
    arms = []
    for sl_id, sl in {"sl10": 0.10, "sl15": 0.15}.items():
        for tp_id, tp in tps.items():
            arms.append(Arm(
                f"T3_{sl_id}_{tp_id}", "binary",
                f"Tier3 interaction: stop {sl:.0%} × TP {tp_id}",
                G({"max_stop_pct": sl, **tp}),
            ))
    return arms


def _all_arms() -> Dict[str, Arm]:
    """Every arm across every grid, keyed by id — for --wfo-gate lookup."""
    out: Dict[str, Arm] = {}
    for a in POPULATION + _exit_grid() + _tier3_grid():
        out[a.id] = a
    return out


def wfo_gate(arm: Arm, start: str, end: str, initial_cash: float,
             train_years: int, test_years: int, anchored: bool) -> Dict[str, Any]:
    """True out-of-sample gate on a FIXED config (no re-optimization).

    The existing run_strategy_wfo.py re-optimizes on the *vectorized* engine
    (no tranche TP / no wider-of stop) — it cannot gate a BackTrader exit config.
    This rolls folds, runs the LOCKED kwargs on each unseen test window in
    BackTrader, and stitches the OOS daily returns into one honest curve. A config
    that only wins in-sample (overfit) shows a large IS→OOS Sharpe drop here.
    """
    from scripts.run_strategy_wfo import make_folds, sharpe_from_returns
    folds = make_folds(start, end, pd.DateOffset(years=train_years),
                       pd.DateOffset(years=test_years), anchored)
    if not folds:
        raise SystemExit("No folds fit — shorten train/test spans.")

    scores_full = _load_scores(arm.signal, start, end)
    oos_slices, fold_recs = [], []
    for i, fold in enumerate(folds):
        ts, te = fold["test_start"], fold["test_end"]
        runner = SEPABacktestRunner(start_date=ts, end_date=te, initial_cash=initial_cash,
                                    db_path=str(DB_PATH), model_path=None)
        runner.setup(scores_df=scores_full, strategy_kwargs=arm.strategy_kwargs)
        runner.run()
        eq = runner.get_equity_curve_dataframe()
        if eq is None or eq.empty:
            continue
        rets = eq["value"].pct_change().dropna()
        stats = sharpe_from_returns(rets)
        fold_recs.append({"test": f"{ts}..{te}", **stats})
        logger.info("fold %d  test %s  OOS_sharpe=%.2f  ret=%.0f%%",
                    i, f"{ts}..{te}", stats["sharpe"], 100 * stats.get("total_return", 0))
        if len(rets):
            oos_slices.append(rets)

    stitched = pd.concat(oos_slices).sort_index() if oos_slices else pd.Series(dtype=float)
    agg = sharpe_from_returns(stitched)
    result = {"arm": arm.id, "config": arm.strategy_kwargs, "mode":
              "anchored" if anchored else "rolling", "aggregate_oos": agg, "folds": fold_recs}
    out_dir = REPO_ROOT / "data" / "selection_sweep" / "wfo_gate"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{arm.id}.json").write_text(json.dumps(result, indent=2, default=float))
    return result


def _load_scores(signal: str, start: str, end: str) -> pd.DataFrame:
    """Load cached scores (not re-scored) and adapt to the ScoreLookup contract."""
    cols = ["date", "ticker", "prob_elite", "calibrated_score"]
    df = pd.read_parquet(CACHE[signal], columns=cols)
    df["date"] = pd.to_datetime(df["date"])
    df = df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))]
    return prototype_scores_to_contract(df)


def _arm_to_job(arm: Arm, start: str, end: str) -> Job:
    """Arm -> population Job. Scores are lazy-loaded IN the worker via a picklable
    partial (not the in-hand frame) so parallel workers don't pickle a big frame."""
    return Job(
        id=arm.id, description=arm.description, signal=arm.signal,
        model="/".join(MODEL[arm.signal]), strategy_kwargs=arm.strategy_kwargs,
        score_loader=partial(_load_scores, arm.signal, start, end),
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="BackTrader confirm of the selection sweep")
    p.add_argument("--start", default="2021-01-01")
    p.add_argument("--end", default="2026-05-31")
    p.add_argument("--initial-cash", type=float, default=25_000.0)
    p.add_argument("--workers", type=int, default=3,
                   help="Parallel arms. Each loads a full price universe — watch RAM.")
    p.add_argument("--grid", choices=["confirm", "exit", "tier3"], default="confirm",
                   help="'confirm' = 5-arm signal population; 'exit' = stop+TP grid "
                        "off champion (Tiers 1+2); 'tier3' = stop×TP interaction.")
    p.add_argument("--arms", default="", help="Comma-separated arm ids (default: all)")
    p.add_argument("--smoke", action="store_true",
                   help="1 arm, 2024 window, serial — smoke test before the full run.")
    p.add_argument("--wfo-gate", default="",
                   help="Arm id to OOS-gate (fixed config, rolling BackTrader folds). "
                        "Overrides --grid; use --train-years/--test-years/--anchored.")
    p.add_argument("--train-years", type=int, default=2)
    p.add_argument("--test-years", type=int, default=1)
    p.add_argument("--anchored", action="store_true", help="Expanding train (default: rolling)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.wfo_gate:
        arm = _all_arms().get(args.wfo_gate)
        if arm is None:
            raise SystemExit(f"Unknown arm {args.wfo_gate}. Known: {sorted(_all_arms())}")
        logger.info("WFO-GATE %s (fixed config) — %d/%d train/test yrs, %s",
                    arm.id, args.train_years, args.test_years,
                    "anchored" if args.anchored else "rolling")
        r = wfo_gate(arm, args.start, args.end, args.initial_cash,
                     args.train_years, args.test_years, args.anchored)
        agg = r["aggregate_oos"]
        print("\n" + "=" * 70)
        print(f"WFO GATE — {arm.id}")
        print(f"  AGGREGATE OOS Sharpe={agg['sharpe']:.2f}  ret={agg.get('total_return', 0):.0%}  "
              f"maxDD={agg['max_drawdown']:.0%}  ({agg['n_days']} days, {len(r['folds'])} folds)")
        print("=" * 70)
        return

    pop = {"exit": _exit_grid, "tier3": _tier3_grid}.get(args.grid, lambda: POPULATION)()
    out_dir = (REPO_ROOT / "data" / "selection_sweep" /
               {"exit": "exit_grid", "tier3": "tier3_grid"}.get(args.grid, "backtrader_confirm"))
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.smoke:
        pop = [pop[0]]
        args.start, args.end, args.workers = "2024-01-01", "2024-12-31", 1
    elif args.arms:
        want = {a.strip() for a in args.arms.split(",")}
        pop = [a for a in pop if a.id in want]

    logger.info("Grid=%s: %d arms, workers=%d, window %s → %s",
                args.grid, len(pop), args.workers, args.start, args.end)

    jobs = [_arm_to_job(a, args.start, args.end) for a in pop]
    results = run_population(jobs, args.start, args.end, args.initial_cash,
                             out_dir, str(DB_PATH), workers=args.workers)

    (out_dir / "summary.json").write_text(json.dumps({
        "window": f"{args.start} → {args.end}",
        "initial_cash": args.initial_cash,
        "runs": results,
    }, indent=2, default=str))
    _render_comparison_md(
        summaries=results, output_path=out_dir / "comparison.md",
        window=f"{args.start} → {args.end}", model_label=f"{args.grid} grid",
    )
    logger.info("Wrote %s", out_dir / "comparison.md")


if __name__ == "__main__":
    main()
