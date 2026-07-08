"""User follow-ups (2026-07-08):

  C6  C4 without the cumulative panel (no realistic meaning), across fwd20/50/100:
      raw daily top-5 return + smoothed line + regime shading, one row per horizon.

  C7  QUANTIFY: can any macro signal separate high- vs low-return deploy periods?
      Candidates: 6 pillars (rolling-2yr percentile, live-safe), the consolidated stress
      composite, VIX, SPY-trend. Judged by (i) Spearman rho vs top-5 fwd, (ii) tercile
      spread T3-T1, (iii) the tail cost of the winning tercile.

All on entry_timing_daily.parquet (the top-5 basket panel: fwd20/50/100 + pillars + vix + spy).
No backtest.
"""
import numpy as np, pandas as pd
import matplotlib.pyplot as plt
from matplotlib.dates import YearLocator
from scipy.stats import spearmanr
from pathlib import Path


def _root() -> Path:
    p = Path(__file__).resolve()
    for d in (p, *p.parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError("root not found")


ROOT = _root()
OUT = ROOT / "data/model_output_eda/regime_weight"
PIL = ["pil_vix", "pil_credit", "pil_term", "pil_rates", "pil_liq", "pil_cape"]


def load() -> pd.DataFrame:
    et = pd.read_parquet(ROOT / "data/model_output_eda/entry_timing/entry_timing_daily.parquet")
    et = et.sort_values("date").reset_index(drop=True)
    for c in PIL:                                    # rolling 2yr percentile (live-safe; handles trending liq/cape)
        et[c + "_rp"] = et[c].rolling(504, min_periods=126).apply(
            lambda x: (x.iloc[-1] >= x).mean(), raw=False)
    return et


def regime() -> pd.DataFrame:
    dd = pd.read_parquet(ROOT / "data/model_output_eda/regime_state/regime_state_daily_dd.parquet")
    return dd[["date", "state"]]


def shade(ax, reg: pd.DataFrame) -> None:
    r = reg.sort_values("date").reset_index(drop=True)
    r["blk"] = (r.state != r.state.shift()).cumsum()
    for _, g in r.groupby("blk"):
        col = {"bear": "#e57373", "bull-stress": "#ffcc80"}.get(g.state.iloc[0])
        if col:
            ax.axvspan(g.date.iloc[0], g.date.iloc[-1], color=col, alpha=.25, lw=0)


SIGS = {                                             # signal -> label
    "pil_vix_rp": "VIX 2yr-pct", "pil_credit_rp": "Credit 2yr-pct", "pil_term_rp": "Term 2yr-pct",
    "pil_rates_rp": "Rates 2yr-pct", "pil_liq_rp": "Liquidity 2yr-pct", "pil_cape_rp": "CAPE 2yr-pct",
    "stress_ew_vix": "stress composite", "vix_close": "VIX raw level",
    "spy_above200": "SPY>200d", "spy_ret60": "SPY 60d mom",
}


def quantify(et: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for s, lbl in SIGS.items():
        row = {"signal": lbl}
        for h in ("fwd20", "fwd50", "fwd100"):
            d = et[[s, h]].dropna()
            row[f"rho_{h}"] = spearmanr(d[s], d[h]).correlation
        # tercile spread on fwd100
        d = et[[s, "fwd100"]].dropna().copy()
        if d[s].nunique() <= 2:
            g = d.groupby(s)["fwd100"].mean() * 100
            row["spread_T3_T1"] = g.iloc[-1] - g.iloc[0]
        else:
            d["t"] = pd.qcut(d[s], 3, labels=[0, 1, 2], duplicates="drop")
            g = d.groupby("t", observed=True)["fwd100"].mean() * 100
            row["spread_T3_T1"] = g.iloc[-1] - g.iloc[0]
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    et = load()
    reg = regime()
    fwds = ["fwd20", "fwd50", "fwd100"]

    # ---- C6: multi-horizon raw daily top-5 return, regime-shaded ----
    fig, ax = plt.subplots(3, 1, figsize=(16, 11), sharex=True)
    for a, h in zip(ax, fwds):
        shade(a, reg)
        y = et.set_index("date")[h] * 100
        a.scatter(y.index, y.values, s=4, alpha=.2, color="#1565c0")
        a.plot(y.rolling(63, min_periods=10).mean().index,
               y.rolling(63, min_periods=10).mean().values, color="#0d47a1", lw=1.5,
               label=f"{h} 63d-avg")
        a.axhline(0, color="k", lw=.7)
        a.axhline(y.mean(), color="#c62828", ls="--", lw=1, label=f"mean {y.mean():+.1f}%")
        a.set_ylabel(f"top-5 {h} (%)"); a.legend(loc="upper left", fontsize=9)
    ax[0].set_title("C6 - daily top-5 basket return by horizon (shade: red=bear, orange=bull-stress)",
                    weight="bold")
    ax[-1].set_xlabel("date"); ax[-1].xaxis.set_major_locator(YearLocator(2))
    ax[-1].tick_params(axis="x", labelrotation=45)
    plt.tight_layout(); plt.savefig(OUT / "return_by_horizon.png", dpi=110, bbox_inches="tight")
    print("saved", OUT / "return_by_horizon.png")

    # ---- C7: quantification table + spread bar chart ----
    q = quantify(et)
    pd.set_option("display.float_format", lambda x: f"{x:+.3f}")
    print("\n=== C7 quantify: does a macro signal separate high/low return periods? ===")
    print(q.to_string(index=False))
    q.to_csv(OUT / "return_vs_macro_quantify.csv", index=False)

    qs = q.sort_values("spread_T3_T1")
    fig, ax = plt.subplots(1, 2, figsize=(15, 6))
    cols = ["#c62828" if v < 0 else "#2e7d32" for v in qs["spread_T3_T1"]]
    ax[0].barh(qs["signal"], qs["spread_T3_T1"], color=cols)
    ax[0].axvline(0, color="k", lw=.8)
    ax[0].set_xlabel("fwd100 spread: top-tercile − bottom-tercile (%)")
    ax[0].set_title("which signal separates high/low return periods?", weight="bold")
    for i, v in enumerate(qs["spread_T3_T1"]):
        ax[0].text(v + (0.3 if v >= 0 else -0.3), i, f"{v:+.1f}", va="center",
                   ha="left" if v >= 0 else "right", fontsize=9)

    # tail cost of the winning tercile (stress composite): mean vs worst-decile per tercile
    d = et[["stress_ew_vix", "fwd100"]].dropna().copy()
    d["t"] = pd.qcut(d["stress_ew_vix"], 3, labels=["low", "mid", "high"])
    gm = d.groupby("t", observed=True)["fwd100"].mean() * 100
    gw = d.groupby("t", observed=True)["fwd100"].apply(
        lambda x: x.nsmallest(max(1, len(x) // 10)).mean()) * 100
    x = np.arange(3)
    ax[1].bar(x - .2, gm.values, .4, label="mean", color="#2e7d32")
    ax[1].bar(x + .2, gw.values, .4, label="worst-decile", color="#c62828")
    ax[1].set_xticks(x); ax[1].set_xticklabels(gm.index)
    ax[1].axhline(0, color="k", lw=.8); ax[1].legend()
    ax[1].set_title("stress composite tercile: high mean BUT worst tail (the catch)", weight="bold")
    ax[1].set_ylabel("fwd100 (%)"); ax[1].set_xlabel("stress tercile")
    plt.tight_layout(); plt.savefig(OUT / "return_vs_macro.png", dpi=110, bbox_inches="tight")
    print("saved", OUT / "return_vs_macro.png")


if __name__ == "__main__":
    main()
