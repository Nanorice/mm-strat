"""Screening's default row order: fresh → triggered → score.

The three keys are ranked, not additive: a name anchored today outranks a
higher-scoring name anchored last month. Getting the key ORDER wrong still
produces a plausibly-sorted table, which is why this is pinned.

`_default_order` is exec'd out of the page source (same trick as
test_chord_matrix) — importing the module would run the page body.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


def _load_default_order():
    src = (ROOT / "scripts" / "pages" / "3_Screening.py").read_text(encoding="utf-8")
    start = src.index("def _default_order")
    end = src.index("def _shape")
    ns: dict = {"pd": pd}
    exec(compile(src[start:end], "_default_order", "exec"), ns)
    return ns["_default_order"]


_default_order = _load_default_order()

AS_OF = "2026-07-21"


def _frame() -> pd.DataFrame:
    """One row per (fresh, stage, score) combination worth distinguishing."""
    return pd.DataFrame([
        # ticker         anchor_date   stage        score
        ("STALE_HIGH",  "2026-06-01", "triggered", 0.99),
        ("FRESH_SETUP", AS_OF,        "setup",     0.10),
        ("FRESH_TRIG_LO", AS_OF,      "triggered", 0.20),
        ("FRESH_TRIG_HI", AS_OF,      "triggered", 0.80),
        ("NO_SCORE",    AS_OF,        "setup",     float("nan")),
    ], columns=["ticker", "anchor_date", "stage", "prob_home_run"])


def _order(df: pd.DataFrame) -> list[str]:
    return _default_order(df, AS_OF)["ticker"].tolist()


def test_fresh_outranks_a_higher_score():
    """The whole point of key 1: today's anchor beats last month's 0.99."""
    out = _order(_frame())
    assert out[0] != "STALE_HIGH"
    assert out[-1] == "STALE_HIGH" or out.index("STALE_HIGH") > out.index("FRESH_SETUP")


def test_triggered_before_setup_within_fresh():
    out = _order(_frame())
    assert out.index("FRESH_TRIG_HI") < out.index("FRESH_SETUP")
    assert out.index("FRESH_TRIG_LO") < out.index("FRESH_SETUP")


def test_score_breaks_the_tie_descending():
    out = _order(_frame())
    assert out.index("FRESH_TRIG_HI") < out.index("FRESH_TRIG_LO")


def test_missing_score_sorts_last_not_first():
    """NaN must not float to the top — a blank score is 'not scored yet', and the
    page's own caption promises score-descending."""
    out = _order(_frame())
    assert out.index("NO_SCORE") > out.index("FRESH_SETUP")


def test_null_anchor_date_is_not_fresh():
    """A breakout from outside the trend template has no anchor date at all; NaT
    must compare false, not raise and not count as today."""
    df = _frame()
    df.loc[len(df)] = ("NO_ANCHOR", None, "triggered", 0.95)
    out = _order(df)
    assert out.index("NO_ANCHOR") > out.index("FRESH_TRIG_HI")


def test_helper_columns_do_not_leak_into_the_table():
    """_shape selects by column name, so a stray _fresh/_trig would be harmless —
    but they'd show up in any downstream .to_csv/debug view. Drop them."""
    out = _default_order(_frame(), AS_OF)
    assert not {"_fresh", "_trig"} & set(out.columns)


def test_finviz_url_shape():
    """The display regex in dashboard_utils only strips this exact URL form; if the
    two drift the table shows raw URLs instead of tickers."""
    import os
    import re
    import sys

    os.environ.setdefault("DASHBOARD_DB_PATH", "data/dashboard.duckdb")
    sys.path.insert(0, str(ROOT / "scripts"))
    import dashboard_utils as du

    url = du.finviz_url("URGN")
    assert url == "https://finviz.com/stock?t=URGN&p=d"
    assert re.search(du._FINVIZ_DISPLAY, url).group(1) == "URGN"
    assert du.finviz_url(None) is None
