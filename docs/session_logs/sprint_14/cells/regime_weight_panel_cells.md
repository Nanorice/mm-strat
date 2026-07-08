# Point-8 — regime-weighting the top-5 fwd-return panel (the governor's cheapest test)

> **What this answers (log point 8 / the REGIME-BLIND close):** the m01 score is regime-blind — it
> keeps signalling "buy these 5" into a falling market, so the deploy rule's outcome is dominated by
> WHEN you start (a lottery). The fix is an EXTERNAL regime governor. Before building a backtest,
> the cheapest honest test: **apply an entry-date regime weight to the EXISTING per-day top-5
> fwd-return panel and see if it lowers the AVERAGE and WORST-DECILE loss.** Two weights, both
> already on the panel:
> - **(a) crude SPY-200MA 2-state** — bull = full weight, bear = 0 (the trunk governor).
> - **(b) continuous `stress_ew_vix`, SPY>200d-gated** — the Thread F 6-pillar tilt in native form.
>
> **Load-bearing findings:**
> 1. **(a) the crude bear-gate is a variance brake, not free alpha.** Cutting bear days lifts the
>    worst-decile by **+5.0pp** (−34.9% → −29.8%) but *lowers* the mean **−1.0pp** — because bear
>    days carry the highest mean fwd100 (+16.6%, the rebound) AND the worst tail (−51%). You trade
>    return for downside. Honest read: a risk brake you'd pay for, not a Sharpe free-lunch.
> 2. **(b) the stress-gated tilt improves BOTH** — mean +0.8pp (12.5% → 13.3%) AND worst-decile
>    +6.0pp (−34.9% → −28.9%) — by concentrating capital into **bull-stress** (the +12.1% mean /
>    −27% tail state) and away from both bull-calm noise and the bear knife. But it only deploys
>    **17.8% of capital** → it's a concentration rule, not a full-deployment governor; the mean is
>    per-dollar-deployed, not per-calendar-day.
> 3. **The whole effect is a fwd100 story** — at fwd20 the deltas are ~⅓ the size (both signal and
>    recovery live long, cf Thread F). Judge the governor on fwd100.
>
> No backtest, no exits/sizing, no scoring — pure reweight of
> `data/model_output_eda/entry_timing/entry_timing_daily.parquet` (5650 days, per-day top-5 mean
> fwd) joined to `regime_state/regime_state_daily_dd.parquet` (SPY-200MA state). Weight is on the
> **entry-date** regime only (what you knew at deploy — no look-ahead). Runnable:
> `docs/session_logs/sprint_14/scripts/regime_weight_panel.py` (+ `_chart.py`).

Paste each block as one cell.

---

### Cell 1 — load the panel + the entry-date regime label

```python
import numpy as np, pandas as pd
from pathlib import Path

def _root():
    p = Path.cwd().resolve()
    for d in (p, *p.parents):
        if (d/"config.py").exists() and (d/"src").is_dir(): return d
    raise RuntimeError("root not found")
ROOT = _root()
HORIZ = "fwd100"                                        # judge on fwd100 — biggest gap

et = pd.read_parquet(ROOT/"data/model_output_eda/entry_timing/entry_timing_daily.parquet")
dd = pd.read_parquet(ROOT/"data/model_output_eda/regime_state/regime_state_daily_dd.parquet")
df = et.merge(dd[["date","state"]], on="date", how="left").dropna(subset=[HORIZ]).reset_index(drop=True)
f  = df[HORIZ].values                                   # per-day mean top-5 fwd return

assert (df["spy_above200"] == et.set_index("date").loc[df.date,"spy_above200"].values).all()  # panel carries the gate
print(f"{len(df)} deploy dates | {df.date.min():%Y-%m}..{df.date.max():%Y-%m}")
print("states:", df["state"].value_counts().to_dict())
```

---

### Cell 2 — weight-aware mean + worst-decile (the two judges)

```python
def wmean(f, w):                                        # capital-weighted realized mean
    return float(np.sum(w*f) / np.sum(w))

def w_worst_decile(f, w):                               # mean of the worst 10% of DEPLOYED capital
    o = np.argsort(f); fo, wo = f[o], w[o]              # ascending — worst first
    k = np.searchsorted(np.cumsum(wo), 0.10*wo.sum()) + 1
    return wmean(fo[:k], wo[:k])

# sanity: flat weights -> ordinary bottom-decile mean; scale-invariant
_f = np.random.default_rng(0).standard_normal(1000)
assert abs(w_worst_decile(_f, np.ones(1000)) - np.sort(_f)[:100].mean()) < 0.02
assert abs(w_worst_decile(_f, np.full(1000,3.0)) - w_worst_decile(_f, np.ones(1000))) < 1e-9
print("weight math ok")
```

---

### Cell 3 — the three deploy rules (weight on the ENTRY-DATE regime)

```python
bull = (df["state"] != "bear").values.astype(float)     # SPY>200d, known at the open

def weights(kind, bear_w=0.0):
    if kind == "flat":   return np.ones(len(df))
    if kind == "spx200": return np.where(bull>0, 1.0, bear_w)          # (a) 2-state
    if kind == "stress":                                              # (b) 6-pillar tilt, bull-gated
        s = df["stress_ew_vix"].values
        z = (s - np.nanmin(s)) / (np.nanmax(s) - np.nanmin(s))        # live composite -> [0,1] tilt
        return bull * np.nan_to_num(z, nan=0.5)                       # bear -> 0 (falling-knife); warmup -> neutral

rules = [("flat","FLAT (no governor)"), ("spx200","(a) SPY-200MA, bear=0"),
         ("stress","(b) stress_ew_vix, bull-gated")]
res = pd.DataFrame([dict(rule=lbl, mean=wmean(f, weights(k)), worst_decile=w_worst_decile(f, weights(k)),
                         deployed_frac=weights(k).sum()/len(df)) for k,lbl in rules])
base = res.iloc[0]
res["d_mean"]  = res["mean"] - base["mean"]
res["d_worst"] = res["worst_decile"] - base["worst_decile"]
pd.set_option("display.float_format", lambda x: f"{x:+.4f}")
print(res.to_string(index=False))
# READ: a governor helps iff d_mean>0 AND d_worst>0 (tail less negative). (a) helps only the tail; (b) helps both.
```

---

### Cell 4 — WHY: fwd100 by state (bear = highest mean, worst tail)

