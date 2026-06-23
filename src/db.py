"""Central DuckDB connection factory.

Single source of truth for DuckDB resource governance. Every connection in the
project must be opened through connect() so the memory/thread caps in config are
applied uniformly — a raw duckdb.connect() inherits DuckDB's default ~80%-of-RAM
budget and starves anything else on the box (notably a parallel agent).
"""

import re
import sys
from pathlib import Path

import duckdb

sys.path.append(str(Path(__file__).parent.parent))
import config

_temp_dir_ready = False


class DuckDBLockedError(RuntimeError):
    """The DuckDB file is held read-write by another process (single-writer)."""


def check_write_available(db_path) -> None:
    """Pre-flight: confirm the DuckDB write lock is free, else raise
    DuckDBLockedError naming the holder. DuckDB is single-writer — a notebook or
    tool left with a read-write connection blocks the pipeline's writes. Fail
    fast here with an actionable message instead of crashing mid-phase."""
    # A non-existent path is created by connect(); an IOException on a write-open
    # means the file is unavailable for writing (held by another process). DuckDB
    # reports this differently per OS — POSIX "Conflicting lock is held", Windows
    # "being used by another process" — so key off the exception type, not text.
    try:
        duckdb.connect(str(db_path), read_only=False).close()
    except duckdb.IOException as e:
        raise DuckDBLockedError(_describe_lock(str(db_path), str(e))) from e


def _describe_lock(db_path: str, err: str) -> str:
    m = re.search(r"PID (\d+)", err)
    holder = f"PID {m.group(1)}" if m else "another process"
    return (
        f"{Path(db_path).name} is locked by {holder} - DuckDB allows only one "
        f"read-write process, so the pipeline cannot write. This is almost always "
        f"a notebook/kernel left with a read-write connection; close it (or reopen "
        f"it read_only) and rerun."
    )


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
