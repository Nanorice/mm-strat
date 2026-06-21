"""Section G — edge existence (permutation null + bootstrap CI + sample adequacy).

Three synthetic regimes mirroring the framework's three rubric outcomes:
  - perfect_model: observed metric is far in the tail of the null,
    permutation pct ≈ 100, both gates pass, sample adequacy varies by N.
  - random_model: observed metric is near the median of the null,
    permutation pct ≈ 50, gates fail.
  - degenerate (all-positive or all-negative labels): section fails the
    blocking 'degenerate_labels' gate fast.

Bootstrap iterations are kept low (50–100) to keep the test under a few
seconds; the production default is 500.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.evaluation.model_card.sections.section_g_edge import (
    ADEQUACY_MIN_POSITIVES,
    run_section_g,
    _make_date_blocks,
    _shuffled_pool_global,
    _shuffled_pool_per_day,
)


def _make_pool(n_days: int, per_day: int, *, kind: str, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = n_days * per_day
    dates = np.repeat(pd.date_range("2022-01-01", periods=n_days), per_day)
    mfe = rng.exponential(scale=20.0, size=n)
    label_binary = (mfe > 30.0).astype(int)
    if kind == "perfect":
        pred = mfe / (mfe.max() + 1e-9)
    elif kind == "random":
        pred = rng.uniform(size=n)
    elif kind == "weak":
        rank = mfe.argsort().argsort().astype(float) / (n - 1)
        pred = 0.4 * rank + 0.6 * rng.uniform(size=n)
    else:
        raise ValueError(kind)
    return pd.DataFrame({
        "ticker": [f"T{i:05d}" for i in range(n)],
        "date": pd.to_datetime(dates),
        "pred_proba": pred,
        "label_binary": label_binary,
        "label_mfe": mfe,
    })


def test_perfect_model_passes_blocking_gates():
    pool = _make_pool(n_days=40, per_day=50, kind="perfect", seed=1)
    section = run_section_g(
        pool, n_permutations=100, n_bootstrap=100, block_size_days=14, seed=11,
    )
    assert section.has_blocking_failure is False
    # G1 + G2 pass; G3 may pass or warn depending on positives count
    g1 = next(g for g in section.gates if g.name == "G1_permutation_null")
    g2 = next(g for g in section.gates if g.name == "G2_bootstrap_ci_excludes_baseline")
    assert g1.status == "pass", g1.detail
    assert g2.status == "pass", g2.detail
    # rubric scores: permutation and bootstrap both Good or Strong
    assert section.rubric_scores["permutation_min"] >= 2
    assert section.rubric_scores["bootstrap_min"] >= 2


def test_random_model_fails_blocking_gates():
    pool = _make_pool(n_days=40, per_day=50, kind="random", seed=2)
    section = run_section_g(
        pool, n_permutations=100, n_bootstrap=100, block_size_days=14, seed=22,
    )
    g1 = next(g for g in section.gates if g.name == "G1_permutation_null")
    g2 = next(g for g in section.gates if g.name == "G2_bootstrap_ci_excludes_baseline")
    # Random model has near-baseline observed metrics; expect G1 to fail.
    assert g1.status == "fail", g1.detail
    # G2 may occasionally pass by chance; check that AT LEAST one of {G1, G2} fails
    assert g1.status == "fail" or g2.status == "fail"
    # Permutation rubric should be Poor.
    assert section.rubric_scores["permutation_min"] == 0


def test_degenerate_labels_voids_section():
    # All positives — AUC / IC undefined.
    pool = _make_pool(n_days=10, per_day=20, kind="perfect", seed=3)
    pool["label_binary"] = 1
    section = run_section_g(
        pool, n_permutations=20, n_bootstrap=20, block_size_days=14, seed=33,
    )
    assert section.has_blocking_failure is True
    # Detail must explain why.
    assert "degenerate" in section.detail.lower() or "undefined" in section.detail.lower()


def test_empty_pool_voids_section():
    pool = pd.DataFrame(columns=["ticker", "date", "pred_proba", "label_binary"])
    section = run_section_g(
        pool, n_permutations=10, n_bootstrap=10, block_size_days=14,
    )
    assert section.has_blocking_failure is True


def test_sample_adequacy_thresholds():
    # Tiny pool — fewer than 50 positives → sample_adequacy = 0.
    pool = _make_pool(n_days=5, per_day=8, kind="perfect", seed=4)
    section = run_section_g(
        pool, n_permutations=20, n_bootstrap=20, block_size_days=14, seed=44,
    )
    n_pos = int(pool["label_binary"].sum())
    if n_pos < 50:
        assert section.rubric_scores["sample_adequacy"] == 0
    g3 = next(g for g in section.gates if g.name == "G3_sample_adequacy")
    # G3 is a warning gate, not blocking.
    assert g3.blocking is False


def test_shuffle_helpers_preserve_per_day_prevalence():
    """Per-day shuffle must keep each date's positive count unchanged."""
    rng = np.random.default_rng(0)
    pool = _make_pool(n_days=20, per_day=30, kind="perfect", seed=5)
    before = pool.groupby("date")["label_binary"].sum().to_numpy()
    shuf = _shuffled_pool_per_day(pool, rng)
    after = shuf.groupby("date")["label_binary"].sum().to_numpy()
    assert np.array_equal(before, after)


def test_global_shuffle_preserves_total_prevalence():
    rng = np.random.default_rng(0)
    pool = _make_pool(n_days=10, per_day=20, kind="random", seed=6)
    before = int(pool["label_binary"].sum())
    shuf = _shuffled_pool_global(pool, rng)
    after = int(shuf["label_binary"].sum())
    assert before == after


def test_date_blocks_cover_all_rows():
    pool = _make_pool(n_days=30, per_day=10, kind="random", seed=7)
    blocks = _make_date_blocks(pool["date"], block_size_days=7)
    assert len(blocks) >= 1
    # All positional indices covered exactly once
    covered = np.concatenate(blocks) if blocks else np.empty(0, dtype=int)
    assert sorted(covered.tolist()) == list(range(len(pool)))
