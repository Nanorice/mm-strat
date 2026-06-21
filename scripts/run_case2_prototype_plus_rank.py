"""
Case 2 — m01_prototype (selection) + m01_rank (entry-timing gate).

m01_prototype defines the eligible universe (prob_elite floor) and provides the
score floor, exactly as in Case 1. m01_rank's daily cross-sectional percentile
REPLACES the ranking key the SEPA engine sorts entries by — so among the names
the prototype deems good, m01_rank decides WHICH to actually enter each day
(the breakout-pullback timing mandate, design note s8 test 0).

No strategy code change: we overwrite `trailing_pct` in the scores_df with
m01_rank's daily percentile and run with rank_by='trailing'. Compared head-to-
head with Case 1 (same engine, same window), the delta isolates the timing
layer's contribution.

Usage:
    python scripts/run_case2_prototype_plus_rank.py --start 2020-01-01 --end 2024-12-31
"""

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest import UniverseScorer, SEPABacktestRunner
from scripts.m01_rank_scorer import train_and_score
from scripts.run_case1_prototype_standalone import yearly_breakdown

PROTOTYPE_MODEL = "models/m01_prototype_2003_2026/v1/model.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--warmup-start", default="2019-01-01",
                    help="Feed/score from here so SMA(50) is ready by --start "
                         "(see Case 1 prenext stall). Warmup year is not evaluated.")
    ap.add_argument("--cash", type=float, default=100_000)
    ap.add_argument("--train-end", default="2020-01-01",
                    help="m01_rank trains on dense rows before this date (OOS for eval window)")
    ap.add_argument("--horizon", type=int, default=20)
    ap.add_argument("--threshold", type=float, default=0.20)
    ap.add_argument("--model", default=PROTOTYPE_MODEL)
    ap.add_argument("--run-note", default="case2_prototype_plus_rank")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING,
                        format="%(asctime)s | %(levelname)s | %(message)s",
                        datefmt="%H:%M:%S")

    # 1. m01_prototype selection scores (same as Case 1), incl. warmup year
    print(f"Scoring T3 with m01_prototype ({args.warmup_start} warmup -> {args.end})...")
    scorer = UniverseScorer(m01_path=args.model)
    proto = scorer.score_from_t3(args.warmup_start, args.end)
    proto["date"] = pd.to_datetime(proto["date"])
    print(f"  prototype: {len(proto):,} rows / {proto['ticker'].nunique()} tickers")

    # 2. m01_rank timing scores (inline-trained classifier; OOS for the eval window,
    #    in-sample only over the un-evaluated warmup year — no leakage into results).
    print(f"Training m01_rank on dense rows < {args.train_end}, scoring "
          f"{args.warmup_start} -> {args.end}...")
    rank_scored, _, _ = train_and_score(
        train_end=args.train_end, score_start=args.warmup_start, score_end=args.end,
        horizon=args.horizon, threshold=args.threshold,
    )
    print(f"  m01_rank: {len(rank_scored):,} rows / {rank_scored['ticker'].nunique()} tickers")

    # 3. Merge: keep prototype floor/selection, swap ranking key to m01_rank pct.
    merged = proto.merge(rank_scored[["date", "ticker", "m01_rank_pct"]],
                         on=["date", "ticker"], how="inner")
    n_drop = len(proto) - len(merged)
    print(f"  merged: {len(merged):,} rows (dropped {n_drop:,} prototype rows "
          f"with no m01_rank score)")
    # m01_rank's daily percentile becomes the entry-ranking key.
    merged["trailing_pct"] = merged["m01_rank_pct"]
    merged["daily_pct_rank"] = merged["m01_rank_pct"]

    # 4. Run the same SEPA engine, ranking entries by m01_rank's timing score.
    runner = SEPABacktestRunner(start_date=args.warmup_start, end_date=args.end,
                                initial_cash=args.cash,
                                model_path=args.model)
    runner.setup(scores_df=merged)
    metrics = runner.run()

    equity = runner.get_equity_curve_dataframe()
    if equity is not None and len(equity) > 1:
        eval_eq = equity[equity.index >= pd.Timestamp(args.start)]
        yb = yearly_breakdown(equity)
        print(f"\n--- PER-YEAR BREAKDOWN (continuous compounding; eval >= {args.start}) ---")
        print(yb.to_string(index=False,
                           formatters={"return_pct": "{:+.1f}".format,
                                       "sharpe": "{:.2f}".format,
                                       "max_dd_pct": "{:.1f}".format,
                                       "avg_positions": "{:.1f}".format}))
        if len(eval_eq) > 1:
            ev_ret = (eval_eq["value"].iloc[-1] / eval_eq["value"].iloc[0] - 1) * 100
            print(f"\nEVAL-WINDOW [{args.start} -> {args.end}] total return: {ev_ret:+.1f}% "
                  f"(start NAV {eval_eq['value'].iloc[0]:,.0f} -> {eval_eq['value'].iloc[-1]:,.0f})")

    runner.print_results(metrics)
    run_dir = runner.save_run(metrics, run_note=args.run_note)
    print(f"\nSaved run to: {run_dir}")


if __name__ == "__main__":
    main()
