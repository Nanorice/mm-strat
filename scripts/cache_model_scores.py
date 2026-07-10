"""Cache a model's t3 scores to parquet so the WFO cone doesn't re-score per run.

score_from_t3 over 25y takes minutes; the cone re-runs it every invocation.
Dump [date, ticker, prob_elite, calibrated_score, ...] once, then feed the WFO
via --scores-parquet.

Usage:
    python scripts/cache_model_scores.py --model m01_binary \
        --start 2003-01-01 --end 2026-05-22
    # -> data/score_cache/m01_binary_calibrated_2003-01-01_2026-05-22.parquet
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

from scripts.run_strategy_optimizer import resolve_model_path, prescore

CACHE_DIR = REPO_ROOT / "data" / "score_cache"
# The WFO only needs these; score_from_t3 otherwise carries ~190 t3 feature cols
# (a full-span copy OOMs at ~12 GiB). Trim per chunk before concat.
# NB: the SEPA entry gate (trend_ok AND breakout_ok) is NOT cached — the per-
# (ticker,date) score is valid regardless; consumers join the flags from
# t3_sepa_features at selection time (src.backtest.sepa_gate). Keeps the cache
# a pure score artifact and lets the existing cache stay valid without a re-score.
KEEP_COLS = ["date", "ticker", "prob_elite", "calibrated_score"]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--raw-prob", action="store_true", help="Cache raw p_pos (no calibrator).")
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()

    model_path = resolve_model_path(args.model)

    # Chunk by year: score_from_t3 copies the full wide t3 frame, so a 25y span
    # OOMs. Score year-by-year, trim to KEEP_COLS, concat the small frames.
    years = pd.date_range(args.start, args.end, freq="YS").year.tolist()
    bounds = [args.start] + [f"{y}-01-01" for y in years if f"{y}-01-01" > args.start] + [args.end]
    bounds = sorted(set(bounds))
    parts = []
    for lo, hi in zip(bounds[:-1], bounds[1:]):
        chunk = prescore(model_path, lo, hi, raw_prob=args.raw_prob)
        cols = [c for c in KEEP_COLS if c in chunk.columns]
        parts.append(chunk[cols].copy())
        del chunk
    scores = pd.concat(parts, ignore_index=True).drop_duplicates(["date", "ticker"])

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    arm = "raw" if args.raw_prob else "calibrated"
    out = Path(args.out) if args.out else (
        CACHE_DIR / f"{args.model}_{arm}_{args.start}_{args.end}.parquet")
    scores.to_parquet(out, index=False)
    print(f"[OK] {len(scores)} rows, {scores['date'].nunique()} dates -> {out}")


if __name__ == "__main__":
    main()
