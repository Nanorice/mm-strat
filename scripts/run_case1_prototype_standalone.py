"""
Case 1 — m01_prototype as a standalone top-K trading signal.

Scores the dense T3 universe daily with m01_prototype, then runs the full
SEPAHybridV1 BackTrader engine (M03 regime gating + 3-tranche ATR exits) over
a continuous window. Reports overall metrics plus a per-calendar-year
breakdown of the equity curve (the 2022 row is the regime stress test).

Usage:
    python scripts/run_case1_prototype_standalone.py --start 2020-01-01 --end 2024-12-31
"""

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest import UniverseScorer, SEPABacktestRunner

PROTOTYPE_MODEL = "models/m01_prototype_2003_2026/v1/model.json"


def yearly_breakdown(equity: pd.DataFrame) -> pd.DataFrame:
    """Per-calendar-year return / Sharpe / max-drawdown from the daily equity curve."""
    eq = equity.copy()
    eq["ret"] = eq["value"].pct_change()
    rows = []
    for year, g in eq.groupby(eq.index.year):
        v = g["value"]
        daily = g["ret"].dropna()
        nav = v / v.iloc[0]
        sharpe = (daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 0 else 0.0
        max_dd = (nav / nav.cummax() - 1).min()
        rows.append({
            "year": int(year),
            "return_pct": (v.iloc[-1] / v.iloc[0] - 1) * 100,
            "sharpe": sharpe,
            "max_dd_pct": max_dd * 100,
            "avg_positions": g["position_count"].mean(),
        })
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--warmup-start", default="2019-01-01",
                    help="Feed/score from here so SMA(50) etc. are ready by --start. "
                         "BackTrader stays in prenext() until every feed's min-period "
                         "is met; without a buffer the eval-start year never trades.")
    ap.add_argument("--cash", type=float, default=100_000)
    ap.add_argument("--model", default=PROTOTYPE_MODEL)
    ap.add_argument("--run-note", default="case1_prototype_standalone")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING,
                        format="%(asctime)s | %(levelname)s | %(message)s",
                        datefmt="%H:%M:%S")

    print(f"Scoring T3 universe with {args.model} "
          f"({args.warmup_start} warmup -> {args.end})...")
    scorer = UniverseScorer(m01_path=args.model)
    scores = scorer.score_from_t3(args.warmup_start, args.end)
    print(f"  scored {len(scores):,} rows / {scores['ticker'].nunique()} tickers / "
          f"{scores['date'].nunique()} dates")

    runner = SEPABacktestRunner(start_date=args.warmup_start, end_date=args.end,
                                initial_cash=args.cash,
                                model_path=args.model)
    runner.setup(scores_df=scores)
    metrics = runner.run()

    equity = runner.get_equity_curve_dataframe()
    if equity is not None and len(equity) > 1:
        eval_eq = equity[equity.index >= pd.Timestamp(args.start)]
        yb = yearly_breakdown(equity)  # full span incl. warmup year for context
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
