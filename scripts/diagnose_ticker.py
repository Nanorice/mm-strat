"""Diagnose why a ticker entered/exited the SEPA watchlist.

Usage:
    python scripts/diagnose_ticker.py ROST
    python scripts/diagnose_ticker.py LUNR --days 20
    python scripts/diagnose_ticker.py ROST --start 2026-03-01 --end 2026-03-28
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).parent.parent))
from src.screener_diagnostics import ScreenerDiagnostics


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose ticker SEPA criteria")
    parser.add_argument("ticker", type=str, help="Ticker symbol")
    parser.add_argument("--days", type=int, default=15, help="Lookback days (default: 15)")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    args = parser.parse_args()

    pd.set_option("display.width", 260)
    pd.set_option("display.max_columns", 20)

    diag = ScreenerDiagnostics()
    result = diag.diagnose(args.ticker, start=args.start, end=args.end, days=args.days)

    if result["criteria"].empty:
        print(f"No t2_screener_features data for {result['ticker']} in this range.")
        sys.exit(1)

    diag.print_report(result)


if __name__ == "__main__":
    main()
