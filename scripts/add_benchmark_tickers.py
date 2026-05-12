"""
Phase 0 — Schema migration + ETF/INDEX ticker enrollment.

Idempotent. Run once (or any time tickers in config are added/changed).

Operations:
  1. ADD COLUMN company_profiles.ticker_type (default 'EQUITY')
  2. Cleanup: replace empty-string sector with NULL
  3. Mark sector-less rows as ticker_type='UNKNOWN' (the 17 misfits)
  4. INSERT/UPDATE non-equity tickers (BENCHMARK + SECTOR + COMMODITY + FIXED_INCOME)
  5. Register screener_criteria_versions row for ticker_type bypass marker (version 0)

After this script: run scripts/backfill_benchmark_prices.py to fetch price history.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

import duckdb
import config
from config import NON_EQUITY_UNIVERSE


DB_PATH = config.DATA_DIR / 'market_data.duckdb'


def ensure_ticker_type_column(conn: duckdb.DuckDBPyConnection) -> bool:
    cols = {r[0] for r in conn.execute("DESCRIBE company_profiles").fetchall()}
    if 'ticker_type' in cols:
        print("  [SKIP] ticker_type column already exists")
        return False
    conn.execute("ALTER TABLE company_profiles ADD COLUMN ticker_type VARCHAR DEFAULT 'EQUITY'")
    print("  [OK]   Added ticker_type column (default 'EQUITY')")
    return True


def cleanup_empty_sectors(conn: duckdb.DuckDBPyConnection) -> int:
    before = conn.execute(
        "SELECT COUNT(*) FROM company_profiles WHERE sector = ''"
    ).fetchone()[0]
    if before == 0:
        print("  [SKIP] No empty-string sectors to clean")
        return 0
    conn.execute("UPDATE company_profiles SET sector = NULL WHERE sector = ''")
    print(f"  [OK]   Replaced empty-string sector with NULL ({before} rows)")
    return before


def mark_unknown_tickers(conn: duckdb.DuckDBPyConnection) -> int:
    """
    Sector-less rows are typically delisted ETFs/funds/preferreds that snuck
    through FMP discovery. Mark them ticker_type='UNKNOWN' so they cannot be
    mistaken for equities downstream.
    """
    n = conn.execute("""
        UPDATE company_profiles
        SET ticker_type = 'UNKNOWN'
        WHERE sector IS NULL AND ticker_type = 'EQUITY'
    """).fetchone()
    affected = conn.execute("""
        SELECT COUNT(*) FROM company_profiles WHERE ticker_type = 'UNKNOWN'
    """).fetchone()[0]
    print(f"  [OK]   Marked {affected} sector-less rows as ticker_type='UNKNOWN'")
    return affected


def insert_non_equity_universe(conn: duckdb.DuckDBPyConnection) -> dict:
    """
    INSERT (or UPDATE on conflict) non-equity tickers from config.
    Sets ticker_type, sector, name, industry=NULL, is_active=TRUE.
    """
    by_type = {'ETF': 0, 'INDEX': 0}
    inserted = 0
    updated = 0

    for spec in NON_EQUITY_UNIVERSE:
        ticker = spec['ticker']
        name = spec['name']
        sector = spec['sector']
        ticker_type = spec['ticker_type']

        existing = conn.execute(
            "SELECT ticker_type FROM company_profiles WHERE ticker = ?", [ticker]
        ).fetchone()

        if existing is None:
            conn.execute("""
                INSERT INTO company_profiles
                    (ticker, name, sector, industry, country, exchange,
                     is_active, ticker_type)
                VALUES (?, ?, ?, NULL, 'US', NULL, TRUE, ?)
            """, [ticker, name, sector, ticker_type])
            inserted += 1
        else:
            conn.execute("""
                UPDATE company_profiles
                SET name        = ?,
                    sector      = ?,
                    industry    = NULL,
                    ticker_type = ?,
                    is_active   = TRUE,
                    updated_at  = CURRENT_TIMESTAMP
                WHERE ticker = ?
            """, [name, sector, ticker_type, ticker])
            updated += 1

        by_type[ticker_type] = by_type.get(ticker_type, 0) + 1

    print(f"  [OK]   Inserted {inserted} new non-equity tickers, updated {updated} existing")
    print(f"         By type: {by_type}")
    return {'inserted': inserted, 'updated': updated, 'by_type': by_type}


def ensure_etf_bypass_criteria_version(conn: duckdb.DuckDBPyConnection) -> None:
    """
    criteria_version=0 is the marker for ETF/INDEX bypass entries written by
    ScreenerManager.auto_enroll_non_equity(). It carries no real thresholds.
    """
    exists = conn.execute(
        "SELECT 1 FROM screener_criteria_versions WHERE version_id = 0"
    ).fetchone()
    if exists:
        print("  [SKIP] criteria_version=0 (ETF bypass) already registered")
        return
    conn.execute("""
        INSERT INTO screener_criteria_versions
            (version_id, effective_date, min_price, min_volume_20d, min_market_cap, notes)
        VALUES (0, DATE '1900-01-01', 0, 0, 0,
                'ETF/INDEX bypass — no price/volume/market_cap filter')
    """)
    print("  [OK]   Registered criteria_version=0 (ETF bypass)")


def print_summary(conn: duckdb.DuckDBPyConnection) -> None:
    print()
    print("=" * 60)
    print("[SUMMARY] company_profiles ticker_type distribution")
    print("=" * 60)
    rows = conn.execute("""
        SELECT ticker_type, COUNT(*) AS n
        FROM company_profiles
        GROUP BY ticker_type
        ORDER BY n DESC
    """).fetchall()
    for tt, n in rows:
        print(f"  {tt:<10s} {n:>6,}")

    print()
    print("[SUMMARY] non-equity tickers inserted")
    rows = conn.execute("""
        SELECT ticker, ticker_type, sector, name
        FROM company_profiles
        WHERE ticker_type IN ('ETF', 'INDEX')
        ORDER BY ticker_type, sector, ticker
    """).fetchall()
    for ticker, tt, sector, name in rows:
        print(f"  {ticker:<8s} {tt:<6s} {sector:<25s} {name}")
    print("=" * 60)


def auto_enroll_etfs_in_screener() -> None:
    """
    Synthetic screener_membership entries for ETF/INDEX tickers.
    Skipped if price_data is empty for a ticker — run after backfill_benchmark_prices.py.
    """
    from src.managers.screener_manager import ScreenerManager
    sm = ScreenerManager(str(DB_PATH))
    result = sm.auto_enroll_non_equity()
    print(f"  [OK]   ScreenerManager.auto_enroll_non_equity: "
          f"{result['enrolled']} enrolled, {result['skipped']} skipped, "
          f"{result['total']} total")


def main() -> None:
    print(f"Connecting to {DB_PATH}...")
    conn = duckdb.connect(str(DB_PATH))
    try:
        print()
        print("Step 1: Ensure ticker_type column")
        ensure_ticker_type_column(conn)

        print()
        print("Step 2: Cleanup empty-string sectors")
        cleanup_empty_sectors(conn)

        print()
        print("Step 3: Mark sector-less rows as UNKNOWN")
        mark_unknown_tickers(conn)

        print()
        print("Step 4: Insert non-equity universe")
        insert_non_equity_universe(conn)

        print()
        print("Step 5: Register ETF bypass criteria version")
        ensure_etf_bypass_criteria_version(conn)

        print_summary(conn)
    finally:
        conn.close()

    print()
    print("Step 6: Auto-enroll ETF/INDEX in screener_membership")
    auto_enroll_etfs_in_screener()


if __name__ == '__main__':
    main()
