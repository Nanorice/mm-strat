"""Forward shadow book — what the champion WOULD do if followed live.

Replays the champion (or any registry strategy that passes ChampionBook's
supported-config check) through the forward step-engine from `--start-date` to
the latest day with data, then persists:
  - shadow_book   : one row per open position (the book AS OF the latest day)
  - shadow_action : append-only "what it did" (enter/target1/target2/stop/trend/
                    regime_liquidation), keyed by book_id + date

Design: **replay-to-today, not incremental serialization.** The book is a pure
function of (scores, prices, regime) over the window, and a few hundred days
replays in seconds — cheaper and far less fragile than pickling live
PositionTracker state. So every run is idempotent: it recomputes the full book
and rewrites the two tables for this book_id. (The plan's "catch-up then
incremental" is the same observable result; replay is the lazy, correct form.)

Fill/warmup/rule fidelity is guaranteed by tests/test_forward_parity.py — this
script is a thin CLI over forward_engine + population's score/price loaders.

Usage:
    python scripts/run_shadow_book.py --strategy champion --start-date 2024-01-01
    python scripts/run_shadow_book.py --strategy champion --start-date 2024-01-01 --book-id champ_live
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

from src import db
from src.backtest import strategy_registry as reg
from src.backtest.forward_engine import ChampionBook, build_price_frame
from src.backtest.score_lookup import prototype_scores_to_contract
from scripts.run_strategy_confirm import CACHE, DB_PATH

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

SMA_PERIOD = 50  # must match the backtest feed / forward engine warmup


def _load_scores(signal: str, start: str, end: str) -> pd.DataFrame:
    df = pd.read_parquet(CACHE[signal], columns=["date", "ticker", "prob_elite", "calibrated_score"])
    df["date"] = pd.to_datetime(df["date"])
    df = df[(df["date"] >= start) & (df["date"] <= end)]
    return prototype_scores_to_contract(df)


def _load_prices(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    placeholders = ",".join(f"'{t}'" for t in tickers)
    con = db.connect(str(DB_PATH), read_only=True)
    try:
        df = con.execute(f"""
            SELECT date, ticker,
                   CAST(open AS DOUBLE) AS open, CAST(high AS DOUBLE) AS high,
                   CAST(low AS DOUBLE) AS low, CAST(close AS DOUBLE) AS close,
                   CAST(volume AS BIGINT) AS volume
            FROM price_data
            WHERE ticker IN ({placeholders}) AND date >= ? AND date <= ?
            ORDER BY ticker, date
        """, [start, end]).fetchdf()
    finally:
        con.close()
    df["date"] = pd.to_datetime(df["date"])
    return df


def _load_regime(start: str, end: str) -> dict:
    con = db.connect(str(DB_PATH), read_only=True)
    try:
        df = con.execute("""
            SELECT date, CASE
                WHEN m03_score >= 75 THEN 4 WHEN m03_score >= 55 THEN 3
                WHEN m03_score >= 35 THEN 2 WHEN m03_score >= 15 THEN 1 ELSE 0 END AS regime_cat
            FROM t2_regime_scores WHERE date >= ? AND date <= ? ORDER BY date
        """, [start, end]).fetchdf()
    finally:
        con.close()
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"].dt.dayofweek < 5]
    return {d.date(): int(c) for d, c in zip(df["date"], df["regime_cat"])}


def replay(strategy: str, start_date: str, end_date: str):
    """Replay the book from start_date. Warmup is PER-TICKER (a name is tradeable
    once its own SMA50 is defined — build_price_frame leaves sma50 NaN for its
    first 49 bars and the engine skips trend-exit on NaN). This intentionally
    differs from the backtest's all-feed global warmup (see test_forward_parity):
    for a live book, one late IPO must not freeze the whole book."""
    d = reg.get(strategy)
    signal = d.signal
    logger.info("Shadow replay %s (%s) %s..%s", d.name, d.fingerprint, start_date, end_date)

    scores = _load_scores(signal, start_date, end_date)
    tickers = sorted(scores["ticker"].unique().tolist())
    prices = _load_prices(tickers, start_date, end_date)
    price_frame = build_price_frame(prices, sma_period=SMA_PERIOD)
    regime_map = _load_regime(start_date, end_date)

    book = ChampionBook(strategy_kwargs=d.strategy_kwargs, scores_df=scores, initial_cash=25_000.0)
    book.set_regime_series(regime_map)

    actions = []
    for day in sorted(regime_map.keys()):
        day_prices = price_frame[price_frame["date"].dt.date == day]
        if day_prices.empty:
            continue
        day_scores = scores[pd.to_datetime(scores["date"]).dt.date == day]
        actions += book.step(day, day_scores, day_prices)

    return book, actions, price_frame


def _ensure_tables(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS shadow_book (
            book_id VARCHAR NOT NULL, strategy VARCHAR NOT NULL, as_of DATE NOT NULL,
            ticker VARCHAR NOT NULL, entry_date DATE, entry_price DOUBLE,
            remaining_shares INTEGER, current_stop DOUBLE, target1 DOUBLE, target2 DOUBLE,
            tranche1_sold BOOLEAN, tranche2_sold BOOLEAN,
            PRIMARY KEY (book_id, ticker)
        )""")
    con.execute("""
        CREATE TABLE IF NOT EXISTS shadow_action (
            book_id VARCHAR NOT NULL, strategy VARCHAR NOT NULL, date DATE NOT NULL,
            ticker VARCHAR NOT NULL, kind VARCHAR NOT NULL, shares INTEGER,
            price DOUBLE, reason VARCHAR, pnl_pct DOUBLE
        )""")


