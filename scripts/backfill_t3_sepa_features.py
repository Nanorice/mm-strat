"""
Chunked-resumable backfill for t3_sepa_features (dense over screener universe).

Calls FeaturePipeline.compute_t3_features() per quarterly chunk. Idempotent via
INSERT OR IGNORE on (ticker, date, feature_version). Resumable via a plain-text
checkpoint log; a mid-chunk crash leaves the chunk in a clean state on retry
(pre-chunk DELETE + re-run).

Usage:
    python scripts/backfill_t3_sepa_features.py                         # resume / 2001-Q1 -> latest
    python scripts/backfill_t3_sepa_features.py --from 2024-Q1 --to 2024-Q1
    python scripts/backfill_t3_sepa_features.py --restart --from 2020-Q1 --to 2024-Q4
    python scripts/backfill_t3_sepa_features.py --force-rebuild 2024-Q2
"""

import argparse
import logging
import sys
import time
from datetime import datetime, date
from pathlib import Path
from typing import Set, Tuple

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DUCKDB_PATH
from src.feature_pipeline import FeaturePipeline

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)

CHECKPOINT_PATH = Path('logs/t3_backfill_progress.log')

QUARTERS = {
    1: ('01-01', '03-31'),
    2: ('04-01', '06-30'),
    3: ('07-01', '09-30'),
    4: ('10-01', '12-31'),
}


def chunk_dates(year: int, q: int) -> Tuple[str, str]:
    s_md, e_md = QUARTERS[q]
    return f'{year}-{s_md}', f'{year}-{e_md}'


def parse_yq(s: str) -> Tuple[int, int]:
    """Parse 'YYYY-Q[1-4]' -> (year, quarter)."""
    s = s.strip().upper().replace('-', '')
    # accept '2024Q1' or '2024-Q1'
    if 'Q' not in s:
        raise ValueError(f"Bad quarter spec '{s}', expected like 2024-Q1")
    year_str, q_str = s.split('Q')
    return int(year_str), int(q_str)


def iter_chunks(from_yq: Tuple[int, int], to_yq: Tuple[int, int]):
    y, q = from_yq
    end_y, end_q = to_yq
    while (y, q) <= (end_y, end_q):
        yield y, q
        q += 1
        if q > 4:
            q = 1
            y += 1


def load_checkpoints() -> Set[Tuple[int, int]]:
    if not CHECKPOINT_PATH.exists():
        return set()
    done = set()
    with CHECKPOINT_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # format: '<ts>  year=YYYY q=Q  rows=<n>  elapsed=<s>s  t3_total=<n>'
            parts = dict(
                tok.split('=', 1) for tok in line.split() if '=' in tok
            )
            try:
                done.add((int(parts['year']), int(parts['q'])))
            except (KeyError, ValueError):
                logger.warning(f"Skipping malformed checkpoint line: {line!r}")
    return done


def append_checkpoint(year: int, q: int, rows: int, elapsed: float, t3_total: int) -> None:
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    line = f"{ts}  year={year} q={q}  rows={rows}  elapsed={elapsed:.0f}s  t3_total={t3_total}\n"
    with CHECKPOINT_PATH.open('a') as f:
        f.write(line)


def clear_all_checkpoints() -> None:
    if CHECKPOINT_PATH.exists():
        CHECKPOINT_PATH.unlink()


def clear_checkpoint_yq(year: int, q: int) -> None:
    """Rewrite checkpoint log without entries for (year, q)."""
    if not CHECKPOINT_PATH.exists():
        return
    keep = []
    with CHECKPOINT_PATH.open() as f:
        for line in f:
            try:
                parts = dict(tok.split('=', 1) for tok in line.split() if '=' in tok)
                if int(parts.get('year', -1)) == year and int(parts.get('q', -1)) == q:
                    continue
            except (ValueError, KeyError):
                pass
            keep.append(line)
    with CHECKPOINT_PATH.open('w') as f:
        f.writelines(keep)


def latest_yq() -> Tuple[int, int]:
    """Return today's (year, quarter)."""
    today = date.today()
    q = (today.month - 1) // 3 + 1
    return today.year, q


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--from', dest='from_yq', default='2001-Q1', help='Start quarter (YYYY-Q[1-4]). Default: 2001-Q1')
    p.add_argument('--to', dest='to_yq', default=None, help='End quarter (YYYY-Q[1-4]). Default: current quarter')
    p.add_argument('--restart', action='store_true', help='DROP t3_sepa_features and clear all checkpoints before starting')
    p.add_argument('--force-rebuild', dest='force_rebuild', default=None,
                   help='DELETE one quarter (YYYY-Q[1-4]) and clear its checkpoint, then run normally')
    p.add_argument('--db', default=str(DUCKDB_PATH), help='DuckDB path')
    p.add_argument('--feature-version', default='v3.1')
    return p.parse_args()


