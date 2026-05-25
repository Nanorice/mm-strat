"""Model-card sections (A, B, C, D, E, F implemented; G in Phase 3)."""

from .section_a_integrity import run_section_a
from .section_b_discrimination import run_section_b
from .section_c_calibration import run_section_c
from .section_d_ranker import run_section_d
from .section_e_gates import run_section_e
from .section_f_robustness import run_section_f

__all__ = [
    "run_section_a",
    "run_section_b",
    "run_section_c",
    "run_section_d",
    "run_section_e",
    "run_section_f",
]
