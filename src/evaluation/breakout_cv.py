"""breakout_cv: purged/embargoed walk-forward CV for the breakout regressor.

Evaluates a regressor predicting `breakout_proximity`.
Metrics:
- Rank IC: per-date Spearman correlation between prediction and realized proximity.
- Top-K Precision: Of the top K predicted stocks per date, how many actually broke out?
- Top-K Recall: Of the stocks that actually broke out, how many were in the top K?
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .gate import GateResult
from .walk_forward import FoldSpec, anchored_walk_forward
from .m02_cv import cross_sectional_rank_ic, assert_no_leakage, _slice

logger = logging.getLogger(__name__)


@dataclass
class BreakoutFoldResult:
    spec: FoldSpec
    rank_ic_mean: float          # mean per-date Spearman IC
    rank_ic_std: float
    rmse: float
    precision_at_50: float       # mean over dates
    recall_at_50: float          # mean over dates
    n_train: int
    n_test: int


@dataclass
class BreakoutCVReport:
    target_col: str
    horizon: int
    fold_results: List[BreakoutFoldResult] = field(default_factory=list)
    gates: List[dict] = field(default_factory=list)


def precision_recall_at_k(
    df: pd.DataFrame,
    date_col: str,
    pred_col: str,
    target_col: str,
    k: int = 50
) -> Tuple[float, float]:
    """Calculate mean precision@k and recall@k across all dates.
    A true positive is a row where target > 0.
    """
    precisions = []
    recalls = []
    
    for _, grp in df.groupby(date_col):
        # We need at least some rows to rank
        if len(grp) < k:
            continue
            
        # Actual positives
        actual_positives = (grp[target_col] > 0).sum()
        if actual_positives == 0:
            continue
            
        # Top K predictions
        top_k = grp.nlargest(k, pred_col)
        hits = (top_k[target_col] > 0).sum()
        
        precisions.append(hits / k)
        recalls.append(hits / actual_positives)
        
    if not precisions:
        return float("nan"), float("nan")
        
    return float(np.mean(precisions)), float(np.mean(recalls))


def run_breakout_cv(
    df: pd.DataFrame,
    date_col: str,
    feature_cols: Sequence[str],
    target_col: str,
    train_start: date,
    test_start: date,
    test_end: date,
    horizon: int,
    train_fn: Callable[[pd.DataFrame, pd.Series], object],
    step: str = "1Y",
    min_train_years: int = 3,
    rank_ic_tripwire: float = 0.02,
) -> BreakoutCVReport:
    """Run embargoed anchored walk-forward for the breakout regressor."""
    fold_specs = list(
        anchored_walk_forward(
            df, date_col, train_start, test_start, test_end,
            step=step, min_train_years=min_train_years, embargo_days=horizon,
        )
    )
    report = BreakoutCVReport(target_col=target_col, horizon=horizon)

    for spec in fold_specs:
        train_slice = _slice(df, date_col, spec.train_start, spec.train_end)
        test_slice = _slice(df, date_col, spec.test_start, spec.test_end)
        if train_slice.empty or test_slice.empty:
            continue

        assert_no_leakage(train_slice, spec.test_start, date_col, horizon)

        X_tr, y_tr = train_slice[list(feature_cols)], train_slice[target_col]
        X_te = test_slice[list(feature_cols)]
        
        # Train model
        model = train_fn(X_tr, y_tr)
        pred = np.asarray(model.predict(X_te))

        scored = test_slice[[date_col, target_col]].copy()
        scored["_pred"] = pred
        
        # Metrics
        ic_mean, ic_std = cross_sectional_rank_ic(scored, date_col, "_pred", target_col)
        resid = scored[target_col].to_numpy() - pred
        p50, r50 = precision_recall_at_k(scored, date_col, "_pred", target_col, k=50)
        
        report.fold_results.append(
            BreakoutFoldResult(
                spec=spec,
                rank_ic_mean=ic_mean, 
                rank_ic_std=ic_std,
                rmse=float(np.sqrt(np.mean(resid ** 2))),
                precision_at_50=p50,
                recall_at_50=r50,
                n_train=len(X_tr), 
                n_test=len(X_te),
            )
        )

    report.gates = _build_gates(report, rank_ic_tripwire)
    return report


def _build_gates(report: BreakoutCVReport, rank_ic_tripwire: float) -> List[dict]:
    gates: List[dict] = []
    ics = [fr.rank_ic_mean for fr in report.fold_results if not np.isnan(fr.rank_ic_mean)]
    worst = float(np.min(ics)) if ics else float("nan")
    gates.append(
        GateResult(
            name="breakout_rank_ic_tripwire",
            status="pass" if (ics and worst >= rank_ic_tripwire) else "fail",
            value=worst,
            threshold=rank_ic_tripwire,
            detail=f"worst-fold cross-sectional Rank IC (tripwire)",
            blocking=False,
        ).to_dict()
    )
    return gates
