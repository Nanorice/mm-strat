# Sub-plan: population-fix rectification — re-derive the arena honestly

> **Trigger.** The SEPA-gate fix (`src/backtest/sepa_gate.py`, verdict §7) revealed that the whole
> Sprint 13 Strategy Arena selected top-5 from a **~99% off-setup population** — `score_from_t3`
> scores the entire trend-active panel and NO `trend_ok AND breakout_ok` gate was applied at
> selection time. So every Sprint 13 conclusion (delay sweep, exit grid, the `sl15×tpTight` champion,
> the OOS gate, the start-time cone) and the Sprint 14 m2 cone were fit on the wrong population.
> `strategy_registry.champion` is a config fit on inflated data.
>
> This plan re-derives them on the gated population. Parent verdict:
> `../verdicts/2026-07-09_regime_governor_backtest.md` (§7 is the fix; task (a) is milestone 1 here).

## Reordering rationale (why not the user's literal 0→1→2→3)

The user's first-pass order was `0. impl minervini exit+entry → 1. re-run arena → 2. re-run m2 cone
→ 3. revisit SPY-EMA trunk + 6-pillar stress`. Two problems, corrected below:

1. **"Include Minervini in the arena" is not a step — it's the engine port.** The §7 re-run already
   proved that in a fixed-hold basket lens the Minervini tight-stop asymmetry (payoff 3.59→1.81) is a
   **NULL** because the lens can't harvest it: "only harvestable in the ENGINE (trailing
   stop-to-breakeven + progressive fills)". So step 0 = port `exit_policy='minervini'` into
   `vectorized_backtest.py`; without that capability the arena can only reproduce the NULL.
2. **Step 3 (deploy gate) is ~80% banked and orthogonal** to which exit policy wins. It's a
   *portfolio exposure* question ([[project_capital_deployment]]: SPY>200d real +3.0% vs +0.6%; VIX
   inverts; 6-pillar stress is a during-period DD dial). It doesn't depend on the new champion, so it
   runs in parallel, not last.

**Scope guard (honest, from §7b).** The breakeven-ratchet ALONE may still NULL — the selection is a
fixed day-0 top-5 lottery, and asymmetry needs position-level path-dependence to harvest. Build the
ratchet first (cheapest), test it, and add progressive fills ONLY if the ratchet alone doesn't move
the median. Do NOT build the full Minervini stack speculatively.

## Milestones

- [ ] **M1 — Engine: `exit_policy='minervini'`** (verdict task a).
  Port a breakeven-ratchet trailing stop into `vectorized_backtest.py::_simulate_exits`:
  tight initial stop (e.g. 8%), ratchet the stop to breakeven once price hits a +trigger (e.g. +10%),
  then trail. New kwargs: `be_trigger_pct`, `trail_pct` (reuse `stop_loss_pct` as the initial stop).
  Gate with a `__main__`/`test_*` self-check that the ratchet actually moves the stop up (asserts on a
  synthetic price path). Progressive fills = phase-2, only if ratchet NULLs.
  **Status:** ✅ DONE (2026-07-09). New kwargs `be_trigger_pct`, `trail_pct`; `stop_loss_pct` = tight
  initial. `exit_policy='minervini'` in `_simulate_exits`: armed once run_high ≥ entry×(1+trigger),
  then stop = max(entry, run_high×(1−trail)) — ratchets up only. Self-check
  (`_minervini_selfcheck`) + scratch smoke both green: ratchet lets a winner run above the tight stop,
  and fires the trail at a **+9.8% profit-lock** vs the −8% initial. Existing guards
  (`test_backtest_smoke`, `test_sepa_gate`) pass.
  **Phase 2 — progressive fills DONE (2026-07-09, per user steer "add progressive fills first").**
  New kwargs `progressive_fills`, `starter_frac`, `add_trigger_pct`. Starter position at entry, adds to
  full once price first clears +add_trigger_pct; the added capital earns only the post-trigger path
  (winners scale up, losers that never trigger stay starved). Wired into the equity curve (per-bar
  size weight), NOT into per-share `pnl_pct` (sizing is a portfolio-weight effect, not a price effect).
  Self-check `_progressive_fills_selfcheck` proves loser-starving (−3.6% vs −7.0% flat). All 22 backtest
  guards pass.
  **RESULT — progressive fills is the load-bearing piece, confirms §7b exactly.** Gated 2021-23 basket:

  | arm | n | Sharpe | ann | maxDD | avg_pnl | win% |
  |---|--:|--:|--:|--:|--:|--:|
  | sma (15% stop) | 129 | 0.03 | −4% | −47% | −1.1% | 31% |
  | minervini ratchet-only | 235 | 0.35 | +6% | −31% | 0.1% | 41% |
  | **minervini + prog-fills** | 235 | **1.19** | **+33%** | **−20%** | 0.1% | 41% |
  | minervini wide-trail (20%) | 165 | 0.33 | +6% | −40% | −0.1% | 22% |
  | minervini wide + prog | 165 | 0.89 | +24% | −30% | −0.1% | 22% |

  Ratchet-ALONE NULLs (0.35, below other windows); **progressive fills lifts Sharpe 0.35→1.19**. The
  trade-level avg_pnl is IDENTICAL (0.1%) ratchet-only vs +prog — the entire uplift is capital-weighting
  winners over losers in the equity curve, the honest signature of press-winners/starve-losers.
  ⚠️ Single window / one param set / pool-scaling interaction un-gated — that's M2/M3's job.

- [ ] **M2 — Re-run the arena on the gated population** with `minervini` in the exit grid.
  Focused head-to-head (user steer): minervini vs sma, each as a LOCKED-policy WFO cone so each gets the
  full trial budget in its own subspace (a free-choice optimizer under-samples minervini — smoke picked
  nday both folds at 8 trials). `minervini`+progressive-fills knobs added to `suggest_params`;
  `LOCK_EXIT_POLICY` env var pins the policy per run. Both cones: 2003-2026, 2yr-train/1yr-test rolling
  folds, 40 trials/fold, gated cache. Judge the per-fold Sharpe CONE (start-date robustness), not the
  single-window IS — that's the whole verdict lesson.
  **Status:** ✅ DONE (2026-07-09). **Minervini+prog-fills WINS the cone:** median 1.00→1.44, %neg folds
  25→5%, worst fold −1.30→−0.09, beats sma in 16/21 folds, rescues the GFC/2017 losers. Prog-fills chosen
  20/21 folds. Sprint 13 `sl15×tpTight` champion superseded + annotated as inflated. Verdict:
  `../verdicts/2026-07-09_m2_minervini_vs_sma_gated_cone.md`. **NOT yet in `strategy_registry`** — vec
  kwargs ≠ BackTrader kwargs; needs a BT-confirm first (new task, see M2b below).

- [ ] **M2b — Port progressive fills into `SEPAHybridV1` + BackTrader-confirm** before promoting to
  registry champion. The M2 cone is vectorized; prog-fills is exactly the path-dependent sizing where
  vec↔BT diverge, and the Sprint 13 champion was only promoted after a BT confirm. Do NOT skip.
  **Status:** 🔄 IN PROGRESS (2026-07-09).
  - ✅ **Ported** (user steer: "progressive fills as a pre-tranche scale-in"): `SEPAHybridV1` gets
    `progressive_fills`/`starter_frac`/`add_trigger_pct` params; `_enter_position` buys the starter,
    `_check_adds` scales in on the +add_trigger cross; `PositionTracker.confirm_add` grows shares +
    blends the cost basis; tranche math keys off the FINAL target size. Default off = byte-identical
    (all 19 guards pass). New state-math test `tests/test_progressive_fills.py`.
  - ✅ **Smoke (2024 gated):** prog-fills lifts BT Sharpe **0.81→1.34** — fidelity engine confirms the
    vec direction with real cash-blocking + next-open fills.
  - ⚠️ **BUG CAUGHT + FIXED:** the BT confirm harness (`run_strategy_confirm._load_scores` +
    `prototype_scores_to_contract`) DROPPED `trend_ok`/`breakout_ok`, so the first M2b run re-inflated
    the population (the exact bug this plan fixes). Both now pass the flags through → ScoreLookup
    restores the breakout gate (verified: "gate disabled" warning gone). This bug would have silently
    poisoned ANY gated BackTrader run, not just M2b.
  - ❌ **CONFIRM FAILS (2026-07-09).** BT cone: baseline median 0.53 / progfill 0.35, %neg **45% both**
    (vs vec 5%). Progressive fills is a WASH on BT. Fixed-config apples-to-apples proves the gap is the
    ENGINE not tuning: same config, vec median 1.51 / %neg 10% vs BT median 0.35 / %neg 45% — vec is ~3×
    optimistic, concentrated in bear folds (no cash-blocking, stop-at-level gap understatement).
    **Champion stays the existing native tranche exit. Do NOT promote minervini.** prog-fills code kept
    (default off) as a lever. Verdict: `../verdicts/2026-07-09_m2b_backtrader_confirm_FAILS.md`.
    **Meta-lesson: the vec start-date cones in this thread are engine-optimistic in ABSOLUTE terms;
    within-engine ranking only. All promotion decisions run on BackTrader.**

- [ ] **M3 — Re-run the m2 / start-time cone** on whatever wins M2.
  The Sprint 13 start-time sweep (−39%..+197% cone) was on the inflated champion. Re-run on the gated
  winner. Expect magnitudes to shrink (§7 pattern).
  **Status:** blocked on M2.

- [ ] **M4 — Confirm the deploy gate on the gated population** (runs parallel to M1–M3).
  Re-confirm SPY 50/100/200 EMA/SMA as the deploy trunk + 6-pillar score as stress/calm, on the
  gated population. Mostly re-validation of [[project_capital_deployment]] /
  [[project_entry_timing_macro_axis]] — cheap, not blocked by the new champion.
  **Status:** not started.

## Done when
One re-derived comparison table (signal × exit-policy incl. minervini) on the **gated** population,
champion named + registry updated, m2 cone re-run on the winner, deploy-gate conclusion re-confirmed.
Every superseded Sprint 13 verdict annotated "population-inflated — see this plan".
