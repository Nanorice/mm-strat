"""
SepaWatchlistManager — event log of SEPA sessions per ticker.

Purpose
-------
Defines the T3 universe gate: any ticker that has ever entered a SEPA session
appears in `sepa_watchlist`. T3 then carries full history for those tickers
(not just SEPA-active days) — see compute_t3_features().

NOT to be confused with `screener_watchlist`, which is the materialised trade
log surfaced to the dashboard. Both coexist:
    sepa_watchlist     — universe gate for the pipeline (this file)
    screener_watchlist — trade log for the dashboard (ViewManager)

Session model
-------------
A session represents one continuous SEPA setup → trend break cycle:

    entry_date    — first day where (trend_ok AND breakout_ok) AND no open session
                    AND (no prior session OR today > prev.cooldown_end)
    exit_date     — first day where the trend boundary breaks
                    (close < sma_50 OR close < sma_150 OR close < sma_200)
                    NOTE: uses C1+C2+C6 only, not full trend_ok (avoids C9 RS
                    flicker fragmenting one long session into many short ones)
    cooldown_end  — exit_date + 14 calendar days
    session_id    — monotonic per ticker, 1-based

A new session can only open after the prior session's cooldown_end. While a
session is active, daily updates refresh `trend_ok`/`breakout_ok`/`status`.

Two execution paths
-------------------
    backfill()        — vectorised SQL over full t2 history; one Python sweep
                        per ticker over candidate sessions (small population).
    update_daily(d)   — incremental single-date update for the daily pipeline.
"""

import logging
from datetime import date, timedelta
from typing import Optional

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

_COOLDOWN_DAYS = 14


