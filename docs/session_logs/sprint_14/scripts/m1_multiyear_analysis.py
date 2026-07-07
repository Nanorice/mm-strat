"""M1 cross-regime analysis: read the per-year cache from score_universe_multiyear.py and test
whether the tail-lift@k (and the above-gate residual) HOLDS across regimes or is a 2025 artifact.
Reusable — reads whatever years are cached. Emits a table + the cross-regime chart.

  python docs/session_logs/sprint_14/scripts/m1_multiyear_analysis.py
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[4]
CACHE = ROOT / "data" / "model_output_eda" / "multiyear"
HR, GATE = 0.30, 0.48

# labelled regimes for the years t3 covers (broad-brush; for narrative only)
REGIME = {2001: "dot-com bust", 2002: "bear", 2003: "recovery", 2004: "bull", 2005: "bull",
          2006: "bull", 2007: "top", 2008: "GFC crash", 2009: "recovery", 2010: "bull",
          2011: "EU crisis", 2012: "bull", 2013: "QE bull", 2014: "bull", 2015: "choppy",
          2016: "bull", 2017: "low-vol bull", 2018: "vol selloff", 2019: "bull",
          2020: "COVID crash/V", 2021: "bull", 2022: "rate-hike bear", 2023: "recovery",
          2024: "bull", 2025: "baseline"}


def tail_lift(s, tail, fracs=(0.01, 0.05, 0.10, 0.25)):
    N, tot = len(s), tail.sum()
    if tot <= 0 or N == 0:
        return {fr: np.nan for fr in fracs}
    order = np.argsort(-s); cum = np.cumsum(tail[order]) / tot
    return {fr: cum[int(fr * N) - 1] / fr for fr in fracs}


def year_stats(df):
    df = df.dropna(subset=["fwd20"])
    s, f = df["prob_elite"].values, df["fwd20"].values
    tail = np.maximum(f - HR, 0.0)
    above = s >= GATE
    full = tail_lift(s, tail)
    cond = tail_lift(s[above], tail[above]) if above.sum() > 100 else {k: np.nan for k in full}
    # magnitude miss vs binary miss for the gate
    tot_t = tail.sum(); tot_c = (f > HR).sum()
    miss_t = tail[~above].sum() / tot_t if tot_t > 0 else np.nan
    miss_c = (f[~above] > HR).sum() / tot_c if tot_c > 0 else np.nan
    return dict(n=len(df), hr_rate=(f > HR).mean(), fwd_max=f.max(),
                lift1_full=full[0.01], lift10_full=full[0.10],
                lift1_cond=cond[0.01], lift10_cond=cond[0.10],
                miss_count=miss_c, miss_mag=miss_t)


def main():
    files = sorted(CACHE.glob("raw_full_*_fwd.parquet"))
    if not files:
        print("no cached years yet — run score_universe_multiyear.py first"); return
    rows = {}
    for fp in files:
        year = int(fp.stem.split("_")[2])
        rows[year] = year_stats(pd.read_parquet(fp))
    t = pd.DataFrame(rows).T.sort_index()
    t.index.name = "year"

    pd.set_option("display.width", 160, "display.float_format", lambda x: f"{x:.3f}")
    print(f"\n=== M1 cross-regime tail-lift ({len(t)} years) ===")
    show = t[["n", "hr_rate", "lift1_full", "lift10_full", "lift1_cond", "lift10_cond",
              "miss_count", "miss_mag"]].copy()
    show.insert(0, "regime", [REGIME.get(y, "?") for y in show.index])
    print(show.to_string())

    print(f"\n=== stability of the claim across {len(t)} regimes ===")
    for col, lbl in [("lift1_full", "top-1% lift (FULL)"), ("lift1_cond", "top-1% lift (above-gate)"),
                     ("miss_mag", "tail-magnitude miss %")]:
        v = t[col].dropna()
        print(f"  {lbl:<28} median {v.median():.2f}  min {v.min():.2f}  max {v.max():.2f}  "
              f"IQR [{v.quantile(.25):.2f},{v.quantile(.75):.2f}]  yrs<1x: {(v<1).sum()}")

    # ---- chart ----
    BAD = {2001, 2002, 2007, 2008, 2009, 2011, 2022}   # bust/bear/top/crash
    fig, ax = plt.subplots(1, 2, figsize=(16, 6))
    yrs = t.index.values
    for y in yrs:                                       # shade bad regimes
        if y in BAD:
            ax[0].axvspan(y - .5, y + .5, color="#c62828", alpha=.10)
    ax[0].plot(yrs, t.lift1_full, "o-", color="#1565c0", label="top-1% lift (full universe)")
    ax[0].plot(yrs, t.lift1_cond, "s--", color="#d84315", label="top-1% lift (above the gate)")
    ax[0].axhline(1, color="k", lw=.8, ls=":", label="no skill")
    ax[0].set_title("Tail-lift across regimes (red = bear/crash) — ranker is PRO-CYCLICAL")
    ax[0].set_xlabel("year"); ax[0].set_ylabel("tail-lift @ top-1%")
    ax[0].legend(fontsize=9); ax[0].grid(alpha=.3)

    ax[1].bar(yrs - .2, t.miss_count * 100, width=.4, color="#c62828", label="binary count miss %")
    ax[1].bar(yrs + .2, t.miss_mag * 100, width=.4, color="#2e7d32", label="tail magnitude miss %")
    ax[1].set_title("Gate miss: binary vs magnitude, per regime"); ax[1].set_xlabel("year")
    ax[1].set_ylabel("% missed by 0.48 gate"); ax[1].legend(fontsize=9); ax[1].grid(alpha=.3)

    fig.suptitle(f"M1 cross-regime ({t.index.min()}-{t.index.max()}, full-universe raw score)",
                 weight="bold")
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    out = CACHE / "m1_multiyear.png"
    plt.savefig(out, dpi=110, bbox_inches="tight")
    t.to_csv(CACHE / "m1_multiyear_table.csv")
    print(f"\nsaved {out}\nsaved {CACHE/'m1_multiyear_table.csv'}")


if __name__ == "__main__":
    main()
