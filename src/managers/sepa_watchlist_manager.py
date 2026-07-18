"""
SepaWatchlistManager — event log of SEPA sessions per ticker.

Purpose
-------
Defines the T3 universe gate: any ticker that has ever entered a SEPA session
appears in `sepa_watchlist`. T3 then carries full history for those tickers
(not just SEPA-active days) — see compute_t3_features().

This is the SINGLE session store (2026-07-18 merge): `screener_watchlist` is now
a thin display VIEW over this table (ViewManager) — it no longer derives its own
sessions. One derivation, one truth.

Session model
-------------
A session represents one continuous SEPA setup → trend break cycle:

    entry_date    — first day where (trend_ok AND breakout_ok) AND no open session
    exit_date     — first day where the trend boundary breaks
                    (close < sma_50 OR close < sma_150 OR close < sma_200)
                    NOTE: uses C1+C2+C6 only, not full trend_ok (avoids C9 RS
                    flicker fragmenting one long session into many short ones)
    session_id    — monotonic per ticker, 1-based

Sessions never overlap per ticker, but there is NO re-entry cool-down: a
re-trigger the day after an exit is a new session. Cool-down was demoted from a
write-time gate to a read-time concern (2026-07-18) — where episode-dedup
matters (e.g. label work), derive it:
    is_retrigger := entry_date - LAG(exit_date) OVER (PARTITION BY ticker
                    ORDER BY entry_date) <= 14 days
Rationale: the pipeline's only structural consumer (T3 universe gate) reads
DISTINCT ticker; a write-time drop destroys re-trigger information for every
other consumer and silently thinned the population vs the training grain.

Two execution paths
-------------------
    backfill()        — vectorised SQL over full t2 history; authoritative rebuild.
    update_daily(d)   — incremental single-date update for the daily pipeline.
"""

import logging
from typing import Optional

import duckdb
from src import db
import pandas as pd

logger = logging.getLogger(__name__)


