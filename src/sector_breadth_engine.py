"""Sector-breadth gauge — one materialized snapshot per (grain, sector/subsector)
for the Macro page's Section-2 heatmap (sprint-14 dashboard uplift).

Rendering job, not research: the page never re-scans price/feature tables per
pageload. This nightly pass aggregates the latest day of
`t2_screener_features ⋈ company_profiles` into per-sector and per-subsector rows —
today's return distribution (quantiles for the KDE shape), up/down breadth,
trend_ok/breakout_ok participation, and names added-today / added-5d. The page
draws the KDE from the stored quantiles.

Grain: one row per sector (grain='sector') plus one per subsector
(grain='subsector', sector=parent). Native Yahoo/FMP taxonomy — no GICS
crosswalk. ETF:* pseudo-sectors excluded. Returns computed from
t2_screener_features OHLC (adj_close is 100% NULL; returns come from close).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pandas as pd

from src import db
import config

DEFAULT_DB_PATH = config.DATA_DIR / "market_data.duckdb"

ADDED_LOOKBACK_DAYS = 12  # enough trading days to cover a 5-session prior window

# Fixed return-distribution bins (percent). Shared across all cards so the KDE
# x-axis is comparable sector-to-sector. Returns clamped into [LO, HI] so tails
# land in the edge bins rather than widening the axis. 32 bins × 0.5% = ±8%.
HIST_LO, HIST_HI, HIST_BINS = -8.0, 8.0, 32
_HIST_W = (HIST_HI - HIST_LO) / HIST_BINS

# Per-group aggregate. `grain` chosen at query time (sector vs subsector); the
# only difference is the GROUP BY key, so one templated CTE serves both.
_AGG_SQL = """
WITH base AS (
    SELECT s.ticker, s.date, s.trend_ok, s.breakout_ok,
           p.sector, p.industry,
           (s.close - s.open) / NULLIF(s.open, 0) AS ret,
           LAG(s.trend_ok)    OVER w AS prev_trend,
           LAG(s.breakout_ok) OVER w AS prev_brk
    FROM t2_screener_features s
    JOIN company_profiles p USING (ticker)
    WHERE s.date >= (SELECT MAX(date) FROM t2_screener_features) - INTERVAL {lookback} DAY
      AND p.sector IS NOT NULL AND p.sector NOT LIKE 'ETF:%'
      AND s.open IS NOT NULL AND s.close IS NOT NULL
    WINDOW w AS (PARTITION BY s.ticker ORDER BY s.date)
)
SELECT
    '{grain}'                                              AS grain,
    sector                                                 AS sector,
    {group_key}                                            AS name,
    COUNT(*)                                               AS n_names,
    COUNT(*) FILTER (WHERE ret > 0)                        AS n_up,
    COUNT(*) FILTER (WHERE ret < 0)                        AS n_down,
    COUNT(*) FILTER (WHERE trend_ok)                       AS n_trend_ok,
    COUNT(*) FILTER (WHERE breakout_ok)                    AS n_breakout_ok,
    COUNT(*) FILTER (WHERE trend_ok AND NOT COALESCE(prev_trend, FALSE))       AS trend_added_today,
    COUNT(*) FILTER (WHERE breakout_ok AND NOT COALESCE(prev_brk, FALSE))      AS breakout_added_today,
    ROUND(100 * MEDIAN(ret), 4)                            AS ret_median_pct,
    ROUND(100 * QUANTILE_CONT(ret, 0.05), 4)              AS ret_p05_pct,
    ROUND(100 * QUANTILE_CONT(ret, 0.25), 4)              AS ret_p25_pct,
    ROUND(100 * QUANTILE_CONT(ret, 0.75), 4)              AS ret_p75_pct,
    ROUND(100 * QUANTILE_CONT(ret, 0.95), 4)              AS ret_p95_pct
FROM base
WHERE date = (SELECT MAX(date) FROM base)
GROUP BY sector, name
"""

# Fixed-bin histogram of today's returns per group. Bin index is clamped into
# [0, HIST_BINS-1] so tails fold into the edge bins. Returns a long frame
# (sector, name, bin, cnt); densified into a full array in pandas.
_HIST_SQL = """
WITH today AS (
    SELECT p.sector AS sector, {group_key} AS name,
           LEAST({bins} - 1, GREATEST(0,
             CAST(FLOOR((100 * (s.close - s.open) / NULLIF(s.open, 0) - {lo}) / {w}) AS INTEGER)
           )) AS bin
    FROM t2_screener_features s
    JOIN company_profiles p USING (ticker)
    WHERE s.date = (SELECT MAX(date) FROM t2_screener_features)
      AND p.sector IS NOT NULL AND p.sector NOT LIKE 'ETF:%'
      AND s.open IS NOT NULL AND s.close IS NOT NULL AND s.open <> 0
)
SELECT sector, name, bin, COUNT(*) AS cnt
FROM today GROUP BY sector, name, bin
"""


def _added_5d(con, grain_key: str) -> pd.DataFrame:
    """Names whose trend_ok/breakout_ok flipped True on any of the last 5 sessions.
    Separate pass: a name added 3d ago is 'added_5d' but not 'added_today'."""
    sql = f"""
    WITH base AS (
        SELECT s.ticker, s.date, s.trend_ok, s.breakout_ok, p.sector, p.industry,
               LAG(s.trend_ok)    OVER w AS prev_trend,
               LAG(s.breakout_ok) OVER w AS prev_brk
        FROM t2_screener_features s
        JOIN company_profiles p USING (ticker)
        WHERE s.date >= (SELECT MAX(date) FROM t2_screener_features) - INTERVAL {ADDED_LOOKBACK_DAYS} DAY
          AND p.sector IS NOT NULL AND p.sector NOT LIKE 'ETF:%'
        WINDOW w AS (PARTITION BY s.ticker ORDER BY s.date)
    ), recent AS (
        SELECT DISTINCT date FROM base ORDER BY date DESC LIMIT 5
    )
    SELECT sector, {grain_key} AS name,
           COUNT(DISTINCT ticker) FILTER (WHERE trend_ok AND NOT COALESCE(prev_trend, FALSE))  AS trend_added_5d,
           COUNT(DISTINCT ticker) FILTER (WHERE breakout_ok AND NOT COALESCE(prev_brk, FALSE)) AS breakout_added_5d
    FROM base WHERE date IN (SELECT date FROM recent)
    GROUP BY sector, name
    """
    return con.execute(sql).df()


def _histograms(con, group_key: str) -> dict:
    """(sector, name) → dense list of HIST_BINS counts for today's return dist."""
    long = con.execute(_HIST_SQL.format(
        group_key=group_key, bins=HIST_BINS, lo=HIST_LO, w=_HIST_W)).df()
    out: dict = {}
    for (sec, name), g in long.groupby(["sector", "name"]):
        counts = [0] * HIST_BINS
        for b, c in zip(g["bin"].astype(int), g["cnt"].astype(int)):
            counts[b] = c
        out[(sec, name)] = counts
    return out


