# Rotation Strategy — m01_binary Honest-Window Cells

> The trustworthy companion to the prototype notebook. Same E1-vs-E2 comparison, but on
> **m01_binary** scored via `score_from_t3` over **2021→2026** — a window that *includes the 2022
> bear*. This is the go/no-go read: a strategy that survives 2022 has edge; one that only worked
> 2025-26 was riding the tape.
>
> **Why binary, not prototype:** the two are a dead heat as a *signal* (arena Sharpe 2.00 vs 1.99),
> but binary can be scored back to 2021 (prototype prod scores start 2025-10). Paste into a new
> notebook `notebooks/s13_rotation_binary.ipynb`.
>
> **CRITICAL — thresholds do NOT transfer from prototype.** Binary's `prob_elite` is on a
> compressed scale: median ~0.06–0.09, **p99 ~0.29, max 0.50** — stable across bull/bear. A fixed
> `min_prob_elite=0.6` selects ZERO names. So this run uses **rank-based top-5 selection**
> (`rank_by='prob_elite'`, no absolute floor), which is regime-robust and matches how the arena ran
> binary. E2's score-drop knobs are rescaled to binary's spread.

---

## Cell 1 — setup

```python
import sys, os
from pathlib import Path

def _repo_root() -> Path:
    p = Path.cwd().resolve()
    for d in (p, *p.parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError(f"repo root not found above {p}")

ROOT = _repo_root()
sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

from src.backtest.runner import SEPABacktestRunner
from src.backtest.universe_scorer import UniverseScorer

DB_PATH = ROOT / "data" / "market_data.duckdb"
MODEL = str(ROOT / "models" / "m01_binary" / "v1" / "model.json")
START, END = "2021-01-01", "2026-05-22"   # spans the 2022 bear
INITIAL_CASH = 25_000
```

## Cell 2 — score the universe (this is the slow step: ~2–5 min over 5 years)

```python
# score_from_t3 computes binary scores directly — no daily_predictions injection.
# The scorer already emits the full ScoreLookup contract (normalized_score,
# daily_pct_rank, trailing_pct, prob_elite), so no adapter needed.
scorer = UniverseScorer(m01_path=MODEL, calibration_path=None)
scores = scorer.score_from_t3(START, END, db_path=DB_PATH)
print(f"{len(scores):,} rows · {scores['ticker'].nunique()} tickers · "
      f"{scores['date'].nunique()} days")
print("prob_elite:", scores['prob_elite'].describe()[['50%','max']].to_dict())
# sanity: median scored names/day should be ~2000+, top-5 always fillable
print("median names/day:", int(scores.groupby('date').size().median()))
```

## Cell 3 — the two configs (rank-based; NO absolute prob floor)

```python
# top-5/day by prob_elite rank, $25k equal-weight, whole SL, staged TP, decoupled SMA.
BASE = dict(
    entry_mode="top_n", entry_top_n=5, rank_by="prob_elite",
    min_prob_elite=0.0,          # rank-based: take top-5, no absolute gate
    min_score=0,
    regime_max_pos={0: 0, 1: 5, 2: 5, 3: 5, 4: 5},
    sizing_mode="equal_weight",
    max_stop_pct=0.10,           # X1 hard SL 10%
    sma_exit_independent=True,   # X3
    min_hold_days=3,
)

# E2 score-drop rescaled to binary's compressed range (entry prob ~0.25–0.29):
#   drop of 0.08 ≈ a real relative decay; floor 0.10 ≈ below-median.
CONFIGS = {
    "E1_immediate":  {**BASE, "entry_delay_days": 0},
    "E2_delay3_band": {**BASE,
                       "entry_delay_days": 3, "entry_ret_lo": -0.05, "entry_ret_hi": 0.15,
                       "score_drop_thresh": 0.08, "score_exit_floor": 0.10},
}
```

## Cell 4 — run both

