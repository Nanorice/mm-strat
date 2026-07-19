"""Model-card charts must be static, self-contained SVG.

The card is embedded in a Streamlit iframe (Model Lab → Model Card). The previous
interactive Plotly build had two standing failure modes: it fetched plotly.js from
a CDN (blank offline / on a locked-down remote) and sized itself in JS, which
clipped inside the iframe. Static inline SVG has no CDN, no script, and no
measurement step. These tests keep it that way.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.evaluation.model_card.report import STYLE, _chart_html  # noqa: E402

RELIABILITY = [
    {"bin_lo": i / 10, "bin_hi": (i + 1) / 10,
     "mean_pred": i / 10 + 0.05, "mean_obs": (i / 10) ** 2}
    for i in range(10)
]
DECILES = [
    {"decile": i, "mean": i * 0.1, "median": i * 0.08,
     "p_min": i * 0.05, "p_max": i * 0.09}
    for i in range(1, 11)
]
THRESHOLD = [{"bin_lo": 0.3, "bin_hi": 0.4,
              "observed_freq": 0.05, "predicted_mean": 0.35}]


def test_charts_are_inline_svg_with_no_external_dependency() -> None:
    for name, rows in [("reliability_curve", RELIABILITY),
                       ("threshold_bin_calibration", THRESHOLD),
                       ("decile_binary_mode_a", DECILES)]:
        out = _chart_html(name, name, rows)
        assert "<svg" in out, f"{name} did not render an SVG"
        assert "<script" not in out, f"{name} emitted a script tag"
        assert "plotly" not in out.lower(), f"{name} still references plotly"
        assert "cdn." not in out, f"{name} references a CDN"


def test_css_scales_svg_to_container() -> None:
    """The viewBox has no intrinsic width — this rule is the clipping fix."""
    assert ".chart svg" in STYLE
    assert "width: 100%" in STYLE


def test_empty_bins_are_skipped_and_reported() -> None:
    """An empty score bin is an all-None row. Plotly dropped these silently; a
    bin with no rows is a calibration fact and must stay visible."""
    rows = RELIABILITY[:6] + [
        {"bin_lo": None, "bin_hi": None, "mean_pred": None, "mean_obs": None}
    ] * 4
    out = _chart_html("reliability_curve", "reliability_curve", rows)
    assert "<svg" in out, "should still plot the 6 usable bins"
    assert "4 of 10 bins were empty" in out, "empty-bin count not reported"


def test_all_empty_degrades_without_crashing() -> None:
    out = _chart_html("reliability_curve", "reliability_curve",
                      [{"mean_pred": None, "mean_obs": None}] * 3)
    assert "nothing to plot" in out
    assert "<svg" not in out


def test_unknown_table_falls_back_to_table() -> None:
    assert "<table" in _chart_html("something_else", "x", [{"a": 1}])


def test_no_rows_renders_nothing() -> None:
    assert _chart_html("reliability_curve", "x", []) == ""
