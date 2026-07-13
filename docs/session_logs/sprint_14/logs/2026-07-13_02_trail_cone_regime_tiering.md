# Session Handover: 2026-07-13 (session 02)

## 🎯 Goal
Close the binary-vs-4class promotion question with the last-mile BackTrader confirm on the
CHAMPION TRAIL-EXIT (not the simple exit), then use that result to answer the user's
higher-order questions about how to actually USE the system — reopening the sprint's
opening regime-quantification loop.

## ✅ Accomplished
- **Q58 — 4-class on the champion trail-exit (the real kill/keep gate).** Registered
  `champion_trail_spygate_4cls` (binary champion config, signal+gate swapped to 4-class
  prod @ 0.60 per user steer: gated-and-ranked, tight gate = tight capacity). Ran the full
  90-cell cone. **Binary WINS decisively**: median Sharpe 0.76 vs 0.33, floor −1.93 vs
  −2.38, %neg 28% vs 38%, median ann_ret 18% vs 5%. Paired 4-class wins only 32%, loses
  every era. The tight gate did NOT rescue 4-class (same variance-knob signature).
  **Binary confirmed as deploy candidate; NOT auto-promoted (held for user go/no-go).**
- **Corrected the user's tail premise.** "Raising the gate widens the tail we want" is a
  LABEL-level illusion on the trail exit: raising the gate lifts only the single `max` cell
  while LOWERING p90/p95 (the harvestable tail body). The exits truncate the tail the gate
  concentrates. So the median-for-tail trade the user hoped for isn't on the menu here.
- **Rotation infra audit (user: "is infra working?").** Traced the worst binary cell
  (2015-07 start, −26%): book rotated 24 trades / 23 unique tickers across 6 months, stop
  fired at ~−11% MAE, 71% stop-out → **infra works as designed.** The failure is structural:
  in chop the replacement pool is the same failing population (IC≈−0.03), so rotating faster
  just pays the stop more. Can't jump to a better ship when all ships sink.
- **Answered the sprint's opening question, made specific (2015).** The weather gauge DOES
  flag 2015-16 as bad: **STAND ASIDE 53%** of the window, SPY>200d only 47% (gate flipped
  11×). Coincident, no lookahead. BUT `stress_high` fired 0 days — it's the **SPY-200d axis**
  that caught it, not stress (2015 was a trend breakdown, not a stress event).
- **Verified the backtest gate is SPY-200d ALONE** (not 6-pillar). Confirmed **no
  portfolio-level DD breaker exists**. Confirmed the residual loss happens THROUGH the open
  gate (71% stop-out on gate-open days).
- **Documented the exploration + a prioritized to-do tracker** (user: this session is
  explore+document only, implementation separate).

## 📝 Files Changed
- `src/backtest/strategy_registry.py`: NEW arm `champion_trail_spygate_4cls` (4-class prod @
  gate 0.60, else == binary champion). Self-check asserts diff-from-champion == {signal, gate}.
- `scripts/run_strategy_confirm.py`: added `proto_cali_gated` signal → the 4-class full-span
  gated cache + MODEL provenance. (No re-scoring — cache built earlier this day.)
- `docs/session_logs/sprint_14/verdicts/2026-07-13_4class_vs_binary_TRAIL_cone.md`: NEW — the
  trail-exit A/B verdict (binary wins).
- `docs/session_logs/sprint_14/plans/2026-07-13_regime_tiering_and_system_usage.md`: NEW —
  research tracker (ground-truth facts, ideas, prioritized to-do). The main deliverable of
  the explore/document half.
- Cone artifacts: `data/selection_sweep/starttime/champion_trail_spygate_4cls/rolling/`.

## 🚧 Work in Progress (CRITICAL)
- **NOTHING implemented from the ideas.** Session was explore + document by user instruction.
  All to-dos (earnings rule, 1-day-delay fan, per-regime gate, DD breaker, m02 reframe) are
  DESIGN-ONLY in the plan doc — implementation is a separate session.
- **Binary is NOT promoted.** The trail cone confirms it wins; the promotion (`set_prod` +
  `backfill_daily_predictions` + rebuild dashboard DB) is a separate user go/no-go.
- `pnl_percent` column in the persisted trade logs is mis-scaled (−639% means impossible);
  the EQUITY curve is the truth. Don't read pnl_percent — a pre-existing log artifact.

## ⏭️ Next Steps
1. **User decision: promote binary?** If yes — `set_prod(binary)` →
   `backfill_daily_predictions --model-version-id <binary>` → rebuild dashboard DB; operating
   threshold by per-day RANK (binary score is discrete/plateaued), not an absolute floor.
2. **🔨 IMMEDIATE builds (design known, separate session):** (a) earnings-proximity entry/exit
   rule; (b) 1-day entry delay on the equity FAN (backtest version was inconclusive).
3. **🔍 NEXT (needs a decision first):** per-regime gate sweep (does higher gate pay in bull?
   — the user's live-pick hunch; Q47 never split by regime); portfolio-level DD circuit
   breaker; regime-tiered fan/cone.
4. The mcap objective fork (tail-odds vs median/Sharpe shortlist) is STILL open from Thread L.

## 💡 Context/Memory
- **The champion ALREADY runs binary** (`signal="binary_gated"`). "Confirm binary" was NOT a
  model swap into the champion — the champion cone IS binary. The missing piece was running
  the 4-CLASS prod model through the champion trail-exit as the A/B. Now done → binary wins.
- **The system is a FILTER, the human is the ranker.** Funnel: ~100k trend_ok/yr → ~10k
  breakouts → ~40/day → ~30 after gate. Blind top-N over the 30 = coin-flip median. The
  realized alpha in past hand-picks lived in the human last mile + regime luck + survivorship
  (user's own read, confirmed). Keep the gate LOW (0.15) for broad raw material; SPY-200d is
  the WHEN lever, human judgment is the WHICH.
- **SEPA is a bull-regime tail strategy, not all-weather** — the honest reframe. Regime-tiered
  usage (§1.2 of the plan) is the right next direction; we lack a validated SEPA-regime label
  beyond SPY-200d, so keep tiers coarse and cone-validate.
- **No band-aid on the tail illusion:** raising the gate does NOT buy a harvestable tail on
  the trail exit (label lift ≠ trade edge, third confirmation).
