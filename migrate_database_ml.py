"""
Database Migration Script - Add ML Columns to buy_list Table

This script adds ML scoring columns to the buy_list table:
- ml_probability: ML success probability (0.0-1.0)
- ml_rank: ML rank (1=best)
- ml_model_version: Model version identifier
- ml_score_date: Date ML score was generated

Run this script ONCE to upgrade your existing database schema.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
import config

def migrate_database():
    """Add ML columns to buy_list table if they don't exist."""

    db_path = config.DB_PATH
    print(f"Migrating database: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if columns already exist
    cursor.execute("PRAGMA table_info(buy_list)")
    existing_columns = [row[1] for row in cursor.fetchall()]

    ml_columns = {
        'ml_probability': 'REAL',
        'ml_rank': 'INTEGER',
        'ml_model_version': 'TEXT',
        'ml_score_date': 'DATE'
    }

    added_columns = []
    skipped_columns = []

    for col_name, col_type in ml_columns.items():
        if col_name not in existing_columns:
            print(f"  Adding column: {col_name} ({col_type})")
            cursor.execute(f"ALTER TABLE buy_list ADD COLUMN {col_name} {col_type}")
            added_columns.append(col_name)
        else:
            skipped_columns.append(col_name)

    conn.commit()
    conn.close()

    # Summary
    print("\n" + "=" * 60)
    print("MIGRATION SUMMARY")
    print("=" * 60)

    if added_columns:
        print(f"✅ Added {len(added_columns)} columns:")
        for col in added_columns:
            print(f"   - {col}")

    if skipped_columns:
        print(f"\nℹ️  Skipped {len(skipped_columns)} columns (already exist):")
        for col in skipped_columns:
            print(f"   - {col}")

    if not added_columns:
        print("\n✅ Database already up to date!")
    else:
        print("\n✅ Migration complete!")

    print("=" * 60)


if __name__ == "__main__":
    try:
        migrate_database()
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        sys.exit(1)