```python
g = df.groupby("state")[HORIZ]
by_state = pd.DataFrame({
    "mean":         g.mean(),
    "worst_decile": g.apply(lambda x: x.nsmallest(max(1,len(x)//10)).mean()),
    "n":            g.size(),
}).loc[["bull-calm","bull-stress","bear"]]
print(by_state.to_string())
print(f"\nbear pos-share {(df[df.state=='bear'][HORIZ]>0).mean():.0%} "
      f"| bear top-decile {df[df.state=='bear'][HORIZ].nlargest(109).mean():+.0%}  (the rebound)")
# READ: bear has the HIGHEST mean (+16.6%, rebound) AND the worst tail (-51%). (a) cutting bear loses the
#       rebound (mean drops) but removes the knife (tail up). (b) sends capital to bull-stress -> both improve.
```

---

### Cell 5 — horizon sweep (the effect is a long-hold one)

```python
sweep = []
for h in ("fwd20","fwd50","fwd100"):
    d = et.merge(dd[["date","state"]], on="date", how="left").dropna(subset=[h]).reset_index(drop=True)
    b = (d["state"]!="bear").values.astype(float); fh = d[h].values
    def w(kind):
        if kind=="flat":   return np.ones(len(d))
        if kind=="spx200": return np.where(b>0,1.0,0.0)
        s=d["stress_ew_vix"].values; z=(s-np.nanmin(s))/(np.nanmax(s)-np.nanmin(s))
        return b*np.nan_to_num(z,nan=0.5)
    for k in ("flat","spx200","stress"):
        sweep.append(dict(horizon=h, rule=k, mean=wmean(fh,w(k)), worst_decile=w_worst_decile(fh,w(k))))
sw = pd.DataFrame(sweep)
print("mean:\n",         sw.pivot(index="rule",columns="horizon",values="mean").to_string())
print("\nworst-decile:\n", sw.pivot(index="rule",columns="horizon",values="worst_decile").to_string())
# READ: deltas at fwd20 are ~1/3 the fwd100 size. Governor + recovery both live long -> judge on fwd100.
```

---

### Cell 6 — the figure

```python
import matplotlib.pyplot as plt
fig, ax = plt.subplots(1, 3, figsize=(16, 5))
labels = ["flat","(a) SPY200\nbear=0","(b) stress\nbull-gated"]; cols = ["#90a4ae","#1565c0","#2e7d32"]
means = [wmean(f, weights(k)) for k,_ in rules]; worst = [w_worst_decile(f, weights(k)) for k,_ in rules]

b = ax[0].bar(labels, [m*100 for m in means], color=cols, width=.6)
for r,v in zip(b,means): ax[0].text(r.get_x()+.3, v*100+.2, f"{v:+.1%}", ha="center", weight="bold")
ax[0].axhline(means[0]*100, color="#90a4ae", ls="--", alpha=.6); ax[0].set_title("mean fwd100"); ax[0].set_ylabel("%")

b = ax[1].bar(labels, [w*100 for w in worst], color=cols, width=.6)
for r,v in zip(b,worst): ax[1].text(r.get_x()+.3, v*100-1.5, f"{v:+.1%}", ha="center", weight="bold")
ax[1].axhline(worst[0]*100, color="#90a4ae", ls="--", alpha=.6); ax[1].set_title("worst-decile fwd100 (the drag)"); ax[1].set_ylabel("%")

st=["bull-calm","bull-stress","bear"]; x=np.arange(3)
gm=[by_state.loc[s,"mean"]*100 for s in st]; gw=[by_state.loc[s,"worst_decile"]*100 for s in st]
ax[2].bar(x-.2, gm, .4, label="mean", color="#2e7d32"); ax[2].bar(x+.2, gw, .4, label="worst-decile", color="#c62828")
ax[2].set_xticks(x); ax[2].set_xticklabels(st, fontsize=9); ax[2].axhline(0,color="k",lw=.8)
ax[2].set_title("fwd100 by state — bear = highest mean, worst tail"); ax[2].legend()

fig.suptitle("Point-8 — regime-weighting the top-5 fwd100 panel (EDA reweight, no backtest)", weight="bold")
plt.tight_layout(); plt.show()
```

**Saved figure:** `data/model_output_eda/regime_weight/regime_weight_fwd100.png`

![regime-weight panel](../../../../data/model_output_eda/regime_weight/regime_weight_fwd100.png)

---

### Cell 7 (markdown) — Read

```markdown
### Read — the governor reduces the drag, so it EARNS a backtest (but the two weights do different jobs)

- **(a) The crude SPY-200MA bear-gate is a variance brake, not free alpha.** Sitting out bear days
  cuts the worst-decile loss +5.0pp (−34.9% → −29.8%) but costs −1.0pp of mean, because bear days
  hold BOTH the highest mean fwd100 (+16.6% rebound) and the worst tail (−51% knife). This is the
  honest shape of the "coincident bull/bear is ENOUGH" trunk: it trades return for downside — a risk
  preference, not a Sharpe free-lunch. It answers point-8 half-yes: worst-decile ↓, mean ↓.
- **(b) The stress_ew_vix bull-gated tilt improves BOTH** — mean +0.8pp AND worst-decile +6.0pp — by
  concentrating into bull-stress (the good-mean / contained-tail state) and away from bull-calm noise
  and the bear knife. It is the better governor on this panel. ⚠️ but it deploys only ~18% of capital,
  so its mean is per-dollar-deployed; as a full-book rule it needs a floor/scaling decision the
  backtest will force. It re-confirms Thread F's "deploy more when stress EXTREME & SPY>200d" —
  now shown to cut the DRAG, not just lift the mean.
- **Point-8 verdict: promote to backtest.** At least one weight lowers both the average and the
  worst-decile loss, so the governor is not a no-op on the EDA panel — the backtest work is earned,
  not saved. Carry BOTH weights in: (a) as the simple full-deployment brake, (b) as the
  concentration tilt; the backtest decides deployment scaling and whether (b)'s 18% duty-cycle is
  acceptable.
- **It's a long-hold effect.** At fwd20 the deltas are ~⅓ the fwd100 size — the governor and the
  recovery both live long (Thread F). Judge on fwd100.
- **⚠️ EDA reweight, not a P&L verdict.** Directional close-to-close top-5 mean returns, no exits, no
  sizing, no transaction cost; worst-decile is a capital-weighted lower tail of daily means, not a
  realized drawdown. The regime label's stress sub-split is 2013+/half-settled
  ([[project_regime_during_period_goal]]) — but (a) rides only the full-25y bear/bull trunk, and
  (b)'s tilt is the already-vetted live-safe composite. Backtest through the start-date cone (M2)
  before wiring.
```

---
---

## Part 2 — start-date drift & the 6-pillar picture (user, 2026-07-08)

