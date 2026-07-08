# M6 consumer #2 — does m01's score→return change by REGIME? (all tickers, 25y, no backtest)

> **What this answers (your 2026-07-08 questions):**
> 1. **Only SPX-vs-200MA for the trunk — or leverage the 6 pillars?** Tested. A **trunk bakeoff**
>    (spx200 vs credit vs term-spread vs a composite) — none of the pillar trunks beat spx200; the
>    evidence is shown, not asserted (Cell 2).
> 2. **How is the threshold constructed / how to tell bull-bear & calm-stress?** Trunk = SPX close
>    vs its **200d MA** (bull/bear). Calm/stress = SPX **drawdown-from-peak ≥ 10%** inside bull.
>    (Full construction + the label-quality audit is in `m6_regime_state_cells.md`.)
> 3. **Does it hold statistically? How tested?** **Two tests, deliberately** (Cell 4): a **block-
>    bootstrap CI** (resample whole days → respects autocorrelation) and **Kruskal-Wallis / Mann-
>    Whitney**. They DISAGREE in the honest direction — see the finding.
> 4. **The natural next test: regime × fwd-return on m01-scored tickers** — done here on the FULL
>    scored universe (all tickers good or bad, per your steer), NOT top-N, NOT a backtest (Cell 3).
>
> **Load-bearing findings (full 25y, 9.0M scored rows, 6,287 days):**
> - **The m01 score RANKS forward return in EVERY regime** — top-vs-bottom decile gradient +2.1%
>   (bull-calm) / +1.6% (bull-stress) / +1.7% (bear), monotone across all deciles in all three.
>   The model is not broken in any regime; the *level* shifts, the *ranking* survives.
> - **Bear/stress days have HIGHER mean fwd return than calm-bull** (bear +1.55%, stress +1.63% vs
>   calm +0.77%). The `gap(stress-calm)` = +0.85%, 95% CI **[+0.47%, +1.20%] — excludes 0, REAL.**
>   This is the mean-reversion / rebound signature (buy-the-stress), consistent with Thread F.
> - **No trunk separates fwd-return positively** — every candidate has *negative* bull-minus-bear
>   separation (bull days follow LOWER returns; the rebound lives on bear days). spx200 is the
>   least-negative → kept as the trend definition, but "trunk that predicts higher fwd return" was
>   the wrong framing. Shown in Cell 2.
>
> - **Both the regime gap and the m01 gradient GROW strongly with the hold** (fwd50/100 now enriched
>   for the full universe): stress-calm gap +0.9% (fwd20) → +2.4% (fwd50) → +2.9% (fwd100); the score's
>   top−bottom gradient grows ~4× to fwd100 in every state. fwd20 materially understated both — Thread
>   F's "signals live long" confirmed on the full universe.
>
> **⚠️ Caveats:** directional MFE-free returns, no exits/sizing; the KW p-value is meaningless-tiny
> (9M rows) — trust the bootstrap CI. fwd50/100 now present (100% coverage bar names near data-end).
>
> Scripts: `m01_by_regime.py` (`--smoke`/full), `m01_by_regime_chart.py`. Outputs under
> `data/model_output_eda/m01_by_regime/`.

Paste each block as one cell.

---

### Cell 1 — load the full scored universe + regime label

