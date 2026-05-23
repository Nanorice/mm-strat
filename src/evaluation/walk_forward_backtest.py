"""Walk-forward backtest harness.

Takes per-fold classifier results from `walk_forward.run_walk_forward` and turns
each fold's out-of-sample predictions into an actual backtest run. Aggregates
across folds and emits gates on mean Sharpe, worst-fold Sharpe, worst-fold
max DD, and mean top-3 Home-Run lift.

Design notes:
  * The harness does NOT itself open DuckDB or load price data — it delegates
    the backtest leg to a `backtest_fn(scores_df, fold_dir) -> dict` callable
    so test fixtures can substitute a deterministic mock and production callers
    can wire `SEPABacktestRunner`.
  * The classifier-side step is also delegated, via `signals_to_scores`, since
    the mapping from `y_pred_proba` to a `(date, ticker, normalized_score,
    daily_pct_rank, prob_elite)` frame depends on how the caller's model frames
    its production class. A default `default_signals_to_scores` is provided.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional

import numpy as np
import pandas as pd

from .gate import GateResult
from .walk_forward import FoldResult, FoldSpec

logger = logging.getLogger(__name__)


SignalsToScoresFn = Callable[[FoldResult, int], pd.DataFrame]
BacktestFn = Callable[[pd.DataFrame, Path], dict]


@dataclass
class FoldBacktestResult:
    fold_spec: FoldSpec
    trades: pd.DataFrame
    equity_curve: pd.DataFrame
    metrics: dict
    scores_rows: int = 0


def default_signals_to_scores(
    fold_result: FoldResult,
    production_class_idx: int,
    date_col: str = "date",
    ticker_col: str = "ticker",
) -> pd.DataFrame:
    """Default mapping: proba[:, production_class_idx] becomes the score.

    Replicates the contract of `UniverseScorer.score_from_t3`: emits
    columns (date, ticker, normalized_score, daily_pct_rank, prob_elite).

    `fold_result.X_test` must have a date column and a ticker column. If only
    the index carries them (a (ticker, date) MultiIndex), the caller should
    pre-flatten before calling this helper.
    """
    X = fold_result.X_test
    if date_col not in X.columns or ticker_col not in X.columns:
        raise KeyError(
            f"X_test must contain '{date_col}' and '{ticker_col}' columns; "
            f"got {list(X.columns)[:10]}..."
        )

    proba = np.asarray(fold_result.y_pred_proba)
    if proba.ndim != 2:
        raise ValueError(f"y_pred_proba must be 2-D, got shape {proba.shape}")
    if production_class_idx >= proba.shape[1]:
        raise IndexError(
            f"production_class_idx={production_class_idx} out of range "
            f"for proba.shape[1]={proba.shape[1]}"
        )

    prob_elite = proba[:, production_class_idx]
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(X[date_col].values),
            "ticker": X[ticker_col].astype(str).values,
            "prob_elite": prob_elite,
            "calibrated_score": prob_elite,
        }
    )

    # daily_pct_rank within each date
    out["daily_pct_rank"] = out.groupby("date")["calibrated_score"].transform(
        lambda s: s.rank(pct=True)
    )

    # normalized_score: linear 0..100 over the full fold window
    cmin, cmax = out["calibrated_score"].min(), out["calibrated_score"].max()
    if cmax > cmin:
        out["normalized_score"] = (out["calibrated_score"] - cmin) / (cmax - cmin) * 100.0
    else:
        out["normalized_score"] = 50.0

    # trailing_pct: leave blank — the SEPA strategy doesn't require it for entry.
    out["trailing_pct"] = np.nan

    return out.sort_values(["date", "daily_pct_rank"], ascending=[True, False]).reset_index(drop=True)


def _top_k_home_run_lift(
    fold_result: FoldResult,
    production_class_idx: int,
    k: int = 3,
) -> Optional[float]:
    """Top-k lift on the production class: P(class=prod | rank in top-k by score) / P(class=prod).

    Computed per-date and then averaged. Returns None if the test slice has no
    production-class samples.
    """
    y_true = np.asarray(fold_result.y_test)
    proba = np.asarray(fold_result.y_pred_proba)
    if proba.ndim != 2 or proba.shape[0] != y_true.shape[0]:
        return None

    score = proba[:, production_class_idx]
    is_prod = (y_true == production_class_idx).astype(float)

    X = fold_result.X_test
    if "date" not in X.columns:
        # Single-date or no temporal grouping — global top-k.
        top_idx = np.argsort(-score)[:k]
        if len(top_idx) == 0:
            return None
        base_rate = float(is_prod.mean())
        if base_rate == 0:
            return None
        top_rate = float(is_prod[top_idx].mean())
        return top_rate / base_rate

    dates = pd.to_datetime(X["date"].values)
    df = pd.DataFrame({"date": dates, "score": score, "is_prod": is_prod})
    base_rate = float(df["is_prod"].mean())
    if base_rate == 0:
        return None

    daily = (
        df.sort_values("score", ascending=False)
        .groupby("date")
        .head(k)
        .groupby("date")["is_prod"]
        .mean()
    )
    if daily.empty:
        return None
    return float(daily.mean() / base_rate)


def run_walk_forward_backtest(
    fold_results: List[FoldResult],
    production_class_idx: int,
    backtest_fn: BacktestFn,
    output_dir: Path,
    signals_to_scores: Optional[SignalsToScoresFn] = None,
    top_k_lift: int = 3,
) -> List[FoldBacktestResult]:
    """Run a backtest for each fold's OOS predictions.

    Args:
        fold_results: from `run_walk_forward`.
        production_class_idx: which proba column the strategy treats as elite.
        backtest_fn: callable that takes (scores_df, fold_output_dir) and
            returns a dict with at minimum
            {'sharpe_ratio', 'max_drawdown', 'win_rate', 'total_return',
             'trades_df': pd.DataFrame, 'equity_df': pd.DataFrame}.
            Anything else carried in the dict is passed through to metrics.
        output_dir: per-fold subdirectories are created inside this.
        signals_to_scores: maps FoldResult to a scores_df with the columns
            `default_signals_to_scores` produces. Override for non-MFE models.
        top_k_lift: k for the home-run-lift metric.

    Returns:
        One FoldBacktestResult per processed fold.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if signals_to_scores is None:
        signals_to_scores = default_signals_to_scores

    out: List[FoldBacktestResult] = []
    for fr in fold_results:
        fold_dir = output_dir / f"fold_{fr.spec.fold_idx:02d}"
        fold_dir.mkdir(parents=True, exist_ok=True)

        try:
            scores_df = signals_to_scores(fr, production_class_idx)
        except Exception as e:
            logger.warning("fold_idx=%d signals_to_scores failed: %s", fr.spec.fold_idx, e)
            continue

        if scores_df is None or scores_df.empty:
            logger.warning("fold_idx=%d produced empty scores_df", fr.spec.fold_idx)
            continue

        bt_out = backtest_fn(scores_df, fold_dir)

        trades = bt_out.get("trades_df", pd.DataFrame())
        equity = bt_out.get("equity_df", pd.DataFrame())

        metrics = {
            k: v for k, v in bt_out.items() if k not in {"trades_df", "equity_df"}
        }
        lift = _top_k_home_run_lift(fr, production_class_idx, k=top_k_lift)
        metrics[f"top_{top_k_lift}_home_run_lift"] = lift

        # Persist per-fold artifacts.
        try:
            if isinstance(trades, pd.DataFrame) and not trades.empty:
                trades.to_parquet(fold_dir / "trades.parquet")
            if isinstance(equity, pd.DataFrame) and not equity.empty:
                equity.to_parquet(fold_dir / "equity.parquet")
            (fold_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str))
        except Exception as e:  # pragma: no cover — disk I/O issues only
            logger.warning("fold_idx=%d artifact write failed: %s", fr.spec.fold_idx, e)

        out.append(
            FoldBacktestResult(
                fold_spec=fr.spec,
                trades=trades if isinstance(trades, pd.DataFrame) else pd.DataFrame(),
                equity_curve=equity if isinstance(equity, pd.DataFrame) else pd.DataFrame(),
                metrics=metrics,
                scores_rows=int(len(scores_df)),
            )
        )

    return out


