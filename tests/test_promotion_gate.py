"""Tests for ModelRegistry.set_prod gate enforcement (§6)."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from src.model_registry import ModelRegistry, PromotionError


def _seed_models_table(db_path: str) -> None:
    """Create the `models` table with the schema the registry expects.

    ModelRegistry.__init__ does NOT create this table — production setup
    relies on schema_design.sql. Our tests need to do the equivalent.
    """
    con = duckdb.connect(db_path)
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS models (
                version_id      VARCHAR PRIMARY KEY,
                model_name      VARCHAR,
                model_version   VARCHAR,
                status_flag     VARCHAR DEFAULT 'test',
                specs_json      VARCHAR,
                feature_version VARCHAR,
                training_date   DATE,
                dataset_rows    INTEGER,
                accuracy        DOUBLE,
                weighted_f1     DOUBLE,
                macro_f1        DOUBLE,
                feature_set_id  VARCHAR,
                git_sha         VARCHAR,
                model_type      VARCHAR,
                artifacts_path  VARCHAR,
                rmse            DOUBLE,
                mae             DOUBLE,
                r2              DOUBLE,
                spearman_corr   DOUBLE,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    finally:
        con.close()


def _register_version(
    registry: ModelRegistry,
    version_id: str,
    artifacts_path: Path,
) -> None:
    """Insert a minimal `models` row pointing at artifacts_path."""
    artifacts_path.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(registry.db_path)
    try:
        con.execute(
            "INSERT OR REPLACE INTO models (version_id, status_flag, artifacts_path) VALUES (?, 'test', ?)",
            [version_id, str(artifacts_path)],
        )
    finally:
        con.close()


def _write_results(artifacts_path: Path, gates: list[dict]) -> Path:
    eval_dir = artifacts_path / "evaluation"
    eval_dir.mkdir(parents=True, exist_ok=True)
    payload = {"gates": gates, "_metadata": {}}
    p = eval_dir / "results.json"
    p.write_text(json.dumps(payload))
    return p


def _pass_gate(name: str = "calibration_ece") -> dict:
    return {
        "name": name, "status": "pass", "value": 0.03, "threshold": 0.05,
        "detail": "ok", "blocking": True,
    }


def _blocking_fail(name: str = "calibration_ece") -> dict:
    return {
        "name": name, "status": "fail", "value": 0.12, "threshold": 0.05,
        "detail": "ECE too high", "blocking": True,
    }


def _non_blocking_fail() -> dict:
    return {
        "name": "diagnostic", "status": "fail", "value": 0.5, "threshold": 0.1,
        "detail": "informational", "blocking": False,
    }


@pytest.fixture
def registry(tmp_path: Path) -> ModelRegistry:
    db = tmp_path / "registry.duckdb"
    _seed_models_table(str(db))
    return ModelRegistry(db_path=db)


def test_promotion_succeeds_when_all_blocking_gates_pass(tmp_path: Path, registry: ModelRegistry):
    artifacts = tmp_path / "art_pass"
    _register_version(registry, "v_pass", artifacts)
    _write_results(artifacts, [_pass_gate(), _non_blocking_fail()])

    # Should not raise.
    registry.set_prod("v_pass")
    assert registry.get_prod_version() == "v_pass"


def test_promotion_blocked_by_blocking_failure(tmp_path: Path, registry: ModelRegistry):
    artifacts = tmp_path / "art_fail"
    _register_version(registry, "v_fail", artifacts)
    _write_results(artifacts, [_blocking_fail()])

    with pytest.raises(PromotionError, match="calibration_ece"):
        registry.set_prod("v_fail")


def test_force_without_reason_raises(tmp_path: Path, registry: ModelRegistry):
    artifacts = tmp_path / "art_force_noreason"
    _register_version(registry, "v_force_noreason", artifacts)
    _write_results(artifacts, [_blocking_fail()])

    with pytest.raises(PromotionError, match="force_reason"):
        registry.set_prod("v_force_noreason", force=True, force_reason="")


def test_force_with_reason_logs_to_forced_promotions(tmp_path: Path, registry: ModelRegistry):
    artifacts = tmp_path / "art_force"
    _register_version(registry, "v_force", artifacts)
    _write_results(artifacts, [_blocking_fail()])

    registry.set_prod("v_force", force=True, force_reason="hotfix for prod outage",
                      promoted_by="hang")
    # The model is now prod.
    assert registry.get_prod_version() == "v_force"

    # And the forced_promotions row exists.
    con = duckdb.connect(registry.db_path, read_only=True)
    try:
        row = con.execute(
            "SELECT version_id, reason, promoted_by FROM forced_promotions WHERE version_id = ?",
            ["v_force"],
        ).fetchone()
    finally:
        con.close()
    assert row is not None
    assert row[0] == "v_force"
    assert row[1] == "hotfix for prod outage"
    assert row[2] == "hang"


def test_missing_results_json_blocks_without_force(tmp_path: Path, registry: ModelRegistry):
    artifacts = tmp_path / "art_noresults"
    _register_version(registry, "v_noresults", artifacts)
    # Do NOT write results.json.

    with pytest.raises(PromotionError, match="No evaluation results"):
        registry.set_prod("v_noresults")


def test_missing_results_json_allowed_with_force(tmp_path: Path, registry: ModelRegistry):
    artifacts = tmp_path / "art_noresults_force"
    _register_version(registry, "v_noresults_force", artifacts)

    # No results.json — but force=True for legacy models. force_reason not
    # required here because there are no *failing gates*; the override is
    # only for the missing-file scenario.
    registry.set_prod("v_noresults_force", force=True)
    assert registry.get_prod_version() == "v_noresults_force"


def test_unknown_version_raises(registry: ModelRegistry):
    with pytest.raises(ValueError, match="not found"):
        registry.set_prod("does_not_exist")


def test_legacy_results_layout_supported(tmp_path: Path, registry: ModelRegistry):
    """Some legacy models wrote results.json next to model.json, not under evaluation/."""
    artifacts = tmp_path / "art_legacy"
    _register_version(registry, "v_legacy", artifacts)
    payload = {"gates": [_pass_gate()]}
    (artifacts / "results.json").write_text(json.dumps(payload))

    registry.set_prod("v_legacy")
    assert registry.get_prod_version() == "v_legacy"


def test_non_blocking_failures_do_not_block(tmp_path: Path, registry: ModelRegistry):
    artifacts = tmp_path / "art_nb"
    _register_version(registry, "v_nb", artifacts)
    _write_results(artifacts, [_pass_gate(), _non_blocking_fail(), _non_blocking_fail()])

    # Should not raise — only blocking failures matter.
    registry.set_prod("v_nb")
    assert registry.get_prod_version() == "v_nb"
