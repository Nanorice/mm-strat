"""Fixed-config out-of-sample gate — the promotion gate for a registry strategy.

Rolls train/test folds, runs the LOCKED registry config on each unseen test
window in BackTrader (the fidelity engine — real slot book, 3-tranche TP,
next-open fills), and stitches the OOS daily returns into one honest curve. A
config that only wins in-sample shows a large IS->OOS Sharpe drop here.

This is NOT run_strategy_wfo.py: that re-OPTIMIZES params/fold on the vectorized
engine (no tranche TP) — a *search*. This gates a *fixed* config for promotion.
The two are complementary; don't merge them.

Usage:
    python scripts/run_oos_gate.py --strategy champion
    python scripts/run_oos_gate.py --strategy champion --anchored --train-years 3 --test-years 1
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

from src.backtest.runner import SEPABacktestRunner
from src.backtest import strategy_registry as reg
from scripts.run_strategy_confirm import _load_scores, DB_PATH

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

OUT_DIR = REPO_ROOT / "data" / "selection_sweep" / "wfo_gate"


def oos_gate(d: reg.StrategyDef, start: str, end: str, initial_cash: float,
             train_years: int, test_years: int, anchored: bool) -> Dict[str, Any]:
    from scripts.run_strategy_wfo import make_folds, sharpe_from_returns

    folds = make_folds(start, end, pd.DateOffset(years=train_years),
                       pd.DateOffset(years=test_years), anchored)
    if not folds:
        raise SystemExit("No folds fit — shorten train/test spans.")

    scores_full = _load_scores(d.signal, start, end)
    oos_slices, fold_recs = [], []
    for i, fold in enumerate(folds):
        ts, te = fold["test_start"], fold["test_end"]
        runner = SEPABacktestRunner(start_date=ts, end_date=te, initial_cash=initial_cash,
                                    db_path=str(DB_PATH), model_path=None)
        runner.setup(scores_df=scores_full, strategy_kwargs=d.strategy_kwargs)
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
    result = {"strategy": d.name, "fingerprint": d.fingerprint, "config": d.strategy_kwargs,
              "mode": "anchored" if anchored else "rolling",
              "aggregate_oos": agg, "folds": fold_recs}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{d.name}.json").write_text(json.dumps(result, indent=2, default=float))
    return result


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fixed-config OOS gate for a registry strategy")
    p.add_argument("--strategy", required=True, help=f"Registry name. Known: {sorted(reg.STRATEGIES)}")
    p.add_argument("--start", default="2021-01-01")
    p.add_argument("--end", default="2026-05-31")
    p.add_argument("--initial-cash", type=float, default=25_000.0)
    p.add_argument("--train-years", type=int, default=2)
    p.add_argument("--test-years", type=int, default=1)
    p.add_argument("--anchored", action="store_true", help="Expanding train (default: rolling)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    d = reg.get(args.strategy)
    logger.info("OOS-GATE %s (%s) — %d/%d train/test yrs, %s", d.name, d.fingerprint,
                args.train_years, args.test_years, "anchored" if args.anchored else "rolling")
    r = oos_gate(d, args.start, args.end, args.initial_cash,
                 args.train_years, args.test_years, args.anchored)
    agg = r["aggregate_oos"]
    print("\n" + "=" * 70)
    print(f"OOS GATE — {d.name}  ({d.fingerprint})")
    print(f"  AGGREGATE OOS Sharpe={agg['sharpe']:.2f}  ret={agg.get('total_return', 0):.0%}  "
          f"maxDD={agg['max_drawdown']:.0%}  ({agg['n_days']} days, {len(r['folds'])} folds)")
    print("=" * 70)


if __name__ == "__main__":
    main()
