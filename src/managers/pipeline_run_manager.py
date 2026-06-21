"""
PipelineRunManager - Tracks pipeline execution state (state layer).

Responsibilities:
- Create/update pipeline_runs table
- Track phase execution (start, complete, fail)
- Query execution history (idempotency checks)
- Generate health metrics (runtime, failure rates)
- Track per-table write timestamps (table_write_log)
- Track per-ticker errors with classification (pipeline_error_log)
"""

import json
import logging
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple
import duckdb
from src import db
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class PipelineRunStatus(Enum):
    """Execution status enum."""
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class PipelineRunManager:
    """Manages pipeline execution tracking in the pipeline_runs table."""

    def __init__(self, db_path: str):
        """
        Initialize manager with database connection.

        Args:
            db_path: Path to DuckDB database
        """
        self.db_path = str(db_path)
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create pipeline_runs, table_write_log, and pipeline_error_log tables if not exists."""
        conn = db.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    run_id INTEGER PRIMARY KEY,
                    run_date DATE NOT NULL,
                    target_date DATE NOT NULL,
                    phase_name VARCHAR NOT NULL,
                    status VARCHAR NOT NULL,
                    runtime_seconds DOUBLE,
                    rows_processed INTEGER,
                    error_message VARCHAR,
                    metadata VARCHAR,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP
                )
            """)

            # Create indexes for fast queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_pipeline_runs_target_phase
                ON pipeline_runs(target_date, phase_name)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status
                ON pipeline_runs(status, run_date)
            """)

            # --- table_write_log: one row per table, upserted on each write ---
            conn.execute("""
                CREATE TABLE IF NOT EXISTS table_write_log (
                    table_name VARCHAR PRIMARY KEY,
                    last_written_at TIMESTAMP NOT NULL,
                    last_rows_written INTEGER,
                    last_phase VARCHAR
                )
            """)

            # --- pipeline_error_log: one row per error event (append-only) ---
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pipeline_error_log (
                    error_id INTEGER,
                    run_id INTEGER,
                    phase_name VARCHAR NOT NULL,
                    error_type VARCHAR NOT NULL,
                    affected_entity VARCHAR,
                    error_detail VARCHAR,
                    occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_error_log_run
                ON pipeline_error_log(run_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_error_log_type_date
                ON pipeline_error_log(error_type, occurred_at)
            """)

            logger.debug("[PipelineRunManager] Tables ready (pipeline_runs, table_write_log, pipeline_error_log)")
        finally:
            conn.close()

    def start_phase(
        self,
        target_date: str,
        phase_name: str,
        metadata: dict = None
    ) -> int:
        """
        Mark phase as RUNNING, return run_id.

        Args:
            target_date: Date being processed (e.g., '2024-01-15')
            phase_name: Phase identifier (e.g., 'phase_1_t1_price')
            metadata: Optional metadata (e.g., {'tickers_count': 1826})

        Returns:
            run_id: Unique ID for this execution
        """
        conn = db.connect(self.db_path)
        try:
            # Get next run_id
            max_id = conn.execute("SELECT COALESCE(MAX(run_id), 0) FROM pipeline_runs").fetchone()[0]
            run_id = max_id + 1

            # Insert RUNNING status
            conn.execute("""
                INSERT INTO pipeline_runs (
                    run_id, run_date, target_date, phase_name, status, metadata, started_at
                ) VALUES (?, CURRENT_DATE, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, [run_id, target_date, phase_name, PipelineRunStatus.RUNNING.value,
                  json.dumps(metadata) if metadata else None])

            logger.debug(f"[PipelineRunManager] Phase '{phase_name}' started (run_id={run_id})")
            return run_id

        finally:
            conn.close()

    def complete_phase(
        self,
        run_id: int,
        status: PipelineRunStatus,
        rows_processed: int = None,
        error_message: str = None
    ) -> None:
        """
        Mark phase as completed with status.

        Args:
            run_id: Unique ID from start_phase()
            status: SUCCESS, FAILED, or SKIPPED
            rows_processed: Number of rows affected (optional)
            error_message: Error details if FAILED (optional)
        """
        conn = db.connect(self.db_path)
        try:
            # Calculate runtime
            runtime = conn.execute("""
                SELECT EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - started_at))
                FROM pipeline_runs
                WHERE run_id = ?
            """, [run_id]).fetchone()[0]

            # Update status
            conn.execute("""
                UPDATE pipeline_runs
                SET status = ?,
                    runtime_seconds = ?,
                    rows_processed = ?,
                    error_message = ?,
                    completed_at = CURRENT_TIMESTAMP
                WHERE run_id = ?
            """, [status.value, runtime, rows_processed, error_message, run_id])

            logger.debug(
                f"[PipelineRunManager] Phase completed (run_id={run_id}, "
                f"status={status.value}, runtime={runtime:.1f}s)"
            )

        finally:
            conn.close()

    def update_phase_metadata(self, run_id: int, extra: dict) -> None:
        """Merge `extra` into a run's JSON metadata (set once at start_phase).

        Used to attach DQ counts computed during the phase (e.g.
        null_filing_date_written) without expanding complete_phase's signature.
        """
        if run_id is None or not extra:
            return
        conn = db.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT metadata FROM pipeline_runs WHERE run_id = ?", [run_id]
            ).fetchone()
            current = {}
            if row and row[0]:
                try:
                    current = json.loads(row[0])
                except (json.JSONDecodeError, TypeError):
                    current = {}
            current.update(extra)
            conn.execute(
                "UPDATE pipeline_runs SET metadata = ? WHERE run_id = ?",
                [json.dumps(current), run_id],
            )
        finally:
            conn.close()

    def is_phase_completed(self, target_date: str, phase_name: str) -> bool:
        """
        Check if phase already completed successfully for target_date.

        Used for idempotency checks (skip if already done).

        Args:
            target_date: Date being processed
            phase_name: Phase identifier

        Returns:
            True if phase completed successfully today
        """
        conn = db.connect(self.db_path)
        try:
            result = conn.execute("""
                SELECT COUNT(*) > 0
                FROM pipeline_runs
                WHERE target_date = ?
                  AND phase_name = ?
                  AND status = ?
                  AND run_date = CURRENT_DATE
            """, [target_date, phase_name, PipelineRunStatus.SUCCESS.value]).fetchone()[0]

            return bool(result)

        finally:
            conn.close()

    def get_phase_metrics(self, phase_name: str, lookback_days: int = 30) -> dict:
        """
        Get average runtime and success rate for a phase.

        Args:
            phase_name: Phase identifier
            lookback_days: Number of days to analyze

        Returns:
            {
                'avg_runtime_sec': 45.2,
                'success_rate': 0.98,
                'failure_count': 2,
                'total_runs': 30
            }
        """
        conn = db.connect(self.db_path)
        try:
            result = conn.execute("""
                SELECT
                    AVG(runtime_seconds) as avg_runtime,
                    SUM(CASE WHEN status = ? THEN 1 ELSE 0 END)::FLOAT / COUNT(*) as success_rate,
                    SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) as failure_count,
                    COUNT(*) as total_runs
                FROM pipeline_runs
                WHERE phase_name = ?
                  AND run_date >= CURRENT_DATE - INTERVAL ? DAY
                  AND status != ?
            """, [
                PipelineRunStatus.SUCCESS.value,
                PipelineRunStatus.FAILED.value,
                phase_name,
                str(lookback_days),
                PipelineRunStatus.RUNNING.value
            ]).fetchone()

            return {
                'avg_runtime_sec': round(result[0], 2) if result[0] else 0,
                'success_rate': round(result[1], 3) if result[1] else 0,
                'failure_count': result[2] or 0,
                'total_runs': result[3] or 0
            }

        finally:
            conn.close()

    def get_health_report(self, target_date: str = None) -> dict:
        """
        Generate pipeline health report.

        Checks:
        - Data freshness (T1/T2/T3 max dates)
        - Recent failures (last 7 days)
        - Breakout drought (0 breakouts for N days)
        - Runtime anomalies (phase >2× avg)

        Args:
            target_date: Optional target date for breakout check

        Returns:
            {
                'data_freshness_ok': True,
                'max_dates': {'price': '2024-01-15', 't2': '2024-01-15', 't3': '2024-01-15'},
                'recent_failures': [...],
                'breakout_drought_days': 0,
                'runtime_anomalies': [...]
            }
        """
        conn = db.connect(self.db_path)
        try:
            # Check data freshness
            freshness = conn.execute("""
                SELECT
                    (SELECT MAX(date) FROM price_data) as max_price_date,
                    (SELECT MAX(date) FROM t2_screener_features) as max_t2_date,
                    (SELECT MAX(date) FROM t3_sepa_features) as max_t3_date
            """).fetchone()

            # Check recent failures (last 7 days)
            failures = conn.execute("""
                SELECT
                    target_date,
                    phase_name,
                    error_message,
                    started_at
                FROM pipeline_runs
                WHERE status = ?
                  AND run_date >= CURRENT_DATE - INTERVAL '7 days'
                ORDER BY started_at DESC
            """, [PipelineRunStatus.FAILED.value]).fetchall()

            # Check breakout drought (consecutive days with 0 T3 rows)
            drought_days = self._count_breakout_drought()

            # Check runtime anomalies (phases >2× avg runtime today)
            anomalies = conn.execute("""
                WITH today_runs AS (
                    SELECT phase_name, runtime_seconds
                    FROM pipeline_runs
                    WHERE run_date = CURRENT_DATE
                      AND status = ?
                ),
                avg_runtimes AS (
                    SELECT
                        phase_name,
                        AVG(runtime_seconds) as avg_runtime
                    FROM pipeline_runs
                    WHERE run_date >= CURRENT_DATE - INTERVAL '30 days'
                      AND status = ?
                    GROUP BY phase_name
                )
                SELECT
                    t.phase_name,
                    t.runtime_seconds,
                    a.avg_runtime
                FROM today_runs t
                JOIN avg_runtimes a ON t.phase_name = a.phase_name
                WHERE t.runtime_seconds > a.avg_runtime * 2
            """, [PipelineRunStatus.SUCCESS.value, PipelineRunStatus.SUCCESS.value]).fetchall()

            return {
                'data_freshness_ok': all(freshness),
                'max_dates': {
                    'price': str(freshness[0]) if freshness[0] else None,
                    't2': str(freshness[1]) if freshness[1] else None,
                    't3': str(freshness[2]) if freshness[2] else None
                },
                'recent_failures': [
                    {
                        'target_date': str(f[0]),
                        'phase_name': f[1],
                        'error_message': f[2],
                        'started_at': str(f[3])
                    } for f in failures
                ],
                'breakout_drought_days': drought_days,
                'runtime_anomalies': [
                    {
                        'phase_name': a[0],
                        'runtime_sec': round(a[1], 1),
                        'avg_runtime_sec': round(a[2], 1),
                        'ratio': round(a[1] / a[2], 1)
                    } for a in anomalies
                ]
            }

        finally:
            conn.close()

    # ========================================================================
    # TABLE WRITE LOG
    # ========================================================================

    def record_write(
        self,
        table_name: str,
        rows_written: int,
        phase_name: str = None
    ) -> None:
        """
        Record that a table was written to. Upserts one row per table.

        Args:
            table_name: DuckDB table that was written (e.g. 'price_data')
            rows_written: Number of rows written in this operation
            phase_name: Pipeline phase that triggered the write (optional)
        """
        conn = db.connect(self.db_path)
        try:
            # DuckDB doesn't have native UPSERT — delete + insert
            conn.execute("DELETE FROM table_write_log WHERE table_name = ?", [table_name])
            conn.execute("""
                INSERT INTO table_write_log (table_name, last_written_at, last_rows_written, last_phase)
                VALUES (?, CURRENT_TIMESTAMP, ?, ?)
            """, [table_name, rows_written, phase_name])

            logger.debug(f"[WriteLog] {table_name}: {rows_written} rows (phase={phase_name})")
        finally:
            conn.close()

    # ========================================================================
    # ERROR LOG
    # ========================================================================

    @staticmethod
    def classify_error(error_msg: str) -> str:
        """
        Classify an error message into a standard error_type.

        Categories:
            RATE_LIMIT    — API rate limit / HTTP 429
            TIMEOUT       — Connection or read timeout
            NO_DATA       — API returned empty / no parseable data
            VALIDATION    — Data failed quality checks
            AUTH          — API key / authentication failure
            FETCH_FAILURE — Catch-all for other fetch errors
        """
        if not error_msg:
            return 'FETCH_FAILURE'
        msg = error_msg.lower()
        if '429' in msg or 'rate limit' in msg or 'too many requests' in msg:
            return 'RATE_LIMIT'
        if 'timeout' in msg or 'timed out' in msg:
            return 'TIMEOUT'
        if (
            'no fmp response' in msg
            or 'no data parsed' in msg
            or 'max retries' in msg
            or 'returned no data' in msg
            or 'no data rows' in msg
            or 'no new rows' in msg
        ):
            return 'NO_DATA'
        if 'validation' in msg:
            return 'VALIDATION'
        if '401' in msg or '403' in msg or 'unauthorized' in msg or 'api key' in msg:
            return 'AUTH'
        return 'FETCH_FAILURE'

    def record_errors(
        self,
        run_id: int,
        phase_name: str,
        errors: List[Tuple[str, Optional[str]]],
    ) -> int:
        """
        Batch-insert error events into pipeline_error_log.

        Args:
            run_id: FK to pipeline_runs (from start_phase)
            phase_name: Phase that produced the errors
            errors: List of (affected_entity, error_detail) tuples.
                    error_type is auto-classified from error_detail.

        Returns:
            Number of error rows inserted.
        """
        if not errors:
            return 0

        conn = db.connect(self.db_path)
        try:
            max_id = conn.execute(
                "SELECT COALESCE(MAX(error_id), 0) FROM pipeline_error_log"
            ).fetchone()[0]

            rows = []
            for entity, detail in errors:
                max_id += 1
                error_type = self.classify_error(detail)
                rows.append((max_id, run_id, phase_name, error_type, entity, detail))

            conn.executemany("""
                INSERT INTO pipeline_error_log
                    (error_id, run_id, phase_name, error_type, affected_entity, error_detail, occurred_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, rows)

            # Log summary by error_type
            from collections import Counter
            type_counts = Counter(r[3] for r in rows)
            summary = ", ".join(f"{t}={c}" for t, c in type_counts.most_common())
            logger.info(f"[ErrorLog] {phase_name}: {len(rows)} errors recorded ({summary})")

            return len(rows)
        finally:
            conn.close()

    def _count_breakout_drought(self) -> int:
        """Count consecutive days with 0 new T3 breakouts (from most recent date backwards)."""
        conn = db.connect(self.db_path)
        try:
            # Get daily breakout counts (last 30 days)
            result = conn.execute("""
                WITH date_series AS (
                    SELECT UNNEST(
                        generate_series(
                            CURRENT_DATE - INTERVAL '30 days',
                            CURRENT_DATE,
                            INTERVAL '1 day'
                        )
                    ) AS date
                ),
                daily_breakouts AS (
                    SELECT
                        date,
                        COUNT(*) as breakout_count
                    FROM t3_sepa_features
                    WHERE date >= CURRENT_DATE - INTERVAL '30 days'
                    GROUP BY date
                )
                SELECT
                    ds.date,
                    COALESCE(db.breakout_count, 0) as count
                FROM date_series ds
                LEFT JOIN daily_breakouts db ON ds.date = db.date
                ORDER BY ds.date DESC
            """).fetchall()

            # Count consecutive zeros from most recent date
            drought = 0
            for date, count in result:
                if count == 0:
                    drought += 1
                else:
                    break

            return drought

        finally:
            conn.close()
