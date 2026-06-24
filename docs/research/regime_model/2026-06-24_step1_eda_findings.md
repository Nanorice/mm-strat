# Regime Model — Findings & Decision Log: Steps 1–3 (2026-06-24)

> Companion to `2026-06-24_regime_model_design.md` (the design/decision record) and
> `market_regime_literature_review.md` (the survey). This document records the **thinking process,
> the data behind each conclusion, and the gate to the next step** for the full R-c roadmap
> (§10 of the design doc) — Step 1 (factor EDA), Step 2 (comparability/P2), Step 3 (joint model gate).
> Cell code in `docs/session_logs/sprint_13/2026-06-24_*_cells.md`; raw artifacts in `scratch/`.
>
> ## ⭐ FINAL VERDICT (Steps 3 & 4, validated): ship the simple thing.
> **Final model: VIX-for-sizing + est_prob-gate-for-crisis. No pre-crisis warning layer, by evidence.**
> - *Joint model (Step 3):* GMM/HMM failed the gate; Mahalanobis passed in-sample only and collapsed
>   to ~0 out-of-sample (walk-forward). VIX alone beats every joint scalar, IS and OOS. R-c ML closed.
> - *Pre-crisis lead (Step 4):* the Absorption Ratio — the literature's #1 fragility signal — was
>   tested and ALSO does not lead (wrong-sign fwd corr; rise-from-calm −0.06; robust across params).
> - *Conclusion:* nothing leads equity tails on this universe, tested against the best academic
>   candidate. Simplest validated model wins. The rest of this doc is the evidence trail.
>
> **The throughline:** characterize each raw factor on its OWN ruler, learn whether it LEADS or only
> COINCIDES, decorrelate, then GATE any joint model on beating a simple baseline. The discipline was
> to find the simplest model that works — and the answer turned out to be very simple.

---

## TL;DR — what Step 1 established

1. **The raw factors are COINCIDENT stress meters, not leading indicators** — confirmed on our data,
   robust to de-overlapping and calm-start controls. Nothing in {VIX, HY spread, term spread, real
   yield, DXY, MOVE, credit ratio} warns ahead of an equity tail; they confirm at the event.
2. **The literature's "credit leads" claim is real but rests on a DIFFERENT metric** — the
   Gilchrist-Zakrajšek **Excess Bond Premium (ebp)**, not raw HY OAS. When we sourced the actual
   ebp and tested it the way the papers do (monthly, broad market), it DOES lead — but **weakly**
   (corr −0.17 on SPY/3m).
3. **The credit signal survives an incremental-value test** (not redundant with vol): controlling
   for VIX it adds **ΔR²=+0.034 to forward-vol (sizing)** and **ΔR²=+0.088 to forward-return
   (timing)** — the ONLY factor here carrying directional info. **But (S3e) the timing edge is
   CRISIS-ONLY:** drop dot-com/GFC/Covid and the corr flips from −0.17 to **+0.13**. It's a tail
   switch, not a continuous tilt — concentrated in the top ebp decile / est_prob >30%.
4. **Use `est_prob` (Fed recession probability), not raw ebp**, as the timing signal — it dominates
   at every horizon (−0.20/−0.23 @ 3m/6m) and is already a calibrated probability (S3e Q1).
5. **The factor set collapses to ~2 independent axes** (risk-off: VIX/HY; rates/dollar level) plus
   the orthogonal credit/recession signal. A naive weighted sum or raw PCA would re-measure the rate
   level several times → P2 (decorrelation) is mandatory.
6. **Decision (§9 resolved by evidence):** a **two-layer** model — a continuous **vol-sizing core**
   (where the joint ML operates) + a rule-based **crisis gate** (`est_prob > ~30%`) sitting OUTSIDE
   it. NOT one explainable scalar. Success metric: **beat a 2-factor (VIX, ebp) regression** (R²
   0.384 sizing / 0.097 timing) — if the ML can't, ship the 2-factor model + the gate.

---

## Method recap (what was held fixed)

- **Panel:** raw, non-transformed factor LEVELS, full available history. Deliberately NOT the
  transformed `z_*`/`m03` columns of the prior event-study (design doc §A1–A11), which were
  QQQ-2010+ and already closed the "does the aggregate lead" question.
- **Sources:** FRED→`scratch/raw_factor_panel.parquet` (real_yield DFII10, DXY broad/legacy, VXTYN);
  DuckDB `macro_data`/`price_data` for VIX, DGS10/2, HY spread, HYG/LQD, MOVE. Nothing written to the
  DB or `config.py` — pure sourcing.
- **Coverage cliffs (bind every multivariate step):** VIX/rates 1990+ · real-yield/HY 2003+ ·
  DXY-broad 2006+ · credit ETFs 2007+ · **MOVE 2021+ only** (the P4 short-history problem).

---

## Step-by-step findings

### S1 — Distributions: which ruler each factor needs

