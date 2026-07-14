# Q65 curiosity chart — day-1 score vs trend-break-exit return.
# OVERFIT by construction (score plotted against realized result): intuition only,
# never a selection claim. Substrate: champion_trail cone trades, filtered to trend exits.
import glob
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[4]
CONE = ROOT / "data/selection_sweep/starttime/champion_trail/rolling"

fs = sorted(glob.glob(str(CONE / "r_*/trades.parquet")))
df = pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)
df = df[df["exit_reason"] == "trend"].copy()  # trend-break exits only
print(f"trend-exit trades: {len(df)}")

SCORES = [("entry_score", "day-1 entry_score"), ("prob_elite", "day-1 prob_elite")]
fig, axes = plt.subplots(1, 2, figsize=(15, 6))

for ax, (col, label) in zip(axes, SCORES):
    d = df.dropna(subset=[col, "pnl_percent"])
    s, p = d[col].values, d["pnl_percent"].values
    rho, pval = spearmanr(s, p)
    ax.scatter(s, p, s=10, alpha=.25, color="#607d8b", edgecolors="none")

    # binned median — does the answer to "best performers higher-scored?" show through the noise?
    d = d.assign(dec=pd.qcut(d[col], 10, labels=False, duplicates="drop"))
    g = d.groupby("dec").agg(x=(col, "median"), med=("pnl_percent", "median"),
                             q25=("pnl_percent", lambda v: v.quantile(.25)),
                             q75=("pnl_percent", lambda v: v.quantile(.75)))
    ax.plot(g.x, g.med, "o-", color="#c62828", lw=2, label="decile median")
    ax.fill_between(g.x, g.q25, g.q75, color="#c62828", alpha=.12, label="decile IQR")

    ax.axhline(0, color="k", lw=.7, alpha=.5)
    ax.set_title(f"{label} vs trend-exit return\nSpearman rho={rho:+.3f} (p={pval:.3f})", fontsize=12)
    ax.set_xlabel(label)
    ax.set_ylabel("pnl_percent (trend exit)")
    ax.legend(fontsize=9)

fig.suptitle(f"Q65 (OVERFIT, intuition only) — day-1 score vs trend-break-exit return, "
             f"{len(df)} champion_trail trades", fontsize=13, weight="bold")
plt.tight_layout(rect=[0, 0, 1, 0.96])
out = ROOT / "docs/session_logs/sprint_14/verdicts/2026-07-14_q65_score_vs_trendexit.png"
plt.savefig(out, dpi=110, bbox_inches="tight")
print(f"saved {out}")

# text read: the actual answer, so it lands in the log not just the PNG
for col, label in SCORES:
    d = df.dropna(subset=[col, "pnl_percent"])
    rho, _ = spearmanr(d[col], d["pnl_percent"])
    top = d[d[col] >= d[col].quantile(.9)]["pnl_percent"].median()
    bot = d[d[col] <= d[col].quantile(.1)]["pnl_percent"].median()
    print(f"{label:>20}: rho={rho:+.3f} | top-decile median pnl {top:+.2f} vs bottom-decile {bot:+.2f}")
