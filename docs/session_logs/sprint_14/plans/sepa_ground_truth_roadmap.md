# SEPA program — ground-truth consolidation & roadmap

**Date:** 2026-07-10 · **Status:** 📋 ROADMAP (steering doc) · **Parent:** [`sepa_funnel_meta_plan.md`](sepa_funnel_meta_plan.md)
**Purpose:** consolidate what is settled, fix the vocabulary that is being conflated, and gate the
open decisions — including "de-gate m01's training set" — behind the evidence that must land first.
Child plans ([R2](r2_leadership_profile_eda_plan.md), [R3](r3_exit_selection_coupling_plan.md)) carry the milestones; this doc carries the *frame*.

---

## 0. The one thing to fix first — "null" is three different currencies

Every conclusion in this program is stated as some flavour of "null" or "wins". They are **not the
same claim** and do not imply each other. Before citing any verdict, name which currency it is in.

| # | Currency | Question it answers | Metric | Verdicts in this currency |
|---|---|---|---|---|
| **C1** | Label-ranking | Does feature X rank the tail *beyond RS* on the panel? | per-date `tail_mag_63` / `home_run_63` lift at matched depth | R1, R1b, R1b-axis2 |
| **C2** | OOS-ranking | Does an *ML model* beat the one-column RS bar out-of-sample? | walk-forward pooled top-decile tail lift, model vs RS on same fold | M3 |
| **C3** | Exit-aware P&L | Does the selection *make money* under a real exit? | BackTrader start-date cone: per-cell Sharpe, %neg, DD | M4, (R3 to come) |

**Rules of use:**
- A C1/C2 null (RS subsumes it / ML ties RS) says **nothing** about whether the incumbent m01 is
  null — the incumbent was never judged in C1/C2. It lives and won in **C3** (M4 `champion_gated`
  median Sharpe 0.47).
- A C1 *win* (e.g. small-cap axis 2.4–3.2×) is **not** a trade claim — the label is upside-only
  (§2). It routes to C3 before anything ships.
- "m01a is null" (true, C2+C3) ≠ "m01 is null" (false). This is the single most likely misread of
  the whole sprint. Anyone citing "the tail ranker failed" must add *in which currency*.

---

## 1. Ground truth — what is SETTLED (do not re-litigate)

| # | Settled fact | Currency | Source |
|---|---|---|---|
| G1 | Breakout is an **entry trigger, not a universe**. Selection research runs on the full `trend_ok` panel. | — | population reframe (2026-07-09) |
| G2 | On the panel, **ML ties one-column RS** OOS; both Tweedie *and* logistic classifier tested, agree fold-sign 13/15. Binding constraint = **feature set / temporal break, not the loss**. | C2 | M3 |
| G3 | The 85 non-RS features **beat RS pre-2019, decay/invert 2019+**. Any revived edge must survive 2019+. | C2 | M3 |
| G4 | RS top-decile concentrates the **tail** but its **median inverts** (weak-RS beats strong-RS on the median path). | C1 | M2 / reframe |
| G5 | RS-tail selection **loses the exit-aware cone** to the gated incumbent (0.10 vs 0.47) — **label lift ≠ trade edge** under tranche exits, because the exit truncates the tail. | C3 | M4 |
| G6 | Fundamentals step-2: revenue-growth / margin-trend are **subsumed by RS** (real ramps, RS-correlated), EPS growth/accel are **U-shaped nulls**, verbatim screen dominated 3× by RS at matched depth, era-fragile. RS stays the one-column gate. | C1 | R1b |
| G7 | **Second axis = SIZE** (cap-decile ramp), coverage-missingness additive within every cap tercile: RS-D10 ∧ smallcap-T1 = 2.4–3.2×, era-stable, vol-matched. Constraint = liquidity ($7.5M/day). | C1 | R1b-axis2 |
| G8 | Incumbent's **first honest full-span cone** (post-gate-fix): median Sharpe 0.47, floor −2.81, 33% neg cells, median ann +9.7%. This is the bar every challenger must clear. | C3 | M4 |

**Corollary — the program is not stuck at selection. It is stuck at monetization (C3).** Steps 1–2
already produce a working watchlist (RS top decile). The open question is whether *any* exit converts
the tail. That is R3, and it is the highest-value fork in the road.

---

## 2. Standing epistemics — keep in mind at EVERY conclusion

These are the recurring ways a conclusion in this program goes wrong. Check each before writing a verdict.

1. **Name the currency (C1/C2/C3).** A ranking result and a P&L result are different claims. Never
   let one stand in for the other.
