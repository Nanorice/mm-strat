"""Both cones must have plottable rows in `cone_cells`.

The Model Lab label-cone tab and the Studio strategy cone both degrade to a quiet
"no rows — run the builder" info box when their engine is missing. That is how the
label cone went unnoticed until 2026-07-19: the page was correct, the cache was
empty. These tests fail loudly instead.

Rebuild with:
    python scripts/build_cone_cache.py         # strategy (engine=BackTrader)
    python scripts/build_label_cone_cache.py   # label    (engine=basket_paths)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("streamlit")
from dashboard_utils import load_cone_cells  # noqa: E402


def test_strategy_cone_has_plottable_sharpe() -> None:
    """Studio render_cone() charts `sharpe` for engine='BackTrader'."""
    cells = load_cone_cells()
    assert not cells.empty, "strategy cone empty — run scripts/build_cone_cache.py"
    champion = cells[cells["arm"] == "champion"]
    assert not champion.empty, "no 'champion' arm — the Studio's default selection"
    assert champion["sharpe"].notna().any(), "champion has no plottable Sharpe points"


def test_label_cone_has_plottable_returns() -> None:
    """Model Lab render_label_cone() charts `total_return` for engine='basket_paths'."""
    cells = load_cone_cells(engine="basket_paths")
    assert not cells.empty, \
        "label cone empty — run scripts/build_label_cone_cache.py"
    baseline = cells[cells["arm"] == "label_baseline"]
    assert not baseline.empty, "no 'label_baseline' arm — the tab's default selection"
    assert baseline["total_return"].notna().any(), "no plottable forward returns"


def test_label_cone_carries_no_sharpe() -> None:
    """A buy-and-hold basket has no Sharpe; inventing one is the C1/C3 category
    error the two-cone split exists to prevent."""
    cells = load_cone_cells(engine="basket_paths")
    assert cells["sharpe"].isna().all(), "basket_paths must not carry a Sharpe"


def test_cones_are_disjoint() -> None:
    """Strategy and label arms must never collide — they are different objects
    (glossary: strategy_cone vs label_cone) sharing one table."""
    strategy = set(load_cone_cells()["arm"])
    label = set(load_cone_cells(engine="basket_paths")["arm"])
    assert strategy.isdisjoint(label), f"cone arms overlap: {strategy & label}"


def test_cell_names_are_reused_across_arms() -> None:
    """Cell names are NOT globally unique — which is why the zoom must pair a cell
    with its own arm.

    A sweep re-runs the same start-date grid per arm, so `r_200301_h12` exists
    under many arms and `h_start_h3` exists only under `champion`. That makes a
    stale cell selection silently resolvable against the WRONG arm — the
    2026-07-19 bug, where `champion_gated` (no `horizon` grid at all) rendered
    `champion`'s `h_start_h3`. This test pins the precondition so the reason the
    picker is keyed per-arm stays visible.
    """
    cells = load_cone_cells()
    reused = cells.groupby("cell")["arm"].nunique()
    assert (reused > 1).any(), \
        "cell names no longer collide across arms — the per-arm widget key in " \
        "4_Backtest_Studio.render_cell_zoom may no longer be needed"


def test_zoom_path_exists_for_every_cell() -> None:
    """Every cone cell must resolve to a real sweep directory under ITS arm.

    This is what the zoom does. A missing path means the picker can offer a cell
    whose artifacts don't exist, which renders as a confusing empty panel rather
    than an error.
    """
    sweep_root = ROOT / "data" / "selection_sweep" / "starttime"
    if not sweep_root.exists():
        pytest.skip("sweep tree is dev-box-local")
    cells = load_cone_cells()
    missing = [
        f"{r.arm}/{r.grid}/{r.cell}"
        for r in cells.itertuples()
        if not (sweep_root / r.arm / r.grid / r.cell / "equity.parquet").exists()
    ]
    assert not missing, f"{len(missing)} cone cells have no equity.parquet: {missing[:5]}"
