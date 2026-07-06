# BackTrader results analysis — notebook cells

Runnable cells for a new notebook (e.g. `notebooks/s13_bt_results.ipynb`). Loads the cached
grid artifacts under `data/selection_sweep/{tier3_grid,exit_grid,backtrader_confirm,wfo_gate}/`
and plots equity curves, drawdown, exit mix, per-year PnL, the Tier-3 interaction, and the OOS gate.

> **Data note:** `equity.parquet` now carries a `date` column (harness fixed 2026-07-05). If an old
> parquet lacks it, re-run `python scripts/run_strategy_confirm.py --grid <g>` — that grid's equity
> was written pre-fix and has no date axis.

Copy each fenced block into its own cell, top to bottom.

---

## Cell 1 — imports + paths

```python
from pathlib import Path
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

SWEEP = Path("data/selection_sweep")   # run from repo root
GRIDS = {
    "tier3":   SWEEP / "tier3_grid",
    "exit":    SWEEP / "exit_grid",
    "confirm": SWEEP / "backtrader_confirm",
}
plt.rcParams["figure.figsize"] = (12, 5)
plt.rcParams["axes.grid"] = True
```

---

## Cell 2 — loaders (one arm, and a whole grid)

```python
def load_arm(grid: str, arm: str) -> dict:
    """Load one arm's artifacts. equity has a DatetimeIndex; trades/rejections as-is."""
    d = GRIDS[grid] / arm
    eq = pd.read_parquet(d / "equity.parquet")
    if "date" in eq.columns:
        eq["date"] = pd.to_datetime(eq["date"])
        eq = eq.set_index("date")
    out = {"equity": eq, "metrics": json.loads((d / "metrics.json").read_text()),
           "config": json.loads((d / "config.json").read_text())}
    tp = d / "trades.parquet"
    if tp.exists():
        t = pd.read_parquet(tp)
        for c in ("entry_date", "exit_date"):
            t[c] = pd.to_datetime(t[c])
        out["trades"] = t
    rp = d / "rejections.parquet"
    if rp.exists():
        out["rejections"] = pd.read_parquet(rp)
    return out

def grid_arms(grid: str) -> list[str]:
    return sorted(p.name for p in GRIDS[grid].iterdir() if p.is_dir())

def load_comparison(grid: str) -> pd.DataFrame:
    """The ranked summary.json rows as a DataFrame."""
    s = json.loads((GRIDS[grid] / "summary.json").read_text())
    return pd.DataFrame(s["runs"]).sort_values("sharpe_ratio", ascending=False)

print("tier3 arms:", grid_arms("tier3"))
load_comparison("tier3")
```

---

## Cell 3 — equity curves, all arms in a grid

```python
def plot_equity(grid: str, arms: list[str] | None = None, logy: bool = True):
    arms = arms or grid_arms(grid)
    fig, ax = plt.subplots()
    for arm in arms:
        eq = load_arm(grid, arm)["equity"]
        ax.plot(eq.index, eq["value"], label=arm, lw=1.4)
    ax.set_title(f"{grid} — equity curves ($25k start)")
    ax.set_ylabel("portfolio value ($)")
    if logy:
        ax.set_yscale("log")
    ax.legend(fontsize=8, ncol=2)
    plt.tight_layout(); plt.show()

plot_equity("tier3")
```

---

## Cell 4 — champion vs old-seed head-to-head (equity + drawdown)

```python
def drawdown(eq: pd.Series) -> pd.Series:
    return eq / eq.cummax() - 1.0

WINNER, OLD = "T3_sl15_tpTight", "T3_sl10_tpDflt"   # new champion vs prior seed
w, o = load_arm("tier3", WINNER), load_arm("tier3", OLD)

fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(12, 8),
                               gridspec_kw={"height_ratios": [2, 1]})
for lbl, d, c in [(f"{WINNER} (winner)", w, "C0"), (f"{OLD} (old seed)", o, "C1")]:
    eq = d["equity"]["value"]
    ax1.plot(eq.index, eq, label=lbl, color=c, lw=1.5)
    ax2.fill_between(eq.index, drawdown(eq) * 100, 0, color=c, alpha=0.35)
ax1.set_yscale("log"); ax1.set_ylabel("equity ($, log)"); ax1.legend()
ax1.set_title("New champion vs old seed — equity & drawdown")
ax2.set_ylabel("drawdown (%)"); ax2.set_xlabel("date")
plt.tight_layout(); plt.show()

# headline metrics side by side
pd.DataFrame({WINNER: w["metrics"], OLD: o["metrics"]}).loc[
    ["sharpe_ratio", "total_return", "max_drawdown", "win_rate", "total_trades", "sqn"]
]
```

---

## Cell 5 — exit-reason mix (why we exit) + PnL by reason

```python
def exit_breakdown(grid: str, arm: str):
    t = load_arm(grid, arm)["trades"]
    g = t.groupby("exit_reason")["pnl_percent"].agg(["count", "mean"]).sort_values("count", ascending=False)
    g["pct_of_trades"] = (g["count"] / len(t) * 100).round(1)
    return g

WINNER = "T3_sl15_tpTight"
bd = exit_breakdown("tier3", WINNER)
print(bd)

fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4))
bd["count"].plot.bar(ax=a1, color="steelblue"); a1.set_title(f"{WINNER}: exit reason counts")
bd["mean"].plot.bar(ax=a2, color=["g" if v > 0 else "r" for v in bd["mean"]])
a2.set_title("avg pnl% at exit  (stop-exits POSITIVE = trailing profit-lock, not loss-cut)")
a2.axhline(0, color="k", lw=0.7)
plt.tight_layout(); plt.show()
```

---

