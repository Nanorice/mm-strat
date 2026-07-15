"""Tests for src.evaluation.walk_forward_backtest (§3.1)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.evaluation.walk_forward import FoldResult, FoldSpec
from src.evaluation.walk_forward_backtest import (
    FoldBacktestResult,
    aggregate_backtest_cone,
    aggregate_walk_forward_backtest,
    default_signals_to_scores,
    run_walk_forward_backtest,
)


def _make_fold(
    fold_idx: int,
    n_rows: int = 200,
    n_tickers: int = 10,
    seed: int = 0,
    prod_signal: float = 0.8,
    n_classes: int = 4,
) -> FoldResult:
    """Build a FoldResult whose X_test carries `date`+`ticker` columns and a
    `y_pred_proba` whose production-class score correlates with truth at
    `prod_signal`."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2022-01-03", periods=n_rows // n_tickers + 1)
    tickers = [f"T{i:03d}" for i in range(n_tickers)]
    rows = []
    for d in dates:
        for tk in tickers:
            rows.append((d, tk))
            if len(rows) >= n_rows:
                break
        if len(rows) >= n_rows:
            break

    X = pd.DataFrame(rows, columns=["date", "ticker"]).head(n_rows)
    y = pd.Series(rng.integers(0, n_classes, n_rows))

    is_prod = (y == n_classes - 1).astype(float).values
    prod_score = prod_signal * is_prod + (1 - prod_signal) * rng.uniform(0, 1, n_rows)

    other = rng.uniform(0, 1, (n_rows, n_classes - 1))
    raw = np.column_stack([other, prod_score.reshape(-1, 1)])
    proba = raw / raw.sum(axis=1, keepdims=True)

    spec = FoldSpec(
        fold_idx=fold_idx,
        train_start=date(2019, 1, 1),
        train_end=date(2019 + fold_idx, 1, 1),
        test_start=date(2019 + fold_idx, 1, 2),
        test_end=date(2020 + fold_idx, 1, 1),
    )
    return FoldResult(
        spec=spec,
        model_path=None,
        X_test=X,
        y_test=y,
        y_pred_proba=proba,
        metrics={"n_train": 1000, "n_test": n_rows, "accuracy": 0.5,
                 "weighted_f1": 0.5, "macro_f1": 0.5},
        train_seconds=0.1,
    )


def _mock_backtest_fn(
    sharpe: float, max_dd: float, win_rate: float = 0.55, total_return: float = 10.0,
) -> callable:
    """Build a backtest_fn that returns canned metrics + tiny trades/equity frames."""

    def fn(scores_df: pd.DataFrame, fold_dir: Path) -> dict:
        n_signals = (scores_df["daily_pct_rank"] > 0.95).sum()
        trades = pd.DataFrame(
            {
                "entry_date": scores_df["date"].iloc[: max(1, n_signals)],
                "ticker": scores_df["ticker"].iloc[: max(1, n_signals)],
                "pnl_percent": np.linspace(-5, 15, max(1, n_signals)),
            }
        )
        equity = pd.DataFrame(
            {
                "date": pd.bdate_range("2022-01-03", periods=10),
                "value": np.linspace(100_000, 100_000 * (1 + total_return / 100), 10),
            }
        )
        return {
            "sharpe_ratio": sharpe,
            "max_drawdown": max_dd,
            "win_rate": win_rate,
            "total_return": total_return,
            "total_trades": int(len(trades)),
            "trades_df": trades,
            "equity_df": equity,
        }

    return fn


# ----------------------------- default_signals_to_scores -----------------------------


def test_default_signals_to_scores_emits_expected_columns():
    fr = _make_fold(fold_idx=0, seed=1)
    out = default_signals_to_scores(fr, production_class_idx=3)
    assert {"date", "ticker", "prob_elite", "normalized_score",
            "daily_pct_rank", "calibrated_score"}.issubset(out.columns)
    # Ranks lie in (0, 1].
    assert out["daily_pct_rank"].between(0, 1).all()
    # 0..100 range for normalized_score.
    assert out["normalized_score"].between(0, 100).all()


