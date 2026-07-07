"""Entry-timing EDA: what distinguishes the BEST vs WORST dates to deploy the top-5?

NOT a backtest. Collapses the 25y cache to a per-day top-5 outcome, scored across a
HORIZON GRID (fwd 20/50/100d — SEPA holds longer than 20d, so we ask: when a date is
weak at 20d, does it get a SECOND CHANCE at 50/100d, or is it dead across the board?).
Then correlates the outcome against entry-date FEATURES (M03 regime + pillars first;
SPY/QQQ/VIX wired but off by default — flip FEATURE_SETS to add them).

Outcome per day = mean fwd-return of that day's top-5 by prob_elite. fwd20 comes from
the cache; fwd50/fwd100 are computed close-to-close from price_data for JUST the top-5
names (tiny lookup, no re-scoring). Convention matches score_universe_multiyear.attach_fwd.

  python docs/session_logs/sprint_14/scripts/entry_timing_features.py
  python docs/session_logs/sprint_14/scripts/entry_timing_features.py --smoke   # 3 recent years
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import duckdb

ROOT = Path(__file__).resolve().parents[4]
CACHE = ROOT / "data" / "model_output_eda" / "multiyear"
DB = ROOT / "data" / "market_data.duckdb"
OUT = ROOT / "data" / "model_output_eda" / "entry_timing"

TOP_N = 5
HORIZONS = [20, 50, 100]          # trading days: ~1mo / ~2.5mo / ~5mo
TAIL_Q = 0.10                     # best/worst decile of dates


def _log(m: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


# --- outcome: per-day top-5, multi-horizon fwd return ------------------------

def top5_per_day(years: list[int] | None) -> pd.DataFrame:
    """One row per (date, ticker) for the top-5 names/day, from the cache."""
    frames = []
    for fp in sorted(CACHE.glob("raw_full_*_fwd.parquet")):
        yr = int(fp.stem.split("_")[2])
        if years and yr not in years:
            continue
        df = pd.read_parquet(fp, columns=["date", "ticker", "prob_elite", "fwd20"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values(["date", "prob_elite"], ascending=[True, False])
        df = df.groupby("date", group_keys=False).head(TOP_N)
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    _log(f"top-{TOP_N}/day: {out['date'].nunique()} days, {len(out)} rows")
    return out


def attach_horizons(top5: pd.DataFrame) -> pd.DataFrame:
    """Compute fwd50/fwd100 close-to-close for the top-5 names. fwd20 kept from cache.
    One price pull per ticker across the whole span (top-5 => few thousand tickers)."""
    extra = [h for h in HORIZONS if h != 20]
    tks = tuple(sorted(top5["ticker"].unique()))
    lo = (top5["date"].min() - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    hi = (top5["date"].max() + pd.Timedelta(days=max(HORIZONS) * 3 + 30)).strftime("%Y-%m-%d")
    con = duckdb.connect(str(DB), read_only=True)
    try:
        px = con.execute(
            "SELECT ticker,date,close FROM price_data WHERE ticker IN "
            f"{tks} AND date BETWEEN ? AND ? ORDER BY ticker,date", [lo, hi]).df()
    finally:
        con.close()
    px["date"] = pd.to_datetime(px["date"])
    pxg = {t: g.set_index("date")["close"] for t, g in px.groupby("ticker")}
    _log(f"loaded price for {len(pxg)} top-5 tickers")

    def fwd(ticker, d, h):
        s = pxg.get(ticker)
        if s is None:
            return np.nan
        s = s[s.index >= d]
        if len(s) <= h or s.iloc[0] == 0:
            return np.nan
        return s.iloc[h] / s.iloc[0] - 1

    for h in extra:
        top5[f"fwd{h}"] = [fwd(t, d, h) for t, d in zip(top5["ticker"], top5["date"])]
    return top5


def per_day_outcome(top5: pd.DataFrame) -> pd.DataFrame:
    """Collapse to one row/day: mean top-5 fwd return at each horizon."""
    cols = {f"fwd{h}": (f"fwd{h}", "mean") for h in HORIZONS}
    day = top5.groupby("date").agg(**cols).reset_index()
    return day


# --- features: M03 first, macro wired but off --------------------------------

def load_macro_pillars_raw() -> pd.DataFrame:
    """The dashboard's 6-pillar macro (dashboard_utils.load_macro_pillars), but RAW
    LEVELS only — the display percentiles use all-time/look-ahead rank and must NOT
    be a backtest/correlation feature (leakage). Same series & net-liq formula, daily
    ffill. CAPE_OURS only exists 2012+ so it's NaN before that (correlation drops NaN).
    """
    con = duckdb.connect(str(DB), read_only=True)
    try:
        df = con.execute("""
            SELECT date, symbol, close AS value FROM macro_data
            WHERE symbol IN ('VIX','BAMLH0A0HYM2','DGS10','DGS2','WALCL',
                             'WTREGEN','RRPONTSYD','CAPE_OURS')
        """).df()
    finally:
        con.close()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["date"] = pd.to_datetime(df["date"])
    w = df.drop_duplicates(["date", "symbol"]).pivot(index="date", columns="symbol",
                                                      values="value").sort_index().ffill()
    out = pd.DataFrame(index=w.index)
    out["pil_vix"] = w["VIX"]
    out["pil_credit"] = w["BAMLH0A0HYM2"]
    out["pil_term"] = w["DGS10"] - w["DGS2"]
    out["pil_rates"] = w["DGS10"]
    out["pil_liq"] = w["WALCL"] / 1000.0 - w.get("WTREGEN", 0).fillna(0) / 1000.0 \
        - w.get("RRPONTSYD", 0).fillna(0)
    out["pil_cape"] = w["CAPE_OURS"] if "CAPE_OURS" in w else np.nan
    return out.reset_index()


def attach_features(day: pd.DataFrame, use_macro: bool, use_pillars: bool) -> pd.DataFrame:
    con = duckdb.connect(str(DB), read_only=True)
    try:
        m03 = con.execute(
            "SELECT date, m03_score, m03_pillar_trend, m03_pillar_liq, m03_pillar_risk, "
            "m03_delta_5d, m03_delta_20d, m03_regime_vol FROM t2_regime_scores ORDER BY date").df()
        macro = con.execute(
            "SELECT date, spy_close, qqq_close, vix_close FROM t1_macro ORDER BY date").df()
    finally:
        con.close()
    m03["date"] = pd.to_datetime(m03["date"])
    day = day.merge(m03, on="date", how="inner")   # inner: M03 starts 2003-07

    if use_macro:
        macro["date"] = pd.to_datetime(macro["date"])
        for col, idx in [("spy", "spy_close"), ("qqq", "qqq_close")]:
            for wn in (20, 60, 120):
                macro[f"{col}_ret{wn}"] = macro[idx] / macro[idx].shift(wn) - 1
            macro[f"{col}_above200"] = (macro[idx] > macro[idx].rolling(200).mean()).astype(float)
        macro["vix_chg20"] = macro["vix_close"] - macro["vix_close"].shift(20)
        feat_cols = ["date", "vix_close", "vix_chg20"] + \
            [f"{c}_{s}" for c in ("spy", "qqq") for s in ("ret20", "ret60", "ret120", "above200")]
        day = day.merge(macro[feat_cols], on="date", how="left")

    if use_pillars:
        day = day.merge(load_macro_pillars_raw(), on="date", how="left")
        day = add_stress_score(day)
    return day


def _z_full(s: pd.Series) -> pd.Series:
    """Full-sample z — LOOK-AHEAD. EDA/reference only, never a live signal."""
    return (s - s.mean()) / s.std()


def _z_expanding(s: pd.Series, min_obs: int = 252) -> pd.Series:
    """Expanding-window z, LIVE-SAFE: day t uses only stats through t−1 (shift(1)).
    Warmup (< min_obs) → NaN. This is the honest version of the composite."""
    mu = s.expanding(min_periods=min_obs).mean().shift(1)
    sd = s.expanding(min_periods=min_obs).std().shift(1)
    return (s - mu) / sd


def _rank_expanding(s: pd.Series, min_obs: int = 252) -> pd.Series:
    """Expanding percentile rank (0..1), live-safe: t's rank among values ≤ t−1.
    Robust to the fat tails in credit spreads that a z-score over-weights."""
    def r(i: int) -> float:
        if i < min_obs:
            return np.nan
        hist = s.iloc[:i].dropna()          # strictly before t
        v = s.iloc[i]
        if not len(hist) or pd.isna(v):
            return np.nan
        return (hist < v).mean()
    return pd.Series([r(i) for i in range(len(s))], index=s.index)


def add_stress_score(day: pd.DataFrame) -> pd.DataFrame:
    """Build the stress composite several ways. Sign-aligned so HIGHER = more stress =
    the direction that predicted BETTER entries (Finding 2): +credit, −rates, −cape (+vix).
    Variants (all but *_full are LIVE-SAFE, expanding-window):
      stress_full        full-sample z of credit/rates/cape (the look-ahead reference)
      stress_ew          expanding-z of credit/rates/cape (honest version of the winner)
      stress_ew_vix      + VIX in the mix
      stress_ew_rank     expanding percentile-rank blend (fat-tail robust)
      stress_cr          expanding-z of credit+rates only (drops CAPE; full 25y coverage)
    """
    C, R, K, V = day["pil_credit"], day["pil_rates"], day["pil_cape"], day["pil_vix"]

    day["stress_full"] = pd.concat(
        [_z_full(C), -_z_full(R), -_z_full(K)], axis=1).mean(axis=1, skipna=True)
    day["stress_ew"] = pd.concat(
        [_z_expanding(C), -_z_expanding(R), -_z_expanding(K)], axis=1).mean(axis=1, skipna=True)
    day["stress_ew_vix"] = pd.concat(
        [_z_expanding(C), -_z_expanding(R), -_z_expanding(K), _z_expanding(V)],
        axis=1).mean(axis=1, skipna=True)
    day["stress_ew_rank"] = pd.concat(
        [_rank_expanding(C), 1 - _rank_expanding(R), 1 - _rank_expanding(K)],
        axis=1).mean(axis=1, skipna=True)
    day["stress_cr"] = pd.concat(
        [_z_expanding(C), -_z_expanding(R)], axis=1).mean(axis=1, skipna=True)
    return day


# --- analysis: correlation + best/worst-date profile -------------------------

FEATURE_COLS_M03 = ["m03_score", "m03_pillar_trend", "m03_pillar_liq", "m03_pillar_risk",
                    "m03_delta_5d", "m03_delta_20d", "m03_regime_vol"]


def report(day: pd.DataFrame) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    day.to_parquet(OUT / "entry_timing_daily.parquet", index=False)

    feats = [c for c in day.columns if c not in ["date"] + [f"fwd{h}" for h in HORIZONS]]
    lines = ["# Entry-timing feature EDA — best vs worst deploy dates", "",
             f"{len(day)} days, {day.date.dt.year.min()}–{day.date.dt.year.max()}. "
             f"Outcome = mean top-{TOP_N} fwd return per day. NOT a backtest.", ""]

    # 1) correlation of every feature with the outcome at each horizon
    lines += ["## Feature vs outcome correlation (Spearman)", "",
              "| feature | " + " | ".join(f"fwd{h}" for h in HORIZONS) + " |",
              "|---|" + "--:|" * len(HORIZONS)]
    for f in feats:
        cors = [day[f].corr(day[f"fwd{h}"], method="spearman") for h in HORIZONS]
        lines.append(f"| {f} | " + " | ".join(f"{c:+.3f}" for c in cors) + " |")

    # 2) best vs worst decile of DATES (by fwd20) — what do their features look like?
    lines += ["", f"## Best vs worst {int(TAIL_Q*100)}% of dates (ranked by fwd20)", "",
              "Mean feature value on the best- vs worst-outcome dates. A gap = that "
              "feature separates good entry timing.", "",
              "| feature | worst | best | delta(best-worst) |", "|---|--:|--:|--:|"]
    lo = day["fwd20"] <= day["fwd20"].quantile(TAIL_Q)
    hi = day["fwd20"] >= day["fwd20"].quantile(1 - TAIL_Q)
    for f in feats:
        w, b = day.loc[lo, f].mean(), day.loc[hi, f].mean()
        lines.append(f"| {f} | {w:+.2f} | {b:+.2f} | {b - w:+.2f} |")

    # 3) the SECOND-CHANCE question: dates weak@20d — do they recover at longer h?
    lines += ["", "## Second chance: weak@20d dates over longer horizons", "",
              "Dates in the worst-20d decile — their mean outcome as the horizon extends. "
              "Recovery => a bad 20d entry is tolerable if held; flat/worse => genuinely dead.", ""]
    worst20 = day[day["fwd20"] <= day["fwd20"].quantile(TAIL_Q)]
    lines += ["| horizon | worst-20d dates mean | all-dates mean | recovered? |",
              "|---|--:|--:|:--|"]
    for h in HORIZONS:
        wm, am = worst20[f"fwd{h}"].mean(), day[f"fwd{h}"].mean()
        tag = "[beats all]" if wm > am else ("[up vs 20d]" if wm > worst20["fwd20"].mean() else "[still dead]")
        lines.append(f"| fwd{h} | {wm:+.2%} | {am:+.2%} | {tag} |")

    STRESS_VARS = ["stress_full", "stress_ew", "stress_ew_vix", "stress_ew_rank", "stress_cr"]
    present = [v for v in STRESS_VARS if v in day.columns]

    # 4) composite variants — full-sample vs LIVE-SAFE, and which blend is best
    if present:
        lines += ["", "## Stress composite variants (option b): full vs live-safe", "",
                  "ρ(composite, outcome). `stress_full` = look-ahead reference. `*_ew`/`*_rank`/"
                  "`*_cr` are expanding-window (live-safe): day t uses only stats through t−1. The "
                  "honest number is the best `_ew*` row, NOT stress_full.", "",
                  "| composite | fwd20 | fwd50 | fwd100 | n(non-null) |", "|---|--:|--:|--:|--:|"]
        for f in present:
            cors = [day[f].corr(day[f"fwd{h}"], method="spearman") for h in HORIZONS]
            lines.append(f"| {f} | " + " | ".join(f"{c:+.3f}" for c in cors)
                         + f" | {day[f].notna().sum()} |")

    # 5) regime split (SPY>200d) on the live composite — bull-too or bear-only?
    if "spy_above200" in day.columns and present:
        best = present[1] if len(present) > 1 else present[0]  # prefer a live-safe one
        lines += ["", f"## Regime split on `{best}` (live-safe)", "",
                  "ρ on SPY-above-200d (bull) vs below (bear). Buy-the-dip => concentrates in bear.",
                  "", "| regime | fwd20 | fwd50 | fwd100 | n |", "|---|--:|--:|--:|--:|"]
        bull = day["spy_above200"] == 1
        for label, mask in [("bull", bull), ("bear", ~bull)]:
            sub = day[mask]
            cors = [sub[best].corr(sub[f"fwd{h}"], method="spearman") for h in HORIZONS]
            lines.append(f"| {label} | " + " | ".join(f"{c:+.3f}" for c in cors) + f" | {len(sub)} |")

    # 6) THE TILT: does deploying more when stress is high lift the outcome? (fwd100)
    #    Quintile monotonicity + a stress-weighted vs flat deployment on the outcome.
    if present:
        best = present[1] if len(present) > 1 else present[0]
        h = HORIZONS[-1]  # signal peaks at the long horizon → judge the tilt there
        d = day.dropna(subset=[best, f"fwd{h}"]).copy()
        lines += ["", f"## The deploy TILT — `{best}`, judged on fwd{h}", "",
                  f"Live composite bucketed into quintiles; mean fwd{h} per bucket. Monotone up "
                  "=> a usable deploy tilt (more capital when stress high). Then a stress-WEIGHTED "
                  "deployment (weight ∝ rank of the composite) vs FLAT, on the same dates.", "",
                  f"| stress quintile | mean fwd{h} | n |", "|---|--:|--:|"]
        d["q"] = pd.qcut(d[best], 5, labels=["Q1 low", "Q2", "Q3", "Q4", "Q5 high"], duplicates="drop")
        g = d.groupby("q", observed=True)[f"fwd{h}"].agg(["mean", "size"])
        for q, row in g.iterrows():
            lines.append(f"| {q} | {row['mean']:+.2%} | {int(row['size'])} |")
        # weighted vs flat: normalize the composite to a [0,1] deploy weight via its expanding rank
        w = d[best].rank(pct=True)  # EDA rank; live version uses _rank_expanding — same shape
        flat = d[f"fwd{h}"].mean()
        wtd = float((w * d[f"fwd{h}"]).sum() / w.sum())
        lines += ["", f"- FLAT deployment mean fwd{h}:     **{flat:+.2%}**",
                  f"- STRESS-WEIGHTED mean fwd{h}:     **{wtd:+.2%}**  "
                  f"(uplift {wtd - flat:+.2%})",
                  f"- Q5(high stress) − Q1(low): **{g['mean'].iloc[-1] - g['mean'].iloc[0]:+.2%}**"]

    path = OUT / "entry_timing_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    _log(f"wrote {path.relative_to(ROOT)}")
    print("\n".join(lines[:40]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="3 recent years only")
    ap.add_argument("--macro", action="store_true", help="also attach SPY/QQQ/VIX features")
    ap.add_argument("--pillars", action="store_true",
                    help="attach the dashboard's 6-macro-pillar levels (raw, no look-ahead)")
    args = ap.parse_args()
    years = [2023, 2024, 2025] if args.smoke else None

    top5 = top5_per_day(years)
    top5 = attach_horizons(top5)
    day = per_day_outcome(top5)
    day = attach_features(day, use_macro=args.macro, use_pillars=args.pillars)
    _log(f"panel: {len(day)} days after M03 inner-join, "
         f"macro={'on' if args.macro else 'off'}, pillars={'on' if args.pillars else 'off'}")
    report(day)


if __name__ == "__main__":
    main()
