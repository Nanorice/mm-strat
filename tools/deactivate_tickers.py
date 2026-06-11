"""
Mark tickers as inactive in company_profiles (delisted, acquired, etc.).

Historical data is preserved — only is_active is set to FALSE so the
pipeline stops ingesting new data for these tickers.

Each --execute run probes yfinance for evidence and appends one JSONL row
per ticker to logs/data_quality/deactivations.jsonl. Row includes db_before
state, yfinance probe result, db_after state, and the operator-supplied
--reason.

Usage:
    python tools/deactivate_tickers.py FPAY IMAB ZYXI                              # dry-run
    python tools/deactivate_tickers.py FPAY --execute --reason "delisted 2026-05"  # apply + log
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import duckdb

sys.path.append(str(Path(__file__).parent.parent))

DB_PATH       = str(Path(__file__).parent.parent / "data" / "market_data.duckdb")
AUDIT_LOG     = Path(__file__).parent.parent / "logs" / "data_quality" / "deactivations.jsonl"
YF_PROBE_DAYS = 10


def probe_yfinance(ticker: str) -> Dict[str, Optional[object]]:
    """Hit yfinance once. Return {has_recent_data, last_yf_bar, probe_error}."""
    try:
        import yfinance as yf
    except ImportError as e:
        return {"has_recent_data": None, "last_yf_bar": None, "probe_error": f"yfinance_import: {e}"}
    try:
        hist = yf.Ticker(ticker).history(period=f"{YF_PROBE_DAYS}d")
    except Exception as e:
        return {"has_recent_data": None, "last_yf_bar": None, "probe_error": str(e)[:200]}
    if hist is None or hist.empty:
        return {"has_recent_data": False, "last_yf_bar": None, "probe_error": None}
    return {
        "has_recent_data": True,
        "last_yf_bar":     hist.index[-1].date().isoformat(),
        "probe_error":     None,
    }


def db_snapshot(conn: duckdb.DuckDBPyConnection, ticker: str) -> Optional[Dict]:
    row = conn.execute("""
        SELECT ticker, name, is_active, delisting_date, updated_at
        FROM company_profiles WHERE ticker = ?
    """, [ticker]).fetchone()
    if not row:
        return None
    last_px = conn.execute(
        "SELECT MAX(date) FROM price_data WHERE ticker = ?", [ticker]
    ).fetchone()[0]
    return {
        "ticker":         row[0],
        "name":           row[1],
        "is_active":      bool(row[2]),
        "delisting_date": row[3].isoformat() if row[3] else None,
        "last_db_px":     last_px.isoformat() if last_px else None,
    }


def append_audit(record: Dict) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, separators=(",", ":")) + "\n")


def run(tickers: list[str], dry_run: bool, reason: Optional[str]) -> None:
    conn = duckdb.connect(DB_PATH)
    prefix = "[DRY RUN] " if dry_run else ""
    event_ts = datetime.now(timezone.utc).isoformat()
    actioned = skipped = missing = 0

    for ticker in tickers:
        before = db_snapshot(conn, ticker)
        if before is None:
            print(f"  {ticker}: not found in company_profiles -- skipping")
            missing += 1
            continue
        if not before["is_active"]:
            print(f"  {ticker} ({before['name']}): already inactive")
            skipped += 1
            continue

        print(f"  {prefix}{ticker} ({before['name']}): active -> inactive "
              f"(last db px: {before['last_db_px']})")

        if dry_run:
            continue

        # Live yfinance probe — captured BEFORE the DB write so the evidence
        # reflects the state we relied on when deciding to deactivate.
        yf_evidence = probe_yfinance(ticker)

        conn.execute("""
            UPDATE company_profiles
            SET is_active = FALSE, delisting_date = CURRENT_DATE
            WHERE ticker = ?
        """, [ticker])
        conn.commit()

        after = db_snapshot(conn, ticker)

        append_audit({
            "event_ts":   event_ts,
            "ticker":     ticker,
            "reason":     reason,
            "db_before":  before,
            "yf_evidence": yf_evidence,
            "db_after":   after,
        })
        actioned += 1

    if dry_run:
        print(f"\n[DRY RUN] {len(tickers) - skipped - missing} would be deactivated, "
              f"{skipped} already inactive, {missing} missing. Pass --execute to apply.")
    else:
        print(f"\n[OK] {actioned} deactivated, {skipped} already inactive, {missing} missing.")
        print(f"     Audit log: {AUDIT_LOG}")

    # Summary
    active = conn.execute("SELECT COUNT(*) FROM company_profiles WHERE is_active = TRUE").fetchone()[0]
    inactive = conn.execute("SELECT COUNT(*) FROM company_profiles WHERE is_active = FALSE").fetchone()[0]
    print(f"\nUniverse: {active} active, {inactive} inactive")
    conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mark tickers inactive with audit log.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("tickers", nargs="+", help="Tickers to deactivate")
    parser.add_argument("--execute", action="store_true",
                        help="Apply changes (default: dry-run)")
    parser.add_argument("--reason", type=str, default=None,
                        help="Reason for deactivation (required with --execute)")
    args = parser.parse_args()

    if args.execute and not args.reason:
        parser.error("--reason is required when --execute is set")

    tickers = [t.strip().upper() for t in args.tickers if t.strip()]
    run(tickers, dry_run=not args.execute, reason=args.reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
