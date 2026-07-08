"""M6 consumer #2: does m01's score->return behaviour change by REGIME state?

User steer (2026-07-08): monitor ALL tickers (good or bad), not just top-N picks; this is
TRACKING m01 output, NOT a backtest. Three questions, all EDA on the 25y full-universe scored
cache (data/model_output_eda/multiyear/raw_full_*_fwd.parquet, cols prob_elite + fwd20):

  1. TRUNK BAKEOFF  — does SPX-vs-200MA separate fwd return better than pillar-based trunks?
                      (justify the trunk with evidence; SHOW the losers, don't assert.)
  2. M01 x REGIME   — full universe: fwd20 by regime state, AND by m01-score-decile x state.
                      Does the score->return gradient hold in EVERY state, or invert in some?
  3. STAT TEST      — block-bootstrap CI on per-state means + the (stress-calm) gap, PLUS
                      Kruskal-Wallis / Mann-Whitney p-values (with the autocorrelation caveat).

  python docs/session_logs/sprint_14/scripts/m01_by_regime.py --smoke   # 3 years
  python docs/session_logs/sprint_14/scripts/m01_by_regime.py           # full 25y
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy import stats


def _root() -> Path:
    p = Path.cwd().resolve()
    for d in (p, *p.parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    for d in (Path(__file__).resolve(), *Path(__file__).resolve().parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError("root not found")


ROOT = _root()
CACHE = ROOT / "data" / "model_output_eda" / "multiyear"
STATE = ROOT / "data" / "model_output_eda" / "regime_state"
DB = ROOT / "data" / "market_data.duckdb"
OUT = ROOT / "data" / "model_output_eda" / "m01_by_regime"
STATES = ["bull-calm", "bull-stress", "bear"]


def _log(m: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def load_universe(years: list[int] | None) -> pd.DataFrame:
    """Full scored universe, prob_elite (raw m01) + fwd20, joined to the dd regime label."""
    frames = []
    for fp in sorted(CACHE.glob("raw_full_*_fwd.parquet")):
        yr = int(fp.stem.split("_")[2])
        if years and yr not in years:
            continue
        df = pd.read_parquet(fp, columns=["date", "ticker", "prob_elite", "fwd20", "fwd50", "fwd100"])
        frames.append(df)
    u = pd.concat(frames, ignore_index=True)
    u["date"] = pd.to_datetime(u["date"])
    u = u.dropna(subset=["fwd20", "prob_elite"])   # fwd50/100 may be NaN near data end -> per-metric dropna
    st = pd.read_parquet(STATE / "regime_state_daily_dd.parquet")[["date", "state"]]
    st["date"] = pd.to_datetime(st["date"])
    u = u.merge(st, on="date", how="inner")   # inner: state label spans full 25y on dd axis
    _log(f"universe: {len(u)} scored rows, {u.date.dt.year.min()}-{u.date.dt.year.max()}, "
         f"{u.date.nunique()} days")
    return u


# ---- 1. trunk bakeoff -----------------------------------------------------------------------
def trunk_candidates() -> pd.DataFrame:
    """date -> several candidate bull/bear trunk flags. All live-safe (past-only).
      spx200   : SPY > 200d MA        (the current trunk)
      credit   : HY credit spread BELOW its expanding median (tight = risk-on)
      term     : 10y-2y term spread ABOVE its expanding median (steep = risk-on)
      composite: majority vote of the three
    """
    con = duckdb.connect(str(DB), read_only=True)
    try:
        spy = con.execute("SELECT date, spy_close FROM t1_macro WHERE spy_close IS NOT NULL "
                          "ORDER BY date").df()
        mac = con.execute("""SELECT date, symbol, close AS v FROM macro_data
                             WHERE symbol IN ('BAMLH0A0HYM2','DGS10','DGS2')""").df()
    finally:
        con.close()
    spy["date"] = pd.to_datetime(spy["date"])
    spy["spx200"] = (spy["spy_close"] > spy["spy_close"].rolling(200).mean()).astype(float)
    m = mac.assign(v=pd.to_numeric(mac["v"], errors="coerce"),
                   date=pd.to_datetime(mac["date"])).pivot_table(
                   index="date", columns="symbol", values="v").sort_index().ffill()
    credit, term = m["BAMLH0A0HYM2"], m["DGS10"] - m["DGS2"]
    # expanding median, live-safe (through t-1)
    cred_bull = (credit < credit.expanding(min_periods=252).median().shift(1)).astype(float)
    term_bull = (term > term.expanding(min_periods=252).median().shift(1)).astype(float)
    t = pd.DataFrame({"credit": cred_bull, "term": term_bull}).reset_index()
    out = spy[["date", "spx200"]].merge(t, on="date", how="left")
    out["composite"] = (out[["spx200", "credit", "term"]].mean(axis=1) >= 0.5).astype(float)
    return out


def bakeoff(u: pd.DataFrame) -> pd.DataFrame:
    """For each trunk candidate: mean fwd20 in its bull vs bear, and the SEPARATION (bull-bear).
    Bigger positive separation = the trunk better tells good-forward from bad-forward days."""
    tr = trunk_candidates()
    d = u.merge(tr, on="date", how="inner")
    rows = []
    for col in ["spx200", "credit", "term", "composite"]:
        sub = d.dropna(subset=[col])
        bull = sub.loc[sub[col] == 1, "fwd20"]
        bear = sub.loc[sub[col] == 0, "fwd20"]
        rows.append(dict(trunk=col, n_bull=len(bull), n_bear=len(bear),
                         mean_bull=bull.mean(), mean_bear=bear.mean(),
                         separation=bull.mean() - bear.mean(),
                         hr_bull=(bull > 0.30).mean(), hr_bear=(bear > 0.30).mean()))
    return pd.DataFrame(rows).sort_values("separation", ascending=False)


# ---- 2. m01 x regime ------------------------------------------------------------------------
def by_state(u: pd.DataFrame) -> pd.DataFrame:
    g = u.groupby("state")["fwd20"].agg(n="size", mean="mean", median="median",
                                        hr=lambda x: (x > 0.30).mean(), std="std")
    return g.reindex(STATES)


def score_gradient_by_state(u: pd.DataFrame) -> pd.DataFrame:
    """m01-score decile x state -> mean fwd20. Does the top decile beat the bottom in EVERY
    state (gradient holds) or does it flatten/invert in some (regime-dependent skill)?"""
    u = u.copy()
    u["dec"] = u.groupby("state")["prob_elite"].transform(
        lambda s: pd.qcut(s, 10, labels=False, duplicates="drop"))
    piv = u.groupby(["state", "dec"])["fwd20"].mean().unstack("state").reindex(columns=STATES)
    # gradient = top-decile mean - bottom-decile mean, per state
    grad = piv.iloc[-1] - piv.iloc[0]
    return piv, grad


# ---- 2c. horizon sweep (does the regime story strengthen at fwd50/100? Thread F: signals live long)
def horizon_sweep(u: pd.DataFrame, horizons=("fwd20", "fwd50", "fwd100")) -> pd.DataFrame:
    """Per state x horizon: mean fwd return + the m01 top-minus-bottom decile gradient.
    Answers whether the regime LEVEL gap and the ranking GRADIENT grow with the hold."""
    rows = []
    for h in horizons:
        sub = u.dropna(subset=[h])
        m = sub.groupby("state")[h].mean().reindex(STATES)
        sub = sub.copy()
        sub["dec"] = sub.groupby("state")["prob_elite"].transform(
            lambda s: pd.qcut(s, 10, labels=False, duplicates="drop"))
        piv = sub.groupby(["state", "dec"])[h].mean().unstack("state").reindex(columns=STATES)
        grad = piv.iloc[-1] - piv.iloc[0]
        for s in STATES:
            rows.append(dict(horizon=h, state=s, mean=m[s], gradient=grad[s]))
    return pd.DataFrame(rows)


# ---- 3. stat test ---------------------------------------------------------------------------
def block_bootstrap_ci(u: pd.DataFrame, n_boot: int = 1000, seed: int = 42) -> pd.DataFrame:
    """Block-bootstrap by DAY: resample whole days (preserves within-day cross-section &
    respects autocorrelation better than iid rows). CI on per-state mean fwd20 + the
    (bull-stress minus bull-calm) gap.

    Cost fix: precompute each (day, state) SUM + COUNT once, then each bootstrap iter is a
    count-weighted mean over resampled days — O(days) not O(rows). Identical statistic.
    """
    rng = np.random.default_rng(seed)
    agg = (u.groupby(["date", "state"])["fwd20"].agg(s="sum", c="size").reset_index())
    # dense day x state matrices of sums and counts (missing = 0)
    S = agg.pivot(index="date", columns="state", values="s").reindex(columns=STATES).fillna(0).values
    C = agg.pivot(index="date", columns="state", values="c").reindex(columns=STATES).fillna(0).values
    ndays = S.shape[0]
    boot = np.empty((n_boot, len(STATES)))
    for b in range(n_boot):
        idx = rng.integers(0, ndays, ndays)
        cs = C[idx].sum(axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            boot[b] = np.where(cs > 0, S[idx].sum(axis=0) / cs, np.nan)  # count-weighted mean/state
    rows = []
    for j, s in enumerate(STATES):
        a = boot[:, j]
        rows.append(dict(state=s, mean=np.nanmean(a),
                         lo=np.nanpercentile(a, 2.5), hi=np.nanpercentile(a, 97.5)))
    gap = boot[:, STATES.index("bull-stress")] - boot[:, STATES.index("bull-calm")]
    rows.append(dict(state="gap(stress-calm)", mean=np.nanmean(gap),
                     lo=np.nanpercentile(gap, 2.5), hi=np.nanpercentile(gap, 97.5)))
    return pd.DataFrame(rows)


def kw_mw(u: pd.DataFrame) -> str:
    """Kruskal-Wallis across states + pairwise Mann-Whitney. ⚠️ assumes iid days
    (autocorrelation violates it → p is optimistic; the bootstrap CI is the honest read)."""
    groups = [u.loc[u.state == s, "fwd20"].values for s in STATES]
    h, p = stats.kruskal(*groups)
    lines = [f"Kruskal-Wallis across {STATES}: H={h:.1f}, p={p:.2e}"]
    for i in range(len(STATES)):
        for j in range(i + 1, len(STATES)):
            _, pp = stats.mannwhitneyu(groups[i], groups[j], alternative="two-sided")
            lines.append(f"  MW {STATES[i]} vs {STATES[j]}: p={pp:.2e}")
    lines.append("  [!] iid-day assumption violated by autocorrelation -> p optimistic; "
                 "trust the bootstrap CI.")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="3 years (2008,2021,2022) — a crash + calm + bear")
    ap.add_argument("--boot", type=int, default=1000)
    args = ap.parse_args()
    years = [2008, 2021, 2022] if args.smoke else None

    u = load_universe(years)
    OUT.mkdir(parents=True, exist_ok=True)

    _log("=== 1. TRUNK BAKEOFF (does SPX-200MA beat pillar trunks at separating fwd return?) ===")
    bo = bakeoff(u); print(bo.round(4).to_string(index=False))
    bo.to_csv(OUT / "trunk_bakeoff.csv", index=False)

    _log("=== 2a. fwd20 BY STATE (all tickers) ===")
    bs = by_state(u); print(bs.round(4).to_string())
    bs.to_csv(OUT / "fwd_by_state.csv")

    _log("=== 2b. m01 score-decile x state (does the gradient hold in every state?) ===")
    piv, grad = score_gradient_by_state(u)
    print(piv.round(4).to_string())
    print("\ntop-minus-bottom decile gradient by state:"); print(grad.round(4).to_string())
    piv.to_csv(OUT / "score_gradient_by_state.csv")

    _log("=== 2c. HORIZON SWEEP (does the regime story grow with the hold? fwd20/50/100) ===")
    hs = horizon_sweep(u)
    print(hs.pivot(index="state", columns="horizon", values="mean").reindex(STATES)[
        ["fwd20", "fwd50", "fwd100"]].round(4).to_string())
    print("\ntop-minus-bottom decile GRADIENT by horizon:")
    print(hs.pivot(index="state", columns="horizon", values="gradient").reindex(STATES)[
        ["fwd20", "fwd50", "fwd100"]].round(4).to_string())
    hs.to_csv(OUT / "horizon_sweep.csv", index=False)

    _log(f"=== 3. STAT TEST (block-bootstrap {args.boot} + Kruskal-Wallis, fwd20) ===")
    ci = block_bootstrap_ci(u, n_boot=args.boot); print(ci.round(4).to_string(index=False))
    ci.to_csv(OUT / "bootstrap_ci.csv", index=False)
    print(); print(kw_mw(u))

    # self-checks
    assert set(bs.index) == set(STATES) and bs["n"].sum() == len(u), "state coverage lost"
    assert bo["separation"].notna().all(), "a trunk failed to separate"
    _log(f"saved outputs under {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
