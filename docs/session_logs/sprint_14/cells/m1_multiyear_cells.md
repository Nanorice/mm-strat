# M1 across 25 regimes (2001–2025) — does the tail-lift hold, or is 6.1× a 2025 artifact?

> **What this answers:** the M1 re-cut was one year (2025). Before moving to M3/M4 we re-scored the
> FULL universe (raw p_pos) for every year t3 covers (2001–2025) and re-ran the tail objective.
>
> **Result (load-bearing):** the score is a **PRO-CYCLICAL** tail-ranker — strong in bulls
> (top-1% lift 7–12×), **at/below no-skill in the two worst tapes (2001 dot-com 0.68×, 2008 GFC
> 0.68×)**. The above-gate SELECTION edge is negative-to-nil in 5/25 years. corr(lift, home-run
> rate) = −0.44: it's WORST exactly when tails are richest. The ONLY regime-robust result is the
> magnitude correction itself (`miss_mag < miss_count` in 25/25 years) — so M1's *metric* is safe to
> adopt, M1's *ranking claim* is regime-conditional.
>
> Cache: `data/model_output_eda/multiyear/raw_full_{YEAR}_fwd.parquet` (built by
> `scripts/score_universe_multiyear.py`, resumable). Analysis: `scripts/m1_multiyear_analysis.py`.
> These cells re-derive the table + chart from the cache — no re-scoring.

Paste each block as one cell (continues the M1 cells; reuses the same `tail_lift` idea).

---

### Cell 1 — load the per-year cache + define the metrics

```python
import numpy as np, pandas as pd
from pathlib import Path

def _root():
    p = Path.cwd().resolve()
    for d in (p, *p.parents):
        if (d/"config.py").exists() and (d/"src").is_dir(): return d
    raise RuntimeError("root not found")
ROOT = _root()
CACHE = ROOT/"data"/"model_output_eda"/"multiyear"
HR, GATE = 0.30, 0.48
BAD = {2001,2002,2007,2008,2009,2011,2022}          # bust/bear/top/crash

def tail_lift(s, tail, fracs=(0.01,0.05,0.10,0.25)):
    N, tot = len(s), tail.sum()
    if tot<=0 or N==0: return {fr: np.nan for fr in fracs}
    order = np.argsort(-s); cum = np.cumsum(tail[order])/tot
    return {fr: cum[int(fr*N)-1]/fr for fr in fracs}

files = sorted(CACHE.glob("raw_full_*_fwd.parquet"))
print(f"{len(files)} years cached: {[int(f.stem.split('_')[2]) for f in files]}")
```

---

### Cell 2 — per-year tail-lift table (full universe + above-gate + magnitude miss)

```python
rows = {}
for fp in files:
    year = int(fp.stem.split("_")[2])
    df = pd.read_parquet(fp).dropna(subset=["fwd20"])
    s, f = df["prob_elite"].values, df["fwd20"].values
    tail = np.maximum(f-HR, 0.0); above = s>=GATE
    full = tail_lift(s, tail); cond = tail_lift(s[above], tail[above]) if above.sum()>100 else {0.01:np.nan,0.10:np.nan}
    rows[year] = dict(n=len(df), hr_rate=(f>HR).mean(),
                      lift1_full=full[0.01], lift10_full=full[0.10],
                      lift1_cond=cond[0.01], lift10_cond=cond[0.10],
                      miss_count=(f[~above]>HR).sum()/(f>HR).sum(),
                      miss_mag=tail[~above].sum()/tail.sum())
t = pd.DataFrame(rows).T.sort_index(); t.index.name="year"
t["bad"] = [y in BAD for y in t.index]
pd.set_option("display.float_format", lambda x: f"{x:.2f}")
print(t[["n","hr_rate","lift1_full","lift1_cond","miss_count","miss_mag","bad"]].to_string())
```

---

### Cell 3 — the good-vs-bad regime split (the headline)