**Observed:** VIX, hy_spread, MOVE are strongly right-skewed & fat-tailed (tail = stress).
real_yield_10y and the rate factors are **bimodal** — a ZIRP cluster (~0) and a post-Covid cluster
(~+2) visibly separated in the histogram.

**Why it matters:** fat-tailed factors should be normalized by **percentile/rank** (so "95th pct" =
equal rarity across factors, design §7-F), not raw z. The bimodality of real_yield is the first clue
that it is regime-switching, not a clean single-distribution factor.

**→ leads to S2:** is that bimodality "drift" (needs a rolling ruler) or two stationary regimes?

### S2 — Stationarity: mean-reverting vs. drifting (the lookback decision)

**Observed:** VIX/hy_spread mean-revert (flat rolling mean, finite half-life). real_yield, DGS10,
dxy_broad drift globally (rolling mean wanders, no fixed center).

**Subtlety caught (S2b):** a single full-history ADF is **unreliable on a bimodal/regime-switching
series** — it can't tell a unit root from two stationary regimes. So S2b tests stationarity *within*
a rolling 5yr window: a factor can be mean-reverting LOCALLY while drifting GLOBALLY. That distinction
IS the design §10 reason-#1 decision.

**Why it matters / decision:** confirms the §10 instinct — drifting rate factors need a **rolling
lookback that captures the cycle, NOT differencing** (differencing would destroy the business-cycle
signal). This is the case for R-c's per-factor normalization over R-b's single stationarized ruler.

**Note:** the S2 rolling-mean *plot* originally rendered as shattered fragments — a BUG, not signal:
`panel` has an outer-joined index with NaN holes (no ffill, by design), so `rolling(252)` counted
index rows and any window touching a NaN returned NaN. Fixed by `dropna()` per factor before rolling.
(Recorded because the same gotcha will recur in any rolling op against `panel` in Step 2.)

### S3 — Coincident stress levels (the per-factor veto calibration)

**Observed (conditioning each raw factor on QQQ worst-5% days, full history):** VIX/HY/MOVE sit at
high percentiles of their own distribution on tail days; rate factors barely move; credit_ratio falls
(risk appetite down). This gives each factor's "stress level on its own ruler."

**Why it matters:** feeds the per-factor veto (§7-G) — a factor whose tail-day median is only its
~60th pctl has a *shallow* stress signature and must not share a fixed z≥2 veto with a fat-tailed one.

**Caveat stated up front:** S3 is COINCIDENT by construction — a level study, not a prediction claim.
The prediction question is S3b/c.

### S3b — The "alerting" test: are factors elevated BEFORE the tail?

**Observed:** VIX and hy_spread are **already at z≈+0.62 a full 21 days before** the tail, rising to
~+0.9 by t−1, VIX jumping to +1.3 at t0. credit_ratio/term_spread flat-to-wrong-way.

**The apparent contradiction:** on its face this says VIX & credit LEAD — but design §A2 found
`corr(z_vix, fwd_ret)` is POSITIVE and rising (the opposite of a lead). Both can't be "leading."

### S3c — Resolver: de-overlap + calm-start control

**Observed:** `B_rise_from_calm ≈ 0` across factors — once we (A) keep only the first tail of each
cluster and (B) require the factor to start BELOW its mean 21d earlier, the t−21 elevation **vanishes**.

**Conclusion:** the S3b "lead" was **autocorrelation + event clustering**, not prediction. Tail days
cluster (Mar-2020 = dozens within weeks); for a clustered tail, "t−21" lands inside a prior tail's
stress window, and VIX/HY are persistent (S2 half-life = weeks). **Elevated-and-persistent ≠ leading.**
→ On our raw daily factors vs. QQQ daily tails: **coincident, confirmed.** Consistent with §A1/§A2.

**→ Why move on, not stop:** this only falsifies *our exact test*. The literature's "credit leads"
might rest on a different measurement. Before concluding "no lead for us," test the literature's
ACTUAL claim (S3d) — otherwise we'd be rejecting a strawman.

### S3d — Reconciling with the literature: the GZ Excess Bond Premium

The "credit leads by 2–4 weeks" headline traces to **Gilchrist & Zakrajšek (2012)**. Five concrete
differences between their test and our S3b/c, each pushing toward "their lead is real but not the
thing we tested":

| # | Their test | Our S3b/c | Direction |
|---|---|---|---|
| 1 METRIC | **GZ Excess Bond Premium** (spread w/ default-risk component REMOVED = pure risk-appetite residual) | raw HY OAS (total) / HYG-LQD ratio | refined > total |
| 2 FREQ | monthly | 21 daily bars | monthly less noisy |
| 3 TARGET | recessions (`est_prob`) | QQQ equity tail days | different event |
| 4 INDEX | broad market | QQQ (tech/vol-tilted) | broad shows it more |
| 5 TEST | predictive regression, decades of obs | ~15–25 onset events | power |

