# M1 visual: 4-panel chart for the tail-magnitude re-cut. Same parquet, no scoring.
import numpy as np, pandas as pd
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[4]
df = pd.read_parquet(ROOT / "data/model_output_eda/raw_full_2025_fwd.parquet").dropna(subset=["fwd20"])
s, f, N = df["prob_elite"].values, df["fwd20"].values, len(df)
GATE, HR = 0.48, 0.30
tail = np.maximum(f - HR, 0.0)
tot_tail = tail.sum()
above = s >= GATE

fig, ax = plt.subplots(2, 2, figsize=(15, 10))

# 1 — binary miss vs magnitude miss (the headline)
miss_c = (f[~above] > HR).sum() / (f > HR).sum()
miss_t = tail[~above].sum() / tot_tail
b = ax[0, 0].bar(["home-run\nCOUNT (binary)", "tail\nMAGNITUDE"], [miss_c * 100, miss_t * 100],
                 color=["#c62828", "#2e7d32"], width=.55, edgecolor="w")
for r, v in zip(b, [miss_c, miss_t]):
    ax[0, 0].text(r.get_x() + r.get_width() / 2, v * 100 + .5, f"{v:.1%}", ha="center", fontsize=13, weight="bold")
ax[0, 0].set_title(f"What the {GATE} gate MISSES — the gate keeps big winners, drops small", fontsize=12)
ax[0, 0].set_ylabel("% missed"); ax[0, 0].set_ylim(0, 30)

# 2 — tail-capture concentration (Lorenz-style): walk score top-down
order = np.argsort(-s)
cum_tail = np.cumsum(tail[order]) / tot_tail
xs = np.arange(1, N + 1) / N
ax[0, 1].plot(xs * 100, cum_tail * 100, lw=2.2, color="#1565c0", label="tail captured")
ax[0, 1].plot([0, 100], [0, 100], "k--", alpha=.4, label="no skill (random)")
for frac in (0.01, 0.10, 0.25):
    idx = int(frac * N) - 1
    ax[0, 1].plot(frac * 100, cum_tail[idx] * 100, "o", color="#c62828")
    ax[0, 1].annotate(f"top {frac:.0%} → {cum_tail[idx]:.0%}\n({cum_tail[idx]/frac:.1f}×)",
                      (frac * 100, cum_tail[idx] * 100), textcoords="offset points", xytext=(8, -4), fontsize=9)
ax[0, 1].set_title("Tail concentration — the raw score RANKS the fat tail", fontsize=12)
ax[0, 1].set_xlabel("top X% of scores"); ax[0, 1].set_ylabel("% of total tail captured")
ax[0, 1].legend(fontsize=9); ax[0, 1].set_xlim(0, 100); ax[0, 1].set_ylim(0, 100)

# 3 — tail magnitude by score ventile (vs the old home-run-RATE bars)
df2 = df.assign(tail=tail, ventile=pd.qcut(df["prob_elite"], 20, labels=False, duplicates="drop"))
g = df2.groupby("ventile").agg(hr_rate=("fwd20", lambda x: (x > HR).mean()), mean_tail=("tail", "mean"))
axb = ax[1, 0]
axb.bar(g.index, g.mean_tail, color="#2e7d32", alpha=.85, label="mean tail (magnitude)")
axb.set_ylabel("mean Σmax(fwd-30%,0)", color="#2e7d32")
axt = axb.twinx()
axt.plot(g.index, g.hr_rate * 100, "o-", color="#c62828", lw=1.5, label="home-run rate (binary)")
axt.set_ylabel("home-run rate %", color="#c62828")
axb.set_title("Score ventile: magnitude (bars) vs binary rate (line) — both grade, rho +1.00", fontsize=12)
axb.set_xlabel("raw-score ventile (19 = top)"); axb.set_xticks(range(0, 20, 2))

# 4 — where the top-1% fwd returns sit in the score distribution
top1 = f >= np.quantile(f, 0.99)
pctile = pd.Series(s).rank(pct=True).values
ax[1, 1].hist(pctile[~top1], bins=40, alpha=.5, density=True, color="#90a4ae", label="all names")
ax[1, 1].hist(pctile[top1], bins=40, alpha=.7, density=True, color="#d84315", label="top-1% fwd returns")
ax[1, 1].axvline(np.median(pctile[top1]), color="#d84315", ls="--", lw=2,
                 label=f"top-1% median pctile {np.median(pctile[top1]):.2f}")
ax[1, 1].set_title("Biggest 1% of winners cluster at the TOP of the score", fontsize=12)
ax[1, 1].set_xlabel("raw-score percentile"); ax[1, 1].set_ylabel("density"); ax[1, 1].legend(fontsize=9)

fig.suptitle("M1 — tail-magnitude re-cut (full universe, 2025, 596k rows, 20d fwd)", fontsize=14, weight="bold")
plt.tight_layout(rect=[0, 0, 1, 0.98])
out = ROOT / "data/model_output_eda/m1_tail_magnitude.png"
plt.savefig(out, dpi=110, bbox_inches="tight")
print(f"saved {out}")
