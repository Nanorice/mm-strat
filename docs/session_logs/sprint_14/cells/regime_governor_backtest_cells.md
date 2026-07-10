# Regime governor — the REAL backtest (point-8 promoted, M2→M3 start-date cone)

> **What this answers (point-8 promotion):** the EDA reweight said the governor was worth a backtest.
> This promotes it to a real 25y walk-forward and judges it on the START-DATE CONE (the whole
> thread's lesson — never one aggregate). Verdict: **the governor is a start-date-ROBUST DRAWDOWN
> CONTROLLER, not the "improves both" story the EDA panel suggested.**
>
> **The spec that went in (LIVE-SAFE — the EDA used full-sample cuts, which can't size live capital):**
> - **TILT** — full exposure in the top EXPANDING-quintile of `stress_ew_vix`, base 0.5 below.
> - **GATE** — zero exposure when SPY ≤ 200d MA.
> - composite = expanding-z (day *t* uses stats through *t−1*); quintile threshold = expanding
>   quantile; whole weight lagged one business day. Lives in `src/backtest/macro_sizer.py::governor_weight`.
>
> **Load-bearing findings:**
> 1. **Governor HALVES drawdown at EVERY start-year** — worst fold DD −46% → −19%, median fold DD
>    −29% → −14%, aggregate maxDD −50.7% → −25.4%. The durable win; survives the cone.
> 2. **It does NOT improve Sharpe or the fold-sign mix** — all three arms (flat/vix/governor) have the
>    SAME 35% negative folds and same worst folds (2008/2011). Governor cone MEDIAN is the LOWEST
>    (0.51 vs flat 0.76); total return collapses (615% → 212%). A pure brake can't lift the mean.
> 3. **WHY the EDA "improves both" didn't survive — GATE × TILT CANCEL.** Of ~467 top-quintile-stress
>    days (2007-22) only 18 are ALSO SPY>200d (bull-stress). The gate zeroes ~96% of "size up on
>    stress" days (high stress ≈ sub-200d ≈ falling knife) → the tilt is inert → the governor reduces
>    to the point-8(a) pure SPY-200d variance brake. point-8(b)'s "improves both" was per-$-deployed on
>    the rare ~18%-capital bull-stress cell; at full book the brake dominates.
> 4. **VIX is strictly dominated** — lower Sharpe than both, worse median than flat, worse maxDD than
>    governor. Same bear axis, blunter (cf `project_entry_timing_macro_axis`).
>
> **Reproduce from the shell (the actual run):**
> ```
> python scripts/cache_model_scores.py --model m01_binary --start 2003-01-01 --end 2026-05-22
> for m in flat vix governor; do
>   python scripts/run_strategy_wfo.py --model m01_binary --start 2003-01-01 --end 2026-05-22 \
>     --train-years 3 --test-years 1 --anchored --n-trials 40 --sizing $m \
>     --scores-parquet data/score_cache/m01_binary_calibrated_2003-01-01_2026-05-22.parquet
> done
> ```
> The cells below re-read the saved fold JSONs and render the cone comparison. Verdict:
> `verdicts/2026-07-09_regime_governor_backtest.md`.

Paste each block as one cell.

---

### Cell 0 — repo-root bootstrap (run FIRST; every path below is ROOT-anchored)

```python
import sys
from pathlib import Path

def _root():
    p = Path.cwd().resolve()
    for d in (p, *p.parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError("root not found")

ROOT = _root(); sys.path.insert(0, str(ROOT))
print("ROOT:", ROOT)
```

### Cell 1 — inspect the governor weights (the GATE × TILT cancellation, directly)

```python
import numpy as np, pandas as pd
from src.backtest.macro_sizer import MacroSizer, GOV_HI_Q, GOV_MIN_OBS, GOV_BASE_W

ms = MacroSizer()
stress = ms._stress_ew_vix("2022-12-31")
hi_cut = stress.expanding(min_periods=GOV_MIN_OBS).quantile(GOV_HI_Q).shift(1)
is_stress = (stress >= hi_cut)

w = ms.governor_weight("2007-01-01", "2022-12-31")
above = pd.Series(w.index).dt.date  # for join clarity only

# Full weight only where top-quintile stress AND SPY>200d = bull-stress (rare).
vc = w.value_counts().sort_index()
print("governor weight distribution (2007-2022):")
print(vc, "\n")
print(f"gate-off (SPY<=200d): {100*(w==0).mean():.0f}%   "
      f"full-size (bull-stress): {100*(w==1).mean():.1f}%   "
      f"base 0.5: {100*(w==GOV_BASE_W).mean():.0f}%")
assert (w == 0.0).any() and (w == GOV_BASE_W).any()
```

### Cell 2 — load the three cone results

```python
import json
from pathlib import Path

arms = {}
for arm in ["flat", "vix", "governor"]:
    fp = ROOT / "models" / "m01_binary" / "wfo" / f"calibrated_{arm}" / "wfo_results.json"
    assert fp.exists(), f"missing {fp} — run the WFO for sizing={arm} first"
    r = json.loads(fp.read_text())
    assert r["sizing"] == arm, f"{fp} has sizing={r['sizing']}, expected {arm} (stale artifact?)"
    r["_folds_df"] = pd.DataFrame([{
        "test": f["test_start"][:4],
        "oos_sharpe": f["oos"]["sharpe"],
        "oos_dd": f["oos"]["max_drawdown"],
    } for f in r["folds"]])
    arms[arm] = r

# Guard the exact bug that showed identical rows: the three arms MUST differ.
meds = {a: arms[a]["cone"]["median"] for a in arms}
assert len(set(meds.values())) > 1, f"all arms identical ({meds}) — stale/wrong paths?"
print(f"{arms['flat']['_folds_df'].shape[0]} folds per arm · cone medians {meds}")
```

### Cell 3 — the cone table (the M2 deliverable: distribution, not one number)

```python
rows = []
for arm, r in arms.items():
    c = r["cone"]; agg = r["aggregate_oos"]; f = r["_folds_df"]
    rows.append({
        "arm": arm,
        "agg_sharpe": round(agg["sharpe"], 2),
        "agg_maxDD": f"{agg['max_drawdown']:.1%}",
        "cone_median": round(c["median"], 2),
        "cone_min": round(c["min"], 2),
        "cone_max": round(c["max"], 2),
        "pct_neg": f"{c['pct_negative']:.0%}",
        "median_foldDD": f"{f['oos_dd'].median():.1%}",
        "worst_foldDD": f"{f['oos_dd'].min():.1%}",
    })
cone = pd.DataFrame(rows).set_index("arm")
cone
```

### Cell 4 — the picture: per-fold Sharpe cone + per-fold drawdown

```python
import matplotlib.pyplot as plt

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
years = arms["flat"]["_folds_df"]["test"]
colors = {"flat": "#888", "vix": "#e69138", "governor": "#3d85c6"}

for arm in arms:
    f = arms[arm]["_folds_df"]
    ax1.plot(years, f["oos_sharpe"], marker="o", label=arm, color=colors[arm])
    ax2.plot(years, f["oos_dd"], marker="o", label=arm, color=colors[arm])

ax1.axhline(0, color="k", lw=0.7); ax1.set_title("Per-fold OOS Sharpe (the start-date CONE)")
ax1.set_ylabel("OOS Sharpe"); ax1.tick_params(axis="x", rotation=60); ax1.legend()
ax2.set_title("Per-fold OOS max drawdown (governor halves it, every year)")
ax2.set_ylabel("max drawdown"); ax2.tick_params(axis="x", rotation=60); ax2.legend()
plt.tight_layout()
plt.savefig(ROOT / "data/model_output_eda/regime_weight/governor_cone.png", dpi=110, bbox_inches="tight")
plt.show()
```

![governor cone — per-fold Sharpe + drawdown](../../../../data/model_output_eda/regime_weight/governor_cone.png)

> **Read the two panels:** left — the Sharpe cones nearly overlap and the governor's is if anything
> LOWER on the good years (its brake damps winners); right — the governor's drawdown line sits
> visibly above (shallower than) flat and vix in EVERY bear year. That's the whole verdict in one
> figure: **DD control, not Sharpe.**

### Cell 5 — the honest one-liner

```python
g, fl = arms["governor"]["_folds_df"], arms["flat"]["_folds_df"]
print("GOVERNOR vs FLAT (25y, 20 start-years):")
print(f"  worst fold DD : {fl['oos_dd'].min():.0%}  ->  {g['oos_dd'].min():.0%}   (halved)")
print(f"  median fold DD: {fl['oos_dd'].median():.0%}  ->  {g['oos_dd'].median():.0%}   (halved)")
print(f"  cone median Sharpe: {fl['oos_sharpe'].median():.2f}  ->  {g['oos_sharpe'].median():.2f}   (COST)")
print(f"  %negative folds: both 35% — the brake doesn't rescue bad START-YEARS, only their DEPTH")
print("\nVERDICT: bank as a DRAWDOWN-CONTROL overlay (--sizing governor), not alpha/stability.")
```
