#!/usr/bin/env python
"""Backtest ↔ prod scoring parity check.

Verifies the backtest UniverseScorer produces the SAME per-(ticker, date) elite
probability that prod materialized into `daily_predictions`. This is the wiring
that proves a backtest scores the identical thing the live system shipped — the
prerequisite for trusting backtest model comparisons.

`daily_predictions` is forward-only (materialized nightly), so parity can only be
checked on the overlap window. The backtest cannot READ from this table for its
history (it starts ~2025-10) — the table is the GROUND-TRUTH ANCHOR, not a source.

Usage:
    python scripts/check_backtest_parity.py --model models/m01_prototype_2003_2026/v2/model.json \
        --version-id m01_prototype_2003_2026_20260514_233125 \
        --start 2025-11-03 --end 2025-11-14
"""

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from src import db
from src.backtest.universe_scorer import UniverseScorer

logger = logging.getLogger("check_backtest_parity")

TOL = 1e-4  # rows above this are flagged as divergent


def check_parity(model_path: str, version_id: str, start: str, end: str) -> int:
    scorer = UniverseScorer(m01_path=model_path, calibration_path=None)
    scored = scorer.score_from_t3(start, end)[["date", "ticker", "prob_elite"]].copy()
    scored["date"] = pd.to_datetime(scored["date"])

    con = db.connect(str(config.DATA_DIR / "market_data.duckdb"), read_only=True)
    try:
        prod = con.execute(
            "SELECT DISTINCT CAST(prediction_date AS DATE) AS date, ticker, prob_class_3 "
            "FROM daily_predictions WHERE model_version_id = ? "
            "AND prediction_date BETWEEN ? AND ?",
            [version_id, start, end],
        ).fetchdf()
    finally:
        con.close()

    if prod.empty:
        print(f"[WARN] No daily_predictions rows for {version_id} in {start}..{end}. "
              f"Nothing to compare (table is forward-only from ~2025-10).")
        return 0

    prod["date"] = pd.to_datetime(prod["date"])
    prod = prod.drop_duplicates(["date", "ticker"])  # same prob across cohorts

    m = scored.merge(prod, on=["date", "ticker"], how="inner")
    if m.empty:
        print("[WARN] No overlapping (ticker, date) rows to compare.")
        return 0

    m["diff"] = (m["prob_elite"] - m["prob_class_3"]).abs()
    n_off = int((m["diff"] > TOL).sum())
    pct_match = (1 - n_off / len(m)) * 100

    print("=" * 60)
    print(f"Backtest <-> prod parity ({start} .. {end})")
    print("=" * 60)
    print(f"  Overlap rows:  {len(m):,}")
    print(f"  Max abs diff:  {m['diff'].max():.6f}")
    print(f"  Mean abs diff: {m['diff'].mean():.6f}")
    print(f"  Rows > {TOL:g}:    {n_off}  ({pct_match:.2f}% match)")
    if n_off:
        print("  Worst offenders:")
        worst = m.sort_values("diff", ascending=False).head(8)
        for _, r in worst.iterrows():
            print(f"    {r['date'].date()} {r['ticker']:6s} "
                  f"bt={r['prob_elite']:.4f} prod={r['prob_class_3']:.4f} d={r['diff']:.4f}")
    print("=" * 60)
    # Non-zero exit only if a meaningful share diverges (>1% of rows).
    return 1 if n_off / len(m) > 0.01 else 0


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", default="models/m01_prototype_2003_2026/v2/model.json")
    p.add_argument("--version-id", default="m01_prototype_2003_2026_20260514_233125")
    p.add_argument("--start", default="2025-11-03")
    p.add_argument("--end", default="2025-11-14")
    args = p.parse_args()

    logging.basicConfig(level=logging.ERROR, format="%(message)s")
    sys.exit(check_parity(args.model, args.version_id, args.start, args.end))


if __name__ == "__main__":
    main()
