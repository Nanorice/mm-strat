"""Section D — pool builder + per-mode metric pass.

Mode A is the trivial filter on split.df; Mode B requires re-scoring
t3_sepa_features. We don't exercise the real DB here — instead we test that
the metric family (per-day IC, top-K lift, decile profile, tail recall,
top-vs-bot decile) produces correct closed-form values on a constructed
pool.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.evaluation.model_card.data_loader import EvalSplit, build_mode_a_pool
from src.evaluation.model_card.sections.section_d_ranker import (
    _decile_profile,
    _per_day_ic,
    _tail_recall,
    _top_k_lift,
    _top_vs_bottom_decile,
    run_section_d,
)


def _make_split(df: pd.DataFrame, pred: np.ndarray, mfe: np.ndarray) -> EvalSplit:
    label_binary = (mfe > 30.0).astype(int)
    label_4class = pd.cut(
        pd.Series(mfe), bins=[-np.inf, 2.0, 10.0, 30.0, np.inf],
        labels=False, include_lowest=True,
    ).astype(int)
    return EvalSplit(
        df=df,
        feature_cols=[],
        label_binary=pd.Series(label_binary, index=df.index),
        label_mfe=pd.Series(mfe, index=df.index),
        label_4class=pd.Series(label_4class.values, index=df.index),
        pred_proba=pd.Series(pred, index=df.index),
        meta={"n_rows": len(df), "prevalence": float(label_binary.mean()),
              "model_id": "synthetic", "date_min": str(df["date"].min()),
              "date_max": str(df["date"].max())},
        db_path=Path("."),
        model_path=Path("."),
    )


def _build_pool(n_days: int, per_day: int, *, seed: int, mfe_scale: float = 50.0,
                pred_strategy: str = "perfect") -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Construct a synthetic eval frame with n_days × per_day rows.

    Returns (df, pred, mfe). pred_strategy:
      'perfect'  — pred = MFE itself (rank-perfect)
      'random'   — pred ~ Uniform(0, 1)
      'inverted' — pred = -MFE
    """
    rng = np.random.default_rng(seed)
    n = n_days * per_day
    dates = np.repeat(pd.date_range("2024-01-01", periods=n_days), per_day)
    tickers = [f"T{i:04d}" for i in range(n)]
    mfe = rng.exponential(scale=mfe_scale, size=n)
    if pred_strategy == "perfect":
        pred = mfe / mfe.max()
    elif pred_strategy == "inverted":
        pred = -mfe
        pred = (pred - pred.min()) / (pred.max() - pred.min())
    elif pred_strategy == "random":
        pred = rng.uniform(size=n)
    else:
        raise ValueError(pred_strategy)
    df = pd.DataFrame({
        "ticker": tickers,
        "date": dates,
        "mfe_pct": mfe,
        "trend_ok": True,
    })
    return df, pred, mfe


def test_perfect_ranker_binary_ic_near_one():
    df, pred, mfe = _build_pool(n_days=20, per_day=50, seed=1, pred_strategy="perfect")
    split = _make_split(df, pred, mfe)
    pool = build_mode_a_pool(split)
    ic_mean, ic_med, _, t_stat, n_days = _per_day_ic(pool, "label_binary")
    assert n_days == 20
    # perfect rank correlation between P and MFE ⇒ binary IC may not be 1.0
    # (since binary label is a thresholded MFE) but must be strongly positive.
    assert ic_med > 0.5, ic_med
    assert t_stat > 5


def test_perfect_ranker_magnitude_ic_is_one():
    df, pred, mfe = _build_pool(n_days=20, per_day=50, seed=2, pred_strategy="perfect")
    split = _make_split(df, pred, mfe)
    pool = build_mode_a_pool(split)
    ic_mean, ic_med, _, _, _ = _per_day_ic(pool, "label_mfe")
    # P is a monotone transform of MFE ⇒ Spearman IC is identically 1.
    assert ic_med == pytest.approx(1.0)
    assert ic_mean == pytest.approx(1.0)


def test_random_ranker_ic_near_zero():
    df, pred, mfe = _build_pool(n_days=40, per_day=50, seed=3, pred_strategy="random")
    split = _make_split(df, pred, mfe)
    pool = build_mode_a_pool(split)
    _, ic_med, _, t_stat, _ = _per_day_ic(pool, "label_mfe")
    assert abs(ic_med) < 0.10, ic_med
    assert abs(t_stat) < 3, t_stat


