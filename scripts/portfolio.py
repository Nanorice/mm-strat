#!/usr/bin/env python3
"""Hand-entered trade log — the book of record for real money.

Usage:
    python scripts/portfolio.py deposit  --amount 500000 --date 2026-01-02
    python scripts/portfolio.py buy  NVDA --qty 100 --price 178.40 --date 2026-07-16
    python scripts/portfolio.py sell NVDA --qty 40  --price 191.05 --date 2026-07-16
    python scripts/portfolio.py withdraw --amount 10000
    python scripts/portfolio.py positions
    python scripts/portfolio.py positions --all       # include closed
    python scripts/portfolio.py trades  --ticker NVDA
    python scripts/portfolio.py nav                   # snapshot today's NAV

The log is APPEND-ONLY: correct a mistake by appending an offsetting fill, never
by editing a row. NAV = cash + positions; cash derives from deposits/withdrawals
plus the fills themselves, so it can never drift out of sync with the log.

Console output is ASCII-only on purpose: this runs under a cp1252 console where
a non-ASCII glyph raises UnicodeEncodeError *after* the DB write has committed --
the trade lands but the command looks like it crashed.
"""
import argparse
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.managers.portfolio_manager import PortfolioManager


def _date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> None:
    parser = argparse.ArgumentParser(description="Hand-entered portfolio trade log")
    parser.add_argument("--db", default="data/market_data.duckdb", help="Path to DuckDB file")
    sub = parser.add_subparsers(dest="cmd", required=True)

    for side in ("buy", "sell"):
        p = sub.add_parser(side, help=f"Append a {side.upper()} fill")
        p.add_argument("ticker")
        p.add_argument("--qty", type=float, required=True)
        p.add_argument("--price", type=float, required=True)
        p.add_argument("--date", type=_date, default=date.today(), help="YYYY-MM-DD (default: today)")
        p.add_argument("--fees", type=float, default=0.0)
        p.add_argument("--note")

    for kind in ("deposit", "withdraw"):
        p = sub.add_parser(kind, help=f"Record an external cash {kind}")
        p.add_argument("--amount", type=float, required=True)
        p.add_argument("--date", type=_date, default=date.today(), help="YYYY-MM-DD (default: today)")
        p.add_argument("--note")

    p = sub.add_parser("positions", help="Derived positions, marked to latest close")
    p.add_argument("--all", action="store_true", help="Include closed positions")

    p = sub.add_parser("trades", help="Raw fill log")
    p.add_argument("--ticker")

    sub.add_parser("nav", help="Snapshot today's NAV into nav_history")

    args = parser.parse_args()
    pm = PortfolioManager(args.db)

    if args.cmd in ("buy", "sell"):
        # A mistyped fill is user error, not a crash: show the reason, not a traceback.
        try:
            tid = pm.add_trade(args.ticker, args.date, args.cmd.upper(), args.qty,
                               args.price, args.fees, args.note)
        except ValueError as e:
            sys.exit(f"[ERR] {e}")
        held = pm.position_qty(args.ticker)
        gross = args.qty * args.price
        print(f"[OK] #{tid}  {args.cmd.upper()} {args.qty:g} {args.ticker.upper()} "
              f"@ {args.price:,.2f}  ({gross:,.2f}"
              f"{f' + {args.fees:,.2f} fees' if args.fees else ''})")
        print(f"   position now: {held:g} {args.ticker.upper()}")

    elif args.cmd in ("deposit", "withdraw"):
        kind = "DEPOSIT" if args.cmd == "deposit" else "WITHDRAW"
        try:
            fid = pm.add_cash_flow(args.date, kind, args.amount, args.note)
        except ValueError as e:
            sys.exit(f"[ERR] {e}")
        print(f"[OK] #{fid}  {kind} {args.amount:,.2f} on {args.date}")
        print(f"   cash now: {pm.cash():,.2f}")

    elif args.cmd == "positions":
        df = pm.positions(open_only=not args.all)
        if df.empty:
            print("No positions. Add one:  python scripts/portfolio.py buy TICKER --qty N --price P")
            return
        show = df[["ticker", "qty", "avg_cost", "close", "market_value",
                   "unrealized_pnl", "pct_return", "price_date"]].copy()
        print(show.to_string(index=False, float_format=lambda v: f"{v:,.2f}"))
        cash = pm.cash()
        print(f"\n   market value: {df['market_value'].sum():,.2f}"
              f"   cash: {cash:,.2f}"
              f"   NAV: {cash + df['market_value'].sum():,.2f}"
              f"   unrealized: {df['unrealized_pnl'].sum():,.2f}")
        if df["close"].isna().any():
            missing = ", ".join(df.loc[df["close"].isna(), "ticker"])
            print(f"   ⚠️  no price_data for: {missing} (excluded from the totals above)")

    elif args.cmd == "trades":
        df = pm.trades(ticker=args.ticker)
        print(df.to_string(index=False) if not df.empty else "No trades logged.")

    elif args.cmd == "nav":
        nav = pm.snapshot_nav()
        print(f"[OK] NAV snapshot: {nav:,.2f}")


if __name__ == "__main__":
    main()
