import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import duckdb
from src import db
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "market_data.duckdb"


class SharesEngine:
    """Fetches and stores shares_outstanding from Yahoo Finance (batch).

    Table: shares_history (ticker, date, shares_outstanding) — PK (ticker, date).
    Uses yf.Tickers() batch API for shared session/cookie — ~20x faster than
    individual FMP calls.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = str(db_path or DEFAULT_DB_PATH)

    def ensure_table(self) -> None:
        con = db.connect(self.db_path)
        try:
            con.execute("""
                CREATE TABLE IF NOT EXISTS shares_history (
                    ticker VARCHAR NOT NULL,
                    date DATE NOT NULL,
                    shares_outstanding BIGINT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (ticker, date)
                )
            """)
        finally:
            con.close()

    # ------------------------------------------------------------------
    # Fetch (yfinance batch)
    # ------------------------------------------------------------------

    def _fetch_batch_yf(
        self, tickers: List[str], as_of_date: str = None, batch_size: int = 200
    ) -> pd.DataFrame:
        """Fetch current shares_outstanding via yf.Tickers() in batches."""
        import yfinance as yf

        rows: List[Dict] = []
        total = len(tickers)
        record_date = as_of_date or datetime.now().strftime("%Y-%m-%d")
        success = 0

        for batch_start in range(0, total, batch_size):
            batch = tickers[batch_start:batch_start + batch_size]
            batch_str = " ".join(batch)

            try:
                yf_batch = yf.Tickers(batch_str)
                for symbol, ticker_obj in yf_batch.tickers.items():
                    try:
                        info = ticker_obj.info
                        shares = info.get("sharesOutstanding")
                        if shares and shares > 0:
                            rows.append({
                                "ticker": symbol.upper(),
                                "date": record_date,
                                "shares_outstanding": int(shares),
                            })
                            success += 1
                    except Exception as e:
                        logger.debug(f"yfinance shares failed for {symbol}: {e}")
            except Exception as e:
                logger.warning(f"yfinance batch failed (offset {batch_start}): {e}")

            if batch_start + batch_size < total:
                time.sleep(1)

            if (batch_start + batch_size) % 1000 < batch_size:
                logger.info(
                    f"[SharesEngine] {min(batch_start + batch_size, total)}/{total} tickers processed"
                )

        logger.info(f"Shares: {success}/{total} tickers returned data")

        if not rows:
            return pd.DataFrame(columns=["ticker", "date", "shares_outstanding"])

        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"]).dt.date
        return df

    # ------------------------------------------------------------------
    # Write to DuckDB
    # ------------------------------------------------------------------

    def _upsert(self, df: pd.DataFrame) -> int:
        if df.empty:
            return 0

        con = db.connect(self.db_path)
        try:
            con.execute("""
                INSERT INTO shares_history (ticker, date, shares_outstanding)
                SELECT ticker, date, shares_outstanding
                FROM df
                ON CONFLICT (ticker, date) DO UPDATE SET
                    shares_outstanding = EXCLUDED.shares_outstanding,
                    updated_at = NOW()
            """)
            con.commit()
            return len(df)
        except Exception as e:
            logger.error(f"Shares DuckDB write failed: {e}")
            return 0
        finally:
            con.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    FRESHNESS_DAYS = 7  # shares outstanding barely changes day-to-day

    def update(self, tickers: List[str], latest_trading_day: str = None, max_workers: int = 8) -> int:
        """Fetch current shares_outstanding for stale tickers (batch yfinance).

        Staleness: any ticker without a shares_history row in the last
        FRESHNESS_DAYS is considered stale. Window is anchored to today
        (not trading day) because shares outstanding is a point-in-time
        snapshot, not a market-hours value.

        Args:
            tickers: Active ticker list from company_profiles.
            latest_trading_day: Used as the record date for new rows.
        """
        self.ensure_table()
        t0 = time.perf_counter()

        today = datetime.now()
        record_date = latest_trading_day or today.strftime("%Y-%m-%d")
        cutoff = (today - pd.Timedelta(days=self.FRESHNESS_DAYS)).strftime("%Y-%m-%d")

        con = db.connect(self.db_path)
        try:
            fresh = set(r[0] for r in con.execute(
                "SELECT DISTINCT ticker FROM shares_history WHERE date >= ?", [cutoff]
            ).fetchall())
        finally:
            con.close()

        stale = [t for t in tickers if t not in fresh]
        if not stale:
            logger.info(f"[SharesEngine] All {len(tickers)} tickers fresh (within {self.FRESHNESS_DAYS}d)")
            return 0

        logger.info(f"[SharesEngine] {len(stale)} tickers to update (skipping {len(fresh)} fresh within {self.FRESHNESS_DAYS}d)")

        df = self._fetch_batch_yf(stale, as_of_date=record_date)
        rows = self._upsert(df)

        elapsed = time.perf_counter() - t0
        logger.info(f"{rows:,} shares records written in {elapsed:.1f}s")
        return rows

    def backfill(self, tickers: List[str], max_workers: int = 8) -> int:
        """Snapshot current shares for all tickers (yfinance only provides current values)."""
        self.ensure_table()
        t0 = time.perf_counter()

        df = self._fetch_batch_yf(tickers)
        rows = self._upsert(df)

        elapsed = time.perf_counter() - t0
        logger.info(f"Backfilled {rows:,} shares records in {elapsed:.1f}s")
        return rows
