"""Guards the st.markdown raw-HTML contract + the Screening presets.

The bug this pins: Streamlit markdown-parses the string passed to st.markdown,
and treats any line indented >=4 spaces as a CODE BLOCK. Interpolated f-string
fragments (e.g. Macro S1's deploy card) carry their source indentation, so the
markup rendered as literal text on the page. The `_html` helper strips per-line
leading whitespace; these tests fail if someone reverts to a raw st.markdown or
reintroduces indentation-sensitive emission.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
PAGES = ROOT / "scripts" / "pages"


def _flatten(markup: str) -> str:
    """Mirror of the pages' `_html` transform."""
    return "\n".join(line.lstrip() for line in markup.splitlines())


def test_flatten_kills_code_block_indentation():
    """An indented interpolated fragment must come out flush-left."""
    dep = """
        <div class="card dep">
          <div class="deprow">
            <span class="chip big pos">DEPLOY</span>
          </div>
        </div>"""
    out = _flatten(f"""
    <div class="s1">
      <div class="grid">tiles</div>
      {dep}
    </div>
    """)
    offenders = [l for l in out.splitlines()
                 if l.strip() and len(l) - len(l.lstrip()) >= 4]
    assert not offenders, f"still code-block indented: {offenders}"


@pytest.mark.parametrize("page", ["2_Macro.py", "3_Screening.py"])
def test_pages_route_html_through_helper(page):
    """unsafe_allow_html must appear only inside the _html helper.

    A bare st.markdown(..., unsafe_allow_html=True) in a page body is the
    regression: it skips the dedent and can render markup as literal text.
    """
    src = (PAGES / page).read_text(encoding="utf-8")
    assert src.count("unsafe_allow_html") == 1, (
        f"{page}: unsafe_allow_html should appear once (in _html); "
        "a page-body call bypasses the dedent"
    )
    assert "def _html(" in src, f"{page}: missing the _html helper"


# ── Screening presets ────────────────────────────────────────────────────────
# Presets are plain predicates; the contract is (a) they never grow the
# population, (b) each is reproducible from the filter row (which is WHY the
# old "Aggressive picks" strip was deleted as pure overlap).

def _pop() -> pd.DataFrame:
    return pd.DataFrame({
        "ticker":             ["A", "B", "C", "D"],
        "cap_tier":           ["small", "large", "micro", "mid"],
        "revenue_growth_yoy": [25.0, 30.0, 5.0, None],
        "eps_growth_yoy":     [10.0, -2.0, 1.0, 5.0],
        "pe_ratio":           [15.0, None, 45.0, 12.0],
        "fcf_positive":       [True, True, False, True],
        "net_margin":         [12.0, 20.0, -5.0, 3.0],
        "debt_to_equity":     [0.5, 2.0, 0.1, 0.2],
    })


def _apply(d, preset):
    if preset.startswith("Aggressive"):
        return d[d["cap_tier"].isin(["small", "micro"])]
    if preset.startswith("Growth"):
        return d[(d["revenue_growth_yoy"] >= 20) & (d["eps_growth_yoy"] > 0)]
    if preset.startswith("Value"):
        return d[(d["pe_ratio"] > 0) & (d["pe_ratio"] <= 20) & (d["fcf_positive"] == True)]  # noqa: E712
    if preset.startswith("Conservative"):
        return d[(d["net_margin"] >= 10) & (d["fcf_positive"] == True)  # noqa: E712
                 & (d["debt_to_equity"] <= 1)]
    return d


@pytest.mark.parametrize("preset,expected", [
    ("Aggressive — small-cap tail", ["A", "C"]),
    ("Growth — revenue & EPS compounding", ["A"]),   # B fails EPS, C fails rev, D NULL rev
    ("Value — cheap and profitable", ["A", "D"]),    # B has no P/E -> excluded (not kept)
    ("Conservative — quality balance sheet", ["A"]),  # B d/e=2, C neg margin, D margin 3
])
def test_presets_select_expected(preset, expected):
    assert list(_apply(_pop(), preset)["ticker"]) == expected


def test_value_preset_excludes_null_pe():
    """Value REQUIRES a real P/E — an unprofitable name must not slip through.

    This is the one place NULL != 'unknown, keep': a name with no P/E was never
    tested against the cheapness bar, so it cannot pass a value screen.
    """
    out = _apply(_pop(), "Value — cheap and profitable")
    assert "B" not in list(out["ticker"])  # B.pe_ratio is None


def test_presets_never_grow_population():
    pop = _pop()
    for preset in ["Aggressive x", "Growth x", "Value x", "Conservative x", "None"]:
        assert len(_apply(pop, preset)) <= len(pop)


# ── Manual threshold filters: None = off, 0 = a real bar ─────────────────────
# Regression: the first cut used `if gm_min:` with a 0/-1000 sentinel default, so
# a threshold of literally 0 ("gross margin >= 0") was FALSY and silently skipped
# the filter. Defaults are now None; the guard is `is not None`.

def _thresh(d, gm=None, nm=None, pe=None, rg=None):
    if gm is not None:
        d = d[d["gross_margin"].isna() | (d["gross_margin"] >= gm)]
    if nm is not None:
        d = d[d["net_margin"].isna() | (d["net_margin"] >= nm)]
    if pe is not None:
        d = d[d["pe_ratio"].isna() | (d["pe_ratio"] <= pe)]
    if rg is not None:
        d = d[d["revenue_growth_yoy"].isna() | (d["revenue_growth_yoy"] >= rg)]
    return d


def _fund() -> pd.DataFrame:
    return pd.DataFrame({
        "gross_margin":       [50.0, -10.0, None, 5.0],
        "net_margin":         [20.0, -5.0, None, 1.0],
        "pe_ratio":           [10.0, 60.0, None, 15.0],
        "revenue_growth_yoy": [30.0, -8.0, None, 2.0],
    })


def test_blank_threshold_is_no_filter():
    assert len(_thresh(_fund())) == 4


def test_zero_threshold_actually_filters():
    """0 is a real bar, not 'off' — the sentinel bug."""
    assert len(_thresh(_fund(), gm=0)) == 3   # the -10 row goes
    assert len(_thresh(_fund(), rg=0)) == 3   # the -8 row goes


def test_null_fundamental_is_kept_by_manual_threshold():
    """NULL = 'unknown, keep' for the manual filters (a pre-report name stays)."""
    out = _thresh(_fund(), gm=40, nm=15, pe=12, rg=25)
    assert out["gross_margin"].isna().sum() == 1
