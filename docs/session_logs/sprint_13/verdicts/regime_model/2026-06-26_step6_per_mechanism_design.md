# Step 6 — Per-Mechanism Lead Signals: Design & Pre-Registered Protocol (2026-06-26)

> **Status: DESIGN ONLY. Pre-registered BEFORE touching forward returns.** This document specifies
> the test and its pass/fail bar in advance, so the per-mechanism hypothesis cannot be talked into a
> "yes" by post-hoc fitting — the exact failure mode (publication bias from ~2 events) that the Step-4b
> root-cause identified in Kritzman.
>
> Companions: `2026-06-24_regime_eda_findings.md` (the Steps 1–4 evidence trail that this challenges),
> `2026-06-25_factor_momentum_challenge.md` (the momentum blindspot, folded in here as one candidate
> transform), `2026-06-24_regime_model_design.md` (§10 roadmap).
>
> **Shipped model is unchanged and remains the default:** `VIX` (sizing) + `est_prob` gate (crisis).
> Step 6 does NOT reopen that. It tests whether a *per-mechanism* lead signal exists that the prior
> *event-averaged* method was structurally unable to detect. If Step 6 fails its pre-registered gate,
> "nothing leads" is confirmed at a higher standard and the matter is closed for good.

---

## 1. The methodological critique (what Steps 1–4 actually proved vs. claimed)

The prior investigation's strongest claim is *"nothing leads equity tails on this universe — confirmed
against the literature's best candidate."* That claim **overreaches its estimator.**

Every lead test in Steps 1–4 (S3b/c, AR3, Step-4b) used the same design:

> **Event-averaged, single-signal:** align all tail events at t0 → average ONE candidate signal's
> trajectory backward → ask "does this signal rise before the *average* tail?"

This estimator is **biased toward the null by construction** when drawdowns are heterogeneous in
*mechanism*. Drawdowns are idiosyncratic: event A is a vol shock, B a rate shock, C a credit-spread
shock. A signal that genuinely leads its *own* subtype (real-yield momentum before rate-led selloffs)
but is flat/wrong-sign in the others gets **averaged to ~zero** across all events. The study would then
report "real-yield momentum doesn't lead" — when the truth is "it leads its events, and the cross-event
mean washed it out."

**Therefore what Steps 1–4 actually licensed is the NARROW claim:**
> *No SINGLE signal leads the cross-event AVERAGE of all tail types.*

…not the BROAD claim *"no useful lead signal exists."* Those are different statements. The prior
results are fully *consistent with* a power problem rather than an absence of signal — AR's +0.16
wrong sign, ebp's ex-crisis flip to +0.13, the −0.06 rise-from-calm are all exactly what heterogeneous
subtypes cancelling out would produce.

**The reframe (the actual hypothesis to test):** not *"one signal predicts all tails"* (a universal
predictor — falsified, and we are NOT re-litigating it). Instead: *"different signals are dangerous in
different regimes; learn from history WHICH signal was the active one per episode."* This is a
**regime/mechanism-classification** question, which the prior study never engaged — it only tested the
pooled-predictor camp (Kritzman AR, Gilchrist-Zakrajšek EBP are both pooled `corr(signal_t, fwd_ret)`
regressions) and declared the whole question closed.

## 2. The danger this reframe carries (why it needs pre-registration)

The reframe is correct but **not free.** With only ~6–8 distinct drawdown episodes and 7+ candidate
signals, "find which signal led each event" is a multiple-comparisons minefield:

- For *any* event, post-hoc, at least one of 7 signals will have spiked beforehand **by chance**.
- "In A vix led, in B rates led, in C spread led" can be a true causal taxonomy **or** pure curve-fit
  to 3 data points — and in-sample on this n, the two are nearly indistinguishable.
- This is precisely the failure that killed Kritzman (Step-4b: in-sample on ~2 events, ~40% FP
  full-sample).

**So the bar is not "does the stratified version look better in-sample" (it always will). The bar is:
does it survive walk-forward OOS, with the mechanism taxonomy FROZEN before the forward test?** Only
that keeps Step 6 from relaunching the overfitting Steps 1–4 were right to fear.