**Sourced** the real series: Fed FEDS Notes `ebp_csv.csv` (Gilchrist-Zakrajšek), **monthly 1973–2026**,
columns `gz_spread` (total) · `ebp` (excess premium = the leading residual) · `est_prob` (recession
prob). Saved to `scratch/gz_ebp_monthly.parquet`. Note `corr(ebp, our hy_total)=0.89`,
`corr(gz_spread, hy_total)=0.97` — ebp IS measuring something our HY spread doesn't fully capture.

**Result — `corr(metric_t, FORWARD market return)`, negative = leading risk signal:**

| metric | QQQ 1m | QQQ 3m | QQQ 6m | SPY 1m | SPY 3m | SPY 6m |
|---|---|---|---|---|---|---|
| gz_spread | −0.065 | −0.086 | −0.067 | −0.103 | −0.161 | −0.144 |
| **ebp** | −0.081 | −0.108 | −0.103 | −0.113 | **−0.172** | −0.158 |

**Read:** signs are now all NEGATIVE (unlike raw daily VIX/HY's positive in §A2) → ebp genuinely
carries a leading-risk signal our raw factors don't. The effect is **stronger on SPY than QQQ**
(−0.172 vs −0.108) — confirming difference #4 (QQQ's tech/vol tilt masked it). **But the magnitude is
tiny** — strongest is r²≈3%. The literature is directionally right; the effect is real but weak.

### S3d-incr — Does ebp add value BEYOND vol? (the decision-grade test)

A −0.17 that's subsumed by vol is worthless; one orthogonal to vol is a keeper. Tested incremental R²
controlling for VIX (monthly, n=399, 1993–2026):

| target | VIX uni-corr | ebp uni-corr | VIX-only R² | +ebp joint R² | **ebp ΔR²** | ebp coef p |
|---|---|---|---|---|---|---|
| **fwd realized vol** (sizing, §A4) | +0.59 | +0.51 | 0.350 | 0.384 | **+0.034** | <0.001 |
| **fwd 3m return** (timing) | +0.10 | −0.17 | 0.010 | 0.097 | **+0.088** | <0.001 |

**Conclusion — ebp earns its keep on BOTH jobs:**
- **Sizing:** +0.034 incremental R² (~10% relative lift) over vix-only, coef significant → ebp is a
  meaningful *second* sizing input, not just a vix echo.
- **Timing:** vix alone is useless for direction (R²=0.01, confirming §A2's contrarian-bullish vix);
  ebp nearly **9×'s** the timing R² (0.010→0.097). ebp is the ONLY factor here that predicts direction.
- They are **orthogonal jobs**: vol forecasts dispersion (+0.59), ebp forecasts direction (−0.17).
  Complementary, not competing.

### S3e — GZ deep-dive: est_prob vs ebp, and WHERE the lead lives

Two follow-ups the ebp result demanded. Both change how the overlay should be built.

**Q1 — does `est_prob` (Fed recession probability) beat `ebp` as the overlay signal? YES, modestly.**
Univariate corr with forward SPY return (n=396, 1993–2025):

| metric | fwd_1m | fwd_3m | fwd_6m | fwd_vol |
|---|---|---|---|---|
| ebp | −0.114 | −0.169 | −0.158 | +0.509 |
| gz_spread | −0.103 | −0.155 | −0.144 | +0.485 |
| **est_prob** | −0.123 | **−0.197** | **−0.229** | +0.510 |

`est_prob` dominates ebp at every return horizon and the gap **widens with horizon** (−0.229 at 6m) —
exactly what a recession-probability signal should do (it's a slow, longer-lead measure). Incremental
over vix: `vix+est_prob` ΔR²=**+0.100** vs `vix+ebp` +0.085. **But** `corr(ebp, est_prob)=0.969` —
they are nearly the same signal; est_prob adds only +0.016 ΔR² *over* ebp. **Decision: use `est_prob`
as the timing/overlay signal** (it's the better of two near-identical series, and it's already
calibrated as a probability — easier to threshold than a raw premium).

**Q2 — the lead is NOT steady; it is ENTIRELY a crisis/high-stress phenomenon.** This is the most
important finding of the deep-dive:

- **Drop 3 crisis windows** (dot-com 2000–02, GFC 2007–09, Covid 2020) and the corr **flips sign**:
  full −0.172 → **ex-crisis +0.130** (n=338). The "credit leads" signal is carried entirely by ~61
  crisis months out of 399.
- **Within ebp terciles:** low/mid terciles show ~0 or *positive* corr; only the **high-ebp tercile
  carries the negative signal (−0.161)**. Below ~0 ebp, the factor says nothing.
- **Decile monotonicity breaks at the top:** mean fwd-3m return is **flat ~+0.03–0.04 across deciles
  0–7**, then drops to +0.018 (dec8) and **−0.014 (dec9, ebp>+0.45)**. It's a **cliff in the top
  ~20%, not a gradient** — same shape the design doc found for the existing score (§A11).
- **est_prob bands confirm:** fwd-3m return is flat +0.035 for est_prob <30%, turns **negative
  (−0.008) only in the >30% band**, where the P5 tail also blows out (−0.171 vs −0.06 elsewhere).

**What this means for the model:** the credit/recession signal is a **tail switch, not a continuous
tilt.** It does nothing in normal times and only earns its keep when stress is already elevated. So
the overlay should be a **threshold gate** (e.g. est_prob > ~30% → cut exposure), NOT a linear factor
fed continuously into a regression/PCA. Feeding it linearly into the joint model would dilute a
sharp tail signal into a weak average — the −0.17 full-sample corr UNDERSTATES its crisis value and
OVERSTATES its normal-times value. This is a concrete argument that ebp/est_prob belongs in a
rule-based overlay layer (lit review §2 Layer-2/3), not inside the R-c learned scalar.

### S4 — DXY / MOVE splice (deferred, characterized separately)

DXY has no single full-history series (legacy DTWEXM 1973–2019 different basket; broad DTWEXBGS
2006+). MOVE is 2021+; its only pre-2021 cousin VXTYN (2003–2020) is a different instrument with
**zero overlap** → cannot rebase. **Decision: keep segments separate, do NOT manufacture a continuous
series** (the §10 "molding error"). Not on the critical path for the Step-2 decision.

**MOVE — DROPPED from Layer A (Step-2 P3, 2026-06-24):** on its 2021+ slice, `R²(MOVE ~ other
factors) = 0.919` → 92% redundant, not a distinct axis. NB the *reason* is "insufficient independent
history" (the 2021+ window is one regime where all risk factors co-move, cf. S5's 0.99s), NOT proven
global redundancy — but the conclusion stands: a factor whose only history is a single regime cannot
enter a regime-learning model. P4 (source pre-2021 MOVE) is moot unless a future need appears.

### S5 — Cross-factor redundancy (the P2 problem, made visible)

Two windows, because the answer depends heavily on which:

**2021+ common window (MOVE-inclusive, n small, ONE regime):** severe collinearity — real_yield↔DGS10
0.99, credit_ratio↔DGS10 0.92, MOVE↔{rates} ≈ −0.91. Misleading: it's one QT regime.

**2007–2026 no-MOVE window (n=4760, the honest read):**
```
              VIX  hy_spread  real_yld  dxy   DGS10  DGS2  term  credit_ratio
VIX          1.00    0.73       0.14  -0.08  -0.04 -0.12  0.15    -0.47
hy_spread    0.73    1.00       0.15  -0.37  -0.09 -0.32  0.42    -0.72
real_yield   0.14    0.15       1.00   0.07   0.93  0.73 -0.17     0.42
dxy_broad   -0.08   -0.37       0.07   1.00   0.04  0.51 -0.79     0.49
DGS10       -0.04   -0.09       0.93   0.04   1.00  0.80 -0.19     0.60
term_spread  0.15    0.42      -0.17  -0.79  -0.19 -0.74  1.00    -0.52
credit_ratio-0.47   -0.72       0.42   0.49   0.60  0.73 -0.52     1.00
```
**Read:** over the full window the rate cluster (real_yield↔DGS10 0.93, DGS2↔DGS10 0.80) is still
collinear but the extreme 0.92–0.99s were a 2021+ artifact. **VIX↔hy_spread = 0.73** is the genuine,
stable risk-off pair (stronger than in §A6's z-score view). term_spread is least redundant.

**Implication for P2:** the panel is ~**2 independent axes** — (i) risk-off (VIX/HY) and (ii) a
rate-level/dollar bloc — plus the orthogonal ebp. A weighted sum or raw PCA would be dominated by the
rate bloc (it measures the rate level ~3×). **The joint model needs decorrelation/whitening**, or
it just re-counts rates. This is the core P2 decision the design doc flagged, now quantified.

---

## Step 2 — Cross-Factor Comparability (P2): results & decision (2026-06-24)

Cells: `docs/session_logs/sprint_13/2026-06-24_step2_comparability_cells.md`. Scope is **Layer A
only** (the est_prob crisis gate, Layer B, is settled and sits outside). Goal: one comparable,
decorrelated daily matrix for Step 3.

**Common ruler (P1):** all factors mapped to **[0,1]** — full-history percentile for mean-reverting
(VIX, hy_spread), percentile-of-rolling-5yr-normal for drifting/regime-switching (rates, DXY). This
is the P2 "shared space" resolution: every factor answers the same "how extreme vs. its own
reference" question, so the joint position is coherent (design §5).

**MOVE: DROPPED (P3).** `R²(MOVE ~ others) = 0.919` on its 2021+ slice → redundant on the only
history it has. Fit window is **2007+, MOVE held out** (the full-with-MOVE panel was 1306 rows of one
regime — unfit for regime learning).

**Decorrelation — empirical comparison (P2a/b/c):**
- **Clusters (|corr|>0.7):** {VIX} {hy_spread} {real_yield, DGS10, DGS2} {dxy_broad} {term_spread}
  {credit_ratio} — the rate bloc is one axis, everything else standalone. Confirms S5.
- **PCA (P2b):** explained var **[0.54, 0.24, 0.11, 0.05, …]** (PC1–3 = 88%). Loadings:
  **PC1 (54%) = rate/dollar level** (real_yield .54, DGS10 .51, DGS2 .48); **PC2 (24%) =
  credit-vs-curve** (hy_spread +.45, term_spread −.59); **PC3 (11%) = pure VIX** (.92).
- **The decisive observation:** VIX — the factor that drives the *proven* use (sizing, §A4 corr 0.67)
  — is only **PC3, 11% of variance**. Whitening optimizes for variance, so it would hand the joint
  model 54% attention to the rate level and 11% to VIX. **Variance ≠ usefulness here.**
- **Silhouette (P2c):** pruned 0.329 vs whitened 0.356 — a 0.027 gap = noise; both isolate Covid as
  its own cluster. Whitening buys NO regime-separation advantage.

**DECISION: PRUNED, not whitened.** Silhouettes tied → whitening's only claim (more info) is actually
rate-level variance we don't want dominating. Pruned is explainable (4 named axes), robust (4 vs 8
factors), and doesn't bury VIX. Starting set: **[VIX, hy_spread, real_yield_10y, term_spread]**
(max offdiag corr 0.47). **Exact membership is TUNABLE in Step 3 by beat-the-baseline lift** — e.g.
whether to add `credit_ratio` (the distinct PC2 credit axis) is decided by whether it improves the
gated metric, not assumed now.

---

## What Step 1 changed in the design (decisions, with evidence)

| Design-doc open item | Status after Step 1 | Evidence |
|---|---|---|
| **§9: regime-ID primary, or two models?** | **Two signals, two jobs.** Strong vol-sizing core (continuous) + a crisis-only recession GATE. NOT one explainable number. | S3d-incr + S3e: vol→dispersion, est_prob→direction in stress only |
| **§10 success metric (deferred to EDA)** | **Beat a 2-factor (VIX, ebp) regression** — on fwd-vol (sizing) AND fwd-ret (timing). | S3d-incr baseline R²: 0.384 / 0.097 |
| **Leading vs coincident** | **Raw factors coincident; only GZ credit leads, weakly, and ONLY in crisis.** | S3b/c flat; S3d −0.17; S3e: ex-crisis flips to +0.13 |
| **Timing/overlay signal** | **Use `est_prob` (not raw ebp)** — dominates at every horizon, already a probability. | S3e Q1: −0.197/−0.229 @ 3m/6m vs ebp; corr(ebp,est_prob)=0.97 |
| **Overlay SHAPE** | **Threshold GATE (est_prob > ~30%), NOT a linear ML input.** | S3e Q2: signal is a top-20% cliff; ex-crisis sign flips; >30% band = the only negative one |
| **Per-factor normalization** | vol/credit → percentile (fat-tail); rates → rolling lookback (regime-switching, NOT differencing) | S1/S2/S2b |
| **P2 (common space)** | **Mandatory decorrelation/whitening** before any joint model. | S5: ~2 axes, rate bloc collinear |
| **New factor to add (step 2)** | **GZ est_prob** (monthly, sourced) — as a gate, not a regression term. | S3e |

---

## Why move to Step 2, and what Step 2 IS

**Why move on:** Step 1's job was to characterize factors and settle leading-vs-coincident. Both done.
We now know the factors, their rulers, that timing is weak-but-real via ebp, and that the joint space
needs decorrelation. The open questions are no longer about the factors — they're about how to
COMBINE them.

**Step 2 (cross-factor comparability / P2) — the explicit decision step:**
1. Put factors on comparable rulers per S1/S2 (percentile for fat-tail/coincident; rolling-z for
   regime-switching rates) — i.e. resolve the "different rulers" problem the design doc named.
2. Decide the **common space** the joint model operates in: decorrelation/whitening of the rate bloc,
   so the learned model doesn't re-count the rate level (S5). Candidate: percentile→rank uniformization,
   or PCA-whiten the rate cluster while keeping VIX/HY/ebp as distinct axes.
3. **Frequency reconciliation:** ebp is monthly; the sizing factors are daily. The overlay/core split
   means this is fine (ebp tilts a slow overlay, vol drives fast sizing) — but it must be explicit.

**The architecture S3e implies — a layered model, not a monolithic scalar:**
- **Layer A (continuous sizing core):** the vol-driven signal (VIX + the coincident risk-off bloc),
  normalized per S1/S2, decorrelated per S5. This is where the joint model (PCA/GMM/HMM) operates and
  where the §A4 0.67 fwd-vol corr lives. ebp is a valid *second sizing input* here (S3d-incr ΔR²=+0.034).
- **Layer B (crisis gate, OUTSIDE the joint model):** `est_prob > ~30%` → cut exposure. S3e shows
  this is a tail switch, not a continuous tilt — feeding it linearly into Layer A would dilute it.
  Keep it as a rule-based overlay (lit review §2 Layer-2/3). This is the ONE thing that adds timing.

**Step 3 (joint model) is GATED on Layer A:** a learned scalar must beat the **2-factor (VIX, ebp)
regression baseline** (R² 0.384 sizing / 0.097 timing). If it can't beat that simple benchmark, R-c's
ML stage adds nothing and we ship the 2-factor sizing model + the est_prob gate — itself explainable,
satisfying the spirit of design §1 without the black-box risk §6 warned about.

**Open / parked (not blocking Step 2):**
- **Absorption Ratio** (lit §4.6) — the literature's top *cross-asset* lead indicator, needs 20–50
  asset return series we don't have. Now MORE attractive given S3e: our only timing signal (est_prob)
  is crisis-only and won't warn before a crisis *forms*. AR claims to (precedes by 20–60d). Parked as
  the candidate to pursue IF pre-crisis warning (not just in-crisis gating) is wanted.
- **est_prob vs ebp — RESOLVED** (S3e Q1): est_prob wins; use it as the gate signal.

---

## Step 3 — Joint Model GATE: results & FINAL verdict (2026-06-24)

Cells: `docs/session_logs/sprint_13/2026-06-24_step3_joint_model_cells.md`. Fit three joint models
(Mahalanobis, GMM, HMM) on the Step-2 pruned [0,1] matrix `[VIX, hy_spread, real_yield_10y,
term_spread]`; output a continuous sizing scalar; **gate = beat the baseline on forward realized vol
R².** Outputs: continuous scalar (scored) + regime labels (overlay only).

**J2 — the in-sample gate (looked like a marginal pass):**

| model | fwd_vol R² | beats daily baseline (0.133)? |
|---|---|---|
| **maha** | 0.142 | ✅ (by +0.009) |
| gmm | 0.109 | ❌ |
| hmm | 0.062 | ❌ |

Two red flags immediately: (a) GMM/HMM — the actual *regime* models — both FAILED; only Mahalanobis
(a 1-line distance, barely "ML") passed. (b) The daily baseline is **0.133, not Step-1's 0.384** —
ffilling monthly ebp to daily craters it. So "maha beats baseline" was partly "baseline kneecapped."

**J4 — membership (decided by lift):** adding credit_ratio *hurt* (0.142 → 0.093). Keep the 4-factor
set. **J5 — regimes:** persistent (26.6-day runs), interpretable (cluster 2 = crisis, VIX 0.82,
fwd_vol 0.21 vs ~0.14). Clean overlay, but not the gate.

**Validation (per "don't believe a 0.009 in-sample edge") — WALK-FORWARD out-of-sample, vs the HONEST
comparator (VIX alone, not the kneecapped baseline):**

| horizon | IS: VIX | IS: maha | **OOS: VIX** | **OOS: maha** | OOS maha − VIX |
|---|---|---|---|---|---|
| H=21 | 0.301 | 0.180 | 0.273 | **0.027** | **−0.246** |
| H=63 | 0.185 | 0.132 | 0.134 | **0.006** | **−0.128** |
| H=126 | 0.121 | 0.079 | 0.069 | **0.001** | **−0.069** |

**Two findings, both fatal to the joint model:**
1. **Even IN-SAMPLE, maha LOSES to VIX-alone at every horizon** (0.180 vs 0.301 @ H=21). The J2
   "pass" was an illusion of comparing maha to a weak ffill-ebp baseline instead of to VIX. Against
   the right comparator, the 4-factor scalar is strictly worse.
2. **OUT-OF-SAMPLE, maha collapses to ~0** (0.027/0.006/0.001) while VIX holds (0.273/0.134/0.069).
   The J3 "+0.066 over VIX" was pure in-sample overfit — the covariance memorizing the train period.

### ⭐ FINAL DECISION — R-c's ML stage is CLOSED (tested, falsified)

**For SIZING: VIX alone.** Strongest fwd-vol predictor, survives OOS, beats every joint model (GMM,
HMM, Mahalanobis) IS and OOS. The multi-factor joint scalar adds nothing — the panel was ~2 axes and
coincident from Step 1; the walk-forward makes it final. **Do NOT build the GMM/HMM regime model.**

**For TIMING/crisis: the est_prob gate (Layer B).** Untouched by this — it was never in the joint
matrix. Still the only directional signal, still crisis-only, still a threshold rule (est_prob >~30%).

**Shipped model = `VIX` (sizing) + `est_prob` gate (crisis). Both trivial, both validated, both
explainable.** This satisfies the spirit of design §1 (one readable number per job) with ZERO
black-box risk (§6) — and it is the cheapest possible thing that works, which was the whole point.

**What this retires:** the design-doc §10 R-c "two-stage learned joint model" pivot is falsified for
THIS factor set. Not the *idea* (a learned regime model could help with richer inputs) — but with the
macro factors available, it does not beat VIX. The one remaining lead candidate — the **Absorption
Ratio** — was then tested (Step 4 below) and ALSO fails. See below.

---

## Step 4 — Absorption Ratio: the last lead candidate, TESTED & rejected (2026-06-24)

Cells: `docs/session_logs/sprint_13/2026-06-24_step4_absorption_ratio_cells.md`. The shipped model
(VIX + est_prob gate) gates DURING a crisis but can't warn BEFORE one forms. The Absorption Ratio
(Kritzman 2012, lit §4.6) is the literature's #1 *pre-crisis* fragility signal — it measures
cross-asset *coupling* (fraction of variance in top PCs), a different mechanism than factor levels,
and claims to precede drawdowns by 20–60d. **Correction to earlier note: we DO maintain the data** —
all 36 cross-asset ETFs are in `price_data`. Built AR on a clean **20-asset, 2007+ panel** (5 equity
regions/styles, 9 sectors, 3 bonds, gold/oil/dollar; XLRE excluded — starts 2015; no bad ticks; full
GFC/Covid/2022).

**Result — AR does NOT lead on our data, robustly:**
- **AR2 (fwd-return corr): WRONG sign.** AR = **+0.16/+0.28/+0.31** @ 1/3/6m — *positive*, the same
  contrarian-bullish pattern as VIX (§A2). A leading fragility signal must be negative. High coupling
  doesn't precede drops; it coincides with the high-vol environment that mean-reverts up.
- **AR3 (rise-from-calm, the decisive test): FLAT/negative.** AR z-trajectory into equity tails:
  t−42 −0.04 → t−21 −0.13 → t0 −0.22 (drifts the wrong way). **RISE_FROM_CALM = −0.06** (needed
  >0). AR sits *below* its mean before tails — no pre-crisis rise.
- **AR4 (robustness): −0.05 to −0.14 across ALL 9** (window 126/252/504 × top-PC 3/4/5). Not a tuning
  artifact; AR simply doesn't lead at any reasonable setting.

**Caveat (honest):** Kritzman demonstrated AR's lead on 2000 & 2008 specifically, and the paper
ADMITS it missed Covid-2020 (exogenous shock, no coupling build-up). Our 2007+ window is dominated by
GFC, Covid, 2022 — and Covid/2022 weren't slow-coupling crises. So AR failing here is partly
*consistent* with the paper's own stated limitation.

### Step 4b — "But the literature can't ALL be wrong" — root-cause investigation

The contradiction with the literature warranted ruling out our own method first. We replicated
Kritzman's ACTUAL test along every axis, not our simplified one:

| we tested THEIR | our AR3 | Kritzman | result of using THEIRS |
|---|---|---|---|
| signal | AR level | standardized **ΔAR** (15d change) | ΔAR vs fwd-drawdown corr = **+0.03** (none) |
| target | worst-return day | the market **PEAK** before drawdown | AR z at peaks = **−0.2 to −0.3** (below avg, not elevated) |
| trading rule | — | **ΔAR > +1σ → risk-off** | fwd-dd on signal days −0.056 = baseline −0.056 (no edge) |
| universe | 20 cross-asset | **51 equity industries** | equity-only 14-asset AR: corr +0.04, GFC-era +0.005 (none) |
| full model | AR alone | **AR × Turbulence 2×2 grid** | see below — the FRAGILE quadrant fails |

**The faithful 2×2 grid (AR × Mahalanobis turbulence), forward 126d drawdown by quadrant:**

| quadrant | n | mean fwd_dd | note |
|---|---|---|---|
| **CALM** (loAR/loTurb) | 1141 | **−0.102** | WORST — the opposite of the framework |
| CRISIS (hiAR/hiTurb) | 893 | −0.057 | already in selloff, mean-reverts up |
| **FRAGILE** (hiAR/loTurb) | 1212 | −0.057 | Kritzman's "warning" — NO worse than baseline |
| IDIO (loAR/hiTurb) | 1268 | −0.062 | |
| baseline | | −0.070 | |

**ROOT CAUSE — four reasons, none of which is "our method was wrong":**
1. **Publication/in-sample bias.** Kritzman's headline ("ΔAR +1σ 20–60d before peak") was shown
   in-sample on ~2 events (2000, 2008). The paper's OWN full-sample numbers already concede it:
   ~60% hit, **~40% false-positive**, missed Covid. We measured the marginal full-sample reality;
   the +0.03 corr is consistent with "right 60% of the time."
2. **Window composition.** Their 1998–2010 = three consecutive slow-coupling crises (LTCM/dot-com/
   GFC). Our 2007–2026 = GFC (works) + Covid (exogenous, paper admits miss) + 2022 (rate grind).
   2 of our 3 are structurally invisible to a coupling signal.
3. **The FRAGILE quadrant doesn't lead** even built faithfully — −0.057 fwd_dd, no worse than baseline.
4. **The deeper, anti-Kritzman truth:** **CALM (low-AR/low-turb) has the WORST forward drawdowns
   (−0.102).** Crashes start from complacency, not visible coupling. Turbulence corr with fwd_dd is
   −0.16 = COINCIDENT (high turb = already in the drop). This is §A2/§A3 ("danger is
   contrarian-bullish; calm precedes storms") confirmed at the CROSS-ASSET level — the same
   structure every level factor, credit, and now coupling has shown.

**Conclusion:** the literature isn't "wrong" — it over-generalized from a favorable in-sample window,
and its core mechanism (coupling warns early) is *contradicted* by the contrarian structure our data
shows at every level tested. "Nothing leads equity tails on this universe" is now the strongest,
most-replicated finding in the investigation, not an unexplained anomaly.

### ⭐⭐ INVESTIGATION COMPLETE — final model, no loose ends

Every lead candidate has now been tested: level factors (coincident, S3b/c), refined credit
(weak + crisis-only, S3d/e), cross-asset coupling (does not lead, Step 4). **Nothing leads equity
tails on this universe — confirmed against the academic literature's best candidate.**

### Scope note — what was NOT tested: VALUATION timing (different horizon, untested, the one open avenue)

This entire investigation tested **TACTICAL / stress signals** at a **short horizon** (days–weeks):
does vol / credit / coupling **warn before an imminent drawdown**? Answer: no, all coincident.

It did **NOT** test **STRATEGIC / valuation** timing at a **long horizon** (months–years): does an
*expensive* market (CAPE, equity-risk-premium, value spread) predict *lower long-run returns*? That
is a different question with a different, literature-supported answer:
- **Asness, Ilmanen & Maloney (2017), "Market Timing: Sin a Little"** — *defends* valuation timing
  against the (incl. Asness's own earlier) skepticism. Valuation DOES carry timing info, but the edge
  is **small and slow**; naive contrarian timing underperformed mostly because it fights trend. The
  resolution: "sin a little" — a *small* valuation tilt, combined with momentum, adds modest value.
  Big all-in timing ("sin a lot") does not.
- **Why this does NOT contradict our finding:** different signal (valuation, not stress), different
  horizon (years, not days), different target (long-run return, not imminent tail). A high-CAPE market
  can be "expensive" for *years* with no near-term stress signal firing. Both hold simultaneously.
  In fact Asness *reinforces* our meta-finding: the only place timing has any edge is a slow, small,
  valuation tilt — **not** a fast stress alarm (which we showed doesn't exist).
- **Implication / a possible "Step 5" of a different character:** if a STRATEGIC (months–years)
  allocation tilt is ever wanted — as opposed to the tactical crisis gate we built — **valuation is
  the candidate**, orthogonal to everything in the VIX/credit/AR panel, and the one literature-backed
  timing signal we have NOT ruled out. It would be a slow allocation overlay, sized small ("sin a
  little"), NOT a drawdown-warning system. Out of scope for this regime/sizing model; noted so it is a
  *deliberate exclusion*, not an overlooked gap.

**FINAL MODEL: `VIX` (sizing) + `est_prob` gate (in-crisis). No pre-crisis warning layer — BY
EVIDENCE.** This is the simplest thing that works, fully validated, fully explainable, and the "no
lead" conclusion is now exhaustively supported rather than assumed.

**Success-metric note:** the Step-1 baseline was stated as monthly R² 0.384 (sizing). Step 3 revealed
the operational baseline is **VIX-alone OOS** (~0.27 @ H=21 daily), which is the number any future
candidate must beat. Recorded so this isn't re-derived.

---

## Artifacts

- Step 1 cells: `docs/session_logs/sprint_13/2026-06-24_raw_factor_eda_cells.md`
- Step 2 cells: `docs/session_logs/sprint_13/2026-06-24_step2_comparability_cells.md`
- Step 3 cells: `docs/session_logs/sprint_13/2026-06-24_step3_joint_model_cells.md`
- Step 4 cells: `docs/session_logs/sprint_13/2026-06-24_step4_absorption_ratio_cells.md`
- Sourcing script: `scratch_source_factors.py` (re-runnable; FRED → parquet)
- Raw factor panel: `scratch/raw_factor_panel.parquet`
- GZ EBP (monthly): `scratch/gz_ebp_monthly.parquet` ← from Fed `ebp_csv.csv`
- All tests run against `data/market_data.duckdb` (read-only), 2026-06-24.
