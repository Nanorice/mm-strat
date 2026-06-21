"""Tests for data_loader: outcome-column separation, label derivation, frozen split."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.evaluation.model_card.data_loader import (
    BINARY_HOME_RUN_THRESHOLD,
    HOME_RUN_CLASS_IDX,
    OUTCOME_COLUMNS,
    _binarise_mfe,
    _bucket_4class,
)


def test_binary_label_threshold():
    s = pd.Series([0.0, 30.0, 30.01, 100.0, -5.0])
    out = _binarise_mfe(s)
    # 30.0 is NOT > 30 ⇒ should be 0
    assert out.tolist() == [0, 0, 1, 1, 0]


def test_4class_bucketing_matches_registry_bins():
    """bins=[2,10,30] => 4 classes:
    (-inf, 2] -> 0, (2, 10] -> 1, (10, 30] -> 2, (30, inf) -> 3
    Home-run class index is 3."""
    s = pd.Series([-5.0, 0.0, 2.0, 5.0, 10.0, 20.0, 30.0, 50.0])
    out = _bucket_4class(s)
    assert out.tolist() == [0, 0, 0, 1, 1, 2, 2, 3]
    assert HOME_RUN_CLASS_IDX == 3


def test_outcome_columns_block_known_leakers():
    """Spot-check the forbidden set covers the v_d2_training outcome columns
    that sit on the same row as features."""
    for col in (
        "mfe_pct", "mae_pct", "return_pct", "return_at_exit",
        "exit_date", "entry_date", "holding_days",
        "sl_triggered", "sl_pct", "sl_date",
    ):
        assert col in OUTCOME_COLUMNS, f"{col} should be in OUTCOME_COLUMNS"


def test_binary_label_threshold_matches_constant():
    assert BINARY_HOME_RUN_THRESHOLD == 30.0