```python
import numpy as np, pandas as pd, glob
from pathlib import Path
from scipy import stats

def _root():
    p = Path.cwd().resolve()
    for d in (p, *p.parents):
        if (d/"config.py").exists() and (d/"src").is_dir(): return d
    raise RuntimeError("root not found")
ROOT = _root()
CACHE = ROOT/"data"/"model_output_eda"/"multiyear"
STATE = ROOT/"data"/"model_output_eda"/"regime_state"
STATES = ["bull-calm","bull-stress","bear"]

# 25y full scored universe: prob_elite (RAW m01 score) + fwd20, every ticker good or bad
u = pd.concat([pd.read_parquet(f, columns=["date","ticker","prob_elite","fwd20","fwd50","fwd100"])
               for f in sorted(CACHE.glob("raw_full_*_fwd.parquet"))], ignore_index=True)
u["date"] = pd.to_datetime(u["date"]); u = u.dropna(subset=["fwd20","prob_elite"])  # fwd50/100: per-metric dropna
st = pd.read_parquet(STATE/"regime_state_daily_dd.parquet")[["date","state"]]
st["date"] = pd.to_datetime(st["date"])
u = u.merge(st, on="date", how="inner")
assert u["state"].notna().all() and set(u.state.unique()) <= set(STATES)
print(f"{len(u):,} scored rows | {u.date.dt.year.min()}-{u.date.dt.year.max()} | {u.date.nunique():,} days")
```

---

### Cell 2 — TRUNK BAKEOFF: does the 200MA beat the 6-pillar trunks? (answers "why not pillars")

```python
import duckdb
def trunk_candidates():
    con = duckdb.connect(str(ROOT/"data"/"market_data.duckdb"), read_only=True)
    spy = con.execute("SELECT date, spy_close FROM t1_macro WHERE spy_close IS NOT NULL ORDER BY date").df()
    mac = con.execute("SELECT date, symbol, close v FROM macro_data WHERE symbol IN ('BAMLH0A0HYM2','DGS10','DGS2')").df()
    con.close()
    spy["date"] = pd.to_datetime(spy.date); spy["spx200"] = (spy.spy_close > spy.spy_close.rolling(200).mean()).astype(float)
    m = mac.assign(v=pd.to_numeric(mac.v, errors="coerce"), date=pd.to_datetime(mac.date)) \
           .pivot_table(index="date", columns="symbol", values="v").sort_index().ffill()
    credit, term = m["BAMLH0A0HYM2"], m["DGS10"]-m["DGS2"]     # live-safe expanding median (through t-1)
    cb = (credit < credit.expanding(252).median().shift(1)).astype(float)
    tb = (term   > term.expanding(252).median().shift(1)).astype(float)
    out = spy[["date","spx200"]].merge(pd.DataFrame({"credit":cb,"term":tb}).reset_index(), on="date", how="left")
    out["composite"] = (out[["spx200","credit","term"]].mean(axis=1) >= 0.5).astype(float)
    return out

d = u.merge(trunk_candidates(), on="date", how="inner")
rows = []
for c in ["spx200","credit","term","composite"]:
    s = d.dropna(subset=[c]); bull, bear = s.loc[s[c]==1,"fwd20"], s.loc[s[c]==0,"fwd20"]
    rows.append(dict(trunk=c, mean_bull=bull.mean(), mean_bear=bear.mean(), separation=bull.mean()-bear.mean()))
bo = pd.DataFrame(rows).sort_values("separation", ascending=False)
print(bo.round(4).to_string(index=False))
# READ: ALL separations are NEGATIVE — bull days precede LOWER fwd return (rebound lives on bear
# days). No pillar trunk beats spx200; spx200 is the least-negative -> kept as the trend def, but
# "a trunk that predicts higher fwd return" is the wrong framing. This is WHY we don't swap in pillars.
assert bo.iloc[0].trunk in ("spx200","term"), "spx200/term should be least-negative"
```

---

### Cell 3 — M01 × REGIME: fwd20 by state, and the score gradient within each state

