# Step 2 — Cross-Factor Comparability (P2) — intended notebook cells (2026-06-24)

> Step 2 of the R-c roadmap. Goal: produce ONE comparable, decorrelated daily factor matrix that
> Step 3's joint model consumes (**Layer A only** — the est_prob crisis gate is Layer B, settled in
> Step 1, sits OUTSIDE this). Findings doc: `docs/research/regime_model/2026-06-24_step1_eda_findings.md`.
>
> **Decisions carried in from Step 1 (do not re-litigate):**
> - Normalization per-factor: fat-tail/mean-reverting (VIX, HY, MOVE) → **percentile**; drifting/
>   regime-switching (rates, DXY) → **rolling-window z** (no differencing — keeps the cycle).
> - Decorrelation: **decide empirically** — build BOTH a pruned and a whitened version, compare.
> - Factor set: **full set, decorrelated** — but on the LONG window (2007+, MOVE held out); MOVE is
>   checked on its 2021+ slice separately (the FULL-with-MOVE panel is 1306 rows of ONE regime → unfit).
> - `panel` has NaN holes (no ffill) → ALWAYS `.dropna()` per factor before any rolling op (S2 bug).

---

## P0 — Rebuild the panel + define the two windows

```python
# %% P0 — panel (reuse S0 loader) + LONG (2007+, no MOVE) vs SHORT (2021+, +MOVE) split
import numpy as np, pandas as pd, duckdb
from pathlib import Path
import matplotlib.pyplot as plt
def _repo_root() -> Path:
    p = Path.cwd().resolve()
    for d in (p, *p.parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError(f"repo root not found above {p}")

ROOT = _repo_root()
con = duckdb.connect(str(ROOT / "data" / "market_data.duckdb"), read_only=True)

fred = pd.read_parquet(ROOT / "scratch" / "raw_factor_panel.parquet")
fred["date"] = pd.to_datetime(fred["date"])
fred = fred.pivot(index="date", columns="symbol", values="value")
macro = con.execute("""SELECT date,symbol,close FROM macro_data
    WHERE symbol IN ('VIX','BAMLH0A0HYM2','DGS10','DGS2')""").df()
macro["date"] = pd.to_datetime(macro["date"])
macro = macro.pivot(index="date", columns="symbol", values="close").rename(columns={"BAMLH0A0HYM2":"hy_spread"})
etf = con.execute("SELECT date,ticker,close FROM price_data WHERE ticker IN ('HYG','LQD','MOVE')").df()
etf["date"] = pd.to_datetime(etf["date"]); etf = etf.pivot(index="date", columns="ticker", values="close")
con.close()

panel = fred.join(macro, how="outer").join(etf, how="outer").sort_index()
panel["term_spread"]  = panel["DGS10"] - panel["DGS2"]
panel["credit_ratio"] = panel["HYG"] / panel["LQD"]

# normalization assignment from Step 1 (S1/S2)
PERCENTILE = ["VIX", "hy_spread", "MOVE"]                       # fat-tail + mean-reverting
ROLLING_Z  = ["real_yield_10y", "DGS10", "DGS2", "dxy_broad"]   # drifting / regime-switching
DERIVED    = ["term_spread", "credit_ratio"]                    # checked below, default rolling-z

LONG_SET  = ["VIX", "hy_spread", "real_yield_10y", "dxy_broad",
             "DGS10", "DGS2", "term_spread", "credit_ratio"]    # 2007+, NO MOVE
SHORT_SET = LONG_SET + ["MOVE"]                                 # 2021+, MOVE included (axis-check only)
print("LONG (fit window):", panel[LONG_SET].dropna().index.min().date(), "n=", len(panel[LONG_SET].dropna()))
print("SHORT (MOVE chk) :", panel[SHORT_SET].dropna().index.min().date(), "n=", len(panel[SHORT_SET].dropna()))
```

---

## P1 — Per-factor normalization (percentile vs rolling-z, per Step 1 labels)

