"""Guardrails for the serving-layer audit.

The checks must FIRE on broken data (a dead phase must not pass silently) and
STAY QUIET on healthy data (an alert that fires on a good day is wallpaper —
the macro_data tolerance lesson). Each test mutates the input along the axis
the check claims to pin.
"""

import duckdb
import pytest

from tools import audit_serving_tables as ast


@pytest.fixture(autouse=True)
def _clear_results():
    ast._results.clear()
    yield
    ast._results.clear()


def _status(check: str) -> str:
    for r in ast._results:
        if r["check"] == check:
            return r["status"]
    raise AssertionError(f"check {check!r} not in {[r['check'] for r in ast._results]}")


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    c.execute("CREATE TABLE daily_predictions (prediction_date DATE)")
    c.execute("CREATE TABLE weather_gauge (date DATE, spy_above_200d BOOLEAN, deploy_posture VARCHAR)")
    c.execute("CREATE TABLE sector_breadth (as_of_date TIMESTAMP)")
    c.execute("CREATE TABLE nav_history (date DATE, nav DOUBLE, cash DOUBLE, positions_value DOUBLE)")
    yield c
    c.close()


def _healthy(c):
    c.execute("INSERT INTO daily_predictions VALUES (CURRENT_DATE)")
    c.execute("INSERT INTO weather_gauge VALUES (CURRENT_DATE, TRUE, 'DEPLOY')")
    c.execute("INSERT INTO sector_breadth VALUES (CURRENT_DATE)")
    c.execute("INSERT INTO nav_history VALUES (CURRENT_DATE, 30.0, 10.0, 20.0)")


def test_healthy_pipeline_raises_nothing(con):
    """A fresh, consistent pipeline must produce zero FAIL/WARNING."""
    _healthy(con)
    ast.check_freshness(con)
    ast.check_sanity(con)
    assert [r for r in ast._results if r["status"] in ("FAIL", "WARNING")] == []


def test_stale_table_warns(con):
    """A phase that stopped writing must be caught (the whole point)."""
    _healthy(con)
    con.execute("DELETE FROM daily_predictions")
    con.execute("INSERT INTO daily_predictions VALUES (CURRENT_DATE - 40)")
    ast.check_freshness(con)
    assert _status("daily_predictions_max_date") == "WARNING"


def test_freshness_tolerance_is_not_hair_trigger(con):
    """Inside tolerance must stay OK — a warning on a healthy gap is noise.

    Varies staleness across the 20d boundary so the tolerance itself is pinned:
    a mutated tolerance changes one of these two assertions.
    """
    con.execute("INSERT INTO daily_predictions VALUES (CURRENT_DATE - 19)")
    ast.check_freshness(con)
    assert _status("daily_predictions_max_date") == "OK"

    ast._results.clear()
    con.execute("DELETE FROM daily_predictions")
    con.execute("INSERT INTO daily_predictions VALUES (CURRENT_DATE - 21)")
    ast.check_freshness(con)
    assert _status("daily_predictions_max_date") == "WARNING"


def test_empty_table_is_info_not_fail(con):
    """nav_history is legitimately empty until the book has fills."""
    ast.check_freshness(con)
    assert _status("nav_history_rows") == "INFO"


def test_sector_breadth_append_bug_fails(con):
    """>1 as_of_date means refresh appended instead of replacing."""
    _healthy(con)
    con.execute("INSERT INTO sector_breadth VALUES (CURRENT_DATE - 1)")
    ast.check_sanity(con)
    assert _status("single_snapshot") == "FAIL"


def test_null_deploy_posture_warns(con):
    """A NULL posture blanks the deploy headline (SPY>200d is the one live lever)."""
    _healthy(con)
    con.execute("UPDATE weather_gauge SET deploy_posture = NULL")
    ast.check_sanity(con)
    assert _status("null_posture_30d") == "WARNING"


def test_nav_drift_fails(con):
    """NAV must equal cash + positions; cash is derived, so drift = broken invariant."""
    _healthy(con)
    con.execute("UPDATE nav_history SET nav = 999.0")
    ast.check_sanity(con)
    assert _status("nav_equals_cash_plus_positions") == "FAIL"
