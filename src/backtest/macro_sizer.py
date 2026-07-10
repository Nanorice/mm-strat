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

# --- Regime governor (sprint 14) ---------------------------------------------
# TWO signals, TWO jobs (project_entry_timing_macro_axis):
#   1. stress_ew_vix ranks the MEAN  -> size UP when stress is high.
#   2. SPY>200d is the TAIL GATE      -> zero exposure below (removes the
#      bear-stress falling knife at ~0 mean cost).
# Both cuts are LIVE-SAFE: the composite is an expanding-z (day t uses stats
# through t-1) and the quintile threshold is an expanding quantile — the EDA
# used full-sample cuts, which can't size live capital.
GOV_STRESS_SYMBOLS = ("BAMLH0A0HYM2", "DGS10", "CAPE_OURS", "VIX")
GOV_HI_Q = 0.80        # top expanding-quintile of stress -> full size
GOV_BASE_W = 0.50      # base size below the top quintile (still deployed, bull-gated)
GOV_MIN_OBS = 252      # 1yr min history before the expanding stats are trusted


def spy_above_200d(start: str, end: str, db_path: Optional[str] = None) -> dict:
    """Date -> bool: was SPY above its 200d SMA at that day's close? The ex-ante
    deploy gate from Thread E Q15 (SPY-200d, not VIX). Uses close through `date`
    only, so it's known at the day's open the strategy would act on — no lookahead.

    The 200d window needs history BEFORE `start`; we fetch a full lookback so the
    first in-window days aren't NaN. Returned dict is date(py) -> bool over [start,end].
    """
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    con = db.connect(str(path), read_only=True)
    try:
        df = con.execute(
            "SELECT date, spy_close FROM t1_macro WHERE date <= ? ORDER BY date", [end],
        ).df()
    finally:
        con.close()
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")["spy_close"].ffill()
    above = df > df.rolling(200).mean()
    above = above[above.index >= pd.Timestamp(start)]
    return {d.date(): bool(v) for d, v in above.items()}


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

    def _stress_ew_vix(self, end: str) -> pd.Series:
        """Live-safe stress composite = mean of expanding-z of
        [+credit, -rates, -cape, +vix] on the macro_data (FRED) table. Same
        definition as Thread F's stress_ew_vix (the best live-safe variant);
        computed here so production code doesn't import a research script.

        Fetches ALL history up to `end` so the expanding stats have a full
        lookback; returns the daily composite indexed by date.
        """
        con = db.connect(str(self.db_path), read_only=True)
        try:
            df = con.execute(
                "SELECT date, symbol, close AS value FROM macro_data "
                "WHERE symbol IN ('BAMLH0A0HYM2','DGS10','CAPE_OURS','VIX') AND date <= ?",
                [end],
            ).df()
        finally:
            con.close()
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df["date"] = pd.to_datetime(df["date"])
        w = (df.drop_duplicates(["date", "symbol"])
               .pivot(index="date", columns="symbol", values="value").sort_index().ffill())

        def zexp(s: pd.Series) -> pd.Series:
            mu = s.expanding(min_periods=GOV_MIN_OBS).mean().shift(1)
            sd = s.expanding(min_periods=GOV_MIN_OBS).std().shift(1)
            return (s - mu) / sd

        parts = [zexp(w["BAMLH0A0HYM2"]), -zexp(w["DGS10"]),
                 -zexp(w.get("CAPE_OURS", pd.Series(index=w.index, dtype=float))),
                 zexp(w["VIX"])]
        return pd.concat(parts, axis=1).mean(axis=1, skipna=True)

    def governor_weight(self, start: str, end: str) -> pd.Series:
        """The regime governor: full size in the top expanding-quintile of stress,
        GOV_BASE_W below; ZERO when SPY<=200d (tail gate). All cuts live-safe and
        lagged one day. Returns a daily exposure series over [start, end].
        """
        stress = self._stress_ew_vix(end)
        # Expanding quantile threshold (day t uses history through t-1) -> live-safe bucket.
        hi_cut = stress.expanding(min_periods=GOV_MIN_OBS).quantile(GOV_HI_Q).shift(1)
        w = pd.Series(GOV_BASE_W, index=stress.index, name="exposure")
        w[stress >= hi_cut] = 1.0
        w[hi_cut.isna()] = 1.0  # pre-history: no stress read yet -> full (gate still applies)

        # Tail gate: SPY<=200d -> flat. spy_above_200d is already causal (close<=date).
        above = spy_above_200d(start, end, str(self.db_path))
        gate = pd.Series({pd.Timestamp(d): (1.0 if v else 0.0) for d, v in above.items()})
        w = w.reindex(w.index.union(gate.index)).ffill()
        w = w * gate.reindex(w.index).ffill().fillna(1.0)

        w = w[(w.index >= pd.Timestamp(start)) & (w.index <= pd.Timestamp(end))]
        # Lag: today's sizing uses yesterday's (known) stress+gate.
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
        if mode == "governor":
            return self.governor_weight(start, end)
        raise ValueError(f"unknown sizing mode '{mode}' (flat|vix|m03|governor)")


if __name__ == "__main__":
    # Self-check: governor weights are live-safe and behave as specced.
    # Span includes real stress episodes (2008 GFC, 2020 COVID) so the top-quintile
    # tilt actually fires — over a calm-only window (e.g. 2015-19) it sits at base
    # weight by design (absolute expanding-quintile; calm eras don't clear it).
    ms = MacroSizer()
    w = ms.governor_weight("2007-01-01", "2022-12-31")
    assert len(w), "empty governor weight"
    assert w.min() >= 0.0 and w.max() <= 1.0, f"weight out of [0,1]: {w.min()}..{w.max()}"
    # Gate must fire: some days flat (SPY<=200d) over a span covering 2008/2020/2022.
    assert (w == 0.0).any(), "tail gate never fired — SPY>200d gate not applied?"
    # Base-weight days must dominate (bull, sub-quintile stress).
    assert (w == GOV_BASE_W).any(), "base-weight days missing — tilt collapsed?"
    # NOTE: full-size (top-quintile x SPY>200d = bull-stress) is RARE by design —
    # stress days mostly coincide with SPY<=200d, so the gate zeroes most of them.
    # This is the GATE x TILT tension made concrete; the cone run tells us if the
    # surviving bull-stress tilt earns its keep vs plain flat-when-above-200d.
    # Composite itself: expanding-z must be NaN in the min-obs warmup, defined after.
    s = ms._stress_ew_vix("2022-12-31")
    assert s.iloc[:GOV_MIN_OBS].isna().all(), "expanding-z leaked into warmup window"
    assert s.iloc[GOV_MIN_OBS + 300:].notna().any(), "stress composite never populated"
    print(f"[OK] governor self-check: {len(w)} days, "
          f"gate-off {100 * (w == 0).mean():.0f}%, full-size {100 * (w == 1).mean():.0f}%, "
          f"base {100 * (w == GOV_BASE_W).mean():.0f}%")