```python
# %% P1 — apply the Step-1 normalization choice to each factor. Output: normalized daily matrix.
ROLL = 1260   # 5yr rolling window for drifting factors (captures business cycle, per S2/§10)

def to_percentile(s, win=None):
    s = s.dropna()
    if win is None:                       # full-history rank percentile (mean-reverting factors)
        return s.rank(pct=True)
    return s.rolling(win).apply(lambda w: (w.argsort().argsort()[-1] + 1) / len(w), raw=True)

def to_rolling_z(s, win=ROLL):
    s = s.dropna()                        # per-factor dropna (panel has NaN holes)
    mu = s.rolling(win).mean(); sd = s.rolling(win).std()
    return (s - mu) / sd

norm = {}
for f in PERCENTILE:
    norm[f] = to_percentile(panel[f])                 # full-history percentile
for f in ROLLING_Z + DERIVED:
    norm[f] = to_rolling_z(panel[f])                  # 5yr rolling z
N = pd.DataFrame(norm).sort_index()

# sanity: percentile factors in [0,1], rolling-z roughly mean 0; show coverage after 5yr warmup
print(N[LONG_SET].describe().loc[["mean","std","min","max"]].round(2).to_string())
Nlong  = N[LONG_SET].dropna()
print(f"\nLONG normalized matrix usable after warmup: {Nlong.index.min().date()} n={len(Nlong)}")

# NOTE: percentile factors live in [0,1], rolling-z in z-units. To put on a COMMON ruler for the
# joint model, convert rolling-z to percentile-of-normal too (so all factors are uniform [0,1]):
from scipy.stats import norm as _nd
Nu = N.copy()
for f in ROLLING_Z + DERIVED:
    Nu[f] = _nd.cdf(N[f])                              # z -> uniform [0,1]
Nu_long = Nu[LONG_SET].dropna()
print(f"unified [0,1] matrix: n={len(Nu_long)}  all cols in [0,1]: "
      f"{(Nu_long.min().min() >= 0) and (Nu_long.max().max() <= 1)}")
```

**Decision recorded:** all factors mapped to a **common [0,1] ruler** — percentile for mean-reverting,
percentile-of-rolling-normal for drifting. This is the P2 "shared space" resolution: every factor now
answers the SAME question ("how extreme vs. its own appropriate reference"), so their joint position
is coherent (design §5 requirement). `Nu` = unified matrix; `N` = mixed (kept for inspection).

---

## P2a — Decorrelation, version A: PRUNE to cluster representatives

```python
# %% P2a — empirical decorrelation route 1: hierarchical cluster the factors, keep one per cluster.
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import squareform

C = Nu_long.corr()
d = squareform(1 - C.abs().values, checks=False)      # distance = 1 - |corr|
Z = linkage(d, method="average")
for thr in [0.3, 0.5]:                                  # |corr|>0.7 and >0.5 cluster cuts
    cl = fcluster(Z, t=thr, criterion="distance")
    groups = {}
    for f, c in zip(LONG_SET, cl): groups.setdefault(c, []).append(f)
    print(f"cut |corr|>{1-thr:.1f}: {list(groups.values())}")

# pick representative = lowest mean |corr| to OTHERS within cluster is wrong; pick the most
# interpretable / longest-history member per cluster (manual, informed by the print above)
PRUNED = ["VIX", "hy_spread", "real_yield_10y", "term_spread"]   # EDIT after seeing clusters
Xp = Nu_long[PRUNED]
print("\nPRUNED set:", PRUNED)
print("max |offdiag corr| after prune:", (Xp.corr().abs() - np.eye(len(PRUNED))).max().max().round(2))
```

## P2b — Decorrelation, version B: PCA-WHITEN the full set

