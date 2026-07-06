# Step 3 — Joint Model (Layer A sizing scalar) — intended notebook cells (2026-06-24)

> Step 3 of the R-c roadmap. Fit a joint model on the Step-2 pruned matrix → a single market-status
> scalar for **sizing (Layer A)**. The est_prob crisis gate (Layer B) stays separate.
> Findings: `docs/research/regime_model/2026-06-24_step1_eda_findings.md`.
>
> **This step is a GATE, not an open build.** The joint scalar must beat the 2-factor (VIX, ebp)
> regression baseline on **forward realized vol R²** (the §A4 sizing job). Baseline from Step 1:
> **vix+ebp joint R² = 0.384.** If the joint model can't beat it, ship the 2-factor model + gate.
>
> **Outputs (both, per decision):** (a) a CONTINUOUS risk scalar — scored on the gate; (b) discrete
> regime labels — readable overlay only, NOT the pass/fail criterion.
> **Membership tunable:** start [VIX, hy_spread, real_yield_10y, term_spread]; test credit_ratio by lift.

---

## J0 — Assemble the gate's target + the baseline to beat

```python
# %% J0 — pruned [0,1] matrix from Step 2 (Nu_long) + forward realized vol target + the BASELINE.
#         Assumes P0/P1 of step2 cells already ran -> Nu_long, panel, ROOT, con available.
import numpy as np, pandas as pd, duckdb
import statsmodels.api as sm

PRUNED = ["VIX", "hy_spread", "real_yield_10y", "term_spread"]   # tunable; +credit_ratio tested in J4
X = Nu_long[PRUNED].copy()

# forward realized vol (sizing target, daily, ann.) — same construction as Step-1 S3d-incr
con = duckdb.connect(str(ROOT / "data" / "market_data.duckdb"), read_only=True)
spy = con.execute("SELECT date,close FROM price_data WHERE ticker='SPY' ORDER BY date").df()
con.close()
spy["date"] = pd.to_datetime(spy["date"]); spy = spy.set_index("date")["close"]
dret = spy.pct_change()
fwd_vol = (dret.rolling(63).std().shift(-63) * np.sqrt(252)).rename("fwd_vol")   # next-quarter vol

D = X.join(fwd_vol, how="inner").dropna()
print(f"fit/eval frame: n={len(D)}  {D.index.min().date()} -> {D.index.max().date()}")

# --- the BASELINE the joint model must beat (rebuilt here on the SAME daily frame for fairness) ---
# vix is in X; ebp is monthly -> ffill to daily for an apples-to-apples daily baseline
gz = pd.read_parquet(ROOT / "scratch" / "gz_ebp_monthly.parquet").set_index("date")
ebp_d = gz["ebp"].reindex(D.index, method="ffill")
B = pd.DataFrame({"vix": D["VIX"], "ebp": ebp_d, "fwd_vol": D["fwd_vol"]}).dropna()
Bz = (B[["vix","ebp"]] - B[["vix","ebp"]].mean()) / B[["vix","ebp"]].std()
base_r2 = sm.OLS(B["fwd_vol"], sm.add_constant(Bz)).fit().rsquared
print(f"BASELINE (vix+ebp) daily fwd_vol R² = {base_r2:.3f}   <-- the number to beat")
```

**Note:** the Step-1 baseline (0.384) was monthly; J0 rebuilds it daily on THIS frame so the gate is
fair (same rows, same target). Record the daily `base_r2` here — that is the actual bar for J2/J3.

---

## J1 — Fit the joint models (continuous scalar + labels)

```python
# %% J1 — three candidate joint models. Each yields (continuous score, discrete labels).
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler
from scipy.spatial.distance import mahalanobis

Xs = StandardScaler().fit_transform(X.loc[D.index])     # standardize for the models

models = {}

# (a) Mahalanobis distance from the 'normal' centroid — the simplest joint scalar, fully explainable
mu = Xs.mean(0); cov = np.cov(Xs.T); inv = np.linalg.pinv(cov)
maha = np.array([mahalanobis(r, mu, inv) for r in Xs])
models["maha"] = {"score": pd.Series(maha, index=D.index), "labels": None}

# (b) GMM (k=4) — crisis-component posterior as the score; argmax as labels
gmm = GaussianMixture(n_components=4, covariance_type="full", random_state=0).fit(Xs)
post = gmm.predict_proba(Xs); lab = gmm.predict(Xs)
# crisis component = the one with highest mean fwd_vol
comp_vol = pd.Series(D["fwd_vol"].values, index=lab).groupby(level=0).mean()
crisis_c = comp_vol.idxmax()
models["gmm"] = {"score": pd.Series(post[:, crisis_c], index=D.index),
                 "labels": pd.Series(lab, index=D.index)}

# (c) HMM (k=4) — same idea, but temporal persistence (regimes are sticky). Optional if hmmlearn present.
try:
    from hmmlearn.hmm import GaussianHMM
    hmm = GaussianHMM(n_components=4, covariance_type="full", n_iter=100, random_state=0).fit(Xs)
    hlab = hmm.predict(Xs)
    hpost = hmm.predict_proba(Xs)
    hc = pd.Series(D["fwd_vol"].values, index=hlab).groupby(level=0).mean().idxmax()
    models["hmm"] = {"score": pd.Series(hpost[:, hc], index=D.index),
                     "labels": pd.Series(hlab, index=D.index)}
except ImportError:
    print("hmmlearn not installed — skipping HMM (pip install hmmlearn to enable)")

print("fitted:", list(models.keys()))
```

---

## J2 — THE GATE: does any joint scalar beat the baseline on fwd-vol R²?

