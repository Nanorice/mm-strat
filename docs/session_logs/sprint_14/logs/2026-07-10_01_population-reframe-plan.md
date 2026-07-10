# Session Handover: 2026-07-10

## 🎯 Goal
Step back from the "trading is a start-date lottery, not a strategy" symptom and challenge the whole
SEPA project path from first principles — specifically: why is the model population limited to breakouts?

## ✅ Accomplished
- **Diagnosed the root flaw:** the project collapsed Minervini's two-stage funnel (persistent ranked
  *watchlist* → breakout *trigger*) into one — `trend_ok AND breakout_ok` was made BOTH the T3 universe
  AND m01's training population. Training a ranker on the post-trigger slice is circular (the breakout
  already spent the signal → IC ≈ −0.03), and a breakout-only universe is a clustered event stream →
  the start-date lottery is a direct consequence, not a separate bug.
- **Ran 2 read-only probes** (price_data fwd-60d, RS_Universe_Rank, NTILE(10)/date, 2010–24) that
  DECIDED the reframe:
  - MEDIAN lens: RS ranking INVERTS (weak-RS > strong-RS); breakout pool ramp IDENTICAL to trend panel
    → breakout gate carries no privileged info → refutes the *naive* pivot.
  - TAIL lens (decider): home-run rate (>30%) is MONOTONE up the RS ladder 2.21%→12.66% = **5.7×**;
    P90 17.2%→34.7%. Strong-RS trend stocks win the tail, lose the median.
- **Distinguished the reframe from the parked m02_breakout** (which was NULL): m02 predicted the *event
  timing* (`breakout_proximity`) and its returns were NON-monotone (peaked decile 7, died decile 10);
  the new model predicts *outcome magnitude* and is monotone to D10. Different question, opposite shape.
- **Resolved the horizon question** ("not fixed per SEPA"): two-clock split — FIXED horizon to *rank*
  (policy-free label), UNDEFINED SEPA horizon to *hold* (event-terminated exit in the backtest, which
  `effective_exit_date` already does). Confirmed the current `mfe_pct` is already event-terminated.
- **Drafted the research plan** for the new model suite `m01a` (registry `model_name` = `m01_tail`,
  user-confirmed), M0–M5 ordered cheapest-falsification-first, with explicit kill criteria.

## 📝 Files Changed
- `docs/session_logs/sprint_14/verdicts/2026-07-09_population_reframe_tail_ranker.md`: NEW — the
  diagnosis + both probe tables + the 3-change reframe + honesty guards. (Dated 07-09 by the probe run;
  session spans the midnight boundary.)
- `docs/session_logs/sprint_14/plans/m01a_tail_ranker_plan.md`: NEW — the m01a/m01_tail research plan.
- `memory/project_population_reframe_tail_ranker.md`: NEW — cross-session fact.
- `memory/MEMORY.md`: index pointer added.

## 🚧 Work in Progress (CRITICAL)
- **Nothing built/trained.** This was a diagnosis + planning session. The plan's **M0 has NOT run** —
  it is the next action and it GATES everything.
- The 5.7× tail probe used **UNCONDITIONAL** 60d MFE (not entry-conditioned) and a single horizon.
  M0 must re-run it entry-conditioned, across N ∈ {21,42,63,126}, and verify monotonicity holds **to
  D10** (the m02 anti-test) and is date-stable — before any label/model is built.

## ⏭️ Next Steps
1. **Run M0** (read-only, no training): RS-decile → {home-run rate, P90, Σmax(MFE−30,0)} for
   N∈{21,42,63,126}, entry-conditioned, split into date-thirds for stability. Pick N + label form.
2. **M0 gate:** if no N gives a to-D10 monotone, date-stable ramp → STOP and escalate to regime/risk
   framing (do NOT force the selection thesis).
3. Then M1 (label build + LeakageGuard), M2 (RS-only baseline = the bar ML must beat).

## 💡 Context/Memory
- **The median was the trap the whole time.** Every prior flat/inverted ranking result
  ([[project_stage_gate_falsified]], [[project_breakout_pool_refinement]] IC≈−0.03) measured central
  tendency; the edge is entirely right-tail. This is why [[project_tail_magnitude_objective]] kept being
  right.
- **m02 lesson governs the build:** "the signal works ≠ the trade works." A pretty decile ramp is
  necessary, not sufficient — must survive entry-conditioning + start-date cone + BackTrader before promotion.
- **Two-clock split** is the reusable idea: rank on a fixed policy-free horizon, hold on the SEPA
  event-terminated horizon. Keeps selection un-entangled from exit mechanics (the m2b circularity trap).
- Naming: suite `m01a`, registry `m01_tail` (parallel to `m01_binary`/`m01_rank`), versions
  `m01a_v{N}_h{HORIZON}`.
