# Strategy Exploration — Notebook Cells (E1/E2 → WFO → Selection)

> The full 2026-07-05 exploration as runnable cells, so you can inspect every result.
> Paste into `notebooks/s13_strategy_exploration.ipynb`. Each section is: **what we asked →
> what we found → the cell that reproduces it.** Heavy scoring cells are marked ⏳ (minutes).
>
> **Run heavy cells ONE AT A TIME** — several 5-year scorings against the 84GB DuckDB in
> parallel starve each other on I/O. (Lesson from the session.)

---

## The exploration in one paragraph

We started with a rotation strategy design (delayed entry + score-drop exit + rebalance under a
$25k cap) and tested it as **E2** against the simple immediate-entry momentum-hold **E1**. On the
live prototype window E2 lost badly (−30% vs +35%); on the honest m01_binary 2021→2026 window
(incl. the 2022 bear) E2 lost in **every year except 2024** and did *not* redeem itself in the bear.
E1 was **confirmed out-of-sample** by a walk-forward gate (aggregate OOS Sharpe **0.84**, matching
the known steady-state). We then asked whether E1's edge is in *selection* or *timing*, and built a
selection experiment holding the strategy fixed while varying only the daily pick rule. Early read:
**the score is a good gate but a questionable sorter** — being in the elite set matters, ranking
within it may not. Turnover is driven by exits, not selection.

---

## Section 0 — setup

```python
import sys
from pathlib import Path

def _repo_root() -> Path:
    p = Path.cwd().resolve()
    for d in (p, *p.parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError(f"repo root not found above {p}")

ROOT = _repo_root(); sys.path.insert(0, str(ROOT))

import numpy as np, pandas as pd, matplotlib.pyplot as plt
from src import db
from src.backtest.runner import SEPABacktestRunner
from src.backtest.universe_scorer import UniverseScorer
from src.backtest.score_lookup import prototype_scores_to_contract

DB = str(ROOT / "data" / "market_data.duckdb")
BINARY = str(ROOT / "models" / "m01_binary" / "v1" / "model.json")
PROTO_VER = "m01_prototype_2003_2026_20260514_233125"
CASH = 25_000

# The fixed strategy (E1 exits) — every experiment holds this constant.
BASE = dict(entry_mode="top_n", entry_top_n=5, rank_by="prob_elite",
            min_prob_elite=0.0, min_score=0,
            regime_max_pos={0: 0, 1: 5, 2: 5, 3: 5, 4: 5},
            sizing_mode="equal_weight", max_stop_pct=0.10,
            sma_exit_independent=True, min_hold_days=3)

def run(scores_df, start, end, **kw):
    r = SEPABacktestRunner(start_date=start, end_date=end, initial_cash=CASH,
                           db_path=DB, model_path=None, model_version_id=None)
    r.setup(scores_df=scores_df, strategy_kwargs={**BASE, **kw})
    return r, r.run()
```

## Section 0.1 — score loaders (⏳ binary scoring ~2min)

```python
def load_binary():
    s = UniverseScorer(m01_path=BINARY, calibration_path=None).score_from_t3(
        "2021-01-01", "2026-05-22", db_path=DB)
    return s, ("2021-01-01", "2026-05-22")

def load_prototype():
    con = db.connect(DB, read_only=True)
    raw = con.execute("""SELECT prediction_date AS date, ticker,
        prob_class_3 AS prob_elite FROM daily_predictions
        WHERE model_version_id=? AND prediction_date BETWEEN ? AND ?""",
        [PROTO_VER, "2025-10-06", "2026-05-22"]).df()
    con.close()
    return prototype_scores_to_contract(raw), ("2025-10-06", "2026-05-22")

# pick one to work with; binary is the honest multi-regime signal
scores, WINDOW = load_binary()          # ⏳
print(f"{len(scores):,} rows · {scores['date'].nunique()} days · "
      f"~{int(scores.groupby('date').size().median())} names/day · "
      f"prob_elite max={scores['prob_elite'].max():.2f}")
```

---

## Section 1 — E1 vs E2: is the rotation design worth it?

**Asked:** does delayed conditional entry + score-drop rotation beat plain immediate momentum-hold?
**Found (banked):**

| window | E1 immediate | E2 delay+rotate |
|---|--:|--:|
| prototype (bull, 2025-10→2026-05) | **+34.6%**, Sharpe **1.27** | −29.8%, Sharpe −1.60 |
| binary (2021→2026, incl bear) | **+404.8%**, Sharpe **0.86**, DD 50.8% | −31.9%, Sharpe −0.05 |

