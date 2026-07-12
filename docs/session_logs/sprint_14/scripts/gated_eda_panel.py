"""ONE shared gated-breakout panel for the Sprint-14 consolidation EDA.

Audit finding (2026-07-11): the `multiyear/raw_full_*_fwd.parquet` cache scores the
FULL trend-active universe (596k rows/yr) — an un-gated `top-N by prob_elite` draws
from the inflated pool (the same population-inflation bug that invalidated the
Sprint-13 arena, RESEARCH_LOG Q21). The genuine-breakout population is only
0.4-1.0% of that panel.

This module builds the audited panel ONCE: the rich full-universe parquet (has
sector/cap/rs/fwd) INNER-JOINed onto the gated score cache (has trend_ok &
breakout_ok), so every downstream cut shares the SAME genuine-breakout population.

    from gated_eda_panel import load_gated_panel
    panel = load_gated_panel()          # all years, cached
    panel = load_gated_panel([2020])    # one year (smoke)
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

import pandas as pd


def _root() -> Path:
    p = Path(__file__).resolve()
    for d in (p, *p.parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError("root not found")


ROOT = _root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MULTIYEAR = ROOT / "data/model_output_eda/multiyear"
GATED_CACHE = (ROOT /
    "data/score_cache/m01_binary_calibrated_2003-01-01_2026-05-22_sepa_gated.parquet")

# columns present in ALL year files (older years lack sector/fwd150/fwd200 —
# schema drift). The consumer coverage-guards the optional ones per-cut.
_CORE = ["date", "ticker", "prob_elite", "fwd20", "fwd50", "fwd100"]


@lru_cache(maxsize=4)
def _gated_keys() -> pd.DataFrame:
    g = pd.read_parquet(GATED_CACHE, columns=["date", "ticker"])
    g["date"] = pd.to_datetime(g["date"])
    return g.drop_duplicates()


@lru_cache(maxsize=1)
def _flags() -> pd.DataFrame:
    """(date, ticker) -> trend_ok, breakout_ok from t3 — the funnel tiers."""
    from src import db
    con = db.connect(str(ROOT / "data/market_data.duckdb"), read_only=True)
    f = con.execute(
        "SELECT date, ticker, trend_ok, breakout_ok FROM t3_sepa_features").df()
    con.close()
    f["date"] = pd.to_datetime(f["date"])
    return f


def load_gated_panel(years: tuple[int, ...] | None = None,
                     gate: str = "breakout") -> pd.DataFrame:
    """Full-universe rich panel at one funnel tier.

    gate:
      "full"     — every scored row (the whole trend-active universe as scored).
      "trend"    — trend_ok=True only (Minervini's watchlist tier).
      "breakout" — trend_ok AND breakout_ok (genuine breakouts; the DEFAULT, the
                   audited population every other section uses).

    Rows carry whatever feature columns that year's parquet had. `sector`/`industry`/
    `fwd150`/`fwd200` are covered ~100%; `rs`/`pe_ratio`/`mom_*` exist ONLY in the
    2025 file (~5%) — join those from t3 before grouping on them.
    """
    if gate == "breakout":
        key = _gated_keys()
        join = lambda df: df.merge(key, on=["date", "ticker"], how="inner")
    elif gate in ("full", "trend"):
        fl = _flags()
        def join(df):
            m = df.merge(fl, on=["date", "ticker"], how="left")
            return m[m["trend_ok"].fillna(False)] if gate == "trend" else m
    else:
        raise ValueError(f"gate must be full|trend|breakout, got {gate!r}")

    frames = []
    for fp in sorted(MULTIYEAR.glob("raw_full_*_fwd.parquet")):
        yr = int(fp.stem.split("_")[2])
        if years and yr not in years:
            continue
        df = pd.read_parquet(fp)          # full schema; varies by year
        df["date"] = pd.to_datetime(df["date"])
        frames.append(join(df))
    panel = pd.concat(frames, ignore_index=True)
    panel = panel.sort_values(["date", "prob_elite"], ascending=[True, False])
    return panel.reset_index(drop=True)


def top_n_per_day(panel: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    """That day's top-N genuine breakouts by prob_elite (panel is pre-sorted)."""
    return panel.groupby("date", group_keys=False).head(n)


if __name__ == "__main__":
    # SMOKE: verify the join lands and the gated pop is the tiny slice we expect.
    p = load_gated_panel((2008, 2020, 2025))
    assert len(p) > 0 and {"date", "ticker", "prob_elite"} <= set(p.columns)
    for yr in (2008, 2020, 2025):
        sub = p[p.date.dt.year == yr]
        print(f"{yr}: {len(sub):>6} breakout rows, {sub.date.nunique():>4} days, "
              f"{len(sub) / max(sub.date.nunique(), 1):.1f} bko/day, "
              f"sector-cov {sub['sector'].notna().mean():.0%}" if "sector" in sub else f"{yr}: no sector col")
    t5 = top_n_per_day(p, 5)
    assert (t5.groupby("date").size() <= 5).all(), "top-5 leaked >5/day"
    print(f"[OK] gated panel smoke: {len(p)} rows, top-5 {len(t5)} rows")
