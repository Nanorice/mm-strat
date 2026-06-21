"""Central DuckDB connection factory.

Single source of truth for DuckDB resource governance. Every connection in the
project must be opened through connect() so the memory/thread caps in config are
applied uniformly — a raw duckdb.connect() inherits DuckDB's default ~80%-of-RAM
budget and starves anything else on the box (notably a parallel agent).
"""

import sys
from pathlib import Path

import duckdb

sys.path.append(str(Path(__file__).parent.parent))
import config

_temp_dir_ready = False


def connect(db_path, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection with project-wide memory/thread caps applied.

    memory_limit forces large window-function queries to spill to temp_directory
    rather than OOM. Settings are per-instance, so they are (re)applied on every
    connect — cheap and idempotent.
    """
    global _temp_dir_ready
    if not _temp_dir_ready:
        Path(config.DUCKDB_TEMP_DIR).mkdir(parents=True, exist_ok=True)
        _temp_dir_ready = True

    con = duckdb.connect(str(db_path), read_only=read_only)
    con.execute(f"PRAGMA memory_limit='{config.DUCKDB_MEMORY_LIMIT}'")
    con.execute(f"PRAGMA threads={config.DUCKDB_THREADS}")
    con.execute(f"PRAGMA temp_directory='{config.DUCKDB_TEMP_DIR}'")
    return con
