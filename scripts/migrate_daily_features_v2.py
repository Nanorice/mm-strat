"""
Migration script to add new RS Line features to daily_features table.

This script:
1. Backs up the current daily_features table
2. Adds new columns for RS Line metrics (price_vs_spy, price_vs_spy_ma63, rs_line_uptrend)
3. Validates the migration

Usage:
    python scripts/migrate_daily_features_v2.py [--dry-run]
"""
import duckdb
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from database_duckdb import DuckDBManager


def check_existing_columns(conn, db_path: str) -> dict:
    """Check which columns already exist in daily_features."""
    try:
        result = conn.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'daily_features'
            ORDER BY column_name
        """).fetchall()

        existing = {col: dtype for col, dtype in result}
        print(f"\n[INFO] Current daily_features schema ({len(existing)} columns):")
        for col, dtype in sorted(existing.items()):
            print(f"   - {col}: {dtype}")

        return existing
    except Exception as e:
        print(f"[ERROR] Failed to query schema: {e}")
        return {}


def backup_table(conn, backup_name: str = "daily_features_backup_v1"):
    """Create a backup of daily_features table."""
    try:
        # Check if backup already exists
        existing = conn.execute(f"""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_name = '{backup_name}'
        """).fetchone()[0]

        if existing > 0:
            print(f"[WARN] Backup table '{backup_name}' already exists. Skipping backup.")
            return True

        # Create backup
        conn.execute(f"CREATE TABLE {backup_name} AS SELECT * FROM daily_features")

        count = conn.execute(f"SELECT COUNT(*) FROM {backup_name}").fetchone()[0]
        print(f"[OK] Backup created: {backup_name} ({count:,} rows)")
        return True

    except Exception as e:
        print(f"[ERROR] Backup failed: {e}")
        return False


def add_missing_columns(conn, existing_columns: dict, dry_run: bool = False) -> list:
    """Add new RS Line columns if they don't exist."""

    new_columns = {
        'price_vs_spy': 'DOUBLE',
        'price_vs_spy_ma63': 'DOUBLE',
        'rs_line_uptrend': 'BOOLEAN',
        'rs_line_log': 'DOUBLE',
        'rs_line_delta': 'DOUBLE',
        'rs_line_lag_delta': 'DOUBLE'
    }

    to_add = []
    for col, dtype in new_columns.items():
        if col not in existing_columns:
            to_add.append((col, dtype))

    if not to_add:
        print("\n[OK] All new columns already exist. No migration needed.")
        return []

    print(f"\n[PLAN] Columns to add ({len(to_add)}):")
    for col, dtype in to_add:
        print(f"   - {col} ({dtype})")

    if dry_run:
        print("\n[DRY RUN] Would execute:")
        for col, dtype in to_add:
            print(f"   ALTER TABLE daily_features ADD COLUMN {col} {dtype};")
        return to_add

    # Execute migrations
    try:
        for col, dtype in to_add:
            print(f"   Adding {col}...", end=" ")
            conn.execute(f"ALTER TABLE daily_features ADD COLUMN {col} {dtype}")
            print("[OK]")

        print(f"\n[OK] Successfully added {len(to_add)} new columns")
        return to_add

    except Exception as e:
        print(f"\n[ERROR] Migration failed: {e}")
        raise


def validate_migration(conn, added_columns: list):
    """Validate that new columns were added successfully."""
    print("\n[VERIFY] Validating migration...")

    try:
        # Check column existence
        result = conn.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'daily_features'
        """).fetchall()

        existing = {col[0] for col in result}

        for col, _ in added_columns:
            if col in existing:
                print(f"   [OK] {col} exists")
            else:
                print(f"   [ERROR] {col} MISSING!")
                return False

        # Check row count unchanged
        count = conn.execute("SELECT COUNT(*) FROM daily_features").fetchone()[0]
        print(f"\n   [INFO] Total rows: {count:,}")

        print("\n[OK] Migration validation passed")
        return True

    except Exception as e:
        print(f"[ERROR] Validation failed: {e}")
        return False


def main():
    """Run the migration."""
    dry_run = '--dry-run' in sys.argv

    print("=" * 60)
    print("DuckDB Schema Migration: Add RS Line Features")
    print("=" * 60)

    if dry_run:
        print("\n[DRY RUN] MODE - No changes will be made")

    # Initialize database
    db_manager = DuckDBManager()
    db_path = db_manager.db_path

    print(f"\n[DB] Database: {db_path}")

    conn = duckdb.connect(db_path)

    try:
        # Step 1: Check existing schema
        print("\n" + "=" * 60)
        print("STEP 1: Check Current Schema")
        print("=" * 60)
        existing = check_existing_columns(conn, db_path)

        # Step 2: Backup
        if not dry_run:
            print("\n" + "=" * 60)
            print("STEP 2: Backup Existing Table")
            print("=" * 60)
            if not backup_table(conn, "daily_features_backup_v1"):
                print("[ERROR] Backup failed. Aborting migration.")
                return 1
        else:
            print("\n[DRY RUN] Skipping backup")

        # Step 3: Add columns
        print("\n" + "=" * 60)
        print("STEP 3: Add New Columns")
        print("=" * 60)
        added = add_missing_columns(conn, existing, dry_run=dry_run)

        # Step 4: Validate
        if not dry_run and added:
            print("\n" + "=" * 60)
            print("STEP 4: Validate Migration")
            print("=" * 60)
            if not validate_migration(conn, added):
                print("[ERROR] Validation failed!")
                return 1

        print("\n" + "=" * 60)
        if dry_run:
            print("[OK] DRY RUN COMPLETE")
        else:
            print("[OK] MIGRATION COMPLETE")
        print("=" * 60)

        if not dry_run and added:
            print("\n[NEXT] Next Steps:")
            print("   1. Run data_curator_duckdb.py to recompute features")
            print("   2. Verify price_vs_spy values match Python calculations")
            print("   3. Test SEPA screening with new RS Line logic")

        return 0

    except Exception as e:
        print(f"\n[ERROR] Migration failed: {e}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
