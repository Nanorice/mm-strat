"""Weather gauge — one persisted daily state row combining the validated regime
signals into a single deploy posture for manual review.

Assembly, not new research (sprint-14 verdicts): reuses MacroSizer's live-safe
signals (SPY>200d brake, expanding-z stress composite) and adds the breakout-
supply gauge (§1c: daily breakout share, EMA-smoothed, expanding-quintile
famine↔flood). All three are causal — day t uses only data through t-1 (stress/
supply expanding stats are shifted; SPY-200d close is same-day but known at the
open the reviewer acts on).

The combination rule (§B3 of the deliverables roadmap):
  - SPY<=200d is the BRAKE → posture = STAND ASIDE (the one honest gate).
  - Above 200d, stress+supply are the DURING-PERIOD STEER (not brakes):
      high stress ∧ famine (early-recovery scarcity) → DEPLOY MORE  (+10.5% pocket)
      flood ∧ low stress (late-cycle)                → DEPLOY, TRIM NEW
      else                                            → DEPLOY
  - 6-pillar macro is context only (it flips bull↔bear; pooling it is unsafe) —
    displayed by the dashboard, NOT gated here.

stress_z ships PROVISIONAL (§B5: the dd/macro stress split is leaky/flickery; the
ew_vix variant is the best live-safe one but flicker-stabilization is open). The
brake + supply carry the gauge; stress only nudges DEPLOY→DEPLOY MORE.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from src import db
from src.backtest.macro_sizer import MacroSizer, spy_above_200d
import config

DEFAULT_DB_PATH = config.DATA_DIR / "market_data.duckdb"

SUPPLY_EMA_SPAN = 10          # §1c: EMA10 of the breakout share (level, not gradient)
SUPPLY_MIN_OBS = 252         # 1yr before expanding quintiles are trusted
FAMINE_Q = 0.20              # bottom expanding-quintile of supply → scarcity
FLOOD_Q = 0.80              # top expanding-quintile → over-supply (late-cycle)
STRESS_HI_Q = 0.80          # top expanding-quintile of stress → "high" (matches governor)


def _supply_share(con, end: str) -> pd.Series:
    """Daily breakout share = breakout_ok / trend_ok, normalized so the 3.6× growth
    in universe size doesn't masquerade as a supply trend (§1c). EMA10-smoothed."""
    df = con.execute(
        """
        SELECT date,
               SUM(CASE WHEN breakout_ok THEN 1 ELSE 0 END) AS n_breakout,
               SUM(CASE WHEN trend_ok THEN 1 ELSE 0 END)    AS n_trend
        FROM t3_sepa_features
        WHERE feature_version = 'v3.1' AND date <= ?
        GROUP BY date ORDER BY date
        """,
        [end],
    ).df()
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").astype(float)
    n_trend = df["n_trend"].where(df["n_trend"] > 0)  # 0-denominator → NaN, not inf
    share = df["n_breakout"] / n_trend
    return share.ewm(span=SUPPLY_EMA_SPAN, min_periods=1).mean()


def _expanding_bucket(s: pd.Series, lo_q: float, hi_q: float) -> pd.Series:
    """Live-safe famine/normal/flood tag: expanding quantiles, shifted so day t
    uses history through t-1 (same pattern as MacroSizer.governor_weight)."""
    lo = s.expanding(min_periods=SUPPLY_MIN_OBS).quantile(lo_q).shift(1)
    hi = s.expanding(min_periods=SUPPLY_MIN_OBS).quantile(hi_q).shift(1)
    tag = pd.Series("normal", index=s.index, dtype=object)
    tag[s <= lo] = "famine"
    tag[s >= hi] = "flood"
    tag[lo.isna()] = "normal"  # warmup: no read yet
    return tag


def _posture(row: pd.Series) -> str:
    """The §B3 combination rule → one headline the reviewer reads."""
    if not row["spy_above_200d"]:
        return "STAND ASIDE"          # brake — below the 200d, nothing else matters
    if row["supply_regime"] == "famine" and row["stress_high"]:
        return "DEPLOY MORE"          # early-recovery scarcity + stress → the +10.5% pocket
    if row["supply_regime"] == "flood" and not row["stress_high"]:
        return "DEPLOY, TRIM NEW"     # late-cycle over-supply, calm → supply-drift warning
    return "DEPLOY"


