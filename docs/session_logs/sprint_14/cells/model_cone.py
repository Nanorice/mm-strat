"""4-class vs binary bake-off — start-date cone × threshold sweep, honest Sharpe.

Q1 (user 2026-07-13): is the deployed 4-class m01_prototype actually better, given the
champion was picked without threshold adjustment? Two axes:
  (A) model representation — 4-class prob_class_3 vs binary P(pos) vs no-macro variants,
      ranked on shared strategy infra by bar-by-bar Sharpe (NOT label lift — memory:
      population_reframe_tail_ranker, label lift != trade edge).
  (B) threshold sensitivity — sweep min_prob_elite PER MODEL (within-model; absolute
      thresholds aren't comparable ACROSS models since 4-class prob_class_3 and binary
      P(pos) live on different scales).

Cone not a point (memory: champion_starttime_dependent — edge is a regime ride).
Score each model ONCE via score_from_t3 (prototype v2 is now t3-loadable, full history),
then reuse across the grid.
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np, pandas as pd

REPO = Path(r"c:/Users/Hang/PycharmProjects/quantamental")
sys.path.insert(0, str(REPO))

from src.backtest.universe_scorer import UniverseScorer
from src.backtest.vectorized_backtest import VectorizedSEPABacktest


def retry_locked(fn, *a, tries: int = 30, wait: float = 10.0, **kw):
    """Retry a read-only DB call through TRANSIENT locks from the box's live writer
    (the user's concurrent dashboard/pipeline periodically opens the DB read-write).
    Bounded — re-raises non-lock errors immediately and gives up after tries*wait."""
    import time as _t
    for i in range(tries):
        try:
            return fn(*a, **kw)
        except Exception as e:
            if "already open" not in str(e) and "being used by another" not in str(e) \
               and "正在使用" not in str(e):
                raise
            if i == tries - 1:
                raise
            _t.sleep(wait)

MODELS = {
    "prototype_4cls":    str(REPO / "models/m01_prototype_2003_2026/v2/model.json"),
    "binary":            str(REPO / "models/m01_binary/v1/model.json"),
    "binary_no_macro":   str(REPO / "models/m01_binary_no_macro/v1/model.json"),
    "no_macro_4cls":     str(REPO / "models/m01_no_macro/v1/model.json"),
}
COMMON = dict(max_positions_per_day=3, ranking_lookback_days=10,
              stop_loss_pct=0.10, sma_exit_period=50, max_hold_days=252)

FULL_START, FULL_END = "2004-01-01", "2026-06-30"
# Cone start dates: every ~18 months across 22yrs → 15 folds, each held to FULL_END.
STARTS = pd.date_range("2004-01-01", "2022-06-30", freq="18MS").strftime("%Y-%m-%d").tolist()
THRESHOLDS = [0.0, 0.10, 0.15, 0.20, 0.25, 0.30]


def cone_stats(sharpes: list[float]) -> dict:
    a = np.array([s for s in sharpes if np.isfinite(s)])
    if len(a) == 0:
        return dict(n=0, median=np.nan, floor=np.nan, p25=np.nan, pct_neg=np.nan)
    return dict(n=len(a), median=np.median(a), floor=a.min(),
                p25=np.percentile(a, 25), pct_neg=float((a < 0).mean()))


def main():
    t0 = time.time()
    # 1) score each model over history in YEARLY CHUNKS (full-panel single query OOMs the
    #    5.5GiB DuckDB limit — memory: large_dataset_queries). Keep only breakout_ok rows:
    #    the engine's SEPA gate discards the rest anyway, and this shrinks the retained
    #    frame ~28× (49k vs 1.4M) so all 4 models fit in memory at once.
    keep = ["date", "ticker", "prob_elite", "calibrated_score", "trend_ok", "breakout_ok"]
    years = pd.date_range(FULL_START, FULL_END, freq="YS").strftime("%Y").tolist()
    scores = {}
    for name, path in MODELS.items():
        s = UniverseScorer(m01_path=path, calibration_path=None)
        parts = []
        for y in years:
            df = retry_locked(s.score_from_t3, f"{y}-01-01", f"{y}-12-31",
                              ranking_lookback_days=COMMON["ranking_lookback_days"])
            parts.append(df.loc[df["breakout_ok"].astype(bool), keep])
        sc = pd.concat(parts, ignore_index=True)
        assert {"trend_ok", "breakout_ok"} <= set(sc.columns), "SEPA gate cols dropped!"
        scores[name] = sc
        print(f"[scored] {name:18s} breakout_rows={len(sc):>7,}  prob_elite p50={sc['prob_elite'].median():.3f} "
              f"p90={sc['prob_elite'].quantile(.9):.3f}", flush=True)

    # 1b) Load the FULL price panel ONCE (all tickers any model ever holds), pass it to
    #     every backtest via precomputed_prices. Avoids 360 reconnects (which raced the
    #     nightly writer → DB lock) and is far faster. memory: notebook_readonly_duckdb.
    from src import db as _db
    all_tk = sorted(set().union(*[set(scores[n]["ticker"]) for n in MODELS]))

    def _load_prices():
        con = _db.connect(str(REPO / "data/market_data.duckdb"), read_only=True)
        try:
            return con.execute(
                "SELECT ticker, date, open, high, low, close FROM price_data "
                "WHERE ticker = ANY(?) AND date >= ? AND date <= ? ORDER BY ticker, date",
                [all_tk, FULL_START, FULL_END],
            ).fetchdf()
        finally:
            con.close()
    prices = retry_locked(_load_prices)
    prices["date"] = pd.to_datetime(prices["date"])
    print(f"[prices] {len(prices):,} rows, {prices['ticker'].nunique():,} tickers loaded once", flush=True)

    # 2) cone × threshold sweep. Score once, prices once, re-run engine per (start, threshold).
    rows = []
    for name in MODELS:
        for thr in THRESHOLDS:
            sharpes = []
            for st in STARTS:
                sc = scores[name][scores[name]["date"] >= pd.Timestamp(st)]
                vbt = VectorizedSEPABacktest(
                    model_path=MODELS[name], start_date=st, end_date=FULL_END,
                    precomputed_scores=sc, precomputed_prices=prices,
                    min_prob_elite=thr, **COMMON,
                )
                tr = vbt.run()
                m = vbt.metrics(tr)
                sharpes.append(m["sharpe"])
            cs = cone_stats(sharpes)
            cs.update(model=name, thr=thr)
            rows.append(cs)
            print(f"  {name:18s} thr={thr:.2f}  median={cs['median']:.2f} "
                  f"floor={cs['floor']:.2f} p25={cs['p25']:.2f} %neg={cs['pct_neg']*100:.0f}%  "
                  f"(n={cs['n']})", flush=True)

    res = pd.DataFrame(rows)
    out = Path(__file__).parent / "model_cone_results.csv"
    res.to_csv(out, index=False)
    print(f"\nsaved {out}  ({time.time()-t0:.0f}s, {len(STARTS)} folds × {len(THRESHOLDS)} thr × {len(MODELS)} models)")

    # headline: threshold-free (thr=0.0 = pure top-3 rank) cross-model comparison
    print("\n=== THRESHOLD-FREE (thr=0.0, top-3/day rank) — cross-model, apples-to-apples ===")
    base = res[res["thr"] == 0.0].set_index("model")[["median", "floor", "p25", "pct_neg"]]
    print(base.sort_values("median", ascending=False).to_string())

    # per-model: does raising the gate help ITS OWN cone?
    print("\n=== PER-MODEL threshold sweep (best-median thr in bold-equivalent) ===")
    for name in MODELS:
        sub = res[res["model"] == name].sort_values("thr")
        best = sub.loc[sub["median"].idxmax()]
        print(f"{name:18s} best median @thr={best['thr']:.2f} ({best['median']:.2f}); "
              f"thr0={sub[sub.thr==0.0]['median'].iloc[0]:.2f} → "
              f"thr.15={sub[sub.thr==0.15]['median'].iloc[0]:.2f} → "
              f"thr.30={sub[sub.thr==0.30]['median'].iloc[0]:.2f}")


if __name__ == "__main__":
    main()
