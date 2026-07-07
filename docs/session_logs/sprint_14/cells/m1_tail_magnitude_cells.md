# M1 — tail-magnitude re-cut cells (replaces Q7's binary >30% miss-rate)

> **What this answers (meta-question M1):** Q7 measured "how many home-runs do we miss?" as a
> binary count of `fwd>30%` — which weights a +35% and a +400% identically. The strategy's alpha
> IS the fat tail, so re-cut by **magnitude** (`Σ max(fwd−30%,0)`) and ask the real question:
> **does the raw score RANK the tail?** (tail-lift@top-k / rank-of-top-1%).
>
> **Load-bearing findings:**
> 1. The 0.48 gate misses **14.2% of tail MAGNITUDE, not 23.4% of home-run EVENTS** — it keeps big
>    winners, drops small ones. Q7 overstated the leak ~40%.
> 2. The raw score **does** rank the tail on the full universe (top-1% fwd at score-pctile 0.89;
>    top-1% scores hold 6.1× their share of tail). "Weak ranker (4× confirmed)" was only true
>    *within the gated pool* / on the *flattened calibrated* score — NOT on the full raw universe.
>
> No scoring, no DB — pure re-analysis of `data/model_output_eda/raw_full_2025_fwd.parquet`
> (596k rows, 250 days 2025, raw p_pos in col `prob_elite` + per-row fwd20). Runnable script:
> `docs/session_logs/sprint_14/scripts/m1_tail_magnitude_recut.py` (+ `_chart.py` for the figure).

Paste each block as one cell.

---

### Cell 1 — load + define the tail objective

```python
import numpy as np, pandas as pd
from pathlib import Path
from scipy.stats import spearmanr

def _root():
    p = Path.cwd().resolve()
    for d in (p, *p.parents):
        if (d/"config.py").exists() and (d/"src").is_dir(): return d
    raise RuntimeError("root not found")
ROOT = _root()

df = pd.read_parquet(ROOT/"data"/"model_output_eda"/"raw_full_2025_fwd.parquet").dropna(subset=["fwd20"])
s, f, N = df["prob_elite"].values, df["fwd20"].values, len(df)   # prob_elite col == RAW p_pos here (naming trap)
GATE, HR = 0.48, 0.30                                            # 0.48 = calibrated 0.15

def excess(x): return np.maximum(x - HR, 0.0)                    # tail magnitude above the 30% line
assert abs(excess(np.array([0.35]))[0] - 0.05) < 1e-9 and (excess(f) >= 0).all()

tail = excess(f); tot_tail = tail.sum(); above = s >= GATE
print(f"{N} rows | home-run events (>30%) = {(f>HR).sum()} ({(f>HR).mean():.2%}) | total tail = {tot_tail:.1f}")
print(f"max fwd20 = {f.max():+.1%}  (this is what the binary count erases)")
```

---

### Cell 2 — Finding 1: what the gate MISSES (binary count vs magnitude)

```python
miss_c = (f[~above] > HR).sum() / (f > HR).sum()
miss_t = tail[~above].sum() / tot_tail
print(f"{'metric':<30}{'miss %':>9}")
print(f"{'home-run COUNT (old binary)':<30}{miss_c:>8.1%}")
print(f"{'tail MAGNITUDE Σmax(fwd-30%,0)':<30}{miss_t:>8.1%}")
print(f"\nmedian magnitude — captured HR {np.median(f[above&(f>HR)]):+.1%}  vs  missed HR {np.median(f[~above&(f>HR)]):+.1%}")
print(f"mean excess     — captured HR {excess(f[above&(f>HR)]).mean():.3f}   vs  missed HR {excess(f[~above&(f>HR)]).mean():.3f}")
# READ: 14.2% of tail missed, not 23.4% of events. Missed home-runs are the SMALL ones -> gate keeps the big tail.
```

---

### Cell 3 — Finding 2: does the score RANK the tail? (rank-of-top-1% + tail-lift@k)

```python
top1 = f >= np.quantile(f, 0.99)
pctile = pd.Series(s).rank(pct=True).values
print(f"top-1% fwd ({top1.sum()} events, cutoff {np.quantile(f,0.99):+.1%}):")
print(f"  median score-percentile {np.median(pctile[top1]):.3f}   mean {np.mean(pctile[top1]):.3f}   (0.5 = no signal)")
print(f"  frac clearing the {GATE} gate: {above[top1].mean():.1%}  (vs base {above.mean():.1%})\n")

order = np.argsort(-s); cum = np.cumsum(tail[order]) / tot_tail   # walk score top-down
print("tail-lift@k (share of total tail in top-k scores / k):")
for frac in (0.01, 0.05, 0.10, 0.25, 0.50):
    i = int(frac*N)-1
    print(f"  top {frac:>4.0%}  ->  {cum[i]:>5.1%} of tail   lift {cum[i]/frac:.2f}x")
# READ: top-1% of scores hold 6.1x their share of the tail. The score ranks the tail on the FULL universe.
```

---

### Cell 4 — magnitude vs binary rate by ventile (does magnitude grade too?)

