"""
Test script to validate backtest optimization imports.

This validates that all dependencies are correctly installed and importable
before running the full optimization (which requires DuckDB integration).
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

print("\n" + "="*80)
print("Testing Backtest Optimization Imports")
print("="*80 + "\n")

# Test 1: Core imports
print("[1/6] Testing core imports...")
try:
    import pandas as pd
    import numpy as np
    import duckdb
    import backtrader as bt
    print("  [OK] pandas, numpy, duckdb, backtrader")
except ImportError as e:
    print(f"  [ERROR] {e}")
    sys.exit(1)

# Test 2: Config
print("[2/6] Testing config...")
try:
    import config
    db_path = Path(config.DUCKDB_PATH)
    if db_path.exists():
        print(f"  [OK] DuckDB database found: {db_path}")
    else:
        print(f"  [WARN] DuckDB database not found: {db_path}")
except Exception as e:
    print(f"  [ERROR] {e}")
    sys.exit(1)

# Test 3: DuckDB feed adapter
print("[3/6] Testing DuckDB feed adapter...")
try:
    from src.backtest.duckdb_feed import DuckDBUniverseDataLoader, DuckDBCandidateFeed
    print("  [OK] DuckDBUniverseDataLoader, DuckDBCandidateFeed")
except ImportError as e:
    print(f"  [ERROR] {e}")
    sys.exit(1)

# Test 4: Backtest runner
print("[4/6] Testing backtest runner...")
try:
    from src.backtest.runner import SEPABacktestRunner
    print("  [OK] SEPABacktestRunner")
except ImportError as e:
    print(f"  [ERROR] {e}")
    sys.exit(1)

# Test 5: Analyzers
print("[5/6] Testing analyzers...")
try:
    from src.backtest.analyzers import CalmarRatio
    print("  [OK] CalmarRatio")
except ImportError as e:
    print(f"  [ERROR] {e}")
    sys.exit(1)

# Test 6: DuckDB connection
print("[6/6] Testing DuckDB connection...")
try:
    conn = duckdb.connect(str(db_path), read_only=True)
    result = conn.execute("SELECT COUNT(*) FROM t3_sepa_features WHERE feature_version='v3.1'").fetchone()
    row_count = result[0] if result else 0
    conn.close()
    print(f"  [OK] Connected to DuckDB, {row_count:,} rows in t3_sepa_features")
except Exception as e:
    print(f"  [ERROR] {e}")
    sys.exit(1)

print("\n" + "="*80)
print("All import tests passed!")
print("="*80 + "\n")

print("Note: Full optimization requires DuckDB integration in SEPABacktestRunner")
print("      Current runner uses parquet files (data/backtest/m03_feed.parquet, etc.)")
print("      See docs/proposals/duckdb_v2/phase_6_5_completion_summary.md for details")
print()
