"""SEPA entry gate — attach trend_ok/breakout_ok to a scores frame.

score_from_t3 already carries the flags, but the cached score parquet
(cache_model_scores.py) and the daily_predictions/prototype path do NOT — the
per-(ticker,date) score is valid either way, so re-scoring just to bake in two
booleans is waste. Instead join the flags from t3_sepa_features at read time.

The gate itself is applied downstream (ScoreLookup / VectorizedSEPABacktest /
the lottery script), all of which already filter on the columns when present.
This module's job is only to make them present.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from src import db
import config

DEFAULT_DB_PATH = config.DATA_DIR / "market_data.duckdb"


def attach_sepa_flags(scores: pd.DataFrame, db_path: Optional[str] = None) -> pd.DataFrame:
    """Left-join trend_ok/breakout_ok onto `scores` by (date, ticker).

    Rows with no matching t3 row (shouldn't happen for scored rows, but be safe)
    get False/False — i.e. NOT a breakout, so the gate excludes them. Idempotent:
    if the flags are already present the frame is returned unchanged.
    """
    if {"trend_ok", "breakout_ok"}.issubset(scores.columns):
        return scores

    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    lo, hi = scores["date"].min(), scores["date"].max()
    con = db.connect(str(path), read_only=True)
    try:
        flags = con.execute(
            "SELECT date, ticker, trend_ok, breakout_ok FROM t3_sepa_features "
            "WHERE date BETWEEN ? AND ?",
            [str(pd.Timestamp(lo).date()), str(pd.Timestamp(hi).date())],
        ).df()
    finally:
        con.close()
    flags["date"] = pd.to_datetime(flags["date"])

    out = scores.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.merge(flags, on=["date", "ticker"], how="left")
    out["trend_ok"] = out["trend_ok"].fillna(False).astype(bool)
    out["breakout_ok"] = out["breakout_ok"].fillna(False).astype(bool)
    return out


if __name__ == "__main__":
    # Self-check: a flag-less score frame gets gated to the known ~1% breakout rate.
    con = db.connect(str(DEFAULT_DB_PATH), read_only=True)
    raw = con.execute(
        "SELECT date, ticker FROM t3_sepa_features "
        "WHERE date BETWEEN '2024-01-01' AND '2024-02-01'"
    ).df()
    con.close()
    raw["date"] = pd.to_datetime(raw["date"])
    tagged = attach_sepa_flags(raw)
    assert {"trend_ok", "breakout_ok"}.issubset(tagged.columns)
    assert len(tagged) == len(raw), "join must not duplicate/drop rows"
    gated = tagged[tagged.trend_ok & tagged.breakout_ok]
    frac = len(gated) / len(tagged)
    assert 0.005 < frac < 0.05, f"breakout rate {frac:.1%} outside sane band"
    # Idempotent.
    assert attach_sepa_flags(tagged) is tagged
    print(f"[OK] sepa_gate self-check: {len(gated)}/{len(tagged)} breakouts ({frac:.1%})")
