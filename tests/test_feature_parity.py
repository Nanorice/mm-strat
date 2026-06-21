"""Tests for LeakageGuard.feature_parity_check (§2.1.3)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from src.evaluation.leakage_guard import LeakageGuard


@pytest.fixture()
def parity_db(tmp_path: Path) -> Path:
    """Build a tiny db with two views holding identical features.

    Then the failing-case tests will swap one view out for a corrupted variant.
    """
    db = tmp_path / "parity.duckdb"
    con = duckdb.connect(str(db))
    con.execute(
        """
        CREATE TABLE model_feature_sets (
            feature_set_id VARCHAR,
            feature_name VARCHAR,
            feature_group VARCHAR,
            ordinal INTEGER
        )
        """
    )
    feats = [("rs", "Momentum", 0), ("sector", "Categorical", 1), ("close", "Price", 2)]
    for name, grp, ordn in feats:
        con.execute(
            "INSERT INTO model_feature_sets VALUES (?, ?, ?, ?)",
            ["TEST_FS", name, grp, ordn],
        )

    rng = np.random.default_rng(0)
    tickers = [f"T{i}" for i in range(5)]
    dates = pd.bdate_range("2024-01-02", periods=30)
    rows = []
    for tk in tickers:
        for d in dates:
            rows.append((tk, d.date(), float(rng.normal(0, 1)), "TECH", float(rng.normal(100, 5))))

    con.execute(
        """
        CREATE TABLE feat_train (
            ticker VARCHAR, date DATE, rs DOUBLE, sector VARCHAR, close DOUBLE
        )
        """
    )
    con.executemany("INSERT INTO feat_train VALUES (?, ?, ?, ?, ?)", rows)
    con.execute("CREATE VIEW v_train AS SELECT * FROM feat_train")
    con.execute("CREATE VIEW v_deploy AS SELECT * FROM feat_train")
    con.close()
    return db


def test_parity_passes_when_views_identical(parity_db: Path):
    result = LeakageGuard.feature_parity_check(
        train_view="v_train",
        deploy_view="v_deploy",
        feature_set_id="TEST_FS",
        db_path=parity_db,
        sample_n=20,
    )
    assert result["passed"] is True
    assert result["mismatches"] == []
    assert result["dtype_mismatches"] == []
    assert result["gate"]["status"] == "pass"
    assert result["sampled_pairs"] > 0
    assert result["matched"] == result["sampled_pairs"]


def test_parity_catches_numerical_mismatch(parity_db: Path):
    """Replace v_deploy with a corrupted variant — rs is shifted by 0.5."""
    con = duckdb.connect(str(parity_db))
    con.execute("DROP VIEW v_deploy")
    con.execute(
        """
        CREATE VIEW v_deploy AS
        SELECT ticker, date, rs + 0.5 AS rs, sector, close FROM feat_train
        """
    )
    con.close()

    result = LeakageGuard.feature_parity_check(
        train_view="v_train",
        deploy_view="v_deploy",
        feature_set_id="TEST_FS",
        db_path=parity_db,
        sample_n=20,
    )
    assert result["passed"] is False
    assert len(result["mismatches"]) > 0
    assert all(m["feature"] == "rs" for m in result["mismatches"])
    assert result["gate"]["status"] == "fail"
    assert result["gate"]["blocking"] is True


def test_parity_catches_categorical_mismatch(parity_db: Path):
    """The m01_rank-style bug: deployment encodes 'sector' as an integer code."""
    con = duckdb.connect(str(parity_db))
    con.execute("DROP VIEW v_deploy")
    con.execute(
        """
        CREATE VIEW v_deploy AS
        SELECT ticker, date, rs,
               CASE WHEN sector = 'TECH' THEN '1' ELSE '0' END AS sector,
               close
        FROM feat_train
        """
    )
    con.close()

    result = LeakageGuard.feature_parity_check(
        train_view="v_train",
        deploy_view="v_deploy",
        feature_set_id="TEST_FS",
        db_path=parity_db,
        sample_n=20,
    )
    assert result["passed"] is False
    assert any(m["feature"] == "sector" for m in result["mismatches"])


def test_parity_returns_na_when_no_overlap(parity_db: Path):
    """Empty intersection → status='n/a', not 'pass' and not 'fail'."""
    con = duckdb.connect(str(parity_db))
    con.execute("DROP VIEW v_deploy")
    con.execute(
        """
        CREATE VIEW v_deploy AS
        SELECT ticker, date + INTERVAL 1000 DAY AS date, rs, sector, close
        FROM feat_train
        """
    )
    con.close()

    result = LeakageGuard.feature_parity_check(
        train_view="v_train",
        deploy_view="v_deploy",
        feature_set_id="TEST_FS",
        db_path=parity_db,
        sample_n=20,
    )
    assert result["sampled_pairs"] == 0
    assert result["gate"]["status"] == "n/a"


def test_parity_raises_on_unknown_feature_set(parity_db: Path):
    with pytest.raises(ValueError, match="empty or unknown"):
        LeakageGuard.feature_parity_check(
            train_view="v_train",
            deploy_view="v_deploy",
            feature_set_id="DOES_NOT_EXIST",
            db_path=parity_db,
            sample_n=20,
        )


def test_parity_handles_multi_row_per_key_views(parity_db: Path):
    """When views fan out to N>1 rows per (ticker, date), the check must NOT
    cross-join them into N*N rows of false-positive mismatches.

    Regression for the 2026-05-23 bug surfaced by the m01_prototype_may run:
    v_d2_training/v_d3_deployment have multiple historical-filing rows per
    (ticker, date) and were producing 100+ false mismatches even when the two
    views were byte-identical.
    """
    con = duckdb.connect(str(parity_db))
    # Wrap both views so each (ticker, date) has 5 duplicate rows.
    con.execute("DROP VIEW v_train")
    con.execute("DROP VIEW v_deploy")
    con.execute(
        """
        CREATE VIEW v_train AS
        SELECT * FROM feat_train
        UNION ALL SELECT * FROM feat_train
        UNION ALL SELECT * FROM feat_train
        UNION ALL SELECT * FROM feat_train
        UNION ALL SELECT * FROM feat_train
        """
    )
    con.execute(
        """
        CREATE VIEW v_deploy AS
        SELECT * FROM feat_train
        UNION ALL SELECT * FROM feat_train
        UNION ALL SELECT * FROM feat_train
        UNION ALL SELECT * FROM feat_train
        UNION ALL SELECT * FROM feat_train
        """
    )
    con.close()

    result = LeakageGuard.feature_parity_check(
        train_view="v_train",
        deploy_view="v_deploy",
        feature_set_id="TEST_FS",
        db_path=parity_db,
        sample_n=20,
    )
    # Views are identical content-wise — must pass.
    assert result["passed"] is True, f"unexpected mismatches: {result['mismatches'][:3]}"
    assert result["mismatches"] == []
    assert result["dtype_mismatches"] == []
    # ...and report the fan-out so a human knows the view needs investigation.
    assert result["train_multi_row_keys"] > 0
    assert result["deploy_multi_row_keys"] > 0
    assert "multi-row keys" in result["gate"]["detail"]


def test_parity_multi_row_with_real_mismatch(parity_db: Path):
    """Multi-row dedup must NOT mask a genuine deploy-side bug."""
    con = duckdb.connect(str(parity_db))
    con.execute("DROP VIEW v_deploy")
    con.execute(
        """
        CREATE VIEW v_deploy AS
        SELECT ticker, date, rs + 0.5 AS rs, sector, close FROM feat_train
        UNION ALL
        SELECT ticker, date, rs + 0.5 AS rs, sector, close FROM feat_train
        """
    )
    con.close()

    result = LeakageGuard.feature_parity_check(
        train_view="v_train",
        deploy_view="v_deploy",
        feature_set_id="TEST_FS",
        db_path=parity_db,
        sample_n=20,
    )
    assert result["passed"] is False
    assert any(m["feature"] == "rs" for m in result["mismatches"])
    assert result["deploy_multi_row_keys"] > 0
