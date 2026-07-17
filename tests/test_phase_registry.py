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


def test_every_orchestrated_phase_has_an_abort_guard():
    """Each non-terminal _execute_phase call must be followed by `if not
    phase_success:`. `_execute_phase` returns success=False only when a HALT phase
    failed (WARN/SKIP are absorbed as success there), so this guard is the real
    HALT control surface — no call site silently ignores a critical failure.
    """
    import inspect
    from src.orchestrators import daily_pipeline_orchestrator as orch

    src = inspect.getsource(orch.DailyPipelineOrchestrator.run_pipeline)
    # Count call sites vs abort guards; the terminal model_card has no guard
    # (nothing runs after it). Everything else must guard.
    exec_ids = re.findall(r"_execute_phase\(\s*[\"']([^\"']+)[\"']", src)
    # Two forms abort on a HALT failure: `if not phase_success:` (mainline) and
    # `return phase_success` (the --phase-N-only shortcuts). Both propagate False.
    n_guards = (len(re.findall(r"if not phase_success:", src))
                + len(re.findall(r"return phase_success", src)))
    non_terminal = [k for k in exec_ids if k != "model_card"]
    assert n_guards >= len(non_terminal), (
        f"{len(non_terminal)} non-terminal phases but only {n_guards} abort guards"
    )


def test_execute_phase_returns_false_only_on_halt():
    """`_execute_phase` is the single HALT control surface: a failing phase
    returns success=False iff config marks it HALT. WARN/SKIP are absorbed as
    success so the run continues.
    """
    from src.orchestrators.daily_pipeline_orchestrator import DailyPipelineOrchestrator

    orch = DailyPipelineOrchestrator(dry_run=True)

    def boom():
        raise RuntimeError("phase blew up")

    for phase in PHASES:
        halt = PIPELINE_FAILURE_MODES[phase.id] == PipelineFailureMode.HALT
        success, _ = orch._execute_phase(phase.id, boom, "2024-01-01",
                                         skip_idempotency_check=True)
        assert success == (not halt), f"{phase.id}: HALT={halt} but success={success}"


def test_unknown_id_helpers_are_failsafe():
    assert failure_mode_for("does_not_exist") == PipelineFailureMode.HALT
    assert label_for("does_not_exist") == "does_not_exist"
    assert order_for("does_not_exist") is None
    # old-generation persisted key (heatmap seam) is unknown to the registry
    assert order_for("phase_9_monitoring") is None