```python
for lbl, mask in [("GOOD (bull/recovery/normal)", ~t.bad), ("BAD (bust/bear/top/crash)", t.bad)]:
    g = t[mask]
    print(f"{lbl}  n={len(g)}")
    print(f"   top-1% lift FULL       median {g.lift1_full.median():.2f}  min {g.lift1_full.min():.2f}")
    print(f"   top-1% lift ABOVE-gate median {g.lift1_cond.median():.2f}  min {g.lift1_cond.min():.2f}  "
          f"yrs<1x {(g.lift1_cond<1).sum()}/{len(g)}")
    print(f"   tail-magnitude miss %  median {g.miss_mag.median():.1%}")
print(f"\ncorr(full lift, home-run rate) = {t.lift1_full.corr(t.hr_rate):+.2f}   "
      f"(<0 => ranker WORSE in tail-rich years = pro-cyclical)")
print(f"miss_mag < miss_count in {(t.miss_mag<t.miss_count).sum()}/{len(t)} years "
      f"(the magnitude correction is regime-robust even where the ranker isn't)")
```

---

### Cell 4 — chart (regime-shaded)

```python
import matplotlib.pyplot as plt
fig, ax = plt.subplots(1, 2, figsize=(16, 6)); yrs = t.index.values
for y in yrs:
    if y in BAD: ax[0].axvspan(y-.5, y+.5, color="#c62828", alpha=.10)
ax[0].plot(yrs, t.lift1_full, "o-", color="#1565c0", label="top-1% lift (full universe)")
ax[0].plot(yrs, t.lift1_cond, "s--", color="#d84315", label="top-1% lift (above the gate)")
ax[0].axhline(1, color="k", lw=.8, ls=":", label="no skill")
ax[0].set_title("Tail-lift across regimes (red = bear/crash) — PRO-CYCLICAL")
ax[0].set_xlabel("year"); ax[0].set_ylabel("tail-lift @ top-1%"); ax[0].legend(fontsize=9); ax[0].grid(alpha=.3)
ax[1].bar(yrs-.2, t.miss_count*100, width=.4, color="#c62828", label="binary count miss %")
ax[1].bar(yrs+.2, t.miss_mag*100, width=.4, color="#2e7d32", label="tail magnitude miss %")
ax[1].set_title("Gate miss: binary vs magnitude, per regime"); ax[1].set_xlabel("year")
ax[1].set_ylabel("% missed by 0.48 gate"); ax[1].legend(fontsize=9); ax[1].grid(alpha=.3)
fig.suptitle("M1 cross-regime (2001-2025, full-universe raw score)", weight="bold")
plt.tight_layout(rect=[0,0,1,0.96]); plt.show()
```

**Saved figure:** `data/model_output_eda/multiyear/m1_multiyear.png`

![M1 cross-regime](../../../../data/model_output_eda/multiyear/m1_multiyear.png)

---

### Cell 5 (markdown) — Read

```markdown
### Read — M1 across 25 regimes
- **The 6.1× top-1% lift is a GOOD-REGIME number.** Median across 25 years is 6.8× but the range is
  0.68×–12.1×. It dives BELOW no-skill in 2001 (dot-com, 0.68×) and 2008 (GFC, 0.68×); weak in
  2007/2009/2011. In bulls it runs 7–12×.
- **The above-gate SELECTION edge is fragile:** median 2.7×, but negative-to-nil in 5/25 years
  (2001, 2002, 2007, 2008, 2011). GOOD regimes 3.3× (0/18 below 1×) vs BAD 0.42× (5/7 below 1×).
  The 3.2× above-gate edge from 2025 does NOT exist in a crash.
- **The model is PRO-CYCLICAL:** corr(lift, home-run rate) = −0.44 — it ranks the tail WORST in the
  tail-rich years. It's a technical/momentum model; crash-moonshots are the returns it can't find.
- **Regime-robust:** `miss_mag < miss_count` in 25/25 years. The magnitude *correction* holds
  universally (leak level swings 9%→66% but is always < the binary count). So adopt the metric;
  treat the ranking claim as a distribution, never one number.
- **For M3/M4:** stability-first selection (M3) must be judged on the bad-regime FLOOR, where the
  edge is ~0, not the bull ceiling. A magnitude regressor (M4) trained pooled will inherit this
  pro-cyclicality unless regime-conditioned or trained tail-weighted on the down years.
- **⚠️ caveat:** early years have a thinner universe (2001 n=163k vs 2025 596k) and older-vintage
  features — the 2001/2008 sub-1× is partly regime, possibly partly coverage. Read the 18-vs-7
  split (robust), not any single year. No exits/sizing — directional.
```
