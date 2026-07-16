"""Macro S3 indicator board — the bits with real edge cases: _sparkline's
degenerate inputs, and the config metadata the board is driven by.

The page module (`scripts/pages/2_Macro.py`) imports streamlit at module scope and
its name isn't a valid identifier, so the pure helpers are exec'd out of source.
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config

PAGE_SRC = (ROOT / "scripts" / "pages" / "2_Macro.py").read_text(encoding="utf-8")


def _extract(start_marker: str, end_marker: str) -> dict:
    # pandas is a module-scope import in the page; the extracted fragment needs it.
    ns: dict = {"pd": pd}
    src = PAGE_SRC[PAGE_SRC.index(start_marker):PAGE_SRC.index(end_marker)]
    exec(src, ns)
    return ns


def _helpers():
    ns = _extract("def _fmt(", "def _render_s3(")
    return ns["_sparkline"], ns["_fmt"]


def test_sparkline_degenerate_inputs():
    spark, _ = _helpers()

    # empty -> no line, no crash
    assert "polyline" not in spark([])

    # single point -> a dot, not a line (can't draw a path through one point)
    assert "circle" in spark([4.2]) and "polyline" not in spark([4.2])

    # flat series would div-by-zero on (v-lo)/rng -> must degrade, not raise
    flat = spark([2.5, 2.5, 2.5])
    assert "polyline" in flat and "nan" not in flat.lower()

    # direction colour: up=green / down=red
    assert "#2f6b3d" in spark([1.0, 2.0, 3.0])
    assert "#a32f2f" in spark([3.0, 2.0, 1.0])


def test_sparkline_caps_resolution():
    """180 points in a 90px cell is ~0.5px/point — sub-pixel noise, the exact reason
    the first version read as uninformative. Must downsample to ~1pt/1.5px."""
    spark, _ = _helpers()
    svg = spark(list(range(180)))
    n_pts = svg.split('points="')[2].split('"')[0].count(",")  # the polyline, not the area
    assert n_pts <= 60, f"line kept {n_pts} points — too dense to resolve"
    # short series are NOT upsampled
    assert spark([1.0, 2.0, 3.0]).split('points="')[2].split('"')[0].count(",") == 3


def test_fmt_scales_precision_to_magnitude():
    _, fmt = _helpers()
    assert fmt(66930.7) == "66,931"   # big: no cents (avoid a .5 tie — banker's rounding)
    assert fmt(143.24) == "143.2"     # mid: one dp
    assert fmt(4.28) == "4.28"        # small: two dp
    assert fmt(float("nan")) == "—"


def test_sigma_thresholds_are_not_permanently_lit():
    """0.5/1.0 fires on a median 14 of 56 rows EVERY day (measured) — a banner lit
    daily is wallpaper. Guard the calibration so it can't be quietly lowered."""
    assert config.S3_SIGMA_WARN >= 1.5, "amber below 1.5σ fires on an ordinary day"
    assert config.S3_SIGMA_ALERT > config.S3_SIGMA_WARN


def test_spreads_excluded_from_pct_z():
    """A spread crossing zero makes pct-change explode (T10Y2Y scored a 22.6% sigma).
    Percent-unit series MUST use absolute change."""
    assert "percent" not in config.S3_PCT_UNITS
    for sid in ("T10Y2Y", "T10Y3M", "DGS10", "BAMLH0A0HYM2"):
        assert config.FRED_SERIES[sid]["unit"] == "percent"


def test_commodities_are_grouped_and_dispatched():
    """A YAHOO_SERIES entry that isn't group-tagged ingests nightly but never shows."""
    assert config.YAHOO_SERIES, "commodity block missing"
    for sid, m in config.YAHOO_SERIES.items():
        assert m.get("group"), f"{sid} has no group -> would never render"
        assert m.get("unit") in config.S3_PCT_UNITS, f"{sid}: prices need pct-change z"


def test_s3_groups_match_config():
    """Every grouped series must sit in a rendered group — else it ingests nightly
    but silently never displays."""
    ns = _extract("S3_GROUPS = [", "\ndef _fg_gauge(")
    rendered = {g for g, _ in ns["S3_GROUPS"]}
    configured = {m["group"]
                  for m in {**config.FRED_SERIES, **config.YAHOO_SERIES}.values()
                  if m.get("group")}
    assert configured - rendered == set(), f"ingested but never rendered: {configured - rendered}"


def test_revised_series_are_flagged():
    """The INSERT-OR-IGNORE first-print-wins caveat only holds if the revised
    series actually carry the flag the board renders."""
    must_be_revised = {"PAYEMS", "CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE", "GDPNOW", "INDPRO"}
    for sid in must_be_revised:
        assert config.FRED_SERIES[sid].get("revised") is True, f"{sid} missing revised=True"
