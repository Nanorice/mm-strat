"""Self-check for load_cohort_return_panel (side-quest watchlist tracker).

Hits the slim dashboard DB read-only. Skips if it isn't built on this host.
"""

import os
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

DASH_DB = ROOT / "data" / "dashboard.duckdb"
if not DASH_DB.exists():
    pytest.skip("dashboard.duckdb not built on this host", allow_module_level=True)
os.environ.setdefault("DASHBOARD_DB_PATH", str(DASH_DB))

from dashboard_utils import load_cohort_return_panel  # noqa: E402

MODEL = "m01_prototype_2003_2026_20260514_233125"
COHORT = "pre_breakout"


def test_panel_shape_and_returns():
    df = load_cohort_return_panel(MODEL, cohort=COHORT, mode="to_today")
    assert not df.empty
    assert {"prediction_date", "days_before_today", "ticker",
            "prob_class_3", "ret_pct"} <= set(df.columns)
    # days_before_today is a non-negative offset from the latest signal day
    assert (df["days_before_today"] >= 0).all()
    # returns are finite where a price join succeeded (NaNs already dropped)
    assert np.isfinite(df["ret_pct"]).all()


def test_threshold_shrinks_membership():
    lo = load_cohort_return_panel(MODEL, cohort=COHORT, min_score=0.0)
    hi = load_cohort_return_panel(MODEL, cohort=COHORT, min_score=0.5)
    assert len(hi) <= len(lo)
    if not hi.empty:
        assert (hi["prob_class_3"] >= 0.5).all()


def test_forward_mode_runs():
    df = load_cohort_return_panel(MODEL, cohort=COHORT, mode="forward", horizon=20)
    # forward mode may drop the newest ~horizon days but must still return finite rows
    if not df.empty:
        assert np.isfinite(df["ret_pct"]).all()


if __name__ == "__main__":
    test_panel_shape_and_returns()
    test_threshold_shrinks_membership()
    test_forward_mode_runs()
    print("[OK] cohort return panel self-check passed")