def test_perfect_top5_lift_strictly_greater_than_one():
    df, pred, mfe = _build_pool(n_days=15, per_day=50, seed=4, pred_strategy="perfect")
    split = _make_split(df, pred, mfe)
    pool = build_mode_a_pool(split)
    lift = _top_k_lift(pool, "label_mfe", k=5)
    # Top 5 of 50 by MFE are by construction in the top 10% — must beat avg.
    assert lift > 1.5, lift


def test_random_top_k_lift_near_one():
    df, pred, mfe = _build_pool(n_days=40, per_day=50, seed=5, pred_strategy="random")
    split = _make_split(df, pred, mfe)
    pool = build_mode_a_pool(split)
    lift = _top_k_lift(pool, "label_mfe", k=5)
    # Random ranker on exponential MFE — top-5 should average around the
    # pool mean (lift ≈ 1) within sampling noise.
    assert 0.7 < lift < 1.3, lift


def test_perfect_tail_recall_is_one():
    df, pred, mfe = _build_pool(n_days=30, per_day=50, seed=6, pred_strategy="perfect")
    split = _make_split(df, pred, mfe)
    pool = build_mode_a_pool(split)
    tr = _tail_recall(pool, "label_mfe")
    # Perfect ranker: top decile of P = top decile of MFE ⊇ top 1% of MFE.
    assert tr == pytest.approx(1.0)


def test_random_tail_recall_near_ten_percent():
    df, pred, mfe = _build_pool(n_days=40, per_day=50, seed=7, pred_strategy="random")
    split = _make_split(df, pred, mfe)
    pool = build_mode_a_pool(split)
    tr = _tail_recall(pool, "label_mfe")
    # Random ranker: top decile of P captures ~10% of any other ranking.
    assert 0.0 <= tr <= 0.25, tr


def test_decile_profile_monotone_for_perfect_ranker():
    df, pred, mfe = _build_pool(n_days=20, per_day=100, seed=8, pred_strategy="perfect")
    split = _make_split(df, pred, mfe)
    pool = build_mode_a_pool(split)
    prof = _decile_profile(pool, "label_mfe")
    means = [r["mean"] for r in prof]
    # Strictly increasing means across deciles (with N=2000 there should be
    # no ties strong enough to break the order).
    assert all(a < b for a, b in zip(means, means[1:])), means


def test_top_vs_bottom_decile_large_for_perfect():
    df, pred, mfe = _build_pool(n_days=20, per_day=100, seed=9, pred_strategy="perfect")
    split = _make_split(df, pred, mfe)
    pool = build_mode_a_pool(split)
    ratio, top_mean, bot_mean = _top_vs_bottom_decile(pool, "label_mfe")
    assert ratio > 10, ratio
    assert top_mean > bot_mean


def test_run_section_d_perfect_passes_blocking_gates():
    df, pred, mfe = _build_pool(n_days=30, per_day=100, seed=10, pred_strategy="perfect")
    split = _make_split(df, pred, mfe)
    pool = build_mode_a_pool(split)
    section = run_section_d(split, pool, mode_b_pool=None)
    blocking_fail = [g for g in section.gates if g.blocking and g.status == "fail"]
    assert not blocking_fail, [(g.name, g.detail) for g in blocking_fail]
    assert section.rubric_scores.get("D_binary", 0) >= 2
    assert section.rubric_scores.get("D_magnitude", 0) >= 2


def test_run_section_d_random_fails_blocking_gates():
    df, pred, mfe = _build_pool(n_days=40, per_day=80, seed=11, pred_strategy="random")
    split = _make_split(df, pred, mfe)
    pool = build_mode_a_pool(split)
    section = run_section_d(split, pool, mode_b_pool=None)
    blocking_fail = [g for g in section.gates if g.blocking and g.status == "fail"]
    # Random ranker must trip at least one of D1/D2/D3 and at least one of D4/D5.
    fail_names = {g.name for g in blocking_fail}
    assert fail_names.intersection({"D1_binary_ic", "D2_top5_hit_lift", "D3_top_vs_bottom_decile"}), \
        fail_names
    assert fail_names.intersection({"D4_magnitude_ic", "D5_top5_magnitude_lift"}), \
        fail_names


def test_build_mode_a_pool_applies_trend_ok_filter():
    df = pd.DataFrame({
        "ticker": [f"T{i}" for i in range(10)],
        "date": pd.date_range("2024-01-01", periods=10),
        "mfe_pct": np.arange(10, dtype=float) * 10,
        "trend_ok": [True] * 5 + [False] * 5,
    })
    pred = np.linspace(0, 1, 10)
    mfe = df["mfe_pct"].values
    split = _make_split(df, pred, mfe)
    pool = build_mode_a_pool(split)
    assert len(pool) == 5
    assert (pool["pred_proba"] == pred[:5]).all()
