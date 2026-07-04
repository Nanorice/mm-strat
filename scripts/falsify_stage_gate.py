"""Phase 3 falsification test for the Minervini stage gate.

The claim under test: an explicit stage gate removes trades that have worse forward returns.
Forward return is the ground truth (no external stage label exists). We measure it across the
two real dashboard populations:

    A = trend_ok AND NOT breakout_ok        (pre-breakout uptrend watchlist)
    B = SEPA watchlist session rows          (post-breakout, held names that can decay)

A is ~monolithically Stage 2 (trend_ok pins it) — reported to CONFIRM the classifier, not to
gate. The real falsification is on B: within held names, do rows that have decayed to Stage 3/4
have materially worse 5/20/60d forward returns than rows still in Stage 2? If not, the gate is
theatre — kill it (or collapse 1<->3 if only that pair fails).

Forward returns come from price_data (continuous panel) via LEAD with an adjacency guard —
NEVER shift(-1) on t3 (active/inactive holes book a months-long move as one bar). Stage inputs
(trend_ok, slope_63d, prior_slope_sign) are all trailing, so market_stage at date t is
tradeable — no look-ahead into the gate.

Timing caveat (surfaced, not hidden): Stage 3 requires NOT trend_ok, but a freshly-topping name
often still passes trend_ok for a while. So the gate catches CONFIRMED tops (template broken),
not early tops. The test measures the gate as built.

Usage:
    python -m scripts.falsify_stage_gate --sample 300     # smoke test (default)
    python -m scripts.falsify_stage_gate --all            # full watchlist universe
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from src import db
from src.features.trend_segments import compute_trend_segments, compute_market_stage

DB_PATH = "data/market_data.duckdb"
HORIZONS = [5, 20, 60]
START = "2018-01-01"
CACHE = Path("docs/session_logs/sprint_13/stage_gate_panel.parquet")
# columns kept for re-analysis (drop the raw price path / pivots — not needed downstream)
CACHE_COLS = ["ticker", "date", "trend_ok", "breakout_ok", "breakout", "in_watchlist",
              "market_stage", "slope_63d", "slope_r2_63d", "prior_slope_sign",
              *[f"fwd_ret_{h}d" for h in HORIZONS]]


def load_panel(tickers: list[str] | None) -> pd.DataFrame:
    """Daily panel: price path + trend_ok/breakout from t3 + forward returns + watchlist span.

    Forward returns use LEAD over price_data with an adjacency guard: null the return if the
    LEAD row is more than ~1.6*h calendar days ahead (a hole), so a held name never books a
    stale jump across an inactive stretch.
    """
    con = db.connect(DB_PATH, read_only=True)
    try:
        tfilter = ""
        if tickers is not None:
            placeholders = ",".join(f"'{t}'" for t in tickers)
            tfilter = f"AND p.ticker IN ({placeholders})"

        # forward-return columns with adjacency guard, computed per horizon
        fwd_cols = []
        for h in HORIZONS:
            fwd_cols.append(f"""
                CASE WHEN datediff('day', p.date, LEAD(p.date, {h}) OVER w) <= {int(h * 1.6)}
                     THEN LEAD(p.close, {h}) OVER w / NULLIF(p.close, 0) - 1
                     ELSE NULL END AS fwd_ret_{h}d""")

        df = con.execute(f"""
            WITH panel AS (
                SELECT
                    p.ticker, p.date, p.close,
                    f.atr_14, f.trend_ok, f.breakout_ok, f.breakout,
                    {",".join(fwd_cols)}
                FROM price_data p
                LEFT JOIN t3_sepa_features f
                    ON p.ticker = f.ticker AND p.date = f.date
                WHERE p.date >= '{START}' {tfilter}
                WINDOW w AS (PARTITION BY p.ticker ORDER BY p.date)
            )
            SELECT panel.*,
                   -- in a watchlist session span on this date => population B
                   (w.ticker IS NOT NULL) AS in_watchlist
            FROM panel
            LEFT JOIN sepa_watchlist w
                ON panel.ticker = w.ticker
               AND panel.date >= w.entry_date
               AND panel.date <= COALESCE(w.exit_date, DATE '2100-01-01')
            ORDER BY panel.ticker, panel.date
        """).df()
    finally:
        con.close()
    return df


def _fwd_summary(g: pd.DataFrame) -> pd.Series:
    out = {"n": len(g)}
    for h in HORIZONS:
        col = f"fwd_ret_{h}d"
        v = g[col].dropna()
        out[f"mean_{h}d"] = v.mean()
        out[f"med_{h}d"] = v.median()
        out[f"win_{h}d"] = (v > 0).mean() if len(v) else np.nan
    return pd.Series(out)


def report(df: pd.DataFrame) -> None:
    df = df.dropna(subset=["market_stage"])

    print("\n" + "=" * 70)
    print("POPULATION A — trend_ok AND NOT breakout_ok (should be ~all Stage 2)")
    print("=" * 70)
    a = df[(df["trend_ok"] == True) & (df["breakout_ok"] != True)]  # noqa: E712
    print(a["market_stage"].value_counts(normalize=True).sort_index().round(3).to_string())
    print(f"(confirms classifier: trend_ok pins Stage 2. n={len(a):,})")

    print("\n" + "=" * 70)
    print("POPULATION B — SEPA watchlist rows, forward return by stage (THE TEST)")
    print("=" * 70)
    b = df[df["in_watchlist"] == True]  # noqa: E712
    if b.empty:
        print("no watchlist rows in sample — rerun with more tickers or --all.")
        return
    summary = b.groupby("market_stage").apply(_fwd_summary, include_groups=False)
    with pd.option_context("display.width", 200, "display.max_columns", 20):
        print(summary.round(4).to_string())

    print("\n--- VERDICT CHECK: Stage 2 vs Stage 3/4 forward return (want 2 > 3,4) ---")
    for h in HORIZONS:
        col = f"fwd_ret_{h}d"
        s2 = b.loc[b["market_stage"] == 2, col].dropna()
        s34 = b.loc[b["market_stage"].isin([3, 4]), col].dropna()
        if len(s2) and len(s34):
            spread = s2.mean() - s34.mean()
            print(f"  {h:>2}d: Stage2 mean={s2.mean():+.4f}  Stage3/4 mean={s34.mean():+.4f}  "
                  f"spread={spread:+.4f}  {'GATE HELPS' if spread > 0 else 'NO EDGE'}")

    print("\n--- Stage 1 vs 3 (the weak seam): do they separate on forward return? ---")
    for h in HORIZONS:
        col = f"fwd_ret_{h}d"
        s1 = b.loc[b["market_stage"] == 1, col].dropna()
        s3 = b.loc[b["market_stage"] == 3, col].dropna()
        if len(s1) and len(s3):
            print(f"  {h:>2}d: Stage1 mean={s1.mean():+.4f} (n={len(s1)})  "
                  f"Stage3 mean={s3.mean():+.4f} (n={len(s3)})  "
                  f"{'DISTINCT' if abs(s1.mean() - s3.mean()) > 0.005 else 'INDISTINCT -> consider collapse'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--sample", type=int, default=300, help="N random watchlist tickers (smoke test)")
    g.add_argument("--all", action="store_true", help="full watchlist universe")
    g.add_argument("--from-cache", action="store_true", help="re-report from cached panel, no recompute")
    args = ap.parse_args()

    if args.from_cache:
        if not CACHE.exists():
            print(f"no cache at {CACHE} — run --all first.")
            return
        res = pd.read_parquet(CACHE)
        print(f"[cache] {len(res):,} rows from {CACHE}")
        report(res)
        return

    con = db.connect(DB_PATH, read_only=True)
    wl_tickers = [r[0] for r in con.execute(
        "SELECT DISTINCT ticker FROM sepa_watchlist ORDER BY ticker"
    ).fetchall()]
    con.close()

    if args.all:
        tickers = None
        print(f"[full] {len(wl_tickers):,} watchlist tickers")
    else:
        rng = np.random.default_rng(42)
        tickers = list(rng.choice(wl_tickers, size=min(args.sample, len(wl_tickers)), replace=False))
        print(f"[sample] {len(tickers)} of {len(wl_tickers):,} watchlist tickers (seed=42)")

    df = load_panel(tickers)
    print(f"loaded {len(df):,} panel rows; computing stages...", flush=True)
    res = compute_trend_segments(df)
    res["market_stage"] = compute_market_stage(res)

    if args.all:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        res[CACHE_COLS].to_parquet(CACHE, index=False)
        print(f"cached {len(res):,} rows -> {CACHE}", flush=True)

    report(res)


if __name__ == "__main__":
    main()
