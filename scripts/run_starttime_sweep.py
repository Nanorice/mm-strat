"""Start-time / horizon sensitivity sweep for a LOCKED registry strategy.

Answers: "how much does the day I start matter?" A robust edge gives a tight
return spread across start dates; a fragile / path-dependent one swings wildly.

Same locked config, many (start, end) windows — a job list over the existing
population_runner. Three grids:
    rolling   fixed horizon, start walked forward every `step` (start-luck at
              constant holding time)
    horizon   fixed start, growing end (how the edge accumulates / decays)
    matrix    every start x every horizon (the full cross)

Cells are compared apples-to-apples via ann_return / sharpe / max_drawdown
(sharpe_from_returns already annualizes) — NEVER raw total_return, which a long
window inflates over a short one.

Scores come from the same cache as run_strategy_confirm, so the window is bounded
by the cache span (binary: 2021..2026), not literally today.

Usage:
    python scripts/run_starttime_sweep.py --strategy champion --grid rolling
    python scripts/run_starttime_sweep.py --strategy champion --grid matrix --workers 4
    python scripts/run_starttime_sweep.py --strategy champion --grid rolling --smoke
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

from src.backtest import strategy_registry as reg
from src.backtest.macro_sizer import spy_above_200d
from src.backtest.population_runner import Job, run_arm
from scripts.run_strategy_confirm import _load_scores, DB_PATH, MODEL
from scripts.run_strategy_wfo import sharpe_from_returns

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

OUT_ROOT = REPO_ROOT / "data" / "selection_sweep" / "starttime"

# Cache span for the binary champion — windows can't exceed this.
CACHE_START, CACHE_END = "2021-01-01", "2026-05-31"


def _month_starts(first: str, last: str, step_months: int) -> List[pd.Timestamp]:
    """Month-anchored start dates from `first` to `last` inclusive, every step."""
    return list(pd.date_range(first, last, freq=pd.DateOffset(months=step_months)))


def build_cells(grid: str, cache_start: str, cache_end: str,
                step_months: int = 1) -> List[Tuple[str, str, str]]:
    """(cell_id, start, end) triples for the chosen grid. Every end is clamped to
    the cache span, so a horizon that would run off the end is silently shortened
    (its shorter n_days is visible in the report — annualized metrics stay fair)."""
    end_ts = pd.Timestamp(cache_end)
    horizons_m = [3, 6, 12, 24]  # months

    def clamp(s: pd.Timestamp, months: int) -> str:
        return min(s + pd.DateOffset(months=months), end_ts).strftime("%Y-%m-%d")

    cells: List[Tuple[str, str, str]] = []
    if grid == "rolling":
        # fixed 12m horizon, start every `step_months` across all but the last year
        starts = _month_starts(cache_start, (end_ts - pd.DateOffset(months=12)).strftime("%Y-%m-%d"), step_months)
        for s in starts:
            cells.append((f"r_{s:%Y%m}_h12", s.strftime("%Y-%m-%d"), clamp(s, 12)))
    elif grid == "horizon":
        # fixed start (cache start), growing end
        for h in horizons_m + [36, 48, 60]:
            cells.append((f"h_start_h{h}", cache_start, clamp(pd.Timestamp(cache_start), h)))
    elif grid == "matrix":
        # every quarter-start x every horizon
        starts = _month_starts(cache_start, (end_ts - pd.DateOffset(months=3)).strftime("%Y-%m-%d"), 3)
        for s in starts:
            for h in horizons_m:
                cells.append((f"m_{s:%Y%m}_h{h}", s.strftime("%Y-%m-%d"), clamp(s, h)))
    else:
        raise ValueError(f"Unknown grid {grid!r}")
    return cells


def _cell_job(d: reg.StrategyDef, cell_id: str, start: str, end: str) -> Job:
    """One (start,end) cell -> a population Job. Scores lazy-loaded IN the worker
    via a picklable partial (windowed to the cell) so parallel workers stay light.

    For `champion_spygate` the SPY-200d deploy gate (window-dependent, so not baked
    into the registry) is injected here as a {date->bool} dict — small, picklable."""
    kwargs = dict(d.strategy_kwargs)
    if d.name == "champion_spygate":
        kwargs["spy_deploy_gate"] = spy_above_200d(start, end, str(DB_PATH))
    return Job(
        id=cell_id, description=f"{d.name} {start}..{end}", signal=d.signal,
        model="/".join(MODEL[d.signal]), strategy_kwargs=kwargs,
        score_loader=partial(_load_scores, d.signal, start, end),
    )


def _cell_metrics(run_dir: Path) -> Dict[str, Any]:
    """Fair, window-length-invariant metrics from the persisted equity curve."""
    eq_path = run_dir / "equity.parquet"
    if not eq_path.exists():
        return {"sharpe": float("nan"), "ann_return": float("nan"),
                "max_drawdown": float("nan"), "total_return": float("nan"), "n_days": 0}
    eq = pd.read_parquet(eq_path)
    rets = eq["value"].pct_change().dropna()
    return sharpe_from_returns(rets)


def _run_cell(cid: str, s: str, e: str, job: Job, initial_cash: float,
              out_dir: Path) -> Dict[str, Any]:
    """One cell, module-level so ProcessPoolExecutor can pickle it.

    Resume: a cell whose equity.parquet already exists is not re-run — delete the
    cell dir to force. Cheap checkpointing for multi-hour full-span sweeps."""
    if not (out_dir / cid / "equity.parquet").exists():
        run_arm(job, s, e, initial_cash, out_dir, str(DB_PATH))
    m = _cell_metrics(out_dir / cid)
    return {"cell": cid, "start": s, "end": e, **m}


def run_sweep(strategy: str, grid: str, initial_cash: float, workers: int,
              smoke: bool, cache_start: str = CACHE_START, cache_end: str = CACHE_END,
              step_months: int = 1) -> List[Dict[str, Any]]:
    d = reg.get(strategy)
    cells = build_cells(grid, cache_start, cache_end, step_months)
    if smoke:
        cells = cells[:2]
        workers = 1
    out_dir = OUT_ROOT / strategy / grid
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("START-TIME SWEEP %s (%s) grid=%s: %d cells, workers=%d",
                d.name, d.fingerprint, grid, len(cells), workers)

    rows: List[Dict[str, Any]] = []
    jobs = [(cid, s, e, _cell_job(d, cid, s, e)) for cid, s, e in cells]

    if workers <= 1:
        for cid, s, e, job in jobs:
            logger.info("── %s  %s..%s", cid, s, e)
            rows.append(_run_cell(cid, s, e, job, initial_cash, out_dir))
    else:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_run_cell, cid, s, e, job, initial_cash, out_dir): cid
                    for cid, s, e, job in jobs}
            for fut in as_completed(futs):
                try:
                    rows.append(fut.result())
                    logger.info("✅ %s", futs[fut])
                except Exception as ex_err:
                    logger.exception("❌ cell %s failed: %s", futs[fut], ex_err)
                    rows.append({"cell": futs[fut], "error": str(ex_err)})

    rows.sort(key=lambda r: r.get("start", ""))
    _write_report(d, grid, rows, out_dir)
    return rows


def _write_report(d: reg.StrategyDef, grid: str, rows: List[Dict[str, Any]],
                  out_dir: Path) -> None:
    (out_dir / "summary.json").write_text(json.dumps(
        {"strategy": d.name, "fingerprint": d.fingerprint, "grid": grid, "cells": rows},
        indent=2, default=float))

    valid = [r for r in rows if r.get("sharpe") == r.get("sharpe")]  # drop NaN
    lines = [f"# Start-time sweep — {d.name} (`{d.fingerprint}`) — grid `{grid}`", ""]
    if valid:
        anns = pd.Series([r["ann_return"] for r in valid])
        shs = pd.Series([r["sharpe"] for r in valid])
        lines += [
            f"**{len(valid)} cells.** ann_return spread: "
            f"{anns.min():.1%} .. {anns.max():.1%} (median {anns.median():.1%}, "
            f"IQR {anns.quantile(.75) - anns.quantile(.25):.1%}). "
            f"Sharpe spread: {shs.min():.2f} .. {shs.max():.2f} (median {shs.median():.2f}).",
            "",
            "> Wide ann_return spread across start dates = the edge is start-time / "
            "path dependent. Tight spread = robust to when you begin.", "",
        ]
    lines += ["| cell | start | end | days | ann_ret | sharpe | maxDD |",
              "|---|---|---|--:|--:|--:|--:|"]
    for r in rows:
        if "error" in r:
            lines.append(f"| {r['cell']} | — | — | — | ERR | — | — |")
            continue
        lines.append(
            f"| {r['cell']} | {r['start']} | {r['end']} | {r['n_days']} | "
            f"{r.get('ann_return', float('nan')):.1%} | {r.get('sharpe', float('nan')):.2f} | "
            f"{r.get('max_drawdown', float('nan')):.1%} |")
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s", out_dir / "report.md")


def _cone_stats(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    """The distribution summary that IS the cone: floor, spread, %negative — not mean."""
    shs = pd.Series([r["sharpe"] for r in rows if r.get("sharpe") == r.get("sharpe")])
    if shs.empty:
        return {"n": 0}
    return {
        "n": int(shs.size), "min": float(shs.min()), "p25": float(shs.quantile(.25)),
        "median": float(shs.median()), "p75": float(shs.quantile(.75)), "max": float(shs.max()),
        "iqr": float(shs.quantile(.75) - shs.quantile(.25)), "std": float(shs.std()),
        "pct_neg": float((shs < 0).mean()),
    }


def compare_cone(grid: str, initial_cash: float, workers: int, smoke: bool) -> None:
    """Task (b): does the SPY-200d deploy gate SHRINK the start-date cone? Run the
    same rolling sweep with (champion_spygate) and without (champion) the gate;
    compare Sharpe DISTRIBUTIONS across start-months — floor / IQR / %neg, not mean."""
    off = run_sweep("champion", grid, initial_cash, workers, smoke)
    on = run_sweep("champion_spygate", grid, initial_cash, workers, smoke)
    s_off, s_on = _cone_stats(off), _cone_stats(on)
    out = OUT_ROOT / "spygate_compare"
    out.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# SPY-200d deploy gate — start-date cone comparison (grid `{grid}`)", "",
        "Same rolling start-month cone, champion config, gate OFF vs ON. The question "
        "is the DISTRIBUTION across start-months (floor, spread, %negative) — not the mean.", "",
        "| metric | gate OFF | gate ON | Δ |", "|---|--:|--:|--:|",
    ]
    for k, label in [("n", "cells"), ("min", "min Sharpe (floor)"), ("p25", "p25"),
                     ("median", "median"), ("p75", "p75"), ("max", "max"),
                     ("iqr", "IQR (spread)"), ("std", "std (spread)"), ("pct_neg", "% cells Sharpe<0")]:
        a, b = s_off.get(k, float("nan")), s_on.get(k, float("nan"))
        fmt = (lambda x: f"{x:.0f}") if k == "n" else ((lambda x: f"{x:.0%}") if k == "pct_neg" else (lambda x: f"{x:.2f}"))
        d = "" if k == "n" else fmt(b - a)
        lines.append(f"| {label} | {fmt(a)} | {fmt(b)} | {d} |")
    lines += ["",
              "> Cone SHRINKS if the gate raises the floor (min↑), narrows the spread "
              "(IQR↓/std↓), and cuts %negative — even if the median barely moves. That is "
              "the real M2-cone test: a distribution shrinker, not just a mean lifter."]
    (out / "cone_compare.md").write_text("\n".join(lines), encoding="utf-8")

    print("\n" + "=" * 70)
    print(f"SPY-200d CONE COMPARE — grid {grid}")
    print(f"  {'':<18}{'OFF':>10}{'ON':>10}{'Δ':>10}")
    for k in ("min", "median", "iqr", "std", "pct_neg"):
        a, b = s_off.get(k, float('nan')), s_on.get(k, float('nan'))
        print(f"  {k:<18}{a:>10.2f}{b:>10.2f}{b - a:>10.2f}")
    print("=" * 70)
    print(f"Artifacts: {out / 'cone_compare.md'}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Start-time / horizon sensitivity sweep")
    p.add_argument("--strategy", default="champion", help=f"Registry name. Known: {sorted(reg.STRATEGIES)}")
    p.add_argument("--grid", choices=["rolling", "horizon", "matrix"], default="rolling")
    p.add_argument("--initial-cash", type=float, default=25_000.0)
    p.add_argument("--workers", type=int, default=3, help="Parallel cells. Each loads a price universe — watch RAM.")
    p.add_argument("--smoke", action="store_true", help="First 2 cells, serial — smoke test before the full run.")
    p.add_argument("--cache-start", default=CACHE_START,
                   help="Sweep span start (bound it to the strategy's score-cache span; "
                        "binary_gated/rs arms span 2003-01-01..2026-05-22).")
    p.add_argument("--cache-end", default=CACHE_END)
    p.add_argument("--step-months", type=int, default=1,
                   help="Rolling-grid start spacing in months (3 = quarterly, for full-span sweeps).")
    p.add_argument("--compare-spygate", action="store_true",
                   help="Task (b): run champion vs champion_spygate on the same cone; "
                        "emit a Sharpe-DISTRIBUTION diff (floor/IQR/%neg, not mean).")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.compare_spygate:
        compare_cone(args.grid, args.initial_cash, args.workers, args.smoke)
        return
    rows = run_sweep(args.strategy, args.grid, args.initial_cash, args.workers, args.smoke,
                     cache_start=args.cache_start, cache_end=args.cache_end,
                     step_months=args.step_months)
    valid = [r for r in rows if r.get("sharpe") == r.get("sharpe")]
    print("\n" + "=" * 70)
    print(f"START-TIME SWEEP — {args.strategy} — grid {args.grid} — {len(valid)}/{len(rows)} cells ok")
    if valid:
        anns = pd.Series([r["ann_return"] for r in valid])
        print(f"  ann_return  min={anns.min():.1%}  median={anns.median():.1%}  max={anns.max():.1%}  "
              f"spread={anns.max() - anns.min():.1%}")
    print("=" * 70)


if __name__ == "__main__":
    main()
