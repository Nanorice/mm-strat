# M2b — BackTrader confirm FAILS: progressive fills does NOT survive the fidelity engine; the vec cone is engine-optimistic

**Date:** 2026-07-09 · **Status:** ❌ NEGATIVE RESULT (the honest kind). The M2 vectorized minervini
cone (median 1.44, %neg 5%) **does NOT confirm on BackTrader**. Progressive fills is ~a wash on the
fidelity engine, and the whole vec cone is **structurally ~3× optimistic** vs BackTrader — the gap is the
ENGINE, not tuning. **Do NOT promote minervini/prog-fills to `strategy_registry.champion`.** Milestone M2b
of `../plans/population_rectification_plan.md`.

## The two BackTrader cones (fixed config, gated 2003-2026, rolling 2y/1y folds)

`scripts/run_strategy_confirm.py --wfo-gate`, real cash-blocking + next-open fills + gap-down exits.

| arm | agg OOS Sharpe | cone median | min | %neg folds | maxDD |
|---|--:|--:|--:|--:|--:|
| gated baseline (native tranche exit) | 0.52 | 0.53 | −1.86 | **45%** | −61% |
| gated + progressive fills | 0.53 | **0.35** | −2.42 | **45%** | −53% |

**Progressive fills is a WASH on BackTrader** — agg Sharpe flat (0.52 vs 0.53), cone median slightly
WORSE (0.53→0.35), %neg identical at 45%. Per-fold it helps some (2006/2010/2015/2021/2024) and hurts
others (2005/2013/2017/2019/2025), netting to nothing. The single-window 2024 smoke (0.81→1.34) that
looked promising was **one lucky fold**, not the distribution.

## The bigger finding: the vectorized engine is ~3× optimistic (fixed-config, apples-to-apples)

To rule out "vec re-optimizes per fold, BT used one locked config" as the cause, I ran the SAME locked
minervini+prog-fills config through BOTH engines on the SAME folds/population (no re-optimization):

| engine (identical config) | cone median | min | %neg folds |
|---|--:|--:|--:|
| **vectorized** | **1.51** | −0.44 | **10%** |
| **BackTrader** | **0.35** | −2.42 | **45%** |

**Same config, same folds, same gated cache — vec reports 3× the Sharpe and near-zero bear damage where
BT shows −2.4 in the 2008/2011/2022 folds.** The gap is NOT tuning; it is the engine. The divergence
concentrates in the BEAR folds — exactly where the vec engine's known optimism bites:
- **No real cash-blocking** — vec's `equity_curve` pro-rata-dilutes phantom concurrency instead of
  blocking entries when cash is out (BT enforces a real slot book + broker cash).
- **Stop fills booked at `stop_level`** even on gap-downs ([[project_backtest_stop_gap_fill]]) —
  understates bear losses; BT has next-open + gap-down exits.
- **Next-day-close entry approximation** vs BT next-open fills.

This is precisely the fidelity gap the Sprint 13 log warned about ("vec ranks WITHIN a signal, never
trust its absolute Sharpe; confirm on BackTrader") — now quantified for the minervini/prog-fills config.

## Verdict & what it changes

1. **M2's "minervini+prog-fills is the new champion" is DOWNGRADED to a vec-only result.** On the honest
   fidelity engine it is not better than the native tranche exit. **Champion stays the existing
   `SEPAHybridV1` native tranche exit** (which IS already a Minervini-style 3-tranche/trailing discipline).
2. **The real lesson is about the ENGINE, not the strategy:** the vectorized start-date cones in this
   whole thread (M2, and by extension the governor verdict's §2/§6/§7 vec numbers) are **engine-optimistic
   in absolute terms** — usable for WITHIN-engine ranking, NOT as absolute Sharpe/%neg claims. Any
   promotion decision must run on BackTrader. This retro-flags M2's cone magnitudes (not its RELATIVE
   minervini>sma ranking, which may still hold within-vec — but the ABSOLUTE 1.44/%neg-5% was optimistic).
3. **Progressive-fills code is KEPT** (default off, all guards pass) as an available lever, but it earns
   no live slot. `tests/test_progressive_fills.py` guards the state math.
4. **The population fix STILL stands and still matters** — both engines now gate correctly; the Sprint 13
   champion was genuinely inflated. What changed is that the *replacement* (minervini) doesn't beat the
   incumbent native exit once measured honestly. Net: the honest gated champion is the **native tranche
   exit on the gated population**, not sl15×tpTight and not minervini.

## Bug fixed en route (would have poisoned any gated BT run)
`run_strategy_confirm._load_scores` + `score_lookup.prototype_scores_to_contract` DROPPED
`trend_ok`/`breakout_ok`, silently re-inflating the population in the BT path. Both now pass the flags
through → ScoreLookup restores the breakout gate (verified). See the plan doc M2b notes.

cf `2026-07-09_m2_minervini_vs_sma_gated_cone.md` (the vec cone this downgrades),
`../plans/population_rectification_plan.md`, [[project_backtest_equity_and_sizing]] (vec↔BT fidelity),
[[project_champion_starttime_dependent]].