2. **Don't condition on a mediator.** RS is *downstream* of fundamentals. Conditioning a cause inside
   its own effect nulls it by construction — this is exactly what made R1 read "null" when R1b's
   unconditional test read "subsumed". Before concluding a feature is dead, test it **unconditionally**
   *and* conditionally, and reconcile the two.
3. **MFE is upside-only — it has no downside twin.** `tail_mag` / `home_run` reward max favorable
   excursion. Small/thin/volatile names inflate it mechanically. Every C1 "win" is suspect on
   risk-adjustment until it clears C3, which supplies the MAE/stop reality.
4. **2019+ or it doesn't ship.** The feature edge decays post-2019 (G3). A result that wins only
   pre-2019 inherits the temporal-break suspicion and is excluded.
5. **Monotone *to the top decile*, not decile-7-peak.** A ramp that peaks mid-distribution and fades
   at the extreme is the m02 trap — it is not a usable selector.
6. **Judge on the BackTrader start-date cone, never vec, never one window.** Vec is optimistic
   (no cash-blocking, stop-at-level gaps): median Sharpe 1.51 vs BackTrader 0.35 on the *same* config.
   A single P&L number is a start-date lottery ticket, not evidence.
7. **Don't sweep after seeing the cone.** Tuning a losing config into a marginal win post-hoc is
   fitting the cone. Every parameter choice needs an ex-ante hypothesis. (Killed M3's "force the ML",
   guards R3's trail.)
8. **Selection and exit are COUPLED.** Never conclude "selection X is dead" without stating which exit
   it ran under. M4's whole lesson: the right selection under the wrong exit reads as a null.
9. **Un-mapped ≠ null.** Earnings surprise, estimate revisions, true multi-quarter Code-33 streak are
   **UNTESTED**, not falsified. Only claim null for what was actually mapped and measured.
10. **Population-inflation check.** Pre-gate-fix arena numbers ran on a ~99%-off-setup population and
    are void. Confirm any cited cone is post-SEPA-gate-fix (2026-07-09+).

---

## 3. The roadmap

Dependencies: **R3 is the gate.** R2 is a cheap parallel filler. The m01 de-gate is *downstream of R3*.

```
        ┌── R2 (leadership passport, C1, read-only) ──┐
START ──┤                                             ├──► CONSOLIDATED GROUND TRUTH
        └── R3 (exit×selection cone, C3) ── decides ──┘        │
                                                               ▼
                                          ┌────────────────────────────────────┐
                                          │ DECISION GATE: does the tail convert?│
                                          └────────────────────────────────────┘
                                           │ yes (C wins cone)   │ no (C ≤ B)
                                           ▼                     ▼
                                   D1  de-gate m01 +      D2  close funnel;
                                       refine features        RS+passport =
                                       (now justified)        discretionary aids
```

### R3 — Exit × selection coupling (THE gate) — [plan](r3_exit_selection_coupling_plan.md)
Currency **C3**. 2×2 factorial {champion picker, RS-tail} × {tranche exit, SEPA trail} on the
BackTrader cone. The decisive cell is **C = RS-tail × tail-harvesting trail** — the one pair M4 left
un-run. Add the **size-tilted selection arm** (G7) so R3 prices the small-cap cohort's liquidity and
stop behaviour in the same run — this is where the upside-only-label bias (epistemic #3) finally gets
its downside twin.
**Outputs:** the 2×2 cone table + the per-trade **MFE-capture ratio** (the diagnostic that names the
mechanism). C must beat B on capture *and* A on the cone to claim conversion.

### R2 — Leadership passport (parallel, cheap) — [plan](r2_leadership_profile_eda_plan.md)
Currency **C1**, read-only EDA, no training. **RESOLVED 2026-07-10 (verdict):** NO trait clears the
≥1.3× RS-D10 stack → step 3 **collapses into RS**. Group-leadership traits are RS-clones (ρ 0.57–0.80);
base-character (vcp/tight-base/52w-high) flat-to-inverted; only residual = a volatility tilt
(adr_20d/natr 1.28×, era-stable but below gate and upside-only — same phenotype as G7's size axis, not
new). Passport ships as a **descriptive/manual-review aid** (dashboard column set on the RS watchlist),
not a selection layer. Confirms G2 (no new head beats RS) at the trait level.

### R3b — Rising-trail-from-entry (R3's un-pursued lever) — [verdict](../verdicts/2026-07-10_r3b_rising_trail_from_entry.md)
Currency **C3**. FALSIFIED 2026-07-10: a stop that ratchets from entry (1.5×/2.5×ATR) was meant to
protect champion_trail's median bleed but **eliminates the trend exit** (38%→2%→1%) — it clips the
winners before the SMA break, i.e. amputates the tail that generated the +0.21. Monotone worse tighter
(e25 median 0.32 < champion_trail 0.46; e15 −0.29). The median bleed and the tail are the same coin →
champion_trail is a local optimum in the trail family. No further ATR-level sweep indicated.

---

## 4. The de-gate decision — gated behind R3, with explicit criteria

**Your instinct:** expand m01's training set by removing the breakout gate.
**Why it waits:** removing the breakout gate = training m01 on the full `trend_ok` panel = **exactly
the m01a population**. m01a already showed (G2) ML ties RS on that panel (C2) and (G5) that selection
loses the cone (C3). So a de-gated m01 **inherits m01a's null unless R3 first proves an exit converts
the panel's tail.** De-gating changes *what the model sees*; if the exit truncates that population's
tail regardless (M4's mechanism), the retrain buys nothing. R3 is the precondition that tells you
whether the de-gate is worth the compute.

**RESOLVED 2026-07-10 (R3 verdict):** R3 landed on the **middle row** — `champion_trail` (D) beat the
incumbent by +0.21 median Sharpe (era-robust) while the trail did nothing for RS-tail (C ≈ B). The
improvement is the **exit**, orthogonal to selection; RS-tail selection (what de-gating m01 reproduces)
stays null under the best exit available. → **DE-GATE NOT TRIGGERED, stays parked.** The exit lever's
remaining idea (rising-trail-from-entry) was then CLOSED by R3b (below) — `champion_trail` is the final
candidate exit, pending only its deploy-gate re-confirm. No live modelling thread remains.

**Go / no-go criteria for the de-gate (the table R3 was evaluated against):**

| R3 outcome | De-gate m01? | Rationale |
|---|---|---|
| **C > A**, era-robust (tail-harvest exit converts RS-tail) | ✅ **YES** — de-gate is now justified | The panel's tail is monetizable; a model trained on the panel + the winning exit is the natural champion candidate. Retrain on de-gated population, judge on the same C3 cone, deploy-gate re-confirm before promotion. |
| **D > A but C ≁ B-lift** (trail helps *any* selection) | ⚠️ **NO** — adopt the exit, keep the gate | The improvement is the exit, orthogonal to selection. De-gating adds population noise without a selection payoff. |
| **C ≤ B** (no exit converts the tail) | ❌ **NO** — funnel closes | The tail is un-monetizable in this trade structure. De-gating trains on a population whose edge doesn't survive exits. RS = watchlist-ordering only. |

**If de-gate proceeds (D1), keep in mind:**
- **Target invariance** — m01's training target stays what it is; do not fall back to another outcome
  column because the population widened. Enrich data to keep the target consistent, don't substitute it.
- **Temporal break (G3)** — a de-gated model built from the same feature family will decay 2019+
  unless the *exit* is what carries the edge. Report the pre/post-2019 fold split explicitly.
- **The de-gated population is m01a's population** — reuse the `m01a_tail_v1` panel + trainer harness;
  do not re-derive the label. This is a re-scope of an existing experiment, not a new one.
- **Deploy-gate re-confirm** (SPY-200d trunk) before any registry promotion — non-negotiable.

---

## 5. Program-level done-when

**RESOLVED 2026-07-10 — funnel program CLOSED (branch b, sharpened).** All boxes resolved:
R1/R1b (fundamentals subsumed by RS; size = 2nd label axis), R2 (leadership traits collapse into RS),
R3 (RS-tail un-monetizable under both exits; `champion_trail` a candidate *exit* refinement), R4 (dormant).

- **Selection** = the one-column RS rule. Steps 1–3 of the book all collapse to it. Second axis =
  size/coverage (G7), label-level only.
- **Exit** = `champion_trail` (trend-exit-only) — candidate refinement (+0.21 median Sharpe, era-robust),
  **deploy-gate re-confirm pending** before registry promotion. NOT promoted off the R3 cone.
- **The 63d MFE tail is NOT systematic alpha beyond the incumbent** — doesn't convert under available
  exits (R3), and no trait adds rank-lift over RS (R2). It is watchlist-ordering value.

**Durable deliverables:** the RS rule, the size axis, and the R2 passport (manual-review aid).
**No live modelling thread remains** — R3b closed the last exit idea (rising-trail-from-entry falsified).
The ONLY open action is the deploy-gate re-confirm for `champion_trail` (+0.21, trend-exit-only) before
it is promoted or parked. Roll into the sprint README at wrap-up.
