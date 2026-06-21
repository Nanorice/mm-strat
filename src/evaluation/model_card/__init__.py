"""Model Card framework — strategy-free model evaluation.

Public API:
    ModelCardBuilder: top-level orchestrator
    EvalSplit, load_eval_data: data ingestion
    SectionResult, MetricEntry, GateEntry: section primitives
    rubric_score: 0-3 banding helper
"""

from .data_loader import EvalSplit, load_eval_data
from .rubric import GateEntry, MetricEntry, SectionResult, rubric_score
from .builder import ModelCard, ModelCardBuilder

__all__ = [
    "EvalSplit",
    "load_eval_data",
    "GateEntry",
    "MetricEntry",
    "SectionResult",
    "rubric_score",
    "ModelCard",
    "ModelCardBuilder",
]
