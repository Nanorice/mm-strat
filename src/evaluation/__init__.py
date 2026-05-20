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
from .training_data_loader import (
    load_pretrain_data,
    derive_target_class,
    DEFAULT_MFE_BINS,
)
from .feature_signal import (
    return_horizon_stats,
    weekly_ticker_activity,
    days_active_by_class,
)
from .html_report import build_html_report
from .pretrain_report import run_pretrain_audit, PretrainReport

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
    # Phase 1 — Pre-training data analytics
    'load_pretrain_data',
    'derive_target_class',
    'DEFAULT_MFE_BINS',
    'return_horizon_stats',
    'weekly_ticker_activity',
    'days_active_by_class',
    'build_html_report',
    'run_pretrain_audit',
    'PretrainReport',
]