```python
# %% J2 — score each continuous scalar vs the baseline. This is the pass/fail.
rows = []
for name, m in models.items():
    s = m["score"].reindex(D.index)
    z = (s - s.mean()) / s.std()
    r2 = sm.OLS(D["fwd_vol"], sm.add_constant(z)).fit().rsquared
    corr = np.corrcoef(z, D["fwd_vol"])[0, 1]
    rows.append({"model": name, "fwd_vol_R2": r2, "corr": corr,
                 "beats_baseline": r2 > base_r2})
gate = pd.DataFrame(rows).set_index("model")
print(f"BASELINE (vix+ebp) R² = {base_r2:.3f}\n")
print(gate.round(3).to_string())
print("\nVERDICT: any True in beats_baseline => R-c ML stage justified. All False => ship 2-factor model.")
```

**Deliverable — the R-c verdict.** If a joint scalar clears `base_r2`, the learned model earns its
place and we proceed to calibrate it (Step 4). If NOT — the honest, pre-committed outcome — we ship
the explainable 2-factor (VIX, ebp) sizing model + the est_prob gate, and R-c's ML stage is closed as
"tested, did not beat baseline." Either way the question is SETTLED, not left open.

---

## J3 — Sanity: is the joint scalar adding signal, or just re-encoding VIX?

```python
# %% J3 — even if a model beats the baseline, check WHY. Partial R² over vix-alone: does the joint
#         scalar add fwd-vol info BEYOND vix? If not, it's a VIX proxy and not worth the complexity.
vixz = (D["VIX"] - D["VIX"].mean()) / D["VIX"].std()
r2_vix = sm.OLS(D["fwd_vol"], sm.add_constant(vixz)).fit().rsquared
print(f"vix-alone fwd_vol R² = {r2_vix:.3f}")
for name, m in models.items():
    s = m["score"].reindex(D.index); z = (s - s.mean()) / s.std()
    both = sm.OLS(D["fwd_vol"], sm.add_constant(pd.DataFrame({"vix": vixz, "joint": z}))).fit()
    print(f"  {name:6s}: vix+joint R²={both.rsquared:.3f}  joint dR² over vix={both.rsquared - r2_vix:+.3f}  joint_p={both.pvalues['joint']:.3f}")
```

**Deliverable:** guards against the §A5 trap ("looks like VIX"). A joint model that beats the baseline
only by re-encoding VIX is not worth it; we want incremental fwd-vol info beyond VIX.

---

## J4 — Membership tuning: does adding credit_ratio lift the gate?

```python
# %% J4 — the deferred 'decide by lift' question. Refit the BEST J2 model with credit_ratio added.
best = gate["fwd_vol_R2"].idxmax()
for extra in [[], ["credit_ratio"]]:
    cols = PRUNED + extra
    Xe = Nu_long[cols].join(fwd_vol, how="inner").dropna()
    Xs2 = StandardScaler().fit_transform(Xe[cols])
    if best == "maha":
        mu2 = Xs2.mean(0); inv2 = np.linalg.pinv(np.cov(Xs2.T))
        sc = np.array([mahalanobis(r, mu2, inv2) for r in Xs2])
    else:
        g = GaussianMixture(n_components=4, covariance_type="full", random_state=0).fit(Xs2)
        p = g.predict_proba(Xs2); l = g.predict(Xs2)
        cc = pd.Series(Xe["fwd_vol"].values, index=l).groupby(level=0).mean().idxmax()
        sc = p[:, cc]
    z = pd.Series((sc - sc.mean()) / sc.std(), index=Xe.index)
    r2 = sm.OLS(Xe["fwd_vol"], sm.add_constant(z)).fit().rsquared
    print(f"  {best} with {cols}: fwd_vol R²={r2:.3f}")
```

**Deliverable:** keep credit_ratio in Layer A only if it lifts the gated R². Finalizes membership by
evidence, not assumption (the Step-2 deferred decision).

---

## J5 — Regime labels as a readable overlay (interpretation, NOT the gate)

```python
# %% J5 — describe the discrete regimes from the best LABEL-producing model (gmm/hmm). Overlay only.
m = models.get("hmm", models.get("gmm"))
if m["labels"] is not None:
    lab = m["labels"]
    tab = pd.DataFrame({"fwd_vol": D["fwd_vol"], "lab": lab})
    summ = tab.groupby("lab").agg(n=("fwd_vol","size"), mean_fwd_vol=("fwd_vol","mean"),
                                   median_fwd_vol=("fwd_vol","median"))
    # add mean of each raw factor per regime for naming
    for f in PRUNED: summ[f] = X.loc[D.index].groupby(lab)[f].mean()
    print(summ.round(3).to_string())
    # run-length (persistence) — are these regimes or noise?
    runs = (lab != lab.shift()).cumsum()
    print(f"\nmean regime run-length: {lab.groupby(runs).size().mean():.1f} trading days")
```

**Deliverable:** named, persistent regimes for human reading (e.g. "calm / risk-off / crisis"),
mapped to their fwd-vol so the scalar is interpretable. This satisfies the *spirit* of design §1
(explainable regime) even though §1.1 was formally relaxed — a bonus, not the gate.

---

## Wrap — Step 3 decision

Record: **(1) base_r2 (the bar), (2) the gate table (J2), (3) the J3 incremental-over-vix check,
(4) the J4 membership verdict, (5) the J5 regime overlay.**

**The fork:**
- **Joint beats baseline (J2) AND adds info over vix (J3):** R-c justified → proceed to Step 4
  (calibrate scalar→size map on stressed history, design §7-E).
- **Joint does NOT beat baseline:** ship the **2-factor (VIX, ebp) sizing model + est_prob gate**.
  This is a clean, explainable, fully-tested result — NOT a failure. The EDA's job was to find the
  simplest model that works; if that's 2 factors, that's the finding.
```
