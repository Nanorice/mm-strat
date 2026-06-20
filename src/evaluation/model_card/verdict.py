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
        return "LIMITATION"
    if section.scored and section.aggregate_score is not None and section.aggregate_score == 0:
        return "LIMITATION"
    if section.scored and section.aggregate_score is not None and section.aggregate_score == 1:
        return "WARNING"
    return "OK"


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
        return "LIMITATION"
    score = d_section.rubric_scores.get(sub_key)
    if score is None:
        return "PENDING"
    if score == 0:
        return "LIMITATION"
    if score == 1:
        return "WARNING"
    return "OK"


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
        if "LIMITATION" in verdicts:
            agg = "LIMITATION"
        elif "PENDING" in verdicts:
            agg = "PENDING"
        elif "WARNING" in verdicts:
            agg = "WARNING"
        else:
            agg = "OK"
        out[use_case] = {"verdict": agg, "reasons": per_section}
    return out


def aggregate_score(sections: dict[str, SectionResult]) -> dict[str, Any]:
    """Calculate a 100-point continuous score using specific weights.
    
    Weights (max 100):
    - D_binary: 12.5 (Ranker)
    - D_magnitude: 12.5 (Ranker)
    - B: 20 (Discrimination)
    - E: 20 (Threshold)
    - C: 15 (Calibration)
    - F: 10 (Robustness)
    - G: 10 (Stats Edge)
    """
    weights = {
        "D_binary": 12.5, "D_magnitude": 12.5,
        "B": 20.0, "C": 15.0, "E": 20.0, "F": 10.0, "G": 10.0
    }
    
    per_section: dict[str, int | None] = {}
    total_score = 0.0
    max_score = 0.0

    d_section = sections.get("D")
    if d_section is not None and not d_section.not_implemented:
        for sub_key in ("D_binary", "D_magnitude"):
            score = d_section.rubric_scores.get(sub_key)
            per_section[sub_key] = int(score) if score is not None else None
            if score is not None:
                # rubric score is out of 3
                total_score += (int(score) / 3.0) * weights[sub_key]
                max_score += weights[sub_key]
    else:
        per_section["D_binary"] = None
        per_section["D_magnitude"] = None

    for key in ("B", "C", "E", "F", "G"):
        sec = sections.get(key)
        if sec is None or sec.not_implemented or sec.aggregate_score is None:
            per_section[key] = None
            continue
        per_section[key] = sec.aggregate_score
        total_score += (sec.aggregate_score / 3.0) * weights[key]
        max_score += weights[key]

    if max_score == 0:
        return {"total": 0, "max": 100, "band": "N/A", "per_section": per_section}

    # Project the achieved score to a 100-point scale based on what was actually evaluated
    projected_total = (total_score / max_score) * 100.0
    
    return {
        "total": round(projected_total, 1),
        "max": 100,
        "per_section": per_section,
        "band": f"{round(projected_total, 1)} / 100",
    }


def card_void(sections: dict[str, SectionResult]) -> bool:
    """Section A blocking failures void the entire card."""
    a = sections.get("A")
    return bool(a and a.has_blocking_failure)
