"""
Daily Pipeline CLI Entrypoint.

Usage:
    python scripts/run_daily_pipeline.py                    # Yesterday's close
    python scripts/run_daily_pipeline.py --date 2024-01-15  # Specific date
    python scripts/run_daily_pipeline.py --dry-run          # Validation only
    python scripts/run_daily_pipeline.py --force            # Ignore idempotency
"""

import atexit
import sys
import argparse
import logging
from pathlib import Path
from datetime import datetime, timedelta

# Add src to path
sys.path.append(str(Path(__file__).parent.parent))

# Configure logging BEFORE imports (modules call getLogger at import time)
# Per-run log: logs/daily_pipeline_YYYY-MM-DD_HHMMSS.log (one file per invocation)
_log_dir = Path("logs")
_log_dir.mkdir(exist_ok=True)
_run_ts = datetime.now().strftime('%Y-%m-%d_%H%M%S')
_log_file = _log_dir / f"daily_pipeline_{_run_ts}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-5s %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.FileHandler(_log_file, encoding='utf-8'),
        logging.StreamHandler(stream=open(1, 'w', encoding='utf-8', closefd=False))
    ]
)
for _noisy in ("urllib3", "requests", "peewee"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
# yfinance logs expected "possibly delisted" / "no earnings dates" events at ERROR,
# which sail past a WARNING filter and bury real signal (50+ lines/run). These are
# already captured + classified in pipeline_error_log, so silence the duplicate
# console/file spam at CRITICAL. --verbose lifts this back to DEBUG below.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

logger = logging.getLogger(__name__)


def _cleanup_empty_log():
    """Remove log file if nothing was written (killed before first log line)."""
    try:
        if _log_file.exists() and _log_file.stat().st_size == 0:
            _log_file.unlink()
    except OSError:
        pass


atexit.register(_cleanup_empty_log)


def main():
    parser = argparse.ArgumentParser(
        description='Run the daily data pipeline (9 phases)'
    )

    # Date arguments
    parser.add_argument(
        '--date',
        type=str,
        help='Target date to process (YYYY-MM-DD). Default: yesterday'
    )

    # Execution mode
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Validate only (no writes to database)'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Ignore idempotency checks (rerun completed phases)'
    )
    parser.add_argument(
        '--phase-1-only',
        action='store_true',
        help='Run Phase 1 (T1 ingestion) only — skip feature computation and downstream phases'
    )
    parser.add_argument(
        '--phase-2-only',
        action='store_true',
        help='Run Phase 2 (screener membership) only — skips T1 ingestion and feature computation'
    )
    parser.add_argument(
        '--phase-3-only',
        action='store_true',
        help='Run Phase 3 (T2 screener features) only — incremental from last computed date'
    )
    parser.add_argument(
        '--phase-4-only',
        action='store_true',
        help='Run Phase 4 (T2 regime scores) only — incremental from last computed date'
    )
    parser.add_argument(
        '--phase-5-only',
        action='store_true',
        help='Run Phase 5 (T3 SEPA features) only — incremental from last computed date'
    )
    parser.add_argument(
        '--universe-refresh',
        action='store_true',
        help='Run quarterly universe discovery before Phase 1 (never runs automatically)'
    )

    # Database
    parser.add_argument(
        '--db',
        type=str,
        help='Path to DuckDB database (default: data/market_data.duckdb)'
    )

    # Logging
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging (DEBUG level)'
    )

    args = parser.parse_args()

    # Set log level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        # Lift the default library suppression so --verbose shows full detail
        for _noisy in ("yfinance", "urllib3", "requests", "peewee"):
            logging.getLogger(_noisy).setLevel(logging.DEBUG)

    # Validate date format
    if args.date:
        try:
            datetime.strptime(args.date, '%Y-%m-%d')
        except ValueError:
            logger.error(f"Invalid date format: {args.date}. Expected YYYY-MM-DD")
            return 1

    # Import + init + run inside try/except so import-time crashes
    # (DuckDB lock, missing dependency) get logged instead of producing empty files.
    try:
        from src.orchestrators.daily_pipeline_orchestrator import DailyPipelineOrchestrator

        orchestrator = DailyPipelineOrchestrator(
            db_path=args.db,
            dry_run=args.dry_run,
            force=args.force
        )

        success = orchestrator.run_pipeline(
            target_date=args.date,
            phase_1_only=args.phase_1_only,
            phase_2_only=args.phase_2_only,
            phase_3_only=args.phase_3_only,
            phase_4_only=args.phase_4_only,
            phase_5_only=args.phase_5_only,
            universe_refresh=args.universe_refresh,
        )

        if success:
            logger.info("[OK] Pipeline completed successfully")
            return 0
        else:
            logger.error("[ERR] Pipeline failed (critical phase error)")
            return 1

    except KeyboardInterrupt:
        logger.warning("Pipeline interrupted by user")
        return 130

    except Exception as e:
        logger.error(f"Pipeline crashed: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