> **Q1 — does the strategy drift up, or is it a start-date lottery?** We have the RAW score + fwd20/50/100
> for the *full universe* across all 25 years (`data/model_output_eda/multiyear/raw_full_*_fwd.parquet`,
> ~1,500 names/day). Rank each day by score, take the **top-1/5/10**, average their fwd return, and
> **cumulate the daily basket return** per representative period. Up-slope ⇒ deploying on successive days
> compounds a real edge; flat/down ⇒ outcome is dominated by WHEN you start (the lottery this whole
> thread is about).
>
> **Q2 — how do the 6 macro pillars move with the return curve?** No consolidated pillar metric yet, so
> plot each pillar's **expanding-window percentile** (live-safe: today's rank within all history to date)
> as a stack beneath the full-span top-5 curve, to eyeball what the macro backdrop looks like while the
> curve climbs vs stalls.
>
> **Load-bearing findings:**
> 1. **Drift is real in bull/rebound regimes, and it INVERTS in the GFC.** Cumulative top-5 fwd20 slope
>    per 100 deploy-days: +2.8 (2003-07 bull), +1.6 (2013-15 calm), **+13.2 (2020 COVID rebound)**,
>    +3.2 (2023-25) — but **−1.9 in 2007-09 GFC**. Same regime-blindness, drawn as a start-date curve:
>    deploy any day in a bull and you drift up; deploy into the GFC and you bleed regardless of the day.
> 2. **top-5 ≈ top-10, top-1 noisier** — confirms the "sharp cliff at 5, no order inside"
>    ([[project_capital_deployment]]); top-1 swings hardest (concentration = variance), especially in 2022.

---

### Cell 8 — Q1 setup: top-N daily basket per period (pre-reduced to top-15/day)

```python
# One-time reduce (skip if _topN_scratch.parquet exists): keep top-15 by score per day, all 25 years.
import glob
scratch = ROOT/"data/model_output_eda/regime_weight/_topN_scratch.parquet"
if not scratch.exists():
    frames = []
    for fp in sorted(glob.glob(str(ROOT/"data/model_output_eda/multiyear/raw_full_*_fwd.parquet"))):
        d = pd.read_parquet(fp, columns=["date","prob_elite","fwd20","fwd50","fwd100"])
        frames.append(d.sort_values("prob_elite", ascending=False).groupby("date").head(15))
    pd.concat(frames, ignore_index=True).to_parquet(scratch)
topn = pd.read_parquet(scratch)

PERIODS = [("2003-07-01","2007-06-30","2003-07 bull"), ("2007-07-01","2009-06-30","2007-09 GFC"),
           ("2013-01-01","2015-12-31","2013-15 calm bull"), ("2020-01-01","2020-12-31","2020 COVID"),
           ("2022-01-01","2022-12-31","2022 bear"), ("2023-01-01","2025-12-31","2023-25 recent")]

def daily_topn(df_, n, h):                              # mean fwd of the top-n scored names each day
    g = df_.sort_values("prob_elite", ascending=False).groupby("date").head(n)
    return g.groupby("date")[h].mean().sort_index()

print("days", topn.date.nunique(), "|", topn.date.min().date(), "->", topn.date.max().date())
```

---

### Cell 9 — Q1: cumulative drift slope per period (the number behind the chart)

```python
rows = []
for start, end, label in PERIODS:
    sub = topn[(topn.date>=start) & (topn.date<=end)]
    rows.append({"period": label, **{f"top{n}": daily_topn(sub,n,"fwd20").cumsum().diff().mean()*100
                                     for n in (1,5,10)}})
slope = pd.DataFrame(rows).set_index("period")
pd.set_option("display.float_format", lambda x: f"{x:+.2f}")
print("cumulative top-N fwd20 slope  (mean daily increment x100 = ~%/100 deploy-days):")
print(slope.to_string())
# READ: +ve & similar across N => real drift; GFC is NEGATIVE (bleed) -> start-date lottery bites in a crash.
```

---

### Cell 10 — Q1 figure: 6 periods × top-1/5/10 cumulative curve

```python
import matplotlib.pyplot as plt
fig, ax = plt.subplots(2, 3, figsize=(17, 9)); cols = {1:"#c62828",5:"#1565c0",10:"#2e7d32"}
for a, (start,end,label) in zip(ax.flat, PERIODS):
    sub = topn[(topn.date>=start) & (topn.date<=end)]
    for n in (1,5,10):
        s = daily_topn(sub,n,"fwd20").cumsum()
        a.plot(s.index, s.values*100, color=cols[n], lw=1.6, label=f"top-{n}")
    a.axhline(0, color="k", lw=.7, alpha=.5); a.set_title(label, weight="bold")
    a.set_ylabel("cum. mean fwd20 (%)"); a.legend(fontsize=8, loc="upper left")
    a.tick_params(axis="x", labelrotation=30, labelsize=8)
fig.suptitle("Q1 — deploy-from-any-day drift: cumulative top-N mean fwd20 per period\n"
             "(up-slope = real edge; flat/down = start-date lottery)", weight="bold")
plt.tight_layout(); plt.show()
```

**Saved figure:** `data/model_output_eda/regime_weight/start_date_drift.png`

![start-date drift](../../../../data/model_output_eda/regime_weight/start_date_drift.png)

---

### Cell 11 — Q2: 6-pillar expanding percentile + full-span top-5 curve

```python
pil = ["pil_vix","pil_credit","pil_term","pil_rates","pil_liq","pil_cape"]
p = et[["date"]+pil].sort_values("date").reset_index(drop=True)
for c in pil:                                          # expanding percentile = rank of today in history-to-date (live-safe)
    p[c+"_pct"] = p[c].expanding().apply(lambda x: (x.iloc[-1] >= x).mean(), raw=False)
curve5 = daily_topn(topn[topn.date>=p.date.min()], 5, "fwd20").cumsum()

nice = {"pil_vix":"VIX","pil_credit":"Credit","pil_term":"Term","pil_rates":"Rates","pil_liq":"Liquidity","pil_cape":"CAPE"}
pcols = ["#6a1b9a","#c62828","#00838f","#ef6c00","#2e7d32","#455a64"]
fig, ax = plt.subplots(7, 1, figsize=(15, 12), sharex=True, gridspec_kw={"height_ratios":[2.2]+[1]*6})
ax[0].plot(curve5.index, curve5.values*100, color="#1565c0", lw=1.7); ax[0].axhline(0,color="k",lw=.7,alpha=.5)
ax[0].set_ylabel("cum. top-5\nfwd20 (%)"); ax[0].grid(alpha=.25)
ax[0].set_title("Q2 — 6-pillar macro (expanding percentile, live-safe) vs the top-5 return curve", weight="bold")
for a, c, col in zip(ax[1:], [c+"_pct" for c in pil], pcols):
    a.fill_between(p.date, 0, p[c]*100, color=col, alpha=.35); a.plot(p.date, p[c]*100, color=col, lw=1)
    a.set_ylim(0,100); a.set_yticks([0,50,100]); a.axhline(50,color="k",lw=.5,alpha=.3); a.grid(alpha=.2)
    a.set_ylabel(nice[c.replace("_pct","")], rotation=0, ha="right", va="center", fontsize=10)
ax[-1].set_xlabel("date"); plt.tight_layout(); plt.show()
# READ: pillars are DAILY-noisy but the low-freq shape tracks regimes — credit/VIX percentile spike into
#       2008 & 2020 (where the curve stalls/dips), CAPE only starts 2012, liquidity jumps at 2020 QE.
```

