"""Phase 8 prod-model-identity alert: the sh019 failure mode (a box silently
scoring a stale model) must produce an alert, and a steady state must not."""

import duckdb
import pytest

from src.orchestrators.daily_pipeline_orchestrator import DailyPipelineOrchestrator


def _make_db(tmp_path, prod_ids, scored_history):
    """scored_history: list of (date, model_version_id)."""
    path = tmp_path / "t.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE models (version_id VARCHAR, status_flag VARCHAR)")
    for vid in prod_ids:
        con.execute("INSERT INTO models VALUES (?, 'prod')", [vid])
    con.execute(
        "CREATE TABLE daily_predictions (prediction_date DATE, model_version_id VARCHAR)"
    )
    for date, vid in scored_history:
        con.execute("INSERT INTO daily_predictions VALUES (?, ?)", [date, vid])
    con.close()
    return str(path)


def _alerts(tmp_path, prod_ids, scored_history):
    # __init__ builds engines/managers against the path; only the query matters here.
    orch = object.__new__(DailyPipelineOrchestrator)
    orch.db_path = _make_db(tmp_path, prod_ids, scored_history)
    return orch._check_prod_model_identity()


def test_steady_state_is_silent(tmp_path):
    alerts = _alerts(tmp_path, ["m01_binary"], [("2026-07-16", "m01_binary"),
                                                ("2026-07-17", "m01_binary")])
    assert alerts == []


def test_no_prod_model_alerts(tmp_path):
    alerts = _alerts(tmp_path, [], [("2026-07-17", "m01_binary")])
    assert len(alerts) == 1
    assert "no prod model registered" in alerts[0]


def test_multiple_prod_models_alert(tmp_path):
    alerts = _alerts(tmp_path, ["m01_binary", "m01_4class"], [])
    assert len(alerts) == 1
    assert "flagged 'prod'" in alerts[0]


def test_model_change_alerts(tmp_path):
    """The sh019 case: prod is binary but history shows 4-class was scoring."""
    alerts = _alerts(tmp_path, ["m01_binary"], [("2026-07-16", "m01_4class"),
                                                ("2026-07-17", "m01_4class")])
    assert len(alerts) == 1
    assert "prod model changed to m01_binary" in alerts[0]
    assert "m01_4class" in alerts[0]


def test_change_alert_fires_once_after_promotion(tmp_path):
    """Once the new model has scored, the older rows must not re-trigger daily."""
    alerts = _alerts(tmp_path, ["m01_binary"], [("2026-07-16", "m01_4class"),
                                                ("2026-07-17", "m01_binary")])
    assert alerts == [], "stale history should not re-alert after the switch"


def test_empty_predictions_is_silent(tmp_path):
    """A fresh box with a prod model but no scoring history yet."""
    assert _alerts(tmp_path, ["m01_binary"], []) == []