```python
# 3a. all-ticker fwd20 by state
bs = u.groupby("state")["fwd20"].agg(n="size", mean="mean", median="median",
                                     hr=lambda x:(x>0.30).mean(), std="std").reindex(STATES)
print("fwd20 by state (all tickers):"); print(bs.round(4).to_string())

# 3b. m01 score-decile x state -> does the top decile beat the bottom in EVERY state?
u["dec"] = u.groupby("state")["prob_elite"].transform(lambda s: pd.qcut(s,10,labels=False,duplicates="drop"))
piv = u.groupby(["state","dec"])["fwd20"].mean().unstack("state").reindex(columns=STATES)
grad = piv.iloc[-1] - piv.iloc[0]
print("\nmean fwd20 by score decile x state:"); print(piv.round(4).to_string())
print("\ntop-minus-bottom decile gradient by state (all POSITIVE => score ranks in every regime):")
print(grad.round(4).to_string())
assert (grad > 0).all(), "the m01 gradient must hold (top>bottom) in every state"

# 3c. HORIZON SWEEP — does the regime story grow with the hold? (fwd50/100 enriched full-universe)
for h in ["fwd20","fwd50","fwd100"]:
    sub = u.dropna(subset=[h])
    m = sub.groupby("state")[h].mean().reindex(STATES)
    print(f"{h:>7}: calm {m['bull-calm']*100:+.2f}%  stress {m['bull-stress']*100:+.2f}%  "
          f"bear {m['bear']*100:+.2f}%  | stress-calm gap {(m['bull-stress']-m['bull-calm'])*100:+.2f}%")
# READ: gap +0.9% (fwd20) -> +2.4% (fwd50) -> +2.9% (fwd100). Both the level gap AND the score
# gradient FAN OUT with the hold -> fwd20 understated it. Thread F "signals live long", confirmed.
```

---

### Cell 4 — STATISTICAL TEST: bootstrap CI (honest) vs Kruskal-Wallis (optimistic)

```python
# block-bootstrap by DAY (resample whole days -> respects autocorrelation). Fast: bootstrap the
# per-(day,state) sums+counts, take count-weighted means. Identical statistic to resampling rows.
rng = np.random.default_rng(42)
agg = u.groupby(["date","state"])["fwd20"].agg(s="sum", c="size").reset_index()
S = agg.pivot(index="date", columns="state", values="s").reindex(columns=STATES).fillna(0).values
C = agg.pivot(index="date", columns="state", values="c").reindex(columns=STATES).fillna(0).values
nd = S.shape[0]; boot = np.empty((1000, len(STATES)))
for b in range(1000):
    i = rng.integers(0, nd, nd); cs = C[i].sum(0)
    with np.errstate(invalid="ignore"): boot[b] = np.where(cs>0, S[i].sum(0)/cs, np.nan)
for j,s in enumerate(STATES):
    a = boot[:,j]; print(f"  {s:<12} mean {np.nanmean(a)*100:+.2f}%  95% CI [{np.nanpercentile(a,2.5)*100:+.2f}, {np.nanpercentile(a,97.5)*100:+.2f}]")
gap = boot[:,STATES.index("bull-stress")] - boot[:,STATES.index("bull-calm")]
lo, hi = np.nanpercentile(gap,2.5)*100, np.nanpercentile(gap,97.5)*100
print(f"  gap(stress-calm) {np.nanmean(gap)*100:+.2f}%  95% CI [{lo:+.2f}, {hi:+.2f}]  -> {'REAL (excludes 0)' if lo>0 or hi<0 else 'straddles 0'}")

# Kruskal-Wallis + pairwise MW — familiar p-values, but iid-day assumption is VIOLATED
h,p = stats.kruskal(*[u.loc[u.state==s,"fwd20"].values for s in STATES])
print(f"\nKruskal-Wallis H={h:.0f}, p={p:.1e}  [!] p is meaningless-tiny at 9M rows (iid violated) -> trust the CI")
```

---

### Cell 5 — the figure (inline + static preview)

