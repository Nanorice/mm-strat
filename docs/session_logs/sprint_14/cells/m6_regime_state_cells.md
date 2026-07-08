# M6 — regime-state classification + M4 during-period edge (cells)

> **What this file explains (your three questions):**
> 1. **How is bull/bear classified?** One metric: **SPY close vs its own 200-day moving average.**
>    Above → bull, at-or-below → bear. That's the whole trunk. It's live-safe (the MA uses only past
>    closes) and matches every known regime (dot-com, GFC, 2015-16, 2018-Q4, COVID, 2022).
> 2. **What's the threshold metric?** Two, one per axis of the split:
>    - **bull/bear:** `SPY / MA200 − 1` crosses **0**.
>    - **calm/stress (inside bull):** `SPY drawdown-from-peak` crosses **10%** (the `dd` axis, default,
>      stationary, full 25y). An alternative `macro` axis uses a macro-stress tercile but it LEAKS by
>      time — kept only for comparison.
> 3. **What's calm vs stress inside a regime?** Bear is bear (no sub-split). A **bull** day is
>    **bull-stress** if SPY is ≥10% below its peak while still above the 200d line (an early-selloff /
>    recovery condition), else **bull-calm**.
>
> **Load-bearing result:** M4's tail-ranking edge (`cond_lift10`) is **weakest in calm bull, strongest
> under stress** — counter-cyclical, not pro-cyclical — and it holds on BOTH stress axes. The M4
> smoke's "dies in the GFC" was a circular artifact.
>
> **⚠️ Honest label caveats:** the bear/bull trunk is good; the calm/stress sub-split is NOT settled —
> `dd` stress is rare (752 M4 rows), `macro` stress leaks by time, and both flicker day-to-day. See
> Cells 3 & 6.
>
> Scripts: `regime_state.py` (label, `--axis dd|macro`), `regime_state_chart.py` (figures),
> `m4_by_regime_state.py` (the M4 stratification). Artifacts under
> `data/model_output_eda/regime_state/`.

Paste each block as one cell.

---

### Cell 1 — load the label + define the classification (the metrics + thresholds)

```python
import numpy as np, pandas as pd, duckdb
from pathlib import Path

def _root():
    p = Path.cwd().resolve()
    for d in (p, *p.parents):
        if (d/"config.py").exists() and (d/"src").is_dir(): return d
    raise RuntimeError("root not found")
ROOT = _root()
EDA = ROOT/"data"/"model_output_eda"/"regime_state"
DB  = ROOT/"data"/"market_data.duckdb"

# the two labels (bear/bull trunk is identical; they differ ONLY in the calm/stress sub-split)
dd    = pd.read_parquet(EDA/"regime_state_daily_dd.parquet")      # DEFAULT: drawdown 10%, full 25y
macro = pd.read_parquet(EDA/"regime_state_daily_macro.parquet")   # macro-stress tercile, 2013+ only
for df in (dd, macro): df["date"] = pd.to_datetime(df["date"])

# THE CLASSIFICATION, spelled out (dd axis) — this is exactly what regime_state.py computes:
#   bull/bear   : spy_above200 == 1  <=>  SPY close > 200d MA
#   calm/stress : spy_dd >= 0.10      <=>  SPY >=10% below its running peak
# verify the rule reproduces the stored labels (self-check, not decoration):
recomputed = np.where(dd.spy_above200 == 0, "bear",
              np.where(dd.spy_dd >= 0.10, "bull-stress", "bull-calm"))
assert (recomputed == dd.state).all(), "the stated rule must reproduce the label"
print("dd   :", dd.date.min().date(), "->", dd.date.max().date(), len(dd), "days  (rule verified)")
print("macro:", macro.date.min().date(), "->", macro.date.max().date(), len(macro), "days")
```

---

### Cell 2 — state distribution + what each state MEANS

