"""
Reclassify company_profiles.ticker_type using EDGAR form types.

CEFs/BDCs/registered funds (N-CSR/NPORT/...) and foreign filers (20-F/40-F/6-K)
are typed EQUITY by default, so they sit in the equity fundamentals cohort that
the yfinance 10-Q/10-K path can never satisfy. They pollute the stale-fundamentals
DQ check and waste a fetch every run. EDGAR form type is the authoritative signal:
this script classifies each ticker and writes back FUND / FOREIGN where warranted.

Tickers that file 10-Q/10-K stay EQUITY. Tickers with no CIK or inconclusive
submissions are left unchanged.

By default it operates on the CURRENT stale-fundamentals cohort (the names the
DQ check flags) — the population this fix is meant to clean. Use --all-equities
for a full universe pass.

Each --execute run appends one JSONL row per reclassification to
logs/data_quality/ticker_type_reclass.jsonl (db_before / edgar_forms / db_after).

Usage:
    python scripts/enrich_ticker_types_edgar.py                  # dry-run, stale cohort
    python scripts/enrich_ticker_types_edgar.py --execute        # apply, stale cohort
    python scripts/enrich_ticker_types_edgar.py --all-equities   # dry-run, full universe
    python scripts/enrich_ticker_types_edgar.py --tickers TY EIC ZNB   # specific names
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import duckdb

sys.path.append(str(Path(__file__).parent.parent))

from config import DUCKDB_PATH, FUNDAMENTAL_STALENESS_DAYS, EXPECTED_NEXT_FILING_LAG_DAYS
from src.edgar_engine import EDGAREngine

AUDIT_LOG = Path(__file__).parent.parent / "logs" / "data_quality" / "ticker_type_reclass.jsonl"


def get_stale_cohort(conn: duckdb.DuckDBPyConnection) -> List[str]:
    """Active EQUITY-typed tickers the DQ staleness check currently flags.

    Mirrors orchestrator._check_filing_date_quality: anchor on the most recent
    period_end that has an actual filing; flag when the next quarter is overdue.
    """
    rows = conn.execute(f"""
        WITH eq AS (
            SELECT ticker FROM company_profiles
            WHERE is_active AND COALESCE(ticker_type, 'EQUITY') = 'EQUITY'
        ),
        latest AS (
            SELECT ticker,
                   MAX(filing_date) AS last_filing,
                   MAX(period_end) FILTER (WHERE filing_date IS NOT NULL) AS last_filed_pe
            FROM fundamentals
            WHERE ticker IN (SELECT ticker FROM eq)
            GROUP BY ticker
        )
        SELECT ticker FROM latest
        WHERE CASE
            WHEN last_filed_pe IS NOT NULL
                THEN DATE_DIFF('day', last_filed_pe, CURRENT_DATE) > {int(EXPECTED_NEXT_FILING_LAG_DAYS)}
            ELSE last_filing IS NULL
                 OR DATE_DIFF('day', last_filing, CURRENT_DATE) > {int(FUNDAMENTAL_STALENESS_DAYS)}
        END
        ORDER BY ticker
    """).fetchall()
    return [r[0] for r in rows]


def get_all_equities(conn: duckdb.DuckDBPyConnection) -> List[str]:
    rows = conn.execute("""
        SELECT ticker FROM company_profiles
        WHERE is_active AND COALESCE(ticker_type, 'EQUITY') = 'EQUITY'
        ORDER BY ticker
    """).fetchall()
    return [r[0] for r in rows]


def current_type(conn: duckdb.DuckDBPyConnection, ticker: str) -> Optional[str]:
    row = conn.execute(
        "SELECT ticker_type FROM company_profiles WHERE ticker = ?", [ticker]
    ).fetchone()
    return row[0] if row else None


def append_audit(record: Dict) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, separators=(",", ":")) + "\n")


def run(tickers: List[str], execute: bool) -> None:
    prefix = "" if execute else "[DRY RUN] "
    engine = EDGAREngine()
    event_ts = datetime.now(timezone.utc).isoformat()

    print(f"{prefix}Classifying {len(tickers)} tickers via EDGAR form types...")
    classified = engine.classify_ticker_types(tickers)  # {ticker: EQUITY|FOREIGN|FUND}

    # Only act on tickers whose authoritative type differs from EQUITY.
    reclass = {t: ty for t, ty in classified.items() if ty != 'EQUITY'}
    stay_equity = sum(1 for ty in classified.values() if ty == 'EQUITY')
    inconclusive = len(tickers) - len(classified)

    print(f"  EQUITY (confirmed 10-Q/10-K): {stay_equity}")
    print(f"  Reclassify (FOREIGN/FUND):    {len(reclass)}")
    print(f"  Inconclusive / no CIK:        {inconclusive}")

    if not reclass:
        print(f"\n{prefix}Nothing to reclassify.")
        return

    by_type: Dict[str, List[str]] = {}
    for t, ty in sorted(reclass.items()):
        by_type.setdefault(ty, []).append(t)
    print()
    for ty, names in by_type.items():
        print(f"  {ty} ({len(names)}): {', '.join(names)}")

    conn = duckdb.connect(str(DUCKDB_PATH))
    try:
        for ticker, new_type in sorted(reclass.items()):
            before = current_type(conn, ticker)
            if before == new_type:
                continue
            if execute:
                conn.execute(
                    "UPDATE company_profiles SET ticker_type = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE ticker = ?",
                    [new_type, ticker],
                )
                append_audit({
                    "event_ts":    event_ts,
                    "ticker":      ticker,
                    "type_before": before,
                    "type_after":  new_type,
                    "source":      "edgar_form_type",
                })
        if execute:
            conn.commit()
    finally:
        conn.close()

    print(f"\n{prefix}{'Wrote' if execute else 'Would write'} {len(reclass)} reclassifications"
          + (f" -> {AUDIT_LOG}" if execute else " (use --execute to apply)"))


def main() -> None:
    ap = argparse.ArgumentParser(description="Reclassify ticker_type via EDGAR form types")
    ap.add_argument("--tickers", nargs="+", help="Specific tickers (overrides cohort selection)")
    ap.add_argument("--all-equities", action="store_true",
                    help="Classify the full active-equity universe (default: stale cohort only)")
    ap.add_argument("--execute", action="store_true", help="Apply changes (default: dry-run)")
    args = ap.parse_args()

    conn = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        if args.tickers:
            tickers = args.tickers
        elif args.all_equities:
            tickers = get_all_equities(conn)
        else:
            tickers = get_stale_cohort(conn)
    finally:
        conn.close()

    if not tickers:
        print("No tickers to classify.")
        return

    run(tickers, execute=args.execute)


if __name__ == "__main__":
    main()
