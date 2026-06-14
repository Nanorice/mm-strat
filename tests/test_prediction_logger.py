"""Tests for src.evaluation.prediction_logger (§2.5)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from src.evaluation.prediction_logger import (
    _migrate_add_cohort,
    ensure_schema,
    log_daily_predictions,
)


def _make_predictions(n: int = 50, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    raw = rng.dirichlet([1, 1, 1, 1], size=n)
    df = pd.DataFrame(
        {
            "ticker": [f"T{i:03d}" for i in range(n)],
            "prob_class_0": raw[:, 0],
            "prob_class_1": raw[:, 1],
            "prob_class_2": raw[:, 2],
            "prob_class_3": raw[:, 3],
        }
    )
    df["predicted_class"] = df[["prob_class_0", "prob_class_1", "prob_class_2", "prob_class_3"]].values.argmax(axis=1)
    return df


def test_ensure_schema_creates_table(tmp_path: Path):
    db = tmp_path / "pred.duckdb"
    ensure_schema(db)
    con = duckdb.connect(str(db), read_only=True)
    try:
        names = [r[1] for r in con.execute("PRAGMA table_info('daily_predictions')").fetchall()]
    finally:
        con.close()
    assert {"prediction_date", "ticker", "model_version_id", "rank_within_day", "decision_taken"} <= set(names)


def test_log_daily_predictions_round_trip(tmp_path: Path):
    db = tmp_path / "pred.duckdb"
    preds = _make_predictions(n=50, seed=1)
    n_written = log_daily_predictions(
        db_path=db,
        prediction_date=date(2026, 5, 23),
        model_version_id="M01_v0.1",
        predictions=preds,
    )
    assert n_written == 50

    con = duckdb.connect(str(db), read_only=True)
    try:
        rows = con.execute(
            "SELECT COUNT(*) FROM daily_predictions WHERE model_version_id = 'M01_v0.1'"
        ).fetchone()[0]
        ranks = con.execute(
            "SELECT rank_within_day FROM daily_predictions ORDER BY rank_within_day"
        ).fetchall()
    finally:
        con.close()
    assert rows == 50
    assert [r[0] for r in ranks] == list(range(1, 51))


def test_log_daily_predictions_idempotent_on_rerun(tmp_path: Path):
    db = tmp_path / "pred.duckdb"
    preds = _make_predictions(n=20)
    log_daily_predictions(db_path=db, prediction_date=date(2026, 5, 23),
                          model_version_id="M01_v0.1", predictions=preds)
    log_daily_predictions(db_path=db, prediction_date=date(2026, 5, 23),
                          model_version_id="M01_v0.1", predictions=preds)
    con = duckdb.connect(str(db), read_only=True)
    try:
        n = con.execute("SELECT COUNT(*) FROM daily_predictions").fetchone()[0]
    finally:
        con.close()
    assert n == 20


def test_log_daily_predictions_two_days(tmp_path: Path):
    db = tmp_path / "pred.duckdb"
    log_daily_predictions(
        db_path=db, prediction_date=date(2026, 5, 22),
        model_version_id="M01_v0.1", predictions=_make_predictions(n=10, seed=1),
    )
    log_daily_predictions(
        db_path=db, prediction_date=date(2026, 5, 23),
        model_version_id="M01_v0.1", predictions=_make_predictions(n=15, seed=2),
    )
    con = duckdb.connect(str(db), read_only=True)
    try:
        n = con.execute("SELECT COUNT(*) FROM daily_predictions").fetchone()[0]
        n_dates = con.execute("SELECT COUNT(DISTINCT prediction_date) FROM daily_predictions").fetchone()[0]
    finally:
        con.close()
    assert n == 25
    assert n_dates == 2


def test_empty_predictions_writes_zero_rows(tmp_path: Path):
    db = tmp_path / "pred.duckdb"
    n = log_daily_predictions(
        db_path=db, prediction_date=date(2026, 5, 23),
        model_version_id="M01_v0.1", predictions=pd.DataFrame(),
    )
    assert n == 0


def test_missing_required_columns_raises(tmp_path: Path):
    db = tmp_path / "pred.duckdb"
    bad = pd.DataFrame({"prob_class_3": [0.5], "predicted_class": [3]})  # no ticker
    with pytest.raises(ValueError, match="missing required"):
        log_daily_predictions(
            db_path=db, prediction_date=date(2026, 5, 23),
            model_version_id="M01_v0.1", predictions=bad,
        )


def test_missing_production_class_column_raises(tmp_path: Path):
    db = tmp_path / "pred.duckdb"
    bad = pd.DataFrame(
        {"ticker": ["T0"], "prob_class_0": [0.5], "prob_class_1": [0.5], "predicted_class": [1]}
    )
    with pytest.raises(ValueError, match="production_class_idx"):
        log_daily_predictions(
            db_path=db, prediction_date=date(2026, 5, 23),
            model_version_id="M01_v0.1", predictions=bad,
            production_class_idx=3,
        )


def test_two_cohorts_coexist_same_date_ticker(tmp_path: Path):
    """Same (date, ticker, model) under two cohorts → two distinct rows."""
    db = tmp_path / "pred.duckdb"
    preds = _make_predictions(n=10, seed=3)
    log_daily_predictions(db_path=db, prediction_date=date(2026, 5, 23),
                          model_version_id="M01_v0.1", predictions=preds, cohort="breakout")
    log_daily_predictions(db_path=db, prediction_date=date(2026, 5, 23),
                          model_version_id="M01_v0.1", predictions=preds, cohort="pre_breakout")
    con = duckdb.connect(str(db), read_only=True)
    try:
        n = con.execute("SELECT COUNT(*) FROM daily_predictions").fetchone()[0]
        cohorts = {r[0] for r in con.execute("SELECT DISTINCT cohort FROM daily_predictions").fetchall()}
    finally:
        con.close()
    assert n == 20  # 10 per cohort, no PK collision
    assert cohorts == {"breakout", "pre_breakout"}


def test_invalid_cohort_raises(tmp_path: Path):
    db = tmp_path / "pred.duckdb"
    with pytest.raises(ValueError, match="cohort must be"):
        log_daily_predictions(db_path=db, prediction_date=date(2026, 5, 23),
                              model_version_id="M01_v0.1",
                              predictions=_make_predictions(n=3), cohort="bogus")


def test_legacy_table_migrates_to_breakout(tmp_path: Path):
    """A pre-cohort table is rebuilt with cohort='breakout' for existing rows."""
    db = tmp_path / "pred.duckdb"
    # Simulate the OLD schema (no cohort column, old PK).
    con = duckdb.connect(str(db))
    try:
        con.execute("""
            CREATE TABLE daily_predictions (
                prediction_date DATE NOT NULL, ticker VARCHAR NOT NULL,
                model_version_id VARCHAR NOT NULL,
                prob_class_0 DOUBLE, prob_class_1 DOUBLE,
                prob_class_2 DOUBLE, prob_class_3 DOUBLE,
                predicted_class INTEGER, rank_within_day INTEGER,
                decision_taken VARCHAR, taken_at TIMESTAMP, notes VARCHAR,
                ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (prediction_date, ticker, model_version_id)
            )""")
        con.execute("""INSERT INTO daily_predictions
            (prediction_date, ticker, model_version_id, prob_class_3, predicted_class, rank_within_day)
            VALUES ('2026-05-01', 'AAPL', 'M01_v0.1', 0.9, 3, 1)""")
        _migrate_add_cohort(con)
        cols = {r[1] for r in con.execute("PRAGMA table_info('daily_predictions')").fetchall()}
        cohort = con.execute("SELECT cohort FROM daily_predictions WHERE ticker='AAPL'").fetchone()[0]
        # Second call must be a no-op (idempotent), not re-trigger the rebuild.
        _migrate_add_cohort(con)
    finally:
        con.close()
    assert "cohort" in cols
    assert cohort == "breakout"


def test_decision_taken_defaults_to_null(tmp_path: Path):
    db = tmp_path / "pred.duckdb"
    log_daily_predictions(
        db_path=db, prediction_date=date(2026, 5, 23),
        model_version_id="M01_v0.1", predictions=_make_predictions(n=5),
    )
    con = duckdb.connect(str(db), read_only=True)
    try:
        n_null = con.execute(
            "SELECT COUNT(*) FROM daily_predictions WHERE decision_taken IS NULL"
        ).fetchone()[0]
    finally:
        con.close()
    assert n_null == 5
