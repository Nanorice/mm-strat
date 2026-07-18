"""Label-cone builder: fingerprint identity + the NULL-metric (C1) contract.

The label cone shares cone_cells with the strategy cone but is a DIFFERENT object
(glossary: label_cone vs strategy_cone). These tests pin the contract that keeps
them from being confused: engine tag, calibrated scale, and — load-bearing — that
a buy-and-hold basket carries NO Sharpe (metric is total_return only)."""
import pandas as pd

from scripts.build_label_cone_cache import _cell_id, collect_cells, VARIANTS
from start_day_basket_paths import SCORE_CACHE  # sys.path set by the build import above


def test_cell_id_is_content_not_path():
    kw = VARIANTS["label_both_gated"]
    start = pd.Timestamp("2021-01-01")
    a = _cell_id("label_both_gated", start, kw)
    assert a == _cell_id("label_both_gated", start, kw)              # reproducible
    assert _cell_id("label_baseline", start, kw) != a               # arm is identity
    assert _cell_id("label_both_gated", pd.Timestamp("2005-01-01"), kw) != a  # start is identity


def test_variants_cover_the_gate_cross():
    # The 4-variant fan = regime-gate on/off × score-gate on/off. Any collapse of
    # this cross would silently drop a comparison the design requires.
    gov = {v["use_governor"] for v in VARIANTS.values()}
    scr = {v["min_score"] is not None for v in VARIANTS.values()}
    assert gov == {True, False} and scr == {True, False}
    assert len(VARIANTS) == 4


def test_collect_cells_null_metric_contract():
    # Integration: runs basket_paths at coarse density. The C1 contract — a
    # buy-and-hold basket has total_return (fwd_return) but NO sharpe/ann_*/max_dd;
    # inventing one would be the category error the two-cone split prevents.
    if not SCORE_CACHE.exists():
        return  # dev-box-only score cache
    df = collect_cells(sample_every=60)   # ~quarterly start-days, fast
    assert not df.empty
    assert (df["engine"] == "basket_paths").all()
    assert (df["score_scale"] == "calibrated").all()
    assert df["total_return"].notna().all()          # the label-cone metric
    assert df["sharpe"].isna().all()                 # NO Sharpe for buy-and-hold
    assert df["max_drawdown"].isna().all()
    assert (df["grid"] == "basket").all()
