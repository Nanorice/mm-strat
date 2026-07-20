"""Ingest tests for research_report_engine. Every test uses a tmp DuckDB — the
live market_data.duckdb is single-writer and the nightly pipeline holds it."""

import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from src.research_report_engine import (
    ResearchReportEngine,
    SchemaVersionError,
)

REAL_RUN = Path.home() / '.tradingagents' / 'logs' / 'reports' / 'RKLB_20260719_212611'

pytestmark = pytest.mark.skipif(
    not REAL_RUN.exists(),
    reason=f"real run not on this box: {REAL_RUN}",
)


@pytest.fixture
def engine(tmp_path):
    return ResearchReportEngine(db_path=str(tmp_path / 'test.duckdb'))


@pytest.fixture
def run_copy(tmp_path):
    """A writable copy of the real run, so tests can corrupt it safely."""
    dest = tmp_path / 'drop' / REAL_RUN.name
    shutil.copytree(REAL_RUN, dest)
    return dest


def test_report_date_comes_from_manifest_not_folder_stamp(engine, run_copy):
    assert engine.ingest_run_dir(run_copy) is True
    rows = engine.list_reports('RKLB')
    assert len(rows) == 1
    # Folder is stamped 20260719_212611; trade_date is what must land.
    assert rows[0]['report_date'] == date(2026, 7, 19)
    assert rows[0]['run_id'] == '186fa743cc20'


def test_ingest_twice_is_a_no_op(engine, run_copy):
    assert engine.ingest_run_dir(run_copy) is True
    assert engine.ingest_run_dir(run_copy) is False
    assert len(engine.list_reports('RKLB')) == 1


def test_drop_dir_reingest_is_a_no_op(engine, run_copy):
    drop = run_copy.parent
    assert engine.ingest_drop_dir(drop) == (1, 0)
    assert engine.ingest_drop_dir(drop) == (0, 1)
    assert len(engine.list_reports('RKLB')) == 1


def test_major_schema_version_mismatch_is_rejected_loudly(engine, run_copy):
    manifest = run_copy / 'manifest.json'
    payload = json.loads(manifest.read_text(encoding='utf-8'))
    payload['schema_version'] = '2.0'
    manifest.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(SchemaVersionError) as exc:
        engine.ingest_run_dir(run_copy)
    # Both versions must be named — a message that hides which shape it saw
    # leaves the reader guessing which side moved.
    assert '2.0' in str(exc.value)
    assert '1.0' in str(exc.value)
    assert engine.list_reports('RKLB') == []


def test_minor_version_bump_is_additive_and_ingests(engine, run_copy):
    manifest = run_copy / 'manifest.json'
    payload = json.loads(manifest.read_text(encoding='utf-8'))
    payload['schema_version'] = '1.7'
    payload['some_new_key'] = 'additive'
    manifest.write_text(json.dumps(payload), encoding='utf-8')
    assert engine.ingest_run_dir(run_copy) is True


def test_absent_schema_version_is_treated_as_baseline(engine, run_copy):
    """The real RKLB run predates the version field. Absent means 'written
    before the field existed', not 'unreadable'."""
    for name in ('manifest.json', 'report.json'):
        path = run_copy / name
        payload = json.loads(path.read_text(encoding='utf-8'))
        payload.pop('schema_version', None)
        path.write_text(json.dumps(payload), encoding='utf-8')
    assert engine.ingest_run_dir(run_copy) is True


def test_payload_version_mismatch_is_rejected(engine, run_copy):
    report = run_copy / 'report.json'
    payload = json.loads(report.read_text(encoding='utf-8'))
    payload['agent_schema_versions'] = {'business_analyst': '3.0'}
    report.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(SchemaVersionError) as exc:
        engine.ingest_run_dir(run_copy)
    assert 'business_analyst' in str(exc.value)