def persist(book, actions, book_id: str, strategy: str, as_of) -> None:
    con = db.connect(str(DB_PATH))  # write
    try:
        _ensure_tables(con)
        # Idempotent per book_id: rewrite this book's rows entirely.
        con.execute("DELETE FROM shadow_book WHERE book_id = ?", [book_id])
        con.execute("DELETE FROM shadow_action WHERE book_id = ?", [book_id])

        book_rows = [{
            "book_id": book_id, "strategy": strategy, "as_of": as_of, "ticker": p.ticker,
            "entry_date": pd.Timestamp(p.entry_date).date() if p.entry_date else None,
            "entry_price": p.entry_price, "remaining_shares": p.remaining_shares,
            "current_stop": p.current_stop, "target1": p.target1, "target2": p.target2,
            "tranche1_sold": p.tranche1_sold, "tranche2_sold": p.tranche2_sold,
        } for p in book.tracker.get_all_open()]
        if book_rows:
            con.register("df_book", pd.DataFrame(book_rows))
            con.execute("INSERT INTO shadow_book SELECT * FROM df_book")

        act_rows = [{
            "book_id": book_id, "strategy": strategy,
            "date": a.date.date() if hasattr(a.date, "date") else a.date,
            "ticker": a.ticker, "kind": a.kind, "shares": a.shares, "price": a.price,
            "reason": a.reason, "pnl_pct": a.pnl_pct,
        } for a in actions]
        if act_rows:
            con.register("df_act", pd.DataFrame(act_rows))
            con.execute("INSERT INTO shadow_action SELECT * FROM df_act")
    finally:
        con.close()
    logger.info("Persisted book_id=%s: %d open positions, %d actions",
                book_id, len(book.tracker.get_all_open()), len(actions))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Forward shadow book (live champion monitor)")
    p.add_argument("--strategy", default="champion", help=f"Registry name. Known: {sorted(reg.STRATEGIES)}")
    p.add_argument("--start-date", required=True, help="Book inception (also the replay start).")
    p.add_argument("--end-date", default=None, help="Latest day (default: cache max).")
    p.add_argument("--book-id", default=None, help="Book key (default: <strategy>_default).")
    p.add_argument("--no-persist", action="store_true", help="Replay + print only, no DB write.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    end_date = args.end_date or "2026-05-31"
    book_id = args.book_id or f"{args.strategy}_default"

    book, actions, price_frame = replay(args.strategy, args.start_date, end_date)
    as_of = max(a.date for a in actions) if actions else pd.Timestamp(end_date).date()

    print("\n" + "=" * 66)
    print(f"SHADOW BOOK — {args.strategy} — book_id={book_id} — as_of {as_of}")
    print(f"  open positions: {len(book.tracker.get_all_open())}   "
          f"actions logged: {len(actions)}   cash: ${book.cash:,.0f}")
    for p in book.tracker.get_all_open():
        print(f"    HOLD {p.ticker:6s} {p.remaining_shares:>6d}sh @ {p.entry_price:.2f} "
              f"stop {p.current_stop:.2f} t1={'[x]' if p.tranche1_sold else '[ ]'}")
    print("=" * 66)

    if not args.no_persist:
        persist(book, actions, book_id, args.strategy, as_of)


if __name__ == "__main__":
    main()
