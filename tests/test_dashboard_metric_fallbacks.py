"""Two dashboard read-time fills, both for data the writer never produced.

- Model Lab: `models.accuracy/weighted_f1/macro_f1` are HOLDOUT-TEST columns and
  are deliberately NULL under `--no-holdout` (train_mfe_classifier.py), which
  stashes val metrics in `specs_json` instead. The page falls back and must say
  so — silently labelling val numbers "Accuracy" is the failure mode.
- Backtest Studio: trades.parquet has no `sector`; it is joined at read.

Both functions are exec'd out of the page source (same trick as
test_screening_order) — importing the module would run the page body.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


def _exec_func(page: str, name: str, ns: dict):
    src = (ROOT / "scripts" / "pages" / page).read_text(encoding="utf-8")
    start = src.index(f"def {name}")
    end = min(i for i in (src.find(t, start + 1) for t in ("\ndef ", "\n@", "\n# ")) if i > 0)
    ns.setdefault("pd", pd)
    ns.setdefault("json", json)
    exec(compile(src[start:end], name, "exec"), ns)
    return ns[name]


classification_metrics = _exec_func("3_Model_Lab.py", "classification_metrics", {})
attach_sector = _exec_func("4_Backtest_Studio.py", "attach_sector", {})


# ── Model Lab metric provenance ──────────────────────────────────────────────

def _row(acc=None, wf1=None, mf1=None, specs=None) -> pd.Series:
    return pd.Series({
        "accuracy": acc, "weighted_f1": wf1, "macro_f1": mf1,
        "specs_json": json.dumps(specs) if specs is not None else None,
    })


def test_test_columns_win_over_specs():
    vals, src = classification_metrics(_row(
        0.29, 0.28, 0.29, {"val_metrics": {"accuracy": 0.9}}))
    assert src == "test"
    assert vals["accuracy"] == 0.29


def test_falls_back_to_val_metrics_and_flags_it():
    vals, src = classification_metrics(_row(specs={"val_metrics": {
        "accuracy": 0.634, "weighted_f1": 0.688, "macro_f1": 0.554}}))
    assert src == "val", "val numbers must never be labelled as test metrics"
    assert vals == {"accuracy": 0.634, "weighted_f1": 0.688, "macro_f1": 0.554}


def test_no_metrics_anywhere():
    assert classification_metrics(_row())[1] == "none"
    # --no-holdout=False writes val_metrics: null
    assert classification_metrics(_row(specs={"val_metrics": None}))[1] == "none"
    assert classification_metrics(_row(specs={"features": []}))[1] == "none"


def test_unparseable_specs_does_not_raise():
    row = _row()
    row["specs_json"] = "{not json"
    assert classification_metrics(row)[1] == "none"


# ── Backtest Studio sector join ──────────────────────────────────────────────

def _stub_profiles(frame: pd.DataFrame):
    mod = types.ModuleType("dashboard_utils")
    mod.load_ticker_sectors = lambda: frame  # type: ignore[attr-defined]
    sys.modules["dashboard_utils"] = mod


def test_sector_joined_onto_trades(monkeypatch):
    monkeypatch.delitem(sys.modules, "dashboard_utils", raising=False)
    _stub_profiles(pd.DataFrame(
        [("AMD", "Technology", "Semiconductors")],
        columns=["ticker", "sector", "industry"]))
    out = attach_sector(pd.DataFrame({"ticker": ["AMD", "ZZZZ"], "pnl_percent": [1.0, -2.0]}))
    assert list(out["sector"]) == ["Technology", None] or out["sector"].isna().iloc[1]
    assert out["sector"].iloc[0] == "Technology"
    assert len(out) == 2, "left join must not drop trades with no profile"


def test_sector_join_is_a_noop_when_not_needed():
    assert attach_sector(None) is None
    empty = pd.DataFrame({"ticker": []})
    assert attach_sector(empty) is empty
    already = pd.DataFrame({"ticker": ["AMD"], "sector": ["Technology"]})
    assert attach_sector(already) is already, "must not clobber an existing sector"
