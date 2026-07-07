# Model-output EDA — binary champion score distribution, the 0.15 gate, and the calibrator

> **What this answers (sprint 14 Q1 + the "is 0.15 the right threshold" question):**
> 1. How does the champion's output distribute? → it's the **binary** model (`m01_binary/v1`),
>    scored as `prob_class_1` = P(positive), NOT the 4-class P(>30%).
> 2. Is 0.15 the right threshold? → **0.15 is calibrated; it equals raw `p_pos ≥ 0.48`** (≈50/50
>    on the raw model). Not low at all — the model is overconfident and the isotonic calibrator
>    corrects raw 0.50 down to 0.15.
> 3. What population does a human review? → breakout cohort is **~10 names/day pre-gate, ~6 after
>    the 0.15 gate**. Small. (The 338/day pre-breakout funnel is the *4-class* model, separate.)
> 4. **Load-bearing finding:** the champion RANKS top-5 on the *calibrated* score, but the
>    isotonic calibrator is a step function — it collapses 2038 distinct raw scores → 23, and its
>    **top decile has the WORST forward return**. Calibrated ranking is worse than useless at the
>    sharp end. Raw `p_pos` ranks weakly-positively (rho 0.60). See [[project_isotonic_flattens_ranking]].
>
> No backtest re-run — reads live `daily_predictions` + `price_data.close`. Outputs to
> `data/model_output_eda/`.

Paste each block as one cell.

---

### Cell 1 — setup + load live binary scores

```python
import sys
from pathlib import Path
import numpy as np, pandas as pd, duckdb

def _root():
    p = Path.cwd().resolve()
    for d in (p, *p.parents):
        if (d/"config.py").exists() and (d/"src").is_dir(): return d
    raise RuntimeError("root not found")
ROOT=_root(); sys.path.insert(0,str(ROOT))
from src.evaluation.calibrator import IsotonicCalibrator

DB = ROOT/"data"/"market_data.duckdb"
MV = "m01_binary_20260524_222020"        # the deployed binary champion version
cal = IsotonicCalibrator.load(ROOT/"models"/"m01_binary"/"v1"/"calibrator.joblib")

con = duckdb.connect(str(DB), read_only=True)   # read_only — never lock the DB
b = con.execute(f"""
  SELECT prediction_date, ticker, cohort, prob_class_1 AS p_pos, rank_within_day
  FROM daily_predictions WHERE model_version_id='{MV}'
""").df()
con.close()
b["prediction_date"] = pd.to_datetime(b["prediction_date"])
b["p_cal"] = cal.transform(b["p_pos"].values)   # what the BACKTEST ranks on
print(f"{len(b)} rows, {b.prediction_date.nunique()} days, cohorts={b.cohort.unique().tolist()}")
print(f"raw p_pos distinct={b.p_pos.nunique()}  ->  calibrated distinct={b.p_cal.nunique()}   (flattening)")
```

---

### Cell 2 — the calibration map: where does the 0.15 gate really sit?

```python
grid = np.linspace(0.001, 0.999, 1000)
cg = cal.transform(grid)
gate_raw = grid[np.searchsorted(cg, 0.15)]
print(f"gate cal=0.15  ==  raw p_pos >= {gate_raw:.3f}   (i.e. the model's ~50/50 line)")
print(f"calibrator maps 1000 raw values -> {len(np.unique(np.round(cg,6)))} distinct plateaus")
# spread erased around the gate: two very different raw probs -> same calibrated value
for r in (0.20, 0.30, 0.40, 0.50, 0.60):
    print(f"  raw {r:.2f} -> cal {cal.transform(np.array([r]))[0]:.4f}")
```

---

### Cell 3 — daily pool size (the human-review population)

```python
per_pre  = b.groupby("prediction_date").size()
adm = b[b.p_cal >= 0.15]
per_gate = adm.groupby("prediction_date").size()
print(f"breakout cohort / day  : med {per_pre.median():.0f}  p10 {per_pre.quantile(.1):.0f}  p90 {per_pre.quantile(.9):.0f}")
print(f"after 0.15 gate  / day : med {per_gate.median():.0f}  p10 {per_gate.quantile(.1):.0f}  p90 {per_gate.quantile(.9):.0f}  max {per_gate.max()}")
print(f"gate admits {(b.p_cal>=0.15).mean():.1%} of the breakout cohort")
```

---

### Cell 4 — forward-return scorer (20d, from close — adj_close is 100% NULL)

```python
H = 20
con = duckdb.connect(str(DB), read_only=True)
tk = tuple(sorted(b.ticker.unique()))
lo = (b.prediction_date.min()-pd.Timedelta(days=5)).strftime("%Y-%m-%d")
hi = (b.prediction_date.max()+pd.Timedelta(days=H*3+10)).strftime("%Y-%m-%d")
px = con.execute(f"SELECT ticker,date,close FROM price_data WHERE ticker IN {tk} AND date BETWEEN ? AND ? ORDER BY ticker,date",[lo,hi]).df()
con.close()
px["date"]=pd.to_datetime(px["date"])
pxg = {t:g.set_index("date")["close"] for t,g in px.groupby("ticker")}
def fwd(r):
    s = pxg.get(r["ticker"])
    if s is None: return np.nan
    s = s[s.index>=r["prediction_date"]]
    if len(s)<=H or s.iloc[0]==0: return np.nan
    return s.iloc[H]/s.iloc[0]-1
b["fwd20"] = b.apply(fwd, axis=1)
sc = b.dropna(subset=["fwd20"]).copy()
print(f"scored {len(sc)} rows for 20d fwd return")
```