```python
def run_cfg(name, kwargs):
    r = SEPABacktestRunner(start_date=START, end_date=END, initial_cash=INITIAL_CASH,
                           db_path=str(DB_PATH), model_path=None, model_version_id=None)
    r.setup(scores_df=scores, strategy_kwargs=kwargs)
    return r, r.run()

runs = {}
for name, kw in CONFIGS.items():
    print(f"running {name} ...")
    runs[name] = run_cfg(name, kw)
    print(f"  {runs[name][1].get('total_return'):+.1f}% "
          f"sharpe={runs[name][1].get('sharpe_ratio')}")
```

## Cell 5 — comparison table

```python
rows = []
for name, (r, m) in runs.items():
    tr = r.get_trade_dataframe()
    rows.append({
        "config": name, "trades": m.get("total_trades"),
        "total_ret_%": round(m.get("total_return", 0), 1),
        "sharpe": round(m.get("sharpe_ratio") or 0, 2),
        "maxDD_%": round(m.get("max_drawdown", 0), 1),
        "win_%": round(m.get("win_rate", 0), 1),
        "avg_hold_d": round(tr["holding_days"].mean(), 1) if tr is not None and len(tr) else None,
        "exits": tr["exit_reason"].value_counts().to_dict() if tr is not None and len(tr) else {},
    })
pd.DataFrame(rows).set_index("config")
```

## Cell 6 — equity + exposure, with the 2022 bear visible

```python
fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
for name, (r, m) in runs.items():
    eq = r.get_equity_curve_dataframe()
    axes[0].plot(eq.index, eq["value"], label=name, lw=1.3)
    axes[1].plot(eq.index, eq["position_count"], label=name, lw=1.0)
axes[0].axhline(INITIAL_CASH, color="grey", ls="--", lw=0.8)
# shade 2022 bear
axes[0].axvspan(pd.Timestamp("2022-01-01"), pd.Timestamp("2022-12-31"),
                color="red", alpha=0.08, label="2022 bear")
axes[0].set_ylabel("Equity ($)"); axes[0].set_title("m01_binary 2021–2026 — $25k cap")
axes[0].legend(); axes[0].grid(alpha=0.3)
axes[1].set_ylabel("Open positions"); axes[1].grid(alpha=0.3)
plt.tight_layout(); plt.show()
```

## Cell 7 — the key question: E1 vs E2 *by year*

```python
# Does E2's rotation earn its keep in the bear (2022) even if it loses in bulls?
for name, (r, m) in runs.items():
    eq = r.get_equity_curve_dataframe()["value"]
    yearly = eq.resample("YE").last().pct_change().dropna()
    # first year from start value
    first = eq.resample("YE").last()
    y0 = (first.iloc[0] / INITIAL_CASH - 1)
    print(f"\n{name}:")
    print(f"  {first.index[0].year}: {y0:+.1%}")
    for dt, v in yearly.items():
        print(f"  {dt.year}: {v:+.1%}")
```

## Cell 8 — full diagnostic per config

```python
runs["E1_immediate"][0].plot()
runs["E2_delay3_band"][0].plot()
```

---

## What to read for

1. **E1 across regimes.** If E1 holds up 2021+2023+2025 but craters in 2022, that's the honest
   momentum profile — it's a bull strategy. maxDD over the full window is the number that matters,
   not the flattered prototype 17.9%.
2. **Does E2's rotation redeem itself in 2022?** (Cell 7, by-year.) The prototype run showed E2
   *hurts* in a bull (score-drop cuts mean-reverting winners). The open question: does cutting weak
   names *protect capital* in the bear? If E2's 2022 is markedly better than E1's, rotation is a
   regime-conditional tool, not a dead one. If E2 loses in 2022 too, it's falsified outright.
3. **Turnover vs the compressed score.** Binary's prob_elite barely moves (p99 0.29) — the
   score-drop exit may rarely fire, or fire on noise. Watch the `score_drop` count in Cell 5.
4. **Next:** whichever config wins, WFO-gate it (`run_strategy_wfo.py --model m01_binary`) before
   trusting it. This is still one long split; WFO is the overfit gate.
```