```python
def dist(df, name):
    v = df.state.value_counts(normalize=True)
    return pd.Series({s: v.get(s, 0.0) for s in ["bear","bull-stress","bull-calm"]}, name=name)
print(pd.concat([dist(dd,"dd"), dist(macro,"macro")], axis=1).round(3).to_string())
print("""
  bear        SPY below its 200d MA           -> a downtrend, regardless of stress
  bull-stress SPY above 200d BUT >=10% off peak -> early-selloff / mid-recovery (rare)
  bull-calm   SPY above 200d, within 10% of peak -> the ordinary uptrend
""")
# dd: 0.285 / 0.178 / 0.536.  macro: 0.149 / 0.206 / 0.645 (2013+ only).
```

---

### Cell 3 — LABEL QUALITY: bear runs match regimes (good); stress split is leaky/sparse (honest)

```python
# (a) bear runs >=20d line up with known drawdowns -> the TRUNK is trustworthy
s = dd.sort_values("date").reset_index(drop=True)
s["grp"] = (s.state != s.state.shift()).cumsum()
runs = s.groupby("grp").agg(state=("state","first"), start=("date","min"),
                            end=("date","max"), n=("date","size")).reset_index(drop=True)
print("bear runs >= 20d (should read as: dot-com, GFC, 2011, 2015-16, 2018Q4, COVID, 2022, 2025):")
print(runs[(runs.state=="bear") & (runs.n>=20)][["start","end","n"]].to_string(index=False))

# (b) is the STRESS split stationary? share of bull-stress by year, both axes
def stress_share(df):
    d = df.assign(yr=df.date.dt.year)
    g = d.groupby("yr").agg(n=("state","size"), bs=("state", lambda x:(x=="bull-stress").sum()))
    return (g.bs/g.n).round(2)
sh = pd.concat([stress_share(dd).rename("dd"), stress_share(macro).rename("macro")], axis=1)
print("\nbull-stress share by year (macro front-loaded 2013->0 = LEAK; dd clusters in recoveries = SPARSE):")
print(sh.fillna(0).to_string())

# (c) flicker: median run length of the stress state (a real 'state' shouldn't flip daily)
for name, df in [("dd", dd), ("macro", macro)]:
    x = df.sort_values("date").reset_index(drop=True); x["g"]=(x.state!=x.state.shift()).cumsum()
    r = x.groupby("g").agg(state=("state","first"), n=("date","size"))
    print(f"{name:5} total runs {len(r):4d} | median bull-stress run {int(r[r.state=='bull-stress'].n.median())}d")
# READ: trunk good; stress sub-split NOT settled (leak/sparsity/flicker) -> needs a persistence filter
#       + a vol-percentile stress cut (spy_vol20 is already in the parquet). See Cell 6.
```

---

### Cell 4 — the M4 during-period edge, by state, cross-validated on both axes

```python
m_dd  = pd.read_csv(EDA/"m4_by_state_dd.csv").set_index("state")
m_mac = pd.read_csv(EDA/"m4_by_state_macro.csv").set_index("state")
order = ["bull-calm","bull-stress","bear","ALL"]
cmp = pd.DataFrame({
    "dd_cond_lift10":    m_dd.cond_lift10.reindex(order).round(2),
    "dd_n":              m_dd.n.reindex(order).astype(int),
    "macro_cond_lift10": m_mac.cond_lift10.reindex(order).round(2),
    "macro_n":           m_mac.n.reindex(order).astype(int),
})
print(cmp.to_string())
print("\nhr_rate (home-run base rate) by state — flat ~0.126 => it's RANKING power, not more tails:")
print(m_dd.hr_rate.reindex(["bull-calm","bull-stress","bear"]).round(3).to_string())
# cond_lift10 = does M4's score rank the big winners WITHIN its own top-decile.
# Both axes: bull-calm < bear < bull-stress. Weakest in calm bull, strongest under stress.
# dd bull-stress (4.29) is 752 rows = high-variance; macro (2.44, n=5036) is the trustworthy magnitude.
```

