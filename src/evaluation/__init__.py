"""
M01 Evaluation Framework
========================

Systematic evaluation for M01 regression models.

Public API:
    - M01Evaluator: Main evaluator class
    - TargetEngineer: Generate alternative targets (A/B/C/D)
    - analyze_deciles: Decile analysis function
    - calculate_ic: Spearman IC function
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

__all__ = [
    'M01Evaluator',
    'TargetEngineer',
    'analyze_deciles',
    'calculate_ic',
    'calculate_precision_at_k',
    'calculate_recall_at_k',
    'calculate_decile_lift',
    'calculate_volatility_correlation'
]
