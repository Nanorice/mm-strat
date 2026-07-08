"""Chart for the point-8 regime-weight experiment (fwd100)."""
import numpy as np, pandas as pd
import matplotlib.pyplot as plt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from regime_weight_panel import load, weights, wmean, w_worst_decile, _root, HORIZ

ROOT = _root()


def main() -> None:
    df = load().dropna(subset=[HORIZ]).reset_index(drop=True)
    f = df[HORIZ].values

    rules = [("flat", "flat"), ("spx200", "(a) SPY200\nbear=0"),
             ("stress_gated", "(b) stress\nbull-gated")]
    means = [wmean(f, weights(df, k)) for k, _ in rules]
    worst = [w_worst_decile(f, weights(df, k)) for k, _ in rules]
    labels = [l for _, l in rules]
    cols = ["#90a4ae", "#1565c0", "#2e7d32"]

    fig, ax = plt.subplots(1, 3, figsize=(16, 5))

    # 1: mean fwd100 by rule
    b = ax[0].bar(labels, [m * 100 for m in means], color=cols, width=.6)
    for r, v in zip(b, means):
        ax[0].text(r.get_x() + .3, v * 100 + .2, f"{v:+.1%}", ha="center", weight="bold")
    ax[0].axhline(means[0] * 100, color="#90a4ae", ls="--", alpha=.6)
    ax[0].set_title("mean fwd100 (average outcome)"); ax[0].set_ylabel("%")

    # 2: worst-decile loss by rule (the drag)
    b = ax[1].bar(labels, [w * 100 for w in worst], color=cols, width=.6)
    for r, v in zip(b, worst):
        ax[1].text(r.get_x() + .3, v * 100 - 1.5, f"{v:+.1%}", ha="center", weight="bold")
    ax[1].axhline(worst[0] * 100, color="#90a4ae", ls="--", alpha=.6)
    ax[1].set_title("worst-decile fwd100 (the drag we want to cut)"); ax[1].set_ylabel("%")

    # 3: fwd100 by state — WHY (bear = high mean, worst tail)
    g = df.groupby("state")[HORIZ]
    st = ["bull-calm", "bull-stress", "bear"]
    gm = [g.get_group(s).mean() * 100 for s in st]
    gw = [g.get_group(s).nsmallest(max(1, len(g.get_group(s)) // 10)).mean() * 100 for s in st]
    x = np.arange(3)
    ax[2].bar(x - .2, gm, .4, label="mean", color="#2e7d32")
    ax[2].bar(x + .2, gw, .4, label="worst-decile", color="#c62828")
    ax[2].set_xticks(x); ax[2].set_xticklabels(st, fontsize=9)
    ax[2].axhline(0, color="k", lw=.8)
    ax[2].set_title("fwd100 by state — bear = highest mean, worst tail"); ax[2].legend()

    fig.suptitle("Point-8 — regime-weighting the top-5 fwd100 panel (EDA reweight, no backtest)",
                 weight="bold")
    plt.tight_layout()
    out = ROOT / "data/model_output_eda/regime_weight/regime_weight_fwd100.png"
    out.parent.mkdir(exist_ok=True)
    plt.savefig(out, dpi=110, bbox_inches="tight")
    print("saved", out)


if __name__ == "__main__":
    main()
