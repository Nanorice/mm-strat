"""m02_prototype: purged/embargoed walk-forward CV for the dense quantile regressor.

Reuses the anchored fold geometry from walk_forward.anchored_walk_forward (with
embargo_days = H so no training row's forward-H target window reaches into the test
fold) and the GateResult primitive from gate.py. Everything else here is m02-specific:
a regression train/score loop (quantile LightGBM) and the primary metric, cross-sectional
Rank IC.

Rank IC is the per-date Spearman correlation between the model's score and the realized
target, averaged over test dates — NOT a single pooled Spearman. The dashboard's job is
to rank today's candidates against each other, so IC must be measured within-date.

Leakage is asserted, not assumed: assert_no_leakage() verifies that for every fold the
latest training row's forward-window end falls strictly before test_start.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, List, Optional, Sequence

import numpy as np
import pandas as pd

from .gate import GateResult
from .walk_forward import FoldSpec, anchored_walk_forward

logger = logging.getLogger(__name__)

# Quantiles the m02 prototype predicts: P10 (stop), P50 (expected), P90 (take-profit).
DEFAULT_QUANTILES = (0.10, 0.50, 0.90)


@dataclass
class M02FoldResult:
    spec: FoldSpec
    quantile: float
    rank_ic_mean: float          # mean per-date Spearman IC
    rank_ic_std: float
    rmse: float
    mae: float
    n_train: int
    n_test: int


@dataclass
class M02CVReport:
    target_col: str
    horizon: int
    quantile_results: dict = field(default_factory=dict)  # quantile -> List[M02FoldResult]
    gates: List[dict] = field(default_factory=list)


def cross_sectional_rank_ic(
    df: pd.DataFrame,
    date_col: str,
    pred_col: str,
    target_col: str,
) -> tuple[float, float]:
    """Mean and std of per-date Spearman rank correlation (pred vs realized target).

    Dates with < 3 ranked rows or zero variance are skipped (Spearman undefined).
    """
    ics: List[float] = []
    for _, grp in df.groupby(date_col):
        if len(grp) < 3:
            continue
        a = grp[pred_col].rank()
        b = grp[target_col].rank()
        if a.std(ddof=0) == 0 or b.std(ddof=0) == 0:
            continue
        ics.append(float(a.corr(b)))  # Pearson on ranks == Spearman
    if not ics:
        return float("nan"), float("nan")
    return float(np.mean(ics)), float(np.std(ics, ddof=0))


def assert_no_leakage(
    train_slice: pd.DataFrame,
    test_start: date,
    date_col: str,
    horizon: int,
) -> None:
    """Verify no training row's forward-H window reaches into the test fold.

    The latest training date + H calendar days must be strictly before test_start.
    Raises AssertionError otherwise (this is the executable form of the design's
    'CV completely eliminates overlapping dates' requirement).
    """
    if train_slice.empty:
        return
    max_train = pd.to_datetime(train_slice[date_col]).max().date()
    forward_end = max_train + timedelta(days=horizon)
    assert forward_end < test_start, (
        f"LEAKAGE: max train date {max_train} + {horizon}d = {forward_end} "
        f">= test_start {test_start}. Increase embargo_days."
    )


def _slice(df: pd.DataFrame, date_col: str, start: date, end: date) -> pd.DataFrame:
    d = pd.to_datetime(df[date_col]).dt.date
    return df.loc[(d >= start) & (d <= end)].copy()


def run_m02_cv(
    df: pd.DataFrame,
    date_col: str,
    feature_cols: Sequence[str],
    target_col: str,
    train_start: date,
    test_start: date,
    test_end: date,
    horizon: int,
    train_fn: Callable[[pd.DataFrame, pd.Series, float], object],
    quantiles: Sequence[float] = DEFAULT_QUANTILES,
    step: str = "1Y",
    min_train_years: int = 3,
    rank_ic_tripwire: float = 0.02,
) -> M02CVReport:
    """Run embargoed anchored walk-forward for each quantile; return per-fold IC + gates.

    `train_fn(X, y, alpha)` trains a quantile regressor at quantile `alpha` and returns
    a model exposing `.predict(X)`. Embargo is fixed to `horizon` days.
    """
    fold_specs = list(
        anchored_walk_forward(
            df, date_col, train_start, test_start, test_end,
            step=step, min_train_years=min_train_years, embargo_days=horizon,
        )
    )
    report = M02CVReport(target_col=target_col, horizon=horizon)

    for q in quantiles:
        fold_results: List[M02FoldResult] = []
        for spec in fold_specs:
            train_slice = _slice(df, date_col, spec.train_start, spec.train_end)
            test_slice = _slice(df, date_col, spec.test_start, spec.test_end)
            if train_slice.empty or test_slice.empty:
                continue

            assert_no_leakage(train_slice, spec.test_start, date_col, horizon)

            X_tr, y_tr = train_slice[list(feature_cols)], train_slice[target_col]
            X_te = test_slice[list(feature_cols)]
            model = train_fn(X_tr, y_tr, q)
            pred = np.asarray(model.predict(X_te))

            scored = test_slice[[date_col, target_col]].copy()
            scored["_pred"] = pred
            ic_mean, ic_std = cross_sectional_rank_ic(scored, date_col, "_pred", target_col)
            resid = scored[target_col].to_numpy() - pred
            fold_results.append(
                M02FoldResult(
                    spec=spec, quantile=q,
                    rank_ic_mean=ic_mean, rank_ic_std=ic_std,
                    rmse=float(np.sqrt(np.mean(resid ** 2))),
                    mae=float(np.mean(np.abs(resid))),
                    n_train=len(X_tr), n_test=len(X_te),
                )
            )
        report.quantile_results[q] = fold_results

    report.gates = _build_gates(report, rank_ic_tripwire)
    return report


def _build_gates(report: M02CVReport, rank_ic_tripwire: float) -> List[dict]:
    """Rank IC tripwire on the P50 quantile's worst fold (kill switch, not ship gate)."""
    gates: List[dict] = []
    p50 = report.quantile_results.get(0.50, [])
    ics = [fr.rank_ic_mean for fr in p50 if not np.isnan(fr.rank_ic_mean)]
    worst = float(np.min(ics)) if ics else float("nan")
    gates.append(
        GateResult(
            name="m02_rank_ic_tripwire",
            status="pass" if (ics and worst >= rank_ic_tripwire) else "fail",
            value=worst,
            threshold=rank_ic_tripwire,
            detail=f"worst-fold P50 cross-sectional Rank IC (tripwire, not ship gate)",
            blocking=False,
        ).to_dict()
    )
    return gates
