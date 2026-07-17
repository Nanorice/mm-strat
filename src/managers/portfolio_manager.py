"""
PortfolioManager — append-only fill log of real trades, entered by hand.

Purpose
-------
The book of record for actual money. Distinct from the watchlist tables, which
are machine-generated candidate trackers:

    screener_watchlist — screener's auto-refreshed candidates (no quantity)
    sepa_watchlist     — universe gate for the pipeline
    trades             — hand-entered real fills (this file)

Fill-log model
--------------
`trades` is APPEND-ONLY: one row per fill, never edited in place. A position is
derived, not stored:

    qty       = SUM(+qty on BUY, -qty on SELL)
    avg_cost  = cost-weighted over BUY fills only
    open      = SUM(qty) != 0

This is what lets a position be scaled into and partially sold without a schema
change. Corrections are made by appending an offsetting fill, never an UPDATE —
the log stays a truthful history of what was actually done.

NAV
---
nav_history marks open positions to `price_data.close` and adds the cash leg:

    nav  = cash + SUM(qty x close)
    cash = SUM(deposits) - SUM(withdrawals)
           - SUM(buy cost + fees) + SUM(sell proceeds - fees)

Cash is DERIVED from `cash_flows` (external money in/out) plus the fills
themselves — never stored as a mutable balance, so it cannot drift out of sync
with the trade log.

Because external flows are separated from P&L, NAV IS a trustworthy return
series: a deposit raises both cash and NAV without inventing a gain. Return is
therefore measured TIME-WEIGHTED (`returns()`), which neutralises the timing and
size of contributions — the only basis comparable to a benchmark or a backtest
cone. A naive nav.pct_change() would still be corrupted by flow days; use
returns(), which strips the flow out of the day it lands on.
"""

import logging
from datetime import date
from typing import Optional

import pandas as pd

from src import db

logger = logging.getLogger(__name__)

SIDES = ("BUY", "SELL")