class SepaWatchlistManager:
    """Manages sepa_watchlist event log for the T3 universe gate."""

    def __init__(self, db_path: str):
        self.db_path = str(db_path)
        with duckdb.connect(self.db_path) as conn:
            self._ensure_schema(conn)

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _ensure_schema(self, conn: duckdb.DuckDBPyConnection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sepa_watchlist (
                ticker        VARCHAR  NOT NULL,
                entry_date    DATE     NOT NULL,
                exit_date     DATE,
                cooldown_end  DATE,
                session_id    INTEGER  NOT NULL,
                trend_ok      BOOLEAN,
                breakout_ok   BOOLEAN,
                status        VARCHAR  NOT NULL,
                updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ticker, entry_date)
            )
        """)

    # ------------------------------------------------------------------
    # Backfill — vectorised candidate extraction + Python cooldown sweep
    # ------------------------------------------------------------------

    def backfill(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict:
        """
        Rebuild sepa_watchlist from full t2 history.

        Strategy:
          1. SQL extracts candidate sessions via gaps-and-islands on the
             trend-active flag (close > sma_50/150/200). Each candidate has
             an entry_date (first entry_signal day inside the trend run) and
             an exit_date (first day after the trend run ends; NULL if still
             active at end_date).
          2. Python sweeps candidates per ticker, applying the 14-day cooldown
             gate. Sequentially-dependent so cannot be pure SQL without a
             RECURSIVE CTE; the candidate set is small (thousands), so the
             sweep is fast.
          3. Bulk INSERT of accepted sessions.

        Returns:
            {'sessions': int, 'tickers': int, 'active': int, 'cooldown': int, 'exited': int}
        """
        with duckdb.connect(self.db_path) as conn:
            if start_date is None:
                start_date = conn.execute(
                    "SELECT MIN(date)::VARCHAR FROM t2_screener_features"
                ).fetchone()[0]
            if end_date is None:
                end_date = conn.execute(
                    "SELECT MAX(date)::VARCHAR FROM t2_screener_features"
                ).fetchone()[0]

            logger.info(f"[SepaWatchlist] Backfill {start_date} → {end_date}")

            # Wipe and rebuild — backfill is authoritative
            conn.execute("DELETE FROM sepa_watchlist")

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

            logger.info(f"[SepaWatchlist] Extracted {len(candidates):,} candidate sessions")

            accepted = self._apply_cooldown_sweep(candidates)
            logger.info(
                f"[SepaWatchlist] Accepted {len(accepted):,} sessions after cooldown sweep "
                f"({len(candidates) - len(accepted):,} dropped)"
            )

            if len(accepted) == 0:
                return {'sessions': 0, 'tickers': 0, 'active': 0, 'cooldown': 0, 'exited': 0}

            # Compute current state for each accepted session relative to end_date
            accepted = self._annotate_state(conn, accepted, end_date)

            # Bulk insert
            conn.register('accepted_df', accepted)
            conn.execute("""
                INSERT INTO sepa_watchlist
                    (ticker, entry_date, exit_date, cooldown_end, session_id,
                     trend_ok, breakout_ok, status)
                SELECT ticker, entry_date, exit_date, cooldown_end, session_id,
                       trend_ok, breakout_ok, status
                FROM accepted_df
            """)
            conn.unregister('accepted_df')

            counts = conn.execute("""
                SELECT
                    COUNT(*) AS sessions,
                    COUNT(DISTINCT ticker) AS tickers,
                    COUNT(*) FILTER (WHERE status = 'ACTIVE')   AS active,
                    COUNT(*) FILTER (WHERE status = 'COOLDOWN') AS cooldown,
                    COUNT(*) FILTER (WHERE status = 'EXITED')   AS exited
                FROM sepa_watchlist
            """).fetchone()

        result = {
            'sessions': counts[0], 'tickers':  counts[1],
            'active':   counts[2], 'cooldown': counts[3], 'exited': counts[4],
        }
        logger.info(f"[SepaWatchlist] Backfill complete: {result}")
        return result

    # ------------------------------------------------------------------
    # Cooldown sweep (per-ticker greedy)
    # ------------------------------------------------------------------

    def _apply_cooldown_sweep(self, candidates: pd.DataFrame) -> pd.DataFrame:
        """
        Per-ticker greedy sweep: drop candidate if its entry_date <= prev kept
        candidate's cooldown_end. Drop is independent of whether prev was kept
        — only kept candidates impose cooldown.

        Returns:
            DataFrame with columns: ticker, entry_date, exit_date, cooldown_end, session_id
        """
        if candidates.empty:
            return pd.DataFrame(
                columns=['ticker', 'entry_date', 'exit_date', 'cooldown_end', 'session_id']
            )

        accepted_rows = []

        for ticker, grp in candidates.groupby('ticker', sort=False):
            last_cooldown_end = None
            session_id = 0
            for row in grp.itertuples(index=False):
                if last_cooldown_end is not None and row.entry_date <= last_cooldown_end:
                    continue
                session_id += 1
                cooldown_end = (
                    row.exit_date + timedelta(days=_COOLDOWN_DAYS)
                    if pd.notna(row.exit_date) else None
                )
                accepted_rows.append({
                    'ticker':       ticker,
                    'entry_date':   row.entry_date,
                    'exit_date':    row.exit_date if pd.notna(row.exit_date) else None,
                    'cooldown_end': cooldown_end,
                    'session_id':   session_id,
                })
                last_cooldown_end = cooldown_end  # may be None (active session) — next entry blocked until session closes

        return pd.DataFrame(accepted_rows)

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
        - Closed sessions: trend_ok/breakout_ok=FALSE. Status='COOLDOWN' if
          as_of_date <= cooldown_end, else 'EXITED'.
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

        def _to_date(v):
            if v is None or pd.isna(v):
                return None
            if hasattr(v, 'date'):
                return v.date()
            return v

        def _status(row) -> str:
            if pd.isna(row['exit_date']):
                return 'ACTIVE'
            cd = _to_date(row['cooldown_end'])
            if cd is not None and as_of <= cd:
                return 'COOLDOWN'
            return 'EXITED'

        sessions['status'] = sessions.apply(_status, axis=1)
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
             Sets exit_date=target_date, cooldown_end=target_date+14, status='COOLDOWN'.
          2. Open a new session for any (ticker) where trend_ok AND breakout_ok
             on target_date AND no open session AND (no prior session OR
             target_date > prev.cooldown_end).
          3. Refresh status: any session in COOLDOWN whose cooldown_end < target_date
             flips to EXITED. Refresh trend_ok/breakout_ok for ACTIVE sessions.

        Returns:
            {'opened': int, 'closed': int, 'cooldown_to_exited': int, 'active': int}
        """
        with duckdb.connect(self.db_path) as conn:
            # Verify target_date has t2 data
            n_t2 = conn.execute(
                f"SELECT COUNT(*) FROM t2_screener_features WHERE date = '{target_date}'"
            ).fetchone()[0]
            if n_t2 == 0:
                logger.warning(f"[SepaWatchlist] No t2 data for {target_date}; skipping")
                return {'opened': 0, 'closed': 0, 'cooldown_to_exited': 0, 'active': 0}

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
                    cooldown_end = DATE '{target_date}' + INTERVAL {_COOLDOWN_DAYS} DAY,
                    status       = 'COOLDOWN',
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
                past_cooldown AS (
                    SELECT n.ticker
                    FROM no_open n
                    LEFT JOIN (
                        SELECT ticker, MAX(cooldown_end) AS last_cd
                        FROM sepa_watchlist
                        GROUP BY ticker
                    ) prev USING (ticker)
                    WHERE prev.last_cd IS NULL OR DATE '{target_date}' > prev.last_cd
                ),
                next_session AS (
                    SELECT p.ticker,
                           COALESCE(MAX(w.session_id), 0) + 1 AS session_id
                    FROM past_cooldown p
                    LEFT JOIN sepa_watchlist w USING (ticker)
                    GROUP BY p.ticker
                )
                INSERT INTO sepa_watchlist
                    (ticker, entry_date, exit_date, cooldown_end, session_id,
                     trend_ok, breakout_ok, status)
                SELECT ticker, DATE '{target_date}', NULL, NULL, session_id,
                       TRUE, TRUE, 'ACTIVE'
                FROM next_session
                RETURNING ticker
            """).fetchall()
            n_opened = len(opened)

            # Step 3a: COOLDOWN → EXITED for any session whose cooldown elapsed
            promoted = conn.execute(f"""
                UPDATE sepa_watchlist
                SET status     = 'EXITED',
                    updated_at = CURRENT_TIMESTAMP
                WHERE status = 'COOLDOWN'
                  AND cooldown_end < DATE '{target_date}'
                RETURNING ticker
            """).fetchall()
            n_promoted = len(promoted)

            # Step 3b: refresh trend_ok/breakout_ok for active sessions (other than just-opened)
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
            'opened':              n_opened,
            'closed':              n_closed,
            'cooldown_to_exited':  n_promoted,
            'active':              active,
        }
        logger.info(
            f"[SepaWatchlist] {target_date}: +{n_opened} opened, -{n_closed} closed, "
            f"{n_promoted} cooldown→exited, {active} active"
        )
        return result

    # ------------------------------------------------------------------
    # Universe lookup
    # ------------------------------------------------------------------

    def get_universe(self) -> list[str]:
        """All tickers that have ever entered a SEPA session — the T3 universe."""
        with duckdb.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT ticker FROM sepa_watchlist ORDER BY ticker"
            ).fetchall()
        return [r[0] for r in rows]

    def get_stats(self) -> dict:
        """Quick summary for monitoring."""
        with duckdb.connect(self.db_path) as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*)                                  AS sessions,
                    COUNT(DISTINCT ticker)                    AS tickers,
                    COUNT(*) FILTER (WHERE status='ACTIVE')   AS active,
                    COUNT(*) FILTER (WHERE status='COOLDOWN') AS cooldown,
                    COUNT(*) FILTER (WHERE status='EXITED')   AS exited,
                    MIN(entry_date)                           AS earliest_entry,
                    MAX(entry_date)                           AS latest_entry
                FROM sepa_watchlist
            """).fetchone()
        return {
            'sessions':       row[0],
            'tickers':        row[1],
            'active':         row[2],
            'cooldown':       row[3],
            'exited':         row[4],
            'earliest_entry': row[5],
            'latest_entry':   row[6],
        }
