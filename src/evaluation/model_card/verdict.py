"""Use-case verdict matrix + aggregate band.

Phase 3: all seven sections (A-G) are implemented, so any PENDING verdict
now reflects an actually-skipped section (e.g., Mode B not built) rather
than unfinished code.
"""

from __future__ import annotations

from typing import Any

from .rubric import SectionResult

USE_CASE_REQUIREMENTS: dict[str, list[str]] = {
    "selection_ranker_size_by_p": ["A", "D_binary", "D_magnitude", "G"],
    "hit_rate_ranker_equal_size": ["A", "D_binary", "G"],
    "threshold_gate": ["A", "E", "G"],
    "probability_sizing": ["A", "B", "C", "G"],
    "composite_gate_plus_rank": ["A", "C", "D_binary", "D_magnitude", "E", "G"],
}


def _section_verdict(section: SectionResult | None) -> str:
    if section is None or section.not_implemented:
        return "PENDING"
    if section.has_blocking_failure:
        return "REJECT"
    if section.scored and section.aggregate_score is not None and section.aggregate_score == 0:
        return "REJECT"
    if section.scored and section.aggregate_score is not None and section.aggregate_score == 1:
        return "MARGINAL"
    return "PASS"


def _d_subscore_verdict(d_section: SectionResult | None, sub_key: str) -> str:
    """Verdict for D_binary or D_magnitude, using the specific rubric subscore
    in section D rather than the section's min-aggregate.

    Blocking gate failures on D propagate to BOTH subscores (a failing
    blocking gate voids any use of section D regardless of which half it sits
    in — we don't try to map individual gates to halves).
    """
    if d_section is None or d_section.not_implemented:
        return "PENDING"
    if d_section.has_blocking_failure:
        return "REJECT"
    score = d_section.rubric_scores.get(sub_key)
    if score is None:
        return "PENDING"
    if score == 0:
        return "REJECT"
    if score == 1:
        return "MARGINAL"
    return "PASS"


def use_case_verdicts(sections: dict[str, SectionResult]) -> dict[str, str]:
    """Walk USE_CASE_REQUIREMENTS. D_binary / D_magnitude resolve to their
    specific rubric subscores within section D (set by run_section_d)."""
    detailed = use_case_verdicts_with_reasons(sections)
    return {use_case: v["verdict"] for use_case, v in detailed.items()}


def use_case_verdicts_with_reasons(
    sections: dict[str, SectionResult],
) -> dict[str, dict[str, Any]]:
    """Same as `use_case_verdicts` but each entry also carries the list of
    per-section sub-verdicts that drove the aggregate, so the report can
    explain *why* a use case rejects.

    Returns:
        {use_case: {
            'verdict': 'PASS' | 'MARGINAL' | 'REJECT' | 'PENDING',
            'reasons': [{'section': 'A', 'verdict': 'PASS'}, ...],
        }}
    """
    out: dict[str, dict[str, Any]] = {}
    d_section = sections.get("D")
    for use_case, required in USE_CASE_REQUIREMENTS.items():
        per_section: list[dict[str, str]] = []
        for key in required:
            if key in ("D_binary", "D_magnitude"):
                v = _d_subscore_verdict(d_section, key)
            else:
                v = _section_verdict(sections.get(key))
            per_section.append({"section": key, "verdict": v})
        verdicts = [r["verdict"] for r in per_section]
        if "REJECT" in verdicts:
            agg = "REJECT"
        elif "PENDING" in verdicts:
            agg = "PENDING"
        elif "MARGINAL" in verdicts:
            agg = "MARGINAL"
        else:
            agg = "PASS"
        out[use_case] = {"verdict": agg, "reasons": per_section}
    return out


def aggregate_score(sections: dict[str, SectionResult]) -> dict[str, Any]:
    """Sum scored sections' aggregate_score, project to band.

    Section D is split into D_binary and D_magnitude — each contributes 3 to
    the max, since the framework rubric (§3.D) lists independent bands for
    both halves. Other sections contribute their single section-level min
    rubric score out of 3.
    """
    per_section: dict[str, int | None] = {}
    total = 0
    max_total = 0

    # Special-case section D: pull D_binary + D_magnitude individually.
    d_section = sections.get("D")
    if d_section is not None and not d_section.not_implemented:
        for sub_key in ("D_binary", "D_magnitude"):
            score = d_section.rubric_scores.get(sub_key)
            per_section[sub_key] = int(score) if score is not None else None
            if score is not None:
                total += int(score)
                max_total += 3
    else:
        per_section["D_binary"] = None
        per_section["D_magnitude"] = None

    for key in ("B", "C", "E", "F", "G"):
        sec = sections.get(key)
        if sec is None or sec.not_implemented or sec.aggregate_score is None:
            per_section[key] = None
            continue
        per_section[key] = sec.aggregate_score
        total += sec.aggregate_score
        max_total += 3

    if max_total == 0:
        return {"total": 0, "max": 0, "band": "INSUFFICIENT",
                "per_section": per_section}

    # Bands per framework §4 (max=21 when full).
    ratio = total / max_total
    if ratio <= 6 / 21:
        band = "BROKEN"
    elif ratio <= 12 / 21:
        band = "WEAK"
    elif ratio <= 17 / 21:
        band = "ACCEPTABLE"
    else:
        band = "STRONG"
    return {
        "total": int(total),
        "max": int(max_total),
        "per_section": per_section,
        "band": band,
    }


def card_void(sections: dict[str, SectionResult]) -> bool:
    """Section A blocking failures void the entire card."""
    a = sections.get("A")
    return bool(a and a.has_blocking_failure)