## Cell 6 — per-year PnL (robustness: is every year positive?)

```python
def yearly_pnl(grid: str, arms: list[str]) -> pd.DataFrame:
    rows = {}
    for arm in arms:
        t = load_arm(grid, arm)["trades"]
        rows[arm] = t.assign(yr=t["entry_date"].dt.year).groupby("yr")["pnl_percent"].sum()
    return pd.DataFrame(rows)

yp = yearly_pnl("tier3", ["T3_sl15_tpTight", "T3_sl10_tpDflt"])
ax = yp.plot.bar(figsize=(11, 4))
ax.set_title("PnL%-sum by entry year — winner vs old seed (2022=bear, 2026=chop)")
ax.axhline(0, color="k", lw=0.7); ax.set_ylabel("Σ pnl_percent")
plt.tight_layout(); plt.show()
yp.round(0)
```

---

## Cell 7 — Tier-3 interaction heatmap (the finding the marginal sweep missed)

```python
comp = load_comparison("tier3").set_index("id")
# arm id = T3_<sl>_<tp>  →  pivot stop × TP
def parse(a):
    _, sl, tp = a.split("_")
    return sl, tp
rows = [(*parse(a), comp.loc[a, "sharpe_ratio"]) for a in comp.index]
piv = pd.DataFrame(rows, columns=["stop", "tp", "sharpe"]).pivot(index="stop", columns="tp", values="sharpe")

fig, ax = plt.subplots(figsize=(6, 3.5))
im = ax.imshow(piv.values, cmap="RdYlGn", aspect="auto")
ax.set_xticks(range(len(piv.columns)), piv.columns)
ax.set_yticks(range(len(piv.index)), piv.index)
for i in range(piv.shape[0]):
    for j in range(piv.shape[1]):
        ax.text(j, i, f"{piv.values[i, j]:.2f}", ha="center", va="center", fontsize=11)
ax.set_title("Tier-3 in-sample Sharpe: stop × TP\n(sl15+tpTight wins; both alone < seed)")
fig.colorbar(im, ax=ax, label="Sharpe")
plt.tight_layout(); plt.show()
```

---

## Cell 8 — OOS gate: per-fold + aggregate (proof it's not overfit)

```python
def load_gate(arm: str) -> dict:
    return json.loads((SWEEP / "wfo_gate" / f"{arm}.json").read_text())

def gate_table(arms: list[str]) -> pd.DataFrame:
    out = []
    for a in arms:
        g = load_gate(a)
        row = {"arm": a, "agg_OOS_sharpe": g["aggregate_oos"]["sharpe"],
               "agg_OOS_ret": g["aggregate_oos"].get("total_return"),
               "agg_OOS_maxDD": g["aggregate_oos"]["max_drawdown"]}
        for i, f in enumerate(g["folds"]):
            row[f"fold{i}_sharpe"] = f["sharpe"]
        out.append(row)
    return pd.DataFrame(out).set_index("arm")

gate = gate_table(["T3_sl15_tpTight", "T3_sl10_tpDflt"])
print(gate.round(2))

# per-fold OOS Sharpe bars — winner vs old seed
fold_cols = [c for c in gate.columns if c.startswith("fold")]
ax = gate[fold_cols].T.plot.bar(figsize=(9, 4))
ax.set_title("OOS Sharpe by unseen fold — winner beats seed, esp. the weak 2024 fold")
ax.axhline(0, color="k", lw=0.7); ax.set_ylabel("OOS Sharpe"); ax.set_xlabel("fold (test window)")
plt.tight_layout(); plt.show()
```

---

## Cell 9 — trade-level scatter: entry prob_elite vs realized PnL (does the score sort?)

```python
t = load_arm("tier3", "T3_sl15_tpTight")["trades"]
fig, ax = plt.subplots(figsize=(9, 5))
sc = ax.scatter(t["prob_elite"], t["pnl_percent"] * 100, c=t["holding_days"],
                cmap="viridis", alpha=0.6, s=18)
ax.axhline(0, color="k", lw=0.7)
ax.set_xlabel("prob_elite at entry"); ax.set_ylabel("realized pnl (%)")
ax.set_title("Entry score vs outcome (color = hold days)")
fig.colorbar(sc, label="holding_days")
plt.tight_layout(); plt.show()

# does higher entry score => higher avg pnl? (score-as-sorter check)
t["prob_bin"] = pd.qcut(t["prob_elite"], 5, duplicates="drop")
print(t.groupby("prob_bin", observed=True)["pnl_percent"].agg(["count", "mean"]).round(3))
```

---

## Cell 10 — inspect any single trade end-to-end (why we entered & exited)

```python
def show_trades(grid: str, arm: str, ticker: str | None = None, n: int = 10) -> pd.DataFrame:
    t = load_arm(grid, arm)["trades"]
    if ticker:
        t = t[t["ticker"] == ticker]
    cols = ["ticker", "entry_date", "entry_price", "exit_date", "exit_price",
            "exit_reason", "entry_regime", "prob_elite", "pnl_percent", "holding_days", "mae_pct"]
    return t.sort_values("pnl_percent", ascending=False)[cols].head(n)

# biggest winners of the champion
show_trades("tier3", "T3_sl15_tpTight", n=10)
```

---

## Cell 11 — rejection audit (why candidates did NOT enter)

```python
r = load_arm("tier3", "T3_sl15_tpTight")["rejections"]
print("total rejections:", len(r))
print(r["reason"].value_counts())
# no_slots dominating => the book is capacity-bound, not signal-bound (working as designed)
r["reason"].value_counts().plot.bar(figsize=(8, 3), title="rejection reasons (why we didn't enter)")
plt.tight_layout(); plt.show()
```
