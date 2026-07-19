"""Date-coverage audit: interior holes in the daily panels must be found.

Interior gaps are the dangerous kind — incremental writers resume from MAX(date),
so a hole behind the frontier never self-closes.
"""

import duckdb
import pytest

import tools.audit_date_coverage as aud


@pytest.fixture(autouse=True)
def _clear_results():
    aud._results.clear()
    yield
    aud._results.clear()


def _con(spy_days, panel_days, panel="t2_screener_features"):
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE price_data (ticker VARCHAR, date DATE)")
    for d in spy_days:
        con.execute("INSERT INTO price_data VALUES ('SPY', ?)", [d])
    for table, _col, _phase, _sev in aud.PANELS:
        con.execute(f"CREATE TABLE {table} (date DATE)")
        for d in (panel_days if table == panel else spy_days):
            con.execute(f"INSERT INTO {table} VALUES (?)", [d])
    return con


def _result_for(table):
    return next(r for r in aud._results if r["section"] == table)


WEEK = ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"]


def test_full_coverage_is_ok():
    aud.check_interior_gaps(_con(WEEK, WEEK), None)
    assert all(r["status"] == "OK" for r in aud._results)


def test_interior_hole_detected():
    """06-03 missing between present dates — never revisited by MAX(date) writers."""
    holed = [d for d in WEEK if d != "2026-06-03"]
    aud.check_interior_gaps(_con(WEEK, holed), None)
    res = _result_for("t2_screener_features")
    assert res["status"] == "FAIL"
    assert res["value"] == 1
    assert "2026-06-03" in res["detail"]


def test_trailing_edge_is_not_a_gap():
    """Dates after the panel's last row are 'not written yet', not holes."""
    aud.check_interior_gaps(_con(WEEK, WEEK[:3]), None)
    assert _result_for("t2_screener_features")["status"] == "OK"


def test_late_start_is_not_a_gap():
    """Panels start at different dates (t3 2001, t2_regime 2003); earlier days aren't gaps."""
    aud.check_interior_gaps(_con(WEEK, WEEK[2:]), None)
    assert _result_for("t2_screener_features")["status"] == "OK"


def test_severity_split_training_vs_display():
    """A hole in a panel the model trains on is FAIL; a display feed is WARNING."""
    sev = {t: s for t, _c, _p, s in aud.PANELS}
    assert sev["t2_screener_features"] == "FAIL"
    assert sev["t3_sepa_features"] == "FAIL"
    assert sev["t1_macro"] == "WARNING"


def test_missing_table_is_fail():
    con = _con(WEEK, WEEK)
    con.execute("DROP TABLE t1_macro")
    aud.check_interior_gaps(con, None)
    res = _result_for("t1_macro")
    assert res["status"] == "FAIL"
    assert res["value"] == "missing"
