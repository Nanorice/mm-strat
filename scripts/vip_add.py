"""CLI for the VIP watchlist — manually curate names to force into the T3 universe.

    vip_add.py add NVDA --source "semis report 7/13" --comment "AI capex, watching VCP"
    vip_add.py remove NVDA
    vip_add.py list [--all]

Add/remove is CLI-only by design — the dashboard reads the list read-only (it runs
against a slim synced DB it doesn't own). Names take effect on the next nightly T3
run, forward from the add date.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # repo root for config/src

import config
from src.managers.vip_watchlist_manager import VipWatchlistManager

DB_PATH = config.DATA_DIR / "market_data.duckdb"


def main() -> None:
    ap = argparse.ArgumentParser(description="Curate the VIP watchlist.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="add or re-activate a VIP ticker")
    a.add_argument("ticker")
    a.add_argument("--source", default="", help="where it came from (report/tip)")
    a.add_argument("--comment", default="", help="your thesis — why you added it")

    r = sub.add_parser("remove", help="soft-remove a VIP ticker (keeps history)")
    r.add_argument("ticker")

    ls = sub.add_parser("list", help="list VIP tickers")
    ls.add_argument("--all", action="store_true", help="include soft-removed names")

    args = ap.parse_args()
    m = VipWatchlistManager(str(DB_PATH))

    if args.cmd == "add":
        m.add(args.ticker, source=args.source, comment=args.comment)
        print(f"[OK] added {args.ticker.upper()} - takes effect next nightly T3 run (forward-only)")
    elif args.cmd == "remove":
        hit = m.remove(args.ticker)
        print(f"{'[OK] removed' if hit else '[WARN] not active'} {args.ticker.upper()}")
    elif args.cmd == "list":
        df = m.list(active_only=not args.all)
        if df.empty:
            print("(no VIP names)")
        else:
            print(df.to_string(index=False))


if __name__ == "__main__":
    main()
