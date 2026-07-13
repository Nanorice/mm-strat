"""Attribute-sliced basket equity fans (sprint-14 §8).

Reuses the validated §5 lottery engine's per-name path (`_name_path`) but lets you
(a) sweep the score gate and (b) slice the breakout pool by a categorical/quantile
attribute (sector, industry, market-cap bucket, RS band) BEFORE picking the daily
top-N — so you can see whose equity fan drives the edge.

One shared loader joins the score cache to entry-day attributes (company_profiles for
static sector/industry/market_cap, t3 for time-varying RS ranks) once; every fan reuses
it. Prices loaded once. Keeps the notebook cells thin.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
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

from src import db
from start_day_basket_paths import _name_path  # reuse the validated per-name path

DB_PATH = ROOT / "data/market_data.duckdb"


# ── attribute enrichment ──────────────────────────────────────────────────────
def enrich(scores: pd.DataFrame) -> pd.DataFrame:
    """Attach entry-day attributes to a (date,ticker,prob_elite) score frame.

    sector/industry/market_cap are static per ticker (company_profiles); RS ranks are
    time-varying (t3). market_cap → a 5-bucket label; RS → 5-band label. LEFT joins so a
    name with no profile still survives (its bucket = 'unknown')."""
    scores = scores.copy()
    scores["date"] = pd.to_datetime(scores["date"])
    con = db.connect(str(DB_PATH), read_only=True)
    try:
        prof = con.execute(
            "SELECT ticker, sector, industry, market_cap FROM company_profiles"
        ).df()
        # time-varying RS on the (date,ticker) grain, only for rows we hold
        tks = scores["ticker"].unique().tolist()
        rs = con.execute(
            'SELECT date, ticker, "RS_Universe_Rank" AS rs_universe '
            "FROM t3_sepa_features WHERE ticker = ANY(?)",
            [tks],
        ).df()
    finally:
        con.close()
    rs["date"] = pd.to_datetime(rs["date"])

    out = scores.merge(prof, on="ticker", how="left").merge(
        rs, on=["date", "ticker"], how="left"
    )
    # buckets. qcut on market_cap (log-spaced naturally); RS is already 0..1 → fixed bands.
    out["mcap_bucket"] = pd.qcut(
        out["market_cap"], 5, labels=["micro", "small", "mid", "large", "mega"],
        duplicates="drop",
    ).astype(str)
    out["rs_band"] = pd.cut(
        out["rs_universe"], [0, 0.2, 0.4, 0.6, 0.8, 1.0],
        labels=["rs0-20", "rs20-40", "rs40-60", "rs60-80", "rs80-100"],
    ).astype(str)
    return out


# ── price panel (once) ────────────────────────────────────────────────────────
def load_prices(tickers: list[str]) -> dict:
    con = db.connect(str(DB_PATH), read_only=True)
    try:
        px = con.execute(
            "SELECT ticker, date, close FROM price_data WHERE ticker = ANY(?)", [tickers]
        ).df()
    finally:
        con.close()
    px["date"] = pd.to_datetime(px["date"])
    px = px.sort_values(["ticker", "date"])
    return {t: (g["date"].to_numpy(), g["close"].to_numpy()) for t, g in px.groupby("ticker")}


# ── the fan ───────────────────────────────────────────────────────────────────
def basket_fan(
    scores: pd.DataFrame,
    by_tkr: dict,
    top_n: int | None = None,
    horizon: int = 150,
    sl_pct: float = 0.15,
    sample_every: int = 5,
    min_score: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (paths, final_returns%) for the per-day baskets in `scores`.

    top_n=None (default) → hold EVERY gate-survivor that day (equal-weight), isolating the
    SCORING question from top-N selection. top_n=k → keep the k highest-score names.
    `scores` is assumed ALREADY sliced to the attribute of interest (caller filters).
    Equal-weight basket per start-day; a start-day with no eligible name is skipped."""
    if min_score is not None:
        scores = scores[scores["prob_elite"] >= min_score]
    start_days = np.sort(scores["date"].unique())[::sample_every]
    paths = []
    for d in start_days:
        d = pd.Timestamp(d)
        day = scores.loc[scores["date"] == d]
        day_top = (day if top_n is None else day.nlargest(top_n, "prob_elite"))["ticker"]
        curves = []
        for t in day_top:
            if t not in by_tkr:
                continue
            dts, cls = by_tkr[t]
            j = np.searchsorted(dts, d)
            if j >= len(dts) or dts[j] != d:
                continue
            fwd = cls[j : j + horizon + 1]
            if len(fwd) < 2:
                continue
            curves.append(_name_path(fwd, sl_pct, None, horizon))
        if curves:
            paths.append(np.mean(np.vstack(curves), axis=0))
    if not paths:
        return np.empty((0, horizon + 1)), np.empty(0)
    P = np.vstack(paths)
    return P, (P[:, -1] - 1) * 100


def fan_stats(final_pct: np.ndarray) -> dict:
    if len(final_pct) == 0:
        return dict(n=0, median=np.nan, p10=np.nan, p90=np.nan, loss=np.nan)
    return dict(
        n=len(final_pct), median=float(np.median(final_pct)),
        p10=float(np.percentile(final_pct, 10)), p90=float(np.percentile(final_pct, 90)),
        loss=float((final_pct < 0).mean()),
    )


if __name__ == "__main__":
    # self-check: raw vs calibrated distinct-value count + a one-slice fan smoke.
    cache = ROOT / "data/score_cache/m01_binary_calibrated_2003-01-01_2026-05-22_sepa_gated.parquet"
    sc = enrich(pd.read_parquet(cache))
    assert {"sector", "mcap_bucket", "rs_band"} <= set(sc.columns), "enrich lost cols"
    assert sc["mcap_bucket"].nunique() >= 3, "mcap buckets collapsed"
    by = load_prices(sc["ticker"].unique().tolist())
    tech = sc[sc["sector"] == "Technology"]
    P, fin = basket_fan(tech, by, sample_every=10)
    st = fan_stats(fin)
    assert st["n"] > 0, "tech fan empty"
    print(f"[selfcheck] enrich OK; Technology fan n={st['n']} median={st['median']:+.1f}% "
          f"p10..p90={st['p10']:.0f}..{st['p90']:.0f}%")
