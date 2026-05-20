"""Pre-training data quality audit — small functions, not one auditor.

Each check does one thing and returns a plain dataclass/primitive. Findings are
surfaced for manual upstream fix in feature_pipeline.py — never auto-applied.
The composing gate raises DataQualityError on any P0 violation.

Reuses LeakageGuard.check_feature_leakage (the notebook forbidden-pattern list)
rather than reimplementing it.
"""

import logging
from dataclasses import dataclass, field
from typing import List

import numpy as np
import pandas as pd

from .leakage_guard import LeakageGuard

logger = logging.getLogger(__name__)

# P0/WARN null-rate thresholds (model_proto.ipynb null audit).
NULL_P0_RATE = 0.50
NULL_WARN_RATE = 0.01
INF_P0_RATE = 0.10

# Per-ticker warm-up sentinels (model_proto.ipynb cell 18, lowercased).
WARMUP_SENTINELS = ("rs", "m03_score", "dist_from_20d_high_delta")


class DataQualityError(RuntimeError):
    """Raised when any P0 data-quality gate fails."""


@dataclass
class NullReport:
    rates: pd.Series                       # per-column null rate, sorted desc
    p0_cols: List[str] = field(default_factory=list)    # rate > 50%
    warn_cols: List[str] = field(default_factory=list)  # 1% <= rate <= 50%


@dataclass
class DataQualityReport:
    passed: bool
    null_rates: pd.Series
    null_p0_cols: List[str]
    zero_variance_cols: List[str]
    infinite_cols: dict          # col -> inf rate (> 10%)
    bad_tickers: List[str]
    leakage_cols: List[str]
    warnings: List[str]
    action_required: List[str]   # copy-pasteable upstream fix list


def null_audit(df: pd.DataFrame, feature_cols: List[str]) -> NullReport:
    """Per-column null rate. P0: > 50%. WARN: 1–50%."""
    rates = df[feature_cols].isnull().mean().sort_values(ascending=False)
    p0 = rates[rates > NULL_P0_RATE].index.tolist()
    warn = rates[(rates >= NULL_WARN_RATE) & (rates <= NULL_P0_RATE)].index.tolist()
    return NullReport(rates=rates, p0_cols=p0, warn_cols=warn)


def variance_audit(df: pd.DataFrame, feature_cols: List[str]) -> List[str]:
    """Zero-variance / constant numeric columns (P0). Non-numeric skipped."""
    num = df[feature_cols].select_dtypes(include=[np.number])
    nunique = num.nunique(dropna=True)
    return nunique[nunique <= 1].index.tolist()


def infinite_audit(df: pd.DataFrame, feature_cols: List[str]) -> dict:
    """Numeric columns with > 10% infinite values (P0)."""
    num = df[feature_cols].select_dtypes(include=[np.number])
    arr = num.to_numpy(dtype="float64", na_value=np.nan)
    inf_rate = np.isinf(arr).mean(axis=0)
    return {
        col: float(rate)
        for col, rate in zip(num.columns, inf_rate)
        if rate > INF_P0_RATE
    }


def detect_bad_tickers(
    df: pd.DataFrame,
    return_1d_thresh: float = 5.0,
    return_20d_thresh: float = 10.0,
    dominance_ratio: float = 0.8,
) -> List[str]:
    """scores_eda.ipynb logic, scale-corrected for v_d2_training.

    The return_* columns are fractional (1.0 = 100%), so the notebook's bare
    500/1000 constants are rescaled: defaults 5.0 (=500% 1d) / 10.0 (=1000% 20d).

    Criteria (reported, never auto-dropped):
      1. any return_1d > return_1d_thresh
      2. return_20d > return_20d_thresh AND return_1d/return_20d > dominance_ratio
    """
    needed = {"return_1d", "return_20d", "ticker"}
    if not needed.issubset(df.columns):
        logger.warning(
            "detect_bad_tickers skipped — missing %s",
            needed - set(df.columns),
        )
        return []

    extreme_1d = df[df["return_1d"] > return_1d_thresh]
    bad = set(extreme_1d["ticker"].unique())

    high_20d = df[df["return_20d"] > return_20d_thresh].copy()
    if not high_20d.empty:
        dominance = high_20d["return_1d"] / high_20d["return_20d"].replace(0, np.nan)
        dominated = high_20d[dominance > dominance_ratio]
        bad |= set(dominated["ticker"].unique())

    return sorted(bad)


