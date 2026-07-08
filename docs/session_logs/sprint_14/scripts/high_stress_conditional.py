"""Dig into the high-stress tercile (user, 2026-07-08): once in high stress, what separates the
good deploys from the falling knife? Across horizons fwd{20,50,100,150,200}.

Answer: the SPY>200d gate. Within high-stress, bull-stress vs bear-stress have ~equal MEAN but
the bear-stress worst-decile is ~2.5x deeper (falling knife = deep-crash-bottom bets). The gate
barely costs mean and roughly halves the tail -> the point-8 governor (b), now horizon-resolved.

Panel: data/model_output_eda/regime_weight/top5_horizons.parquet (top-5 basket + macro).
"""
import numpy as np, pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path


def _root() -> Path:
    p = Path(__file__).resolve()
    for d in (p, *p.parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError("root not found")


ROOT = _root()
OUT = ROOT / "data/model_output_eda/regime_weight"
H = ["fwd20", "fwd50", "fwd100", "fwd150", "fwd200"]
HN = [20, 50, 100, 150, 200]


def worst_decile(s: pd.Series) -> float:
    return s.nsmallest(max(1, len(s) // 10)).mean()


def main() -> None:
    p = pd.read_parquet(OUT / "top5_horizons.parquet")
    p["stress_t"] = pd.qcut(p["stress_ew_vix"], 3, labels=["lo", "mid", "hi"])
    hi = p[p["stress_t"] == "hi"].copy()
    bull = hi[hi["spy_above200"] == 1]
    bear = hi[hi["spy_above200"] == 0]

    # summary table
    rows = []
    for name, sub in [("all-stress-hi", hi), ("hi & SPY>200 (bull-stress)", bull),
                      ("hi & SPY<=200 (bear-stress)", bear)]:
        for h in H:
            rows.append(dict(cohort=name, horizon=h, n=len(sub), mean=sub[h].mean() * 100,
                             worst_dec=worst_decile(sub[h]) * 100, neg_pct=100 * (sub[h] < 0).mean()))
    tab = pd.DataFrame(rows)
    tab.to_csv(OUT / "high_stress_conditional.csv", index=False)
    print(tab.pivot(index="cohort", columns="horizon", values="mean").round(1).to_string())
    print("\nworst-decile:")
    print(tab.pivot(index="cohort", columns="horizon", values="worst_dec").round(1).to_string())

    # chart: mean, worst-decile, reward/tail ratio across horizons, bull vs bear stress
    fig, ax = plt.subplots(1, 3, figsize=(17, 5.5))
    x = np.array(HN)
    bm = [bull[h].mean() * 100 for h in H]; rm = [bear[h].mean() * 100 for h in H]
    bw = [worst_decile(bull[h]) * 100 for h in H]; rw = [worst_decile(bear[h]) * 100 for h in H]

    ax[0].plot(x, bm, "o-", color="#2e7d32", lw=2, label="bull-stress (SPY>200)")
    ax[0].plot(x, rm, "o-", color="#c62828", lw=2, label="bear-stress (SPY<=200)")
    ax[0].axhline(0, color="k", lw=.7); ax[0].set_title("MEAN — nearly identical", weight="bold")
    ax[0].set_xlabel("horizon (days)"); ax[0].set_ylabel("mean top-5 return (%)"); ax[0].legend()

    ax[1].plot(x, bw, "o-", color="#2e7d32", lw=2, label="bull-stress")
    ax[1].plot(x, rw, "o-", color="#c62828", lw=2, label="bear-stress")
    ax[1].axhline(0, color="k", lw=.7)
    ax[1].set_title("WORST-DECILE — bear-stress ~2.5x deeper (the knife)", weight="bold")
    ax[1].set_xlabel("horizon (days)"); ax[1].set_ylabel("worst-decile return (%)"); ax[1].legend()

    br = [bull[h].mean() / abs(worst_decile(bull[h])) for h in H]
    rr = [bear[h].mean() / abs(worst_decile(bear[h])) for h in H]
    ax[2].plot(x, br, "o-", color="#2e7d32", lw=2, label="bull-stress")
    ax[2].plot(x, rr, "o-", color="#c62828", lw=2, label="bear-stress")
    ax[2].axhline(0, color="k", lw=.7)
    ax[2].set_title("REWARD / TAIL (mean ÷ |worst-decile|)", weight="bold")
    ax[2].set_xlabel("horizon (days)"); ax[2].set_ylabel("ratio"); ax[2].legend()

    fig.suptitle("High-stress tercile, split by SPY>200d — the gate keeps the mean, cuts the tail "
                 f"(n bull={len(bull)}, bear={len(bear)})", weight="bold")
    plt.tight_layout()
    plt.savefig(OUT / "high_stress_conditional.png", dpi=110, bbox_inches="tight")
    print("\nsaved", OUT / "high_stress_conditional.png")


if __name__ == "__main__":
    main()
