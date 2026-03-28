"""
Rename/merge tickers across all DuckDB tables.

Handles two cases:
  1. Simple rename: old ticker exists, new doesn't -> UPDATE ticker
  2. Merge: both exist -> move old history into new (INSERT OR IGNORE), delete old

Usage:
    python tools/rename_tickers.py POAI:AGPU LPTX:CYPH KAR:OPLN
    python tools/rename_tickers.py POAI:AGPU --execute

Dry-run by default. Pass --execute to apply.
"""
import sys
from pathlib import Path

import duckdb

sys.path.append(str(Path(__file__).parent.parent))

DB_PATH = str(Path(__file__).parent.parent / "data" / "market_data.duckdb")

# Tables with (ticker, date_col) composite key — date_col varies per table
DATED_TABLES = {
    "price_data":           "date",
    "fundamentals":         "period_end",
    "shares_history":       "date",
    "earnings_calendar":    "earnings_date",
    "daily_features":       "date",
    "t2_screener_features": "date",
    "t3_sepa_features":     "date",
}

# Tables with ticker only (or ticker + non-date key)
OTHER_TABLES = [
    "company_profiles",
    "screener_members",
]

ALL_TABLES = list(DATED_TABLES.keys()) + OTHER_TABLES


def parse_renames(args: list[str]) -> list[tuple[str, str]]:
    renames = []
    for arg in args:
        if ":" not in arg:
            continue
        old, new = arg.split(":", 1)
        renames.append((old.strip().upper(), new.strip().upper()))
    return renames


def get_table_columns(conn: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    return [r[0] for r in conn.execute(f"""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = '{table}' ORDER BY ordinal_position
    """).fetchall()]


def run(renames: list[tuple[str, str]], dry_run: bool = True):
    conn = duckdb.connect(DB_PATH)
    prefix = "[DRY RUN] " if dry_run else ""

    existing = {r[0] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()}

    for old, new in renames:
        print(f"\n{prefix}Rename: {old} -> {new}")

        for table in ALL_TABLES:
            if table not in existing:
                continue
            cols = get_table_columns(conn, table)
            if "ticker" not in cols:
                continue

            old_count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE ticker = ?", [old]
            ).fetchone()[0]
            if old_count == 0:
                continue

            new_count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE ticker = ?", [new]
            ).fetchone()[0]

            if new_count == 0:
                # Simple rename — no conflict possible
                print(f"  {table}: {old_count} rows -> UPDATE ticker")
                if not dry_run:
                    conn.execute(f"UPDATE {table} SET ticker = ? WHERE ticker = ?", [new, old])
            elif table == "company_profiles":
                # Keep old profile (longer history), delete new
                print(f"  {table}: DELETE new ({new}), RENAME old ({old} -> {new})")
                if not dry_run:
                    conn.execute("DELETE FROM company_profiles WHERE ticker = ?", [new])
                    conn.execute("UPDATE company_profiles SET ticker = ? WHERE ticker = ?", [new, old])
            elif table in DATED_TABLES:
                date_col = DATED_TABLES[table]
                # Merge: delete overlapping new rows, rename old -> new
                print(f"  {table}: MERGE {old_count} old + {new_count} new (old wins on overlap, key={date_col})")
                if not dry_run:
                    conn.execute(
                        f"DELETE FROM {table} WHERE ticker = ? AND {date_col} IN "
                        f"(SELECT {date_col} FROM {table} WHERE ticker = ?)",
                        [new, old]
                    )
                    conn.execute(f"UPDATE {table} SET ticker = ? WHERE ticker = ?", [new, old])
            else:
                # screener_members etc — delete new, rename old
                print(f"  {table}: DELETE {new_count} new, RENAME {old_count} old ({old} -> {new})")
                if not dry_run:
                    conn.execute(f"DELETE FROM {table} WHERE ticker = ?", [new])
                    conn.execute(f"UPDATE {table} SET ticker = ? WHERE ticker = ?", [new, old])

    if not dry_run:
        conn.commit()
        print("\n[OK] All renames applied.")
    else:
        print("\n[DRY RUN] No changes made. Pass --execute to apply.")

    conn.close()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--execute"]
    execute = "--execute" in sys.argv

    renames = parse_renames(args)
    if not renames:
        print("Usage: python tools/rename_tickers.py OLD:NEW [OLD:NEW ...] [--execute]")
        print("Example: python tools/rename_tickers.py POAI:AGPU LPTX:CYPH KAR:OPLN")
        sys.exit(1)

    print(f"Renames: {renames}")
    run(renames, dry_run=not execute)
