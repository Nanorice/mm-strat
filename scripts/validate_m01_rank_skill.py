"""
m01_rank skill validation — is the model good at what it's DESIGNED to do?

Before wiring m01_rank into execution, confirm its core skill: predicting
short-horizon forward performance on a name that is already a SEPA breakout
candidate. This is a score-vs-return analysis, NOT a portfolio backtest.

Metric A — per-ticker forward-return IC (the timing skill):
  For each horizon H in {5,10,20}, Spearman corr of m01_rank score vs the
  realized H-day forward return, computed WITHIN each ticker's history and
  averaged equally across tickers (Phase 1 showed pooled IC is row-count
  inflated). Plus top/bottom-decile mean forward return (monotonicity).

Metric B — breakout-day pullback detection (the 'delay entry' use case):
  On breakout_ok days only, bucket by m01_rank score quintile and measure the
  near-term forward DRAWDOWN (min close over next H days vs entry). If a LOW
  score predicts a deeper pullback, m01_rank can justify delaying entry.

Returns from price_data.close with an adjacency guard (t3 shift would book
multi-week moves as 1-day; adj_close is 100% NULL so close is used, split
artifacts clipped). Leakage-clean: m01_rank trained on <train_end, evaluated
on the OOS window.

Usage:
    python scripts/validate_m01_rank_skill.py --train-end 2020-01-01 \
        --start 2020-01-01 --end 2024-12-31 --horizon-train 20 --thr-train 0.20
"""

import argparse
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from scripts.m01_rank_scorer import train_and_score

DB_PATH = str(config.DATA_DIR / "market_data.duckdb")
HORIZONS = (5, 10, 20)
RET_CLIP = {1: 0.25, 5: 0.50, 10: 1.0, 20: 2.0}  # blunt split-artifact guard per horizon


def fwd_returns_and_drawdown(start: str, end: str, horizons=HORIZONS) -> pd.DataFrame:
    """Per (ticker, date): H-day forward return + H-day forward max-drawdown,
    from the continuous price_data panel with an adjacency guard.

    fwd_ret_H  = close[t+H]/close[t] - 1, only if t+H is within ~2.5*H cal days.
    fwd_dd_H   = min(close[t+1..t+H])/close[t] - 1  (the worst pullback over the
                 next H sessions; <= 0). Captures 'how much did it dip first'.
    """
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        px = con.execute(
            'SELECT ticker, date, CAST(close AS DOUBLE) AS close FROM price_data '
            'WHERE date >= ? AND date <= ? ORDER BY ticker, date',
            [start, (pd.Timestamp(end) + pd.Timedelta(days=max(horizons) * 3)).strftime("%Y-%m-%d")],
        ).df()
    finally:
        con.close()
    px["date"] = pd.to_datetime(px["date"])

    out = []
    for tkr, g in px.groupby("ticker", sort=False):
        g = g.sort_values("date").reset_index(drop=True)
        c = g["close"].to_numpy(dtype=float)
        d = g["date"].to_numpy()
        n = len(g)
        rec = {"ticker": tkr, "date": g["date"]}
        for H in horizons:
            # Forward return: close shifted -H, with adjacency guard on the date gap.
            fwd_c = np.full(n, np.nan)
            fwd_dd = np.full(n, np.nan)
            if n > H:
                idx = np.arange(n - H)
                jdx = idx + H
                gap = (d[jdx] - d[idx]) / np.timedelta64(1, "D")
                ok = (gap <= H * 2.5) & (c[idx] > 0)
                ret = np.where(ok, c[jdx] / c[idx] - 1.0, np.nan)
                fwd_c[idx] = ret
                # Forward min over the next H sessions: reverse-rolling min.
                # min of c[i+1 .. i+H] for each i.
                fwd_min = np.full(n, np.nan)
                # sliding window minimum via pandas rolling on reversed array
                s = pd.Series(c)
                # rolling(H) min looking BACKWARD on reversed series = forward min
                rev_min = s[::-1].rolling(H, min_periods=1).min()[::-1].to_numpy()
                # rev_min[i] = min(c[i .. i+H-1]); we want min(c[i+1 .. i+H])
                fwd_min[: n - 1] = rev_min[1:]  # min(c[i+1 .. i+H])
                with np.errstate(invalid="ignore"):
                    dd = np.where((c > 0), fwd_min / c - 1.0, np.nan)
                # A pullback is the worst dip BELOW entry over the next H days;
                # if the name never closed below entry, pullback = 0 (not positive).
                dd = np.minimum(dd, 0.0)
                dd[idx] = np.where(ok, dd[idx], np.nan)
                dd[n - H:] = np.nan  # no full forward window
                fwd_dd = dd
            clip = RET_CLIP[H]
            fwd_c[np.abs(fwd_c) > clip] = np.nan
            rec[f"fwd_ret_{H}"] = fwd_c
            rec[f"fwd_dd_{H}"] = fwd_dd
        out.append(pd.DataFrame(rec))
    res = pd.concat(out, ignore_index=True)
    return res