def test_default_signals_to_scores_rejects_missing_columns():
    fr = _make_fold(fold_idx=0, seed=1)
    fr.X_test = fr.X_test.drop(columns=["ticker"])
    with pytest.raises(KeyError, match="must contain"):
        default_signals_to_scores(fr, production_class_idx=3)


def test_default_signals_to_scores_rejects_bad_prod_idx():
    fr = _make_fold(fold_idx=0, seed=1)
    with pytest.raises(IndexError):
        default_signals_to_scores(fr, production_class_idx=99)


# ----------------------------- run_walk_forward_backtest -----------------------------


def test_run_wf_backtest_produces_one_result_per_fold(tmp_path: Path):
    folds = [_make_fold(i, seed=10 + i) for i in range(3)]
    bt = run_walk_forward_backtest(
        fold_results=folds,
        production_class_idx=3,
        backtest_fn=_mock_backtest_fn(sharpe=1.2, max_dd=12.0),
        output_dir=tmp_path,
    )
    assert len(bt) == 3
    for r in bt:
        assert "sharpe_ratio" in r.metrics
        assert "top_3_home_run_lift" in r.metrics  # >0 because prod_signal=0.8
        assert r.metrics["top_3_home_run_lift"] is None or r.metrics["top_3_home_run_lift"] > 0
        assert r.scores_rows > 0
        # Per-fold artifacts written.
        fold_dir = tmp_path / f"fold_{r.fold_spec.fold_idx:02d}"
        assert (fold_dir / "metrics.json").exists()


def test_run_wf_backtest_skips_fold_when_signals_to_scores_raises(tmp_path: Path):
    """If signals_to_scores raises (e.g., missing cols), the fold is dropped."""
    folds = [_make_fold(i, seed=20 + i) for i in range(2)]
    folds[0].X_test = folds[0].X_test.drop(columns=["date"])

    bt = run_walk_forward_backtest(
        fold_results=folds,
        production_class_idx=3,
        backtest_fn=_mock_backtest_fn(sharpe=1.0, max_dd=10.0),
        output_dir=tmp_path,
    )
    assert len(bt) == 1
    assert bt[0].fold_spec.fold_idx == 1


def test_run_wf_backtest_with_custom_signals_to_scores(tmp_path: Path):
    folds = [_make_fold(0, seed=33)]
    captured = {}

    def custom_s2s(fr: FoldResult, idx: int) -> pd.DataFrame:
        captured["called"] = True
        return pd.DataFrame(
            {
                "date": pd.to_datetime(fr.X_test["date"].values),
                "ticker": fr.X_test["ticker"].values,
                "prob_elite": np.zeros(len(fr.X_test)),
                "normalized_score": np.full(len(fr.X_test), 50.0),
                "daily_pct_rank": np.full(len(fr.X_test), 0.5),
            }
        )

    bt = run_walk_forward_backtest(
        fold_results=folds,
        production_class_idx=3,
        backtest_fn=_mock_backtest_fn(sharpe=0.9, max_dd=8.0),
        output_dir=tmp_path,
        signals_to_scores=custom_s2s,
    )
    assert captured["called"]
    assert len(bt) == 1


# ----------------------------- aggregate_walk_forward_backtest -----------------------------


def test_aggregate_empty_returns_empty_payload():
    out = aggregate_walk_forward_backtest([])
    assert out == {"per_fold": [], "summary": {}, "gates": []}


def _make_bt_result(fold_idx: int, sharpe: float, max_dd: float, lift: float) -> FoldBacktestResult:
    spec = FoldSpec(
        fold_idx=fold_idx,
        train_start=date(2019, 1, 1),
        train_end=date(2019 + fold_idx, 1, 1),
        test_start=date(2019 + fold_idx, 1, 2),
        test_end=date(2020 + fold_idx, 1, 1),
    )
    return FoldBacktestResult(
        fold_spec=spec,
        trades=pd.DataFrame(),
        equity_curve=pd.DataFrame(),
        metrics={
            "sharpe_ratio": sharpe,
            "max_drawdown": max_dd,
            "win_rate": 0.5,
            "total_return": 10.0,
            "total_trades": 25,
            "top_3_home_run_lift": lift,
        },
        scores_rows=100,
    )


