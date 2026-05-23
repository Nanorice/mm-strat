"""Tests for the standardized evaluator_run metadata block in BaseEvaluator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from src.evaluation.base_evaluator import BaseEvaluator, _safe_git_sha


class _StubEvaluator(BaseEvaluator):
    """Minimal concrete evaluator so we can exercise BaseEvaluator directly."""

    def evaluate(self, **kwargs) -> Dict[str, Any]:  # pragma: no cover — unused here
        return {}

    def generate_report(self, metrics, plots) -> Path:  # pragma: no cover — unused here
        return self.eval_dir / "report.md"


def _build_stub(tmp_path: Path, **overrides) -> _StubEvaluator:
    ev = _StubEvaluator(
        model_name="StubModel",
        model_version="v_test",
        output_dir=tmp_path,
        db_path=None,
    )
    for k, v in overrides.items():
        setattr(ev, k, v)
    return ev


def test_metadata_block_contains_required_fields(tmp_path):
    ev = _build_stub(
        tmp_path,
        label_registry_id="mfe_4class_30d_v1",
        feature_set_id="M01_baseline_v0.1",
        pipeline_run_id=42,
    )
    out = ev.eval_dir / "results.json"
    ev._save_metrics_json({"accuracy": 0.7}, out)

    payload = json.loads(out.read_text())
    meta = payload["_metadata"]
    run = meta["evaluator_run"]

    # Original metadata still present
    assert meta["model_name"] == "StubModel"
    assert meta["model_version"] == "v_test"
    assert meta["evaluator_class"] == "_StubEvaluator"
    assert "evaluation_timestamp" in meta

    # New evaluator_run block
    for required in ["git_sha", "python_version", "label_registry_id", "feature_set_id", "pipeline_run_id"]:
        assert required in run, f"missing key: {required}"

    assert run["label_registry_id"] == "mfe_4class_30d_v1"
    assert run["feature_set_id"] == "M01_baseline_v0.1"
    assert run["pipeline_run_id"] == 42
    assert run["python_version"]  # non-empty
    # git_sha may legitimately be None if we're outside a repo or git is missing;
    # but in this repo we expect a value. Accept either, just don't crash.
    assert run["git_sha"] is None or isinstance(run["git_sha"], str)


def test_metadata_block_pipeline_run_id_optional(tmp_path):
    ev = _build_stub(tmp_path)
    out = ev.eval_dir / "results.json"
    ev._save_metrics_json({"x": 1}, out)
    payload = json.loads(out.read_text())
    run = payload["_metadata"]["evaluator_run"]

    # Not crashing when no db / no overrides is the contract
    assert run["pipeline_run_id"] is None
    assert run["label_registry_id"] is None
    assert run["feature_set_id"] is None


def test_safe_git_sha_returns_string_or_none():
    sha = _safe_git_sha()
    assert sha is None or (isinstance(sha, str) and len(sha) >= 7)
