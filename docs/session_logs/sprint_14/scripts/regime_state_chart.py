"""M6 regime-state figures — the 4 panels that explain the classification.

Renders (and saves PNGs the review cells embed):
  1. SPY price + 200d MA, background shaded by state   -> WHERE each state fires vs price
  2. Threshold mechanics: drawdown% (10% cut) + SPY %-distance-to-200d (0 cut) -> the METRICS
  3. State timeline ribbon 2000-2026                    -> the regime sequence + flicker
  4. M4 cond_lift10 by state, dd vs macro side-by-side  -> the counter-cyclical edge

  python docs/session_logs/sprint_14/scripts/regime_state_chart.py            # dd axis
  python docs/session_logs/sprint_14/scripts/regime_state_chart.py --axis macro
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Patch


def _root() -> Path:
    p = Path.cwd().resolve()
    for d in (p, *p.parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError("root not found")


ROOT = _root()
EDA = ROOT / "data" / "model_output_eda" / "regime_state"
DB = ROOT / "data" / "market_data.duckdb"

COLORS = {"bear": "#c62828", "bull-stress": "#ef6c00", "bull-calm": "#2e7d32"}
DD_HI = 0.10


def load(axis: str) -> pd.DataFrame:
    df = pd.read_parquet(EDA / f"regime_state_daily_{axis}.parquet")
    df["date"] = pd.to_datetime(df["date"])
    con = duckdb.connect(str(DB), read_only=True)
    try:
        spy = con.execute(
            "SELECT date, spy_close FROM t1_macro WHERE spy_close IS NOT NULL ORDER BY date").df()
    finally:
        con.close()
    spy["date"] = pd.to_datetime(spy["date"])
    spy["ma200"] = spy["spy_close"].rolling(200).mean()
    return df.merge(spy, on="date", how="left").sort_values("date").reset_index(drop=True)


def _shade_by_state(ax, df):
    """Shade the x-axis background by contiguous state runs."""
    df = df.reset_index(drop=True)
    grp = (df["state"] != df["state"].shift()).cumsum()
    for _, r in df.groupby(grp):
        ax.axvspan(r["date"].iloc[0], r["date"].iloc[-1], color=COLORS[r["state"].iloc[0]], alpha=0.18, lw=0)


def fig_price_ma(df, axis):
    fig, ax = plt.subplots(figsize=(16, 6))
    _shade_by_state(ax, df)
    ax.plot(df["date"], df["spy_close"], color="#1a1a1a", lw=1.1, label="SPY close")
    ax.plot(df["date"], df["ma200"], color="#1565c0", lw=1.4, ls="--", label="200d MA (bull/bear line)")
    ax.set_title(f"1 · SPY vs 200d MA, shaded by regime state (axis={axis}) — "
                 "bear = SPY below the blue line", weight="bold")
    ax.set_ylabel("SPY"); ax.legend(loc="upper left", fontsize=9)
    ax.legend(handles=ax.get_legend().legend_handles +
              [Patch(color=c, alpha=0.35, label=s) for s, c in COLORS.items()],
              loc="upper left", fontsize=9)
    fig.tight_layout()
    p = EDA / f"fig1_price_ma_{axis}.png"; fig.savefig(p, dpi=110); plt.close(fig)
    return p


def fig_thresholds(df, axis):
    fig, ax = plt.subplots(2, 1, figsize=(16, 8), sharex=True)
    # (a) drawdown-from-peak with the 10% stress cut
    ax[0].fill_between(df["date"], df["spy_dd"] * 100, color="#ef6c00", alpha=0.35)
    ax[0].axhline(DD_HI * 100, color="#c62828", ls="--", lw=1.5,
                  label=f"stress cut = {DD_HI:.0%} drawdown (dd axis)")
    ax[0].set_ylabel("SPY drawdown %"); ax[0].invert_yaxis()
    ax[0].set_title("2 · the THRESHOLD metrics", weight="bold")
    ax[0].legend(fontsize=9, loc="lower left")
    # (b) SPY %-distance to 200d MA with the 0 (bull/bear) line
    dist = (df["spy_close"] / df["ma200"] - 1) * 100
    ax[1].fill_between(df["date"], dist, 0, where=(dist >= 0), color="#2e7d32", alpha=0.35)
    ax[1].fill_between(df["date"], dist, 0, where=(dist < 0), color="#c62828", alpha=0.35)
    ax[1].axhline(0, color="#1565c0", ls="--", lw=1.5, label="bull/bear line (dist to 200d = 0)")
    ax[1].set_ylabel("SPY % above/below 200d"); ax[1].set_xlabel("date")
    ax[1].legend(fontsize=9, loc="lower left")
    fig.tight_layout()
    p = EDA / f"fig2_thresholds_{axis}.png"; fig.savefig(p, dpi=110); plt.close(fig)
    return p


def fig_ribbon(df, axis):
    fig, ax = plt.subplots(figsize=(16, 1.8))
    codes = {s: i for i, s in enumerate(["bear", "bull-stress", "bull-calm"])}
    _shade_by_state(ax, df)
    ax.set_yticks([]); ax.set_ylim(0, 1)
    ax.set_title(f"3 · state timeline ribbon (axis={axis}) — read the regime sequence + flicker",
                 weight="bold")
    ax.legend(handles=[Patch(color=c, alpha=0.35, label=s) for s, c in COLORS.items()],
              loc="upper center", ncol=3, fontsize=9, bbox_to_anchor=(0.5, -0.3))
    ax.set_xlim(df["date"].min(), df["date"].max())
    fig.tight_layout()
    p = EDA / f"fig3_ribbon_{axis}.png"; fig.savefig(p, dpi=110); plt.close(fig)
    return p


def fig_m4_edge():
    m_dd = pd.read_csv(EDA / "m4_by_state_dd.csv").set_index("state")
    m_mac = pd.read_csv(EDA / "m4_by_state_macro.csv").set_index("state")
    order = ["bull-calm", "bull-stress", "bear"]
    fig, ax = plt.subplots(figsize=(9, 6))
    x = np.arange(len(order)); w = 0.38
    b1 = ax.bar(x - w / 2, [m_dd.loc[s, "cond_lift10"] for s in order], w,
                color="#1565c0", label="dd axis")
    b2 = ax.bar(x + w / 2, [m_mac.loc[s, "cond_lift10"] for s in order], w,
                color="#ef6c00", label="macro axis")
    for bars, src in ((b1, m_dd), (b2, m_mac)):
        for r, s in zip(bars, order):
            ax.text(r.get_x() + r.get_width() / 2, r.get_height() + 0.05,
                    f"{r.get_height():.2f}\nn={int(src.loc[s,'n'])}", ha="center", fontsize=8)
    ax.axhline(1.0, color="k", ls=":", alpha=0.5, label="no skill (1×)")
    ax.set_xticks(x); ax.set_xticklabels(order)
    ax.set_ylabel("cond_lift10 (tail-ranking within top-decile)")
    ax.set_title("4 · M4 edge by state — WEAKEST in calm bull, STRONGEST under stress\n"
                 "(counter-cyclical, holds on BOTH axes)", weight="bold")
    ax.legend(fontsize=9)
    fig.tight_layout()
    p = EDA / "fig4_m4_edge.png"; fig.savefig(p, dpi=110); plt.close(fig)
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--axis", choices=["dd", "macro"], default="dd")
    args = ap.parse_args()
    df = load(args.axis)
    paths = [fig_price_ma(df, args.axis), fig_thresholds(df, args.axis),
             fig_ribbon(df, args.axis), fig_m4_edge()]
    for p in paths:
        print("saved", p.relative_to(ROOT))
    # self-check: bear shading exactly matches SPY<200d
    assert ((df["state"] == "bear") == (df["spy_above200"] == 0)).all(), "bear != SPY<200d"


if __name__ == "__main__":
    main()