**Saved figure:** `data/model_output_eda/regime_weight/pillars_vs_curve.png`

![pillars vs curve](../../../../data/model_output_eda/regime_weight/pillars_vs_curve.png)

---

### Cell 12 (markdown) — Read (Q1 + Q2)

```markdown
### Read — the drift is regime-gated; the pillars are the backdrop, not yet a consolidated signal

- **Q1: deploy-from-any-day drift is REAL in bull/rebound regimes and INVERTS in the GFC.** Cumulative
  top-5 fwd20 slope per 100 deploy-days: 2020 COVID +13.2, 2023-25 +3.2, 2003-07 +2.8, 2013-15 +1.6 —
  all steady up-slopes, so within a bull/recovery the start-DAY barely matters (you drift up whenever
  you start). But 2007-09 GFC is **−1.9**: deploy into the crash and you bleed regardless of the day.
  This IS the regime-blindness redrawn as an equity curve — the edge is a bull-regime property, which
  is exactly why the point-8 governor (gate/tilt off SPY-200d + stress) is the fix.
- **top-5 ≈ top-10, top-1 is the noisy one.** The 5/10 curves track each other (the "sharp cliff at 5,
  flat inside" from [[project_capital_deployment]]); top-1 swings widest (concentration = variance),
  most visibly in 2022. Basket width buys smoothness, not more mean.
- **Q2: the 6 pillars are a legible macro BACKDROP, not yet a consolidated signal.** As expanding
  percentiles they're daily-noisy but the low-frequency shape tracks regimes — credit & VIX percentiles
  spike into 2008 and 2020 (where the curve stalls/dips), rates fall through those windows, CAPE only
  exists 2012+. This is the raw material behind `stress_ew_vix` (+credit −rates −cape +vix); the
  consolidated version is that composite ([[project_entry_timing_macro_axis]]).
  - ⚠️ **EXPANDING percentile is BROKEN for the two TRENDING pillars — see Part 3/C5 for the fix.**
    Net Liquidity (corr w/ time +0.96) and CAPE (+0.91) only ever ramp up, so their expanding percentile
    is pinned at ~100% after 2004 (it just re-encodes "later = higher", not a regime signal). VIX/credit/
    term/rates are cyclical so expanding-pct is fine there. Part 3 replaces it with a ROLLING 2yr
    percentile, which shows the cyclical position for all six.
- **⚠️ Same EDA caveats.** Directional close-to-close fwd returns, no exits/sizing; cumulative sum is a
  deploy-every-day proxy path, not a realized equity curve (no capital constraint, one basket/day
  overlapping). Percentiles are expanding (live-safe) so no look-ahead, but they're a visualization, not
  a fitted feature.
```

---
---

## Part 3 — non-cumulative returns, whole-period view, fixed pillars (user follow-ups, 2026-07-08)

> **User asks:** (1) plot the NON-cumulative return — each point = a day's top-N basket entry and its
> realized fwd return, so we see what the cumulative curve is summing. (2) A whole-period chart to see
> the regime changes directly. (3) On the pillars: CAPE is blank before ~2012, and Liquidity never drops
> below 50% after 2004 — why?
>
> **Answers to (3), both REAL data facts, not bugs:**
> - **CAPE starts 2012-12-03.** `pil_cape` = `CAPE_OURS`, self-computed (`cape_engine.py`); the Shiller
>   feed is dormant and the self-computed series only begins end-2012. Genuinely absent before, not dropped.
> - **Liquidity pinned >50% because it's a TRENDING series under an EXPANDING percentile.** Net Liquidity
>   rose ~monotonically (738 in 2003 → 6,095 in 2024, corr-with-time +0.96 — Fed balance sheet/reserves
>   only grow at this scale). An expanding percentile of a rising series is always near its own running
>   max → stuck at ~100%. Same for CAPE (+0.91). **Fix = rolling 2yr percentile (C5)** → both now oscillate
>   and reveal QT drawdowns (Liq dips 2018/2022) instead of a flat ceiling.
>
> **On (1):** yes — Part 2's curve is a **cumulative SUM** of each day's top-N mean fwd20. C3/C4 show the
> raw per-day points it integrates.

---

### Cell 13 — C3: NON-cumulative per-day top-5 fwd20 per period

```python
fig, ax = plt.subplots(2, 3, figsize=(17, 9))
for a, (start, end, label) in zip(ax.flat, PERIODS):
    sub = topn[(topn.date>=start) & (topn.date<=end)]
    d5 = daily_topn(sub, 5, "fwd20") * 100                 # each point = one day's top-5 basket, realized fwd20
    a.scatter(d5.index, d5.values, s=6, alpha=.35, color="#1565c0", label="top-5 daily")
    roll = d5.rolling(21, min_periods=5).mean()
    a.plot(roll.index, roll.values, color="#0d47a1", lw=1.8, label="21d-avg")
    a.axhline(0, color="k", lw=.7); a.axhline(d5.mean(), color="#c62828", ls="--", lw=1, label=f"mean {d5.mean():+.1f}%")
    a.set_title(label, weight="bold"); a.set_ylabel("fwd20 (%)")
    a.legend(fontsize=7, loc="upper left"); a.tick_params(axis="x", labelrotation=30, labelsize=8)
fig.suptitle("C3 - NON-cumulative: each point = a day's top-5 basket, its realized fwd20", weight="bold")
plt.tight_layout(); plt.show()
# READ: the cumulative curve is the running SUM of these points. A positive mean line (red) => drift up;
#       GFC/bear panels sit near/below 0 with fat downside scatter.
```

