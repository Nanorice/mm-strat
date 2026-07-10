# R1b — Step 2 retested book-faithfully (fundamentals as a screen, not a ranker beyond RS)

**Date:** 2026-07-10 · **Status:** ✅ CLOSED 2026-07-10 — verdict: `verdicts/2026-07-10_r1b_step2_screen.md`
(step 2 SUBSUMED by RS for rev-growth/margin-trend, NULL for EPS pair; screen dominated 3× depth-matched;
no 126d rescue; surprise: missing-fundamental cohort is the hottest, era-stable 2.2–2.9×) · **Parent:** `sepa_funnel_meta_plan.md`
**Reopens:** `r1_fundamental_coverage_audit_plan.md` — whose verdict stands but is **scope-narrowed**:
it killed "fundamentals add ranking info *beyond RS top-decile* at the 63d tail", not Mark's step 2.
**Cost:** 1–2 sessions, read-only queries + cells. No training.

## Why R1's design under-tested step 2 (the user's correction)

1. **RS is a step-1 criterion, not step 2.** Trend template #8 = RS rating ≥ 70 (pref. 80s/90s).
   The repo's `trend_ok` (feature_pipeline.py, C1–C7) carries only a weak RS-line proxy
   (`price_vs_spy > price_vs_spy_ma63`) — the strength floor is MISSING from step 1, and RS-D10 was
   promoted into the step-2 slot. Book-faithful funnel: trend template (incl. moderate RS floor) →
   fundamentals screen → leadership profile → manual.
2. **Conditioning on a mediator.** Fundamentals → outperformance → RS. Splitting *within* extreme RS
   conditions on the downstream variable and screens off the upstream signal (plus range restriction:
   D10 fundamentals variance is compressed). Within-D10 null ≠ panel null.
3. **Horizon mismatch.** The earnings thesis is multi-quarter; `tail_mag_63` is momentum's horizon.
   Fundamentals were never tested at 126d+.

**What R1/M3 DID establish (don't re-litigate):** unconditional ML on the panel (fundamentals in the
feature set) ties RS as a 63d-tail *ranker*, and fundamentals add no *ranking* info within RS-D10.
R1b's questions are different: screen (conjunction + capture), ordering (moderate floor first), and
horizon.

## Milestones

- [x] **M0 — Restore step 1's missing criterion (threshold on OUR definition).** The book's RS
  rating is a 1–99 *cross-sectional percentile*; ours is a raw weighted-momentum composite
  (`rs_rating = 0.4·mom63 + 0.2·mom126 + 0.2·mom189 + 0.2·mom252`, feature_pipeline.py:360) — the
  number 70 does not transfer across scales. Book-faithful floor on our definition = per-date
  percentile of that composite (`rs_universe_rank`), swept at **≥ 70 / 80 / 90th pct** (the book's
  "70 floor, preferably 80s/90s"; note ≥90 ≈ the RS-D10 cut — same axis, different depth). Measure
  the funnel triple at each cut: names remaining, tail lift, home-run capture (% of all panel
  home-runs surviving). **Scratch code only** — query-level funnel stage in a scratch script; NO
  changes to `feature_pipeline.py`/`trend_ok`/t2/t3 or any `src/` module at this stage.
  **Deliverable:** the corrected step-1 gate definition + its triple per cut.

