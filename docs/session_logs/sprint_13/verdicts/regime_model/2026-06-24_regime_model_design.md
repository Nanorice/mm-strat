# Regime Risk Model — Design Record & Open Decision (2026-06-24)

> 📍 **Index:** `README_regime_research_map.md` — meta map of every step (problem→did→result→test)
> + metric glossary. Start there to look back or challenge a result.
>
> Sprint 13. Consolidates the M03 / 5-risk-factor investigation into a single design problem.
> Written to be taken away for a decision. The throughline: **the model's entire value is that it
> collapses many macro factors into ONE explainable number** (factor levels → regime score →
> sizing). Every design question below is judged by whether it preserves that chain.

---

## 1. What this model is FOR (the non-negotiable requirement)

The model must produce **a single scalar** with three properties:

1. **Explainable** — the number decomposes back to factor levels ("score is low because VIX is in
   its 95th percentile and credit is widening"). Not a black box.
2. **Regime-identifying** — the scalar (plus its factor decomposition) maps to a nameable market
   state: risk-on / neutral / stress / crisis.
3. **Sizing-actionable** — the regime maps to position size (research-confirmed use; see §2).

This chain — **factor levels → one score → regime → size** — is the product. Any redesign that
breaks the single-number collapse (e.g. independent per-factor outputs, or an opaque 7-factor PCA
the user can't read) **fails the requirement even if it scores better statistically.**

---

## 2. What the research established (closed findings)

These are settled and bound the design:

- **The model is a COINCIDENT vol/stress meter, not a drawdown predictor.** Across event-study,
  lead-lag sweep, and conditional tests: no factor leads QQQ drawdowns. `corr(z_vix, fwd return)`
  is *positive* and rises with horizon — danger signals are contrarian-bullish on the mean.
- **Its real, proven use is SIZING.** `corr(z_vix, realized vol over next H days)` peaks **0.67 at
  H=5–10d**, monotone across deciles (ann. fwd vol 9.4% → 33.7%). It forecasts *dispersion*, not
  direction → a vol-targeting / position-sizing signal, horizon ≈ 1–2 weeks.
- **The current aggregation is sound, NOT a VIX proxy.** `weighted_z = Σ(z·W)`,
  `W={z_vix .25, z_hy .25, z_term .15, z_trend .15, z_slope .20}`. Variance-share of weighted_z:
  **z_vix 29.5%, z_hy 24.8%, z_slope 21.7%, z_trend 19.1%, z_term 4.9%.** Balanced. ("Looks like
  VIX" = factor co-movement in stress, not weighting — z_trend corr with weighted_z 0.87 > z_vix.)
- **z_term is near-inert (4.9% share, decorrelated from all others)** — candidate to drop/re-spec.
- **A regime IS the joint/correlation structure.** Factor corr matrix shows real structure
  (z_trend–z_slope 0.79, z_vix–z_trend 0.67, z_term ⟂ everything). PCA: PC1 risk-on/off,
  PC2 credit-vs-curve, PC3 ≈ pure net-liquidity. 4 KMeans clusters = 4 interpretable, persistent
  regimes (incl. a clean Mar-2020 crisis cluster). **→ regime identification is inherently
  multivariate; it cannot come from factors treated independently.**

---

## 3. The current model (baseline) and its ONE real flaw

**Architecture:** per-factor **10yr (2555d) ROLLING z-score** → weighted sum → 5yr rolling
percentile → 6 discrete exposure bands (0.15–1.00); veto: any z≥2.0 → exposure 0.15.

This already does what the user wanted ("z-score the bases, weight, one number"). It is a unified,
explainable, single-number regime/sizing model. **It is not broken.** It has one structural flaw:

- **Temporal amnesia.** The rolling window means old shocks age out. Covid leaves the z-baseline
  ~2030; GFC already has. Once the worst stress exits the window, a future VIX=40 z-scores as more
  extreme than it should, and the veto (z≥2) drifts. **The yardstick slides.**

Everything below is about fixing amnesia **without breaking the single-number chain.**

---

## 4. The tangle of sub-problems (why this isn't one clean fix)

Four distinct issues got conflated in discussion. Separating them is the key insight:

| # | Problem | What it is | What does / doesn't fix it |
|---|---------|------------|----------------------------|
| P1 | **Temporal amnesia** | rolling μ/σ forgets old shocks; adding "normal" years dilutes σ so fixed extremes z-score weaker over time | fixed / expanding reference fixes; rolling doesn't |
| P2 | **Cross-factor comparability** | VIX-z=2 ≠ MOVE-z=2 in stress meaning (different tail shapes / horizons) | z-scoring does NOT fix this; anchoring does NOT fix this |
| P3 | **Secular drift** | rate/liquidity factor *levels* shift structurally (ZIRP vs now) → a fixed μ mis-centers them | per-factor reference choice, OR transform to stationary |
| P4 | **Short history** | MOVE (2021+) has no crisis in its native data → no honest tail | no normalization trick manufactures missing crisis data |

**Corrections to earlier (wrong) claims in this thread, recorded for honesty:**
- "Anchored z solves the VIX-vs-MOVE horizon difference" — **WRONG.** Anchoring fixes P1 (temporal),
  not P2 (cross-factor). Different problems.
- "Windows need not align, so drop the 10yr constraint and add any factor" — **TRUE for a sizing
  SUM, FALSE for a regime identifier.** A regime is read from factors' *joint* position on the same
  day; if each factor uses a different reference ruler, the joint position is meaningless. A regime
  identifier REQUIRES a shared/common reference → short-history factors ARE constrained.

---

## 5. The central tension (this is the crux of the decision)

Two requirements pull in opposite directions:

- **Economically:** mean-reverting factors (VIX, HY) want full-history references (keep crisis
  memory); drifting factors (rates, liquidity) want recent references (what's "normal" changed). →
  *different references per factor.*
- **For regime identification:** all factors must answer the SAME question against the SAME
  reference, or their joint position (= the regime) is incoherent. → *one shared reference.*

**You cannot have per-factor-optimal references AND a coherent joint regime via different windows.**
The honest resolutions:

- **(R-a) One shared reference for all** (e.g. fixed 2005–2022 window). Coherent regime space; but
  mis-centers the drifting factors (P3 unfixed).
- **(R-b) Stationarize first, then shared reference.** Transform drifting factors into
  mean-reverting forms (e.g. term-spread *change* or deviation-from-slow-trend) so a single
  full-history reference is valid for ALL factors. Keeps crisis memory (P1), keeps coherent joint
  space, fixes drift (P3). **Cleanest — turns the windowing problem into a feature-definition
  problem.** Does not address P2/P4 (short-history factors).
- **(R-c) Two-stage:** per-factor appropriate normalization → a *learned* joint model
  (PCA/GMM/clustering) re-derives the common space. Most flexible, but the joint stage risks
  becoming the black box that violates §1.1 (explainability).

---

## 6. The usage constraint that rules options in/out

The user's framing makes §1 sharp: the output is **one number, explainable via factor-level
distribution / z-score, → regime → sizing.** This **rules out**:

- ✗ **Per-factor independent level→outcome maps** — no single number, no regime (regime needs the
  joint structure), and you'd need a fusion rule. Good for sizing alone, fails regime-ID.
- ✗ **Raw 7-factor PCA as the output** — PC1 is a fine *internal* axis, but "your size is 0.6
  because PC1 = −1.4" is not explainable to a human in factor terms. Black box. Fails §1.1.

It **keeps** the current shape (weighted z-sum → score), and asks only: *fix the reference
distribution so the single number stops forgetting shocks, without losing explainability.*

---

## 7. Options, organized by the problem each solves

**Reference distribution (fixes P1 temporal amnesia) — pick ONE base:**
- **A. Rolling z** (status quo) — forgets. Reject for the stated goal.
- **B. Expanding/full-history z** — never forgets, BUT each normal year dilutes σ (the user's exact
  concern); old shocks z-score progressively weaker.
- **C. Fixed-window z** — μ/σ frozen on a crisis-containing range. Stops dilution; one inspectable
  judgment call; mis-centers drifting factors unless combined with R-b.

**Drift handling (fixes P3) — needed if any rate/liquidity factor is in:**
- **D. Stationarize the drifting factors** (change / detrend) so one full-history reference is valid
  for all. Enables R-b. Recommended.

**Dilution mitigation (the user's "calibrate afterwards" idea) — addresses P1 from the OUTPUT side:**
- **E. Calibrate score→regime→size on STRESSED outcomes, not on the z magnitude.** Even if σ-dilution
  makes the z drift, the *mapping* from "this score" to "this forward-vol bucket / this size" is fit
  on history that includes crises, so the action stays correct. This is the user's insight: for a
  sizing/regime model, what must be stable is the **score→action map**, which can be calibrated once
  on stressed history independent of the normalization. Compatible with B or C.

**Cross-factor comparability (fixes P2) — only if mixing different-tail factors:**
- **F. Per-factor percentile** instead of raw z for the tails, so "95th pct" = equal rarity across
  factors. (Aggregate already uses a rolling percentile; this moves it per-factor.)
- **G. Per-factor veto calibration** — set each factor's crisis trigger from its own stressed
  history, so a shallow-tail factor can't over-trigger the z≥2 veto.

**Short-history factors / MOVE (P4):**
- **H. Test MOVE on 2021+ slice FIRST** — measure incremental sizing signal before any backfill.
- **I. Acquire pre-2021 MOVE externally** — obtainable (MOVE ~1988+) but NOT via current pipeline:
  different vendor, no ingestion path, no validation, rebasing risk, ongoing maintenance. DQ/landmine
  cost (cf. the orphaned net-liq rows just deleted). Only if H proves it's worth it.

---

## 8. Recommendation

**Keep the single-number, explainable architecture. Fix amnesia via a fixed/expanding shared
reference on STATIONARIZED factors, and make the score→size map the calibrated, stress-aware layer.**

Concretely: **R-b + D + E**, i.e.
1. **Stationarize** drifting factors (rates/liquidity → change or deviation-from-trend) so they're
   mean-reverting like VIX/HY (D).
2. **One shared full-history (or fixed crisis-containing) reference** z-score across all factors —
   coherent joint space, never forgets (C or B).
3. **Keep `weighted_z` → score → regime** as the explainable single number (unchanged shape, §1
   preserved).
4. **Calibrate the score→regime→size map on stressed history** (E) — this is where the user's
   "we just need to know how each factor behaves in stress" insight lives; it makes the action
   robust to any residual σ-dilution.
5. **Defer P2/P4:** only adopt per-factor percentile/veto-calibration (F/G) and MOVE (H→I) IF new
   different-tail factors are actually added. Don't pay that complexity for the existing 5.
6. **Drop or re-spec z_term** (4.9% share, inert) while touching the factor set.

This preserves everything the model is for, fixes the one real flaw (amnesia), resolves the
per-factor-vs-joint tension cleanly (via stationarization, not via mismatched windows), and keeps
the door open for new factors without committing to a black box.

**Smallest first step (low-risk, high-information):** prototype B/C vs A on history — same dates,
compare regime labels + veto-firing + the score→fwd-vol map. See if a fixed/expanding reference
actually changes the model's calls before committing to the larger refactor.

---

## 9. Open question left for the user

The architecture hinges on one thing only the user can set:

> **Is the regime identifier the primary model, with sizing as a downstream read-off? Or are
> "regime ID" and "sizing" two separate models?**

- If **regime-ID primary** (assumed above): build the unified §8 design; sizing reads off the score.
- If **separate**: sizing could be the simpler per-factor thing; regime-ID is its own unified build.
  But this risks two models to maintain — the very thing the consolidation was trying to avoid.

---

## Appendix A — Evidence base (verified test results, 2026-06-23/24)

All numbers below were computed against `data/market_data.duckdb` (QQQ 2010+, 80 merged
onset-anchored bearish events; tables `t2_regime_scores`, `t2_risk_scores`, `price_data`).
Cell artifacts: `2026-06-23_{regime_conditional,unified_factor,regime_merge_tiers}_cells.md`.

### A1. No leading signal (event study, onset-anchored ±63d)
PRE / EVENT / POST means vs unconditional baseline; every factor flat into onset, snaps at day 0.

| indicator | PRE-63 z | EARLY-10 z | JUMP-day z |
|---|---|---|---|
| m03_score | +0.01 | +0.01 | −1.00 |
| m03_pillar_trend | +0.06 | +0.07 | −1.19 |
| m03_pillar_risk | −0.04 | −0.02 | −0.79 |
| weighted_z | 0.00 | −0.09 | +1.12 |
| z_vix | +0.05 | −0.02 | +1.53 |
| z_hy | −0.02 | −0.09 | +0.61 |
| z_term | −0.08 | −0.08 | +0.10 |
| z_trend | 0.00 | −0.11 | +1.10 |
| z_slope | +0.04 | −0.02 | +0.35 |
| target_exposure | +0.02 | +0.06 | −0.84 |

Read: PRE/EARLY all ≈ 0σ (no lead); JUMP-day large (coincident). **The original "lead" was a
de-overlapping artifact** (50% of unmerged "pre-crash" days sat inside a prior event's post-window).
Baseline matters: vs a "far-from-event" control (n=171) z_vix PRE looked +2.95, but that control is a
survivorship trap (only deep-calm days survive). Vs the honest unconditional baseline (n=4139): +0.07.

### A2. Lead-lag sweep — falsifies "signal fired too early"
`corr(indicator_t, QQQ fwd return over next H)`. A leading bear signal would be NEGATIVE and grow with
H. Instead:

| indicator | H=5 | H=21 | H=63 | H=126 | H=252 |
|---|---|---|---|---|---|
| z_vix | +0.09 | +0.21 | +0.30 | +0.30 | +0.25 |
| weighted_z | +0.09 | +0.19 | +0.25 | +0.28 | +0.36 |
| m03_score | −0.07 | −0.13 | −0.19 | −0.17 | −0.17 |

z_vix is positive and RISING with horizon — the opposite of a lead. (m03 negative = it cuts into
rallies, wrong sign for timing.) Forward-drawdown corr is only negative at H≤10 (coincident tail), decays to ~0 by 63d.

### A3. Conditional outcomes — danger is contrarian-bullish on the mean, fatter tail
When each signal flags its worst decile/quartile:

| signal (H=21) | mean fwd | base | P5 | base P5 | mean MDD | base MDD |
|---|---|---|---|---|---|---|
| z_vix top decile | +4.0% | +1.6% | −8.5% | −7.4% | −3.8% | −2.9% |
| weighted_z top decile | +3.2% | +1.6% | −10.3% | −7.4% | −4.2% | −2.9% |
| veto_flag True | +2.1% | +1.6% | −9.6% | −7.4% | −3.9% | −2.9% |

Higher mean (vol risk premium) + fatter left tail = **signals dispersion, not direction.** `veto_flag`
is the exception worth watching: P(neg) 36% @63d vs 24% base with no mean lift.

### A4. SIZING proof — z_vix predicts forward realized vol, horizon ≈ 1–2 weeks
`corr(z_vix_t, realized stdev of next-H returns)`:

| H | 2 | 3 | 5 | 10 | 21 | 42 | 63 | 126 |
|---|---|---|---|---|---|---|---|---|
| corr | 0.53 | 0.61 | **0.67** | 0.67 | 0.61 | 0.51 | 0.45 | 0.38 |

Peaks H=5–10. Monotone across deciles: ann. 5d fwd vol **9.4% (dec0) → 33.7% (dec9)**, every step
increasing. Clean sizing signal; useless as direction.

### A5. Aggregation audit — balanced, NOT a VIX proxy
`weighted_z = Σ(z·W)` reconstructs stored column exactly (corr 1.0). Variance-share of weighted_z:

| z_vix | z_hy | z_slope | z_trend | z_term |
|---|---|---|---|---|
| 29.5% | 24.8% | 21.7% | 19.1% | **4.9%** |

(My earlier "f_vix 93.5%" was an ERROR — measured raw `f_*` columns, whose magnitude is dominated by
VIX on UNITS not weight. Retracted.) "Looks like VIX" = co-movement: z_trend corr with weighted_z 0.87
> z_vix 0.78.

### A6. Factor correlation structure (= the regime signal)
```
         z_vix  z_hy  z_term  z_trend  z_slope
z_vix     1.00  0.41   -0.15     0.67     0.48
z_hy      0.41  1.00    0.00     0.39     0.13
z_term   -0.15  0.00    1.00     0.10     0.14
z_trend   0.67  0.39    0.10     1.00     0.79
z_slope   0.48  0.13    0.14     0.79     1.00
```
z_trend–z_slope 0.79, z_vix–z_trend 0.67; **z_term decorrelated from all** (why its share is 4.9%).

### A7. PCA on unified 7-factor set (5 risk z + 2 unique M03 pillars)
Explained var: **[0.46, 0.18, 0.13, 0.11, 0.07, 0.04, 0.01]**. Loadings:
- **PC1 (46%) = risk-on/off** — z_trend 0.54, z_slope 0.44, z_vix 0.40
- **PC2 (18%) = credit-vs-curve** — z_hy +0.47 vs z_term −0.61
- **PC3 (13%) ≈ pure net-liquidity** — m03_pillar_liq 0.88 (independent axis the 5-factor model lacks)

### A8. KMeans(4) → interpretable, persistent regimes
| cluster | n | z_vix | z_trend | liq | fwd_vol | fwd21 | note |
|---|---|---|---|---|---|---|---|
| calm/weak-trend low-liq | 1461 | −0.32 | −0.49 | low | 0.151 | +1.1% | |
| risk-OFF high-vol | 720 | +0.96 | +1.19 | mid | 0.280 | +2.5% | run ~11d |
| calm high-liq | 1909 | −0.34 | −0.59 | high | 0.139 | +1.6% | best fwd |
| **CRISIS** | 29 | +5.99 | +3.70 | max | 0.722 | +11.9% | all Mar–Apr 2020, run ~15d |

Run-lengths 6–15d → regimes persist, not noise. Position in factor space = market condition.

### A9. M03 vs risk-model overlap (the "don't naively merge" evidence)
- `corr(m03_score, weighted_z) = −0.57`; danger-flag Jaccard **0.45** (disagree on ~55% of flags).
- Pillar map: `m03_pillar_trend ≈ −0.88 z_trend` (redundant); `m03_pillar_risk ≈ −0.66 z_vix` (partial);
  **`m03_pillar_liq ≈ 0` everywhere (orthogonal net-liq)**.
- Incremental fwd-vol info: weighted_z keeps **+0.42** after removing m03; m03 keeps −0.19 after
  removing weighted_z → both carry independent signal.

### A10. M03 in M01 — NOT a drag (existing walk-forward ablation)
`models/m01_binary/.../ablation_summary.json`, baseline Sharpe 1.045. Δ Sharpe when group dropped:
Core_Volume −0.57 > Fundamentals −0.51 > Momentum_RS −0.41 > Moving_Averages −0.26 >
Categoricals −0.24 > **M03_Regime −0.22** > Fast_Alphas −0.12 > Technical_Oscillators +0.00 >
**Volatility_Ranges +0.13** (dropping it HELPS). → M03 is a net-positive mid-pack contributor.
Real prune candidates: Volatility_Ranges, Technical_Oscillators.

### A11. Tier calibration — monotone but mis-placed cut points
M03 fixed 0/25/50/75 bins → fwd vol 0.32/0.24/0.15/0.12 (monotone) but day counts 221/916/2125/878
(unbalanced; score is clumped, median 61, p10 33). Decile scan: fwd vol cliffs in bottom ~20%
(m03≈23→31%, ≈48→17%), **FLAT from ~50→90 (17%→12%)** — score only discriminates below ~40–50.
→ recalibrate to empirical-percentile / 3-tier (Danger <40 / Neutral 40–70 / Benign >70).
target_exposure ladder (0.15/0.35/0.75–0.85/1.0) already monotone + well-spaced — leave it.

### A12. Data availability for new factors (10yr-z constraint binds)
- 🐛→✅ net_liquidity orphan rows (frozen 2026-02-19) DELETED; M03 derives it live, fresh to 2026-06-22.
- **DFII10 (real yield):** FRED, 2003+, best add (one line in config.FRED_SERIES).
- **DXY (UUP 2007+):** corr +0.13 vs z_vix → independent. **Credit HYG/LQD (2007+):** −0.25 vs z_hy.
- **MOVE:** in DB but **2021+ only (1318d)** → too short for 10yr z; reject pending P4 resolution.
- **VIX term-structure / breadth:** not ingested; defer.

---

## 10. Post-Review Addendum (R-c Pivot)

> **Step-1 EDA results are recorded in `2026-06-24_step1_eda_findings.md` (same folder).** That doc
> holds the data behind the decisions below: factors are coincident (not leading); the GZ Excess Bond
> Premium is the one weak-but-real lead; §9 resolves to two-signals/two-jobs; success metric = beat a
> 2-factor (VIX, ebp) regression. Read it for the evidence; this section for the design direction.

Based on further discussion, the design direction has pivoted towards **R-c (Two-stage: per-factor normalization → learned joint model)** for the following reasons:

1. **The Cyclicality of Macro Factors:** Stationarizing the 10-year yield (e.g., via short-term differencing) would destroy the underlying business cycle signal. It is better to use a rolling window that captures the cycle natively (e.g., 5-10 years) rather than forcing it into a stationary mold.
2. **Avoiding "Molding" Errors:** Forcing all factors onto a single shared yardstick introduces statistical errors for non-conforming factors. R-c allows each factor to be normalized according to its own economic reality (e.g., full-history for VIX, 5-year rolling for Rates, 2-year for MOVE).
3. **Machine Learning as the Unifier:** Because the factors will be on different "rulers," a simple weighted sum is invalid. An unsupervised model (PCA, GMM, or HMM) will be used to learn the joint space and output a **single scalar metric** (e.g., Mahalanobis distance from normal, or Probability of Crisis) depicting the market status.

### Decisions taken in review (2026-06-24) — these OVERRIDE earlier sections

- **§1.1 explainability is RELAXED, by decision.** Earlier sections treat "the scalar decomposes
  back to factor levels" as non-negotiable and use it to reject R-c (§5, §6). That veto is lifted.
  Rationale: a single number that explains *every* situation may not exist; if the learned joint
  model is **statistically better**, explainability is not grounds to reject it. R-c is now a valid
  candidate. (§1.1 stays a *preference*, not a gate.)
- **Consequence — the only remaining gate is "statistically better," so a success metric is
  REQUIRED.** With explainability gone, R-c has no rejection criterion until a concrete target is
  set. The honest incumbent to beat is §A4: `corr(scalar, realized vol over next 5–10d)`,
  **z_vix alone = 0.67**. If the learned scalar can't beat a single-factor baseline on the chosen
  target, the relaxation bought nothing.
- **Success metric: DEFERRED to the EDA.** Not committed now — the factor distributions seen in
  step 1 inform what target is even achievable, and whether ML earns its keep at all.
  **Therefore: proposing the success metric is an explicit DELIVERABLE of the EDA phase.** Step 3
  (joint model) must not begin until step 1 hands over a pass/fail target.
- **§9 (regime-ID primary vs. sizing+regime as two models): DEFERRED to the EDA.** No prior answer;
  the EDA decides. R-c implicitly assumes regime-ID primary — if the EDA shows sizing alone suffices
  (a single factor already gives 0.67 fwd-vol corr, §A4), the whole ML stage may be unnecessary.

### The Revised Roadmap
0. **Source factors:** ingest the additional factors before any analysis — DFII10 (FRED, one config
   line), DXY/UUP, HYG/LQD, MOVE (§A12). MOVE remains 2021+ only (P4 unresolved); carry it through
   EDA on its native slice but do not let its short history gate the others.
1. **Factor-Level EDA (raw, full-horizon) — deliberately NOT a re-run of §A1.** §A1–A3 studied
   *transformed/derived* columns over QQQ-2010+ and answered "does the factor *lead* events" (no).
   This step studies the **raw, non-transformed** factors over their **whole available history**, and
   answers a *different*, distributional question: per-factor tail shape, stationarity,
   autocorrelation, cyclicality, and how each behaves around extreme market moves *on its own ruler*.
   This is the intuition the prior (transformed, short-window) study did not provide. **Deliverables:
   per-factor lookback/window choice, normalization choice, AND a proposed step-3 success metric.**
2. **Cross-factor comparability (P2) — explicit decision step.** Because factors will be on different
   rulers (full-history VIX vs. 5yr rates vs. 2yr MOVE), the joint model does NOT automatically
   escape P2 (§4): PCA/Mahalanobis over mismatched references still yields an incoherent joint space.
   Decide here the **common space the ML operates in** (e.g. per-factor percentile → uniform ranks,
   or a shared standardization applied post-normalization). "ML will figure it out" is not an answer.
3. **Joint Model Prototyping:** feed the comparability-resolved factors into a joint model
   (PCA/GMM/HMM) to collapse the dimensions into a single market-status scalar (Mahalanobis from
   normal, or P(crisis)). **Gated by the step-1 success metric** vs. the §A4 single-factor baseline.
4. **Outcome Calibration:** once the joint metric clears the gate, calibrate the final sizing map on
   the empirical forward volatility of that metric (§7-E).