```python
# %% P2b — empirical decorrelation route 2: whiten. Keep all factors, output orthogonal components.
from numpy.linalg import svd
M = Nu_long.values - Nu_long.values.mean(0)
U, S, Vt = svd(M, full_matrices=False)
evr = (S**2) / (S**2).sum()
print("explained var ratio:", np.round(evr, 3))
print("cumulative:        ", np.round(np.cumsum(evr), 3))
# loadings of the first 3 components (which raw factors drive each axis)
load = pd.DataFrame(Vt[:3].T, index=LONG_SET, columns=["PC1","PC2","PC3"])
print(load.round(2).to_string())
# whitened scores (unit variance, orthogonal) -- candidate Layer-A input
Wh = pd.DataFrame((U * 1.0)[:, :4], index=Nu_long.index, columns=[f"w{i+1}" for i in range(4)])
print("\nwhitened corr (should be ~I):"); print(Wh.corr().round(2).to_string())
```

## P2b-plot — PCA biplot + loadings heatmap (the visual of "VIX is only PC3")

```python
# %% P2b-plot — make the P2b loadings VISUAL. Two panels:
#   (left)  biplot: each DATE scored on PC1×PC2, with factor loading arrows overlaid.
#   (right) loadings heatmap PC1-3 × factors — shows PC1=rate/dollar level, PC3=pure VIX (the point).
import matplotlib.pyplot as plt

scores = M @ Vt.T                       # date scores on every PC (M, Vt from P2b)
fig, ax = plt.subplots(1, 2, figsize=(15, 6))

# --- left: PC1-PC2 biplot, colored by VIX percentile so we can SEE risk-off ---
vix_pctl = Nu_long["VIX"].rank(pct=True).values if "VIX" in Nu_long.columns else None
sc = ax[0].scatter(scores[:, 0], scores[:, 1], c=vix_pctl, cmap="RdYlGn_r", s=6, alpha=.5)
plt.colorbar(sc, ax=ax[0], label="VIX percentile (red = stress)")
arrow_scale = np.abs(scores[:, :2]).max() * 0.9
for i, fac in enumerate(LONG_SET):
    ax[0].arrow(0, 0, Vt[0, i] * arrow_scale, Vt[1, i] * arrow_scale,
                color="black", head_width=arrow_scale * .02, length_includes_head=True)
    ax[0].text(Vt[0, i] * arrow_scale * 1.12, Vt[1, i] * arrow_scale * 1.12, fac,
               fontsize=9, ha="center", color="navy")
ax[0].axhline(0, color="grey", lw=.5); ax[0].axvline(0, color="grey", lw=.5)
ax[0].set_xlabel(f"PC1 ({evr[0]:.0%}) — rate/dollar level")
ax[0].set_ylabel(f"PC2 ({evr[1]:.0%}) — credit-vs-curve")
ax[0].set_title("PCA biplot: dates on PC1×PC2 + factor loadings")

# --- right: loadings heatmap, the decisive 'where does VIX live' view ---
load_full = pd.DataFrame(Vt[:3].T, index=LONG_SET, columns=["PC1","PC2","PC3"])
im = ax[1].imshow(load_full.values, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")
ax[1].set_xticks(range(3)); ax[1].set_xticklabels(
    [f"PC1\n{evr[0]:.0%}", f"PC2\n{evr[1]:.0%}", f"PC3\n{evr[2]:.0%}"])
ax[1].set_yticks(range(len(LONG_SET))); ax[1].set_yticklabels(LONG_SET)
for (r, c), v in np.ndenumerate(load_full.values):
    ax[1].text(c, r, f"{v:.2f}", ha="center", va="center",
               color="white" if abs(v) > .55 else "black", fontsize=8)
plt.colorbar(im, ax=ax[1], label="loading")
ax[1].set_title("Loadings — VIX sits in PC3 (11%), NOT PC1")
fig.tight_layout()
```