def test_aggregate_gates_all_pass_on_strong_folds():
    bts = [_make_bt_result(i, sharpe=1.2, max_dd=15.0, lift=8.0) for i in range(9)]
    out = aggregate_walk_forward_backtest(bts)
    assert out["summary"]["n_folds"] == 9
    gates = {g["name"]: g for g in out["gates"]}
    assert gates["wf_backtest_mean_sharpe"]["status"] == "pass"
    assert gates["wf_backtest_worst_sharpe"]["status"] == "pass"
    assert gates["wf_backtest_worst_max_drawdown"]["status"] == "pass"
    assert gates["wf_backtest_mean_top_3_home_run_lift"]["status"] == "pass"


def test_aggregate_fails_mean_sharpe_when_weak():
    bts = [_make_bt_result(i, sharpe=0.2, max_dd=12.0, lift=8.0) for i in range(5)]
    out = aggregate_walk_forward_backtest(bts, mean_sharpe_threshold=0.5)
    gates = {g["name"]: g for g in out["gates"]}
    assert gates["wf_backtest_mean_sharpe"]["status"] == "fail"


def test_aggregate_fails_worst_sharpe_on_one_bad_fold():
    bts = [_make_bt_result(0, sharpe=1.2, max_dd=15.0, lift=8.0),
           _make_bt_result(1, sharpe=1.0, max_dd=18.0, lift=7.0),
           _make_bt_result(2, sharpe=-1.5, max_dd=22.0, lift=8.0)]  # bad fold
    out = aggregate_walk_forward_backtest(bts, worst_sharpe_threshold=-0.3)
    gates = {g["name"]: g for g in out["gates"]}
    assert gates["wf_backtest_worst_sharpe"]["status"] == "fail"


def test_aggregate_fails_max_dd_when_exceeded():
    bts = [_make_bt_result(i, sharpe=1.0, max_dd=50.0, lift=8.0) for i in range(3)]
    out = aggregate_walk_forward_backtest(bts, worst_max_dd_threshold=35.0)
    gates = {g["name"]: g for g in out["gates"]}
    assert gates["wf_backtest_worst_max_drawdown"]["status"] == "fail"
    assert gates["wf_backtest_worst_max_drawdown"]["value"] == 50.0


def test_aggregate_fails_lift_when_too_low():
    bts = [_make_bt_result(i, sharpe=1.0, max_dd=12.0, lift=1.5) for i in range(3)]
    out = aggregate_walk_forward_backtest(bts, mean_top_k_lift_threshold=5.0)
    gates = {g["name"]: g for g in out["gates"]}
    assert gates["wf_backtest_mean_top_3_home_run_lift"]["status"] == "fail"


def test_aggregate_records_blocking_gates():
    bts = [_make_bt_result(i, sharpe=1.0, max_dd=12.0, lift=8.0) for i in range(3)]
    out = aggregate_walk_forward_backtest(bts)
    gates = {g["name"]: g for g in out["gates"]}
    # Trade-edge gates block; the label-lift gate is diagnostic-only (label lift
    # != trade edge, sprint-14 Q28/Q33).
    assert gates["wf_backtest_mean_sharpe"]["blocking"] is True
    assert gates["wf_backtest_worst_sharpe"]["blocking"] is True
    assert gates["wf_backtest_worst_max_drawdown"]["blocking"] is True
    assert gates["wf_backtest_mean_top_3_home_run_lift"]["blocking"] is False


def test_aggregate_handles_nan_sharpe_gracefully():
    bts = [_make_bt_result(i, sharpe=float("nan"), max_dd=12.0, lift=8.0) for i in range(3)]
    out = aggregate_walk_forward_backtest(bts)
    gates = {g["name"]: g for g in out["gates"]}
    # NaN values can't satisfy "> threshold" → fail, not crash.
    assert gates["wf_backtest_mean_sharpe"]["status"] == "fail"
    assert gates["wf_backtest_worst_sharpe"]["status"] == "fail"


