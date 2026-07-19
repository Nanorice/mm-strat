"""Phase 1 t1_macro interior-gap self-heal.

`ingest_daily_macro` writes only the target date and the incremental path resumes
from MAX(date), so a missed date is a permanent hole. The heal derives from local
price_data/macro_data — no network, so no rate-limited silent no-op.
"""

import duckdb
import pytest

from src.orchestrators.daily_pipeline_orchestrator import DailyPipelineOrchestrator

SPY = [("2026-06-01", 758.5, 43634900, 760.0, 755.0),
       ("2026-06-02", 755.0, 40000000, 757.0, 753.0),
       ("2026-06-03", 754.2, 51402500, 756.0, 752.0)]
QQQ = [("2026-06-01", 742.7, 30000000, 744.0, 740.0),
       ("2026-06-02", 741.0, 29000000, 743.0, 739.0),
       ("2026-06-03", 744.2, 31000000, 746.0, 742.0)]
VIX = [("2026-06-01", 16.05), ("2026-06-02", 16.30), ("2026-06-03", 16.06)]


def _orch(tmp_path, existing_macro_dates):
    path = tmp_path / "m.duckdb"
    con = duckdb.connect(str(path))
    con.execute("""CREATE TABLE price_data (ticker VARCHAR, date DATE, close DOUBLE,
                   volume UBIGINT, high DOUBLE, low DOUBLE)""")
    for t, rows in (("SPY", SPY), ("QQQ", QQQ)):
        for d, close, vol, high, low in rows:
            con.execute("INSERT INTO price_data VALUES (?,?,?,?,?,?)",
                        [t, d, close, vol, high, low])
    con.execute("""CREATE TABLE macro_data (date DATE, symbol VARCHAR,
                   close DOUBLE, volume BIGINT, value DOUBLE, unit VARCHAR)""")
    for d, v in VIX:
        con.execute("INSERT INTO macro_data VALUES (?,'VIX',?,NULL,NULL,NULL)", [d, v])
    con.execute("""CREATE TABLE t1_macro (date DATE PRIMARY KEY, spy_close DOUBLE,
                   spy_volume UBIGINT, spy_high DOUBLE, spy_low DOUBLE,
                   qqq_close DOUBLE, qqq_volume UBIGINT, qqq_high DOUBLE,
                   qqq_low DOUBLE, vix_close DOUBLE,
                   updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    for d in existing_macro_dates:
        con.execute("INSERT INTO t1_macro (date, spy_close, vix_close) VALUES (?, -1.0, -1.0)", [d])
    con.close()

    orch = object.__new__(DailyPipelineOrchestrator)
    orch.db_path = str(path)
    return orch


# Lookback must span the fixture's 2026-06 dates regardless of the real clock.
LOOKBACK = 100_000


def test_heals_interior_gap(tmp_path):
    """06-02 is missing between two present dates — the case daily ingest never revisits."""
    orch = _orch(tmp_path, ["2026-06-01", "2026-06-03"])
    assert orch._heal_t1_macro_gaps(lookback_days=LOOKBACK) == 1

    con = duckdb.connect(orch.db_path, read_only=True)
    row = con.execute("""SELECT spy_close, qqq_close, vix_close, spy_volume
                         FROM t1_macro WHERE date='2026-06-02'""").fetchone()
    con.close()
    assert row == pytest.approx((755.0, 741.0, 16.30, 40000000))


def test_vix_read_from_close_not_value(tmp_path):
    """macro_data stores VIX in `close`; `value` is NULL. Reading `value` writes NULLs."""
    orch = _orch(tmp_path, [])
    orch._heal_t1_macro_gaps(lookback_days=LOOKBACK)
    con = duckdb.connect(orch.db_path, read_only=True)
    nulls = con.execute("SELECT COUNT(*) FROM t1_macro WHERE vix_close IS NULL").fetchone()[0]
    con.close()
    assert nulls == 0, "vix_close must be populated from macro_data.close"


def test_never_overwrites_existing_rows(tmp_path):
    """Existing rows are sentinel -1.0; the heal must leave them untouched."""
    orch = _orch(tmp_path, ["2026-06-01", "2026-06-02", "2026-06-03"])
    assert orch._heal_t1_macro_gaps(lookback_days=LOOKBACK) == 0

    con = duckdb.connect(orch.db_path, read_only=True)
    untouched = con.execute("SELECT COUNT(*) FROM t1_macro WHERE spy_close = -1.0").fetchone()[0]
    con.close()
    assert untouched == 3


def test_no_gaps_is_noop(tmp_path):
    orch = _orch(tmp_path, ["2026-06-01", "2026-06-02", "2026-06-03"])
    assert orch._heal_t1_macro_gaps(lookback_days=LOOKBACK) == 0


def test_lookback_bounds_the_scan(tmp_path):
    """Holes older than the window are left alone (no nightly 26-year rescan)."""
    orch = _orch(tmp_path, [])
    assert orch._heal_t1_macro_gaps(lookback_days=0) == 0