**Read (this plot IS the PRUNE argument):** the heatmap shows PC1 (54%) is loaded on
`real_yield/DGS10/DGS2` (the rate-level bloc) and **VIX barely loads on PC1–PC2 — it's PC3, ~11%**. So
whitening (which optimizes for variance) would hand the joint model 54% attention to the rate level
and bury VIX, the ONE proven-useful factor (§A4 fwd-vol corr 0.67). The biplot's red (high-VIX) dates
scatter along PC3, orthogonal to the dominant axes — visual confirmation that **variance ≠ usefulness**
here. This is why P2c's silhouette tie resolves to **PRUNED**, not whitened.

## P2c — COMPARE the two routes (the empirical decision)

```python
# %% P2c — which decorrelation gives cleaner / more separable regimes? Judge on:
#   (1) how many components/factors carry the variance (parsimony),
#   (2) separability of a quick KMeans on each (silhouette),
#   (3) does each route still SEPARATE known stress episodes (Covid 2020, 2022) from calm?
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

def regime_quality(X, k=4, label=""):
    km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(X)
    sil = silhouette_score(X, km.labels_)
    # fwd realized vol separation across clusters = does the regime mean anything?
    print(f"{label:10s} k={k} silhouette={sil:.3f}")
    return km.labels_

print("=== PRUNED ==="); lp = regime_quality(Xp.values, label="pruned")
print("=== WHITENED (top4) ==="); lw = regime_quality(Wh.values, label="whitened")
# overlay Covid/2022 to eyeball whether either cleanly isolates crisis
for name, lab, idx in [("pruned", lp, Xp.index), ("whitened", lw, Wh.index)]:
    s = pd.Series(lab, index=idx)
    covid = s.loc["2020-03-01":"2020-04-30"].mode()
    print(f"{name}: dominant cluster in Mar-Apr 2020 = {covid.values}")
```

**Deliverable — the Step-2 decision:** pick PRUNED or WHITENED for Layer A based on P2c
(parsimony + silhouette + clean crisis isolation). Expectation from S5 (~2 axes): both should work;
PRUNED is more explainable (named factors), WHITENED retains more info but PC axes are less readable.
Given Step-1 relaxed §1.1 explainability, WHITENED is acceptable IF it separates regimes materially
better; otherwise prefer PRUNED for interpretability. **Record the choice + numbers here.**

---

## P3 — MOVE axis-check (does it add an axis the LONG set misses?)

```python
# %% P3 — ONLY question for MOVE: on its 2021+ slice, is it spanned by the existing factors, or a
#         distinct axis? If R^2 of MOVE on the others is high, it's redundant -> stays out. If low,
#         it's a real bond-vol axis -> flag for inclusion once history allows (P4, future).
import statsmodels.api as sm
Nu_short = Nu[SHORT_SET].dropna()
y = Nu_short["MOVE"]; X = sm.add_constant(Nu_short[[c for c in LONG_SET]])
r2 = sm.OLS(y, X).fit().rsquared
print(f"MOVE 2021+ slice: n={len(Nu_short)}  R^2(MOVE ~ other factors)={r2:.3f}")
print("  high R^2 (>0.7) => MOVE is redundant on this window, leave out (consistent w/ S5 collinearity)")
print("  low  R^2 (<0.4) => MOVE is a DISTINCT axis; revisit when pre-2021 history is sourced (P4)")
```

**Deliverable:** keep/defer decision for MOVE, evidence-based, without letting its short history
clamp the main matrix.

---

## Wrap — Step 2 outputs handed to Step 3

1. **`Nu_long`** — unified [0,1] daily factor matrix, 2007+, the common space (P2 resolved).
2. **Decorrelation choice** (PRUNED vs WHITENED) + the matrix that won (P2c).
3. **MOVE verdict** (P3).
4. Confirm the **est_prob crisis gate (Layer B)** stays separate — NOT added to this matrix.

**Then Step 3** fits the joint model (GMM/HMM/PCA) on the chosen matrix and is GATED on beating the
2-factor (VIX, ebp) regression baseline from Step 1 (R² 0.384 sizing / 0.097 timing).
```
