"""
Evaluation Framework
====================

Systematic evaluation for ML models.

Public API:
    M01:
        - M01Evaluator: Main evaluator class for regression models
        - TargetEngineer: Generate alternative targets (A/B/C/D)
        - analyze_deciles: Decile analysis function
        - calculate_ic: Spearman IC function

    M03:
        - M03Evaluator: Validate regime calculator against ground truth
        - M03GridSearch: Grid search for archetype optimization
        - load_ground_truth_df: Load historical regime periods

    M04+:
        - ClassificationEvaluator: Multi-class classification evaluator
        - BaseEvaluator: Abstract base class for evaluators
        - EvaluationPlotter: Visualization library
        - LeakageGuard: Temporal leakage detection
"""

from .m01_evaluator import M01Evaluator
from .targets import TargetEngineer
from .ranking import analyze_deciles
from .metrics import (
    calculate_ic,
    calculate_precision_at_k,
    calculate_recall_at_k,
    calculate_decile_lift,
    calculate_volatility_correlation
)
from .feature_screener import FeatureScreener
from .feature_analyzer import FeatureAnalyzer
from .m03_evaluator import M03Evaluator
from .m03_ground_truth import load_ground_truth_df, GROUND_TRUTH_PERIODS
from .m03_grid_search import M03GridSearch, ARCHETYPES, VIX_CURVES
from .base_evaluator import BaseEvaluator
from .classification_evaluator import ClassificationEvaluator
from .plotting import EvaluationPlotter
from .leakage_guard import LeakageGuard

__all__ = [
    # M01
    'M01Evaluator',
    'TargetEngineer',
    'FeatureScreener',
    'FeatureAnalyzer',
    'analyze_deciles',
    'calculate_ic',
    'calculate_precision_at_k',
    'calculate_recall_at_k',
    'calculate_decile_lift',
    'calculate_volatility_correlation',
    # M03
    'M03Evaluator',
    'M03GridSearch',
    'ARCHETYPES',
    'VIX_CURVES',
    'load_ground_truth_df',
    'GROUND_TRUTH_PERIODS',
    # M04+ (Classification)
    'BaseEvaluator',
    'ClassificationEvaluator',
    'EvaluationPlotter',
    'LeakageGuard',
]