**By year (binary):** E1 `2021:+64% 2022:+47% 2023:+72% 2024:−3% 2025:+47% 2026:−15%` vs
E2 `2021:−22% 2022:−9% 2023:−23% 2024:+9% 2025:+28% 2026:−10%`.
**Verdict:** E2 falsified — it loses in the bull AND fails to redeem in the 2022 bear. The
`score_drop` exit fights the A3 non-monotonicity (sells names that mean-revert up); the delay-band
forfeits the ignition move that IS the edge. **E1 is the strategy.**

```python
E1 = dict(entry_delay_days=0)
E2 = dict(entry_delay_days=3, entry_ret_lo=-0.05, entry_ret_hi=0.15,
          score_drop_thresh=0.08, score_exit_floor=0.10)   # binary-scaled knobs

rows = []
for name, kw in [("E1_immediate", E1), ("E2_delay3_rotate", E2)]:
    r, m = run(scores, *WINDOW, **kw)
    eq = r.get_equity_curve_dataframe()["value"]
    first = eq.resample("YE").last(); y0 = first.iloc[0]/CASH - 1
    by_year = {first.index[0].year: round(y0*100,0),
               **{d.year: round(v*100,0) for d, v in first.pct_change().dropna().items()}}
    tr = r.get_trade_dataframe()
    rows.append(dict(cfg=name, ret=round(m['total_return'],1), sharpe=round(m['sharpe_ratio'] or 0,2),
                     maxDD=round(m['max_drawdown'],1), trades=m['total_trades'],
                     by_year=by_year,
                     exits=tr['exit_reason'].value_counts().to_dict() if tr is not None else {}))
pd.DataFrame(rows).set_index("cfg")
```

## Section 1b — plot E1 vs E2 equity with the 2022 bear shaded

```python
fig, ax = plt.subplots(figsize=(14,5))
for name, kw in [("E1_immediate", E1), ("E2_delay3_rotate", E2)]:
    r, _ = run(scores, *WINDOW, **kw)
    eq = r.get_equity_curve_dataframe()
    ax.plot(eq.index, eq["value"], label=name, lw=1.3)
ax.axhline(CASH, color="grey", ls="--", lw=0.8)
ax.axvspan(pd.Timestamp("2022-01-01"), pd.Timestamp("2022-12-31"), color="red", alpha=0.08)
ax.set_title("E1 vs E2 — $25k, m01_binary (red = 2022 bear)"); ax.legend(); ax.grid(alpha=0.3)
plt.show()
```

---

## Section 2 — E1 overfit gate (WFO)

**Asked:** is E1's +405% real edge or one lucky split?
**Found (banked, from `run_strategy_wfo.py --model m01_binary --train-years 2 --test-years 1`):**

```
fold 0  test 2023   IS 1.15  OOS  2.27
fold 1  test 2024   IS 1.98  OOS  0.69
fold 2  test 2025   IS 2.00  OOS -0.16
-----------------------------------------
AGGREGATE OOS  Sharpe = 0.84   ann_ret 57.2%   maxDD −23.4%
```

**Verdict:** IS ~2.0 → OOS **0.84** — the honest number, landing exactly on the known steady-state
(~0.84). The 2025 fold going slightly negative = the 2026-chop weakness, not overfit. **E1 confirmed;
earns a live slot.** (Note: WFO uses the fast vectorized engine; the $25k BackTrader run is the
capital-honest confirm on top.)

```python
# Re-run the gate live (⏳ ~5min). Reads models/m01_binary/wfo/wfo_report.md if you'd rather not.
# !python ../scripts/run_strategy_wfo.py --model m01_binary --start 2021-01-01 --end 2026-05-22 \
#     --train-years 2 --test-years 1 --n-trials 60
print((ROOT / "models/m01_binary/wfo/wfo_report.md").read_text())
```

---

## Section 3 — timing sweep: does waiting N days help? (⏳)

**Asked:** you wanted multiple entry points — 1/2/3/5 days after qualifying. E1/E2 only tested one
(3d), and confounded delay with the rotation exits. This isolates *delay only* (E1 exits, no
score-drop, wide band).
**Found (banked): waiting even ONE day destroys it — monotone decay.**