---

## 3. Protocol — two stages, screen then gate

### Step 6a — Controlled distributional screen (lead generator, NOT a verdict)

**Purpose:** cheaply identify *which factors even have a pre-tail distributional fingerprint*, without
pre-labelling mechanisms — so the candidate set carried into 6b is chosen on evidence, not assumed.
This is the screening step; it never proves a lead.

**The idea (why distribution, not mean):** the prior study collapsed each signal to a *mean
trajectory* (S3b "z≈+0.62 at t−21"). A mean is exactly what destroys a subtype-specific signal. A full
**distribution** preserves it: a factor that spikes before its *own* 2 events appears as a **fat right
tail / bimodality** in the conditional distribution even when the conditional *mean* barely moves. So
the distributional view can reveal subtype signal **without** having to pre-label subtypes — the
cleanest possible answer to the §1 heterogeneity critique.

**The comparison:** `P(factor | t ∈ [tail−k, tail−1])` overlaid on a baseline distribution, for each
factor and each transform (level, _diff1m/21d, _diff3m/63d — folding in the momentum challenge).

**THE TRAP (must be controlled or this reproduces S3b):** the pre-tail window is NOT a random sample
of time. Tails cluster (Mar-2020 = dozens in weeks); factors are persistent (S2 half-life = weeks). So
`[tail−k, tail−1]` for one tail lands *inside the elevated stress of a prior tail*. The naive
conditional distribution looks shifted-and-fat **even for a factor with zero leading power** — purely
autocorrelation. The naive overlay will make *everything* look leading. **This is the S3b artifact;
the distributional view inherits it and does not escape it.**

**Mandatory controls (the S3c discipline, applied to the distribution):**
1. **De-cluster:** keep only the *first* tail (onset) of each stress cluster — one onset per episode,
   so the pre-window cannot overlap a prior tail's aftermath. (Target ~6–8 declustered onsets.)
2. **Calm-start condition:** require the factor *below its own median at t−k*, then ask if it *rises
   into* the tail. Only this version makes "elevated pre-tail" mean *leading* rather than *still
   elevated from last time*.
3. **Matched baseline, not unconditional:** compare against `P(factor | random k-windows matched to
   the same era/regime)`, NOT the full-history unconditional. Otherwise you partly measure "tails
   happen in high-vol decades" (composition), not "factor rises before tail."
4. **Test the TAIL, not the center:** report the right-tail mass / 90th-percentile shift, not the
   mean. A subtype-specific signal moves the conditional *tail*; testing the mean (what S3b did) is
   underpowered against exactly this hypothesis. Quantify with **KS / Anderson-Darling** on the
   controlled samples — visual overlay is the eyeball version, the two-sample test is decision-grade.

**Sensitivity:** sweep k ∈ {21, 42, 63} and the tail-definition threshold; a real fingerprint is not a
single-k artifact.

**Output of 6a:** a short list of (factor, transform) pairs whose *controlled* conditional distribution
genuinely differs from matched windows — pre-screened candidates for 6b. **No forward-return claim is
made here.** If `real_yield_3m_change` has a fatter controlled right tail than matched windows but
`dxy` does not, real_yield momentum advances and dxy does not.

> **Hard caveat to set expectations:** with ~6–8 declustered onsets, the conditional distribution has
> very few independent draws. **6a is a LEAD GENERATOR, not a verdict.** The verdict lives entirely in
> 6b. Treating a 6a overlay as proof would be the Kritzman error in a new costume.

### Step 6b — Signal-conditional walk-forward gate (the verdict)

**Purpose:** the only test that survives the bar that killed the joint model (Step 3) and AR (Step 4).

**Flip the anchor.** The prior study (and 6a) anchor on *tails* and look *back* at signals — which
forces pooling across mechanisms. Instead, anchor on *each signal firing* and look *forward*:

> For each screened (factor, transform), condition on **IT** firing (e.g. its rate-of-change in the top
> decile), then measure **forward drawdown / forward return — WALK-FORWARD, OUT-OF-SAMPLE.**

Why this answers the §1 critique cleanly: you **never pool across signals/mechanisms.** A signal that
leads only its own subtype will still show negative forward returns *conditional on itself firing*,
even if it is silent the rest of the time. The averaging-across-mechanisms problem is structurally
absent because there is no averaging across mechanisms — each signal is judged on its own firing days.

**The pre-registered gate (frozen now, before any forward look):**
- **Taxonomy / candidate set is FROZEN** at the 6a output. No adding signals after seeing 6b returns.
- **Walk-forward only.** Fit any threshold/percentile on a trailing window; evaluate strictly OOS.
  In-sample lift is assumed and does not count (Step 3 maha was +0.066 IS → ~0 OOS).
- **Comparator = the honest one:** forward drawdown *conditional on signal firing* vs *unconditional
  base-rate* in the SAME OOS period. Beating a kneecapped baseline does not count (the Step-3 ffill-ebp
  lesson).
- **Multiple-comparison honesty:** with k candidate signals tested, require the survivor to clear the
  bar by more than a Bonferroni-style allowance for k looks — OR show consistency across the k-sweep
  and across at least two non-overlapping OOS sub-periods. One signal clearing one threshold in one
  window is curve-fit, not a finding.

**PASS:** a screened signal shows materially worse forward drawdown *conditional on its own firing*,
OOS, robust across the k-sweep and across ≥2 OOS sub-periods, surviving the multiple-look correction.
→ It earns a place — most likely as a **Layer-B gate trigger** ("rate-shock" rule alongside est_prob),
NOT as another linear input to Layer-A (S3e showed tail switches must not be diluted into a regression).

**FAIL:** no screened signal survives OOS. → "Nothing leads" is now confirmed at a *higher* standard
(per-mechanism, distribution-aware, signal-conditional) than the event-averaged Steps 1–4. The matter
is closed, and the shipped VIX + est_prob model is vindicated, not merely defaulted to.

---

## 4. What this retires / settles either way

| Outcome | What it establishes |
|---|---|
| 6b PASS | The prior "nothing leads" was an **estimator artifact** of event-averaging; a per-mechanism gate exists. Add it to Layer B. |
| 6b FAIL | "Nothing leads" survives the strongest reframe available. The shipped model is correct **by exhaustion**, not assumption. Close the lead question permanently. |

Either result is decision-grade *because the gate was pre-registered here, before forward returns were
touched.* That is the whole point of writing this before running it.

---

## 5. Relationship to prior challenges (consolidated)

- **Momentum challenge (2026-06-25):** correctly found Steps 1–4 tested levels-only, never
  rate-of-change. Verified: `real_yield_10y` 3m-change vs fwd SPY 3m ≈ −0.19 (level only −0.06). BUT
  its strong conclusion ("heavily favored to beat VIX OOS") was unverified — the −0.19 is daily/
  overlapping; non-overlapping it's ≈−0.22 (≈ ebp, not better); it conflates leading with coincident
  (corr with PAST 3m ret = −0.15 vs FWD −0.19); and asserts OOS lift with zero walk-forward.
  **Folded in here as candidate *transforms* (level + diff1m + diff3m) entering the 6a screen — NOT as
  a standalone reopen.**
- **Heterogeneity challenge (this doc):** the deeper, separate critique — the wrong *aggregation*, not
  the wrong *transform*. Addressed by 6a (distribution-aware screen) + 6b (signal-conditional OOS gate).

---

## 6. Open / to-build (not yet run)

- [ ] 6a cells: controlled distributional screen — declustered onsets, calm-start, matched baseline,
      tail-mass + KS/AD, k∈{21,42,63}. Output: screened (factor, transform) shortlist.
- [ ] 6b cells: signal-conditional walk-forward gate on the shortlist, with the §3 pre-registered bar.
- [ ] Decide declustering rule + onset list FIRST (frozen artifact) before either step looks forward.