def main() -> int:
    args = parse_args()
    from_yq = parse_yq(args.from_yq)
    to_yq = parse_yq(args.to_yq) if args.to_yq else latest_yq()

    if from_yq > to_yq:
        logger.error(f"--from {from_yq} > --to {to_yq}; nothing to do")
        return 1

    pipeline = FeaturePipeline(db_path=args.db, feature_version=args.feature_version)

    # NOTE: never hold a long-lived connection open across compute_t3_features() calls.
    # FeaturePipeline opens its own connections internally; an outer writer connection
    # held in parallel forces DuckDB to serialize / spin and can stall the inner SQL
    # for many minutes. Always open a connection, do one short DDL/maintenance op,
    # close it, then call the pipeline.

    def _with_con(fn):
        con = duckdb.connect(args.db)
        try:
            return fn(con)
        finally:
            con.close()

    if args.restart:
        logger.warning("RESTART: dropping t3_sepa_features and clearing checkpoints")
        def _restart(con):
            con.execute("DROP TABLE IF EXISTS t3_sepa_features")
            pipeline._create_t3_table(con)
        _with_con(_restart)
        clear_all_checkpoints()

    # Ensure table exists even without --restart (for cold start without prior data)
    def _ensure_table(con):
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        if 't3_sepa_features' not in tables:
            logger.info("t3_sepa_features missing, creating from DDL")
            pipeline._create_t3_table(con)
    _with_con(_ensure_table)

    done = load_checkpoints()

    if args.force_rebuild:
        y, q = parse_yq(args.force_rebuild)
        s, e = chunk_dates(y, q)
        def _force(con):
            n = con.execute(
                f"SELECT COUNT(*) FROM t3_sepa_features WHERE date BETWEEN '{s}' AND '{e}'"
            ).fetchone()[0]
            logger.warning(f"FORCE-REBUILD {y}-Q{q}: deleting {n:,} existing rows")
            con.execute(f"DELETE FROM t3_sepa_features WHERE date BETWEEN '{s}' AND '{e}'")
        _with_con(_force)
        done.discard((y, q))
        clear_checkpoint_yq(y, q)

    chunks = list(iter_chunks(from_yq, to_yq))
    logger.info(f"Backfill plan: {len(chunks)} quarters from {from_yq} to {to_yq}")
    logger.info(f"  Already complete (skipping): {len(done & set(chunks))}")

    overall_t0 = time.time()
    completed = 0

    for year, q in chunks:
        if (year, q) in done:
            logger.info(f"[SKIP] {year}-Q{q} (checkpoint)")
            continue

        s, e = chunk_dates(year, q)

        # Pre-chunk sanity: clean up any partial state from a prior crashed run.
        # If we're not in checkpoint but have rows for this quarter, those rows
        # may have NULL alpha/vol-adj cols (the post-INSERT Python passes never
        # ran). Delete and start fresh to guarantee a clean chunk.
        def _precheck(con):
            partial = con.execute(
                f"SELECT COUNT(*) FROM t3_sepa_features WHERE date BETWEEN '{s}' AND '{e}'"
            ).fetchone()[0]
            if partial > 0:
                logger.warning(f"[CLEANUP] {year}-Q{q} has {partial:,} orphaned rows from prior crash — deleting")
                con.execute(f"DELETE FROM t3_sepa_features WHERE date BETWEEN '{s}' AND '{e}'")
        _with_con(_precheck)

        logger.info(f"[RUN] {year}-Q{q} {s} -> {e}")
        t0 = time.time()
        try:
            # CRITICAL: no outer connection open while this runs.
            rows = pipeline.compute_t3_features(start_date=s, end_date=e)
        except Exception as exc:
            logger.error(f"[FAIL] {year}-Q{q}: {exc}", exc_info=True)
            logger.error(f"Aborting. Re-run to resume from checkpoint.")
            return 2

        elapsed = time.time() - t0
        t3_total = _with_con(lambda con: con.execute("SELECT COUNT(*) FROM t3_sepa_features").fetchone()[0])
        append_checkpoint(year=year, q=q, rows=rows, elapsed=elapsed, t3_total=t3_total)
        completed += 1
        logger.info(f"[DONE] {year}-Q{q}: {rows:,} rows in {elapsed:.0f}s (t3_total={t3_total:,})")

    overall_elapsed = time.time() - overall_t0
    logger.info(f"Backfill complete: {completed} quarters in {overall_elapsed:.0f}s "
                f"({overall_elapsed / 60:.1f} min)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
