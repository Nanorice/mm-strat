"""Tests for src.evaluation.drift (§2.2 of evaluation_remaining plan)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.evaluation.drift import (
    compute_psi,
    quarterly_drift_report,
    reference_snapshot,
)


def test_psi_identical_distribution_is_near_zero():
    rng = np.random.default_rng(0)
    ref = rng.normal(0, 1, 10_000)
    cur = rng.normal(0, 1, 10_000)  # same distribution, different sample
    psi = compute_psi(ref, cur, bins=10)
    assert psi < 0.01, f"PSI on identical distributions should be tiny, got {psi}"


def test_psi_one_sigma_shift_above_drift_threshold():
    rng = np.random.default_rng(1)
    ref = rng.normal(0, 1, 10_000)
    cur = rng.normal(1.0, 1, 10_000)  # shifted by 1σ
    psi = compute_psi(ref, cur, bins=10)
    assert psi > 0.25, f"PSI should clear drift threshold for 1σ shift, got {psi}"


def test_psi_handles_nans():
    rng = np.random.default_rng(2)
    ref = rng.normal(0, 1, 1000)
    cur = rng.normal(0, 1, 1000)
    # Inject NaNs
    ref[::10] = np.nan
    cur[::7] = np.nan
    psi = compute_psi(ref, cur, bins=10)
    assert psi < 0.05  # still close to zero — same dist, just with NaNs dropped


def test_psi_raises_on_empty_inputs():
    with pytest.raises(ValueError, match="reference is empty"):
        compute_psi(np.array([np.nan, np.nan]), np.array([1.0, 2.0]))
    with pytest.raises(ValueError, match="current is empty"):
        compute_psi(np.array([1.0, 2.0]), np.array([np.nan, np.nan]))


def test_psi_clamps_zero_current_bins():
    """An empty current bin should not blow up to infinity."""
    ref = np.linspace(-3, 3, 1000)
    # current heavily concentrated — most bins will be empty
    cur = np.full(1000, 0.0)
    psi = compute_psi(ref, cur, bins=10)
    assert np.isfinite(psi)
    assert psi > 0.5  # drift is dramatic but finite


def test_reference_snapshot_roundtrip(tmp_path: Path):
    rng = np.random.default_rng(3)
    df = pd.DataFrame({
        "f1": rng.normal(0, 1, 1000),
        "f2": rng.uniform(0, 10, 1000),
        "f3": rng.exponential(1, 1000),
    })
    snap_path = tmp_path / "ref.json"
    snap = reference_snapshot(df, ["f1", "f2", "f3"], snap_path, bins=10,
                              model_version_id="test_v0.1")

    assert snap_path.exists()
    saved = json.loads(snap_path.read_text())
    assert saved["n_features"] == 3
    assert saved["model_version_id"] == "test_v0.1"
    for name in ("f1", "f2", "f3"):
        assert name in saved["features"]
        feat = saved["features"][name]
        assert feat["status"] == "ok"
        assert len(feat["bin_edges"]) >= 2
        assert sum(feat["ref_counts"]) == 1000  # all rows binned
        # First edge should be -inf, last +inf for open-ended tails.
        assert feat["bin_edges"][0] == float("-inf")
        assert feat["bin_edges"][-1] == float("inf")


def test_reference_snapshot_handles_missing_column(tmp_path: Path):
    df = pd.DataFrame({"f1": np.arange(100).astype(float)})
    snap = reference_snapshot(df, ["f1", "missing_col"], tmp_path / "ref.json")
    assert "missing_col" in snap["skipped_features"]
    assert "f1" in snap["features"]


def test_reference_snapshot_flags_insufficient_data(tmp_path: Path):
    # 5 rows vs bins=10 — can't build stable baseline.
    df = pd.DataFrame({"f1": [1.0, 2.0, 3.0, 4.0, 5.0]})
    snap = reference_snapshot(df, ["f1"], tmp_path / "ref.json", bins=10)
    assert snap["features"]["f1"]["status"] == "insufficient_data"


def test_quarterly_drift_report_identifies_drifted_feature(tmp_path: Path):
    rng = np.random.default_rng(4)
    train_df = pd.DataFrame({
        "stable": rng.normal(0, 1, 5000),
        "drifting": rng.normal(0, 1, 5000),
    })
    snap_path = tmp_path / "ref.json"
    reference_snapshot(train_df, ["stable", "drifting"], snap_path, bins=10,
                       model_version_id="test_v1")

    # Current: stable feature unchanged, drifting feature shifted by 2σ
    current_df = pd.DataFrame({
        "stable": rng.normal(0, 1, 2000),
        "drifting": rng.normal(2.0, 1, 2000),
    })

    report = quarterly_drift_report(
        reference_snapshot_path=snap_path,
        current_view="<not used>",
        db_path=Path("<not used>"),
        quarter="2026Q1",
        current_df=current_df,
    )

    assert report["quarter"] == "2026Q1"
    assert report["n_features_checked"] == 2
    assert "drifting" in report["drifted_features"]
    assert "stable" not in report["drifted_features"]
    assert report["per_feature"]["stable"]["status"] == "ok"
    assert report["per_feature"]["drifting"]["status"] == "drifted"

    # Gate should be 'fail' since at least one feature drifted.
    gate = report["gates"][0]
    assert gate["name"] == "psi_drift"
    assert gate["status"] == "fail"
    assert gate["value"] == 1.0


def test_quarterly_drift_report_passes_when_no_drift(tmp_path: Path):
    rng = np.random.default_rng(5)
    train_df = pd.DataFrame({"f": rng.normal(0, 1, 5000)})
    snap_path = tmp_path / "ref.json"
    reference_snapshot(train_df, ["f"], snap_path, bins=10)

    current_df = pd.DataFrame({"f": rng.normal(0, 1, 2000)})
    report = quarterly_drift_report(
        reference_snapshot_path=snap_path,
        current_view="<not used>",
        db_path=Path("<not used>"),
        quarter="2026Q1",
        current_df=current_df,
    )
    assert report["n_features_drifted"] == 0
    assert report["gates"][0]["status"] == "pass"


def test_quarterly_drift_report_missing_current_column(tmp_path: Path):
    train_df = pd.DataFrame({"f1": np.arange(1000).astype(float),
                              "f2": np.arange(1000).astype(float) * 2})
    snap_path = tmp_path / "ref.json"
    reference_snapshot(train_df, ["f1", "f2"], snap_path, bins=10)

    current_df = pd.DataFrame({"f1": np.arange(500).astype(float)})  # f2 missing
    report = quarterly_drift_report(
        reference_snapshot_path=snap_path,
        current_view="<not used>",
        db_path=Path("<not used>"),
        quarter="2026Q1",
        current_df=current_df,
    )
    assert "f2" in report["skipped_features"]
    assert report["per_feature"]["f2"]["reason"] == "missing_in_current"


def test_quarterly_drift_raises_on_missing_snapshot(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        quarterly_drift_report(
            reference_snapshot_path=tmp_path / "does-not-exist.json",
            current_view="x",
            db_path=tmp_path / "x.duckdb",
            quarter="2026Q1",
            current_df=pd.DataFrame({"a": [1.0]}),
        )
