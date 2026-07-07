# Regime Model Research — Meta Map & Metric Glossary

> **Purpose:** one place to see, per step: the **problem statement**, **what we did**, the **result**,
> and the **exact test + metric definitions** behind each conclusion. Built so a future challenge (like
> the momentum and heterogeneity challenges of 2026-06-25/26) can be mounted in minutes, not by
> re-reading five docs. **This file is an INDEX — it summarizes; the linked docs are authoritative.**
>
> **Status legend:** ✅ run & concluded · 🟡 designed/cells written, NOT yet run · ❌ falsified ·
> 🔒 shipped.
>
> Last updated: 2026-06-26.

---

## 0. The one-line state of the investigation

**Shipped model 🔒:** `VIX` (continuous sizing) + `est_prob > ~30%` gate (in-crisis exposure cut).
Both trivial, both walk-forward-validated, both explainable. **No pre-crisis warning layer — by
evidence (Steps 1–4).** Two open challenges to that "no lead" conclusion are now in flight:
**Step 6** (per-mechanism, the strong one) and **Step 5** (strategic valuation, a different horizon).

**The throughline:** characterize each factor on its own ruler → test LEAD vs COINCIDENT →
decorrelate → GATE any joint model on beating a simple baseline (VIX-alone, OOS). Find the simplest
model that works.

### 0.1 The PRE-EXISTING baseline: the M03 / 5-risk-factor model (where this all started)

> This whole investigation began as an attempt to *improve* the model(s) below. They are the incumbent,
> the comparison baseline, and the origin of every problem the steps address. **Not broken** — working,
> unified, single-number regime/sizing models. Source of truth: design doc §2–5 + Appendix A, and the
> CODE: `src/pipeline/risk_5_factor.py` (5-factor) and `src/pipeline/m03_regime.py` (M03 pillars).

> ⚠️ **NAMING — two distinct models, often both called "M03/risk":**
> - **`RiskFiveFactorCalculator`** (`risk_5_factor.py`) — the **5-factor z-score → exposure** model.
>   This is the *sizing baseline* the R-c investigation tried to beat (the `z_vix…z_slope` weights,
>   bands, veto below). Writes `t2_risk_scores`.
> - **`M03RegimeCalculator`** (`m03_regime.py`) — a **separate 3-pillar 0–100 score**
>   (Trend/Liquidity/RiskAppetite) that feeds **M01 as 8 features** (`m03_score`, pillars, deltas).
>   Different formulas, different output, different consumer. Documented in §0.2.
> Steps 1–6 operate on the **5-factor** model's question (sizing + lead); M03-pillar is the feature-gen
> cousin. Both are below so a challenge knows exactly which is which.

**(A) The 5-factor sizing model — architecture (the "one explainable number" chain):**
```
per-factor 10yr (2555d) ROLLING z-score   z = (f − rollmean) / rollstd(ddof=1)
  → weighted sum  weighted_z = Σ(z · W)
  → 5yr (1260d) rolling percentile   pct = #(window < today) / (window−1)
  → 6 discrete exposure bands (0.15 … 1.00)
  → veto: ANY factor z ≥ 2.0  →  target_exposure = 0.15
```

**The 5 RAW factor formulas (all signed so positive = MORE market risk)** — from `risk_5_factor.py`:

| factor | weight | formula (source) | reads as |
|---|---|---|---|
| `f_vix`   | .25 | `vix` (spot level) | high VIX = risk |
| `f_hy`    | .25 | `hy_oas − hy_oas.shift(20)` where `hy_oas = WBAA − DGS10` | 20d *widening* of HY credit spread = risk |
| `f_term`  | .15 | `−(DGS10 − DGS2)` | curve *inversion* (neg term spread) = risk |
| `f_trend` | .15 | `−(SPX / SMA200 − 1)` | SPX *below* its 200d SMA = risk |
| `f_slope` | .20 | `−(SMA200 / SMA200.shift(20) − 1)` | 200d SMA *rolling over* (20d) = risk |

> Note: `f_hy` here is a **20-day CHANGE** of the WBAA−DGS10 spread (a momentum term), NOT the raw HY
> OAS level the EDA later sourced (`BAMLH0A0HYM2`). And `f_slope` is an SMA-momentum proxy, not the
> Fed net-liquidity slope used in the M03-pillar model — the two "risk" models do NOT share inputs.

