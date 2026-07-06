# Notebook cells — macro scores vs start-time sweep return

Paste into `notebooks/s13_bt_strategy.ipynb` (append at end). Answers: *does the macro
model tell you a good day to start trading?* Joins each rolling-sweep start date to what
M03 / the 5-factor model said that day, then correlates against the forward 12m return.

Prereqs already in the notebook: `ROOT`, `DB` (or `DB_PATH`). All read-only.

> **Scale gotcha (from regime_model.md §3):** M03 raw `score` is **0–100**. 5-factor
> `target_exposure` is 0–1. Don't mix them on one axis.

---

### Cell A — markdown

```markdown
## Macro timing: do the regime models call the good start dates?

The champion's edge is start-time dependent (rolling sweep: ann_return −24%..+109%).
If a macro score on the start date correlates with the forward 12m return, it's a timing
lever. M03's own doc says it's a *coincident* descriptor, not a forward predictor — so a
flat/near-zero correlation here would *confirm* that, and a positive one would be news.
```

### Cell B — load the sweep + macro scores

```python
import json
import pandas as pd
from src.pipeline.m03_regime import M03RegimeCalculator
from src.pipeline.risk_5_factor import RiskFiveFactorCalculator

SWEEP = ROOT / "data" / "selection_sweep" / "starttime" / "champion" / "rolling" / "summary.json"
sweep = pd.DataFrame(json.load(open(SWEEP))["cells"])
sweep = sweep[sweep["sharpe"].notna()].copy()
sweep["start"] = pd.to_datetime(sweep["start"])
lo, hi = sweep["start"].min().strftime("%Y-%m-%d"), sweep["start"].max().strftime("%Y-%m-%d")
print(f"{len(sweep)} cells · starts {lo}..{hi}")

# M03 (0-100 score + pillars) over the sweep span. Live calc — parquet is stale (<=2026-01-31).
m03 = M03RegimeCalculator().calculate_history_vectorized(lo, hi, freq="D")
m03 = m03[["score", "trend_score", "liquidity_score", "risk_appetite_score"]].rename(
    columns={"score": "m03_score"})

# 5-factor exposure model (0-1 target_exposure, weighted_z, veto)
r5 = RiskFiveFactorCalculator(db_path=str(DB)).compute_history(start_date=lo)
r5 = r5[["target_exposure", "weighted_z", "rolling_percentile", "veto_flag"]]

# as-of join: macro value on-or-before each start date (start dates are month-anchored,
# may land on a non-trading day — backward asof avoids NaN)
def asof_join(left, right, cols):
    r = right.sort_index()
    out = pd.merge_asof(left.sort_values("start"), r[cols], left_on="start",
                        right_index=True, direction="backward")
    return out

df = asof_join(sweep, m03, m03.columns.tolist())
df = asof_join(df, r5, r5.columns.tolist())
df[["start", "ann_return", "sharpe", "m03_score", "target_exposure", "weighted_z", "veto_flag"]].round(3)
```

### Cell C — scatter grid: each macro signal vs forward ann_return

```python
import matplotlib.pyplot as plt
from scipy.stats import spearmanr

SIGNALS = [("m03_score", "M03 score (0-100)"),
           ("risk_appetite_score", "M03 risk-appetite pillar"),
           ("target_exposure", "5-factor target exposure (0-1)"),
           ("weighted_z", "5-factor weighted-z (higher=safer)"),
           ("rolling_percentile", "5-factor percentile"),
           ("liquidity_score", "M03 liquidity pillar")]

fig, axes = plt.subplots(2, 3, figsize=(16, 9))
for ax, (col, label) in zip(axes.ravel(), SIGNALS):
    x, y = df[col].astype(float), df["ann_return"].astype(float) * 100
    rho, p = spearmanr(x, y, nan_policy="omit")
    sc = ax.scatter(x, y, c=df["start"].map(pd.Timestamp.toordinal), cmap="viridis", s=45)
    ax.axhline(0, color="grey", ls="--", lw=0.8)
    ax.set_xlabel(label); ax.set_ylabel("fwd 12m ann_return %")
    ax.set_title(f"{label}\nSpearman ρ={rho:+.2f} (p={p:.2f})", fontsize=10)
    ax.grid(alpha=0.3)
cb = fig.colorbar(sc, ax=axes, shrink=0.6, pad=0.01)
cb.set_label("start date (→ later)")
fig.suptitle("Macro score on start-date vs forward 12m return (each dot = one sweep cell)",
             fontweight="bold")
plt.show()
```

### Cell D — timeline: macro score and forward return share an x-axis

```python
fig, ax1 = plt.subplots(figsize=(15, 5))
ax1.bar(df["start"], df["ann_return"] * 100, width=20,
        color=["#2e7d32" if v > 0 else "#c62828" for v in df["ann_return"]],
        alpha=0.6, label="fwd 12m ann_return %")
ax1.axhline(0, color="black", lw=0.6); ax1.set_ylabel("fwd 12m ann_return %")
ax2 = ax1.twinx()
ax2.plot(df["start"], df["m03_score"], color="#1f77b4", lw=2, marker="o", ms=3, label="M03 (0-100)")
ax2.plot(df["start"], df["target_exposure"] * 100, color="#ff7f0e", lw=2, ls="--",
         marker="s", ms=3, label="5-factor exposure ×100")
ax2.set_ylabel("macro score")
# mark 5-factor vetoes
for _, r in df[df["veto_flag"] == True].iterrows():
    ax1.axvline(r["start"], color="purple", ls=":", alpha=0.5)
ax1.set_title("Did a high macro score on the start date precede a good year? "
              "(purple = 5-factor veto active)")
fig.legend(loc="upper right", bbox_to_anchor=(0.9, 0.88)); plt.show()
```

### Cell E — the money question: bucket return by macro regime on entry

```python
# If the macro model is a timing lever, high-regime starts should out-earn low-regime starts.
df["m03_bucket"] = pd.cut(df["m03_score"], [0, 45, 60, 100],
                          labels=["neutral/bear <45", "bull 45-60", "strong_bull >60"])
by_regime = df.groupby("m03_bucket", observed=True)["ann_return"].agg(
    ["count", "mean", "median", lambda s: (s > 0).mean()]).round(3)
by_regime.columns = ["n_starts", "mean_ann_ret", "median_ann_ret", "hit_rate"]
print(by_regime)
print("\nVeto-active vs veto-off start dates:")
print(df.groupby("veto_flag")["ann_return"].agg(["count", "mean", "median"]).round(3))
```

### Cell F — markdown (fill in after running)

```markdown
### Read

- **Spearman ρ (Cell C):** |ρ| < ~0.3 with p>0.1 on all six ⇒ no start-timing alpha —
  *confirms* M03 is coincident (regime_model.md §2/§6). A clean positive ρ on `target_exposure`
  or `weighted_z` would be the exception worth chasing (5-factor is the exposure model, not M03).
- **Regime buckets (Cell E):** if strong_bull-start mean ann_return ≈ neutral-start, the score
  doesn't pick good entry windows. If veto-off >> veto-on, the *veto* is the usable lever
  (matches the regime_model.md §8 roadmap item: veto_flag is the one forward-negative signal).
```

---

**Skipped:** the `matrix`/`horizon` grids (same join, swap the `SWEEP` path — add only if `rolling` shows signal).
**Skipped:** re-running the sweep — uses the cached `summary.json`. Re-run `scripts/run_starttime_sweep.py` first if the champion config changed.
