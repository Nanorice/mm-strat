# Research plan — m01a: the tail-objective trend-panel ranker

> **Suite name:** `m01a` (user-named). **Proposed registry `model_name`:** `m01_tail` — parallel to the
> existing `m01_binary` / `m01_rank` descriptive-suffix convention (letter-vs-word `m01a` breaks parity in
> `SELECT DISTINCT model_name`). Suite = m01a; registry id = m01_tail unless the user prefers the letter.
> **Versioning within suite:** `m01a_v{N}_h{HORIZON}` (e.g. `m01a_v1_h63`) so the horizon sweep produces
> legibly-named siblings and the winning horizon is encoded in the id.

**Date:** 2026-07-10 · **Status:** 📋 PLAN (not started). Supersedes the SELECTION question in
`population_rectification_plan.md`. Parent diagnosis:
`../verdicts/2026-07-09_population_reframe_tail_ranker.md`.

## The thesis in one line

Rank the **full `trend_ok` panel** (Minervini's persistent stage-1 watchlist) by **tail probability**
(home-run / `Σmax(fwd−k%,0)`), demote **breakout → entry trigger**, hold with the **SEPA event-terminated
exit** (undefined horizon). Fixed horizon to *rank*, undefined horizon to *hold*.

## What's already evidenced (don't re-litigate)

- RS ranks the trend-panel **tail monotonically 5.7×** (home-run rate D1 2.2%→D10 12.7%) while the
  **median inverts** — verdict probes 1&2. So: tail objective, not median; RS is a proven axis.
- The breakout pool carries **no privileged info** (decile ramp identical to trend panel) → breakout is
  timing, not selection.
- Prior m02_breakout NULL is the standing warning: **event-prediction ≠ tradeable edge**; m02's returns
  were **non-monotone** (peaked decile 7, died decile 10) = "top decile buys the top". Every milestone
  below must prove monotonicity survives *to the top decile* on the *entry-conditioned* statistic.

## Target & horizon definition (the core design decision)

**Two-clock split** — this is the whole answer to "horizon isn't fixed per SEPA":
- **Ranker label horizon = FIXED, policy-free.** The label is a pure property of the forward price path
  (MFE over N days), independent of any exit rule → measures "big move in the tank", not exit skill.
  Keeps the ranker un-circular (the m2b entanglement trap).
- **Trade/hold horizon = EVENT-TERMINATED (SEPA).** "Undefined holding, trail until trend breaks" lives
  in the *backtest exit policy* (`effective_exit_date` machinery already does this), NOT in the label.

**Label candidates (decide in M0):**
- Binary: `1[ MFE_over_N_days > k% ]`, k=30 (home-run) — simplest, matches the probe.
- Continuous tail-magnitude: `Σ max(MFE_over_N − k, 0)` per [[project_tail_magnitude_objective]] — richer
  gradient, the objective that memory already argued for.
- N chosen by **evidence in M0**, not hardcoded: sweep N ∈ {21, 42, 63, 126}, pick where the RS→tail
  monotonicity is strongest AND most start-date-stable.

## Milestones

- [x] **M0 — Horizon & target selection (read-only, no training).** ✅ DONE 2026-07-10 — **GATE
  PASSES: N=63, label = continuous `max(MFE_63−0.30,0)`** (binary home-run as diagnostic). Top-end
  strictly monotone in every horizon × date-third; N=63 most date-stable (D10/D1 5.7–6.7×).
  `../verdicts/2026-07-10_m0_horizon_sweep.md`.
  One query per N ∈ {21,42,63,126}: RS-decile → {home-run rate, P90, `Σmax(MFE−30,0)`}, on the
  **entry-conditioned** forward path (enter at close, MFE from next bar — not unconditional).
  **Deliverable:** a chosen N + label form, justified by (a) monotonicity holds *to D10* (the m02 anti-test)
  and (b) start-date stability of the ramp (split the sample into date-thirds, ramp must survive all three).
  **Gate to proceed:** if no N gives a to-the-top monotone, date-stable ramp → STOP, escalate: the edge is
  not a cross-sectional selection signal and the honest pivot is regime/risk framing
  ([[project_capital_deployment]]). Cheapest possible falsification, run FIRST.

- [x] **M1 — Label build + leakage audit.** ✅ DONE 2026-07-10 — `label_registry/m01a_tail_v1.json`
  via `scripts/build_m01a_tail_label.py`; 1.61M rows, 11.45% positive; LeakageGuard 1500-row audit
  clean. Corrupt-high dirt class found & source-nulled (178 bars, cleaner part G; EXEL 999.99).
  `../verdicts/2026-07-10_m1_label_m2_rs_baseline.md`.
  Materialize the M0 label on the `trend_ok` panel via a `LabelDefinition` (`label_registry/`) with
  `horizon_days=N`, `exit_rule='fixed_horizon'`, `target_col`. Run `LeakageGuard` — the fixed-horizon MFE
  must not leak (window strictly forward of entry, entry-day excluded per existing view convention).
  **Deliverable:** `label_registry/m01a_tail_v1.json` + leakage report clean.

- [x] **M2 — Baseline ranker = RS-only, no ML.** ✅ DONE 2026-07-10 — the bar: top-decile tail_mag
  lift **3.5×** / top-5% **4.2×** (home-run 2.5×/2.7×), stable across thirds; ramp still rising inside
  the top decile. `../verdicts/2026-07-10_m1_label_m2_rs_baseline.md`.
  Before any XGBoost: does the *single feature* (RS_Universe_Rank) already deliver the edge? Rank the panel
  by raw RS, measure top-decile lift vs universe on the label. This is the honesty floor — the ML model
  must **beat RS-alone** to justify its existence (ponytail: don't train a model to reproduce one column).
  **Deliverable:** RS-only lift table = the bar M3 must clear.

- [x] **M3 — ML ranker (m01a_v1).** ❌ GATE FAILS 2026-07-10 → **kill criterion #2: ship the
  one-column RS rule.** Tweedie + binary variants (86 feats, anchored WF 2003→, 15 OOS folds
  2012–26, embargo 100d): D10 lift 3.88×/3.93× vs RS 3.87× — a wash; beats RS only pre-2019
  (6/7 folds), loses 2019+ (13/16). Objective-agnostic, un-tuned by design. Selection signal =
  `RS_Universe_Rank` top decile. `../verdicts/2026-07-10_m3_ml_vs_rs_bar.md`,
  `scripts/train_m01a_tail.py`.
  XGBoost on the `trend_ok` panel, tail label, `fs_m01_prototype`-style feature set (RS + fundamentals +
  alphas + regime). Objective matched to label (binary logistic or ranking/regression on tail-magnitude).
  **No balanced-class reweighting that fights the imbalance** — the imbalance IS the signal
  (verdict). Temporal split, register as `m01a_v1_h{N}`.
  **Gate:** must beat M2 RS-only lift by a margin that survives the start-date cone, else RS-only wins and
  ML is dropped.

- [x] **M4 — Backtest.** ❌ GATE FAILS 2026-07-10 → **kill criterion #3: incumbent stays champion.**
  Clean A/B (champion exits, top-5 slots, BackTrader, 90 quarterly-start × 12m cells 2003–26, gated
  pop): `rs_tail` median Sharpe 0.10 / 47% neg cells vs `champion_gated` 0.47 / 33%; rs wins 33/90
  paired cells, loses every era. Not under-deployment (equal trade counts) — label-level tail lift
  doesn't convert under stop+tranche exits (median inverts, exits truncate the tail). Side
  deliverable: first post-gate-fix incumbent reference cone (median 0.47, floor −2.81).
  `../verdicts/2026-07-10_m4_rs_tail_backtrader_cone.md`.
  Selection = top-X% of m01a score on the trend panel; entry trigger = breakout/VCP on those names; exit =
  event-terminated SEPA trail. Judge on the **start-date cone** (not single window —
  [[project_champion_starttime_dependent]]) and confirm on **BackTrader** (vec is ~3× optimistic —
  [[project_vec_engine_optimistic]], [[project_minervini_progfills_fails_bt]]).
  **Deliverable:** cone median Sharpe + %neg folds vs the incumbent native-tranche champion on the gated pop.

- [x] **M5 — MOOT 2026-07-10:** champion unchanged by M4, and its SPY-200d deploy gate was already
  BackTrader-confirmed on the gated population (2026-07-09, Q26). Nothing to re-confirm.
  Tail edge is likely pro-cyclical ([[project_tail_magnitude_objective]]). Re-confirm SPY-200d deploy trunk
  + 6-pillar stress dial ([[project_capital_deployment]], [[project_entry_timing_macro_axis]]) as the
  during-period DD control on the new champion.

## Done when

m01a champion named + registered, horizon N data-justified, ranker beats RS-only, backtest confirmed on
the **BackTrader cone** (not vec, not single window) vs the incumbent, deploy-gate re-confirmed. Every
superseded selection claim in `population_rectification_plan.md` annotated "selection superseded → m01a".

> **CLOSED 2026-07-10 — outcome: kill criteria #2 and #3 both fired.** M0–M2 passed (N=63 label,
> RS-only bar 3.5×/4.2×); M3 ML tied RS → the selection signal is the one-column RS rule; M4 the RS
> rule lost the BackTrader cone to the incumbent → **champion unchanged**. The durable deliverables:
> the `m01a_tail_v1` label + registry, the RS tail-lift finding (label-level watchlist ranking), the
> incumbent's first post-gate-fix reference cone, and the arms/loaders in the registry for future A/Bs.
> Every kill was reached in the plan's cheap-first order — this is the plan working, not failing.

## Kill criteria (state upfront, honesty guard)

- M0 ramp not monotone-to-D10 or not date-stable → not a selection signal, pivot to risk framing.
- M3 doesn't beat M2 RS-only → ship the one-column rule, no ML.
- M4 cone median ≤ incumbent on BackTrader → m01a is a vec mirage like m2b; incumbent stays champion.
Any of these is a *valid* result, not a failure — the point is to find out, cheaply, in that order.
