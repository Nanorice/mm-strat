# Step 4 — Absorption Ratio: the pre-crisis lead test — intended cells (2026-06-24)

> The one untested lead candidate (lit review §4.6, Kritzman 2012). Steps 1–3 shipped
> **VIX (sizing) + est_prob gate (crisis)** but that gate only fires DURING a crisis — it can't warn
> BEFORE one forms. AR claims to (precedes drawdowns by 20–60d) via cross-asset *coupling*, a
> different mechanism than levels. This step tests whether AR earns a place as a pre-crisis overlay.
> Findings doc: `docs/research/regime_model/2026-06-24_step1_eda_findings.md`.
>
> **The bar AR must clear is HIGH and pre-committed:** VIX/credit all FAILED the lead test (S3b/c
> flat, S3d-incr crisis-only). AR only earns inclusion if it does what they could NOT — show a
> genuine rise-from-calm BEFORE equity tails, robust to the same de-overlap/calm-start controls.
> Anything less and it's just another coincident meter, and we don't add it.
>
> **AR universe (verified clean, 2007-04→today, 4829d, no bad ticks, full GFC/Covid/2022):**
> 20 assets — 5 equity regions/styles, 9 sectors (NO XLRE: starts 2015 & would clamp window),
> 3 bonds (TLT/LQD/HYG), gold/oil/dollar (GLD/USO/UUP).

---

## AR0 — Build the cross-asset return panel

```python
# %% AR0 — load the 20-asset universe, daily returns, common 2007+ window.
import numpy as np, pandas as pd, duckdb
from pathlib import Path
import matplotlib.pyplot as plt
ROOT = Path.cwd()
while not (ROOT / "data" / "market_data.duckdb").exists() and ROOT != ROOT.parent:
    ROOT = ROOT.parent
con = duckdb.connect(str(ROOT / "data" / "market_data.duckdb"), read_only=True)

AR_UNIVERSE = ["SPY","QQQ","IWM","EFA","EEM",
               "XLE","XLF","XLK","XLV","XLI","XLY","XLP","XLU","XLB",
               "TLT","LQD","HYG","GLD","USO","UUP"]
q = "SELECT date, ticker, close FROM price_data WHERE ticker IN ({})".format(
    ",".join("'"+t+"'" for t in AR_UNIVERSE))
px = con.execute(q).df(); px["date"] = pd.to_datetime(px["date"])
spy = con.execute("SELECT date, close FROM price_data WHERE ticker='SPY' ORDER BY date").df()
spy["date"] = pd.to_datetime(spy["date"]); spy = spy.set_index("date")["close"]
con.close()

P = px.pivot(index="date", columns="ticker", values="close").sort_index()
R = P[AR_UNIVERSE].pct_change().dropna()                # common-window daily returns
print(f"return panel: {R.shape[1]} assets, n={len(R)}  {R.index.min().date()} -> {R.index.max().date()}")
```

---

## AR1 — Compute the Absorption Ratio (rolling cross-asset PCA)

```python
# %% AR1 — AR = fraction of variance in the top N PCs over a rolling window (Kritzman 2012).
#          High AR = tightly coupled (one factor drives all) = fragile. Low AR = diversified.
WIN   = 252          # 1yr covariance window (Kritzman uses ~500d; 252 = faster, more responsive)
N_PC  = 4            # top components ~ "1/5 of assets" rule (20 assets -> 4)

def absorption_ratio(R, win=WIN, n_pc=N_PC):
    out = pd.Series(index=R.index, dtype=float)
    V = R.values
    for i in range(win, len(R)):
        w = V[i-win:i]
        w = w - w.mean(0)
        cov = np.cov(w.T)
        ev = np.linalg.eigvalsh(cov)[::-1]              # descending eigenvalues
        out.iloc[i] = ev[:n_pc].sum() / ev.sum()
    return out.dropna()

AR = absorption_ratio(R).rename("AR")
print(f"AR: n={len(AR)}  {AR.index.min().date()} -> {AR.index.max().date()}")
print(f"AR range [{AR.min():.3f}, {AR.max():.3f}]  mean={AR.mean():.3f}")

# standardized DELTA-AR is the actual signal Kritzman uses (level is regime-dependent)
dAR = ((AR - AR.rolling(WIN).mean()) / AR.rolling(WIN).std()).rename("dAR_z").dropna()

fig, ax = plt.subplots(2, 1, figsize=(14, 7), sharex=True)
AR.plot(ax=ax[0], title=f"Absorption Ratio (top {N_PC} PCs / {R.shape[1]} assets, {WIN}d window)")
ax[0].axhline(AR.mean(), color="grey", lw=.5)
dAR.plot(ax=ax[1], title="standardized 15d ΔAR (the Kritzman risk signal)", color="firebrick")
ax[1].axhline(0, color="grey", lw=.5)
fig.tight_layout()
```

**Read:** eyeball whether AR *rises into* GFC-2008 / Covid-2020 / 2022 BEFORE SPY peaks. Kritzman's
claim is the +1σ ΔAR fires 20–60d before the drawdown. The plot is the first gut-check; AR3 tests it.

---

## AR2 — Does AR LEAD where VIX/credit didn't? (forward-return corr, the §A2/§S3d test)