**Normalization & aggregation (exact):**
- z-score: 2555d rolling, `min_periods=2555` (so ~10yr warmup before ANY score) — `ddof=1`.
- `weighted_z = .25·z_vix + .25·z_hy + .15·z_term + .15·z_trend + .20·z_slope`.
- `rolling_percentile` of `weighted_z`: 1260d window, strict-less-than rank `/(window−1)`.
- **Exposure bands** (percentile → equity exposure): `[0.00,0.20)→1.00 · [0.20,0.40)→0.85 ·
  [0.40,0.55)→0.75 · [0.55,0.70)→0.50 · [0.70,0.85)→0.35 · [0.85,1.00)→0.15`.
- **Veto:** `(any z ≥ 2.0) → target_exposure = 0.15` (overrides the band).

- **Actual variance-share** of `weighted_z` (design §2, proves it's balanced, NOT a VIX proxy):
  **z_vix 29.5% · z_hy 24.8% · z_slope 21.7% · z_trend 19.1% · z_term 4.9%.**

**What it's actually GOOD for (proven, keep):**
- **SIZING, not direction.** `corr(z_vix, realized vol next H days)` peaks **0.67 @ H=5–10d**, monotone
  across deciles (ann. fwd vol 9.4% → 33.7%). It forecasts **dispersion**, horizon ≈ 1–2 weeks.
- **It is COINCIDENT, not predictive.** `corr(z_vix, fwd RETURN)` is *positive* and rises with horizon
  — danger is contrarian-bullish on the mean. (This is the finding the whole "does anything lead?"
  investigation set out to overturn — and, through Step 4, could not.)
- **A regime = the joint correlation structure** (z_trend–z_slope 0.79, z_vix–z_trend 0.67, z_term ⟂
  all). 4 KMeans clusters = 4 interpretable, persistent regimes incl. a clean Mar-2020 crisis cluster.
  → regime ID is inherently **multivariate** — it can't come from factors treated independently.

**Its ONE real structural flaw — and the four sub-problems it spawned (the ORIGIN of every step):**

| ID | Problem | What it is | Why it matters / what does NOT fix it |
|---|---|---|---|
| **flaw** | **Temporal amnesia** | the 10yr ROLLING window forgets old shocks: GFC already aged out, Covid exits ~2030. Once worst stress leaves the window, a future VIX=40 z-scores *too extreme* and the z≥2 veto drifts. **The yardstick slides.** | fixed/expanding reference fixes it; rolling doesn't. This is the *motivating* defect. |
| **P1** | Temporal amnesia (formal) | rolling μ/σ forgets shocks; adding "normal" years dilutes σ → fixed extremes z-score weaker over time | anchored/expanding ref fixes; rolling doesn't |
| **P2** | Cross-factor comparability | VIX-z=2 ≠ MOVE-z=2 in stress *meaning* (different tail shapes/horizons) | z-scoring does NOT fix; anchoring does NOT fix → **Step 2** (common [0,1] ruler) |
| **P3** | Secular drift | rate/liquidity *levels* shift structurally (ZIRP vs now) → fixed μ mis-centers them | per-factor reference, OR stationary transform → **Step 1 S1/S2** |
| **P4** | Short history | MOVE (2021+) has no crisis in its native data → no honest tail | no normalization manufactures missing data → **MOVE DROPPED** |

**The central tension that makes it hard (design §5):** mean-reverting factors (VIX, HY) want
*full-history* references (keep crisis memory); drifting factors (rates, liquidity) want *recent*
references (what's "normal" changed). But regime ID needs ALL factors on the SAME reference or the
joint position is incoherent. **You can't have per-factor-optimal references AND a coherent joint
regime via different windows** — that conflict is what the R-c roadmap (Steps 1–3) set out to resolve.

**Where the shipped model came from:** Steps 1–4 tested whether a smarter *joint* model could beat this
baseline's core use (sizing) or add the thing it lacks (a *lead*). Result: the joint ML lost to
VIX-alone OOS (Step 3), nothing leads (Steps 1–4) → the baseline's multi-factor machinery was **not
justified by evidence**, and the investigation collapsed it to `VIX + est_prob gate`. So the shipped
model is the 5-factor baseline's proven core (VIX sizing) + the one signal that survived (est_prob
gate), with the 5-factor aggregation, bands, and z≥2 veto **retired as unvalidated complexity.**

### 0.2 The M03-pillar model (the M01 feature-generator cousin) — formulas

> SEPARATE from §0.1's 5-factor model. `M03RegimeCalculator` (`m03_regime.py`, version 1.1.0) outputs a
> **0–100 bullishness score** (higher = bullish — opposite orientation to the 5-factor "risk" sign) and
> generates **8 normalized features consumed by M01**. It is NOT the sizing model the R-c steps tried to
> beat; it's the regime-feature feed. Documented here so the two "M03/risk" things are never conflated.

**Composite:** `score = 0.40·trend + 0.30·liquidity + 0.30·risk_appetite`, each pillar on 0–100,
clipped 0–100. **T+1 publication lag** applied to all FRED macro (avoids lookahead; VIX is T+0).

**Pillar formulas (from source):**

| pillar | weight | formula | notes |
|---|---|---|---|
| **Trend** | .40 | `50 + 50·tanh(pct_above · 10)`, `pct_above = (SPY − SMA200)/SMA200` | ±10% from SMA200 saturates to ~0/100 |
| **Liquidity** | .30 | `50 + 50·tanh(slope_pct · 50)`, `slope_pct = (20d OLS slope of NetLiq / NetLiq)·100`; **`NetLiq = WALCL − WTREGEN − RRPONTSYD`** (Fed assets − TGA − RRP) | rising net liquidity = bullish |
| **Risk Appetite** | .30 | `vix_score + spread_score`, each 0–50: `vix_score = 50·(1 − clip((VIX−10)/(40−10),0,1))`; `spread_score = 50·(1 − clip((HY−2)/(8−2),0,1))` | linear ramps; VIX 10→50pts/40→0, HY 2%→50pts/8%→0 |

**Categories** (score → label): `≥80 strong_bull · ≥60 bull · ≥40 neutral · ≥20 bear · else strong_bear`.
**Gating:** `allow_longs = score ≥ 30`; `reduced_sizing = score < 50`.

**The 8 M01 features** (`generate_m01_features`, all normalized): `m03_score` (score/100),
`m03_regime_cat` (ordinal 0–4), `m03_delta_5d` / `m03_delta_20d` (score.diff(5|20)/100),
`m03_regime_vol` (10d rolling std/100, clip≤1), `m03_pillar_trend|liq|risk` (each pillar/100).

> **Cross-reference for challenges:** the 5-factor model's `f_hy` is a 20d *change* of `WBAA−DGS10`;
> the M03-pillar's risk uses the raw HY level `BAMLH0A0HYM2`. Its `f_slope` is SMA-momentum; the
> pillar's liquidity is Fed-NetLiq slope. **Same names ("risk", "trend"), different math** — when a
> result cites "HY" or "trend" or "liquidity", check WHICH model it came from.

---

## 1. Document map (what lives where)

| Doc | Role |
|---|---|
| `market_regime_literature_review.md` | The survey — what the academic literature claims leads. |
| `2026-06-24_regime_model_design.md` | Design record + open decisions (§10 roadmap, Appendix A evidence). |
| `2026-06-24_regime_eda_findings.md` | **The evidence trail.** Steps 1–4 thinking, data, gates. ⭐ primary. |
| `2026-06-25_factor_momentum_challenge.md` | Challenge #1: levels-only blindspot (rate-of-change). |
| `2026-06-26_step6_per_mechanism_design.md` | Challenge #2 + pre-registered protocol (event-averaging blindspot). |
| `README_regime_research_map.md` | **This file** — meta index + metric glossary. |
| Cells (executable), per step | S1+S1b: `2026-06-24_raw_factor_eda_cells.md` (NB: not named `step1`; S3d-incr/S3e appended) · S2: `..._step2_comparability_cells.md` · S3: `..._step3_joint_model_cells.md` · S4: `..._step4_absorption_ratio_cells.md` · S5: `2026-06-25_step5_valuation_timing_cells.md` · S6: `2026-06-26_step6_per_mechanism_cells.md` |

---

## 2. Step-by-step map

Each row: **problem → what we did → result → which test/metric settled it** (metric defs in §3).

### Step 1 — Factor EDA: leading vs coincident ✅
- **Problem:** Do raw macro factors {VIX, HY spread, term spread, real yield, DXY, MOVE, credit ratio}
  *warn before* an equity tail, or only *confirm at* it?
- **What we did:** Distribution (S1), stationarity (S2), coincident-level conditioning on QQQ worst-5%
  days (S3), pre-tail "alerting" trajectory (S3b), de-overlap + calm-start control (S3c), reconcile
  with literature via GZ Excess Bond Premium (S3d/e), redundancy/PCA (S5).
- **Result ❌ (for a lead):** Raw factors are **COINCIDENT stress meters**, robust to de-clustering and
  calm-start. The S3b apparent "lead" (VIX z≈+0.62 at t−21) was **autocorrelation + event
  clustering**, not prediction — `B_rise_from_calm ≈ 0`. Only the **GZ EBP / est_prob** carries a real
  but **weak, crisis-only** lead (see Step-1b). Panel ≈ **2 independent axes** (risk-off VIX/HY; rate/
  dollar level) → decorrelation mandatory.
- **Settled by:** S3c rise-from-calm (≈0), de-overlapped pre-tail trajectory. §3 metrics: *coincident
  vs leading corr*, *rise-from-calm*.

### Step 1b — The GZ credit signal (the only real lead) ✅
- **Problem:** Literature says "credit leads 2–4 weeks." Does it, on our data, the way the papers test?
- **What we did:** Sourced the actual **Gilchrist-Zakrajšek Excess Bond Premium** (monthly 1973–2026,
  `ebp`/`gz_spread`/`est_prob`). Tested `corr(metric_t, fwd_return)`; incremental-R² over VIX;
  crisis-vs-ex-crisis split; tercile/decile/band monotonicity.
- **Result (weak + crisis-only):** `ebp` fwd-3m corr **−0.172 (SPY)**, stronger than QQQ (−0.108).
  Incremental over VIX: ΔR² **+0.034 sizing**, **+0.088 timing** — the only directional factor. **BUT
  S3e:** drop dot-com/GFC/Covid and corr **flips to +0.13**. It's a **tail switch, not a continuous
  tilt** — lives entirely in the top ebp decile / `est_prob > 30%`. `est_prob` beats `ebp` at every
  horizon (−0.197/−0.229 @ 3m/6m) and is already a calibrated probability.
- **Decision:** Use **`est_prob` as a THRESHOLD GATE** (Layer B), NOT a linear regression/PCA input —
  feeding a tail switch linearly dilutes it.
- **Settled by:** §3 metrics: *fwd-return corr*, *incremental ΔR²*, *crisis-exclusion sign flip*,
  *decile/band monotonicity*.
- **Cells:** S3d/S3d-incr/S3e in `2026-06-24_raw_factor_eda_cells.md` (appended after S3d — same file
  as Step 1, NOT a separate `step1b` file).

### Step 2 — Cross-factor comparability (P2) ✅
- **Problem:** Factors live on different rulers & re-measure the rate level ~3×. Build one comparable,
  decorrelated daily matrix for the joint model.
- **What we did:** Map all factors to **[0,1]** (full-history percentile for mean-reverting;
  percentile-of-rolling-5yr for drifting). Compare **PRUNE vs WHITEN** via clusters, PCA, silhouette.
- **Result:** **PRUNED, not whitened.** PCA: PC1 (54%) = rate/dollar level, PC2 (24%) = credit-vs-
  curve, PC3 (11%) = **pure VIX** — i.e. whitening would hand 54% attention to the rate level and bury
  VIX (the proven-useful factor) at 11%. Silhouette pruned 0.329 vs whitened 0.356 = noise → whitening
  buys no separation. Starting set: **[VIX, hy_spread, real_yield_10y, term_spread]** (max offdiag
  0.47), membership tunable in Step 3 by lift.
- **Settled by:** §3 metrics: *explained-variance / PCA loadings*, *silhouette*, *max off-diagonal corr*.

### Step 3 — Joint model GATE ✅ ❌
- **Problem:** Can a learned joint scalar (Mahalanobis / GMM / HMM) on the Step-2 matrix **beat
  VIX-alone** at forecasting forward realized vol — IN and OUT of sample?
- **What we did:** Fit all three; gate = forward-vol R². Then **walk-forward OOS** vs the *honest*
  comparator (VIX-alone, not the kneecapped ffill-ebp baseline).
- **Result ❌ FATAL:** (1) Even **in-sample**, maha LOSES to VIX-alone at every horizon (0.180 vs 0.301
  @ H=21); the J2 "pass" compared maha to a weak baseline. (2) **OOS, maha collapses to ~0**
  (0.027/0.006/0.001) while VIX holds (0.273/0.134/0.069). GMM/HMM failed outright. **R-c ML stage
  CLOSED.** For sizing: **VIX alone.**
- **Settled by:** §3 metrics: *forward-vol R²*, *walk-forward OOS R²*, *baseline-honesty rule*.

### Step 4 — Absorption Ratio (last lead candidate) ✅ ❌
- **Problem:** The shipped gate fires *during* a crisis; can the Absorption Ratio (Kritzman 2012, lit
  #1 cross-asset *pre-crisis* fragility signal) warn *before* one forms?
- **What we did:** Built AR on a clean 20-asset 2007+ panel. Tested fwd-return corr (AR2), rise-from-
  calm (AR3), param robustness (AR4). Then **Step-4b**: replicated Kritzman's ACTUAL test (ΔAR signal,
  market-peak target, ΔAR>+1σ rule, 51-industry universe, AR×Turbulence 2×2 grid).
- **Result ❌:** AR does NOT lead — **wrong sign** (+0.16/+0.28/+0.31 @ 1/3/6m, contrarian-bullish like
  VIX), rise-from-calm **−0.06**, robust across all 9 param sets. Faithful 2×2: the **CALM** quadrant
  has the **WORST** forward drawdown (−0.102) — opposite of the framework. Root cause: publication/
  in-sample bias (~2 events), window composition (Covid/2022 not coupling crises), and the anti-
  Kritzman truth that **crashes start from complacency, not visible coupling.**
- **Settled by:** §3 metrics: *fwd-return corr (sign)*, *rise-from-calm*, *param robustness sweep*,
  *quadrant forward-drawdown*.

### Step 5 — Strategic valuation timing 🟡 (designed, NOT run; verdict TBD)
- **Problem:** A DIFFERENT question/horizon — does an *expensive* market (CAPE / ERP) predict *lower
  long-run* (≥3y) returns? (Asness "Sin a Little" — small, trend-aware tilt, not a fast alarm.)
- **What we did (designed):** `scratch/valuation_panel.parquet` (Shiller+multpl, monthly 1881–2026).
  V1 Spearman corr vs fwd annualized TR by horizon; V2 within-trend control (is it just buy-after-
  crash?); V3 sin-a-little vs sin-a-lot vs buy&hold Sharpe; V4 robustness (SIN size, era).
- **Pre-registered bar:** PASS = monotone valuation→fwd-return AND `sin-a-little` Sharpe > buy&hold
  AND survives the momentum/within-trend control AND robust across SIN∈[0.1,0.33] & eras. Else FAIL.
- **Result: TBD** — cells written, not executed.
- **Cells:** `2026-06-25_step5_valuation_timing_cells.md`.

### Step 6 — Per-mechanism lead signals 🟡 (designed, NOT run; the strong open challenge)
- **Problem:** Steps 1–4 used an **event-AVERAGED single-signal** estimator — biased to the null when
  drawdowns are heterogeneous in mechanism (A=vol, B=rate, C=credit). So they only proved the NARROW
  claim "no single signal leads the *average* tail," not "no lead exists." Test the reframe: *different
  signals are dangerous in different regimes — learn which led each episode.*
- **What we'll do (pre-registered, frozen before forward look):**
  - **6a — controlled distributional screen** (lead generator, not verdict): `P(factor|pre-tail)` vs
    **matched** baseline, with **de-cluster + calm-start** controls, testing **tail-mass not mean**
    (KS/AD), k∈{21,42,63}. Folds momentum challenge in as candidate transforms (level/diff1m/diff3m).
  - **6b — signal-conditional walk-forward gate** (verdict): anchor on each signal *firing*, look
    *forward*, OOS, taxonomy frozen, multiple-comparison-corrected. PASS → Layer-B gate trigger; FAIL
    → "nothing leads" confirmed at a higher standard.
- **Result: TBD.** **Critical guardrail:** ~6–8 events × 7 signals = overfitting minefield; only OOS
  with a frozen taxonomy counts (the Kritzman lesson).
- **Design:** `2026-06-26_step6_per_mechanism_design.md`. **Cells (written, not run):**
  `2026-06-26_step6_per_mechanism_cells.md` (S6-0 frozen onsets/taxonomy → S6a screen → S6b OOS gate).

---

## 3. Metric glossary — definition · interpretation · gotcha

> Read this before challenging any result. Each entry: **what it is**, **how to read it**, and **the
> trap** that produces a false positive/negative.

### Forward-return correlation — `corr(metric_t, fwd_ret_{t→t+h})`
- **Def:** Pearson (or Spearman, valuation) corr between a signal at time *t* and the market return over
  the *next* h periods. Horizons used: 1m/3m/6m (=21/63/126 trading days), and ≥3y for valuation.
- **Read:** **Negative = leading risk signal** (high signal → low forward return). Positive = either
  irrelevant or **contrarian-bullish** (the danger-is-bullish-on-the-mean pattern of VIX/AR).
- **Trap 1 (sign):** A *positive* fwd-return corr for a "stress" factor (VIX, AR) does NOT mean it's
  useless — it means stress mean-reverts up; it's coincident, not leading. AR's +0.16 failed *because*
  a lead must be negative.
- **Trap 2 (overlap):** Daily, overlapping windows inflate |corr| and crush the effective sample size.
  The momentum challenge's −0.186 (daily/overlapping) became ≈−0.22 on a non-overlapping ~quarterly
  sample — comparable to ebp, not "stronger." **Always check non-overlapping before believing a daily
  corr.**
- **Trap 3 (leading vs coincident):** Compare `corr(signal, FWD ret)` against `corr(signal, PAST ret)`.
  If they're similar magnitude, the signal is coincident (still-elevated-from-last-time), not leading.

### Rise-from-calm — `B_rise_from_calm`
- **Def:** After (A) de-clustering tails (first onset of each cluster only) and (B) requiring the factor
  *below its own mean* k days pre-tail, does it *rise into* the tail? Measured as the conditional
  trajectory / its slope.
- **Read:** **>0 = genuine lead** (rises from calm before the event). **≈0 or <0 = no lead** — the raw
  "elevation" was persistence/clustering, not prediction.
- **The decisive control of the whole investigation.** S3c: ≈0 (factors). AR3: −0.06. This is what
  separates "elevated-and-persistent" from "leading." **Any new lead claim must pass this.**

### Incremental R² over VIX — `ΔR²`
- **Def:** `R²(target ~ VIX, X) − R²(target ~ VIX)`. Target = forward realized vol (sizing) or forward
  return (timing). Asks: does X add value *beyond* what VIX already explains?
- **Read:** A factor with a real univariate corr but ΔR²≈0 is a **VIX echo** — worthless. ebp earned
  its keep: +0.034 sizing, +0.088 timing (the only directional factor).
- **Trap:** Measured in-sample, ΔR² overstates. Must be confirmed OOS (Step 3: maha's +0.066 IS → ~0
  OOS).

### Forward realized vol R² (the SIZING gate)
- **Def:** R² of a candidate scalar predicting realized vol over the next h days. The metric the joint
  model was gated on.
- **Read:** Higher = better sizing signal. VIX is the champion (OOS ~0.27 @ H=21). **Any sizing
  candidate must beat VIX-alone OOS** — this is THE operational baseline, not the monthly 0.384.

### Walk-forward OOS R²
- **Def:** Fit on a trailing window, evaluate strictly on the next out-of-sample block; roll forward.
- **Read:** The ONLY R² that counts for a verdict. In-sample lift is assumed and ignored. Killed the
  joint model (maha 0.027 OOS vs 0.142 IS) and is the §3-bar for Step 6b.
- **Baseline-honesty rule:** compare against the *strongest fair* comparator (VIX-alone), never a
  kneecapped one (the ffill-ebp 0.133 baseline made maha look like a pass when it wasn't).

### Crisis-exclusion sign flip
- **Def:** Recompute fwd-return corr after dropping dot-com/GFC/Covid windows.
- **Read:** If the corr **flips sign** (ebp: −0.172 → +0.13), the signal is a **crisis-only tail
  switch**, not a continuous tilt → belongs in a threshold GATE, not a linear model.

### Monotonicity (tercile / decile / band)
- **Def:** Bin the signal into quantiles; check whether mean forward return declines monotonically.
- **Read:** A clean gradient = continuous factor (use linearly). A **flat-then-cliff** shape (ebp: flat
  deciles 0–7, drops at 8–9) = **tail switch** (use a gate at the cliff). est_prob: flat <30%, negative
  only >30%.

### PCA explained variance / loadings · Silhouette (Step 2)
- **Def:** PCA share of variance per component + factor loadings; silhouette = cluster-separation
  quality (higher = cleaner regimes).
- **Read:** **Variance ≠ usefulness.** VIX was only PC3 (11%) despite being the proven-useful factor →
  whitening (variance-optimal) would bury it. Silhouette tie (0.329 vs 0.356) ⇒ whitening buys nothing
  ⇒ PRUNE.

### Max off-diagonal correlation
- **Def:** Largest |corr| between any two factors in the chosen set. Proxy for residual redundancy.
- **Read:** Lower = more independent axes. Pruned set = 0.47 (acceptable). The rate bloc at 0.93–0.99
  is why decorrelation was mandatory.

### Quadrant forward-drawdown (Step 4 AR×Turbulence)
- **Def:** Mean forward 126d drawdown within each cell of the AR×Turbulence 2×2 grid.
- **Read:** The "FRAGILE" (hiAR/loTurb) cell should be worst if the framework works. It wasn't (−0.057
  ≈ baseline); **CALM was worst (−0.102)** → crashes start from complacency. Falsified the framework.

### Distributional tail-mass shift + KS/AD (Step 6a, designed)
- **Def:** Compare `P(factor | controlled pre-tail)` to `P(factor | matched random windows)` via the
  90th-pctl shift / right-tail mass and a KS or Anderson-Darling two-sample test.
- **Read:** A subtype-specific signal moves the conditional **tail**, not the **mean** — so test the
  tail. **Trap:** without de-cluster + calm-start + *matched* (not unconditional) baseline, the pre-tail
  window is autocorrelated with prior tails and EVERYTHING looks shifted (the S3b artifact). Lead
  generator only — never a verdict (n≈6–8 onsets).

---

## 4. The recurring failure mode (memorize this)

Across S3b, AR2/3, the momentum challenge, and Step-4b, the **same artifact** keeps producing false
"leads": **persistence + event clustering makes a coincident, mean-reverting stress factor look like it
warns ahead.** The standard defenses, in order:
1. **De-overlap / de-cluster** (one onset per stress episode).
2. **Calm-start condition** (factor below its mean pre-tail → must *rise into* the event).
3. **Non-overlapping sample** before trusting any daily correlation.
4. **Leading-vs-coincident check** (`corr` with FWD vs PAST return).
5. **Walk-forward OOS** with an honest baseline — the only thing that produces a verdict.

If a new lead claim hasn't passed 1–5, it hasn't been tested — it's been observed in-sample.

---

## 5. Artifacts (data the tests ran on)

| Artifact | Contents |
|---|---|
| `scratch/raw_factor_panel.parquet` | FRED factors: real_yield_10y, dxy_broad/major_legacy, bondvol_vxtyn. |
| `scratch/gz_ebp_monthly.parquet` | GZ Excess Bond Premium: `gz_spread`, `ebp`, `est_prob` (monthly 1973–2026). |
| `scratch/valuation_panel.parquet` | Shiller+multpl monthly 1881–2026: cape, earnings_yield, erp_cape, etc. |
| `data/market_data.duckdb` (read-only) | VIX, DGS10/2, HY spread, HYG/LQD, MOVE, SPY/QQQ + 36 cross-asset ETFs (AR). |
| Sourcing scripts | `scratch_source_factors.py`, `scratch_source_valuation.py`. |

> **Coverage cliffs (bind every multivariate step):** VIX/rates 1990+ · real-yield/HY 2003+ ·
> DXY-broad 2006+ · credit ETFs 2007+ · **MOVE 2021+ only** (dropped, single-regime). bondvol_vxtyn
> 2003–2020 only.
