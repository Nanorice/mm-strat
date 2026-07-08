"""Follow-up charts (user, 2026-07-08):

  C3  NON-cumulative per-day top-N mean fwd20 — each point = that day's basket entry,
      its realized fwd20. Shows the raw scatter the cumulative curve integrates.
  C4  WHOLE-period (2001-2025) top-5: raw daily points + cumulative curve + regime shading,
      to see the regime changes directly.
  C5  6-pillar as ROLLING 2yr percentile (fixes the expanding-pct defect: Net Liquidity &
      CAPE trend +0.96/+0.91 so expanding-pct pins them at ~100%; rolling window shows the
      cyclical position instead). Still live-safe (backward window).
"""
import numpy as np, pandas as pd
import matplotlib.pyplot as plt
from matplotlib.dates import YearLocator
from pathlib import Path
from start_date_drift import _root, OUT, PERIODS, daily_topn

ROOT = _root()
ROLL = 504   # ~2yr trading days


def load_regime() -> pd.DataFrame:
    dd = pd.read_parquet(ROOT / "data/model_output_eda/regime_state/regime_state_daily_dd.parquet")
    return dd[["date", "state"]]


def shade_regime(ax, reg: pd.DataFrame) -> None:
    """Light background bands: bear=red, bull-stress=orange, bull-calm=none."""
    cmap = {"bear": "#e57373", "bull-stress": "#ffcc80"}
    r = reg.sort_values("date").reset_index(drop=True)
    r["blk"] = (r["state"] != r["state"].shift()).cumsum()
    for _, g in r.groupby("blk"):
        st = g["state"].iloc[0]
        if st in cmap:
            ax.axvspan(g["date"].iloc[0], g["date"].iloc[-1], color=cmap[st], alpha=.25, lw=0)


def main() -> None:
    topn = pd.read_parquet(OUT / "_topN_scratch.parquet")
    reg = load_regime()

    # ---- C3: non-cumulative per-day top-N fwd20, per period ----
    fig, ax = plt.subplots(2, 3, figsize=(17, 9))
    for a, (start, end, label) in zip(ax.flat, PERIODS):
        sub = topn[(topn.date >= start) & (topn.date <= end)]
        d5 = daily_topn(sub, 5, "fwd20") * 100
        d1 = daily_topn(sub, 1, "fwd20") * 100
        a.scatter(d5.index, d5.values, s=6, alpha=.35, color="#1565c0", label="top-5 daily")
        a.plot(d5.rolling(21, min_periods=5).mean().index,
               d5.rolling(21, min_periods=5).mean().values, color="#0d47a1", lw=1.8, label="top-5 21d-avg")
        a.axhline(0, color="k", lw=.7); a.axhline(d5.mean(), color="#c62828", ls="--", lw=1,
                                                  label=f"mean {d5.mean():+.1f}%")
        a.set_title(label, weight="bold"); a.set_ylabel("fwd20 (%)")
        a.legend(fontsize=7, loc="upper left"); a.tick_params(axis="x", labelrotation=30, labelsize=8)
    fig.suptitle("C3 - NON-cumulative: each point = a day's top-5 basket, its realized fwd20\n"
                 "(the raw returns the cumulative curve sums)", weight="bold")
    plt.tight_layout(); plt.savefig(OUT / "drift_noncumulative.png", dpi=110, bbox_inches="tight")
    print("saved", OUT / "drift_noncumulative.png")

    # ---- C4: whole period, top-5 raw + cumulative + regime shading ----
    d5 = daily_topn(topn, 5, "fwd20") * 100
    fig, ax = plt.subplots(2, 1, figsize=(16, 9), sharex=True, gridspec_kw={"height_ratios": [1, 1.2]})
    shade_regime(ax[0], reg); shade_regime(ax[1], reg)
    ax[0].scatter(d5.index, d5.values, s=4, alpha=.25, color="#1565c0")
    roll = d5.rolling(63, min_periods=10).mean()
    ax[0].plot(roll.index, roll.values, color="#0d47a1", lw=1.6, label="63d-avg fwd20")
    ax[0].axhline(0, color="k", lw=.7); ax[0].set_ylabel("daily top-5 fwd20 (%)")
    ax[0].set_ylim(-40, 60); ax[0].legend(loc="upper left")
    ax[0].set_title("C4 - whole period (2001-2025): raw daily top-5 fwd20  "
                    "(shade: red=bear, orange=bull-stress)", weight="bold")
    ax[1].plot(d5.index, d5.cumsum().values, color="#1565c0", lw=1.7)
    ax[1].axhline(0, color="k", lw=.7); ax[1].set_ylabel("cumulative (%)")
    ax[1].set_xlabel("date"); ax[1].xaxis.set_major_locator(YearLocator(2))
    ax[1].tick_params(axis="x", labelrotation=45)
    ax[1].set_title("cumulative sum - regime changes = slope changes (flat/down in bear bands)")
    plt.tight_layout(); plt.savefig(OUT / "drift_wholeperiod.png", dpi=110, bbox_inches="tight")
    print("saved", OUT / "drift_wholeperiod.png")

    # ---- C5: 6-pillar rolling-2yr percentile (fixes trending-pillar defect) ----
    et = pd.read_parquet(ROOT / "data/model_output_eda/entry_timing/entry_timing_daily.parquet")
    pil = ["pil_vix", "pil_credit", "pil_term", "pil_rates", "pil_liq", "pil_cape"]
    p = et[["date"] + pil].sort_values("date").reset_index(drop=True)
    for c in pil:
        p[c + "_rp"] = p[c].rolling(ROLL, min_periods=126).apply(
            lambda x: (x.iloc[-1] >= x).mean(), raw=False)
    curve5 = (daily_topn(topn[topn.date >= p.date.min()], 5, "fwd20") * 100).cumsum()

    nice = {"pil_vix": "VIX", "pil_credit": "Credit", "pil_term": "Term",
            "pil_rates": "Rates", "pil_liq": "Liquidity", "pil_cape": "CAPE"}
    pcols = ["#6a1b9a", "#c62828", "#00838f", "#ef6c00", "#2e7d32", "#455a64"]
    fig, ax = plt.subplots(7, 1, figsize=(15, 12), sharex=True,
                           gridspec_kw={"height_ratios": [2.2] + [1] * 6})
    shade_regime(ax[0], reg)
    ax[0].plot(curve5.index, curve5.values, color="#1565c0", lw=1.7)
    ax[0].axhline(0, color="k", lw=.7, alpha=.5); ax[0].grid(alpha=.25)
    ax[0].set_ylabel("cum. top-5\nfwd20 (%)")
    ax[0].set_title("C5 - 6-pillar ROLLING 2yr percentile (live-safe; fixes trending Liq/CAPE) "
                    "vs top-5 curve", weight="bold")
    for a, c, col in zip(ax[1:], pil, pcols):
        shade_regime(a, reg)
        a.fill_between(p.date, 0, p[c + "_rp"] * 100, color=col, alpha=.35)
        a.plot(p.date, p[c + "_rp"] * 100, color=col, lw=1)
        a.set_ylim(0, 100); a.set_yticks([0, 50, 100]); a.axhline(50, color="k", lw=.5, alpha=.3)
        a.grid(alpha=.2)
        a.set_ylabel(nice[c], rotation=0, ha="right", va="center", fontsize=10)
    ax[-1].set_xlabel("date")
    plt.tight_layout(); plt.savefig(OUT / "pillars_vs_curve_rolling.png", dpi=110, bbox_inches="tight")
    print("saved", OUT / "pillars_vs_curve_rolling.png")


if __name__ == "__main__":
    main()
