# Session Handover: 2026-07-11 (02 — portfolio layer: rotation anatomy, cadence, capacity)

## 🎯 Goal
The user's question — "what does sprint 14 bring us? we're still missing a sound strategy that's
not a lottery, right?" — pivoted the work from the (saturated) SELECTION layer to the untested
PORTFOLIO layer. Open Thread J; lock the strategy purpose; run the rotation/breadth/capacity tests.

## ✅ Accomplished
- **Strategy PURPOSE locked in** (user): the ideal trade = confirmative breakout + strong
  fundamentals + momentum + institutional accumulation → the BREAKOUT population is the intended
  hunting ground BY DESIGN (conviction over coverage), not a historical accident. End product is
  HUMAN-IN-THE-LOOP (system outputs a handful of names; technicals applied by the human). Recorded
  as the Thread J header in RESEARCH_LOG.
- **Q44 rotation anatomy** ✅ (`verdicts/2026-07-11_rotation_anatomy.md`) — from the 90 persisted
  champion cone cells, NO re-runs. Book runs 3.8/5 occupancy, 55% days full, refills SAME day a
  slot frees; ~23 trades/12m, ~29d holds, 52% stop / 45% trend. **Headline: the `no_slots` queue
  is near-book quality** (fwd100 +5.7% / HR 17.5% vs entered +6.4% / 21.0%) → strategy is
  slot-constrained, not signal-constrained. Refill "penalty" decomposes into regime composition.
- **entry_top_n bug FOUND + FIXED** in `SEPAHybridV1._process_entries` — the param was declared but
  NEVER enforced (entries sliced by available_slots only). Champion unaffected (slots=5≡top5;
  regression-verified byte-identical), but any arm with entry_top_n<max_pos was mislabeled. Fix =
  per-bar cadence cap `min(available_slots, entry_top_n)` + new `daily_cap` rejection reason.
- **Q45 temporal breadth (top-1/day)** ✅ WASH (`verdicts/2026-07-11_q45_temporal_breadth_top1.md`)
  — 90-cell paired cone: median 0.65 vs 0.76 (−0.10), IQR −0.32, %neg −2pp; wins 40% of cells.
  The cadence knob doesn't bind: ~29d holds mean slots free ≤1/day anyway, drip reaches 5/5 in ~5
  days. The stagger the fan motivated is already implicit in the slow rotation. Pool variants
  (ii-iv) PARKED (cadence doesn't bind + within-pool re-ranking is a closed kill).
- **Q46 capacity (10 slots @ 10%)** ✅ (`verdicts/2026-07-11_q46_capacity_n10.md`) — one ex-ante
  arm, 90-cell paired cone: median 0.81 vs 0.76 (+0.05 ≈ noise), floor +0.16, but p25 −0.29 / IQR
  +0.42. Q44's queue-quality prediction CONFIRMED in realized P&L: ~2× capital deployable at flat
  expectancy. But NOT a better strategy (extra names add regime-correlated exposure, not
  diversification). **Champion stays 5 slots**; n10 banked as the capacity envelope.

## 📝 Files Changed
- `src/backtest/sepa_strategy.py`: enforce `entry_top_n` per bar; `daily_cap` rejection reason
  (+ docstring line for it). **Real bug fix** — makes S-array baselines honest to their labels too.
- `src/backtest/strategy_registry.py`: added `champion_trail_spygate_top1` (Q45) and
  `champion_trail_spygate_n10` (Q46) candidate arms + self-check asserts.
- `docs/session_logs/sprint_14/RESEARCH_LOG.md`: Thread J (Q41–46) appended.
- **NEW** verdicts: `2026-07-11_rotation_anatomy.md`, `_q45_temporal_breadth_top1.md`, `_q46_capacity_n10.md`.
- Data artifacts: `data/selection_sweep/starttime/champion_trail_spygate_{top1,n10}/rolling/`.

## 🚧 Work in Progress (CRITICAL)
None half-finished. Both new registry arms are `status="candidate"` — champion unchanged.
The `entry_top_n` fix is committed to the working tree; smoke tests (`test_backtest_smoke.py`) pass.

## ⏭️ Next Steps (the remaining ~8 sprint days)
Selection saturated (Threads H/I), portfolio knobs now exhausted (Thread J). What's left is
PRODUCT/INFRA, research de-risked:
1. **Direction C — two-tier human-review watchlist**: breakout tier via m01, trend_ok tier via
   RS×size rules + the relvol defensive tag (session-01 §6c). No retrain (Q43: m01a M3 already
   showed ML ties RS on trend_ok).
2. **Shadow-book Step 6** (nightly orchestrator wiring) — start accumulating live evidence vs the
   backtest cone.

## 💡 Context/Memory
- **Thread J one-liner**: the champion's book design is NOT leaving Sharpe on the table — every
  portfolio knob tested (cadence Q45, breadth Q46, per-name stops §6a, gates beyond SPY-200d §2c)
  is a wash or a variance trade. The residual constraint is REGIME CONCENTRATION, which no
  portfolio knob removes. That IS the honest "is it sound?" answer: positive expectancy, known
  capacity (~2× via slots at the ~$7.5M/day liquidity cap), start-time risk = regime risk.
- The lottery framing is a per-DRAW artifact of the equity fan; the champion is already a rotating
  book that earns the mean via aggregation — the fan just can't show it.
- Cone comparisons judge the DISTRIBUTION (floor/IQR/%neg), never paired win-rate (the gate/mechanism
  is inert in bull windows → paired counts mislead; same lesson as M4/deploy-gate).
