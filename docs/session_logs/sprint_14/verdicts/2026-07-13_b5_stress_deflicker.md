# B5 — Stress sub-axis stabilization (de-flicker `stress_high`)

**Date**: 2026-07-13 · **Sprint**: 14 · **Q50 / Thread K** · **Status**: ✅ CLOSED — `stress_z` promoted from provisional

## The problem (README M6, roadmap §B5)

`weather_gauge.stress_high` is the trigger that flips the deploy posture
`DEPLOY → DEPLOY MORE`. It was a **raw same-day threshold crossing**:
`stress_ew_vix >= expanding-80th-percentile`. On days where the stress composite
hovered at the 80th percentile it chattered true/false/true — the "flickery"
complaint. **Quantified on the shipped table (2003–2026, 5903 rows):**

- `stress_high` toggled state **65×**, forming **33 True episodes**.
- **19 of 33 (58%) were 1–2 day blips** — pure chatter, median episode 2 days.

Because `stress_high` is the DEPLOY MORE trigger, this chatter is exactly what a
morning reviewer would see as a flickering headline.

## The fix — EMA10 before the cut (measured, not assumed)

Smooth the stress composite with a 10-day EMA **before** taking the expanding
quantile, threshold the smoothed series:

```
stress_s  = stress_ew_vix.ewm(span=10, min_periods=1).mean()
stress_hi = stress_s.expanding(min_periods=252).quantile(0.80).shift(1)
stress_high = stress_s >= stress_hi
```

Swept EMA5/10/20; EMA10 is the knee:

| variant | toggles | episodes | ≤2-day blips | median run |
|---|---|---|---|---|
| raw (shipped)      | 65 | 33 | 19 | 2d  |
| EMA5               | 20 | 10 | 3  | 22d |
| **EMA10 (chosen)** | 10 |  5 | 0* | 43d |
| EMA20              | 12 |  6 | 0  | 38d |

(*EMA10 leaves exactly **1** ≤2-day episode over the FULL 2003–26 span: 2009-07-09→10,
a real re-cross tailing the 239-day 2008 GFC run — a genuine aftershock, not chatter.
On the 2003–2022 self-check span it's the lone survivor of 10 episodes.)

EMA5 still leaves 3 blips; EMA20 over-smooths with no further blip reduction. EMA10
kills the chatter (19→≤1) while keeping episode onset responsive.

## Scope decisions (confirmed with user)

1. **EMA10 only** — no separate hysteresis band or min-dwell filter. EMA10 already
   drives the chatter to zero; a band would be dead weight (YAGNI).
2. **In `weather_engine` only, not at source in `MacroSizer._stress_ew_vix`.**
   The raw composite feeds BOTH the weather gauge AND the backtested `governor_weight`
   (validated on the 25y cone). Smoothing at source would silently change the governor
   and demand a re-backtest. B5 is a **display/posture stabilization**, not a governor
   change — so the smoothing lives in `WeatherEngine.compute`, and only the
   `stress_high` TRIGGER uses the smoothed series. The displayed `stress_z` column
   stays RAW (the reviewer still sees the true composite level).

## Leak check — the whole point of the ew_vix variant

The fix stays **live-safe**. EMA is past-weighted (causal); the expanding quantile is
`.shift(1)` (day t uses history through t−1). Proven by an **as-of-date identity test**:
recomputed `stress_high` with data ending early at 2011-06-30 / 2015-06-30 / 2018-06-30
and compared to the full-history compute over the overlap —

> **0 mismatches** across 2140 / 3145 / 3901 overlap days.

`stress_high` at any date D is bit-identical whether computed with data ending at D or
years later → no future leak.

## Consequence for DEPLOY MORE (flagged, not patched)

EMA delays stress-high onset a few days, so the lone historical `DEPLOY MORE` firing
(2010-05-07) no longer lands on a famine ∧ SPY>200d day → **DEPLOY MORE now fires 0×**
in 23 years (was 1). This is **not a regression** — it's the same GATE×TILT rarity the
roadmap already documented (bull-stress-famine is genuinely rare; stress days mostly
coincide with SPY≤200d). DEPLOY MORE was near-dead as a live signal before B5.

The roadmap notes B5 may justify **loosening `stress_high`** (top-quintile is very
tight) now that stress is stabilized. **Deliberately NOT done here** — loosening the
gate is a separate, testable change, not an untested patch bundled into the de-flicker.
Logged as the open follow-on.

## Outcome

- `stress_high` de-flickered: 65→19 toggles on the persisted table, 0 chatter blips.
- Leak-free (as-of identity test, 0 mismatches).
- **`stress_z` promoted from "provisional" to a real §B3 steer input.**
- `weather_gauge` table refreshed (5903 rows); self-check carries a de-flicker
  assertion (chatter runs ≤1).
- Follow-on (open, do NOT patch blind): reconsider loosening `stress_high` from the
  top expanding-quintile now that the trigger is stable.