**Saved figure:** `data/model_output_eda/regime_weight/drift_noncumulative.png`

![non-cumulative drift](../../../../data/model_output_eda/regime_weight/drift_noncumulative.png)

---

### Cell 14 — C4: whole period (2001-2025), raw + cumulative + regime shading

```python
from matplotlib.dates import YearLocator
dd = pd.read_parquet(ROOT/"data/model_output_eda/regime_state/regime_state_daily_dd.parquet")[["date","state"]]

def shade(ax, reg):                                        # red=bear, orange=bull-stress
    r = reg.sort_values("date").reset_index(drop=True); r["blk"] = (r.state != r.state.shift()).cumsum()
    for _, g in r.groupby("blk"):
        col = {"bear":"#e57373","bull-stress":"#ffcc80"}.get(g.state.iloc[0])
        if col: ax.axvspan(g.date.iloc[0], g.date.iloc[-1], color=col, alpha=.25, lw=0)

d5 = daily_topn(topn, 5, "fwd20") * 100
fig, ax = plt.subplots(2, 1, figsize=(16, 9), sharex=True, gridspec_kw={"height_ratios":[1,1.2]})
for a in ax: shade(a, dd)
ax[0].scatter(d5.index, d5.values, s=4, alpha=.25, color="#1565c0")
ax[0].plot(d5.rolling(63,min_periods=10).mean().index, d5.rolling(63,min_periods=10).mean().values,
           color="#0d47a1", lw=1.6, label="63d-avg fwd20")
ax[0].axhline(0,color="k",lw=.7); ax[0].set_ylim(-40,60); ax[0].set_ylabel("daily top-5 fwd20 (%)"); ax[0].legend(loc="upper left")
ax[0].set_title("C4 - whole period: raw daily top-5 fwd20 (shade: red=bear, orange=bull-stress)", weight="bold")
ax[1].plot(d5.index, d5.cumsum().values, color="#1565c0", lw=1.7); ax[1].axhline(0,color="k",lw=.7)
ax[1].set_ylabel("cumulative (%)"); ax[1].set_xlabel("date"); ax[1].xaxis.set_major_locator(YearLocator(2))
ax[1].tick_params(axis="x", labelrotation=45); ax[1].set_title("cumulative sum - slope goes flat/down inside bear bands")
plt.tight_layout(); plt.show()
# READ: the red bear bands (2001-02, 2008, 2020, 2022) line up with the flat/declining stretches of the
#       cumulative curve -> the regime change IS visible; the drift is a bull-regime phenomenon.
```

**Saved figure:** `data/model_output_eda/regime_weight/drift_wholeperiod.png`

![whole period](../../../../data/model_output_eda/regime_weight/drift_wholeperiod.png)

---

### Cell 15 — C5: 6-pillar ROLLING 2yr percentile (fixes trending Liq/CAPE)

```python
ROLL = 504                                                 # ~2yr trading days
p = et[["date"]+pil].sort_values("date").reset_index(drop=True)
for c in pil:                                              # rolling percentile: rank of today within trailing 2yr (live-safe)
    p[c+"_rp"] = p[c].rolling(ROLL, min_periods=126).apply(lambda x:(x.iloc[-1]>=x).mean(), raw=False)
curve5 = (daily_topn(topn[topn.date>=p.date.min()], 5, "fwd20")*100).cumsum()

fig, ax = plt.subplots(7, 1, figsize=(15, 12), sharex=True, gridspec_kw={"height_ratios":[2.2]+[1]*6})
shade(ax[0], dd); ax[0].plot(curve5.index, curve5.values, color="#1565c0", lw=1.7)
ax[0].axhline(0,color="k",lw=.7,alpha=.5); ax[0].grid(alpha=.25); ax[0].set_ylabel("cum. top-5\nfwd20 (%)")
ax[0].set_title("C5 - 6-pillar ROLLING 2yr percentile (live-safe; fixes trending Liq/CAPE) vs top-5 curve", weight="bold")
for a, c, col in zip(ax[1:], pil, pcols):
    shade(a, dd); a.fill_between(p.date, 0, p[c+"_rp"]*100, color=col, alpha=.35); a.plot(p.date, p[c+"_rp"]*100, color=col, lw=1)
    a.set_ylim(0,100); a.set_yticks([0,50,100]); a.axhline(50,color="k",lw=.5,alpha=.3); a.grid(alpha=.2)
    a.set_ylabel(nice[c], rotation=0, ha="right", va="center", fontsize=10)
ax[-1].set_xlabel("date"); plt.tight_layout(); plt.show()
# READ: Liquidity now DIPS below 50% in QT windows (2018, 2022) instead of pinning at 100%; CAPE shows
#       cyclical position not a monotone ramp. Credit/VIX spike to ~100% into the red bear bands.
```

**Saved figure:** `data/model_output_eda/regime_weight/pillars_vs_curve_rolling.png`

![pillars rolling](../../../../data/model_output_eda/regime_weight/pillars_vs_curve_rolling.png)

---

### Cell 16 (markdown) — Read (Part 3)

```markdown
### Read — the raw returns, the regime picture, and the pillar-transform fix

- **The cumulative curve was summing per-day top-5 mean fwd20 (C3).** Each point is one deploy-date's
  basket outcome. The red mean-line is +ve in bull/rebound panels (drift) and near/below 0 with fat
  downside scatter in GFC/bear — the cumulative slope is just the running total of these.
- **Whole-period (C4): the regime change is visible.** The bear bands (2001-02, 2008, 2020, 2022) sit
  exactly on the flat/declining stretches of the cumulative curve; between them it climbs. Confirms at
  25-yr scale that the edge is a bull-regime property and the drawdowns are regime-timed, not random —
  the case for the point-8 governor.
- **Pillar data facts (user Qs), both REAL:** (i) CAPE genuinely starts 2012-12 (`CAPE_OURS`,
  self-computed; earlier is absent, cf [[project_cape_ours_pillar]]). (ii) Liquidity pinned >50% was a
  TRANSFORM bug, not data — Net Liquidity trends up (+0.96 with time), and an EXPANDING percentile of a
  trending series saturates at ~100%. Fixed with a rolling 2yr percentile (C5): Liq now dips in QT
  (2018/2022), CAPE shows cyclical position. Lesson for any future pillar viz: use a rolling window for
  trending pillars, expanding is only safe for mean-reverting ones.
- **⚠️ Rolling percentile is still a VISUALIZATION**, not a fitted feature; the consolidated live-safe
  signal remains `stress_ew_vix` ([[project_entry_timing_macro_axis]]). Same directional/no-exit caveats.
```

