"""Evaluation gate primitives.

A `GateResult` records the outcome of a single threshold check (calibration ECE,
walk-forward Sharpe, label-horizon violation count, ...). `EvaluationGate`
collects them per model_version and answers the single question that
`ModelRegistry.set_prod()` will eventually ask: is this version promotable?
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Optional

GateStatus = Literal["pass", "fail", "warn", "n/a"]


@dataclass(frozen=True)
class GateResult:
    name: str
    status: GateStatus
    value: Optional[float]
    threshold: Optional[float]
    detail: str
    blocking: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GateResult":
        return cls(
            name=data["name"],
            status=data["status"],
            value=data.get("value"),
            threshold=data.get("threshold"),
            detail=data.get("detail", ""),
            blocking=bool(data.get("blocking", False)),
        )


@dataclass
class EvaluationGate:
    model_version: str
    results: List[GateResult] = field(default_factory=list)

    def record(self, result: GateResult) -> None:
        self.results.append(result)

    def is_promotable(self) -> bool:
        return not any(r.blocking and r.status == "fail" for r in self.results)

    def blocking_failures(self) -> List[GateResult]:
        return [r for r in self.results if r.blocking and r.status == "fail"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_version": self.model_version,
            "promotable": self.is_promotable(),
            "gates": [r.to_dict() for r in self.results],
        }

    @classmethod
    def from_results_json(cls, model_version: str, payload: Dict[str, Any]) -> "EvaluationGate":
        gate = cls(model_version=model_version)
        for entry in payload.get("gates", []) or []:
            gate.record(GateResult.from_dict(entry))
        return gate
