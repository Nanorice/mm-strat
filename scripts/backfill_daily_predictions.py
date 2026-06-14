"""Backfill daily_predictions with RAW prod-model scores across a date range.

Two jobs, one tool:
  1. Fill the history gap — daily_predictions only exists from 2026-05-22 (when
     Phase 7.4 went live), so the dashboard can only attach scores to tickers that
     broke out on the latest day. Backfilling the full d3 window gives every
     watchlist row a score from its own entry date.
  2. Re-score on model switch — pass --model-version-id to materialize a newly
     promoted model's scores. The (date, ticker, model, cohort) PK lets many
     models coexist; the dashboard reads whichever is prod.

Stores RAW softprob only (no calibration) via the shared ScoreEngine — same code
path as the orchestrator's Phase 7.4, so the two cannot drift. Idempotent
(INSERT OR REPLACE per PK); safe to re-run. Run against the FULL DB, then rebuild
the slim dashboard DB to propagate.

Usage:
    python scripts/backfill_daily_predictions.py                 # prod, full d3 window, both cohorts
    python scripts/backfill_daily_predictions.py --start 2025-10-03 --end 2026-06-12
    python scripts/backfill_daily_predictions.py --cohort breakout
    python scripts/backfill_daily_predictions.py --model-version-id <id>
    python scripts/backfill_daily_predictions.py --dry-run        # count dates, score nothing
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from src.evaluation.score_engine import ScoreEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_daily_predictions")

DB_PATH = str(config.DATA_DIR / "market_data.duckdb")

# (cohort, source view). Both views carry the same feature contract as the model.
COHORT_VIEWS = {
    "breakout": "v_d3_deployment",
    "pre_breakout": "v_d3_prebreakout",
}


def _pull_window(view: str, start: str | None, end: str | None):
    """One pull of the whole windowed frame — far cheaper than 100s of per-date
    queries that each re-evaluate the view."""
    pred, params = [], []
    if start:
        pred.append("date >= ?"); params.append(start)
    if end:
        pred.append("date <= ?"); params.append(end)
    where = f"WHERE {' AND '.join(pred)}" if pred else ""
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        return con.execute(f"SELECT * FROM {view} {where} ORDER BY date", params).df()
    finally:
        con.close()


def backfill_cohort(engine: ScoreEngine, cohort: str, view: str,
                    start: str | None, end: str | None, dry_run: bool) -> None:
    t0 = time.time()
    frame = _pull_window(view, start, end)
    dates = sorted(frame["date"].unique()) if not frame.empty else []

    logger.info("[%s] %d rows over %d dates from %s (%s → %s) · pulled in %.1fs",
                cohort, len(frame), len(dates), view,
                dates[0] if dates else "—", dates[-1] if dates else "—", time.time() - t0)
    if dry_run:
        logger.info("[%s] DRY RUN — scored nothing.", cohort)
        return
    if frame.empty:
        return

    # Score the whole window in one vectorized pass, then log per date (the logger
    # computes rank_within_day per (date, cohort), so we hand it one date at a time).
    scored = engine.predict_frame(frame)
    scored["date"] = frame["date"].values

    total = 0
    for i, d in enumerate(dates, 1):
        day = scored[scored["date"] == d].drop(columns=["date"])
        try:
            total += engine.log_predictions(day, d, cohort, DB_PATH)
        except Exception as e:  # one bad date never aborts the run
            logger.warning("[%s] %s failed: %s", cohort, d, e)
        if i % 40 == 0 or i == len(dates):
            logger.info("[%s] %d/%d dates · %d rows", cohort, i, len(dates), total)
    logger.info("[%s] DONE — %d rows across %d dates in %.1fs",
                cohort, total, len(dates), time.time() - t0)


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill daily_predictions (raw scores).")
    ap.add_argument("--model-version-id", default=None,
                    help="Model to score with. Default: current prod model.")
    ap.add_argument("--start", default=None, help="Inclusive start date YYYY-MM-DD (default: view min).")
    ap.add_argument("--end", default=None, help="Inclusive end date YYYY-MM-DD (default: view max).")
    ap.add_argument("--cohort", choices=["breakout", "pre_breakout", "both"], default="both")
    ap.add_argument("--dry-run", action="store_true", help="List dates per cohort; score nothing.")
    args = ap.parse_args()

    if args.model_version_id:
        engine = ScoreEngine.from_version(DB_PATH, args.model_version_id)
    else:
        engine = ScoreEngine.from_prod(DB_PATH)
        if engine is None:
            logger.error("No prod model registered and --model-version-id not given.")
            return 1
    logger.info("Scoring with model_version_id=%s (%d features)",
                engine.version_id, len(engine.feature_names))

    cohorts = ["breakout", "pre_breakout"] if args.cohort == "both" else [args.cohort]
    for cohort in cohorts:
        backfill_cohort(engine, cohort, COHORT_VIEWS[cohort], args.start, args.end, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
