#!/usr/bin/env python3
"""Recreate all DuckDB virtual views.

Usage:
    python scripts/create_duckdb_views.py
    python scripts/create_duckdb_views.py --db data/market_data.duckdb
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.managers.view_manager import ViewManager


def main():
    parser = argparse.ArgumentParser(description="Create/refresh DuckDB views")
    parser.add_argument("--db", default="data/market_data.duckdb", help="Path to DuckDB file")
    args = parser.parse_args()

    ViewManager(args.db).create_all()


if __name__ == "__main__":
    main()
