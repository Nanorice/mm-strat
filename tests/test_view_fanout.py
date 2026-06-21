"""Regression test for the 2026-05-24 v_d2_features fan-out bug.

Background: `fundamental_features` can have multiple rows tied at the same
(ticker, filing_date) — e.g. UNH 2007-03-06 carried Q2/Q3/Q4 stamped on the
same filing_date in production data. The old `_create_v_d2_features`
correlated-subquery pattern (`WHERE filing_date = (SELECT MAX(filing_date)
...)`) would let all N tied rows survive the join, fanning one d1 row into
N rows downstream. The fix collapses the source via
`QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker, filing_date ORDER BY
fiscal_period DESC NULLS LAST) = 1`.

These tests build a minimal fixture DB (no daily_features pipeline) and
exercise `_create_v_d2_features` directly with deliberately-tied source rows.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from src.managers.view_manager import ViewManager


@pytest.fixture()
def fanout_db(tmp_path: Path) -> Path:
    """Build a tiny DB containing only the tables _create_v_d2_features needs.

    `v_d1_candidates` is mocked as a 1-row view; the test then inserts
    fundamental_features rows that deliberately collide on (ticker, filing_date).
    """
    db = tmp_path / "fanout.duckdb"
    con = duckdb.connect(str(db))

    # Minimal v_d1_candidates surface — the view's SELECT projects d1.*, so we
    # only need ticker/date/close (the rest of d1.* travels through unused).
    con.execute(
        """
        CREATE TABLE mock_d1 (
            ticker VARCHAR, date DATE, close DOUBLE
        )
        """
    )
    con.execute(
        "INSERT INTO mock_d1 VALUES "
        "('UNH', DATE '2007-03-21', 50.0), "
        "('AAPL', DATE '2024-06-30', 200.0)"
    )
    con.execute("CREATE VIEW v_d1_candidates AS SELECT * FROM mock_d1")

    # company_profiles — LEFT JOIN, optional.
    con.execute(
        """
        CREATE TABLE company_profiles (
            ticker VARCHAR, market_cap DOUBLE, shares_outstanding DOUBLE
        )
        """
    )
    con.execute(
        "INSERT INTO company_profiles VALUES "
        "('UNH', 1e11, 1e9), ('AAPL', 3e12, 1.5e10)"
    )

    # t3_sepa_features — only queried by the post-build sanity print to compute
    # the "latest date" row count. Stub with one row so the print doesn't error.
    con.execute("CREATE TABLE t3_sepa_features (date DATE)")
    con.execute("INSERT INTO t3_sepa_features VALUES (DATE '2024-06-30')")

    # fundamental_features — schema matches what _create_v_d2_features projects.
    con.execute(
        """
        CREATE TABLE fundamental_features (
            ticker VARCHAR, filing_date DATE, fiscal_period VARCHAR,
            revenue DOUBLE, net_income DOUBLE, eps_diluted DOUBLE,
            total_assets DOUBLE, total_equity DOUBLE,
            revenue_growth_yoy DOUBLE, eps_growth_yoy DOUBLE,
            net_income_growth_yoy DOUBLE,
            eps_accel DOUBLE, revenue_accel DOUBLE, revenue_cagr_3y DOUBLE,
            eps_stability_score DOUBLE,
            debt_to_equity DOUBLE, current_ratio DOUBLE, quick_ratio DOUBLE,
            gross_margin DOUBLE, operating_margin DOUBLE, net_margin DOUBLE,
            roe DOUBLE, roa DOUBLE, fcf_margin DOUBLE,
            earnings_quality_score DOUBLE, inventory_growth_yoy DOUBLE,
            inventory_vs_sales_spread DOUBLE, gross_margin_trend DOUBLE
        )
        """
    )

    con.close()
    return db


def _insert_filing(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    filing_date: str,
    fiscal_period: str,
    revenue: float,
    eps_diluted: float = 1.0,
) -> None:
    """Helper to insert a fundamental_features row with mostly-zero filler."""
    con.execute(
        """
        INSERT INTO fundamental_features VALUES
        (?, DATE %r, ?, ?, 0, ?, 0, 0,  0, 0, 0,  0, 0, 0, 0,  0, 0, 0,
         0, 0, 0, 0, 0, 0,  0, 0, 0, 0)
        """ % filing_date,
        [ticker, fiscal_period, revenue, eps_diluted],
    )


def test_no_fanout_when_source_has_tied_filings(fanout_db: Path):
    """The UNH 2007-03-06 case: three filings stamped with the same filing_date.

    Without the ff_dedup fix, the as-of join lets all three through, producing
    3 rows in v_d2_features for UNH 2007-03-21. With the fix, exactly 1 row.
    """
    con = duckdb.connect(str(fanout_db))
    _insert_filing(con, "UNH", "2007-03-06", "Q2", 1.0e10)
    _insert_filing(con, "UNH", "2007-03-06", "Q3", 1.5e10)
    _insert_filing(con, "UNH", "2007-03-06", "Q4", 1.8e10)
    # AAPL gets one clean filing — sanity baseline.
    _insert_filing(con, "AAPL", "2024-01-15", "Q1", 1.0e11)

    ViewManager._create_v_d2_features(con)

    row_counts = con.execute(
        """
        SELECT ticker, date, COUNT(*) AS n
        FROM v_d2_features
        GROUP BY ticker, date
        ORDER BY ticker, date
        """
    ).fetchall()
    con.close()

    assert row_counts == [
        ("AAPL", __import__("datetime").date(2024, 6, 30), 1),
        ("UNH", __import__("datetime").date(2007, 3, 21), 1),
    ], f"expected exactly 1 row per (ticker, date), got {row_counts}"


def test_tiebreaker_picks_largest_fiscal_period(fanout_db: Path):
    """When ties exist, ORDER BY fiscal_period DESC NULLS LAST should win.

    Q4 > Q3 > Q2 lexicographically, so Q4's revenue must be the one selected.
    """
    con = duckdb.connect(str(fanout_db))
    _insert_filing(con, "UNH", "2007-03-06", "Q2", 1.0e10)
    _insert_filing(con, "UNH", "2007-03-06", "Q3", 1.5e10)
    _insert_filing(con, "UNH", "2007-03-06", "Q4", 1.8e10)

    ViewManager._create_v_d2_features(con)

    revenue, fiscal_period = con.execute(
        """
        SELECT revenue, fiscal_period
        FROM v_d2_features
        WHERE ticker = 'UNH' AND date = DATE '2007-03-21'
        """
    ).fetchone()
    con.close()

    assert fiscal_period == "Q4", f"expected Q4 tiebreaker winner, got {fiscal_period}"
    assert revenue == 1.8e10


def test_no_fanout_with_clean_source(fanout_db: Path):
    """Sanity: when source has no dups, output still has exactly 1 row per key."""
    con = duckdb.connect(str(fanout_db))
    _insert_filing(con, "UNH", "2006-12-31", "Q4", 9.0e9)
    _insert_filing(con, "AAPL", "2024-01-15", "Q1", 1.0e11)

    ViewManager._create_v_d2_features(con)

    fanout = con.execute(
        """
        SELECT ticker, date, COUNT(*) AS n
        FROM v_d2_features
        GROUP BY ticker, date
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    con.close()

    assert fanout == [], f"unexpected fan-out: {fanout}"


def test_d1_rows_without_filings_still_appear(fanout_db: Path):
    """Left-join semantics must survive the rewrite: d1 rows with no
    fundamentals in their history should still appear with NULL fundamentals.
    """
    con = duckdb.connect(str(fanout_db))
    # Only insert a filing for UNH; AAPL has none → should still appear in
    # v_d2_features with revenue=NULL.
    _insert_filing(con, "UNH", "2006-12-31", "Q4", 9.0e9)

    ViewManager._create_v_d2_features(con)

    aapl = con.execute(
        """
        SELECT ticker, date, revenue
        FROM v_d2_features
        WHERE ticker = 'AAPL'
        """
    ).fetchone()
    con.close()

    assert aapl is not None, "AAPL row should appear via LEFT JOIN even without filings"
    assert aapl[2] is None, f"AAPL revenue should be NULL, got {aapl[2]}"