---
---

## Part 4 — return by horizon + can macro QUANTIFY high/low-return periods? (user, 2026-07-08)

> **User asks:** (1) redo C4 without the cumulative panel (it has no realistic meaning — overlapping
> baskets, no capital constraint), across fwd20/50/100. (2) Can we QUANTIFY which deploy periods have
> high vs low return using the 6 pillars — individually, a consolidated score, VIX, or SPY?
>
> The panel `entry_timing_daily.parquet` IS the top-5 basket (corr 1.0 with the multiyear top-5) and
> already carries fwd20/50/100 + all 6 pillars + VIX + SPY-trend, so no new data — one 2003-2025 table.
>
> **Answer to (2): YES — three signals separate high-return periods, all the SAME axis (stress/VIX).**
> fwd100 tercile spread (top-tercile minus bottom-tercile mean return):
> - **VIX (raw or 2yr-pct) +11.0–11.5%**, **stress composite +10.5%**, **Credit 2yr-pct +9.6%** — all
>   say high-stress/wide-credit periods precede HIGHER top-5 fwd100 (buy-the-stress / rebound).
> - **Rates −8.9%, CAPE −8.3% INVERT** (expensive/high-rates → lower). **SPY>200d −5.1%** (rebound lives
>   sub-200d). SPY-momentum ≈ 0.
> - ρ stays weak everywhere (|ρ|≤0.09) — these are TILTS not gates, and the separation is a level/timing
>   fact, not within-basket selection.
>
> **The catch (must be shown):** the winning high-stress tercile has the **best mean (+18.5%) AND the
> worst tail (−43.3% worst-decile)** — high-mean, high-variance (falling knife). That's exactly why the
> point-8 governor gates stress WITHIN SPY>200d rather than chasing raw stress.

---

### Cell 17 — Part 4 setup: rolling-percentile signals on the top-5 panel

```python
from scipy.stats import spearmanr
PIL = ["pil_vix","pil_credit","pil_term","pil_rates","pil_liq","pil_cape"]
e = et.sort_values("date").reset_index(drop=True).copy()
for c in PIL:                                              # rolling 2yr pct (live-safe; handles trending liq/cape)
    e[c+"_rp"] = e[c].rolling(504, min_periods=126).apply(lambda x:(x.iloc[-1]>=x).mean(), raw=False)

SIGS = {"pil_vix_rp":"VIX 2yr-pct","pil_credit_rp":"Credit 2yr-pct","pil_term_rp":"Term 2yr-pct",
        "pil_rates_rp":"Rates 2yr-pct","pil_liq_rp":"Liquidity 2yr-pct","pil_cape_rp":"CAPE 2yr-pct",
        "stress_ew_vix":"stress composite","vix_close":"VIX raw level","spy_above200":"SPY>200d",
        "spy_ret60":"SPY 60d mom"}
print("signals ready:", len(SIGS))
```

---

### Cell 18 — C6: daily top-5 return by horizon (regime-shaded, no cumulative)

```python
from matplotlib.dates import YearLocator
dd = pd.read_parquet(ROOT/"data/model_output_eda/regime_state/regime_state_daily_dd.parquet")[["date","state"]]
def shade(ax, reg):
    r = reg.sort_values("date").reset_index(drop=True); r["blk"]=(r.state!=r.state.shift()).cumsum()
    for _,g in r.groupby("blk"):
        col={"bear":"#e57373","bull-stress":"#ffcc80"}.get(g.state.iloc[0])
        if col: ax.axvspan(g.date.iloc[0], g.date.iloc[-1], color=col, alpha=.25, lw=0)

fig, ax = plt.subplots(3, 1, figsize=(16, 11), sharex=True)
for a, h in zip(ax, ["fwd20","fwd50","fwd100"]):
    shade(a, dd); y = e.set_index("date")[h]*100
    a.scatter(y.index, y.values, s=4, alpha=.2, color="#1565c0")
    a.plot(y.rolling(63,min_periods=10).mean().index, y.rolling(63,min_periods=10).mean().values,
           color="#0d47a1", lw=1.5, label=f"{h} 63d-avg")
    a.axhline(0,color="k",lw=.7); a.axhline(y.mean(),color="#c62828",ls="--",lw=1,label=f"mean {y.mean():+.1f}%")
    a.set_ylabel(f"top-5 {h} (%)"); a.legend(loc="upper left", fontsize=9)
ax[0].set_title("C6 - daily top-5 basket return by horizon (shade: red=bear, orange=bull-stress)", weight="bold")
ax[-1].set_xlabel("date"); ax[-1].xaxis.set_major_locator(YearLocator(2)); ax[-1].tick_params(axis="x", labelrotation=45)
plt.tight_layout(); plt.show()
# READ: mean return grows with horizon (+2.6% -> +5.9% -> +12.1%); the 2020 rebound spike dominates fwd100.
```

**Saved figure:** `data/model_output_eda/regime_weight/return_by_horizon.png`

![return by horizon](../../../../data/model_output_eda/regime_weight/return_by_horizon.png)

---

### Cell 19 — C7: quantify — which signal separates high/low-return periods

```python
rows = []
for s, lbl in SIGS.items():
    row = {"signal": lbl}
    for h in ("fwd20","fwd50","fwd100"):
        d = e[[s,h]].dropna(); row[f"rho_{h}"] = spearmanr(d[s], d[h]).correlation
    d = e[[s,"fwd100"]].dropna().copy()
    if d[s].nunique() <= 2:
        g = d.groupby(s)["fwd100"].mean()*100; row["spread_T3_T1"] = g.iloc[-1]-g.iloc[0]
    else:
        d["t"] = pd.qcut(d[s], 3, labels=[0,1,2], duplicates="drop")
        g = d.groupby("t", observed=True)["fwd100"].mean()*100; row["spread_T3_T1"] = g.iloc[-1]-g.iloc[0]
    rows.append(row)
q = pd.DataFrame(rows).sort_values("spread_T3_T1", ascending=False)
pd.set_option("display.float_format", lambda x: f"{x:+.3f}")
print(q.to_string(index=False))
# READ: VIX/stress/credit separate high-return periods (+9..+11.5% fwd100 spread); rates/CAPE invert;
#       SPY>200d is NEGATIVE (rebound lives sub-200d). rho weak everywhere -> a TILT, not a gate.
```

---

### Cell 20 — C7 figure: spread ranking + the tail catch

