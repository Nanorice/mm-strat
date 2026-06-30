"""Checkpoint + truncate the Prefect SQLite WAL.

Repeated hard crashes of the Prefect server (never a clean shutdown) leave the
write-ahead log uncheckpointed; it grows until SQLite's WAL recovery stalls the
next server startup with 'database is locked'. Run this ONLY while the server is
stopped (teardown barrier) so the next start opens a compact, recovered db.
No-op if the db is missing or busy.
"""
import os
import sqlite3
import sys

DB = os.path.expanduser(os.path.join("~", ".prefect", "prefect.db"))


def main() -> int:
    if not os.path.exists(DB):
        return 0
    try:
        con = sqlite3.connect(DB, timeout=30)
        result = con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        con.execute("PRAGMA optimize")
        con.close()
        print(f"wal_checkpoint(TRUNCATE) -> {result}")
    except sqlite3.Error as e:
        print(f"wal checkpoint skipped: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
