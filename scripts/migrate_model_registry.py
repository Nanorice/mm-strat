"""Migrate models table: add classification metrics + reproducibility columns.

Adds new columns to existing DBs without dropping anything.
Safe to run multiple times (ALTER TABLE IF NOT EXISTS pattern via catch).
"""

import sys
from pathlib import Path

import duckdb

sys.path.append(str(Path(__file__).parent.parent))
from src.model_registry import ModelRegistry

DB_PATH = Path(__file__).parent.parent / "data" / "market_data.duckdb"

NEW_COLUMNS = [
    ("accuracy",       "DOUBLE"),
    ("weighted_f1",    "DOUBLE"),
    ("macro_f1",       "DOUBLE"),
    ("feature_set_id", "VARCHAR"),
    ("git_sha",        "VARCHAR"),
    ("model_type",     "VARCHAR DEFAULT 'classifier'"),
]


def migrate(db_path: Path) -> None:
    con = duckdb.connect(str(db_path))
    try:
        existing = {
            row[0]
            for row in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'models'"
            ).fetchall()
        }

        added = []
        for col, dtype in NEW_COLUMNS:
            if col not in existing:
                con.execute(f"ALTER TABLE models ADD COLUMN {col} {dtype}")
                added.append(col)

        if added:
            print(f"[OK] Added columns: {', '.join(added)}")
        else:
            print("[OK] models table already up to date — nothing to add")

        # Ensure catalog tables exist (idempotent via ModelRegistry.__init__)
        ModelRegistry(db_path=db_path)
        print("[OK] feature_catalog and model_feature_sets tables ensured")

    finally:
        con.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Migrate model registry schema")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args()

    print(f"Migrating {args.db} ...")
    migrate(args.db)
    print("Done.")