class SectorBreadthEngine:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH

    def compute(self) -> pd.DataFrame:
        """Latest-day sector + subsector breadth snapshot. One frame, grain-tagged."""
        con = db.connect(str(self.db_path), read_only=True)
        try:
            as_of = con.execute("SELECT MAX(date) FROM t2_screener_features").fetchone()[0]
            sector = con.execute(_AGG_SQL.format(
                grain="sector", group_key="sector",
                lookback=ADDED_LOOKBACK_DAYS)).df()
            subsector = con.execute(_AGG_SQL.format(
                grain="subsector", group_key="industry",
                lookback=ADDED_LOOKBACK_DAYS)).df()
            add5_sec = _added_5d(con, "sector")
            add5_sub = _added_5d(con, "industry")
            hist_sec = _histograms(con, "sector")
            hist_sub = _histograms(con, "industry")
        finally:
            con.close()

        sector = sector.merge(add5_sec, on=["sector", "name"], how="left")
        subsector = subsector.merge(add5_sub, on=["sector", "name"], how="left")
        out = pd.concat([sector, subsector], ignore_index=True)
        for c in ("trend_added_5d", "breakout_added_5d"):
            out[c] = out[c].fillna(0).astype(int)

        # Return histogram as a JSON string (survives register→CTAS→slim-DB copy
        # unscathed; the page json-parses it). Empty → all-zero bins.
        hist = {**hist_sec, **hist_sub}
        zeros = [0] * HIST_BINS
        out["ret_hist"] = [
            json.dumps(hist.get((r["sector"], r["name"]), zeros))
            for _, r in out.iterrows()
        ]
        out.insert(0, "as_of_date", pd.to_datetime(as_of))
        return out

    def refresh(self) -> int:
        """Recompute and persist sector_breadth. Returns row count. Orchestrator-owned
        write; snapshot table (latest day only), rebuilt each run."""
        df = self.compute()
        con = db.connect(str(self.db_path))
        try:
            con.execute("DROP TABLE IF EXISTS sector_breadth")
            con.register("_sb", df)
            con.execute("CREATE TABLE sector_breadth AS SELECT * FROM _sb")
            con.unregister("_sb")
            n = con.execute("SELECT COUNT(*) FROM sector_breadth").fetchone()[0]
        finally:
            con.close()
        return n


if __name__ == "__main__":
    # Self-check: snapshot has both grains, 11 real sectors, no ETF:* leakage,
    # quantiles ordered, participation counts bounded by name count.
    df = SectorBreadthEngine().compute()
    assert len(df), "empty sector_breadth snapshot"
    sec = df[df.grain == "sector"]
    assert len(sec) == 11, f"expected 11 real sectors, got {len(sec)}: {sorted(sec['name'])}"
    assert not df["name"].str.startswith("ETF:").any(), "ETF:* pseudo-sector leaked"
    assert (df.grain == "subsector").sum() > len(sec), "no subsector rows materialized"
    bad = df[df.ret_p05_pct > df.ret_p95_pct]
    assert bad.empty, f"quantiles out of order for {list(bad['name'])}"
    over = df[(df.n_trend_ok > df.n_names) | (df.n_breakout_ok > df.n_names)]
    assert over.empty, f"participation exceeds name count: {list(over['name'])}"
    # histogram: right length, non-negative, sums to ~today's names (≤ n_names).
    hists = df["ret_hist"].map(json.loads)
    assert (hists.map(len) == HIST_BINS).all(), "histogram wrong bin count"
    sums = hists.map(sum)
    assert (sums <= df["n_names"]).all() and (sums > 0).any(), "histogram counts invalid"
    # subsector names roll up to their parent sector's name count (>= because a
    # sector row counts every name; subsectors partition the same set).
    print(f"[OK] sector_breadth self-check: as_of {df['as_of_date'].iloc[0].date()} | "
          f"{len(sec)} sectors, {(df.grain=='subsector').sum()} subsectors | "
          f"total names {sec['n_names'].sum()}")
