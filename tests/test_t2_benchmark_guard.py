"""Guard against the 2026-06 all-FALSE trend_ok corruption.

`trend_ok` gates on price_vs_spy = close / t1_macro.spy_close. When t1_macro is
behind (the WARN-mode phase_1_t1_macro sub-phase no-ops), the old LEFT JOIN made
price_vs_spy NULL and COALESCE(..., FALSE) wrote trend_ok = FALSE for the whole
universe on six days. These pin the pre-flight that now refuses to write.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb

from src.feature_pipeline import FeaturePipeline

_TRADING_DAYS = ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04"]


def _seed(con: duckdb.DuckDBPyConnection, macro_days: list[str],
          spy_days: list[str] | None = None) -> None:
    """price_data gets AAPL on every trading day; SPY only on `spy_days`."""
    con.execute("CREATE TABLE price_data (ticker VARCHAR, date DATE, close DOUBLE)")
    for d in _TRADING_DAYS:
        con.execute("INSERT INTO price_data VALUES ('AAPL', ?, 100.0)", [d])
    for d in (_TRADING_DAYS if spy_days is None else spy_days):
        con.execute("INSERT INTO price_data VALUES ('SPY', ?, 450.0)", [d])
    con.execute("CREATE TABLE t1_macro (date DATE, spy_close DOUBLE)")
    for d in macro_days:
        con.execute("INSERT INTO t1_macro VALUES (?, 450.0)", [d])


class TestBenchmarkCoverageGuard(unittest.TestCase):
    def setUp(self) -> None:
        self.db = Path(__file__).parent / "_t2_guard.duckdb"
        self.db.unlink(missing_ok=True)
        self.pipeline = FeaturePipeline(str(self.db))

    def tearDown(self) -> None:
        self.db.unlink(missing_ok=True)

    def _check(self, macro_days: list[str]) -> None:
        con = duckdb.connect(str(self.db))
        try:
            _seed(con, macro_days)
            self.pipeline._assert_benchmark_coverage(
                con, _TRADING_DAYS[0], _TRADING_DAYS[-1])
        finally:
            con.close()

    def test_full_coverage_passes(self) -> None:
        self._check(_TRADING_DAYS)  # no raise

    def test_missing_day_raises(self) -> None:
        """The real failure: one trading day has no benchmark row."""
        with self.assertRaises(ValueError) as ctx:
            self._check([d for d in _TRADING_DAYS if d != "2026-06-03"])
        msg = str(ctx.exception)
        self.assertIn("2026-06-03", msg)
        self.assertIn("spy_close missing for 1", msg)

    def test_null_spy_close_raises(self) -> None:
        """A present row with NULL spy_close is just as corrupting as a missing one."""
        con = duckdb.connect(str(self.db))
        try:
            _seed(con, _TRADING_DAYS)
            con.execute("UPDATE t1_macro SET spy_close = NULL WHERE date = '2026-06-02'")
            with self.assertRaises(ValueError) as ctx:
                self.pipeline._assert_benchmark_coverage(
                    con, _TRADING_DAYS[0], _TRADING_DAYS[-1])
            self.assertIn("2026-06-02", str(ctx.exception))
        finally:
            con.close()

    def test_market_holiday_not_a_gap(self) -> None:
        """A holiday with phantom vendor bars must NOT block a recompute.

        2026-06-19 (Juneteenth) carries 4 junk price rows and no SPY bar; 2001-09-11
        carries 1. Both correctly have no t1_macro row. Keying the guard off "any
        price row" would flag them and block the June 2026 backfill, whose range
        spans 06-19.
        """
        con = duckdb.connect(str(self.db))
        try:
            holiday = "2026-06-03"
            # macro and SPY both absent for the holiday; AAPL has a phantom bar
            _seed(con,
                  macro_days=[d for d in _TRADING_DAYS if d != holiday],
                  spy_days=[d for d in _TRADING_DAYS if d != holiday])
            self.pipeline._assert_benchmark_coverage(
                con, _TRADING_DAYS[0], _TRADING_DAYS[-1])  # no raise
        finally:
            con.close()

    def test_out_of_range_gap_ignored(self) -> None:
        """A gap outside the write range must not block the run."""
        con = duckdb.connect(str(self.db))
        try:
            _seed(con, [d for d in _TRADING_DAYS if d != "2026-06-01"])
            self.pipeline._assert_benchmark_coverage(con, "2026-06-02", "2026-06-04")
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