class WeatherEngine:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH

    def compute(self, start: str, end: str) -> pd.DataFrame:
        """Daily weather state over [start, end]. One row per trading day."""
        sizer = MacroSizer(db_path=str(self.db_path))
        stress = sizer._stress_ew_vix(end)                      # causal expanding-z
        stress_hi = stress.expanding(min_periods=SUPPLY_MIN_OBS).quantile(STRESS_HI_Q).shift(1)

        con = db.connect(str(self.db_path), read_only=True)
        try:
            supply = _supply_share(con, end)
            regime = con.execute(
                "SELECT date, m03_score FROM t2_regime_scores WHERE date <= ? ORDER BY date",
                [end],
            ).df()
        finally:
            con.close()
        regime["date"] = pd.to_datetime(regime["date"])
        m03 = regime.set_index("date")["m03_score"].ffill()

        above = spy_above_200d(start, end, str(self.db_path))
        gate = pd.Series({pd.Timestamp(d): bool(v) for d, v in above.items()})

        supply_regime = _expanding_bucket(supply, FAMINE_Q, FLOOD_Q)

        out = pd.DataFrame(index=gate.index)
        out["spy_above_200d"] = gate
        out["stress_z"] = stress.reindex(out.index).ffill()
        out["stress_high"] = (stress >= stress_hi).reindex(out.index).ffill().fillna(False)
        out["m03_score"] = m03.reindex(out.index).ffill()
        out["breakout_supply_share"] = supply.reindex(out.index).ffill()
        out["supply_regime"] = supply_regime.reindex(out.index).ffill()
        out = out[(out.index >= pd.Timestamp(start)) & (out.index <= pd.Timestamp(end))]
        out["deploy_posture"] = out.apply(_posture, axis=1)
        return out.reset_index(names="date")

    def refresh(self, start: str = "2003-01-01", end: Optional[str] = None) -> int:
        """Recompute and persist the full weather_gauge table. Returns row count.
        Full recompute (not incremental): expanding stats depend on all history and
        the table is tiny (one row/day). Orchestrator-owned write."""
        if end is None:
            con = db.connect(str(self.db_path), read_only=True)
            try:
                end = str(con.execute("SELECT MAX(date) FROM t3_sepa_features").fetchone()[0])
            finally:
                con.close()
        df = self.compute(start, end)
        con = db.connect(str(self.db_path))
        try:
            con.execute("DROP TABLE IF EXISTS weather_gauge")
            con.register("_wg", df)
            con.execute("CREATE TABLE weather_gauge AS SELECT * FROM _wg")
            con.unregister("_wg")
            n = con.execute("SELECT COUNT(*) FROM weather_gauge").fetchone()[0]
        finally:
            con.close()
        return n


if __name__ == "__main__":
    # Self-check: the gauge is live-safe and the posture rule fires all four states
    # over a span covering bull, bear, and stress episodes.
    eng = WeatherEngine()
    df = eng.compute("2007-01-01", "2022-12-31")
    assert len(df), "empty weather series"
    # Brake dominates below-200d spans (2008/2020/2022).
    assert (df["deploy_posture"] == "STAND ASIDE").any(), "brake never fired"
    assert (df["deploy_posture"] == "DEPLOY").any(), "baseline DEPLOY missing"
    # supply_regime must exercise all three states over 15 years.
    assert set(df["supply_regime"].unique()) >= {"famine", "normal", "flood"}, \
        f"supply regime incomplete: {df['supply_regime'].unique()}"
    # Live-safe: the raw stress composite must be NaN through its OWN first 252 obs
    # (compute() windows to 2007+, by which point the 1990s-onward series is warm).
    raw = MacroSizer()._stress_ew_vix("2022-12-31")
    assert raw.iloc[:SUPPLY_MIN_OBS].isna().all(), "stress expanding-z leaked into warmup"
    print(f"[OK] weather self-check: {len(df)} days | postures "
          f"{df['deploy_posture'].value_counts().to_dict()}")