```python
# %% AR2 — same forward-return test the level factors took. A LEADING fragility signal is NEGATIVE
#          (high AR now -> low return ahead) AND the effect should appear at LONGER lead than VIX.
m = spy.resample("MS").last()                            # monthly, like the GZ test
def fwd(h): return m.pct_change(h).shift(-h)
ARm = AR.resample("MS").last(); dARm = dAR.resample("MS").last()
T = pd.DataFrame({"AR": ARm, "dAR": dARm,
                  "f1": fwd(1), "f3": fwd(3), "f6": fwd(6)}).dropna()
print("corr(signal_t, FORWARD SPY return) — negative = leading risk signal:")
for c in ["AR", "dAR"]:
    print(f"  {c:4s}  f1={T[c].corr(T['f1']):+.3f}  f3={T[c].corr(T['f3']):+.3f}  f6={T[c].corr(T['f6']):+.3f}")
print("\nbenchmark to beat (Step-1/3): VIX fwd-ret corr was ~0 (contrarian-bullish);")
print("GZ est_prob was -0.20/-0.23 @ 3m/6m but CRISIS-ONLY. AR must show a lead that is NOT just crisis-only (AR3).")
```

## AR3 — The decisive test: rise-from-calm BEFORE equity tails (mirror of S3c)

```python
# %% AR3 — the test VIX/credit FAILED. Onset-only equity tails + calm-start control. Does AR climb
#          into the tail FROM A CALM BASE? This is the genuine-lead criterion; B_rise must be >0.
ret = spy.pct_change()
tail = ret <= ret.quantile(0.05)
tail_idx = np.where(tail.reindex(AR.index).fillna(False).values)[0]
onset = tail_idx[np.concatenate([[True], np.diff(tail_idx) > 21])]   # de-overlap (cluster onsets)
arz = ((AR - AR.mean()) / AR.std()).values

def mean_at(idx, off):
    p = idx + off; p = p[(p >= 0) & (p < len(arz))]
    return np.nanmean(arz[p])

print(f"onset tails: {len(onset)}")
print(f"AR z-trajectory into tail:  t-42={mean_at(onset,-42):+.2f}  t-21={mean_at(onset,-21):+.2f}  "
      f"t-10={mean_at(onset,-10):+.2f}  t0={mean_at(onset,0):+.2f}")
# calm-start: onset tails where AR was BELOW its mean 21d before
calm = np.array([o for o in onset if (o-21) >= 0 and arz[o-21] < 0])
if len(calm):
    b21, b0 = np.nanmean([arz[o-21] for o in calm]), np.nanmean([arz[o] for o in calm])
    print(f"CALM-start (n={len(calm)}): AR t-21={b21:+.2f} -> t0={b0:+.2f}  RISE_FROM_CALM={b0-b21:+.2f}")
print("\nVERDICT: RISE_FROM_CALM materially >0 AND visible at t-42/-21 = GENUINE pre-crisis lead")
print("(this is what VIX/credit could NOT do; if AR also flat-from-calm, it's coincident too -> reject)")

# trajectory plot vs the VIX trajectory from S3b, for direct comparison
fig, ax = plt.subplots(figsize=(10, 5))
offs = [-42,-21,-10,-5,-3,-1,0]
ax.plot(offs, [mean_at(onset,o) for o in offs], marker="o", label="AR (cross-asset coupling)")
ax.axvline(0, color="k", lw=.7); ax.axhline(0, color="grey", lw=.5)
ax.set_xlabel("trading days to equity tail"); ax.set_ylabel("mean z"); ax.legend()
ax.set_title("AR trajectory INTO equity tails — does coupling rise BEFORE the drop?")
```

**Deliverable — the AR verdict (pre-committed):**
- **RISE_FROM_CALM > 0 and AR elevated at t−42/−21:** AR genuinely leads via coupling — the ONE
  signal that warns before a crisis forms. → add it as a **pre-crisis fragility overlay** alongside
  the est_prob in-crisis gate. This fills the exact gap the shipped model has.
- **RISE_FROM_CALM ≈ 0 (flat from calm):** AR is coincident too — coupling spikes AT the crisis, not
  before. → reject; the shipped VIX+est_prob model stands, and "no factor leads on our data" is now
  tested against the literature's BEST lead candidate. Either outcome closes the question honestly.

## AR4 — Robustness (only if AR3 passes)

```python
# %% AR4 — if AR3 shows a lead, confirm it's not a single-crisis artifact or a parameter fluke.
#   (a) leave-one-crisis-out: does the lead survive dropping GFC? (the biggest coupling event)
#   (b) sensitivity to WIN (126/252/504) and N_PC (3/4/5).
for win in [126, 252, 504]:
    for npc in [3, 4, 5]:
        a = absorption_ratio(R, win=win, n_pc=npc)
        az = ((a - a.mean())/a.std()).values
        ti = np.where(tail.reindex(a.index).fillna(False).values)[0]
        on = ti[np.concatenate([[True], np.diff(ti) > 21])]
        cl = np.array([o for o in on if (o-21)>=0 and az[o-21]<0])
        rise = (np.nanmean([az[o] for o in cl]) - np.nanmean([az[o-21] for o in cl])) if len(cl) else np.nan
        print(f"  WIN={win} N_PC={npc}: rise_from_calm={rise:+.2f} (calm_n={len(cl)})")
```

---

## Wrap — Step 4 decision

Record: AR2 forward-corr table, AR3 rise-from-calm + trajectory, AR4 robustness (if run).

**The fork (final piece of the regime model):**
- **AR leads (AR3 passes):** the complete model is **VIX (sizing) + est_prob gate (in-crisis) +
  AR overlay (pre-crisis fragility warning)** — three simple signals, three jobs, all validated.
- **AR does not lead:** ship **VIX + est_prob** as-is. The model has no pre-crisis warning, BY
  EVIDENCE — every candidate (level factors AND the literature's top cross-asset signal) tested and
  none leads on this data. That is a legitimate, well-supported conclusion, not a gap left unexplored.
```
