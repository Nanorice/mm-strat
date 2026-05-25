"""Unit tests for rubric_score banding."""

from __future__ import annotations

import math

import pytest

from src.evaluation.model_card.rubric import rubric_score


def test_higher_is_better_bands():
    th = [0.55, 0.60, 0.68]
    assert rubric_score(0.40, th) == 0
    assert rubric_score(0.56, th) == 1
    assert rubric_score(0.63, th) == 2
    assert rubric_score(0.80, th) == 3
    # boundary: value equal to threshold goes to higher band
    assert rubric_score(0.55, th) == 1
    assert rubric_score(0.60, th) == 2
    assert rubric_score(0.68, th) == 3


def test_lower_is_better_bands():
    th = [0.02, 0.05, 0.10]
    assert rubric_score(0.01, th, higher_is_better=False) == 3
    assert rubric_score(0.04, th, higher_is_better=False) == 2
    assert rubric_score(0.07, th, higher_is_better=False) == 1
    assert rubric_score(0.15, th, higher_is_better=False) == 0


def test_nan_returns_zero():
    assert rubric_score(float("nan"), [1, 2, 3]) == 0
    assert rubric_score(None, [1, 2, 3]) == 0


def test_invalid_thresholds_raise():
    with pytest.raises(ValueError):
        rubric_score(0.5, [1.0, 2.0])
