"""Cone-cache builder: fingerprint identity + score_scale branch."""
import json

from scripts.build_cone_cache import _cell_id, _score_scale, collect_cells, SWEEP_ROOT


def test_cell_id_is_config_content_not_path():
    # Identical config+window → identical id (a re-run is a provable reproduction);
    # a different param → different id. This is the glossary's cell_id contract.
    cfg = {"strategy_kwargs": {"entry_top_n": 5}, "signal": "binary", "model": "m01_binary/v1"}
    a = _cell_id(cfg, "2021-01-01", "2022-01-01")
    b = _cell_id(cfg, "2021-01-01", "2022-01-01")
    assert a == b
    cfg2 = json.loads(json.dumps(cfg)); cfg2["strategy_kwargs"]["entry_top_n"] = 10
    assert _cell_id(cfg2, "2021-01-01", "2022-01-01") != a
    # window is part of identity — same params, different start = different cell
    assert _cell_id(cfg, "2005-01-01", "2006-01-01") != a


def test_score_scale_branch():
    # The §2 two-scale trap: a prob_elite-ranked cell is calibrated in backtest;
    # an RS-ranked cell has no prob_elite gate; empty config never guesses.
    assert _score_scale({"strategy_kwargs": {"rank_by": "prob_elite"}, "signal": "binary_gated"}) == "calibrated"
    assert _score_scale({"strategy_kwargs": {"rank_by": "rs"}, "signal": "rs"}) == "n/a"
    assert _score_scale({}) == "unknown"


def test_collect_cells_from_summaries():
    # Integration: walks the real sweep summaries. Every cell scores off the
    # calibrated cache → no 'unknown' scales; ann_return is the window-fair value
    # from summary.json (never the metrics.json 0.0 gap).
    if not SWEEP_ROOT.exists():
        return  # dev-box-only artifacts
    df = collect_cells(SWEEP_ROOT)
    assert not df.empty
    assert (df["score_scale"] != "unknown").all()
    assert df["ann_return"].notna().any()
    assert (df["engine"] == "BackTrader").all()