def test_missing_report_json_still_ingests_with_null_key_facts(engine, run_copy):
    (run_copy / 'report.json').unlink()
    assert engine.ingest_run_dir(run_copy) is True
    assert engine.get_key_facts('RKLB', '2026-07-19') is None
    assert len(engine.list_reports('RKLB')) == 1


def test_missing_manifest_is_skipped_not_stamped_from_folder(engine, run_copy):
    (run_copy / 'manifest.json').unlink()
    assert engine.ingest_run_dir(run_copy) is False
    assert engine.list_reports() == []


def test_null_agent_is_distinct_from_absent(engine, run_copy):
    """null = ran, produced nothing typed. Absent = not in the graph. Neither
    may raise, and neither may invent a value."""
    report = run_copy / 'report.json'
    payload = json.loads(report.read_text(encoding='utf-8'))
    payload['agents']['research_manager'] = None   # ran, no typed output
    payload['agents'].pop('portfolio_manager')     # not in the graph
    report.write_text(json.dumps(payload), encoding='utf-8')

    assert engine.ingest_run_dir(run_copy) is True
    row = engine.list_reports('RKLB')[0]
    assert row['thesis'] is None
    assert row['conviction'] is None
    # The distinction survives into key_facts_json, which stores the sidecar whole.
    facts = engine.get_key_facts('RKLB', '2026-07-19')
    assert 'research_manager' in facts['agents']
    assert facts['agents']['research_manager'] is None
    assert 'portfolio_manager' not in facts['agents']


def test_same_day_rerun_replaces_parent_but_keeps_both_runs(engine, run_copy, tmp_path):
    assert engine.ingest_run_dir(run_copy) is True

    rerun = tmp_path / 'drop' / 'RKLB_20260719_235959'
    shutil.copytree(run_copy, rerun)
    manifest = rerun / 'manifest.json'
    payload = json.loads(manifest.read_text(encoding='utf-8'))
    payload['run_id'] = 'deadbeef0001'
    manifest.write_text(json.dumps(payload), encoding='utf-8')

    assert engine.ingest_run_dir(rerun) is True

    # Parent keeps one canonical row per trade date, holding the newer run.
    rows = engine.list_reports('RKLB')
    assert len(rows) == 1
    assert rows[0]['run_id'] == 'deadbeef0001'

    # Child keeps both — corroboration needs the runs the parent discarded.
    conn_rows = _runs(engine)
    assert {r[0] for r in conn_rows} == {'186fa743cc20', 'deadbeef0001'}


def test_populated_fields_map_from_the_sidecar(engine, run_copy):
    engine.ingest_run_dir(run_copy)
    row = engine.list_reports('RKLB')[0]
    assert row['conviction'] == 'Underweight'      # portfolio_manager.rating
    # thesis is the argument, not the verdict. These two being equal was the bug.
    assert row['thesis'] != row['conviction']
    # portfolio_manager.investment_thesis is prose, not one of the rating enums.
    assert len(row['thesis']) > 100
    facts = engine.get_key_facts('RKLB', '2026-07-19')
    assert facts['agents']['business_analyst']['ticker'] == 'RKLB'


def _runs(engine):
    from src import db
    conn = db.connect(engine.db_path, read_only=True)
    try:
        return conn.execute(
            "SELECT run_id, ticker, report_date FROM research_report_runs"
        ).fetchall()
    finally:
        conn.close()


def test_force_reingests_a_run_already_seen(engine, run_copy):
    """A parser fix does not reach stored rows without this — the run_id gate
    skips them. `thesis` mapped the wrong field for three sessions and every row
    stayed wrong until the sidecars on disk could be re-read."""
    assert engine.ingest_run_dir(run_copy) is True
    assert engine.ingest_run_dir(run_copy) is False
    assert engine.ingest_run_dir(run_copy, force=True) is True

    # Re-ingesting must not duplicate the child row.
    assert len([r for r in _runs(engine) if r[0] == '186fa743cc20']) == 1
