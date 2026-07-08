"""Figures for m01_by_regime (M6 consumer #2). Saves PNGs the cells file embeds.
  python docs/session_logs/sprint_14/scripts/m01_by_regime_chart.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def _root() -> Path:
    p = Path.cwd().resolve()
    for d in (p, *p.parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError("root not found")


ROOT = _root()
OUT = ROOT / "data" / "model_output_eda" / "m01_by_regime"
COL = {"bull-calm": "#2e7d32", "bull-stress": "#ef6c00", "bear": "#c62828"}
STATES = ["bull-calm", "bull-stress", "bear"]


def main():
    grad = pd.read_csv(OUT / "score_gradient_by_state.csv", index_col=0)
    ci = pd.read_csv(OUT / "bootstrap_ci.csv")
    bo = pd.read_csv(OUT / "trunk_bakeoff.csv")
    hs = pd.read_csv(OUT / "horizon_sweep.csv")

    fig, ax = plt.subplots(2, 2, figsize=(15, 10)); ax = ax.ravel()

    # 1: m01 score-decile -> mean fwd20, one line per state (does the gradient hold everywhere?)
    for s in STATES:
        ax[0].plot(grad.index, grad[s] * 100, "o-", color=COL[s], label=s, lw=2)
    ax[0].axhline(0, color="k", lw=0.6, alpha=0.5)
    ax[0].set_xlabel("m01 score decile (0=low, 9=top)"); ax[0].set_ylabel("mean fwd20 %")
    ax[0].set_title("1 · m01 score RANKS return in EVERY state\n(monotone up in all three)", weight="bold")
    ax[0].legend(fontsize=9)

    # 2: bootstrap CI on per-state mean fwd20 + the gap
    sub = ci[ci.state.isin(STATES)]
    y = np.arange(len(sub))
    ax[1].errorbar(sub["mean"] * 100, y, xerr=[(sub["mean"] - sub["lo"]) * 100,
                   (sub["hi"] - sub["mean"]) * 100], fmt="o", capsize=5, color="#1565c0", ms=8)
    ax[1].set_yticks(y); ax[1].set_yticklabels(sub["state"])
    ax[1].axvline(0, color="k", lw=0.6, alpha=0.5)
    gap = ci[ci.state == "gap(stress-calm)"].iloc[0]
    ax[1].set_title(f"2 · mean fwd20 by state, 95% block-bootstrap CI\n"
                    f"gap(stress-calm) {gap['mean']*100:+.2f}% "
                    f"[{gap['lo']*100:+.2f}, {gap['hi']*100:+.2f}] "
                    f"{'REAL' if gap['lo']>0 or gap['hi']<0 else 'straddles 0'}", weight="bold")
    ax[1].set_xlabel("mean fwd20 %")

    # 3: trunk bakeoff — separation (bull-bear) per candidate trunk
    b = bo.sort_values("separation")
    colors = ["#c62828" if v < 0 else "#2e7d32" for v in b["separation"]]
    ax[2].barh(b["trunk"], b["separation"] * 100, color=colors)
    ax[2].axvline(0, color="k", lw=0.6)
    ax[2].set_xlabel("bull-minus-bear mean fwd20 %  (separation)")
    ax[2].set_title("3 · trunk bakeoff — NONE separate fwd+\n(bear-day rebound; spx200 least-negative)",
                    weight="bold")

    # 4: horizon sweep — mean fwd per state across fwd20/50/100 (Thread F: signals live long)
    hp = hs.pivot(index="horizon", columns="state", values="mean").reindex(["fwd20", "fwd50", "fwd100"])
    xh = np.arange(3)
    for s in STATES:
        ax[3].plot(xh, hp[s] * 100, "o-", color=COL[s], lw=2, label=s)
    ax[3].set_xticks(xh); ax[3].set_xticklabels(["fwd20", "fwd50", "fwd100"])
    ax[3].set_ylabel("mean fwd return %"); ax[3].legend(fontsize=9)
    ax[3].set_title("4 · the regime gap GROWS with the hold\n(stress-calm: +0.9% → +2.9% by fwd100)",
                    weight="bold")

    fig.tight_layout()
    p = OUT / "m01_by_regime.png"; fig.savefig(p, dpi=110); plt.close(fig)
    print("saved", p.relative_to(ROOT))
    assert (grad.loc[9] > grad.loc[0]).all(), "top decile must beat bottom in every state"


if __name__ == "__main__":
    main()
