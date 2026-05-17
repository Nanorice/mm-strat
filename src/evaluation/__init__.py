"""
Evaluation Framework
====================

Systematic evaluation for ML models.

Public API:
    M03:
        - M03Evaluator: Validate regime calculator against ground truth
        - load_ground_truth_df: Load historical regime periods

    M04+:
        - ClassificationEvaluator: Multi-class classification evaluator
        - BaseEvaluator: Abstract base class for evaluators
        - EvaluationPlotter: Visualization library
        - LeakageGuard: Temporal leakage detection
"""

from .m03_evaluator import M03Evaluator
from .m03_ground_truth import load_ground_truth_df, GROUND_TRUTH_PERIODS
from .base_evaluator import BaseEvaluator
from .classification_evaluator import ClassificationEvaluator
from .plotting import EvaluationPlotter
from .leakage_guard import LeakageGuard

__all__ = [
    # M03
    'M03Evaluator',
    'load_ground_truth_df',
    'GROUND_TRUTH_PERIODS',
    # M04+ (Classification)
    'BaseEvaluator',
    'ClassificationEvaluator',
    'EvaluationPlotter',
    'LeakageGuard',
]