```python
fig, ax = plt.subplots(1, 2, figsize=(15, 6))
qs = q.sort_values("spread_T3_T1")
cols = ["#c62828" if v<0 else "#2e7d32" for v in qs["spread_T3_T1"]]
ax[0].barh(qs["signal"], qs["spread_T3_T1"], color=cols); ax[0].axvline(0, color="k", lw=.8)
for i,v in enumerate(qs["spread_T3_T1"]):
    ax[0].text(v+(0.3 if v>=0 else -0.3), i, f"{v:+.1f}", va="center", ha="left" if v>=0 else "right", fontsize=9)
ax[0].set_xlabel("fwd100 spread: top-tercile − bottom-tercile (%)")
ax[0].set_title("which signal separates high/low return periods?", weight="bold")

d = e[["stress_ew_vix","fwd100"]].dropna().copy(); d["t"] = pd.qcut(d["stress_ew_vix"], 3, labels=["low","mid","high"])
gm = d.groupby("t", observed=True)["fwd100"].mean()*100
gw = d.groupby("t", observed=True)["fwd100"].apply(lambda x:x.nsmallest(max(1,len(x)//10)).mean())*100
x = np.arange(3)
ax[1].bar(x-.2, gm.values, .4, label="mean", color="#2e7d32"); ax[1].bar(x+.2, gw.values, .4, label="worst-decile", color="#c62828")
ax[1].set_xticks(x); ax[1].set_xticklabels(gm.index); ax[1].axhline(0, color="k", lw=.8); ax[1].legend()
ax[1].set_title("stress composite tercile: high mean BUT worst tail (the catch)", weight="bold")
ax[1].set_ylabel("fwd100 (%)"); ax[1].set_xlabel("stress tercile")
plt.tight_layout(); plt.show()
```

**Saved figure:** `data/model_output_eda/regime_weight/return_vs_macro.png`

![return vs macro](../../../../data/model_output_eda/regime_weight/return_vs_macro.png)

---

### Cell 21 (markdown) — Read (Part 4)

```markdown
### Read — high/low-return periods ARE quantifiable by macro, on ONE axis, with a tail cost

- **Yes, macro separates high- from low-return deploy periods — but it's all ONE axis (stress/VIX).**
  fwd100 top−bottom-tercile spread: VIX +11.5%, VIX-raw +11.0%, stress composite +10.5%, credit +9.6%.
  Rates (−8.9%) and CAPE (−8.3%) are the same axis with the sign flipped (expensive/tight → worse).
  The consolidated `stress_ew_vix` is NOT better than raw VIX here — VIX alone carries most of it
  ([[project_entry_timing_macro_axis]]: VIX ≈ the realized-vol / bear axis, corr +0.87 with spy_vol20).
- **SPY-trend does NOT separate return LEVEL** (SPY>200d spread −5.1%, momentum ~0) — because the high
  returns are the rebounds that happen BELOW 200d. SPY-trend is a DOWNSIDE/tail gate (point-8 finding a),
  not a return-level ranker. Two different jobs: stress/VIX ranks the MEAN, SPY-trend contains the TAIL.
- **The catch: the high-return tercile is also the worst-tail tercile.** High-stress: mean +18.5% but
  worst-decile −43.3% (vs low-stress mean +8.1% / worst-decile −32.3%). High mean, high variance — the
  falling knife. So "deploy more when stress is high" only survives WITH the SPY>200d gate on top (which
  removes the sub-200d knife) — the exact point-8 governor (b). Chasing raw stress ungated buys the tail.
- **All |ρ|≤0.09 → these are TILTS not gates**, and they rank the deploy-DATE return level, separate
  from m01's within-basket name selection. ⚠️ directional close-to-close top-5 mean returns, no
  exits/sizing; rolling percentiles are live-safe but the tercile CUTS are full-sample (EDA framing) —
  an expanding cut would be needed to size live capital.
```

---
---

## Part 5 — INSIDE the high-stress tercile + 150d/200d (user, 2026-07-08)

> **User asks:** (1) dig further conditional on the high-stress tercile — what separates the good
> deploys from the knife? (2) conclusion + what it means for the strategy. (3) add fwd150/fwd200.
>
> **New data:** enriched the multiyear parquets with fwd150/fwd200 (same shift(-H) recipe, smoke-tested
> on 2022, 99.6%/98.7% coverage) and rebuilt a top-5 basket panel at all 5 horizons +macro:
> `scripts/build_top5_horizons.py` → `data/model_output_eda/regime_weight/top5_horizons.parquet`.
>
> **THE finding — inside the high-stress tercile (n=1800), SPY>200d cleanly splits the knife from the
> ride.** Bull-stress (SPY>200, n=1091) vs bear-stress (SPY≤200, n=709):
>
> | | fwd20 | fwd50 | fwd100 | fwd150 | fwd200 |
> |---|--:|--:|--:|--:|--:|
> | mean — bull-stress | +3.7 | +11.2 | +18.9 | +32.2 | +35.7 |
> | mean — bear-stress | +1.2 | +6.3 | +18.0 | +27.7 | +43.6 |
> | worst-dec — bull-stress | −16.1 | −21.0 | **−23.6** | −25.4 | −31.3 |
> | worst-dec — bear-stress | −29.5 | −40.0 | **−56.3** | −61.2 | −65.1 |
> | reward/tail — bull-stress | 0.23 | 0.53 | **0.80** | **1.27** | 1.14 |
> | reward/tail — bear-stress | 0.04 | 0.16 | **0.32** | 0.45 | 0.67 |
>
> Nearly-equal MEAN, but bear-stress worst-decile is ~2.5× deeper at every horizon → the SPY>200d gate
> keeps the return and cuts the tail in half. Bear-stress's higher fwd200 mean is a handful of
> deep-crash clusters (248 of its days are 2008, 101 are 2009) — betting on catching the exact bottom.

---

### Cell 22 — build/load the top-5 panel at 5 horizons (150d/200d enriched)

```python
# One-time: run scripts/build_top5_horizons.py to enrich fwd150/200 + build the panel.
panel = pd.read_parquet(ROOT/"data/model_output_eda/regime_weight/top5_horizons.parquet")
H = ["fwd20","fwd50","fwd100","fwd150","fwd200"]; HN = [20,50,100,150,200]
panel["stress_t"] = pd.qcut(panel["stress_ew_vix"], 3, labels=["lo","mid","hi"])
def worst_decile(s): return s.nsmallest(max(1, len(s)//10)).mean()
print("coverage:", {h: f"{panel[h].notna().mean():.0%}" for h in H})
print("\nmean by stress tercile x horizon (%):")
print((panel.groupby("stress_t", observed=True)[H].mean()*100).round(1).to_string())
# READ: the stress gradient widens with horizon — hi-stress fwd200 +38.8% vs lo +21.1%.
```

