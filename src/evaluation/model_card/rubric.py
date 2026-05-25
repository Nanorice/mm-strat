"""Rubric scoring + section result primitives.

A `SectionResult` carries everything a section knows: metrics (numeric),
rubric scores (0-3 bands), gates (PASS/FAIL/WARN), and free-form detail.
The HTML renderer reads only this structure — sections never render directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass(frozen=True)
class MetricEntry:
    name: str
    value: Optional[float]
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GateEntry:
    name: str
    status: str  # 'pass' | 'fail' | 'warn' | 'n/a'
    value: Optional[float]
    threshold: Optional[float]
    detail: str
    blocking: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SectionResult:
    name: str  # 'A', 'B', 'C', 'D', 'E', 'F', 'G'
    title: str
    scored: bool  # False for section A (gate-only)
    metrics: list[MetricEntry] = field(default_factory=list)
    rubric_scores: dict[str, int] = field(default_factory=dict)  # metric -> 0/1/2/3
    gates: list[GateEntry] = field(default_factory=list)
    tables: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    detail: str = ""
    not_implemented: bool = False

    @property
    def aggregate_score(self) -> Optional[int]:
        if not self.scored or not self.rubric_scores:
            return None
        # Section aggregate = max possible (3) — average of bands gets confusing.
        # Per framework §4 each section reports a single score out of 3 — we use
        # the *minimum* of its rubric scores (the weakest band drives the verdict).
        return int(min(self.rubric_scores.values()))

    @property
    def gates_passed(self) -> int:
        return sum(1 for g in self.gates if g.status == "pass")

    @property
    def gates_total(self) -> int:
        return len(self.gates)

    @property
    def has_blocking_failure(self) -> bool:
        return any(g.blocking and g.status == "fail" for g in self.gates)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "scored": self.scored,
            "not_implemented": self.not_implemented,
            "metrics": [m.to_dict() for m in self.metrics],
            "rubric_scores": dict(self.rubric_scores),
            "gates": [g.to_dict() for g in self.gates],
            "tables": dict(self.tables),
            "detail": self.detail,
            "aggregate_score": self.aggregate_score,
            "gates_passed": self.gates_passed,
            "gates_total": self.gates_total,
            "has_blocking_failure": self.has_blocking_failure,
        }


def rubric_score(value: float, thresholds: list[float], higher_is_better: bool = True) -> int:
    """Map a metric value to a 0-3 band.

    thresholds: three ascending cutoffs [marginal, good, strong]. With
    higher_is_better=True:
        value < thresholds[0]  -> 0 (Poor)
        value < thresholds[1]  -> 1 (Marginal)
        value < thresholds[2]  -> 2 (Good)
        value >= thresholds[2] -> 3 (Strong)
    With higher_is_better=False, signs flip.
    """
    if value is None or (isinstance(value, float) and (value != value)):  # NaN check
        return 0
    if len(thresholds) != 3:
        raise ValueError(f"thresholds must have length 3, got {len(thresholds)}")
    t0, t1, t2 = thresholds
    if higher_is_better:
        if value >= t2:
            return 3
        if value >= t1:
            return 2
        if value >= t0:
            return 1
        return 0
    else:
        if value <= t0:
            return 3
        if value <= t1:
            return 2
        if value <= t2:
            return 1
        return 0


def placeholder_section(name: str, title: str) -> SectionResult:
    return SectionResult(
        name=name,
        title=title,
        scored=False,
        not_implemented=True,
        detail=f"Section {name} not yet implemented (Phase 2/3).",
    )
