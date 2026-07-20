"""
Research Report Engine — ingests TradingAgents report trees into DuckDB.

One source (the drop dir), two raw tables, no interpretation:

  research_reports      one row per (ticker, report_date, source) — the canonical,
                        human-readable record for a name on a trade date.
  research_report_runs  one row per run_id — every run that landed, so a name run
                        several times in a day keeps all its extractions for the
                        corroboration step. The parent stays one-row-per-day.

Drop format (produced by TradingAgents, unchanged on its side):

    <reports>/<TICKER>_<wallclock_stamp>/
      complete_report.md    raw_md, the source of truth
      report.json           typed agent outputs      (optional)
      manifest.json         run identity, trade_date (required)

report_date comes from manifest.trade_date, never the folder's wall-clock stamp:
backfilling a week of history in one evening makes those disagree on every row
and collapses the PK onto a single day.
"""

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import config
from src import db

logger = logging.getLogger(__name__)

SOURCE = 'tradingagent'

# Two version namespaces, deliberately separate. The envelope describes the
# sidecar wrapper (ticker/trade_date/agents); the payload versions describe the
# agent models inside it. A renamed BusinessProfile field changes meaning without
# touching the envelope, so one number cannot speak for both.
ENVELOPE_SCHEMA_VERSION = '1.0'
PAYLOAD_SCHEMA_VERSIONS: Dict[str, str] = {
    'sentiment_analyst':  '1.0',
    'business_analyst':   '1.0',
    'research_manager':   '1.0',
    'trader':             '1.0',
    'portfolio_manager':  '1.0',
}

# Runs predating the versioning change carry no version key at all. Absent means
# "written before the field existed" — i.e. the baseline — which is a different
# fact from a declared version we cannot read. Absent ingests; a major mismatch
# never does.
_BASELINE = '1.0'


class SchemaVersionError(RuntimeError):
    """A sidecar declares a major schema version this engine was not written for."""