---

### Cell 23 — inside high-stress: bull-stress vs bear-stress across horizons

```python
hi = panel[panel["stress_t"]=="hi"]; bull = hi[hi.spy_above200==1]; bear = hi[hi.spy_above200==0]
rows = []
for name, sub in [("bull-stress (SPY>200)", bull), ("bear-stress (SPY<=200)", bear)]:
    for h in H:
        rows.append(dict(cohort=name, horizon=h, n=len(sub), mean=sub[h].mean()*100,
                         worst_dec=worst_decile(sub[h])*100, neg_pct=100*(sub[h]<0).mean(),
                         reward_tail=sub[h].mean()/abs(worst_decile(sub[h]))))
cond = pd.DataFrame(rows)
print("MEAN:\n", cond.pivot(index="cohort", columns="horizon", values="mean").round(1).to_string())
print("\nWORST-DECILE:\n", cond.pivot(index="cohort", columns="horizon", values="worst_dec").round(1).to_string())
print("\nREWARD/TAIL:\n", cond.pivot(index="cohort", columns="horizon", values="reward_tail").round(2).to_string())
# READ: mean ~equal; bear-stress tail ~2.5x deeper; reward/tail bull >> bear at every horizon.
```

---

### Cell 24 — figure: the gate keeps the mean, cuts the tail

```python
fig, ax = plt.subplots(1, 3, figsize=(17, 5.5)); x = np.array(HN)
def series(sub, fn): return [fn(sub[h]) for h in H]
ax[0].plot(x, series(bull, lambda s:s.mean()*100), "o-", color="#2e7d32", lw=2, label="bull-stress (SPY>200)")
ax[0].plot(x, series(bear, lambda s:s.mean()*100), "o-", color="#c62828", lw=2, label="bear-stress (SPY<=200)")
ax[0].axhline(0,color="k",lw=.7); ax[0].set_title("MEAN — nearly identical", weight="bold")
ax[0].set_xlabel("horizon (days)"); ax[0].set_ylabel("mean top-5 return (%)"); ax[0].legend()
ax[1].plot(x, series(bull, lambda s:worst_decile(s)*100), "o-", color="#2e7d32", lw=2, label="bull-stress")
ax[1].plot(x, series(bear, lambda s:worst_decile(s)*100), "o-", color="#c62828", lw=2, label="bear-stress")
ax[1].axhline(0,color="k",lw=.7); ax[1].set_title("WORST-DECILE — bear-stress ~2.5x deeper (knife)", weight="bold")
ax[1].set_xlabel("horizon (days)"); ax[1].set_ylabel("worst-decile (%)"); ax[1].legend()
ax[2].plot(x, series(bull, lambda s:s.mean()/abs(worst_decile(s))), "o-", color="#2e7d32", lw=2, label="bull-stress")
ax[2].plot(x, series(bear, lambda s:s.mean()/abs(worst_decile(s))), "o-", color="#c62828", lw=2, label="bear-stress")
ax[2].axhline(0,color="k",lw=.7); ax[2].set_title("REWARD / TAIL (mean ÷ |worst-decile|)", weight="bold")
ax[2].set_xlabel("horizon (days)"); ax[2].set_ylabel("ratio"); ax[2].legend()
fig.suptitle(f"High-stress tercile split by SPY>200d — gate keeps mean, cuts tail (n bull={len(bull)}, bear={len(bear)})", weight="bold")
plt.tight_layout(); plt.show()
```

**Saved figure:** `data/model_output_eda/regime_weight/high_stress_conditional.png`

![high-stress conditional](../../../../data/model_output_eda/regime_weight/high_stress_conditional.png)

---

### Cell 25 (markdown) — CONCLUSION: what this means for the strategy

```markdown
### Conclusion — the governor is a GATE (SPY>200d) × a TILT (stress), and the two do separate jobs

**The finding, stated once:** high stress marks the high-return periods (Part 4). But raw high-stress
is bimodal — inside the top stress tercile, *whether SPY is above its 200d MA* cleanly splits the
outcome. Bull-stress and bear-stress earn ~the SAME mean at every horizon (fwd100 +18.9% vs +18.0%),
but the bear-stress worst-decile is ~2.5× deeper (−56% vs −24% at fwd100, worsening to −65% vs −31%
at fwd200). Bear-stress's slightly higher fwd200 mean is a mirage of a few deep-crash clusters (2008/09)
where you'd have had to catch the exact bottom. On reward/|tail|, bull-stress dominates at every
horizon (fwd150 1.27 vs 0.45).

**What it means for the strategy — three concrete rules:**
1. **The governor is TWO signals doing TWO jobs, not one.** `stress/VIX` ranks the MEAN (deploy MORE
   when stress is high — the return is there); `SPY>200d` is the TAIL GATE (it removes the falling
   knife without sacrificing the mean). Stacking a second vol/VIX sizing factor on top double-counts
   ([[project_entry_timing_macro_axis]]: VIX ≈ the bear axis) — use ONE of each job.
2. **This confirms point-8 (b) and resolves its ambiguity.** Point-8 (b) — deploy weight ∝ stress,
   gated by SPY>200d — improved BOTH mean and tail; Part 5 shows exactly WHY: the gate is removing the
   bear-stress knife, which is a distinct, identifiable sub-population, not a blur. The gate is
   cheap (near-zero mean cost) and load-bearing (halves the tail).
3. **Hold long, and only above the 200d line.** The stress edge and the tail-healing both strengthen
   with horizon: bull-stress reward/tail climbs 0.23→1.27 (fwd20→fwd150). SEPA is a long-hold strategy;
   entering into stress WHILE SPY>200d and holding to ~100-150d is where the risk-adjusted edge lives.
   Entering into stress BELOW the 200d line is the one thing to avoid — same expected return, but you
   wear a −56%..−65% tail.

**Net:** the regime-blind m01 score does not need to become regime-aware; it needs a two-part external
governor — **size up on stress, but gate on SPY>200d** — and the gate is worth the most at the longest
holds. This is the falsifiable spec to carry into the backtest (through the M2 start-date cone).

**⚠️ caveats:** directional close-to-close top-5 means, no exits/sizing/costs; worst-decile is a
day-level lower tail, not a realized drawdown; stress tercile + SPY gate are full-sample cuts (EDA) —
an expanding-window version is required before sizing live capital; bear-stress n=709 is crash-clustered
(2008/09 heavy) so its tail is a few-episode estimate, not 700 independent draws.
```