```python
df2 = df.assign(tail=tail, ventile=pd.qcut(df["prob_elite"], 20, labels=False, duplicates="drop"))
g = df2.groupby("ventile").agg(hr_rate=("fwd20", lambda x:(x>HR).mean()), mean_tail=("tail","mean"),
                               sum_tail=("tail","sum"))
g["tail_share"] = g["sum_tail"]/tot_tail
print(g.loc[[0,9,14,17,18,19], ["hr_rate","mean_tail","tail_share"]].to_string())
print(f"\nmonotonic rho — HR-rate {spearmanr(g.index,g.hr_rate).correlation:+.2f}   "
      f"mean-tail {spearmanr(g.index,g.mean_tail).correlation:+.2f}")
# READ: both grade monotonically (rho +1.00); top ventile alone holds ~25% of ALL tail magnitude.
```

---

### Cell 5 — the 4-panel figure

```python
import matplotlib.pyplot as plt
fig, ax = plt.subplots(2, 2, figsize=(15, 10))

# 1 binary-miss vs magnitude-miss
b = ax[0,0].bar(["count (binary)","magnitude"], [miss_c*100, miss_t*100], color=["#c62828","#2e7d32"], width=.55)
for r,v in zip(b,[miss_c,miss_t]): ax[0,0].text(r.get_x()+.27, v*100+.5, f"{v:.1%}", ha="center", weight="bold")
ax[0,0].set_title(f"what the {GATE} gate MISSES"); ax[0,0].set_ylabel("% missed"); ax[0,0].set_ylim(0,30)

# 2 tail-capture concentration
ax[0,1].plot(np.arange(1,N+1)/N*100, cum*100, lw=2, color="#1565c0", label="tail captured")
ax[0,1].plot([0,100],[0,100],"k--",alpha=.4,label="no skill")
for fr in (0.01,0.10,0.25):
    i=int(fr*N)-1; ax[0,1].plot(fr*100,cum[i]*100,"o",color="#c62828")
    ax[0,1].annotate(f"top {fr:.0%}->{cum[i]:.0%} ({cum[i]/fr:.1f}x)",(fr*100,cum[i]*100),
                     textcoords="offset points",xytext=(8,-4),fontsize=9)
ax[0,1].set_title("tail concentration — score RANKS the tail"); ax[0,1].set_xlabel("top X% of scores")
ax[0,1].set_ylabel("% of tail captured"); ax[0,1].legend(fontsize=9)

# 3 ventile magnitude (bars) vs binary rate (line)
axb=ax[1,0]; axb.bar(g.index,g.mean_tail,color="#2e7d32",alpha=.85); axb.set_ylabel("mean tail",color="#2e7d32")
axt=axb.twinx(); axt.plot(g.index,g.hr_rate*100,"o-",color="#c62828"); axt.set_ylabel("home-run rate %",color="#c62828")
axb.set_title("ventile: magnitude (bars) vs binary rate (line)"); axb.set_xlabel("raw-score ventile (19=top)")

# 4 where the top-1% fwd sit in the score dist
ax[1,1].hist(pctile[~top1],bins=40,alpha=.5,density=True,color="#90a4ae",label="all")
ax[1,1].hist(pctile[top1],bins=40,alpha=.7,density=True,color="#d84315",label="top-1% fwd")
ax[1,1].axvline(np.median(pctile[top1]),color="#d84315",ls="--",lw=2,label=f"median {np.median(pctile[top1]):.2f}")
ax[1,1].set_title("biggest 1% cluster at the TOP of the score"); ax[1,1].set_xlabel("raw-score percentile")
ax[1,1].legend(fontsize=9)

fig.suptitle("M1 — tail-magnitude re-cut (full universe, 2025)", weight="bold")
plt.tight_layout(); plt.show()
```

**Saved figure:** `data/model_output_eda/m1_tail_magnitude.png`

![M1 tail-magnitude](../../../../data/model_output_eda/m1_tail_magnitude.png)

---

### Cell 6 (markdown) — Read

```markdown
### Read
- **The gate misses 14% of the tail, not 23% of the events.** The old binary "23.4% missed"
  weighted a +30.01% the same as a +400%. By magnitude the leak is 14.2%, and the missed
  home-runs are the SMALL ones (mean excess +12% vs +23% for captured). The gate keeps the big tail.
- **The raw score DOES rank the fat tail on the full universe.** Top-1% forward returns sit at
  score-percentile 0.89 (median); 86% of them clear the gate vs 34% base; top-1% of scores hold
  6.1× their share of total tail (top-10% 4.7×); magnitude grades monotonically (rho +1.00).
- **This does NOT contradict "weak ranker."** Both are true and non-overlapping: weak WITHIN the
  homogeneous ~6-name gated pool (IC≈0) and on the flattened CALIBRATED score; strong on the
  continuous RAW full-universe score, where the tail concentrates at the extreme top — the same
  place M5's persistent continuous top-N lives. The findings stitch.
- **Reusable objective for M3/M4:** `tail-lift@top-k` (top-1% 6.1×, top-10% 4.7×) is the
  rank-of-tail eval M4's magnitude regressor must beat, and the stability target M3 sweeps. It
  drops into the WFO/start-cone harness — swap `home_run_rate` → `tail_lift@k`.
- **⚠️ One year (2025), no exits/sizing** — directional. Bootstrap-CI the 6.1× lift and repeat
  across years through the start-date cone (M2) before hard-wiring.
```