---

### Cell 5 — the figures, rendered INLINE (plot code is in the cell; run it → charts appear below)

```python
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
%matplotlib inline

COL = {"bear":"#c62828", "bull-stress":"#ef6c00", "bull-calm":"#2e7d32"}
# SPY close + 200d MA (recompute here so the cell is self-contained)
con = duckdb.connect(str(DB), read_only=True)
spy = con.execute("SELECT date, spy_close FROM t1_macro WHERE spy_close IS NOT NULL ORDER BY date").df()
con.close()
spy["date"] = pd.to_datetime(spy["date"]); spy["ma200"] = spy.spy_close.rolling(200).mean()
g = dd.merge(spy, on="date", how="left").sort_values("date").reset_index(drop=True)

def shade(ax, d):
    d = d.reset_index(drop=True); grp = (d.state != d.state.shift()).cumsum()
    for _, r in d.groupby(grp):
        ax.axvspan(r.date.iloc[0], r.date.iloc[-1], color=COL[r.state.iloc[0]], alpha=0.18, lw=0)

fig, ax = plt.subplots(3, 1, figsize=(15, 12))
# panel 1: SPY vs 200d MA, shaded by state -> WHERE each state fires (bull/bear = the blue line)
shade(ax[0], g)
ax[0].plot(g.date, g.spy_close, color="#1a1a1a", lw=1.0, label="SPY close")
ax[0].plot(g.date, g.ma200, color="#1565c0", lw=1.4, ls="--", label="200d MA (bull/bear line)")
ax[0].set_yscale("log"); ax[0].set_ylabel("SPY (log)")
ax[0].set_title("1 · SPY vs 200d MA, shaded by state — bear = below the blue line", weight="bold")
ax[0].legend(handles=[*ax[0].get_legend_handles_labels()[0],
                      *[Patch(color=c, alpha=.35, label=s) for s,c in COL.items()]], fontsize=8, loc="upper left")
# panel 2: the THRESHOLD metrics — drawdown% (10% stress cut) + %-dist-to-200d (0 = bull/bear)
ax[1].fill_between(g.date, g.spy_dd*100, color="#ef6c00", alpha=0.4)
ax[1].axhline(10, color="#c62828", ls="--", lw=1.5, label="stress cut = 10% drawdown")
ax[1].invert_yaxis(); ax[1].set_ylabel("SPY drawdown %")
ax[1].set_title("2 · the threshold metrics (drawdown → calm/stress)", weight="bold"); ax[1].legend(fontsize=8)
# panel 3: state ribbon -> the regime sequence + flicker
shade(ax[2], g); ax[2].set_yticks([]); ax[2].set_ylim(0,1); ax[2].set_xlim(g.date.min(), g.date.max())
ax[2].set_title("3 · state timeline ribbon (read the sequence + the flicker)", weight="bold")
ax[2].legend(handles=[Patch(color=c, alpha=.35, label=s) for s,c in COL.items()], ncol=3, fontsize=8, loc="upper center")
fig.tight_layout(); plt.show()
```

