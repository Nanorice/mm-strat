"""Tests for src.evaluation.label_registry."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.evaluation.label_registry import LabelDefinition


def _make(**overrides) -> LabelDefinition:
    base = dict(
        label_id="mfe_4class_v1",
        description="4-class MFE within 30 trading days post-breakout",
        target_col="mfe_class",
        horizon_days=30,
        exit_rule="C1 AND C2 AND C6 lost",
        source_query="SELECT ticker, date, mfe_class FROM v_d2_training",
        git_sha="abc123",
        generated_at="2026-05-23T12:00:00",
        bins=[0.02, 0.10, 0.30],
    )
    base.update(overrides)
    return LabelDefinition(**base)


def test_round_trip_json(tmp_path: Path):
    src = _make()
    path = tmp_path / "label.json"
    src.to_json(path)

    restored = LabelDefinition.from_json(path)
    assert restored == src


def test_to_json_creates_parent_dirs(tmp_path: Path):
    src = _make()
    target = tmp_path / "nested" / "dirs" / "label.json"
    src.to_json(target)
    assert target.exists()
    loaded = json.loads(target.read_text())
    assert loaded["label_id"] == src.label_id


def test_fingerprint_stable_across_reserialization(tmp_path: Path):
    src = _make()
    fp1 = src.fingerprint()

    path = tmp_path / "label.json"
    src.to_json(path)
    restored = LabelDefinition.from_json(path)
    fp2 = restored.fingerprint()
    assert fp1 == fp2


def test_fingerprint_ignores_generated_at():
    a = _make(generated_at="2026-05-23T12:00:00")
    b = _make(generated_at="2027-01-01T00:00:00")
    assert a.fingerprint() == b.fingerprint()


def test_fingerprint_changes_with_horizon():
    a = _make(horizon_days=30)
    b = _make(horizon_days=45)
    assert a.fingerprint() != b.fingerprint()


def test_fingerprint_changes_with_bins():
    a = _make(bins=[0.02, 0.10, 0.30])
    b = _make(bins=[0.02, 0.10, 0.40])
    assert a.fingerprint() != b.fingerprint()


def test_bins_optional():
    binary = _make(bins=None, label_id="binary_v1")
    fp = binary.fingerprint()
    assert isinstance(fp, str) and len(fp) == 64
