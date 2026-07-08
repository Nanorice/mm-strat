"""Charts for Q1 (top-N drift per period) and Q2 (6-pillar percentiles vs return curve).

Self-contained: recomputes from the same parquets as start_date_drift.py.
"""
import numpy as np, pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from start_date_drift import _root, OUT, PERIODS, daily_topn

ROOT = _root()


def main() -> None:
    topn = pd.read_parquet(OUT / "_topN_scratch.parquet")

    # ---- Chart 1: Q1 — 6 periods, top-1/5/10 cumulative fwd20 curve ----
    fig, ax = plt.subplots(2, 3, figsize=(17, 9))
    cols = {1: "#c62828", 5: "#1565c0", 10: "#2e7d32"}
    for a, (start, end, label) in zip(ax.flat, PERIODS):
        sub = topn[(topn.date >= start) & (topn.date <= end)]
        for n in (1, 5, 10):
            s = daily_topn(sub, n, "fwd20").cumsum()
            a.plot(s.index, s.values * 100, color=cols[n], lw=1.6, label=f"top-{n}")
        a.axhline(0, color="k", lw=.7, alpha=.5)
        a.set_title(label, weight="bold"); a.set_ylabel("cum. mean fwd20 (%)")
        a.legend(fontsize=8, loc="upper left")
        a.tick_params(axis="x", labelrotation=30, labelsize=8)
    fig.suptitle("Q1 - deploy-from-any-day drift: cumulative top-N mean fwd20 per period\n"
                 "(up-slope = real edge; flat/down = start-date lottery)", weight="bold")
    plt.tight_layout()
    f1 = OUT / "start_date_drift.png"
    plt.savefig(f1, dpi=110, bbox_inches="tight"); print("saved", f1)

    # ---- Chart 2: Q2 — 6-pillar expanding percentile stack + top-5 curve ----
    et = pd.read_parquet(ROOT / "data/model_output_eda/entry_timing/entry_timing_daily.parquet")
    pil = ["pil_vix", "pil_credit", "pil_term", "pil_rates", "pil_liq", "pil_cape"]
    p = et[["date"] + pil].sort_values("date").reset_index(drop=True)
    for c in pil:
        p[c + "_pct"] = p[c].expanding().apply(lambda x: (x.iloc[-1] >= x).mean(), raw=False)
    curve5 = daily_topn(topn[topn.date >= p.date.min()], 5, "fwd20").cumsum()

    nice = {"pil_vix": "VIX", "pil_credit": "Credit", "pil_term": "Term",
            "pil_rates": "Rates", "pil_liq": "Liquidity", "pil_cape": "CAPE"}
    pcols = ["#6a1b9a", "#c62828", "#00838f", "#ef6c00", "#2e7d32", "#455a64"]
    fig, ax = plt.subplots(7, 1, figsize=(15, 12), sharex=True,
                           gridspec_kw={"height_ratios": [2.2] + [1] * 6})
    ax[0].plot(curve5.index, curve5.values * 100, color="#1565c0", lw=1.7)
    ax[0].axhline(0, color="k", lw=.7, alpha=.5)
    ax[0].set_ylabel("cum. top-5\nfwd20 (%)"); ax[0].grid(alpha=.25)
    ax[0].set_title("Q2 - 6-pillar macro (expanding percentile, live-safe) vs the top-5 return curve",
                    weight="bold")
    for a, c, col in zip(ax[1:], [c + "_pct" for c in pil], pcols):
        a.fill_between(p.date, 0, p[c] * 100, color=col, alpha=.35)
        a.plot(p.date, p[c] * 100, color=col, lw=1)
        a.set_ylim(0, 100); a.set_yticks([0, 50, 100])
        a.axhline(50, color="k", lw=.5, alpha=.3); a.grid(alpha=.2)
        a.set_ylabel(nice[c.replace("_pct", "")], rotation=0, ha="right", va="center", fontsize=10)
    ax[-1].set_xlabel("date")
    plt.tight_layout()
    f2 = OUT / "pillars_vs_curve.png"
    plt.savefig(f2, dpi=110, bbox_inches="tight"); print("saved", f2)


if __name__ == "__main__":
    main()
