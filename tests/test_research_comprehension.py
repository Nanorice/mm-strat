"""Relation logging + the quote_verified gate finally being persisted.

The negative controls matter as much as here as in test_research_quote_fidelity:
a log that records every quote as verified is worse than no log, because it
launders unchecked claims into a knowledge base that looks audited.
"""

import json
from pathlib import Path

import pytest

from src.research_comprehension import (
    comprehend_runs,
    counterparty_key,
    ensure_tables,
    fidelity_by_run,
)
from src import db

EDGAR_CACHE = Path.home() / '.tradingagents' / 'cache' / 'edgar'
REAL_RUN = Path.home() / '.tradingagents' / 'logs' / 'reports' / 'RKLB_20260719_212611'


# --- counterparty_key -------------------------------------------------------

def test_legal_suffixes_do_not_split_one_counterparty():
    """GLW discloses "Prysmian Group S.p.A."; another filing may write
    "Prysmian Group". Two surface forms on one PK is the double-counting the
    whole projection design exists to avoid."""
    assert counterparty_key('Prysmian Group S.p.A.', 'competitor', None) == \
           counterparty_key('Prysmian Group', 'competitor', None)
    assert counterparty_key('Infineon Technologies AG', 'customer', None) == \
           counterparty_key('Infineon Technologies', 'customer', None)


def test_distinct_names_keep_distinct_keys():
    """The fold must not become a blanket merge."""
    assert counterparty_key('Amphenol', 'competitor', None) != \
           counterparty_key('Fujikura', 'competitor', None)


def test_aggregate_gets_a_synthetic_key_rather_than_being_dropped():
    """"Top five customers = 49% of revenue" names no party and is still the
    strongest line in the RKLB profile."""
    key = counterparty_key(None, 'customer', 5)
    assert key == '__top5_customers__'
    assert counterparty_key(None, 'customer', 10) != key


def test_a_name_of_pure_legal_boilerplate_does_not_collapse_to_empty():
    """Stripping every token would give "", colliding with every other such name."""
    assert counterparty_key('Company Ltd', 'supplier', None).strip() != ''


# --- the log ----------------------------------------------------------------

@pytest.fixture
def logged(tmp_path):
    """A DB holding one ingested run with two relations: one real quote, one invented."""
    real = (
        "For the year ended December 31, 2025, our top five customers accounted for "
        "approximately 49% of our revenues and our top five backlog customers accounted "
        "for approximately 77% of our backlog in the aggregate as of December 31, 2025."
    )
    invented = (
        "The Company expects Neutron to capture a majority share of the medium-lift "
        "launch market by the end of the 2027 fiscal year."
    )
    payload = {'agents': {'business_analyst': {'ticker': 'RKLB', 'relations': [
        {'direction': 'customer', 'counterparty': None, 'aggregate_count': 5,
         'pct_revenue': 49.0,
         'evidence': {'quote': real, 'source': '0001819994-26-000013 item1a ¶19',
                      'strength': 'strong'}},
        {'direction': 'customer', 'counterparty': 'NASA', 'aggregate_count': None,
         'pct_revenue': None,
         'evidence': {'quote': invented, 'source': '0001819994-26-000013 item1 ¶4',
                      'strength': 'strong'}},
    ]}}}

    path = str(tmp_path / 'test.duckdb')
    conn = db.connect(path)
    conn.execute("""
        CREATE TABLE research_report_runs (
            run_id VARCHAR, ticker VARCHAR, report_date DATE,
            key_facts_json VARCHAR
        )
    """)
    conn.execute("INSERT INTO research_report_runs VALUES (?, ?, ?, ?)",
                 ['run_a', 'RKLB', '2026-07-19', json.dumps(payload)])
    conn.commit()
    conn.close()
    return path


pytestmark_cache = pytest.mark.skipif(
    not (EDGAR_CACHE / 'RKLB').exists(), reason="edgar cache not on this box")


@pytest.mark.skipif(not (EDGAR_CACHE / 'RKLB').exists(), reason="no edgar cache")
def test_the_gate_actually_grades(logged):
    """The whole point: an invented quote lands as quote_verified = False.

    Before this table existed the checker computed exactly this and discarded it.
    """
    assert comprehend_runs(logged) == (1, 2)
    conn = db.connect(logged, read_only=True)
    verdicts = dict(conn.execute(
        "SELECT rel_idx, quote_verified FROM research_relations").fetchall())
    conn.close()
    assert verdicts == {0: True, 1: False}


@pytest.mark.skipif(not (EDGAR_CACHE / 'RKLB').exists(), reason="no edgar cache")
def test_rerunning_inserts_nothing(logged):
    assert comprehend_runs(logged) == (1, 2)
    assert comprehend_runs(logged) == (0, 0)


@pytest.mark.skipif(not (EDGAR_CACHE / 'RKLB').exists(), reason="no edgar cache")
def test_force_rescores_without_duplicating(logged):
    """A checker fix must be able to correct stored verdicts. Twice on
    2026-07-20 a normalization bug made clean quotes look fabricated."""
    comprehend_runs(logged)
    assert comprehend_runs(logged, force=True) == (1, 2)
    conn = db.connect(logged, read_only=True)
    assert conn.execute("SELECT COUNT(*) FROM research_relations").fetchone()[0] == 2
    conn.close()


@pytest.mark.skipif(not (EDGAR_CACHE / 'RKLB').exists(), reason="no edgar cache")
def test_fidelity_rolls_up_per_run(logged):
    comprehend_runs(logged)
    [row] = fidelity_by_run(logged)
    assert (row['relations'], row['verified'], row['uncheckable']) == (2, 1, 0)


def test_uncheckable_is_null_not_false(logged, monkeypatch):
    """A box without the EDGAR cache must not report every quote as fabricated.
    The gate does not error when the filing is missing — it stops being a gate,
    and that has to be visible as NULL rather than a wall of False.
    """
    import src.research_comprehension as rc
    monkeypatch.setattr(rc, 'load_filing_text', lambda *a, **k: (_ for _ in ()).throw(
        FileNotFoundError('no cached filing')))
    assert rc.comprehend_runs(logged) == (1, 2)
    conn = db.connect(logged, read_only=True)
    verdicts = [r[0] for r in conn.execute(
        "SELECT quote_verified FROM research_relations").fetchall()]
    conn.close()
    assert verdicts == [None, None]


def test_no_typed_profile_logs_nothing(tmp_path):
    """A run whose business_analyst fell back to free text has no relations to
    log. It must not raise, and must not invent an empty row."""
    path = str(tmp_path / 'x.duckdb')
    conn = db.connect(path)
    conn.execute("CREATE TABLE research_report_runs (run_id VARCHAR, ticker VARCHAR, "
                 "report_date DATE, key_facts_json VARCHAR)")
    conn.execute("INSERT INTO research_report_runs VALUES (?, ?, ?, ?)",
                 ['run_b', 'GLW', '2026-07-20',
                  json.dumps({'agents': {'business_analyst': None}})])
    conn.commit()
    conn.close()
    assert comprehend_runs(path) == (1, 0)
