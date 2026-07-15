"""Unit tests for rubric_score banding + verdict aggregation."""

from __future__ import annotations

import math

import pytest

from src.evaluation.model_card.rubric import (
    GateEntry,
    SectionResult,
    placeholder_section,
    rubric_score,
)
from src.evaluation.model_card.verdict import (
    USE_CASE_REQUIREMENTS,
    aggregate_score,
    use_case_verdicts,
    use_case_verdicts_with_reasons,
)


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


def _make_section(name: str, *, scored: bool, min_score: int = 3,
                  has_blocking_fail: bool = False, sub_scores: dict | None = None) -> SectionResult:
    section = SectionResult(name=name, title=f"Section {name}", scored=scored)
    if sub_scores is not None:
        section.rubric_scores.update(sub_scores)
    elif scored:
        section.rubric_scores["primary"] = min_score
    if has_blocking_fail:
        section.gates.append(GateEntry(
            name=f"{name}_fail", status="fail", value=None, threshold=None,
            detail="forced", blocking=True,
        ))
    return section


def test_use_case_verdict_reject_when_required_section_fails():
    sections = {
        "A": _make_section("A", scored=False),
        "B": _make_section("B", scored=True, min_score=3),
        "C": _make_section("C", scored=True, min_score=3),
        "D": _make_section("D", scored=True, sub_scores={"D_binary": 0, "D_magnitude": 3}),
        "E": _make_section("E", scored=True, min_score=3),
        "F": _make_section("F", scored=True, min_score=3),
        "G": _make_section("G", scored=True, min_score=3),
    }
    detail = use_case_verdicts_with_reasons(sections)
    # hit_rate_ranker requires D_binary; D_binary=0 ⇒ LIMITATION
    assert detail["hit_rate_ranker_equal_size"]["verdict"] == "LIMITATION"
    # selection_ranker requires both halves; one is 0 ⇒ LIMITATION
    assert detail["selection_ranker_size_by_p"]["verdict"] == "LIMITATION"
    # threshold_gate only needs A/E/G — all pass ⇒ OK
    assert detail["threshold_gate"]["verdict"] == "OK"


def test_use_case_verdict_pending_when_section_not_implemented():
    sections = {
        "A": _make_section("A", scored=False),
        "B": _make_section("B", scored=True, min_score=3),
        "C": _make_section("C", scored=True, min_score=3),
        "D": _make_section("D", scored=True, sub_scores={"D_binary": 3, "D_magnitude": 3}),
        "E": _make_section("E", scored=True, min_score=3),
        "F": _make_section("F", scored=True, min_score=3),
        "G": placeholder_section("G", "Edge existence (not implemented)"),
    }
    detail = use_case_verdicts_with_reasons(sections)
    # Any use case that requires G must now be PENDING
    assert detail["threshold_gate"]["verdict"] == "PENDING"
    assert detail["probability_sizing"]["verdict"] == "PENDING"


def test_use_case_verdicts_consistent_with_reasons():
    """`use_case_verdicts` should always equal the aggregated 'verdict' field
    in `use_case_verdicts_with_reasons` — they share the implementation."""
    sections = {
        "A": _make_section("A", scored=False),
        "B": _make_section("B", scored=True, min_score=2),
        "C": _make_section("C", scored=True, min_score=2),
        "D": _make_section("D", scored=True, sub_scores={"D_binary": 1, "D_magnitude": 2}),
        "E": _make_section("E", scored=True, min_score=2),
        "F": _make_section("F", scored=True, min_score=2),
        "G": _make_section("G", scored=True, min_score=2),
    }
    short = use_case_verdicts(sections)
    long = use_case_verdicts_with_reasons(sections)
    for key in USE_CASE_REQUIREMENTS:
        assert short[key] == long[key]["verdict"]
        # reasons covers every required section for that use case
        assert [r["section"] for r in long[key]["reasons"]] == USE_CASE_REQUIREMENTS[key]


def test_aggregate_band_with_full_strong_card():
    sections = {
        "A": _make_section("A", scored=False),
        "B": _make_section("B", scored=True, min_score=3),
        "C": _make_section("C", scored=True, min_score=3),
        "D": _make_section("D", scored=True, sub_scores={"D_binary": 3, "D_magnitude": 3}),
        "E": _make_section("E", scored=True, min_score=3),
        "F": _make_section("F", scored=True, min_score=3),
        "G": _make_section("G", scored=True, min_score=3),
    }
    agg = aggregate_score(sections)
    # 100-point weighted projection; every subscore = 3/3 ⇒ full 100.
    assert agg["max"] == 100
    assert agg["total"] == 100.0
    assert agg["band"] == "100.0 / 100"
