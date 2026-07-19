"""Phase 4b canary: a box carrying pre-2026-07-18 COOLDOWN rows must be detected.

Phase 4b only appends today's events, so stale statuses in the source table
survive nightly runs forever. The `screener_watchlist` VIEW self-heals on Phase 6;
the `sepa_watchlist` TABLE does not.
"""

import duckdb

from src.orchestrators.daily_pipeline_orchestrator import DailyPipelineOrchestrator


def _db_with_statuses(tmp_path, statuses):
    path = tmp_path / "w.duckdb"
    con = duckdb.connect(str(path))
    con.execute("""
        CREATE TABLE sepa_watchlist (
            ticker VARCHAR, entry_date DATE, status VARCHAR
        )
    """)
    for i, status in enumerate(statuses):
        con.execute("INSERT INTO sepa_watchlist VALUES (?, ?, ?)",
                    [f"T{i}", "2026-01-02", status])
    con.close()

    orch = object.__new__(DailyPipelineOrchestrator)
    orch.db_path = str(path)
    return orch


def test_clean_box_is_silent(tmp_path):
    orch = _db_with_statuses(tmp_path, ["ACTIVE", "EXITED", "EXITED"])
    assert orch._check_watchlist_status_vocab() == 0


def test_cooldown_rows_detected(tmp_path):
    """The sh019 case: a pre-merge box still holding COOLDOWN sessions."""
    orch = _db_with_statuses(tmp_path, ["ACTIVE", "COOLDOWN", "COOLDOWN", "EXITED"])
    assert orch._check_watchlist_status_vocab() == 2


def test_empty_table_is_silent(tmp_path):
    assert _db_with_statuses(tmp_path, [])._check_watchlist_status_vocab() == 0


def test_counts_all_retired_statuses(tmp_path):
    orch = _db_with_statuses(tmp_path, ["COOLDOWN", "PENDING", "ACTIVE"])
    assert orch._check_watchlist_status_vocab() == 2