```python
# panel 4: M4 edge by state — cond_lift10, dd vs macro (the counter-cyclical result)
m_dd  = pd.read_csv(EDA/"m4_by_state_dd.csv").set_index("state")
m_mac = pd.read_csv(EDA/"m4_by_state_macro.csv").set_index("state")
order = ["bull-calm","bull-stress","bear"]; x = np.arange(3); w = 0.38
fig, ax = plt.subplots(figsize=(9, 5.5))
b1 = ax.bar(x-w/2, [m_dd.cond_lift10[s] for s in order], w, color="#1565c0", label="dd axis")
b2 = ax.bar(x+w/2, [m_mac.cond_lift10[s] for s in order], w, color="#ef6c00", label="macro axis")
for bars, src in ((b1,m_dd),(b2,m_mac)):
    for r,s in zip(bars, order):
        ax.text(r.get_x()+r.get_width()/2, r.get_height()+0.05, f"{r.get_height():.2f}\nn={int(src.n[s])}", ha="center", fontsize=8)
ax.axhline(1.0, color="k", ls=":", alpha=.5, label="no skill (1×)")
ax.set_xticks(x); ax.set_xticklabels(order); ax.set_ylabel("cond_lift10 (tail-rank within top-decile)")
ax.set_title("4 · M4 edge by state — weakest calm, strongest stress (holds on BOTH axes)", weight="bold")
ax.legend(fontsize=9); fig.tight_layout(); plt.show()
assert m_dd.cond_lift10["bull-stress"] > m_dd.cond_lift10["bull-calm"], "counter-cyclical must hold on dd"
```

> The batch script `regime_state_chart.py --axis dd|macro` writes the same four as PNGs under
> `data/model_output_eda/regime_state/` if you want them as files (e.g. for the verdict doc).

**Static preview** (the PNGs from `regime_state_chart.py`, so this .md is readable without running):

![price+MA](../../../../data/model_output_eda/regime_state/fig1_price_ma_dd.png)
![thresholds](../../../../data/model_output_eda/regime_state/fig2_thresholds_dd.png)
![ribbon](../../../../data/model_output_eda/regime_state/fig3_ribbon_dd.png)
![m4 edge](../../../../data/model_output_eda/regime_state/fig4_m4_edge.png)

---

### Cell 6 (markdown) — Read

```markdown
### Read
- **Classification (the answer to "how do we call bull/bear/calm/stress"):**
  - **bull vs bear** = SPY close above/below its **200-day MA** (metric `SPY/MA200−1`, threshold 0).
    This trunk is GOOD — its ≥20d bear runs are exactly the known drawdowns (see figure 1: red sits
    below the blue line at 2000-03, 2008, 2022).
  - **calm vs stress** (only *inside* bull) = SPY **drawdown-from-peak ≥ 10%** (dd axis, default).
    "Stress" here means SPY is above its 200d line yet still ≥10% off its high — an early-selloff or
    mid-recovery condition (figure 1: orange in 2003-05 and 2009-11).
- **The result:** M4's tail-ranking edge (`cond_lift10`) is **weakest in calm bull (1.62/1.87),
  strongest under stress (2.44/4.29), bear in between (2.37)** — counter-cyclical, and it holds on
  BOTH independently-built stress axes. Home-run base rate is flat (~12.6%) across states, so this is
  genuine ranking power (best when dispersion is high), not a base-rate artifact. The M4 smoke's
  "dies in the GFC" was a **circular** split (it hand-picked the weakest fold).
- **⚠️ The label is only HALF-settled — be honest about this:**
  - Bear/bull trunk: trustworthy.
  - Calm/stress sub-split: NOT. The `dd` stress state is rare (752 of 25,898 M4 rows → high-variance);
    the `macro` stress state leaks by time (2013 = 88% stressed → 2017/2025 = 0%, an expanding-z
    drift); both flicker (median stress-run 1–4 days).
- **⚠️ Scope:** M4's OOS folds stop at 2013, so this doesn't touch M1's 2001/2008 full-universe
  pro-cyclicality (a deeper-crash era). The `dd` axis reaches 2008 — running it on a pre-2013
  population (SEPA candidates) is the real "does it survive a true crash" test.
- **To make the stress state SETTLED (next steps, your call):** (1) a **persistence filter**
  (min-run smoothing) to kill the daily flicker; (2) a **vol-percentile** stress cut — `spy_vol20` is
  already in the parquet, is stationary, and fires in choppy-but-calm markets (fixes the dd sparsity);
  (3) run the `dd` axis on the SEPA-candidate population (model-agnostic during-period lens, reaches 2008).
```
