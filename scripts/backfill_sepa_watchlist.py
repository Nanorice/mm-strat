"""
Backfill the sepa_watchlist event log from full t2_screener_features history.

Single SQL pass + Python cooldown sweep — see SepaWatchlistManager.backfill().
Authoritative rebuild: any existing sepa_watchlist rows are wiped before insert.

Usage:
    python scripts/backfill_sepa_watchlist.py
    python scripts/backfill_sepa_watchlist.py --start 2001-01-01 --end 2026-05-08
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DUCKDB_PATH
from src.managers import SepaWatchlistManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', help='Start date (YYYY-MM-DD); default = MIN(t2.date)')
    parser.add_argument('--end',   help='End date (YYYY-MM-DD); default = MAX(t2.date)')
    args = parser.parse_args()

    mgr = SepaWatchlistManager(DUCKDB_PATH)

    t0 = time.time()
    result = mgr.backfill(start_date=args.start, end_date=args.end)
    elapsed = time.time() - t0

    stats = mgr.get_stats()
    logger.info("=" * 60)
    logger.info(f"sepa_watchlist backfill complete in {elapsed:.1f}s")
    logger.info(f"  sessions: {stats['sessions']:,}")
    logger.info(f"  tickers:  {stats['tickers']:,}")
    logger.info(f"  active:   {stats['active']:,}")
    logger.info(f"  cooldown: {stats['cooldown']:,}")
    logger.info(f"  exited:   {stats['exited']:,}")
    logger.info(f"  range:    {stats['earliest_entry']} -> {stats['latest_entry']}")
    logger.info("=" * 60)
    return 0


if __name__ == '__main__':
    sys.exit(main())