def test_aggregate_proportional_positive_folds_required():
    """With 3 folds, required positive = round(7 * 3 / 9) = 2."""
    # 2 positive, 1 negative — should still pass positive-count check (>=2).
    bts = [_make_bt_result(0, sharpe=0.6, max_dd=12.0, lift=8.0),
           _make_bt_result(1, sharpe=0.7, max_dd=15.0, lift=7.5),
           _make_bt_result(2, sharpe=-0.1, max_dd=14.0, lift=7.0)]
    out = aggregate_walk_forward_backtest(bts, worst_sharpe_threshold=-0.3)
    gates = {g["name"]: g for g in out["gates"]}
    assert gates["wf_backtest_worst_sharpe"]["status"] == "pass"


# ----------------------------- aggregate_backtest_cone -----------------------------

def _cone_cell(sharpe, dd=15.0, total_return=20.0):
    return {"sharpe_ratio": sharpe, "max_drawdown": dd, "total_return": total_return}


def test_cone_empty_returns_zero_cells():
    out = aggregate_backtest_cone([])
    assert out["summary"]["n_cells"] == 0
    assert out["gates"] == []


def test_cone_distribution_stats():
    cells = [_cone_cell(s) for s in [-0.5, 0.2, 0.6, 0.8, 1.5]]
    out = aggregate_backtest_cone(cells)
    s = out["summary"]
    assert s["n_cells"] == 5
    assert s["median_sharpe"] == pytest.approx(0.6)
    assert s["floor_sharpe"] == pytest.approx(-0.5)
    assert s["pct_negative_cells"] == pytest.approx(20.0)  # 1 of 5 negative
    # Calmar = total_return / |maxDD| = 20 / 15 for the default cell.
    assert s["median_calmar"] == pytest.approx(20.0 / 15.0)


def test_cone_gates_blocking_split_and_pass():
    # A strong cone (median 0.7, 0% neg, calmar 20/15=1.33) passes all blocking gates.
    out = aggregate_backtest_cone([_cone_cell(s) for s in [0.3, 0.7, 1.1]])
    gates = {g["name"]: g for g in out["gates"]}
    assert gates["cone_median_sharpe"]["blocking"] is True
    assert gates["cone_pct_negative"]["blocking"] is True
    assert gates["cone_median_calmar"]["blocking"] is True
    assert gates["cone_floor_sharpe"]["blocking"] is False  # diagnostic
    assert all(gates[n]["status"] == "pass"
               for n in ("cone_median_sharpe", "cone_pct_negative", "cone_median_calmar"))


def test_cone_median_sharpe_gate_fails_below_threshold():
    # Median Sharpe 0.05 < 0.20 threshold → the blocking gate fails.
    out = aggregate_backtest_cone([_cone_cell(s) for s in [-0.2, 0.05, 0.1]])
    g = {x["name"]: x for x in out["gates"]}["cone_median_sharpe"]
    assert g["status"] == "fail" and g["blocking"] is True


def test_cone_alpha_vs_spy_is_blocking():
    idx = pd.date_range("2024-01-01", periods=60, freq="B")
    rng = np.random.default_rng(1)
    bench = pd.Series(rng.normal(0.0005, 0.01, 60), index=idx)
    strat = 1.0 * bench + 0.001
    cells = [{**_cone_cell(0.8), "daily_returns": strat}]
    out = aggregate_backtest_cone(cells, bench_returns={"SPY": bench, "QQQ": bench})
    gates = {g["name"]: g for g in out["gates"]}
    assert gates["cone_alpha_vs_SPY"]["blocking"] is True
    assert gates["cone_alpha_vs_QQQ"]["blocking"] is False  # QQQ diagnostic
    assert gates["cone_beta_vs_SPY"]["blocking"] is False


def test_cone_alpha_beta_from_pooled_returns():
    # Strategy = 1.5x the benchmark + constant daily alpha → beta≈1.5, alpha>0.
    idx = pd.date_range("2024-01-01", periods=60, freq="B")
    rng = np.random.default_rng(0)
    bench = pd.Series(rng.normal(0.0005, 0.01, 60), index=idx)
    strat = 1.5 * bench + 0.001  # +0.1%/day alpha
    cells = [{**_cone_cell(0.8), "daily_returns": strat}]
    out = aggregate_backtest_cone(cells, bench_returns={"SPY": bench})
    assert out["summary"]["beta_vs_SPY"] == pytest.approx(1.5, abs=0.05)
    assert out["summary"]["alpha_ann_vs_SPY"] > 0