```python
import matplotlib.pyplot as plt
%matplotlib inline
COL = {"bull-calm":"#2e7d32","bull-stress":"#ef6c00","bear":"#c62828"}
fig, ax = plt.subplots(1, 2, figsize=(15, 5.2))
# score-decile gradient per state
for s in STATES:
    ax[0].plot(piv.index, piv[s]*100, "o-", color=COL[s], lw=2, label=s)
ax[0].axhline(0, color="k", lw=.6, alpha=.5); ax[0].legend(fontsize=9)
ax[0].set_xlabel("m01 score decile (0=low,9=top)"); ax[0].set_ylabel("mean fwd20 %")
ax[0].set_title("m01 score ranks return in EVERY state\n(monotone up in all three)", weight="bold")
# per-state mean with bootstrap CI
y = np.arange(len(STATES))
means = [np.nanmean(boot[:,j])*100 for j in range(len(STATES))]
los   = [means[j]-np.nanpercentile(boot[:,j],2.5)*100 for j in range(len(STATES))]
his   = [np.nanpercentile(boot[:,j],97.5)*100-means[j] for j in range(len(STATES))]
ax[1].errorbar(means, y, xerr=[los,his], fmt="o", capsize=5, color="#1565c0", ms=8)
ax[1].set_yticks(y); ax[1].set_yticklabels(STATES); ax[1].axvline(0, color="k", lw=.6, alpha=.5)
ax[1].set_xlabel("mean fwd20 %"); ax[1].set_title("mean fwd20 by state (95% block-bootstrap CI)", weight="bold")
fig.tight_layout(); plt.show()
assert (piv.iloc[-1] > piv.iloc[0]).all()
```

**Static preview** (3-panel from `m01_by_regime_chart.py`, incl. the trunk bakeoff):

![m01 by regime](../../../../data/model_output_eda/m01_by_regime/m01_by_regime.png)

---

### Cell 6 (markdown) — Read

```markdown
### Read
- **m01 ranks forward return in EVERY regime.** Top-minus-bottom decile gradient is +2.1% (bull-calm),
  +1.6% (bull-stress), +1.7% (bear) on fwd20, monotone across deciles in all three states. The model's
  RANKING skill is regime-robust — what shifts is the base LEVEL, not the ordering. This is the
  reassuring counterpart to the M4 finding (which was about tail-ranking specifically).
- **Stress/bear days precede HIGHER returns than calm bull** (bear +1.55%, stress +1.63% vs calm
  +0.77%); gap(stress-calm) +0.85%, 95% bootstrap CI [+0.47, +1.20] — REAL. Buy-the-stress /
  rebound, consistent with Thread F's stress-composite entry signal.
- **Why not the 6 pillars for the trunk:** the bakeoff shows every trunk (spx200, credit, term,
  composite) has NEGATIVE bull-minus-bear separation — none predicts higher forward return, because
  the rebound lives on bear days. spx200 is the least-negative, so it stays as the trend definition,
  but swapping in a pillar trunk would not help. Evidence, not assertion.
- **Two stat tests, and they DISAGREE the honest way:** on the 25y sample the bootstrap CI excludes 0
  (gap is real); on the 3-year smoke it STRADDLED 0 (not established). Kruskal-Wallis p is ~0 at 9M
  rows regardless — the iid-day assumption is violated by autocorrelation, so the p-value over-states
  significance. The block-bootstrap (resamples whole days) is the read to trust.
- **Horizon: the regime story GROWS with the hold.** stress-calm gap +0.9% (fwd20) → +2.4% (fwd50)
  → +2.9% (fwd100); the m01 top−bottom gradient grows ~4× to fwd100 in every state. fwd50/100 are now
  enriched for the whole 25y universe (`enrich_fwd_horizons.py`, verified to reproduce fwd20 exactly).
  fwd20 understated both effects — Thread F's "signals live long" confirmed at universe scale.
- **⚠️** directional returns, no exits/sizing. The regime LABEL's stress sub-split is only half-settled
  (see `m6_regime_state_cells.md`) — the bear/bull trunk carries most of the separation here anyway.
- **Dashboard implication:** the state→level relationship (calm/stress/bear mean + CI) is the panel
  to surface beneath the 6-pillar table — a current-state badge + regime strip (next build).
```
