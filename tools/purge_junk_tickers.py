"""
Purge non-tradeable tickers (warrants, units, rights, preferred, SPACs).

Blacklisted tickers are deleted from company_profiles, price_data, and all
downstream tables. ticker_blacklist is the permanent record — once blacklisted,
a ticker is never re-added to company_profiles.

Also removes all pre-2000 junk rows from price_data.
"""
import duckdb
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

DB_PATH = str(Path(__file__).parent.parent / "data" / "market_data.duckdb")


def identify_purge_candidates(conn: duckdb.DuckDBPyConnection) -> list[str]:
    """Identify non-tradeable tickers still in company_profiles."""
    rows = conn.execute("""
        SELECT DISTINCT cp.ticker
        FROM company_profiles cp
        WHERE cp.ticker LIKE '%-WT' OR cp.ticker LIKE '%-WT%'
           OR cp.ticker LIKE '%-UN' OR cp.ticker LIKE '%-UN%'
           OR cp.ticker LIKE '%-RI' OR cp.ticker LIKE '%-RI%'
           OR cp.ticker LIKE '%-P_' OR cp.ticker LIKE '%-P__'
           OR cp.ticker LIKE '%*'
           OR cp.ticker = 'MTEST-A'
           OR LOWER(cp.name) LIKE '%acquisition%'
           OR LOWER(cp.name) LIKE '%spac%'
           OR LOWER(cp.name) LIKE '%blank check%'
           OR LOWER(cp.name) LIKE '%merger%'
           OR LENGTH(cp.ticker) > 5
    """).fetchall()
    return [r[0] for r in rows]


def run(dry_run: bool = True):
    conn = duckdb.connect(DB_PATH)

    # Step 1: Blacklist + delete non-tradeable tickers
    purge_tickers = identify_purge_candidates(conn)
    print(f"[1/3] Non-tradeable tickers to purge: {len(purge_tickers)}")

    if dry_run and purge_tickers:
        for t in purge_tickers[:30]:
            print(f"  {t}")
        if len(purge_tickers) > 30:
            print(f"  ... +{len(purge_tickers) - 30} more")

    if not dry_run and purge_tickers:
        # Add to blacklist (permanent record)
        for t in purge_tickers:
            conn.execute(
                "INSERT OR IGNORE INTO ticker_blacklist (ticker, reason) VALUES (?, 'non_tradeable_security')",
                [t]
            )
        # Delete from company_profiles
        conn.execute("""
            DELETE FROM company_profiles
            WHERE ticker IN (SELECT unnest(?::VARCHAR[]))
        """, [purge_tickers])
        # Delete from price_data
        price_del = conn.execute("""
            DELETE FROM price_data
            WHERE ticker IN (SELECT unnest(?::VARCHAR[]))
        """, [purge_tickers]).fetchone()
        print(f"  Blacklisted {len(purge_tickers)} tickers, deleted {price_del[0] if price_del else 0} price rows")

    # Step 2: Enforce blacklist — delete any blacklisted tickers lingering in company_profiles
    lingering = conn.execute("""
        SELECT COUNT(*) FROM company_profiles
        WHERE ticker IN (SELECT ticker FROM ticker_blacklist)
    """).fetchone()[0]
    if lingering > 0:
        print(f"\n[2/3] Blacklisted tickers still in company_profiles: {lingering}")
        if not dry_run:
            conn.execute("""
                DELETE FROM company_profiles
                WHERE ticker IN (SELECT ticker FROM ticker_blacklist)
            """)
            print(f"  Deleted {lingering} rows")
    else:
        print(f"\n[2/3] No blacklisted tickers in company_profiles [OK]")

    # Step 3: Purge pre-2000 junk rows
    junk_count = conn.execute(
        "SELECT COUNT(*) FROM price_data WHERE date < '2000-01-01'"
    ).fetchone()[0]
    print(f"\n[3/3] Junk rows (date < 2000-01-01): {junk_count}")

    if not dry_run and junk_count > 0:
        conn.execute("DELETE FROM price_data WHERE date < '2000-01-01'")
        print(f"  Deleted {junk_count} junk rows")

    # Summary
    cp = conn.execute("SELECT COUNT(*) FROM company_profiles").fetchone()[0]
    bl = conn.execute("SELECT COUNT(*) FROM ticker_blacklist").fetchone()[0]
    pd_count = conn.execute("SELECT COUNT(DISTINCT ticker) FROM price_data").fetchone()[0]

    print(f"\nUniverse summary:")
    print(f"  company_profiles: {cp}")
    print(f"  ticker_blacklist: {bl}")
    print(f"  price_data:       {pd_count} tickers")

    conn.close()

    if dry_run:
        print("\n[DRY RUN] No changes made. Run with --execute to apply.")


if __name__ == "__main__":
    execute = "--execute" in sys.argv
    run(dry_run=not execute)