class PortfolioManager:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def ensure_schema(self) -> None:
        with db.connect(self.db_path) as conn:
            conn.execute("""
                CREATE SEQUENCE IF NOT EXISTS trades_id_seq START 1
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id   BIGINT PRIMARY KEY DEFAULT nextval('trades_id_seq'),
                    ticker     VARCHAR NOT NULL,
                    trade_date DATE    NOT NULL,
                    side       VARCHAR NOT NULL CHECK (side IN ('BUY','SELL')),
                    quantity   DOUBLE  NOT NULL CHECK (quantity > 0),
                    price      DOUBLE  NOT NULL CHECK (price > 0),
                    fees       DOUBLE  NOT NULL DEFAULT 0 CHECK (fees >= 0),
                    note       VARCHAR,
                    created_at TIMESTAMP DEFAULT now()
                )
            """)
            conn.execute("""
                CREATE SEQUENCE IF NOT EXISTS cash_flows_id_seq START 1
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cash_flows (
                    flow_id    BIGINT PRIMARY KEY DEFAULT nextval('cash_flows_id_seq'),
                    flow_date  DATE    NOT NULL,
                    kind       VARCHAR NOT NULL CHECK (kind IN ('DEPOSIT','WITHDRAW')),
                    amount     DOUBLE  NOT NULL CHECK (amount > 0),
                    note       VARCHAR,
                    created_at TIMESTAMP DEFAULT now()
                )
            """)
            # nav_history carries cash + flow so returns() can strip external
            # flows out of the day they land on (a deposit is not a gain).
            conn.execute("""
                CREATE TABLE IF NOT EXISTS nav_history (
                    date       DATE PRIMARY KEY,
                    nav        DOUBLE,
                    cash       DOUBLE,
                    positions_value DOUBLE,
                    net_flow   DOUBLE,
                    n_open     INTEGER,
                    updated_at TIMESTAMP DEFAULT now()
                )
            """)

    def add_trade(self, ticker: str, trade_date: date, side: str, quantity: float,
                  price: float, fees: float = 0.0, note: Optional[str] = None) -> int:
        """Append one fill. Returns the new trade_id.

        Validates at the trust boundary: this is hand-typed input for the book of
        record, so a fat-fingered SELL of stock never held must not land silently.
        """
        side = side.upper()
        if side not in SIDES:
            raise ValueError(f"side must be one of {SIDES}, got {side!r}")
        if quantity <= 0:
            raise ValueError(f"quantity must be > 0 (use side=SELL to reduce), got {quantity}")
        if price <= 0:
            raise ValueError(f"price must be > 0, got {price}")
        if fees < 0:
            raise ValueError(f"fees must be >= 0, got {fees}")

        ticker = ticker.upper().strip()
        self.ensure_schema()

        if side == "SELL":
            held = self.position_qty(ticker)
            if quantity > held + 1e-9:
                raise ValueError(
                    f"cannot SELL {quantity} {ticker}: only {held} held as of the log. "
                    f"Append the missing BUY first, or check the ticker."
                )

        with db.connect(self.db_path) as conn:
            row = conn.execute(
                """
                INSERT INTO trades (ticker, trade_date, side, quantity, price, fees, note)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                RETURNING trade_id
                """,
                [ticker, trade_date, side, quantity, price, fees, note],
            ).fetchone()
        return int(row[0])

    def add_cash_flow(self, flow_date: date, kind: str, amount: float,
                      note: Optional[str] = None) -> int:
        """Record external money in/out. Returns the new flow_id."""
        kind = kind.upper()
        if kind not in ("DEPOSIT", "WITHDRAW"):
            raise ValueError(f"kind must be DEPOSIT or WITHDRAW, got {kind!r}")
        if amount <= 0:
            raise ValueError(f"amount must be > 0 (use kind=WITHDRAW to remove), got {amount}")
        self.ensure_schema()
        with db.connect(self.db_path) as conn:
            row = conn.execute(
                "INSERT INTO cash_flows (flow_date, kind, amount, note) VALUES (?,?,?,?) RETURNING flow_id",
                [flow_date, kind, amount, note],
            ).fetchone()
        return int(row[0])

    def cash(self, as_of: Optional[date] = None) -> float:
        """Cash balance DERIVED from flows + fills — never a stored balance.

        Deriving it means cash can't drift out of sync with the trade log; a
        corrected fill automatically corrects cash.
        """
        self.ensure_schema()
        where_f = "WHERE flow_date <= ?" if as_of else ""
        where_t = "WHERE trade_date <= ?" if as_of else ""
        p = [as_of] if as_of else []
        with db.connect(self.db_path, read_only=True) as conn:
            flows = conn.execute(f"""
                SELECT COALESCE(SUM(CASE WHEN kind='DEPOSIT' THEN amount ELSE -amount END), 0)
                FROM cash_flows {where_f}
            """, p).fetchone()[0]
            fills = conn.execute(f"""
                SELECT COALESCE(SUM(CASE WHEN side='BUY' THEN -(quantity*price) - fees
                                         ELSE  (quantity*price) - fees END), 0)
                FROM trades {where_t}
            """, p).fetchone()[0]
        return float(flows) + float(fills)

    def returns(self) -> pd.DataFrame:
        """Daily TIME-WEIGHTED return series from nav_history.

        r_t = (nav_t - net_flow_t) / nav_{t-1} - 1

        Subtracting the day's external flow is what makes a deposit not a gain:
        a naive nav.pct_change() would book a 500k deposit as a 500k profit. TWR
        also neutralises contribution timing/size, which is what makes this series
        comparable to a benchmark or a backtest cone.
        """
        nav = self.nav_history()
        if len(nav) < 2:
            return pd.DataFrame(columns=["date", "ret", "cum_ret", "drawdown"])
        nav = nav.sort_values("date").reset_index(drop=True)
        prev = nav["nav"].shift(1)
        nav["ret"] = (nav["nav"] - nav["net_flow"].fillna(0)) / prev - 1
        nav = nav.iloc[1:].copy()
        curve = (1 + nav["ret"]).cumprod()
        nav["cum_ret"] = curve - 1
        # Anchor the peak at the series start (1.0), else the first day is always
        # its own peak and a fall from the opening NAV reports drawdown 0.
        nav["drawdown"] = curve / curve.cummax().clip(lower=1.0) - 1
        return nav[["date", "ret", "cum_ret", "drawdown"]]

    def nav_history(self) -> pd.DataFrame:
        """NAV rows, `date` as plain datetime.date (DuckDB hands back datetime64,
        which silently fails a .loc[date(...)] lookup)."""
        self.ensure_schema()
        with db.connect(self.db_path, read_only=True) as conn:
            df = conn.execute(
                "SELECT date, nav, cash, positions_value, net_flow, n_open "
                "FROM nav_history ORDER BY date"
            ).df()
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"]).dt.date
        return df

    def position_qty(self, ticker: str) -> float:
        """Net quantity currently held for one ticker (0 if never traded)."""
        self.ensure_schema()
        with db.connect(self.db_path, read_only=True) as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(CASE WHEN side='BUY' THEN quantity ELSE -quantity END), 0)
                FROM trades WHERE ticker = ?
                """,
                [ticker.upper().strip()],
            ).fetchone()
        return float(row[0]) if row else 0.0

    def trades(self, ticker: Optional[str] = None) -> pd.DataFrame:
        """Raw fill log, oldest first."""
        self.ensure_schema()
        sql = "SELECT trade_id, trade_date, ticker, side, quantity, price, fees, note FROM trades"
        params: list = []
        if ticker:
            sql += " WHERE ticker = ?"
            params.append(ticker.upper().strip())
        sql += " ORDER BY trade_date, trade_id"
        with db.connect(self.db_path, read_only=True) as conn:
            return conn.execute(sql, params).df()

    def positions(self, open_only: bool = True) -> pd.DataFrame:
        """Derive positions from the fill log, marked to the latest close.

        avg_cost is weighted over BUY fills only — the standard convention, so a
        partial sale does not distort the remaining lot's cost basis.
        """
        self.ensure_schema()
        # The fill-log derivation stands alone; marking to market is a separate
        # concern layered on top. If price_data is absent (a bare portfolio DB),
        # positions still resolve with a NULL mark rather than a CatalogException.
        with db.connect(self.db_path, read_only=True) as conn:
            has_px = conn.execute("""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_name = 'price_data'
            """).fetchone()[0] > 0
        px_cte = """
                SELECT ticker, close, date AS price_date,
                       ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
                FROM price_data
                WHERE ticker IN (SELECT ticker FROM agg) AND close IS NOT NULL
        """ if has_px else """
                SELECT NULL::VARCHAR AS ticker, NULL::DOUBLE AS close,
                       NULL::DATE AS price_date, 1 AS rn WHERE FALSE
        """
        sql = """
            WITH agg AS (
                SELECT ticker,
                       SUM(CASE WHEN side='BUY' THEN quantity ELSE -quantity END) AS qty,
                       SUM(CASE WHEN side='BUY' THEN quantity*price + fees END)
                         / NULLIF(SUM(CASE WHEN side='BUY' THEN quantity END), 0)  AS avg_cost,
                       MIN(trade_date) AS first_entry,
                       MAX(trade_date) AS last_fill,
                       COUNT(*)        AS n_fills,
                       SUM(fees)       AS fees
                FROM trades GROUP BY ticker
            ),
            px AS (""" + px_cte + """)
            SELECT a.ticker, a.qty, a.avg_cost, p.close, p.price_date,
                   a.qty * p.close                          AS market_value,
                   (p.close - a.avg_cost) * a.qty           AS unrealized_pnl,
                   (p.close / NULLIF(a.avg_cost,0) - 1)*100 AS pct_return,
                   a.first_entry, a.last_fill, a.n_fills, a.fees
            FROM agg a
            LEFT JOIN px p ON p.ticker = a.ticker AND p.rn = 1
        """
        if open_only:
            sql += " WHERE a.qty > 1e-9"
        sql += " ORDER BY market_value DESC NULLS LAST"
        with db.connect(self.db_path, read_only=True) as conn:
            return conn.execute(sql).df()

    def snapshot_nav(self, as_of: Optional[date] = None) -> float:
        """Mark open positions to close, add the cash leg, upsert one nav_history row.

        net_flow = the day's external deposits/withdrawals, stored so returns()
        can strip it out of that day (a deposit must not read as a gain).
        """
        self.ensure_schema()
        as_of = as_of or date.today()
        pos = self.positions(open_only=True)
        pos_val = float(pos["market_value"].sum()) if not pos.empty else 0.0
        cash = self.cash(as_of=as_of)
        nav = cash + pos_val
        n_open = int(len(pos))

        with db.connect(self.db_path) as conn:
            net_flow = conn.execute("""
                SELECT COALESCE(SUM(CASE WHEN kind='DEPOSIT' THEN amount ELSE -amount END), 0)
                FROM cash_flows WHERE flow_date = ?
            """, [as_of]).fetchone()[0]
            conn.execute("DELETE FROM nav_history WHERE date = ?", [as_of])
            conn.execute(
                "INSERT INTO nav_history (date, nav, cash, positions_value, net_flow, n_open)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [as_of, nav, cash, pos_val, float(net_flow), n_open],
            )
        logger.info(f"[portfolio] NAV {as_of}: {nav:,.2f} "
                    f"(cash {cash:,.2f} + positions {pos_val:,.2f}, {n_open} open)")
        return nav
