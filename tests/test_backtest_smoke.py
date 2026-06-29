"""End-to-end smoke + parity guard for the backtest scoring path.

These are integration tests — they require the real market DB and the prod model
artifact, so they skip cleanly when either is absent (CI without data). They are
the regression guard that "finalised" the backtester:

  1. The vectorized engine scores the prod model end-to-end without raising
     (catches categorical-contract / feature-resolution regressions).
  2. A model with categorical features but no categorical_mapping.json hard-fails
     (the contract that keeps scoring reproducible).
  3. Backtest scoring matches the materialized daily_predictions on the overlap
     window (proves backtest == prod scoring, the basis for model comparison).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import config
from src import db

PROD_MODEL = config.BASE_DIR / "models" / "m01_prototype_2003_2026" / "v2" / "model.json"
PROD_VERSION_ID = "m01_prototype_2003_2026_20260514_233125"
MAPLESS_MODEL = Path("models/m01_prototyoe_2003_2026/model.json")  # orphaned, no mapping
DB_PATH = config.DATA_DIR / "market_data.duckdb"

_db_missing = not DB_PATH.exists()
_model_missing = not Path(PROD_MODEL).exists()

requires_data = pytest.mark.skipif(
    _db_missing or _model_missing,
    reason=f"needs market DB ({DB_PATH}) and prod model ({PROD_MODEL})",
)


@requires_data
def test_vectorized_scores_prod_model_end_to_end():
    from src.backtest.vectorized_backtest import VectorizedSEPABacktest

    vbt = VectorizedSEPABacktest(
        model_path=str(PROD_MODEL),
        start_date="2024-01-01",
        end_date="2024-02-29",
        min_prob_elite=0.15,
        max_positions_per_day=3,
    )
    trades = vbt.run()
    # A short window over the full universe must produce *some* trades; the exact
    # count is not asserted (data-dependent), only that the path runs clean.
    assert trades is not None
    assert {"ticker", "entry_date", "exit_price", "pnl_pct"}.issubset(trades.columns)


@requires_data
def test_mapless_model_hard_fails():
    """A model with categorical features but no frozen vocab must raise, not
    silently fall back to per-frame codes (which drift vs training)."""
    if not MAPLESS_MODEL.exists():
        pytest.skip("orphaned mapless model not present")

    from src.backtest.universe_scorer import UniverseScorer

    scorer = UniverseScorer(m01_path=str(MAPLESS_MODEL), calibration_path=None)
    with pytest.raises(ValueError, match="categorical_mapping"):
        scorer.score_from_t3("2024-01-01", "2024-01-31")


@requires_data
def test_backtest_matches_prod_predictions():
    """Backtest scoring == materialized daily_predictions on the overlap window.

    Skips if the prod model has no logged predictions in the table yet.
    """
    from src.backtest.universe_scorer import UniverseScorer

    start, end = "2025-11-03", "2025-11-14"

    con = db.connect(str(DB_PATH), read_only=True)
    try:
        prod = con.execute(
            "SELECT DISTINCT CAST(prediction_date AS DATE) AS date, ticker, prob_class_3 "
            "FROM daily_predictions WHERE model_version_id = ? "
            "AND prediction_date BETWEEN ? AND ?",
            [PROD_VERSION_ID, start, end],
        ).fetchdf()
    finally:
        con.close()

    if prod.empty:
        pytest.skip("no daily_predictions for prod model in overlap window")

    scorer = UniverseScorer(m01_path=str(PROD_MODEL), calibration_path=None)
    scored = scorer.score_from_t3(start, end)[["date", "ticker", "prob_elite"]].copy()
    scored["date"] = pd.to_datetime(scored["date"])
    prod["date"] = pd.to_datetime(prod["date"])
    prod = prod.drop_duplicates(["date", "ticker"])

    merged = scored.merge(prod, on=["date", "ticker"], how="inner")
    assert len(merged) > 100, "too few overlapping rows to be meaningful"

    diff = (merged["prob_elite"] - merged["prob_class_3"]).abs()
    frac_off = (diff > 1e-4).mean()
    # NaN-passthrough (matching prod) brings this to <1% (residual is a couple of
    # tickers whose t3 vs v_d3 feature snapshot differs). The old window-median
    # fill put this at ~44%.
    assert frac_off < 0.01, (
        f"{frac_off:.1%} of rows diverge from prod scoring (max diff {diff.max():.4f}). "
        f"Backtest scoring has drifted from daily_predictions."
    )
