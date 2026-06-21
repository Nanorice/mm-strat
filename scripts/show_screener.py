"""CLI dashboard: show active SEPA screener trades."""
import argparse
from pathlib import Path

import duckdb

DB_PATH = Path("data/market_data.duckdb")


def show_active(db_path: Path = DB_PATH, sort_by: str = "entry_date") -> None:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        df = con.execute(f"""
            SELECT
                ticker,
                company_name,
                sector,
                industry,
                entry_date,
                ROUND(entry_price, 2) AS entry_price,
                ROUND(current_close, 2) AS current_close,
                ROUND(pct_return, 2) AS pct_return,
                days_held,
                ROUND(market_cap / 1e9, 2) AS mcap_bn
            FROM screener_watchlist
            WHERE status = 'ACTIVE'
            ORDER BY {sort_by} DESC, ticker
        """).fetchdf()
        if 'entry_date' in df.columns:
            df['entry_date'] = df['entry_date'].dt.strftime('%Y-%m-%d')
    finally:
        con.close()

    if df.empty:
        print("No active SEPA trades.")
        return

    # Format table
    print(f"\n{'='*110}")
    print(f"  SEPA Screener - Active Trades ({len(df)})")
    print(f"{'='*110}")
    print(f"{'Ticker':<8} {'Company':<30} {'Sector':<22} {'Entry Date':<12} "
          f"{'Entry':>8} {'Current':>8} {'Return%':>8} {'Days':>5} {'MCap$B':>7}")
    print(f"{'-'*110}")

    for _, r in df.iterrows():
        ret = r['pct_return']
        ret_str = f"{ret:+.2f}" if ret is not None and ret == ret else "  N/A"
        mcap = r['mcap_bn']
        mcap_str = f"{mcap:.1f}" if mcap is not None and mcap == mcap else "N/A"
        company = str(r['company_name'] or '')[:28]
        sector = str(r['sector'] or '')[:20]

        print(f"{r['ticker']:<8} {company:<30} {sector:<22} {r['entry_date']!s:<12} "
              f"{r['entry_price']:>8.2f} {r['current_close']:>8.2f} {ret_str:>8} "
              f"{r['days_held']:>5} {mcap_str:>7}")

    print(f"{'='*110}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Show active SEPA screener trades")
    parser.add_argument("--sort", default="entry_date",
                        choices=["entry_date", "pct_return", "ticker", "mcap_bn", "days_held"],
                        help="Sort column (default: entry_date)")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="DuckDB path")
    args = parser.parse_args()
    show_active(db_path=args.db, sort_by=args.sort)
