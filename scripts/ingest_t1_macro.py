"""
Ingest daily macro data into t1_macro table.

Usage:
    python scripts/ingest_t1_macro.py                    # Incremental (from last date)
    python scripts/ingest_t1_macro.py --backfill         # Full backfill from 2020-01-01
    python scripts/ingest_t1_macro.py --start 2024-01-01 # Custom start date
"""

import sys
import argparse
import logging
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from src.macro_engine import MacroEngine

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Default database path
DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "market_data.duckdb"


def main():
    parser = argparse.ArgumentParser(description='Ingest macro data to t1_macro table')
    parser.add_argument('--backfill', action='store_true', help='Force full backfill from 2020-01-01')
    parser.add_argument('--start', type=str, help='Custom start date (YYYY-MM-DD)')
    parser.add_argument('--db', type=str, default=str(DEFAULT_DB_PATH), help='DuckDB path')
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("T1 MACRO INGESTION")
    logger.info("=" * 60)

    engine = MacroEngine(db_path=args.db)

    try:
        inserted = engine.ingest_daily_macro(
            start_date=args.start,
            force=args.backfill
        )

        if inserted > 0:
            logger.info(f"[OK] Inserted {inserted} macro records")
        else:
            logger.info("[OK] No new macro data to ingest")

        return 0

    except Exception as e:
        logger.error(f"[ERROR] Ingestion failed: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