- [x] **M1 — Quantify the book's step-2 preferences holistically (not lift-first).** On the trend
  panel (NOT within RS-D10), for each mapped criterion (`eps_growth_yoy`, `eps_accel`,
  `revenue_growth_yoy`, `revenue_accel`, `gross_margin_trend`):
  (a) **Distributional portrait** — full distribution on the panel, among book-threshold passers, and
  among realized home-runs vs rest (the R2 contrast method applied to step 2); per-criterion pass
  rates over time (does "EPS ≥ 25%" select 5% of names in 2009 and 40% in 2021? — a preference whose
  selectivity swings that much means the book number needs a per-era reading);
  (b) **Mediation check** — unconditional decile ramps vs `home_run_63`/`tail_mag_63` + per-date rank
  corr vs `rs_universe_rank` (fundamentals→RS link);
  (c) **Interaction structure** — pairwise joint pass rates (does the book's conjunction select a
  coherent cohort or an empty intersection?).
  **Readout logic:** forward-return lift is ONE lens, not the verdict. Ramps monotone unconditionally
  + dead within-D10 (R1's result) → fundamentals are *upstream of RS* — "subsumed", not "null".
  Flat unconditionally → genuine null. Either way (a) and (c) fill the mapping table on their own —
  the quantification of Mark's preferences is a deliverable independent of whether it carries alpha.

- [x] **M2 — The book-faithful step-2 SCREEN, judged holistically.** Fundamental thresholds from the
  book VERBATIM (growth %s are scale-free so they transfer, unlike RS): EPS growth YoY ≥ 25%, sales
  growth YoY ≥ 20%, margin trend > 0 (expanding), acceleration > 0 where coverage allows (`eps_accel`,
  `revenue_accel` — the Code-33 shadow). Apply as a conjunction on M0's corrected step-1 survivors
  (scratch code only, as M0). The verdict is a **holistic profile of what the screen selects**, not a
  single lift number:
  - the funnel triple (trim ratio, tail lift, home-run capture) — the alpha lens;
  - **who survives** — sector/cap/age composition of passers vs the panel (does it select the book's
    archetype: young growth leaders — or accidentally load on one sector/era?);
  - head-to-head vs RS-percentile floors from M0 **and their conjunction**: triple + name overlap
    (Jaccard) — substitutes, complements, or orthogonal;
  - era stability (date-thirds; flag but don't auto-kill on 2019+ weakness — characterize WHEN the
    screen works, per [[project_regime_during_period_goal]]);
  - missing-fundamental rows as their own tracked bucket, never silently dropped.
  Threshold sensitivity (±10pts) secondary only — book numbers are the spec.

- [x] **M3 — Horizon extension.** Repeat M1 + M2 lift/capture at `MFE_126` (computed in-query like the
  m01a M0 sweep; no new label registration unless it wins). If fundamentals separate at 126d but not
  63d, step 2 is real but slower than the trading horizon → feeds R2's passport and the watchlist
  ordering, and flags that the 63d label under-serves the earnings axis.

## Guardrails / gotchas

- `read_only=True`; label rows from `m01a_tail_v1` `source_query`; MFE_126 windows strictly forward,
  entry-day excluded (LeakageGuard convention).
- Coverage is adequate (~90%, R1-M0) — but staleness still applies; use `days_since_report` to
  exclude zombie fundamentals (> 1 quarter + grace) from the screen rather than treating them as pass.
- t3 panel gappy — never shift(-1) on t3; forward paths from `price_data`.
- Report every criterion that CANNOT be mapped (earnings surprise, estimate revisions, true Code-33
  streak, base count) in the meta-plan mapping table as UNTESTED — an unmapped criterion is not a null.

## Kill criteria (valid outcomes — they kill the ALPHA claim, not the deliverable)

The holistic quantification (distributions, pass rates, survivor profiles, mapping table) ships
regardless of outcome — that's the "quantify Mark's preferences" goal and it can't fail, only inform.
What the gates decide is the *funnel-stage* question:

- M1 flat unconditionally AND M2 screen adds no lift/capture advantage over the RS floor at both
  horizons → step 2 carries no selection alpha beyond RS on our data; R1's verdict upgrades from
  scope-narrowed to general. Mapping table still filled.
- M2 screen ≈ RS floor with high overlap → substitutes; keep RS as the operational gate (one column
  beats five thresholds), mapping table records "subsumed".
- Screen works only in some eras → not a standing gate; record WHEN it works as part of the holistic
  profile (candidate regime-conditional stage, decision deferred).
- Any WIN here is label-level (watchlist/funnel value). Monetization claims still route through R3's
  harness — no strategy claims from EDA.

## Done when

Verdict doc (`verdicts/YYYY-MM-DD_r1b_step2_screen.md`) with the funnel triples (RS floor, screen,
RS-D10, conjunction × 2 horizons), the mediation readout, and the meta-plan mapping table updated
row-by-row (proven / subsumed / null / untested per criterion).
