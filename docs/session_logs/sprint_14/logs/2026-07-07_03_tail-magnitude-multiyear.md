# Session Handover: 2026-07-07 (session 03 — M1 tail-magnitude + 25-year regime sweep)

## 🎯 Goal
Land meta-question **M1** (re-cut the home-run objective from binary >30% count to tail-MAGNITUDE),
then — per user — validate it across regimes before moving on, and answer three follow-up questions
about the model's crash behaviour, basket width, and how to deploy limited capital without bad-start drag.

## ✅ Accomplished
- **M1 done — objective re-cut to tail-magnitude.** Pure re-analysis of the existing 2025 parquet.
  The gate misses **14.2% of tail MAGNITUDE, not 23.4% of home-run EVENTS** (Q7's number overstated
  the leak ~40% — the missed home-runs are the SMALL ones). Reusable metrics: `Σ max(fwd−30%,0)` +
  **tail-lift@top-k**. Feed M3 (stability target) + M4 (rank-of-tail eval).
- **Answered the scope/horizon question (#1):** the "good tail-ranker" claim is point-in-time
  full-universe RAW score, 20d fwd; the "weak ranker (4×)" was the OPPOSITE conditioning (inside the
  ~6-name gated pool / on the flattened calibrated score). Decomposed the 6.1× top-1% lift: ~half is
  the gate re-expressed, **residual above-gate edge is 3.2×** (2025) — that's the real selection edge.
- **Ran the full 2001–2025 universe sweep (25 years, cached).** Result: the score is a
  **PRO-CYCLICAL** tail-ranker — median top-1% lift 6.8× but **0.68× (below no-skill) in 2001/2008
  crashes**; above-gate edge negative-to-nil in 5/25 yrs; corr(lift, home-run-rate) = **−0.44**. The
  ONLY regime-robust result is `miss_mag < miss_count` (25/25) → adopt the metric, treat ranking as
  a distribution.
- **Thread E (user Qs 13–15):**
  - **Q13** — pro-cyclicality is a SCOPE boundary, not a defect: SEPA excludes crash-bottoms; model
    is CONTINUATION not reversal. Bad-regime floor is a pessimistic full-universe read.
  - **Q14** — widening top-5→top-10 does NOT catch more winners (+2.30% ≈ +2.36%); sharp cliff at 5.
    Argues AGAINST the S13 "widen the basket" plan → narrow top-5.
  - **Q15** — **SPY>200d is a real ex-ante deploy gate** (top-5 fwd +3.0% vs +0.6%, 25y); VIX is NOT
    (inverts, high-VIX days are best). Residual 42% bad-day rate → stagger entry, don't time it.

## 📝 Files Changed
- `docs/session_logs/sprint_14/scripts/m1_tail_magnitude_recut.py`: **new** — single-year M1 re-cut (+ chart).
- `docs/session_logs/sprint_14/scripts/score_universe_multiyear.py`: **new** — resumable toolkit, scores full universe per year (RAW p_pos, calibrator bypassed), caches one parquet/year.
- `docs/session_logs/sprint_14/scripts/m1_multiyear_analysis.py`: **new** — cross-regime table + shaded chart.
- `docs/session_logs/sprint_14/scripts/capital_deployment.py`: **new** — Thread E Q14/Q15 tables (basket width, SPY-200d gate).
- `docs/session_logs/sprint_14/verdicts/2026-07-07_tail_magnitude_recut.md`: **new** — M1 verdict + 25-regime section + Finding 2b.
- `docs/session_logs/sprint_14/verdicts/2026-07-07_capital_deployment.md`: **new** — Thread E write-up + design direction.
- `docs/session_logs/sprint_14/cells/m1_tail_magnitude_cells.md`, `m1_multiyear_cells.md`: **new** — reviewable cells + embedded charts.
- `docs/session_logs/sprint_14/cells/binary-model-eda.ipynb`: user pasted M1 cells into the notebook.
- `docs/session_logs/sprint_14/RESEARCH_LOG.md`: Q7 resolved, M1 marked done, **new Thread E** (Q13–15).
- `data/model_output_eda/multiyear/`: 25 per-year parquets + table CSV + chart (scratch/gitignore-class).
- Memory: new `project_tail_magnitude_objective`, `project_capital_deployment`; MEMORY.md index.

## 🚧 Work in Progress (CRITICAL)
- **Nothing half-finished** — M1 is landed and Thread E is recorded. But two claims are FULL-UNIVERSE
  and need re-cutting on the **SEPA-eligible** universe before they're trusted for M3: the bad-regime
  lift floor (0.68×) and the pro-cyclicality magnitude. Read the *direction* (continuation-not-reversal),
  not the exact numbers.
- **All fwd-return, no exits/sizing/liquidity** — everything here is directional, not tradable P&L.

## ⏭️ Next Steps
1. **(b) — the deferred piece: does the SPY-200d gate SHRINK the start-date cone?** Not just lift the
   mean — narrow the Sharpe *distribution* across start-months. This needs the actual backtest/WFO
   harness (`run_strategy_wfo.py`), not a cache re-slice. **This IS the first real M2-cone test and
   the entry into M3.**
2. **M3** — stability-first strategy selection using the tail-lift objective, judged on the
   bad-regime FLOOR (where the edge is ~0), not the bull ceiling.
3. **M4** — magnitude/quantile regressor design doc; must be regime-conditioned / tail-weighted on
   down years or it inherits the pro-cyclicality. Pick an id ≠ M03 regime.
4. **Regime detection** promoted to critical-path — M1 quantified the payoff (8.8× good vs 1.4× bad).
5. Ops carryover (from S13): clean_dirty_shares on sh019; t1_macro June gaps.

## 💡 Context/Memory
- **M2 is NOT skipped — it's been absorbed.** M2 = "single-Sharpe is unsafe → decisions go through a
  start-date cone (distribution not aggregate)." This session validated M2's claim 3× (the 25-yr
  sweep is a coarse cone; Q15's "42% neg days → stagger not time"; and (b) is literally a cone test).
  M2 reframed from a standalone deliverable into the **evaluation lens (b) applies** — don't
  re-litigate whether to "do M2"; (b) is it.
- **The recurring lesson, refined:** the score is a strong GATE, a weak within-pool ranker, and a
  strong-but-PRO-CYCLICAL full-universe tail-ranker. The alpha lives at the sharp top-5 of the
  continuous score, only in up-regimes, only for continuation setups.
- **Design direction crystallised:** continuation-only, SPY-200d-gated, sharp top-5 (not wider),
  staggered-entry book. This is the product hypothesis Thread E points to.
