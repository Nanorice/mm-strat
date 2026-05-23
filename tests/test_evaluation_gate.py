"""Tests for src.evaluation.gate."""

from __future__ import annotations

import pytest

from src.evaluation.gate import EvaluationGate, GateResult


def _pass() -> GateResult:
    return GateResult(
        name="calibration_ece",
        status="pass",
        value=0.03,
        threshold=0.05,
        detail="ECE within bound",
        blocking=True,
    )


def _warn() -> GateResult:
    return GateResult(
        name="permutation_importance",
        status="warn",
        value=None,
        threshold=None,
        detail="Diagnostic only",
        blocking=False,
    )


def _blocking_fail() -> GateResult:
    return GateResult(
        name="feature_parity",
        status="fail",
        value=7.0,
        threshold=0.0,
        detail="7 features mismatch",
        blocking=True,
    )


def test_is_promotable_false_when_blocking_failure():
    gate = EvaluationGate(model_version="v_test")
    gate.record(_pass())
    gate.record(_warn())
    gate.record(_blocking_fail())

    assert gate.is_promotable() is False
    failures = gate.blocking_failures()
    assert len(failures) == 1
    assert failures[0].name == "feature_parity"


def test_is_promotable_true_when_only_pass_and_warn():
    gate = EvaluationGate(model_version="v_test")
    gate.record(_pass())
    gate.record(_warn())

    assert gate.is_promotable() is True
    assert gate.blocking_failures() == []


def test_non_blocking_failure_does_not_block_promotion():
    gate = EvaluationGate(model_version="v_test")
    gate.record(_pass())
    non_blocking_fail = GateResult(
        name="diagnostic_only",
        status="fail",
        value=0.1,
        threshold=0.05,
        detail="not blocking",
        blocking=False,
    )
    gate.record(non_blocking_fail)

    assert gate.is_promotable() is True


def test_serialization_round_trips():
    gate = EvaluationGate(model_version="v_round")
    gate.record(_pass())
    gate.record(_blocking_fail())

    payload = gate.to_dict()
    restored = EvaluationGate.from_results_json(
        model_version=payload["model_version"], payload=payload
    )

    assert restored.model_version == gate.model_version
    assert len(restored.results) == len(gate.results)
    assert restored.is_promotable() == gate.is_promotable()
    assert restored.results[1].name == "feature_parity"
    assert restored.results[1].blocking is True


def test_gate_result_from_dict_handles_missing_optional_fields():
    minimal = {"name": "x", "status": "pass", "blocking": False}
    result = GateResult.from_dict(minimal)
    assert result.value is None
    assert result.threshold is None
    assert result.detail == ""


def test_empty_gate_is_promotable():
    gate = EvaluationGate(model_version="empty")
    assert gate.is_promotable() is True
    assert gate.to_dict()["gates"] == []
