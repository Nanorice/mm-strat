# M2 — Minervini (breakeven-ratchet + progressive fills) BEATS sma on the gated start-date cone

> ⚠️⚠️ **DOWNGRADED by M2b (2026-07-09):** this is a VECTORIZED-ENGINE result and does NOT survive the
> BackTrader confirm. Same fixed config on BT: cone median 0.35 vs vec 1.51, %neg 45% vs 10% — the vec
> engine is ~3× optimistic (no real cash-blocking, stop-at-level gap understatement). Progressive fills
> is a WASH on BT. The champion is NOT minervini. The RELATIVE minervini>sma ranking may hold within-vec,
> but the ABSOLUTE 1.44/%neg-5% below is engine-optimistic. See
> `2026-07-09_m2b_backtrader_confirm_FAILS.md`.

**Date:** 2026-07-09 · **Status:** ⚠️ vectorized WFO cone DONE but SUPERSEDED by M2b's BackTrader confirm. Minervini+progressive-fills is the new
**vectorized** champion — pending a BackTrader confirm before it can replace `strategy_registry.champion`
(same fidelity bar the Sprint 13 champion had to clear; do NOT skip it — this is the exact path-dependent
sizing where vec↔BT diverge). Milestone M2 of `../plans/population_rectification_plan.md`.

**Population:** the SEPA-gated cache (`data/score_cache/m01_binary_calibrated_..._sepa_gated.parquet`),
i.e. genuine breakouts only (`trend_ok AND breakout_ok`) — the fix that invalidated the Sprint 13 arena.
**Harness:** `scripts/run_strategy_wfo.py`, 2yr-train/1yr-test rolling folds, 2003→2026, 40 trials/fold,
`LOCK_EXIT_POLICY` pinning each policy so both get the full trial budget in their own subspace (a
free-choice optimizer under-sampled minervini — smoke picked nday). Artifacts:
`data/selection_sweep/m2_cone_{sma,minervini}/`.

## The cone (start-date robustness — the gate that matters, not single-window IS)

| arm | cone median | min | max | %neg folds | agg OOS Sharpe | agg ann | agg maxDD |
|---|--:|--:|--:|--:|--:|--:|--:|
| **sma** (re-derived, gated) | 1.00 | −1.30 | 2.90 | **25%** | 0.99 | 22.0% | −36.1% |
| **minervini + prog-fills** | **1.44** | **−0.09** | 3.49 | **5%** | **1.36** | 32.6% | **−30.4%** |

**Minervini beats sma in 16/21 overlapping folds**, and — the load-bearing part — it rescues the
*worst* folds, the ones that made the old champion start-time-fragile ([[project_champion_starttime_dependent]]):

| fold (test-start) | sma OOS | minervini OOS |
|---|--:|--:|
| 2007 (into GFC) | **−1.30** | **+1.61** |
| 2017 | −0.30 | **+2.88** |
| 2011 | −0.05 | +0.67 |
| 2022 | −0.25 | +0.06 |

`%neg folds 25% → 5%`; worst fold `−1.30 → −0.09`. The 5 folds sma wins (2006/15/23/24/25) are all mild
good-regime folds where the ratchet gives back a little — the honest, small cost.

## Why it works (mechanism, confirmed by the optimizer)

**Progressive fills was chosen in 20/21 folds** — the optimizer independently confirms it's load-bearing,
not a thumb on the scale. The tight-stop/breakeven-ratchet asymmetry (starve losers at starter size, press
winners to full only after they prove up) is harvestable ONLY in the engine — which is exactly what the
governor verdict §6d/§7b predicted and the fixed-hold basket lens could not show. This is the mechanism
that turns losing start-years positive: it's not more picks, it's asymmetric capital on the picks.

**Modal winning config** (diffuse where the mechanic makes a knob non-load-bearing):
- `progressive_fills=True` (20/21) · `add_trigger_pct=0.05` (15/21) · `starter_frac` 0.3/0.5 split
- `be_trigger_pct` 0.05–0.10 · `trail_pct=0.10` (15/21)
- `stop_loss_pct` DIFFUSE (0.05–0.15, no mode) — the ratchet makes the initial stop less load-bearing,
  consistent with the mechanic. `min_prob_elite` also diffuse. `max_hold_days=60` modal (10/21).

## Verdict & scope

1. **The Sprint 13 `sl15×tpTight` champion is superseded AND was population-inflated.** Even the
   re-derived honest sma (gated) is beaten across the cone.
2. **New vectorized champion = minervini + progressive fills.** NOT yet written to `strategy_registry`
   (which holds BackTrader-shaped kwargs; the vec `exit_policy`/prog-fills kwargs are a different engine).
   **→ Task: port progressive fills into `SEPAHybridV1` + BackTrader-confirm the cone before promoting.**
   Registering vec kwargs in a BT registry would be a silent trap.
3. **Start-time fragility is materially reduced, not eliminated** — %neg 25→5%, but 2015/2022 still
   flat/slightly-neg. The forward shadow-book ([[project_forward_shadow_book]]) is still the live check.

cf `../plans/population_rectification_plan.md` (M2), the population fix in
`2026-07-09_regime_governor_backtest.md` §7, [[project_strategy_registry]].