---

### Cell 5 — the decile test: does the score RANK forward returns? (raw vs calibrated)

```python
from scipy.stats import spearmanr
for col in ("p_pos", "p_cal"):
    sc["dec"] = pd.qcut(sc[col], 10, labels=False, duplicates="drop")
    g = sc.groupby("dec")["fwd20"].mean()
    rho = spearmanr(g.index, g.values).correlation
    print(f"[{col}] top-dec {g.iloc[-1]*100:+.1f}%  bot-dec {g.iloc[0]*100:+.1f}%  "
          f"spread {(g.iloc[-1]-g.iloc[0])*100:+.1f}%  monotonic rho {rho:+.2f}")
# EXPECT: p_pos weakly positive+monotonic (rho~0.6); p_cal top decile NEGATIVE (calibration
# inverts the sharp end) -> ranking on calibrated prob_elite is actively harmful for top-5.
```

---

### Cell 6 — charts (6-panel)

```python
import matplotlib.pyplot as plt
fig, ax = plt.subplots(2, 3, figsize=(18, 10))
# 1 calibration map
ax[0,0].plot(grid, cg, lw=2); ax[0,0].plot([0,1],[0,1],"k--",alpha=.4,label="identity")
ax[0,0].axhline(0.15,color="r",ls=":",label="gate cal=0.15"); ax[0,0].axvline(gate_raw,color="r",ls=":")
ax[0,0].set_title("isotonic map raw->cal (0.15 == raw %.2f)"%gate_raw); ax[0,0].set_xlabel("raw p_pos"); ax[0,0].legend(fontsize=8)
# 2 dist raw vs cal
ax[0,1].hist(b.p_pos,bins=50,alpha=.6,label=f"raw ({b.p_pos.nunique()})")
ax[0,1].hist(b.p_cal,bins=50,alpha=.6,label=f"cal ({b.p_cal.nunique()})")
ax[0,1].axvline(0.15,color="r",ls=":"); ax[0,1].set_title("live score dist — cal collapses to spikes"); ax[0,1].legend(fontsize=8)
# 3 pool size
ax[0,2].hist(per_gate,bins=range(0,35,2),color="#2e7d32",alpha=.7,edgecolor="w")
ax[0,2].axvline(per_gate.median(),color="k",lw=2,label=f"med {per_gate.median():.0f}")
ax[0,2].set_title("daily gated pool (human-review N)"); ax[0,2].set_xlabel("names/day"); ax[0,2].legend(fontsize=8)
# 4,5 decile fwd
for j,col in enumerate(("p_pos","p_cal")):
    sc["dec"]=pd.qcut(sc[col],10,labels=False,duplicates="drop"); g=sc.groupby("dec")["fwd20"].mean()
    ax[1,j].bar(g.index,g.values*100,color=np.where(g>0,"#2e7d32","#c62828")); ax[1,j].axhline(0,color="k",lw=.6)
    ax[1,j].set_title(f"20d fwd by {col} decile (top {g.iloc[-1]*100:+.1f}%)"); ax[1,j].set_xlabel("decile (9=top)")
# 6 gate admission over time
af=b.assign(g=b.p_cal>=0.15).groupby("prediction_date")["g"].mean()
ax[1,2].plot(af.index,af.values,lw=1); ax[1,2].axhline(af.mean(),color="r",ls="--",label=f"mean {af.mean():.2f}")
ax[1,2].set_title("frac admitted by 0.15 gate"); ax[1,2].legend(fontsize=8)
plt.tight_layout(); plt.show()
```

---

### Cell 7 (markdown) — Read

```markdown
### Read

- **The champion is the BINARY model** (`m01_binary/v1`), scored `prob_class_1` = P(positive) —
  NOT the 4-class P(>30%). The two scores are on different, non-comparable scales.
- **0.15 is not a low gate — it's raw `p_pos ≥ 0.48`** (the model's ~50/50 line). It looked low
  only because we were comparing it to the *4-class* P(HomeRun) (median ~0.31). The isotonic
  calibrator maps raw 0.50 → 0.15 because the model is overconfident (raw 50% ≈ 15% realized).
- **Human-review population is small: ~6 names/day after the gate** (~10 pre-gate). This is the
  Minervini-style shortlist size for the breakout cohort. (Pre-breakout's 338/day is the 4-class
  funnel — a different, wider list.)
- **CALIBRATED RANKING IS HARMFUL AT THE TOP.** The calibrated top decile has the *worst* 20d fwd
  return (negative); raw `p_pos` is weakly positive + monotonic (rho ~0.6). The champion ranks
  top-5 on the calibrated score → it's picking from a mis-ordered top. This corroborates the
  existing `models/m01_binary/v1/backtests/` evidence (raw Sharpe 1.44 vs calibrated 0.78).
- **Implication:** the sprint-13 "gate-not-ranker → widen the basket" plan is premature. The
  lazy fix is **rank on raw `p_pos`, not calibrated `prob_elite`** — the calibrator should be
  used for *display probabilities*, never as the *ranking key*. Confirm via the corrected
  cohort-bootstrap (Phase 0) then a WFO re-run with `rank_by` on raw prob.
- **Caveat:** raw `p_pos`'s edge is weak (top-vs-bottom decile spread only ~+0.2%/20d). It's a
  better ranker than calibrated, but not a strong one. Widening the basket stays a live option B.
```