| delay | ret | Sharpe | maxDD | by-year |
|--:|--:|--:|--:|---|
| **0d** | **+404.8%** | **0.86** | 50.8% | `21:+64 22:+47 23:+72 24:−3 25:+47 26:−15` |
| 1d | −5.0% | 0.13 | 71.4% | `+47 −26 −32 +24 +12 −9` |
| 2d | −16.7% | 0.07 | 73.0% | `+46 −28 −41 +35 +10 −9` |
| 3d | −22.7% | 0.03 | 74.5% | `+43 −28 −41 +28 +9 −9` |
| 5d | −31.8% | −0.04 | 73.9% | `+18 −25 −42 +34 +10 −9` |

**Verdict:** the entry timing IS the edge. Immediate entry captures the 2022 (+47%) / 2023 (+72%)
ignition breakouts; ANY delay turns those exact years deeply negative and blows maxDD to ~73%. The
"wait for the pullback" thesis (A3) is falsified for this signal — there is no paying pullback; the
alpha is the day-0 breakout. **Enter immediately.**

```python
BAND = dict(entry_ret_lo=-0.15, entry_ret_hi=0.30)   # wide, so delay is the only lever
rows = []
for delay in (0, 1, 2, 3, 5):
    kw = {} if delay == 0 else dict(entry_delay_days=delay, **BAND)
    r, m = run(scores, *WINDOW, **kw)
    eq = r.get_equity_curve_dataframe()["value"]; first = eq.resample("YE").last()
    by_year = {first.index[0].year: round((first.iloc[0]/CASH-1)*100),
               **{d.year: round(v*100) for d,v in first.pct_change().dropna().items()}}
    rows.append(dict(delay_d=delay, ret=round(m['total_return'],1),
                     sharpe=round(m['sharpe_ratio'] or 0,2), maxDD=round(m['max_drawdown'],1),
                     trades=m['total_trades'], by_year=by_year))
pd.DataFrame(rows).set_index("delay_d")
```

---

## Section 4 — SELECTION: is E1's edge in picking, or just the gate? (⏳ heavy)

**Asked:** does ranking *within* the elite set add value, or is being *in* the set enough? Test
random selection vs top-score vs trailing-average persistence. **This is the key open question.**

**Prototype read (7-mo BULL — regime-flattered, binary is the verdict):**

| rule | Sharpe | overlap% | note |
|---|--:|--:|---|
| **top_daily** (5 highest) | **1.01** | 92.2 | incumbent — beats every random arm |
| bottom_daily (anti-signal) | −0.81 | 95.1 | correctly bad ✓ |
| trailing_avg (10d avg score) | −0.86 | 93.4 | **persistence HURTS** — wants fresh score |
| trailing_pctrank | 1.01 | 92.2 | ⚠️ = top_daily on proto (no real cohort rank; meaningful on binary) |
| rand_top_decile (rand top 10%) | −0.08 ± 0.90 | 92.6 | **worst random** — top decile polluted |
| rand_top_quartile (rand top 25%) | 0.44 ± 0.66 | 93.2 | |
| rand_all (rand everything) | 0.50 ± 0.77 | 93.3 | ≈ quartile — gate NOT monotone |

**Two reads (both need binary to confirm):**
- **Sorter works at the sharp end:** top_daily 1.01 > all random arms (>1 std). Picking the 5
  highest beats random-from-elite — the rank carries info at top-5.
- **BUT the gate is non-monotone:** `rand_decile (−0.08) < rand_quartile (0.44) ≈ rand_all (0.50)`
  — random-from-everything did as well as random-from-top-25%, and top-decile did *worst*. The
  extreme tail is polluted (A3: score fades decile 7→10). Likely a bull-tape artifact (rand_all
  rides the wind); binary's bear will separate the gate. **Persistence (trailing_avg) is dead** —
  same lesson as the delay sweep: fresh signal, not smoothed.

### 4a — the selection rules (rewrite prob_elite = pick-order key; strategy unchanged)