def _safe_mean(values: List[Optional[float]]) -> float:
    arr = np.asarray([v for v in values if v is not None and not (isinstance(v, float) and np.isnan(v))], dtype=float)
    if arr.size == 0:
        return float("nan")
    return float(arr.mean())


def _safe_min(values: List[Optional[float]]) -> float:
    arr = np.asarray([v for v in values if v is not None and not (isinstance(v, float) and np.isnan(v))], dtype=float)
    if arr.size == 0:
        return float("nan")
    return float(arr.min())


def aggregate_walk_forward_backtest(
    bt_results: List[FoldBacktestResult],
    mean_sharpe_threshold: float = 0.5,
    worst_sharpe_threshold: float = -0.3,
    min_positive_folds: int = 7,
    min_total_folds_for_positive_gate: int = 9,
    worst_max_dd_threshold: float = 35.0,
    mean_top_k_lift_threshold: float = 5.0,
    top_k: int = 3,
) -> dict:
    """Aggregate per-fold backtest metrics and emit gates.

    Gate set (per plan §3.1):
      - mean Sharpe > mean_sharpe_threshold
      - worst-fold Sharpe > worst_sharpe_threshold AND
        positive_folds >= min_positive_folds out of min_total_folds_for_positive_gate
        (sized down proportionally when fewer folds were run)
      - worst-fold max DD < worst_max_dd_threshold
      - mean top-k Home Run lift > mean_top_k_lift_threshold
    """
    if not bt_results:
        return {"per_fold": [], "summary": {}, "gates": []}

    rows = []
    for r in bt_results:
        m = r.metrics
        rows.append(
            {
                "fold_idx": r.fold_spec.fold_idx,
                "train_start": r.fold_spec.train_start.isoformat(),
                "train_end": r.fold_spec.train_end.isoformat(),
                "test_start": r.fold_spec.test_start.isoformat(),
                "test_end": r.fold_spec.test_end.isoformat(),
                "sharpe_ratio": m.get("sharpe_ratio"),
                "max_drawdown": m.get("max_drawdown"),
                "win_rate": m.get("win_rate"),
                "total_return": m.get("total_return"),
                "total_trades": m.get("total_trades"),
                f"top_{top_k}_home_run_lift": m.get(f"top_{top_k}_home_run_lift"),
                "scores_rows": r.scores_rows,
            }
        )

    df = pd.DataFrame(rows)

    sharpes = list(df["sharpe_ratio"])
    dds = list(df["max_drawdown"])
    lifts = list(df[f"top_{top_k}_home_run_lift"])

    mean_sharpe = _safe_mean(sharpes)
    worst_sharpe = _safe_min(sharpes)
    worst_dd = _safe_mean([])  # placeholder; computed below
    positive_folds = int(np.sum([(s is not None and not (isinstance(s, float) and np.isnan(s)) and s > 0) for s in sharpes]))
    n_folds = len(sharpes)
    mean_lift = _safe_mean(lifts)

    # Max drawdown convention: this codebase reports DD as a positive percentage
    # (e.g., 22.5 means 22.5%). "Worst" fold = largest drawdown.
    valid_dds = [d for d in dds if d is not None and not (isinstance(d, float) and np.isnan(d))]
    worst_dd = float(np.max(valid_dds)) if valid_dds else float("nan")

    # Aggregate equity curve: concatenate OOS windows in fold order.
    parts = []
    for r in sorted(bt_results, key=lambda x: x.fold_spec.fold_idx):
        eq = r.equity_curve
        if isinstance(eq, pd.DataFrame) and not eq.empty:
            tmp = eq.copy()
            tmp["fold_idx"] = r.fold_spec.fold_idx
            parts.append(tmp)
    aggregate_equity = pd.concat(parts, axis=0) if parts else pd.DataFrame()

    summary = {
        "n_folds": int(n_folds),
        "mean_sharpe": mean_sharpe,
        "worst_sharpe": worst_sharpe,
        "positive_folds": positive_folds,
        "worst_max_drawdown": worst_dd,
        f"mean_top_{top_k}_home_run_lift": mean_lift,
    }

    gates: List[dict] = []

    gates.append(
        GateResult(
            name="wf_backtest_mean_sharpe",
            status="pass" if (not np.isnan(mean_sharpe) and mean_sharpe > mean_sharpe_threshold) else "fail",
            value=float(mean_sharpe),
            threshold=float(mean_sharpe_threshold),
            detail=f"mean Sharpe across {n_folds} folds",
            blocking=True,
        ).to_dict()
    )

    # Worst-fold Sharpe & positive-folds combination gate.
    required_positive = int(round(min_positive_folds * n_folds / min_total_folds_for_positive_gate))
    required_positive = max(1, min(required_positive, n_folds))
    worst_ok = not np.isnan(worst_sharpe) and worst_sharpe > worst_sharpe_threshold
    pos_ok = positive_folds >= required_positive
    gates.append(
        GateResult(
            name="wf_backtest_worst_sharpe",
            status="pass" if (worst_ok and pos_ok) else "fail",
            value=float(worst_sharpe),
            threshold=float(worst_sharpe_threshold),
            detail=(
                f"worst Sharpe={worst_sharpe:.3f}, "
                f"positive_folds={positive_folds}/{n_folds} (required {required_positive})"
            ),
            blocking=True,
        ).to_dict()
    )

    gates.append(
        GateResult(
            name="wf_backtest_worst_max_drawdown",
            status="pass" if (not np.isnan(worst_dd) and worst_dd < worst_max_dd_threshold) else "fail",
            value=float(worst_dd),
            threshold=float(worst_max_dd_threshold),
            detail=f"worst-fold max DD (lower is better)",
            blocking=True,
        ).to_dict()
    )

    gates.append(
        GateResult(
            name=f"wf_backtest_mean_top_{top_k}_home_run_lift",
            status="pass" if (not np.isnan(mean_lift) and mean_lift > mean_top_k_lift_threshold) else "fail",
            value=float(mean_lift),
            threshold=float(mean_top_k_lift_threshold),
            detail=f"mean top-{top_k} home-run lift across folds",
            blocking=True,
        ).to_dict()
    )

    return {
        "per_fold": rows,
        "summary": summary,
        "gates": gates,
        "aggregate_equity_rows": int(len(aggregate_equity)),
    }
