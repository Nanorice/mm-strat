"""Macro-driven position sizing — a SEPARATE input from model selection.

The model decides *what* to hold (score -> rank -> pick). MacroSizer decides
*how much* to hold, from a macro regime signal that is NOT a model feature. This
keeps regime out of the score (no M03 double-counting) while still letting regime
govern exposure.

Produces a daily weight series w(date) in [0, 1] to feed
VectorizedSEPABacktest.equity_curve(trades, exposure=w). The weight is lagged one
business day so a day's sizing uses only information available before that day
(no lookahead).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from src import db
import config

DEFAULT_DB_PATH = config.DATA_DIR / "market_data.duckdb"

# VIX -> exposure. Bands are a fixed hypothesis, not tuned params: risk-off in
# high vol. Edges are right-open [lo, hi).
VIX_BANDS = [
    (0.0, 15.0, 1.00),
    (15.0, 25.0, 0.60),
    (25.0, 35.0, 0.30),
    (35.0, 999.0, 0.15),
]

# M03 regime score is 0-100 (risk-on high). Risk-off => cut exposure. Right-open [lo, hi).
M03_BANDS = [
    (0.0, 40.0, 0.15),
    (40.0, 55.0, 0.30),
    (55.0, 70.0, 0.60),
    (70.0, 999.0, 1.00),
]


class MacroSizer:
    def __init__(self, db_path: Optional[str] = None, lag_days: int = 1):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.lag_days = lag_days

    def flat(self, dates: pd.DatetimeIndex) -> pd.Series:
        """Control: constant full exposure."""
        return pd.Series(1.0, index=pd.DatetimeIndex(dates), name="exposure")

    def vix_weight(self, start: str, end: str) -> pd.Series:
        """VIX-banded daily exposure, lagged to avoid lookahead."""
        con = db.connect(str(self.db_path), read_only=True)
        try:
            df = con.execute(
                "SELECT date, vix_close FROM t1_macro WHERE date BETWEEN ? AND ? ORDER BY date",
                [start, end],
            ).df()
        finally:
            con.close()
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")["vix_close"].ffill()

        w = pd.Series(1.0, index=df.index, name="exposure")
        for lo, hi, weight in VIX_BANDS:
            w[(df >= lo) & (df < hi)] = weight
        # Lag: today's sizing uses yesterday's (known) VIX regime.
        return w.shift(self.lag_days).ffill().fillna(1.0)

    def m03_weight(self, start: str, end: str) -> pd.Series:
        """M03 regime-score daily exposure, lagged. m03_score is 0-100 (risk-on
        high); banded to exposure the same shape as VIX so the two are comparable.
        Tests M03 as a sizing lever rather than a model feature."""
        con = db.connect(str(self.db_path), read_only=True)
        try:
            df = con.execute(
                "SELECT date, m03_score FROM t2_regime_scores WHERE date BETWEEN ? AND ? ORDER BY date",
                [start, end],
            ).df()
        finally:
            con.close()
        df["date"] = pd.to_datetime(df["date"])
        score = df.set_index("date")["m03_score"].ffill()
        w = pd.Series(1.0, index=score.index, name="exposure")
        for lo, hi, weight in M03_BANDS:
            w[(score >= lo) & (score < hi)] = weight
        return w.shift(self.lag_days).ffill().fillna(1.0)

    def weight(self, mode: str, start: str, end: str,
               dates: Optional[pd.DatetimeIndex] = None) -> pd.Series:
        if mode == "flat":
            if dates is None:
                raise ValueError("flat mode needs a `dates` index")
            return self.flat(dates)
        if mode == "vix":
            return self.vix_weight(start, end)
        if mode == "m03":
            return self.m03_weight(start, end)
        raise ValueError(f"unknown sizing mode '{mode}' (flat|vix|m03)")
