"""
T1 Price Data Cleanup — F3
---------------------------
Removes rows with non-positive close prices from price_data.

Root cause: Historical ingestion before the close <= 0 validation guard was
added. The affected tickers (VATE, CBIO, VHI) have valid recent data — this
purge removes only the sign-flipped historical artifact rows, not the tickers.

Run (dry-run first):
    python tools/purge_t1_price_negatives.py --dry-run
    python tools/purge_t1_price_negatives.py
"""

import argparse
import sys

import duckdb

sys.path.insert(0, ".")
from config import DUCKDB_PATH


def audit(con: duckdb.DuckDBPyConnection) -> dict:
    rows = con.execute("""
        SELECT ticker,
               COUNT(*) AS bad_rows,
               MIN(date) AS first_bad,
               MAX(date) AS last_bad,
               ROUND(MIN(close), 4) AS min_close,
               ROUND(MAX(close), 4) AS max_close
        FROM price_data
        WHERE close IS NULL OR close <= 0
        GROUP BY ticker
        ORDER BY bad_rows DESC
    """).fetchall()
    return {r[0]: {"bad_rows": r[1], "first_bad": r[2], "last_bad": r[3],
                   "min_close": r[4], "max_close": r[5]} for r in rows}


def purge(con: duckdb.DuckDBPyConnection) -> int:
    return con.execute("""
        DELETE FROM price_data WHERE close IS NULL OR close <= 0
    """).rowcount


def main() -> None:
    parser = argparse.ArgumentParser(description="Purge non-positive close prices from price_data (F3)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting")
    args = parser.parse_args()

    con = duckdb.connect(str(DUCKDB_PATH), read_only=args.dry_run)
    try:
        findings = audit(con)
        total_bad = sum(v["bad_rows"] for v in findings.values())

        if not findings:
            print("[OK] No non-positive close prices found — nothing to do.")
            return

        print(f"Found {total_bad} rows with close <= 0 across {len(findings)} tickers:\n")
        for ticker, v in findings.items():
            print(f"  {ticker:8s}  {v['bad_rows']:5d} rows  "
                  f"{v['first_bad']} to {v['last_bad']}  "
                  f"close range [{v['min_close']}, {v['max_close']}]")

        if args.dry_run:
            print(f"\n[DRY RUN] Would delete {total_bad} rows. Re-run without --dry-run to apply.")
            return

        deleted = purge(con)
        print(f"\n[OK] Deleted {deleted} rows.")

        remaining = con.execute("SELECT COUNT(*) FROM price_data WHERE close IS NULL OR close <= 0").fetchone()[0]
        if remaining == 0:
            print("[OK] price_data clean — no non-positive close rows remain.")
        else:
            print(f"[WARN] {remaining} non-positive close rows still remain after purge.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