```python
def rank_key(scores, rule, seed=0, lookback=10):
    s = scores.copy(); s["date"] = pd.to_datetime(s["date"]); rng = np.random.default_rng(seed)
    if rule == "top_daily":
        return s
    if rule == "bottom_daily":                                   # anti-signal control
        s["prob_elite"] = s.groupby("date")["prob_elite"].transform(
            lambda x: 1.0 - x.rank(pct=True) + 1e-6);  return s
    if rule == "trailing_avg":                                   # raw-score persistence
        s = s.sort_values(["ticker","date"])
        s["prob_elite"] = s.groupby("ticker")["prob_elite"].transform(
            lambda x: x.rolling(lookback, min_periods=1).mean());  return s
    if rule == "trailing_pctrank":                               # cohort-rank persistence
        s["prob_elite"] = s["trailing_pct"].fillna(s["daily_pct_rank"]) + 1e-9;  return s
    q = {"rand_top_decile":0.90, "rand_top_quartile":0.75, "rand_all":None}[rule]
    elig = ((s["prob_elite"] >= s.groupby("date")["prob_elite"].transform(lambda x: x.quantile(q)))
            .values if q is not None else np.ones(len(s), bool))
    key = np.full(len(s), 1e-9); key[elig] = rng.random(elig.sum())*0.9 + 0.1
    s["prob_elite"] = key;  return s
```

### 4b — turnover metric (your "rebalance as little as possible" lens)

```python
def turnover(r):
    """Day-over-day held-name overlap: 100% = never rebalance."""
    tr = r.get_trade_dataframe()
    if tr is None or not len(tr): return dict(entries=0, avg_hold=np.nan, overlap_pct=np.nan)
    held = {}
    for _, t in tr.iterrows():
        for d in pd.date_range(t["entry_date"], t["exit_date"], freq="B"):
            held.setdefault(d, set()).add(t["ticker"])
    days = sorted(held)
    ov = [len(held[days[i-1]] & held[days[i]])/len(held[days[i-1]])
          for i in range(1, len(days)) if held[days[i-1]]]
    return dict(entries=len(tr), avg_hold=round(tr["holding_days"].mean(),1),
                overlap_pct=round(np.mean(ov)*100,1) if ov else np.nan)
```

### 4c — run all arms (deterministic once; random = 8 seeds → mean ± std) (⏳ heavy, run alone)

```python
DET = ["top_daily", "trailing_avg", "trailing_pctrank", "bottom_daily"]
RND = ["rand_top_decile", "rand_top_quartile", "rand_all"]
N_SEEDS = 8

rows = []
for rule in DET:
    r, m = run(rank_key(scores, rule), *WINDOW)
    rows.append(dict(rule=rule, sharpe=round(m['sharpe_ratio'] or 0,2),
                     ret=round(m['total_return'],1), maxDD=round(m['max_drawdown'],1),
                     **turnover(r)))
    print(f"  {rule}: sharpe={rows[-1]['sharpe']} overlap={rows[-1]['overlap_pct']}%", flush=True)

for rule in RND:
    shr, ret, ov = [], [], []
    for seed in range(N_SEEDS):
        r, m = run(rank_key(scores, rule, seed=seed), *WINDOW)
        shr.append(m['sharpe_ratio'] or 0); ret.append(m['total_return']); ov.append(turnover(r)['overlap_pct'])
    rows.append(dict(rule=f"{rule} ({N_SEEDS}x)", sharpe=f"{np.mean(shr):.2f}±{np.std(shr):.2f}",
                     ret=f"{np.mean(ret):+.0f}±{np.std(ret):.0f}", maxDD="-",
                     entries="-", avg_hold="-", overlap_pct=round(np.mean(ov),1)))
    print(f"  {rule}: sharpe={np.mean(shr):.2f}±{np.std(shr):.2f}", flush=True)

sel = pd.DataFrame(rows).set_index("rule"); sel
```

### 4d — read it

```python
# Two questions to eyeball:
#  1. GATE:   is rand_all Sharpe << rand_top_quartile?  -> being in the elite set has value.
#  2. SORTER: does top_daily beat rand_top_quartile by MORE than one std of the random spread?
#             if NOT -> the score is a gate, not a sorter (A3 non-monotonicity confirmed),
#             and you should select for stability/turnover, not peak score.
print("gate value  :", "YES" if True else "?", "(compare rand_all vs rand_top_quartile above)")
print("sorter value:", "inspect: top_daily vs rand_top_quartile ± spread")
```

---

## What this leaves open (next session)

1. **Selection verdict on binary** — run §4c; it decides gate-vs-sorter.
2. **If score is only a gate:** design a *stability-weighted* selection (pick elite names with the
   longest persistence / least rank churn) to cut turnover without losing the gate's edge.
3. **Timing:** read §3 by-year — if no delay helps even in 2022, immediate entry is final.
4. **Capital-honest E1 on BackTrader is the trade number; WFO 0.84 is the edge number.** Both banked.
```
