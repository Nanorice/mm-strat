"""
Mark tickers as inactive in company_profiles (delisted, acquired, etc.).

Historical data is preserved — only is_active is set to FALSE so the
pipeline stops ingesting new data for these tickers.

Usage:
    python tools/deactivate_tickers.py FPAY IMAB ZYXI
    python tools/deactivate_tickers.py FPAY --execute

Dry-run by default. Pass --execute to apply.
"""
import sys
from pathlib import Path

import duckdb

sys.path.append(str(Path(__file__).parent.parent))

DB_PATH = str(Path(__file__).parent.parent / "data" / "market_data.duckdb")


def run(tickers: list[str], dry_run: bool = True):
    conn = duckdb.connect(DB_PATH)
    prefix = "[DRY RUN] " if dry_run else ""

    for ticker in tickers:
        row = conn.execute(
            "SELECT ticker, name, is_active FROM company_profiles WHERE ticker = ?", [ticker]
        ).fetchone()

        if not row:
            print(f"  {ticker}: not found in company_profiles -- skipping")
            continue

        if not row[2]:
            print(f"  {ticker} ({row[1]}): already inactive")
            continue

        last_price = conn.execute(
            "SELECT MAX(date) FROM price_data WHERE ticker = ?", [ticker]
        ).fetchone()[0]

        print(f"  {prefix}{ticker} ({row[1]}): active -> inactive (last price: {last_price})")
        if not dry_run:
            conn.execute("""
                UPDATE company_profiles
                SET is_active = FALSE, delisting_date = CURRENT_DATE
                WHERE ticker = ?
            """, [ticker])

    if not dry_run:
        conn.commit()
        print("\n[OK] Tickers deactivated.")
    else:
        print("\n[DRY RUN] No changes made. Pass --execute to apply.")

    # Summary
    active = conn.execute("SELECT COUNT(*) FROM company_profiles WHERE is_active = TRUE").fetchone()[0]
    inactive = conn.execute("SELECT COUNT(*) FROM company_profiles WHERE is_active = FALSE").fetchone()[0]
    print(f"\nUniverse: {active} active, {inactive} inactive")

    conn.close()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--execute"]
    execute = "--execute" in sys.argv

    tickers = [t.strip().upper() for t in args if t.strip()]
    if not tickers:
        print("Usage: python tools/deactivate_tickers.py TICKER [TICKER ...] [--execute]")
        print("Example: python tools/deactivate_tickers.py FPAY IMAB ZYXI")
        sys.exit(1)

    run(tickers, dry_run=not execute)