class ResearchReportEngine:
    """Reads TradingAgents report trees from the drop dir into DuckDB."""

    def __init__(self, db_path: str = None, reports_dir: str = None):
        self.db_path = db_path or str(config.DUCKDB_PATH)
        self.reports_dir = Path(reports_dir or config.RESEARCH_REPORTS_DIR)
        self._ensure_tables()

    # =========================================================================
    # Schema
    # =========================================================================

    def _ensure_tables(self) -> None:
        conn = db.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS research_reports (
                    ticker          VARCHAR NOT NULL,
                    report_date     DATE    NOT NULL,
                    source          VARCHAR NOT NULL,
                    raw_md          VARCHAR,
                    summary         VARCHAR,
                    thesis          VARCHAR,
                    conviction      VARCHAR,
                    key_facts_json  VARCHAR,
                    run_id          VARCHAR,
                    ingested_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (ticker, report_date, source)
                )
            """)
            # Child table: every run, not just the canonical one. Corroboration
            # (step 4) counts how often a relation recurs across runs, which is
            # only answerable if the non-canonical runs were kept.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS research_report_runs (
                    run_id            VARCHAR NOT NULL PRIMARY KEY,
                    ticker            VARCHAR NOT NULL,
                    report_date       DATE    NOT NULL,
                    source            VARCHAR NOT NULL,
                    key_facts_json    VARCHAR,
                    envelope_version  VARCHAR,
                    source_dir        VARCHAR,
                    generated_at      TIMESTAMP,
                    ingested_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS research_report_runs_tkr_idx "
                "ON research_report_runs (ticker, report_date)"
            )
        finally:
            conn.close()

    # =========================================================================
    # Version gate
    # =========================================================================

    @staticmethod
    def _major(version: str) -> str:
        return str(version).split('.')[0]

    def _check_envelope(self, declared: Optional[str], path: Path) -> str:
        """Absent → baseline. Major mismatch → refuse, naming both versions."""
        if declared is None:
            return _BASELINE
        if self._major(declared) != self._major(ENVELOPE_SCHEMA_VERSION):
            raise SchemaVersionError(
                f"{path}: envelope schema_version {declared!r} has a different "
                f"major version than {ENVELOPE_SCHEMA_VERSION!r}, which this "
                f"engine was written against. A major bump means a key was "
                f"removed, renamed, or changed meaning - half-reading it would "
                f"succeed silently on the old shape. Update "
                f"research_report_engine.ENVELOPE_SCHEMA_VERSION deliberately."
            )
        return str(declared)

    def _check_payloads(self, report: dict, path: Path) -> None:
        """Same rule, per agent. The producer does not emit these yet; absent is
        the baseline, so this gate is inert until it does."""
        declared = report.get('agent_schema_versions') or {}
        for agent, version in declared.items():
            expected = PAYLOAD_SCHEMA_VERSIONS.get(agent)
            if expected is None:
                continue  # unknown agent — additive, not our business to reject
            if self._major(version) != self._major(expected):
                raise SchemaVersionError(
                    f"{path}: agent {agent!r} declares payload schema version "
                    f"{version!r}, major-incompatible with the {expected!r} this "
                    f"engine parses. The agent's model shape changed; update "
                    f"research_report_engine.PAYLOAD_SCHEMA_VERSIONS deliberately."
                )

    # =========================================================================
    # Parsing
    # =========================================================================

    @staticmethod
    def _read_json(path: Path) -> Optional[dict]:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding='utf-8'))

    def parse_run_dir(self, run_dir: Path) -> Optional[dict]:
        """Parse one report tree into a row dict, or None if it cannot be ingested.

        Returns None (with a warning) for a run with no manifest: report_date
        would then have to come from the folder's wall-clock stamp, which is the
        one thing the PK cannot tolerate. Raises SchemaVersionError on a major
        version mismatch - that is a refusal, not a skip.
        """
        manifest = self._read_json(run_dir / 'manifest.json')
        if manifest is None:
            logger.warning(
                f"[ResearchReports] {run_dir.name}: no manifest.json - skipped. "
                f"report_date is only trustworthy from manifest.trade_date; the "
                f"folder's wall-clock stamp is not a trade date."
            )
            return None

        self._check_envelope(manifest.get('schema_version'), run_dir / 'manifest.json')

        trade_date = manifest.get('trade_date')
        ticker = manifest.get('ticker')
        if not trade_date or not ticker:
            logger.warning(
                f"[ResearchReports] {run_dir.name}: manifest missing "
                f"ticker/trade_date - skipped."
            )
            return None

        md_path = run_dir / 'complete_report.md'
        if not md_path.exists():
            logger.warning(
                f"[ResearchReports] {run_dir.name}: no complete_report.md - "
                f"skipped. raw_md is the source of truth; a row without it is empty."
            )
            return None

        report = self._read_json(run_dir / 'report.json')
        envelope_version = _BASELINE
        if report is not None:
            envelope_version = self._check_envelope(
                report.get('schema_version'), run_dir / 'report.json'
            )
            self._check_payloads(report, run_dir / 'report.json')

        agents = (report or {}).get('agents') or {}
        # .get(...) or {} twice over: an agent key present with a null value means
        # "ran, produced nothing typed" - distinct from absent, and both yield no
        # fields here without raising.
        manager = agents.get('research_manager') or {}
        portfolio = agents.get('portfolio_manager') or {}

        return {
            'ticker':           str(ticker).upper(),
            'report_date':      _parse_date(trade_date),
            'source':           SOURCE,
            'raw_md':           md_path.read_text(encoding='utf-8'),
            'summary':          manager.get('rationale'),
            # thesis is the argument, conviction is the verdict. Mapping
            # research_manager.recommendation here made them the same
            # PortfolioRating on every row ("Underweight"/"Underweight"), which
            # reads as agreement between two agents and is really one field
            # printed twice.
            'thesis':           portfolio.get('investment_thesis'),
            'conviction':       portfolio.get('rating'),
            'key_facts_json':   json.dumps(report) if report is not None else None,
            'run_id':           manifest.get('run_id'),
            'envelope_version': envelope_version,
            'source_dir':       str(run_dir),
            'generated_at':     _parse_ts(manifest.get('generated_at')),
        }

    # =========================================================================
    # Ingest
    # =========================================================================

    def ingest_run_dir(self, run_dir: Path, force: bool = False) -> bool:
        """Ingest one report tree. Returns True if a row landed, False if the run
        was skipped or already ingested.

        `force` re-parses a run already in `research_report_runs`. The reason it
        exists: a parser fix does not reach rows already ingested, because the
        run_id gate skips them. `thesis` mapped the wrong field for three
        sessions and every stored row was wrong until this could re-read the
        sidecars sitting on disk. Same rule as
        `research_comprehension.comprehend_runs` — a reader change is the one
        legitimate reason to recompute.
        """
        row = self.parse_run_dir(Path(run_dir))
        if row is None:
            return False

        conn = db.connect(self.db_path)
        try:
            run_id = row['run_id']
            if run_id:
                seen = conn.execute(
                    "SELECT 1 FROM research_report_runs WHERE run_id = ?", [run_id]
                ).fetchone()
                if seen and force:
                    conn.execute(
                        "DELETE FROM research_report_runs WHERE run_id = ?", [run_id])
                elif seen:
                    logger.info(
                        f"[ResearchReports] {Path(run_dir).name}: run_id {run_id} "
                        f"already ingested - no-op."
                    )
                    return False

            # Canonical row for the trade date. A same-day re-run replaces it;
            # two runs of one name on one trade date are a re-run, not two opinions.
            conn.execute("""
                INSERT INTO research_reports
                    (ticker, report_date, source, raw_md, summary, thesis,
                     conviction, key_facts_json, run_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (ticker, report_date, source) DO UPDATE SET
                    raw_md         = EXCLUDED.raw_md,
                    summary        = EXCLUDED.summary,
                    thesis         = EXCLUDED.thesis,
                    conviction     = EXCLUDED.conviction,
                    key_facts_json = EXCLUDED.key_facts_json,
                    run_id         = EXCLUDED.run_id,
                    ingested_at    = now()
            """, [
                row['ticker'], row['report_date'], row['source'], row['raw_md'],
                row['summary'], row['thesis'], row['conviction'],
                row['key_facts_json'], row['run_id'],
            ])

            if run_id:
                conn.execute("""
                    INSERT INTO research_report_runs
                        (run_id, ticker, report_date, source, key_facts_json,
                         envelope_version, source_dir, generated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    run_id, row['ticker'], row['report_date'], row['source'],
                    row['key_facts_json'], row['envelope_version'],
                    row['source_dir'], row['generated_at'],
                ])
            conn.commit()
        finally:
            conn.close()

        logger.info(
            f"[ResearchReports] ingested {row['ticker']} {row['report_date']} "
            f"(run_id={row['run_id']})"
        )
        return True

    def ingest_drop_dir(self, reports_dir: str = None,
                        force: bool = False) -> Tuple[int, int]:
        """Ingest every report tree under the drop dir. Returns (ingested, skipped).

        Re-running over the same drop dir is a no-op: already-seen run_ids are
        skipped, so the counts come back (0, n). `force` re-parses everything —
        see `ingest_run_dir`.
        """
        root = Path(reports_dir or self.reports_dir)
        if not root.exists():
            logger.warning(f"[ResearchReports] drop dir not found: {root}")
            return (0, 0)

        ingested = skipped = 0
        for run_dir in sorted(d for d in root.iterdir() if d.is_dir()):
            if self.ingest_run_dir(run_dir, force=force):
                ingested += 1
            else:
                skipped += 1

        logger.info(
            f"[ResearchReports] drop dir {root}: {ingested} ingested, {skipped} skipped"
        )
        return (ingested, skipped)

    # =========================================================================
    # Read helpers — never SELECT *, raw_md is 40-60KB/row
    # =========================================================================

    def list_reports(self, ticker: str = None) -> List[dict]:
        """Metadata for ingested reports, without raw_md."""
        conn = db.connect(self.db_path, read_only=True)
        try:
            where = "WHERE ticker = ?" if ticker else ""
            params = [ticker] if ticker else []
            rows = conn.execute(f"""
                SELECT ticker, report_date, source, conviction, thesis,
                       run_id, ingested_at
                FROM research_reports {where}
                ORDER BY report_date DESC, ticker
            """, params).fetchall()
        finally:
            conn.close()
        cols = ['ticker', 'report_date', 'source', 'conviction', 'thesis',
                'run_id', 'ingested_at']
        return [dict(zip(cols, r)) for r in rows]

    def get_key_facts(self, ticker: str, report_date) -> Optional[dict]:
        """Parsed key_facts_json for one report, or None."""
        conn = db.connect(self.db_path, read_only=True)
        try:
            row = conn.execute("""
                SELECT key_facts_json FROM research_reports
                WHERE ticker = ? AND report_date = ? AND source = ?
            """, [ticker.upper(), _parse_date(report_date), SOURCE]).fetchone()
        finally:
            conn.close()
        if not row or row[0] is None:
            return None
        return json.loads(row[0])


def _parse_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return datetime.strptime(str(value), '%Y-%m-%d').date()


def _parse_ts(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None
