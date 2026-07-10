# R1 — Fundamental coverage audit + within-RS splits (step-2 rescue or clean kill)

**Date:** 2026-07-10 · **Status:** ✅ DONE 2026-07-10, verdict **SCOPE-NARROWED** same day →
reopened as `r1b_step2_book_faithful_plan.md` · **Parent:** `sepa_funnel_meta_plan.md`
**Cost:** 1 session, read-only queries + notebook cells. No training, no long runs.

> **Scope note (2026-07-10):** what M1/M2 killed is "fundamentals add ranking info *beyond RS
> top-decile* at the 63d tail". It is NOT a test of Mark's step 2: RS rating ≥ 70 is trend-template
> criterion #8 (step 1), and conditioning on extreme RS conditions on a *downstream mediator* of
> fundamentals (plus range restriction). The book-faithful test — fundamentals as a threshold SCREEN
> on trend-template survivors, judged on trim/lift/capture, at 63d and 126d — is R1b.

## The question

M3 found 86 features (incl. `eps_accel`, `revenue_accel`, `eps_growth_yoy`, `gross_margin_trend` —
the Minervini step-2 acceleration set DOES exist in `fs_m01_prototype`) tie one-column RS OOS.
Three competing explanations, in order of checkability:

- **(a) Coverage artifact** — EDGAR backfill never run ([[edgar_fundamentals]]); if fundamentals are
  NaN/stale for a large share of the 1.61M-row label panel (especially pre-2015), XGBoost effectively
  trained on price features and the tie is the *expected* outcome, not evidence.
- **(b) Scaling artifact** — raw `eps_growth_yoy` levels aren't comparable across 25 years; RS works
  partly *because* it's a per-date cross-sectional rank. Fundamentals never got that treatment.
- **(c) Genuine null** — fundamentals carry no tail information beyond RS on this panel. Valid; kills
  step 2 beyond RS permanently.

The M3 temporal break (features win pre-2019, lose after) is a secondary diagnostic — (a) predicts the
break tracks coverage improving/regime shifting; a revived edge must survive 2019+ regardless.

## Milestones

- [x] **M0 — Coverage audit (the R4 trigger).** Per-year non-null % for every Fundamentals-group
  column of `fs_m01_prototype` on the `m01a_tail_v1` label panel (join `t3_training_cache` exactly as
  `scripts/train_m01a_tail.py` did — same 86-column availability intersection). Plus staleness:
  `days_since_report` distribution per year (a "non-null" that's 300 days old is still dead).
  **Deliverable:** coverage table + one heatmap cell.
  **Decision:** key acceleration columns (`eps_accel`, `revenue_accel`, `eps_growth_yoy`) >40% NaN or
  chronically stale in a material span of years → **coverage is binding, trigger R4**, and M1/M2
  results are read as lower bounds only.
  *(Completed 2026-07-10: Coverage adequate, ~89-94% for acceleration features. R4 NOT triggered.)*

- [x] **M1 — Within-RS-D10 conditional splits (the rescue-or-kill test).** Within the per-date
  `rs_universe_rank` top decile, split home-run rate (`home_run_63`) and `tail_mag_63` by terciles of
  each acceleration feature, non-null rows only. Baseline to beat: unconditional RS-D10 lift
  (home-run ≈2.5×, tail_mag ≈3.5× — M2 verdict). Anti-tests carried over from m01a: monotone
  *to the top tercile*, and stable across date-thirds (specifically must not die 2019+).
  **Gate:** any feature with a ≥1.3× monotone, date-stable within-D10 split → step-2 revival evidence.
  Nothing clears → step 2 beyond RS is a **clean kill** (subject to the M0 coverage caveat).
  *(Completed 2026-07-10: Null-ish. No feature hit 1.3x monotone lift.)*

- [x] **M2 — Rank-transform re-test (conditional; tests suspect (b)).** Only if M0 says coverage is
  adequate but M1 is null-ish: recompute the M1 splits on per-date cross-sectional
  `PERCENT_RANK` of the same features. This isolates scaling from information content WITHOUT
  re-training any ML. Same gate as M1.
  If a rank-transformed feature clears the gate, ONLY THEN is a model re-test justified — and it
  re-enters through the m01a harness (`train_m01a_tail.py` arms exist) with the RS bar unchanged.
  *(Completed 2026-07-10: Still null-ish. No feature hit 1.3x monotone lift. Clean kill.)*

## Guardrails / gotchas

- All notebook connections `read_only=True`; scope queries to the label panel / `t3_training_cache`,
  never bare `SELECT *` on raw tables.
- `pe_ratio`/`ps_ratio`/`peg_adjusted`/`pb_ratio` are NOT in `fundamental_features` (memory) — expect
  catalog-vs-table mismatches; report them, don't paper over.
- t3 panel is gappy/non-contiguous — the label registry's `source_query` is the canonical row set;
  never re-derive rows.
- Correlation check: any "winning" fundamental must be shown ≠ RS in disguise (within-D10 split
  already mostly handles this; still report the per-date rank correlation vs `rs_universe_rank`).

## Kill criteria (valid outcomes, stated upfront)

- M0 coverage bad → R1 pauses, R4 triggers; no conclusion about fundamentals is drawn from thin data.
- M1+M2 null with adequate coverage → step 2 = RS-only, permanently; annotate the meta plan and stop.
- A split that wins pre-2019 only → inherits the M3 decay verdict, not shippable.

## Done when

One verdict doc (`verdicts/YYYY-MM-DD_r1_fundamental_audit.md`) stating which of (a)/(b)/(c) holds,
with the coverage table and split tables; meta-plan R1 box checked; R4 triggered or declared dead.
