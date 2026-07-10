# Population reframe: the breakout gate was a TRIGGER masquerading as a UNIVERSE — and the ranker's target should be the TAIL, not the median

**Date:** 2026-07-09 · **Status:** ✅ DIAGNOSIS + evidence probe. Reframes the whole SEPA-project path
after the "trading is a start-date lottery, not a strategy" observation. Two read-only DuckDB probes
decide it. This is a HIGH-LEVEL revision doc, not a code change.

## The observation that triggered this

The Sprint 13/14 arena produces a **start-date lottery** ([[project_champion_starttime_dependent]]:
ann_return −39%..+197%, 17/53 Sharpe-negative), not a repeatable strategy. Stepping back to the SEPA
book (Minervini), the method is a **two-stage funnel**:

1. **Screen / rank** — Trend Template + earnings/sales/margin/RS growth + leadership similarity →
   produces a *persistent ranked watchlist*. This is the 95%-elimination.
2. **Trigger / entry** — the breakout / VCP pivot → a *timing event applied to names already on the
   watchlist*. Answers "buy today?", NOT "is this a good stock?".

**What the project did:** it collapsed both stages into the *population definition*. `trend_ok AND
breakout_ok` gates the T3 universe, and m01 was trained ONLY on breakout-day rows (methodology §7.1:
"*is experiencing a breakout today*"; §8.2: "31,489 breakout samples"). Consequences:

- The model never sees Minervini's stage-1 population. It only sees the post-trigger slice.
- Asking XGBoost to re-derive the stage-2 growth/leadership elimination **on a population already
  filtered by a stage-2 event is circular** — the breakout already spent the signal
  ([[project_breakout_pool_refinement]]: model IC ≈ −0.03, 0% next-day persistence inside the pool).
- **The lottery is a direct consequence:** a breakout-only universe is a stream of discrete rare events
  clustered in bull regimes. Which breakouts you catch is set by *when you start* — you're sampling a
  Poisson process, not running a strategy. The book avoids this because the **watchlist persists** for
  weeks; the breakout is just when you act. The project kept the events and threw away the persistent
  ranked object.

## Probe 1 — does RS rank the trend panel? (median lens) → NO, it INVERTS

Read-only, `price_data` forward returns (calendar-safe, [[project_t3_gappy_panel]]), 2010–2024,
60d horizon, `RS_Universe_Rank` (Minervini stage-2 core) as the axis, NTILE(10) per date.

| RS decile | trend-only median fwd60 | breakout-pool median fwd60 |
|---|--:|--:|
| D1 (weakest RS) | **+2.36%** | +1.88% |
| D10 (strongest RS) | +0.39% | −0.15% |
| **top−bottom spread** | **−1.97%** | **−2.03%** |

Two findings:
- **RS as a median ranker is INVERTED** (weak-RS beats strong-RS at 60d median) — consistent with
  [[project_stage_gate_falsified]] (stage ranking inverts prior at 60d).
- **The breakout pool has NO privileged information** — its decile ramp is identical to the trend
  panel's. The breakout gate is neither the source of signal nor, alone, the fix. This *refutes the
  naive pivot* ("swap population, rank by RS, dispersion appears" — it doesn't on the median).

## Probe 2 — the TAIL lens rescues it: RS ranks the home-run rate MONOTONICALLY, 5.7×

Same setup, tail statistics (P90 and home-run rate >30%) on the **trend panel**:

| RS decile | n | P90 fwd60 | home-run rate (>30%) |
|---|--:|--:|--:|
| D1 (weakest) | 105,614 | 17.2% | 2.21% |
| D2 | 105,265 | 17.1% | 2.29% |
| D3 | 104,900 | 17.8% | 2.42% |
| D4 | 104,548 | 18.8% | 2.74% |
| D5 | 104,210 | 19.6% | 3.42% |
| D6 | 103,837 | 20.7% | 4.25% |
| D7 | 103,504 | 22.3% | 5.11% |
| D8 | 103,171 | 24.7% | 6.59% |
| D9 | 102,810 | 28.5% | 9.07% |
| **D10 (strongest)** | 102,438 | **34.7%** | **12.66%** |

**Clean, monotone, no reversal.** Strongest-RS trend stocks are **5.7× more likely to be a >30%
winner** (12.66% vs 2.21%) and have **2× the P90** (34.7% vs 17.2%) — while being WORSE on the median.
This is the right-skewed press-your-winners signature that [[project_tail_magnitude_objective]]
predicted (objective = Σmax(fwd−30%,0), NOT central tendency), and it explains why every median-based
test came up flat/inverted: **the project measured the wrong statistic.**

## Verdict — the reframe (three changes)

1. **Population for the RANKER = the full `trend_ok` panel, NOT the breakout slice.** Every trend-active
   day is a candidate row — this is Minervini's persistent stage-1 watchlist. The watchlist persisting
   across days is what converts the event-lottery into a positionable strategy.

2. **Target = the TAIL, not the median / not 4-class-balanced.** The ranker's job is to sort the trend
   panel by home-run probability (>30% MFE / tail magnitude). The current m01 4-class + balanced-weight
   setup fights the very imbalance that IS the signal. Ranking axis: RS is a *proven monotone tail
   ranker* here — combine with the fundamental leg (earnings/sales/margin accel) as the next test.

3. **Breakout / VCP → entry TRIGGER only.** Applied at backtest/live entry to the top-ranked names,
   exactly as the book uses it. It stops defining who the model ever sees.

This attacks the lottery at its root: entry timing (breakout) now samples from a *stable ranked
watchlist* instead of a stream of isolated events, and the ranker finally has real dispersion to learn
(the trend panel, tail objective) instead of the signal-spent breakout pool.

## What this does NOT claim (honesty guard)

- It does NOT claim a median-return edge — there isn't one; the edge is entirely in the right tail.
  Position sizing / risk management must be built for a low-hit-rate, fat-right-tail payoff.
- It does NOT resurrect parked m02 ([[project_strategy_arena_goal]] "top-50 fwd ≈ universe"): that was a
  median-ish forward-return test on a breakout event. This is a *tail-objective* ranker on the
  *persistent trend panel*. Different axis, statistic, and population.
- The tail edge is likely still **pro-cyclical** ([[project_tail_magnitude_objective]]: below no-skill
  in 2001/2008). Regime/deploy-gating ([[project_capital_deployment]],
  [[project_entry_timing_macro_axis]]) remains the during-period risk dial — orthogonal, still needed.

## Impact on the rectification plan

`../plans/population_rectification_plan.md` (M1–M4) is a *within-the-old-frame* effort: it re-derived
exit policies (minervini/prog-fills) on the gated **breakout** population and correctly found the
champion doesn't improve ([[project_minervini_progfills_fails_bt]]). That work stands as an
exit-mechanics result, but it optimized the WRONG population. The reframe supersedes the *selection*
question:
- Next milestone (proposed): **build the tail-objective ranker on the trend panel**, backtest with
  breakout as the entry trigger, judge on the start-date CONE (not single window) and on BackTrader
  (not vec — [[project_vec_engine_optimistic]]).
- Re-open the target definition per [[feedback_target_invariant_enrich_dont_substitute]]: this is a
  *new, better-scoped model*, not a fallback — decide it deliberately.

## Reproduce

Both probes are read-only single queries in this session's transcript: `t3_sepa_features` (state,
trend_ok, RS_Universe_Rank) JOIN `price_data` (LEAD(close,60) forward return), NTILE(10) per date,
2010–2024. Probe 1 = MEDIAN by decile × {trend, breakout}. Probe 2 = P90 + rate(fwd60>0.30) by decile.