def metric_a_per_ticker_ic(merged: pd.DataFrame, min_obs=30) -> pd.DataFrame:
    """Per-ticker Spearman IC of m01_rank_prob vs fwd_ret_H, averaged across tickers."""
    rows = []
    for H in HORIZONS:
        col = f"fwd_ret_{H}"
        ics = []
        for _, g in merged.groupby("ticker"):
            s = g[["m01_rank_prob", col]].replace([np.inf, -np.inf], np.nan).dropna()
            if len(s) >= min_obs and s["m01_rank_prob"].nunique() > 1:
                ic = stats.spearmanr(s["m01_rank_prob"], s[col]).correlation
                if not np.isnan(ic):
                    ics.append(ic)
        ics = np.array(ics)
        # Pooled IC for contrast (Phase 1: pooled inflates).
        sp = merged[["m01_rank_prob", col]].replace([np.inf, -np.inf], np.nan).dropna()
        pooled = stats.spearmanr(sp["m01_rank_prob"], sp[col]).correlation if len(sp) > 100 else np.nan
        rows.append({
            "horizon": H,
            "ic_ticker_mean": float(np.mean(ics)) if len(ics) else np.nan,
            "ic_ticker_median": float(np.median(ics)) if len(ics) else np.nan,
            "pct_tickers_positive": float((ics > 0).mean()) if len(ics) else np.nan,
            "n_tickers": len(ics),
            "ic_pooled": float(pooled),
        })
    return pd.DataFrame(rows)


def metric_a_deciles(merged: pd.DataFrame) -> pd.DataFrame:
    """Mean forward return by m01_rank daily-percentile decile (monotonicity check)."""
    m = merged.copy()
    m["decile"] = (m["m01_rank_pct"] * 10).clip(0, 9.999).astype(int)
    rows = []
    for H in HORIZONS:
        col = f"fwd_ret_{H}"
        g = m.dropna(subset=[col]).groupby("decile")[col].mean()
        spread = g.get(9, np.nan) - g.get(0, np.nan)
        rows.append({"horizon": H, "d0_bottom": g.get(0, np.nan),
                     "d9_top": g.get(9, np.nan), "top_minus_bottom": spread,
                     "monotone_up": bool(g.is_monotonic_increasing)})
    return pd.DataFrame(rows)


def metric_b_breakout_pullback(merged: pd.DataFrame) -> pd.DataFrame:
    """On breakout days: forward drawdown by m01_rank score quintile.

    The 'delay entry' thesis: a LOW m01_rank score at breakout should predict a
    DEEPER near-term pullback (more negative fwd_dd). If quintile 1 (lowest
    score) has materially worse fwd_dd than quintile 5, delaying entry on low
    scores avoids drawdown.
    """
    bo = merged[merged["breakout_ok"] == True].copy()
    if bo.empty:
        return pd.DataFrame()
    bo["quintile"] = pd.qcut(bo["m01_rank_prob"].rank(method="first"), 5,
                             labels=[1, 2, 3, 4, 5])
    rows = []
    for H in HORIZONS:
        agg = bo.groupby("quintile", observed=True).agg(
            fwd_dd_mean=(f"fwd_dd_{H}", "mean"),
            fwd_ret_mean=(f"fwd_ret_{H}", "mean"),
            n=(f"fwd_dd_{H}", "size"),
        ).reset_index()
        agg["horizon"] = H
        rows.append(agg)
    return pd.concat(rows, ignore_index=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-end", default="2020-01-01")
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--horizon-train", type=int, default=20,
                    help="target horizon the m01_rank classifier is trained on")
    ap.add_argument("--thr-train", type=float, default=0.20)
    args = ap.parse_args()

    print(f"Training m01_rank (target H={args.horizon_train}, thr={args.thr_train}) "
          f"on <{args.train_end}; scoring {args.start}..{args.end} OOS")
    scored, _, _ = train_and_score(
        train_end=args.train_end, score_start=args.start, score_end=args.end,
        horizon=args.horizon_train, threshold=args.thr_train,
    )
    print(f"  scored {len(scored):,} rows / {scored['ticker'].nunique()} tickers")

    # breakout flag for metric B
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        bo = con.execute(
            "SELECT ticker, date, breakout_ok FROM t3_sepa_features "
            "WHERE feature_version='v3.1' AND date >= ? AND date <= ?",
            [args.start, args.end],
        ).df()
    finally:
        con.close()
    bo["date"] = pd.to_datetime(bo["date"])
    scored = scored.merge(bo, on=["ticker", "date"], how="left")

    print("Computing forward returns + drawdowns from price_data (adjacency-guarded)...")
    fwd = fwd_returns_and_drawdown(args.start, args.end)
    merged = scored.merge(fwd, on=["ticker", "date"], how="inner")
    print(f"  merged {len(merged):,} (ticker,date) rows with forward returns")
    # Sanity: forward returns must be non-null with sane spread (handover lesson).
    for H in HORIZONS:
        s = merged[f"fwd_ret_{H}"]
        print(f"  fwd_ret_{H}: non-null={s.notna().sum():,} "
              f"min={s.min():.3f} median={s.median():.4f} max={s.max():.3f}")

    print("\n=== METRIC A: per-ticker forward-return IC (timing skill) ===")
    print(metric_a_per_ticker_ic(merged).to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\n--- decile monotonicity (mean fwd return by m01_rank decile) ---")
    print(metric_a_deciles(merged).to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    print("\n=== METRIC B: breakout-day pullback by m01_rank quintile ===")
    print("(thesis: low quintile -> deeper fwd_dd -> justifies delaying entry)")
    mb = metric_b_breakout_pullback(merged)
    if not mb.empty:
        print(mb.to_string(index=False, float_format=lambda x: f"{x:.4f}"))


if __name__ == "__main__":
    main()