class SepaWatchlistManager:
    """Manages sepa_watchlist event log for the T3 universe gate."""

    def __init__(self, db_path: str):
        self.db_path = str(db_path)
        with db.connect(self.db_path) as conn:
            self._ensure_schema(conn)

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _ensure_schema(self, conn: duckdb.DuckDBPyConnection) -> None:
        # status is ACTIVE (exit_date NULL) or EXITED — the COOLDOWN state and
        # cooldown_end column were removed 2026-07-18 (see module docstring).
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sepa_watchlist (
                ticker        VARCHAR  NOT NULL,
                entry_date    DATE     NOT NULL,
                exit_date     DATE,
                session_id    INTEGER  NOT NULL,
                trend_ok      BOOLEAN,
                breakout_ok   BOOLEAN,
                status        VARCHAR  NOT NULL,
                updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ticker, entry_date)
            )
        """)

    # ------------------------------------------------------------------
    # Backfill — vectorised candidate extraction
    # ------------------------------------------------------------------

    def backfill(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict:
        """
        Rebuild sepa_watchlist from full t2 history.

        Strategy:
          1. SQL extracts sessions via gaps-and-islands on the trend-active
             flag (close > sma_50/150/200). Each session has an entry_date
             (first entry_signal day inside the trend run) and an exit_date
             (first day after the trend run ends; NULL if still active at
             end_date).
          2. Bulk INSERT — every session is kept (no cool-down gate).

        Returns:
            {'sessions': int, 'tickers': int, 'active': int, 'exited': int}
        """
        with db.connect(self.db_path) as conn:
            if start_date is None:
                start_date = conn.execute(
                    "SELECT MIN(date)::VARCHAR FROM t2_screener_features"
                ).fetchone()[0]
            if end_date is None:
                end_date = conn.execute(
                    "SELECT MAX(date)::VARCHAR FROM t2_screener_features"
                ).fetchone()[0]

            logger.info(f"[SepaWatchlist] Backfill {start_date} → {end_date}")

            # Wipe and rebuild — backfill is authoritative. DROP (not DELETE)
            # so a pre-2026-07-18 table loses its cooldown_end column too.
            conn.execute("DROP TABLE IF EXISTS sepa_watchlist")
            self._ensure_schema(conn)

            candidates = conn.execute(f"""
                WITH base AS (
                    SELECT
                        ticker,
                        date,
                        (close > sma_50 AND close > sma_150 AND close > sma_200) AS trend_active,
                        (trend_ok AND breakout_ok) AS entry_signal
                    FROM t2_screener_features
                    WHERE date BETWEEN '{start_date}' AND '{end_date}'
                      AND sma_50 IS NOT NULL
                      AND sma_150 IS NOT NULL
                      AND sma_200 IS NOT NULL
                ),
                with_prev AS (
                    SELECT *,
                        LAG(trend_active) OVER (PARTITION BY ticker ORDER BY date) AS prev_active
                    FROM base
                ),
                runs AS (
                    -- Gaps-and-islands: each maximal trend_active=TRUE streak gets one run_id.
                    -- Streak starts when prev was FALSE/NULL; cumulative SUM of starts = run_id.
                    SELECT *,
                        SUM(CASE WHEN trend_active = TRUE AND COALESCE(prev_active, FALSE) = FALSE
                                 THEN 1 ELSE 0 END) OVER (PARTITION BY ticker ORDER BY date) AS run_id
                    FROM with_prev
                ),
                trend_runs AS (
                    SELECT * FROM runs WHERE trend_active = TRUE
                ),
                run_bounds AS (
                    SELECT
                        ticker,
                        run_id,
                        MIN(date) AS run_start,
                        MAX(date) AS run_end,
                        MIN(CASE WHEN entry_signal THEN date END) AS entry_date
                    FROM trend_runs
                    GROUP BY ticker, run_id
                    HAVING entry_date IS NOT NULL  -- run must contain at least one entry_signal
                ),
                with_exit AS (
                    -- exit_date = first trading day inside [start_date, end_date] with
                    -- date > run_end for this ticker. If no such day exists in the window
                    -- (the trend run extends to end_date), exit_date is NULL — the session
                    -- is still considered active as of end_date.
                    SELECT
                        rb.ticker,
                        rb.entry_date,
                        rb.run_end,
                        (
                            SELECT MIN(t.date) FROM t2_screener_features t
                            WHERE t.ticker = rb.ticker
                              AND t.date > rb.run_end
                              AND t.date <= '{end_date}'
                        ) AS exit_date
                    FROM run_bounds rb
                )
                SELECT ticker, entry_date, exit_date
                FROM with_exit
                ORDER BY ticker, entry_date
            """).fetchdf()

            logger.info(f"[SepaWatchlist] Extracted {len(candidates):,} sessions")

            if len(candidates) == 0:
                return {'sessions': 0, 'tickers': 0, 'active': 0, 'exited': 0}

            # session_id: monotonic per ticker by entry order (candidates arrive
            # ordered by ticker, entry_date from the SQL above)
            candidates['session_id'] = candidates.groupby('ticker').cumcount() + 1
            candidates['exit_date'] = candidates['exit_date'].where(
                candidates['exit_date'].notna(), None
            )

            # Compute current state for each session relative to end_date
            accepted = self._annotate_state(conn, candidates, end_date)

            # Bulk insert
            conn.register('accepted_df', accepted)
            conn.execute("""
                INSERT INTO sepa_watchlist
                    (ticker, entry_date, exit_date, session_id,
                     trend_ok, breakout_ok, status)
                SELECT ticker, entry_date, exit_date, session_id,
                       trend_ok, breakout_ok, status
                FROM accepted_df
            """)
            conn.unregister('accepted_df')

            counts = conn.execute("""
                SELECT
                    COUNT(*) AS sessions,
                    COUNT(DISTINCT ticker) AS tickers,
                    COUNT(*) FILTER (WHERE status = 'ACTIVE') AS active,
                    COUNT(*) FILTER (WHERE status = 'EXITED') AS exited
                FROM sepa_watchlist
            """).fetchone()

        result = {
            'sessions': counts[0], 'tickers': counts[1],
            'active':   counts[2], 'exited':  counts[3],
        }
        logger.info(f"[SepaWatchlist] Backfill complete: {result}")
        return result

    # ------------------------------------------------------------------
    # State annotation — derive trend_ok / breakout_ok / status as of end_date
    # ------------------------------------------------------------------

    def _annotate_state(
        self,
        conn: duckdb.DuckDBPyConnection,
        sessions: pd.DataFrame,
        as_of_date: str,
    ) -> pd.DataFrame:
        """
        Add trend_ok / breakout_ok / status columns to sessions.

        - Active sessions (exit_date is NULL): pull current trend_ok/breakout_ok
          from t2_screener_features as of as_of_date. Status='ACTIVE'.
        - Closed sessions: trend_ok/breakout_ok=FALSE. Status='EXITED'.
        """
        as_of = pd.to_datetime(as_of_date).date()

        sessions = sessions.copy()
        sessions['trend_ok']    = False
        sessions['breakout_ok'] = False

        active_mask = sessions['exit_date'].isna()
        if active_mask.any():
            active_tickers = sessions.loc[active_mask, 'ticker'].tolist()
            conn.register('active_tk', pd.DataFrame({'ticker': active_tickers}))
            latest = conn.execute(f"""
                SELECT t.ticker, t.trend_ok, t.breakout_ok
                FROM t2_screener_features t
                INNER JOIN active_tk a USING (ticker)
                WHERE t.date = (
                    SELECT MAX(date) FROM t2_screener_features t2
                    WHERE t2.ticker = t.ticker AND t2.date <= '{as_of}'
                )
            """).fetchdf()
            conn.unregister('active_tk')

            latest_map = latest.set_index('ticker')[['trend_ok', 'breakout_ok']].to_dict('index')
            for idx in sessions.index[active_mask]:
                tk = sessions.at[idx, 'ticker']
                if tk in latest_map:
                    sessions.at[idx, 'trend_ok']    = bool(latest_map[tk]['trend_ok'])
                    sessions.at[idx, 'breakout_ok'] = bool(latest_map[tk]['breakout_ok'])

        sessions['status'] = sessions['exit_date'].map(
            lambda v: 'ACTIVE' if pd.isna(v) else 'EXITED'
        )
        return sessions

    # ------------------------------------------------------------------
    # Incremental — single-date update
    # ------------------------------------------------------------------

    def update_daily(self, target_date: str) -> dict:
        """
        Apply one trading day's worth of session events.

        Three operations on `target_date`:
          1. Close any open session whose trend boundary breaks on target_date.
             (close < sma_50 OR close < sma_150 OR close < sma_200)
             Sets exit_date=target_date, status='EXITED'.
          2. Open a new session for any (ticker) where trend_ok AND breakout_ok
             on target_date AND no open session.
          3. Refresh trend_ok/breakout_ok for ACTIVE sessions.

        Returns:
            {'opened': int, 'closed': int, 'active': int}
        """
        with db.connect(self.db_path) as conn:
            # Verify target_date has t2 data
            n_t2 = conn.execute(
                f"SELECT COUNT(*) FROM t2_screener_features WHERE date = '{target_date}'"
            ).fetchone()[0]
            if n_t2 == 0:
                logger.warning(f"[SepaWatchlist] No t2 data for {target_date}; skipping")
                return {'opened': 0, 'closed': 0, 'active': 0}

            # Step 1: close sessions whose trend boundary breaks today
            closed = conn.execute(f"""
                WITH breaking AS (
                    SELECT t.ticker
                    FROM t2_screener_features t
                    WHERE t.date = '{target_date}'
                      AND (t.close < t.sma_50 OR t.close < t.sma_150 OR t.close < t.sma_200)
                ),
                to_close AS (
                    SELECT w.ticker, w.entry_date
                    FROM sepa_watchlist w
                    INNER JOIN breaking b USING (ticker)
                    WHERE w.exit_date IS NULL
                )
                UPDATE sepa_watchlist
                SET exit_date    = DATE '{target_date}',
                    status       = 'EXITED',
                    trend_ok     = FALSE,
                    breakout_ok  = FALSE,
                    updated_at   = CURRENT_TIMESTAMP
                WHERE (ticker, entry_date) IN (SELECT ticker, entry_date FROM to_close)
                RETURNING ticker
            """).fetchall()
            n_closed = len(closed)

            # Step 2: open new sessions
            opened = conn.execute(f"""
                WITH eligible AS (
                    SELECT t.ticker
                    FROM t2_screener_features t
                    WHERE t.date = '{target_date}'
                      AND t.trend_ok = TRUE
                      AND t.breakout_ok = TRUE
                ),
                no_open AS (
                    SELECT e.ticker
                    FROM eligible e
                    WHERE NOT EXISTS (
                        SELECT 1 FROM sepa_watchlist w
                        WHERE w.ticker = e.ticker AND w.exit_date IS NULL
                    )
                ),
                next_session AS (
                    SELECT n.ticker,
                           COALESCE(MAX(w.session_id), 0) + 1 AS session_id
                    FROM no_open n
                    LEFT JOIN sepa_watchlist w USING (ticker)
                    GROUP BY n.ticker
                )
                INSERT INTO sepa_watchlist
                    (ticker, entry_date, exit_date, session_id,
                     trend_ok, breakout_ok, status)
                SELECT ticker, DATE '{target_date}', NULL, session_id,
                       TRUE, TRUE, 'ACTIVE'
                FROM next_session
                RETURNING ticker
            """).fetchall()
            n_opened = len(opened)

            # Step 3: refresh trend_ok/breakout_ok for active sessions (other than just-opened)
            conn.execute(f"""
                UPDATE sepa_watchlist w
                SET trend_ok    = COALESCE(t.trend_ok, FALSE),
                    breakout_ok = COALESCE(t.breakout_ok, FALSE),
                    updated_at  = CURRENT_TIMESTAMP
                FROM t2_screener_features t
                WHERE w.exit_date IS NULL
                  AND t.ticker = w.ticker
                  AND t.date = DATE '{target_date}'
            """)

            active = conn.execute(
                "SELECT COUNT(*) FROM sepa_watchlist WHERE status = 'ACTIVE'"
            ).fetchone()[0]

        result = {
            'opened': n_opened,
            'closed': n_closed,
            'active': active,
        }
        logger.info(
            f"[SepaWatchlist] {target_date}: +{n_opened} opened, -{n_closed} closed, "
            f"{active} active"
        )
        return result

    # ------------------------------------------------------------------
    # Universe lookup
    # ------------------------------------------------------------------

    def get_universe(self) -> list[str]:
        """All tickers that have ever entered a SEPA session — the T3 universe."""
        with db.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT ticker FROM sepa_watchlist ORDER BY ticker"
            ).fetchall()
        return [r[0] for r in rows]

    def get_stats(self) -> dict:
        """Quick summary for monitoring."""
        with db.connect(self.db_path) as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*)                                AS sessions,
                    COUNT(DISTINCT ticker)                  AS tickers,
                    COUNT(*) FILTER (WHERE status='ACTIVE') AS active,
                    COUNT(*) FILTER (WHERE status='EXITED') AS exited,
                    MIN(entry_date)                         AS earliest_entry,
                    MAX(entry_date)                         AS latest_entry
                FROM sepa_watchlist
            """).fetchone()
        return {
            'sessions':       row[0],
            'tickers':        row[1],
            'active':         row[2],
            'exited':         row[3],
            'earliest_entry': row[4],
            'latest_entry':   row[5],
        }
