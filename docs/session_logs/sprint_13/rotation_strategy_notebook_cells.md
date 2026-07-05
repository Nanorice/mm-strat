# Rotation Strategy — Notebook Cells

> Copy each block into a cell of a new notebook (e.g. `notebooks/rotation_strategy.ipynb`).
> Runs the E1 (immediate entry) baseline vs E2 (delayed conditional entry) on **m01_prototype**
> prod scores with a real **$25k cash cap**, plus your requested plots. Per project rule, edit
> the notebook by pasting these — not the `.ipynb` directly.
>
> **Window caveat (regime-limited):** prototype prod scores only cover 2025-10-06 onward — a short,
> strong-tape stretch. Treat every number here as *illustrative, not a go/no-go*. The honest
> multi-regime read comes from re-running the same configs on `m01_binary` (2021→2026) later.

---

## Cell 1 — setup

```python
import sys, os
sys.path.insert(0, os.path.abspath(".."))  # repo root, so `src` imports

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

from src import db
from src.backtest.runner import SEPABacktestRunner
from src.backtest.score_lookup import prototype_scores_to_contract

DB_PATH = "../data/market_data.duckdb"
PROTO_VERSION = "m01_prototype_2003_2026_20260514_233125"
START, END = "2025-10-06", "2026-05-22"   # prototype prod-score coverage
INITIAL_CASH = 25_000
```

## Cell 2 — load prototype scores (read-only DB)

```python
con = db.connect(DB_PATH, read_only=True)     # read_only or the kernel locks the DB
raw = con.execute("""
    SELECT prediction_date AS date, ticker, prob_class_3 AS prob_elite
    FROM daily_predictions
    WHERE model_version_id = ? AND prediction_date BETWEEN ? AND ?
""", [PROTO_VERSION, START, END]).df()
con.close()

scores = prototype_scores_to_contract(raw)    # -> full ScoreLookup contract
print(f"{len(scores):,} score rows · {scores['ticker'].nunique()} tickers · "
      f"{scores['date'].nunique()} days")
scores.head()
```

## Cell 3 — the two configs

```python
# Shared knobs: top-5/day, prob_elite ranking, $25k equal-weight, whole-position SL,
# staged TP (T1 +15% / T2 +2ATR / T3 SMA-trail — now decoupled via sma_exit_independent).
BASE = dict(
    entry_mode="top_n", entry_top_n=5, rank_by="prob_elite", min_score=0,
    regime_max_pos={0: 0, 1: 5, 2: 5, 3: 5, 4: 5},   # $25k -> ~5 slots
    sizing_mode="equal_weight",
    max_stop_pct=0.10,           # X1 hard SL 10%
    sma_exit_independent=True,   # X3 MA cross exits any open position
    min_hold_days=3,             # don't churn on a one-day dip
)

# Sweep p(home) entry threshold here:
PROB_THRESH = 0.60               # try 0.50 / 0.60 / 0.70

CONFIGS = {
    # E1: enter immediately on qualifying
    "E1_immediate": {**BASE, "min_prob_elite": PROB_THRESH, "entry_delay_days": 0},
    # E2: wait 3 days, enter only if return-since-join in [-5%, +15%]
    #     (skips names already spent, per A3; skips failing names)
    "E2_delay3_band": {**BASE, "min_prob_elite": PROB_THRESH,
                       "entry_delay_days": 3, "entry_ret_lo": -0.05, "entry_ret_hi": 0.15,
                       # X2 rotation: exit if prob_elite drops >0.15 from entry or below 0.30
                       "score_drop_thresh": 0.15, "score_exit_floor": 0.30},
}
```

## Cell 4 — run both (each ~1–2 min)

```python
def run_cfg(name, kwargs):
    r = SEPABacktestRunner(start_date=START, end_date=END, initial_cash=INITIAL_CASH,
                           db_path=DB_PATH, model_path=None, model_version_id=None)
    r.setup(scores_df=scores, strategy_kwargs=kwargs)
    metrics = r.run()
    return r, metrics

runs = {}
for name, kw in CONFIGS.items():
    print(f"running {name} ...")
    runs[name] = run_cfg(name, kw)
    print(f"  done: {runs[name][1].get('total_return'):+.1f}% "
          f"sharpe={runs[name][1].get('sharpe_ratio')}")
```

## Cell 5 — comparison table

