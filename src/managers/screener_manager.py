"""
ScreenerManager - Event-log based screener membership (Phase 2 redesign).

Design:
- screener_membership: append-only event log (one row per status change per ticker)

Two execution paths:
  backfill_all(start, end)  — vectorised SQL over full history, no Python loop
  evaluate_and_log(date)    — incremental single-date update for daily pipeline

Grace period: 126 consecutive failing days before an exit event is written.
Implemented via gaps-and-islands window function — no per-ticker Python iteration.

Criteria v2 (effective 2020-01-01):
    close >= 5, avg_volume_20d >= 100K, market_cap >= 150M
"""

import logging
from typing import Optional

import duckdb

logger = logging.getLogger(__name__)

_GRACE_DAYS = 126


class ScreenerManager:
    """Manages screener_membership event log for point-in-time universe tracking."""

    def __init__(self, db_path: str):
        self.db_path = str(db_path)
        with duckdb.connect(self.db_path) as conn:
            self._ensure_schema(conn)

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _ensure_schema(self, conn: duckdb.DuckDBPyConnection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS screener_membership (
                ticker           VARCHAR  NOT NULL,
                effective_date   DATE     NOT NULL,
                is_active        BOOLEAN  NOT NULL,
                criteria_version INTEGER  NOT NULL,
                last_price       DOUBLE,
                avg_volume_20d   DOUBLE,
                market_cap       DOUBLE,
                consec_fail_days INTEGER  DEFAULT 0,
                PRIMARY KEY (ticker, effective_date)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS screener_criteria_versions (
                version_id      INTEGER PRIMARY KEY,
                effective_date  DATE    NOT NULL,
                min_price       DOUBLE  NOT NULL DEFAULT 15.0,
                min_volume_20d  DOUBLE  NOT NULL DEFAULT 500000,
                min_market_cap  DOUBLE,
                max_market_cap  DOUBLE,
                is_backfilled   BOOLEAN DEFAULT FALSE,
                notes           VARCHAR,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            INSERT INTO screener_criteria_versions
                (version_id, effective_date, min_price, min_volume_20d, notes)
            SELECT 1, DATE '2020-01-01', 15.0, 500000, 'Initial SEPA criteria'
            WHERE NOT EXISTS (SELECT 1 FROM screener_criteria_versions WHERE version_id = 1)
        """)

        conn.execute("""
            INSERT INTO screener_criteria_versions
                (version_id, effective_date, min_price, min_volume_20d, min_market_cap, notes)
            SELECT 2, DATE '2020-01-01', 5.0, 100000, 150000000.0,
                   'Phase 2 redesign: relaxed criteria + market cap filter'
            WHERE NOT EXISTS (SELECT 1 FROM screener_criteria_versions WHERE version_id = 2)
        """)

        # Drop legacy screener_members view/table if it still exists
        try:
            conn.execute("DROP VIEW IF EXISTS screener_members")
            conn.execute("DROP TABLE IF EXISTS screener_members")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Criteria lookup
    # ------------------------------------------------------------------

    def _get_active_criteria(self, target_date: str) -> dict:
        with duckdb.connect(self.db_path) as conn:
            row = conn.execute("""
                SELECT version_id, min_price, min_volume_20d,
                       COALESCE(min_market_cap, 0)
                FROM screener_criteria_versions
                WHERE effective_date <= ?
                ORDER BY effective_date DESC, version_id DESC
                LIMIT 1
            """, [target_date]).fetchone()
        if not row:
            raise ValueError(f"No screener criteria defined for date {target_date}")
        return {
            'version_id':     row[0],
            'min_price':      row[1],
            'min_volume_20d': row[2],
            'min_market_cap': row[3],
        }

    # ------------------------------------------------------------------
    # Core SQL builder — shared by backfill and incremental paths
    # ------------------------------------------------------------------

    def _build_evaluation_sql(
        self,
        start_date: str,
        end_date: str,
        criteria: dict,
    ) -> str:
        """
        Returns a SQL expression that produces the full event log for [start_date, end_date].

        Logic (gaps-and-islands):
          1. all_days: every (ticker, date) in price_data with passes flag + metrics
          2. streak_groups: SUM(passes) over time groups consecutive fails under one id
          3. streak_lengths: ROW_NUMBER within each group = consecutive fail count
          4. transitions: detect pass→fail (entry) and fail→exit-after-grace (exit) events
        """
        p  = criteria['min_price']
        v  = criteria['min_volume_20d']
        mc = criteria['min_market_cap']
        cv = criteria['version_id']

        return f"""
        WITH all_days AS (
            -- Full history up to end_date so vol/streak windows are warm at start_date.
            -- Event filtering to [start_date, end_date] happens in the final SELECT.
            -- ASOF JOIN forward-fills shares_outstanding from quarterly reports to every trading day.
            -- Non-equity tickers (ETF/INDEX) are excluded — they have no shares_outstanding
            -- and are enrolled separately by auto_enroll_non_equity().
            SELECT
                p.ticker,
                p.date,
                p.close,
                AVG(CAST(p.volume AS BIGINT)) OVER (
                    PARTITION BY p.ticker ORDER BY p.date
                    ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                ) AS avg_volume_20d,
                p.close * COALESCE(s.shares_outstanding, 0) AS market_cap,
                (
                    p.close >= {p}
                    AND AVG(CAST(p.volume AS BIGINT)) OVER (
                            PARTITION BY p.ticker ORDER BY p.date
                            ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                        ) >= {v}
                    AND p.close * COALESCE(s.shares_outstanding, 0) >= {mc}
                ) AS passes
            FROM price_data p
            INNER JOIN company_profiles cp
                ON p.ticker = cp.ticker
                AND COALESCE(cp.ticker_type, 'EQUITY') = 'EQUITY'
            ASOF LEFT JOIN shares_history s ON p.ticker = s.ticker AND p.date >= s.date
            WHERE p.date <= '{end_date}'
        ),
        streak_groups AS (
            -- Gaps-and-islands: SUM(passes) freezes within a consecutive-fail run
            SELECT *,
                   SUM(passes::INTEGER) OVER (
                       PARTITION BY ticker ORDER BY date
                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                   ) AS pass_cumsum
            FROM all_days
        ),
        streak_lengths AS (
            -- ROW_NUMBER within each (ticker, pass_cumsum) group = consecutive fail streak
            SELECT *,
                   CASE WHEN passes THEN 0
                        ELSE ROW_NUMBER() OVER (
                                 PARTITION BY ticker, pass_cumsum ORDER BY date
                             )
                   END AS consec_fail_days,
                   LAG(passes) OVER (PARTITION BY ticker ORDER BY date) AS prev_passes
            FROM streak_groups
        ),
        raw_events AS (
            -- Entry: first passing day after a fail streak (or very first day)
            SELECT ticker, date AS effective_date, TRUE AS is_active,
                   {cv} AS criteria_version,
                   close AS last_price, avg_volume_20d, market_cap,
                   0 AS consec_fail_days
            FROM streak_lengths
            WHERE passes = TRUE
              AND (prev_passes IS NULL OR prev_passes = FALSE)

            UNION ALL

            -- Exit: ticker has been failing for exactly grace-period days
            -- Only emit if there is a prior passing day for this ticker before this date
            SELECT ticker, date AS effective_date, FALSE AS is_active,
                   {cv} AS criteria_version,
                   close AS last_price, avg_volume_20d, market_cap,
                   consec_fail_days
            FROM streak_lengths sl
            WHERE passes = FALSE
              AND consec_fail_days = {_GRACE_DAYS}
              AND EXISTS (
                  SELECT 1 FROM streak_lengths sl2
                  WHERE sl2.ticker = sl.ticker
                    AND sl2.passes = TRUE
                    AND sl2.date < sl.date
              )
        ),
        events AS (
            -- Deduplicate: keep only rows where is_active differs from the previous event
            -- This eliminates duplicate entry events caused by data gaps (suspended/relisted tickers)
            SELECT *,
                   LAG(is_active) OVER (PARTITION BY ticker ORDER BY effective_date) AS prev_event_active
            FROM raw_events
            QUALIFY prev_event_active IS DISTINCT FROM is_active
        )
        SELECT ticker, effective_date, is_active, criteria_version,
               last_price, avg_volume_20d, market_cap, consec_fail_days
        FROM events
        WHERE effective_date >= '{start_date}'
        ORDER BY ticker, effective_date
        """

    # ------------------------------------------------------------------
    # Backfill — full vectorised SQL, no Python loop
    # ------------------------------------------------------------------

    def backfill_all(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict:
        """
        Populate screener_membership for the full price_data history in one SQL pass.

        No Python loop — gaps-and-islands window functions derive the complete
        event log in a single query, then bulk INSERT OR IGNORE.

        Returns:
            {'entered': int, 'exited': int, 'total_events': int, 'active': int}
        """
        with duckdb.connect(self.db_path) as conn:
            if start_date is None:
                start_date = conn.execute(
                    "SELECT MIN(date)::VARCHAR FROM price_data"
                ).fetchone()[0]
            if end_date is None:
                end_date = conn.execute(
                    "SELECT MAX(date)::VARCHAR FROM price_data"
                ).fetchone()[0]

        criteria = self._get_active_criteria(end_date)
        logger.info(
            f"[ScreenerManager] Backfill {start_date} → {end_date} "
            f"(criteria v{criteria['version_id']})"
        )

        events_sql = self._build_evaluation_sql(start_date, end_date, criteria)

        with duckdb.connect(self.db_path) as conn:
            before = conn.execute("SELECT COUNT(*) FROM screener_membership").fetchone()[0]

            conn.execute(f"""
                INSERT OR IGNORE INTO screener_membership
                    (ticker, effective_date, is_active, criteria_version,
                     last_price, avg_volume_20d, market_cap, consec_fail_days)
                {events_sql}
            """)

            after = conn.execute("SELECT COUNT(*) FROM screener_membership").fetchone()[0]
            inserted = after - before

            counts = conn.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE is_active = TRUE)  AS entered,
                    COUNT(*) FILTER (WHERE is_active = FALSE) AS exited
                FROM screener_membership
            """).fetchone()

            active = conn.execute("""
                WITH latest AS (
                    SELECT ticker, is_active,
                           ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY effective_date DESC) AS rn
                    FROM screener_membership
                )
                SELECT COUNT(*) FROM latest WHERE rn = 1 AND is_active = TRUE
            """).fetchone()[0]

        logger.info(
            f"[ScreenerManager] Backfill complete: {inserted} events written "
            f"({counts[0]} entries, {counts[1]} exits), {active} active tickers"
        )
        return {
            'entered':      counts[0],
            'exited':       counts[1],
            'total_events': inserted,
            'active':       active,
        }

    # ------------------------------------------------------------------
    # Incremental — single-date update for daily pipeline
    # ------------------------------------------------------------------

    def evaluate_and_log(self, target_date: str) -> dict:
        """
        Evaluate and write membership events for a single date (daily pipeline use).

        Uses the same SQL logic as backfill_all but scoped to one date,
        filtering to only rows where the derived event differs from the
        last known state in screener_membership.

        Returns:
            {'entered': int, 'exited': int, 'active': int, 'criteria_version': int}
        """
        criteria = self._get_active_criteria(target_date)
        version_id = criteria['version_id']

        # Warmup window: need enough history for 20d vol + grace period
        with duckdb.connect(self.db_path) as conn:
            warmup_start = conn.execute(f"""
                SELECT MIN(date)::VARCHAR FROM (
                    SELECT date FROM price_data
                    WHERE date <= '{target_date}'
                    ORDER BY date DESC
                    LIMIT {_GRACE_DAYS + 20 + 5}
                )
            """).fetchone()[0]

            if warmup_start is None:
                logger.warning(f"[ScreenerManager] No price data before {target_date}")
                return {'entered': 0, 'exited': 0, 'active': 0, 'criteria_version': version_id}

            events_sql = self._build_evaluation_sql(warmup_start, target_date, criteria)

            # Only insert events on target_date that differ from current state
            before = conn.execute("SELECT COUNT(*) FROM screener_membership").fetchone()[0]

            conn.execute(f"""
                INSERT OR IGNORE INTO screener_membership
                    (ticker, effective_date, is_active, criteria_version,
                     last_price, avg_volume_20d, market_cap, consec_fail_days)
                WITH new_events AS (
                    SELECT * FROM ({events_sql}) WHERE effective_date = '{target_date}'
                ),
                current_state AS (
                    SELECT DISTINCT ON (ticker) ticker, is_active
                    FROM screener_membership
                    WHERE effective_date <= '{target_date}'
                    ORDER BY ticker, effective_date DESC
                )
                -- Entry events: ticker not previously active
                SELECT n.* FROM new_events n
                LEFT JOIN current_state c ON n.ticker = c.ticker
                WHERE n.is_active = TRUE
                  AND (c.ticker IS NULL OR c.is_active = FALSE)

                UNION ALL

                -- Exit events: ticker currently active, now exiting
                SELECT n.* FROM new_events n
                JOIN current_state c ON n.ticker = c.ticker
                WHERE n.is_active = FALSE
                  AND c.is_active = TRUE
            """)

            inserted = conn.execute("SELECT COUNT(*) FROM screener_membership").fetchone()[0] - before

            counts = conn.execute(f"""
                SELECT
                    COUNT(*) FILTER (WHERE is_active = TRUE)  AS entered,
                    COUNT(*) FILTER (WHERE is_active = FALSE) AS exited
                FROM screener_membership
                WHERE effective_date = '{target_date}'
            """).fetchone()

            active = conn.execute(f"""
                WITH latest AS (
                    SELECT ticker, is_active,
                           ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY effective_date DESC) AS rn
                    FROM screener_membership
                    WHERE effective_date <= '{target_date}'
                )
                SELECT COUNT(*) FROM latest WHERE rn = 1 AND is_active = TRUE
            """).fetchone()[0]

        logger.info(
            f"[ScreenerManager] {target_date}: +{counts[0]} entered, -{counts[1]} exited, "
            f"{active} active (criteria v{version_id})"
        )
        return {
            'entered':          counts[0],
            'exited':           counts[1],
            'active':           active,
            'criteria_version': version_id,
        }

    # ------------------------------------------------------------------
    # Non-equity auto-enrollment (ETF / INDEX)
    # ------------------------------------------------------------------

    def auto_enroll_non_equity(self) -> dict:
        """
        Insert one is_active=TRUE entry per ETF/INDEX ticker into
        screener_membership, using criteria_version=0 (bypass marker).

        effective_date = MIN(price_data.date) for that ticker.
        No exit event is ever generated — ETFs are evergreen in the screener.

        Idempotent: skips tickers that already have any membership row.
        """
        with duckdb.connect(self.db_path) as conn:
            existing_in_screener = {r[0] for r in conn.execute(
                "SELECT DISTINCT ticker FROM screener_membership"
            ).fetchall()}

            candidates = conn.execute("""
                SELECT
                    cp.ticker,
                    MIN(p.date) AS first_date,
                    LAST(p.close ORDER BY p.date) AS last_close
                FROM company_profiles cp
                JOIN price_data p ON cp.ticker = p.ticker
                WHERE cp.ticker_type IN ('ETF', 'INDEX')
                GROUP BY cp.ticker
                ORDER BY cp.ticker
            """).fetchall()

            inserted = 0
            skipped = 0
            for ticker, first_date, last_close in candidates:
                if ticker in existing_in_screener:
                    skipped += 1
                    continue
                conn.execute("""
                    INSERT OR IGNORE INTO screener_membership
                        (ticker, effective_date, is_active, criteria_version,
                         last_price, avg_volume_20d, market_cap, consec_fail_days)
                    VALUES (?, ?, TRUE, 0, ?, NULL, NULL, 0)
                """, [ticker, first_date, last_close])
                inserted += 1

        logger.info(
            f"[ScreenerManager] auto_enroll_non_equity: {inserted} enrolled, "
            f"{skipped} already present"
        )
        return {'enrolled': inserted, 'skipped': skipped, 'total': len(candidates)}

    # ------------------------------------------------------------------
    # Point-in-time lookup
    # ------------------------------------------------------------------

    def get_active_tickers(self, as_of_date: Optional[str] = None) -> list[str]:
        """Active tickers as of a given date (point-in-time correct)."""
        with duckdb.connect(self.db_path) as conn:
            if as_of_date is None:
                as_of_date = conn.execute(
                    "SELECT MAX(effective_date)::VARCHAR FROM screener_membership"
                ).fetchone()[0]
            if as_of_date is None:
                return []
            rows = conn.execute(f"""
                WITH latest AS (
                    SELECT ticker, is_active,
                           ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY effective_date DESC) AS rn
                    FROM screener_membership
                    WHERE effective_date <= '{as_of_date}'
                )
                SELECT ticker FROM latest WHERE rn = 1 AND is_active = TRUE
                ORDER BY ticker
            """).fetchall()
        return [r[0] for r in rows]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_membership_stats(self) -> dict:
        with duckdb.connect(self.db_path) as conn:
            stats = conn.execute("""
                WITH latest AS (
                    SELECT ticker, is_active, last_price, avg_volume_20d,
                           ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY effective_date DESC) AS rn
                    FROM screener_membership
                )
                SELECT
                    COUNT(*) FILTER (WHERE is_active = TRUE)  AS active_count,
                    COUNT(*) FILTER (WHERE is_active = FALSE) AS inactive_count,
                    COUNT(*)                                   AS total_count,
                    AVG(last_price)     FILTER (WHERE is_active = TRUE) AS avg_price,
                    AVG(avg_volume_20d) FILTER (WHERE is_active = TRUE) AS avg_volume
                FROM latest WHERE rn = 1
            """).fetchone()
        return {
            'active_count':   stats[0],
            'inactive_count': stats[1],
            'total_count':    stats[2],
            'avg_price':      round(stats[3], 2) if stats[3] else 0,
            'avg_volume':     round(stats[4], 0) if stats[4] else 0,
        }