def warmup_clip(
    df: pd.DataFrame,
    sentinels=WARMUP_SENTINELS,
) -> pd.DataFrame:
    """Per-ticker cumsum drop of leading-NULL rows on sentinel cols.

    Reproduces model_proto.ipynb cell 18: within each ticker, drop rows before
    the first row where all sentinels are non-null. Interior NULLs are kept.
    """
    present = [c for c in sentinels if c in df.columns]
    if not present:
        logger.warning("warmup_clip: no sentinel columns present, returning unchanged")
        return df

    out = df.sort_values(["ticker", "date"])
    is_valid = ~out[present].isnull().any(axis=1)
    cumvalid = is_valid.groupby(out["ticker"]).cumsum()
    clipped = out[cumvalid > 0].copy()
    logger.info(
        "warmup_clip: %d -> %d rows (dropped %d leading-NULL)",
        len(df), len(clipped), len(df) - len(clipped),
    )
    return clipped


def check_leakage(feature_cols: List[str]) -> dict:
    """Thin wrapper over LeakageGuard.check_feature_leakage — do not reimplement."""
    return LeakageGuard.check_feature_leakage(list(feature_cols))


def run_quality_gate(
    df: pd.DataFrame,
    feature_cols: List[str],
    mode: str,
) -> DataQualityReport:
    """Compose all checks. Raises DataQualityError on any P0.

    In mode='dense' the target-null P0 is not applicable (no target column);
    leakage detection still runs so dense audits catch leaked feature columns
    at the source.
    """
    null_rep = null_audit(df, feature_cols)
    zero_var = variance_audit(df, feature_cols)
    inf_cols = infinite_audit(df, feature_cols)
    bad_tickers = detect_bad_tickers(df)
    leak = check_leakage(feature_cols)
    leak_cols = leak["suspicious_features"]

    warnings: List[str] = []
    action: List[str] = []

    if null_rep.warn_cols:
        warnings.append(
            f"{len(null_rep.warn_cols)} cols with 1-50% nulls: "
            f"{', '.join(null_rep.warn_cols[:10])}"
            + (" ..." if len(null_rep.warn_cols) > 10 else "")
        )
    if bad_tickers:
        warnings.append(
            f"{len(bad_tickers)} bad tickers flagged (extreme returns): "
            f"{', '.join(bad_tickers[:10])}"
            + (" ..." if len(bad_tickers) > 10 else "")
        )

    p0_failures: List[str] = []
    if null_rep.p0_cols:
        p0_failures.append(f"null>50%: {', '.join(null_rep.p0_cols)}")
        action += [f"[null>50%] fix or drop upstream: {c}" for c in null_rep.p0_cols]
    if zero_var:
        p0_failures.append(f"zero-variance: {', '.join(zero_var)}")
        action += [f"[zero-variance] remove from feature_pipeline: {c}" for c in zero_var]
    if inf_cols:
        p0_failures.append(
            "inf>10%: " + ", ".join(f"{c}({r:.1%})" for c, r in inf_cols.items())
        )
        action += [f"[inf>10%] guard division upstream: {c}" for c in inf_cols]
    if leak_cols:
        p0_failures.append(f"leakage: {', '.join(leak_cols)}")
        action += [f"[leakage] exclude from feature set: {c}" for c in leak_cols]

    passed = not p0_failures
    report = DataQualityReport(
        passed=passed,
        null_rates=null_rep.rates,
        null_p0_cols=null_rep.p0_cols,
        zero_variance_cols=zero_var,
        infinite_cols=inf_cols,
        bad_tickers=bad_tickers,
        leakage_cols=leak_cols,
        warnings=warnings,
        action_required=action,
    )

    if not passed:
        raise DataQualityError(
            f"P0 data-quality gate failed (mode={mode}): " + " | ".join(p0_failures)
        )
    return report
