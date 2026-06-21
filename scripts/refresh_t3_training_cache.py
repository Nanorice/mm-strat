#!/usr/bin/env python3
"""Refresh t3_training_cache (materialized v_t3_training) — weekly cadence.

This is the full feature matrix: t3_sepa_features + sector/industry + shares +
fundamentals + derived valuation ratios (pe/ps/pb/peg). The underlying ASOF joins
cost ~215s, and the fundamental/shares inputs change weekly at most, so this is
deliberately NOT part of the per-run ViewManager.create_all(). Run it weekly (or
after a fundamentals/shares backfill).

Usage:
    python scripts/refresh_t3_training_cache.py
    python scripts/refresh_t3_training_cache.py --db data/market_data.duckdb
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.managers.view_manager import ViewManager


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh t3_training_cache (weekly)")
    parser.add_argument("--db", default=None, help="DuckDB path (defaults to project DB)")
    args = parser.parse_args()

    vm = ViewManager(db_path=args.db)
    vm.refresh_t3_training_cache()


if __name__ == "__main__":
    main()
