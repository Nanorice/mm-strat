"""End-to-end synthetic-classifier sanity for Sections B + D + E together.

The plan's Phase 2 acceptance: random ≈ 0 score, perfect ≈ full score,
weak ≈ middle band. We exercise only B/D/E (the metric-bearing scored
sections in Phase 2 that don't depend on the DB).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.evaluation.model_card.data_loader import EvalSplit, build_mode_a_pool
from src.evaluation.model_card.sections.section_b_discrimination import run_section_b
from src.evaluation.model_card.sections.section_d_ranker import run_section_d
from src.evaluation.model_card.sections.section_e_gates import run_section_e


def _make_eval(n_days: int, per_day: int, *, seed: int, kind: str) -> EvalSplit:
    rng = np.random.default_rng(seed)
    n = n_days * per_day
    dates = np.repeat(pd.date_range("2022-01-01", periods=n_days), per_day)
    mfe = rng.exponential(scale=20.0, size=n)
    label_binary = (mfe > 30.0).astype(int)

    if kind == "perfect":
        # Perfect rank by MFE, but compressed into (0, 1) so threshold gates have meaning.
        pred = mfe.argsort().argsort().astype(float) / (n - 1)
    elif kind == "random":
        pred = rng.uniform(size=n)
    elif kind == "weak":
        # 0.2 signal + 0.8 noise — moderate signal that won't cross the
        # "Strong" bands but should still beat random.
        rank = mfe.argsort().argsort().astype(float) / (n - 1)
        noise = rng.uniform(size=n)
        pred = 0.2 * rank + 0.8 * noise
    else:
        raise ValueError(kind)

    df = pd.DataFrame({
        "ticker": [f"T{i:05d}" for i in range(n)],
        "date": dates,
        "mfe_pct": mfe,
        "trend_ok": True,
    })
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
        meta={"n_rows": n, "prevalence": float(label_binary.mean()),
              "model_id": f"synthetic_{kind}",
              "date_min": str(df["date"].min()),
              "date_max": str(df["date"].max())},
        db_path=Path("."), model_path=Path("."),
    )


def _run_b_d_e(split: EvalSplit):
    pool = build_mode_a_pool(split)
    return {
        "B": run_section_b(split),
        "D": run_section_d(split, pool, mode_b_pool=None),
        "E": run_section_e(split, pool),
    }


def test_perfect_model_strong_bands():
    split = _make_eval(n_days=30, per_day=80, seed=100, kind="perfect")
    results = _run_b_d_e(split)
    # D_binary and D_magnitude should score 2 or 3 (Good / Strong).
    assert results["D"].rubric_scores.get("D_magnitude", 0) >= 2
    assert results["D"].rubric_scores.get("D_binary", 0) >= 2
    # B's AUC must be near 1
    auc = next(m.value for m in results["B"].metrics if m.name == "roc_auc")
    assert auc > 0.95
    # Blocking gates all pass
    for sec in results.values():
        bad = [g for g in sec.gates if g.blocking and g.status == "fail"]
        assert not bad, f"{sec.name}: {[g.name for g in bad]}"


def test_random_model_fails_blocking_gates():
    split = _make_eval(n_days=40, per_day=80, seed=200, kind="random")
    results = _run_b_d_e(split)
    # At least one blocking failure across B/D/E.
    n_fail = sum(
        sum(1 for g in sec.gates if g.blocking and g.status == "fail")
        for sec in results.values()
    )
    assert n_fail >= 2, n_fail
    # D ranker scores: at least one half scores 0 (Poor).
    binary = results["D"].rubric_scores.get("D_binary")
    mag = results["D"].rubric_scores.get("D_magnitude")
    assert (binary == 0) or (mag == 0), (binary, mag)


def test_weak_model_partial_pass():
    split = _make_eval(n_days=30, per_day=80, seed=300, kind="weak")
    results = _run_b_d_e(split)
    # Weak model: should have a moderate AUC and pass at least one of B's gates.
    auc = next(m.value for m in results["B"].metrics if m.name == "roc_auc")
    assert 0.55 < auc < 0.95, auc
    # D magnitude IC must be positive (signal carries through despite noise).
    ic_med = next(m.value for m in results["D"].metrics if m.name == "Amag_ic_median")
    assert ic_med > 0