```python
rows = []
for name, (r, m) in runs.items():
    tr = r.get_trade_dataframe()
    rows.append({
        "config": name,
        "trades": m.get("total_trades"),
        "total_ret_%": round(m.get("total_return", 0), 1),
        "sharpe": round(m.get("sharpe_ratio") or 0, 2),
        "maxDD_%": round(m.get("max_drawdown", 0), 1),
        "win_%": round(m.get("win_rate", 0), 1),
        "avg_hold_d": round(tr["holding_days"].mean(), 1) if tr is not None and len(tr) else None,
        "exits": tr["exit_reason"].value_counts().to_dict() if tr is not None and len(tr) else {},
    })
pd.DataFrame(rows).set_index("config")
```

## Cell 6 — equity curves + exposure (your capital-constraint view)

```python
fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=True)
for name, (r, m) in runs.items():
    eq = r.get_equity_curve_dataframe()
    axes[0].plot(eq.index, eq["value"], label=name, lw=1.5)
    axes[1].plot(eq.index, eq["position_count"], label=name, lw=1.2)
axes[0].axhline(INITIAL_CASH, color="grey", ls="--", lw=0.8)
axes[0].set_ylabel("Equity ($)"); axes[0].set_title(f"Equity — $25k cap, p(home)>{PROB_THRESH}")
axes[0].legend(); axes[0].grid(alpha=0.3)
axes[1].set_ylabel("Open positions"); axes[1].set_xlabel("Date")
axes[1].set_title("Slots used (capital constraint bites when this hits the cap)")
axes[1].grid(alpha=0.3)
plt.tight_layout(); plt.show()
```

## Cell 7 — turnover (rotation costs money — watch this)

```python
# Turnover proxy: entries per week. High turnover = commission/slippage bleed.
fig, ax = plt.subplots(figsize=(13, 3.5))
for name, (r, m) in runs.items():
    tr = r.get_trade_dataframe()
    if tr is None or not len(tr): continue
    entries = pd.to_datetime(tr["entry_date"]).dt.to_period("W").value_counts().sort_index()
    ax.plot(entries.index.to_timestamp(), entries.values, marker="o", ms=3, label=name)
ax.set_ylabel("Entries / week"); ax.set_title("Turnover — the rotation tax")
ax.legend(); ax.grid(alpha=0.3); plt.tight_layout(); plt.show()
```

## Cell 8 — exit-reason mix (did rotation/score-drop actually fire?)

```python
fig, axes = plt.subplots(1, len(runs), figsize=(6*len(runs), 4))
if len(runs) == 1: axes = [axes]
for ax, (name, (r, m)) in zip(axes, runs.items()):
    tr = r.get_trade_dataframe()
    if tr is not None and len(tr):
        tr["exit_reason"].value_counts().plot.pie(ax=ax, autopct="%1.0f%%")
    ax.set_title(name); ax.set_ylabel("")
plt.tight_layout(); plt.show()
```

## Cell 9 — full BackTrader diagnostic panel (per config)

```python
# The runner's built-in 6-panel: equity+regime, underwater, monthly heatmap,
# per-trade PnL, PnL-by-regime, exit reasons.
r, m = runs["E2_delay3_band"]
r.plot()
```

---

## What to read for / next steps

1. **Does E2 beat E1?** Compare Cell-5 Sharpe/return. If E2 wins, the "wait for the pullback"
   thesis (Goal B mean-reversion) holds on the live signal. If not, immediate entry is fine and
   E2 is complexity you can drop.
2. **Is the cap binding?** Cell-6 lower panel — if position_count sits pinned at 5, capital is the
   constraint and rank quality matters more than adding rules.
3. **Is rotation paying for its turnover?** Cell-7 vs Cell-5 — if E2 churns a lot (high entries/wk)
   but doesn't out-return E1, the `score_drop`/band rules are just bleeding costs.
4. **Sweep** `PROB_THRESH ∈ {0.5, 0.6, 0.7}` and the E2 band `entry_ret_hi ∈ {0.10, 0.15, 0.20}`.
5. **Honest number:** re-run the winning config on `m01_binary` 2021→2026 (spans 2022 bear) via
   `score_from_t3` instead of the prototype adapter — that's the go/no-go, not this window.
6. **Overfit gate:** once a config looks good, WFO it (the arena ladder step 3) before trusting it.
```
