"""Guardrails for the stable-id phase registry.

These assert the invariants whose violation caused the original drift:
config's failure-mode map, the registry, and the orchestrator's actual phase
keys must all agree. If a future edit reintroduces drift, one of these fails.
"""

import re

import pytest

from config import PIPELINE_FAILURE_MODES, PipelineFailureMode
from src.orchestrators.phase_registry import (
    PHASES,
    PHASE_BY_ID,
    failure_mode_for,
    label_for,
    order_for,
)


def test_every_registry_id_has_a_failure_mode():
    """Registry phases must resolve a failure mode from config (no KeyError)."""
    for phase in PHASES:
        assert phase.id in PIPELINE_FAILURE_MODES, f"{phase.id} missing from config"
        assert isinstance(phase.failure_mode, PipelineFailureMode)


def test_ids_are_unique_and_orders_are_distinct():
    ids = [p.id for p in PHASES]
    assert len(ids) == len(set(ids)), "duplicate phase id"
    orders = [p.order for p in PHASES]
    assert len(orders) == len(set(orders)), "duplicate phase order"


def test_orders_match_declared_execution_sequence():
    """PHASES is declared in execution order; `order` must be monotonic."""
    orders = [p.order for p in PHASES]
    assert orders == sorted(orders), "PHASES not in ascending order"


def test_ids_are_stable_not_positional():
    """A stable id must NOT encode its position (no 'phase_N' prefix)."""
    for phase in PHASES:
        assert not re.match(r"phase_\d", phase.id), (
            f"{phase.id} looks positional — ids must be order-independent"
        )


def test_orchestrator_phase_keys_match_registry():
    """Every id passed to _execute_phase must be a registered phase.

    Guards against an orchestrator call site using an unregistered key (which
    would silently fall back to default-HALT + a raw-id label).
    """
    import inspect
    from src.orchestrators import daily_pipeline_orchestrator as orch

    src = inspect.getsource(orch.DailyPipelineOrchestrator.run_pipeline)
    # First positional arg to each _execute_phase(...) call.
    keys = re.findall(r"_execute_phase\(\s*[\"']([^\"']+)[\"']", src)
    assert keys, "no _execute_phase keys found — test brittle, update pattern"
    for key in keys:
        assert key in PHASE_BY_ID, f"orchestrator uses unregistered phase id {key!r}"


def test_every_orchestrated_phase_has_a_critical_guard():
    """Each _execute_phase call must be followed by the uniform
    `_is_critical(<same id>)` guard, so failure_mode is the real control surface
    (no call site silently ignores a HALT failure).
    """
    import inspect
    from src.orchestrators import daily_pipeline_orchestrator as orch

    src = inspect.getsource(orch.DailyPipelineOrchestrator.run_pipeline)
    exec_ids = re.findall(r"_execute_phase\(\s*[\"']([^\"']+)[\"']", src)
    guard_ids = set(re.findall(r"_is_critical\([\"']([^\"']+)[\"']\)", src))
    # model_card is the final statement (nothing runs after it) — guard optional.
    for pid in exec_ids:
        if pid == "model_card":
            continue
        assert pid in guard_ids, f"{pid} has no _is_critical guard after _execute_phase"


def test_is_critical_matches_config():
    """The orchestrator's _is_critical must agree with the config failure map."""
    from src.orchestrators.daily_pipeline_orchestrator import DailyPipelineOrchestrator

    orch = DailyPipelineOrchestrator(dry_run=True)
    for phase in PHASES:
        expected = PIPELINE_FAILURE_MODES[phase.id] == PipelineFailureMode.HALT
        assert orch._is_critical(phase.id) == expected, phase.id


def test_unknown_id_helpers_are_failsafe():
    assert failure_mode_for("does_not_exist") == PipelineFailureMode.HALT
    assert label_for("does_not_exist") == "does_not_exist"
    assert order_for("does_not_exist") is None
    # old-generation persisted key (heatmap seam) is unknown to the registry
    assert order_for("phase_9_monitoring") is None
