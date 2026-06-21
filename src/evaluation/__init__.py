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

Imports here are lazy (PEP 562). `from src.evaluation import X` still works
but only triggers the import of the submodule that owns `X`. Direct
submodule imports — `from src.evaluation.X import Y` — bypass this module
entirely. The win matters because the eager chain includes m03_evaluator →
m03_regime → macro_engine → yfinance, which adds ~1s+ of import time
nobody pays for unless they actually need M03.
"""

from typing import Any

# name → (submodule, attribute_name). attribute_name=None means re-export the module.
_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    # M03
    "M03Evaluator": ("m03_evaluator", "M03Evaluator"),
    "load_ground_truth_df": ("m03_ground_truth", "load_ground_truth_df"),
    "GROUND_TRUTH_PERIODS": ("m03_ground_truth", "GROUND_TRUTH_PERIODS"),
    # M04+ (Classification)
    "BaseEvaluator": ("base_evaluator", "BaseEvaluator"),
    "ClassificationEvaluator": ("classification_evaluator", "ClassificationEvaluator"),
    "EvaluationPlotter": ("plotting", "EvaluationPlotter"),
    "LeakageGuard": ("leakage_guard", "LeakageGuard"),
    # Phase 1 — Pre-training data analytics
    "load_pretrain_data": ("training_data_loader", "load_pretrain_data"),
    "derive_target_class": ("training_data_loader", "derive_target_class"),
    "DEFAULT_MFE_BINS": ("training_data_loader", "DEFAULT_MFE_BINS"),
    "return_horizon_stats": ("feature_signal", "return_horizon_stats"),
    "weekly_ticker_activity": ("feature_signal", "weekly_ticker_activity"),
    "days_active_by_class": ("feature_signal", "days_active_by_class"),
    "build_html_report": ("html_report", "build_html_report"),
    "run_pretrain_audit": ("pretrain_report", "run_pretrain_audit"),
    "PretrainReport": ("pretrain_report", "PretrainReport"),
}


def __getattr__(name: str) -> Any:
    """Lazy attribute resolution per PEP 562.

    Called once per attribute when not already in module dict — subsequent
    accesses hit the cached attribute via normal lookup.
    """
    spec = _LAZY_EXPORTS.get(name)
    if spec is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    submodule_name, attr_name = spec
    from importlib import import_module
    module = import_module(f".{submodule_name}", package=__name__)
    value = getattr(module, attr_name)
    globals()[name] = value  # cache for subsequent lookups
    return value


def __dir__() -> list[str]:
    return sorted(list(_LAZY_EXPORTS.keys()) + list(globals().keys()))


__all__ = list(_LAZY_EXPORTS.keys())
