# Verdict: raw binary score ↔ forward return (full-universe EDA, no backtest)

**Date:** 2026-07-07 · **Status:** ✅ exploratory, 1 year (2025), full active-candidate universe
**Feeds:** consolidating the ranking question after WFO. **Data:** `score_from_t3` raw p_pos,
596k rows / 250 days / 2530 tickers, 20d fwd from close. Artifact:
`data/model_output_eda/raw_full_2025_fwd.parquet`.

> **Purpose:** the WFO showed calibrated ≥ raw *for the breakout strategy*. This EDA asks the
> orthogonal question the user posed — on the **continuous raw score across the full universe**
> (not just day-0 breakouts): is the threshold right, what do we miss, do top names persist now,
> and what do winners share? It clarifies WHERE ranking signal exists vs doesn't.

## Q1 — is 0.48 (=cal 0.15) the right threshold?
The raw score grades forward return monotonically at the top (full universe):

| raw score ventile | mean fwd20 | home-run rate (>30%) | win |
|---|---:|---:|---:|
| 0.50–0.53 | +1.5% | 4.4% | 52% |
| 0.65–0.71 | +4.7% | 10.8% | 54% |
| 0.71–0.90 | +4.9% | **12.7%** | 54% |

Real 3× gradient in home-run rate. **But this is the GATE working** (separating 0.5 from 0.7),
not fine ranking. The gate is a **precision/recall dial** (Q2).

## Q2 — how many home-runs do we miss?
19,431 home-run events (fwd>30%) in 2025. Gate `raw≥0.48` **captures 76.6%, misses 23.4%** — and
the missed ones sit just under the line (median raw 0.41, p90 0.47), near-misses not deep rejects.

| gate (raw) | recall (HR captured) | precision (HR-rate admitted) | admit/day |
|---|---:|---:|---:|
| 0.40 | 89% | 6.0% | 1155 |
| **0.48** | **77%** | **7.4%** | **805** |
| 0.61 | 48% | 10.4% | 356 |
| 0.71 | 19% | 12.7% | 116 |

No free lunch: tightening ~doubles precision but discards most home-runs. **Key point for a top-5
strategy: you fill 5 slots but 0.48 admits 805/day → you can tighten HARD (to 0.65–0.71) and still
never run out of names, buying much higher precision.** The current gate is tuned for breadth the
top-N strategy doesn't use.

## Q3/Q4 — rotation & drift on the CONTINUOUS score (vs 0% on gated breakout)
On the continuous full-universe score the top names **persist**:
- top-5 next-day overlap **50%**, top-10 54%, top-20 **63%**.
- yesterday's top-20 drifts only **~7 rank places/day** — a slow, stable ranking.

**This contradicts the 0% persistence of the gated breakout cohort — because that was day-0
events. The continuous score ranks the full active-candidate pool (incl. persistent pre-breakout
names). → a persistent, rotatable top-N exists here that the breakout gate throws away.**

## Q5 — what do the best performers share? (top vs bottom fwd-decile medians)
- **prob_elite barely separates** (0.534 vs 0.511) — score is a weak within-population ranker (again).
- **Technicals useless / inverted** — mom_21d, mom_252d, rs all flat or slightly NEGATIVE for winners.
- **Fundamentals separate, counter-intuitively:** winners are **CHEAPER, lower-quality** —
  PE 17.7 vs 37.4, gross margin 41 vs 45, ROE lower. A **value/mean-reversion rebound** signature,
  not quality-momentum.
- **Sector: winners tilt Healthcare 1.65× and Tech 1.32×** in 2025 (Financials 0.51×, Real Estate
  0.18×). ⚠️ Healthcare here is OPPOSITE to the breakout-cohort finding (where it was worst) —
  different population (full active candidates vs day-0 breakouts) and different year → **sector
  effects are regime/population-dependent, do not hard-wire a Healthcare veto without conditioning.**

## Does the persistent top-N pay? (mean fwd20 by daily raw-rank band)
| rank band | mean fwd20 | home-run rate |
|---|---:|---:|
| 1–5 | **+5.66%** | **19.0%** |
| 6–20 | +3.82% | 13.9% |
| 21–50 | +3.95% | 12.8% |
| 51–300 | ~+4.0% | ~11% |

**Only the top-5 stands out; ranks 6–300 are flat (~+4%).** So the continuous score has a *sharp
top* (top-5 pays) but no gradient below it.

## Consolidated answer — WHERE is there ranking potential?
1. **Not in a finer version of the same score within the gated pool** — proven flat 3 ways (WFO,
   within-day IC≈0, Q5 prob_elite barely separates).
2. **YES at the extreme top of the continuous full-universe score** — top-5 by raw ranks
   meaningfully (+5.7%, 19% HR) AND persists (50% overnight, 7-place drift). This is a different
   product from the breakout strategy: a **persistent continuous-score top-N**, not day-0 breakouts.
3. **In a DIFFERENT axis (fundamentals/sector), not technicals** — winners are cheap value-rebound
   names; the model (technical-heavy) is blind to this. This is the human-judgment layer.

## Next leads (all no-regret EDA / small tests)
- **Tighten the gate** for the top-N strategy (0.48→~0.65) — free precision, never slot-starved. Backtest.
- **Prototype a persistent continuous-score top-N** (not breakout-gated) and WFO it — the 50%
  persistence + top-5 edge suggests a lower-turnover cousin of the champion.
- **Condition sector/fundamental tilts on regime** before trusting them — 2025 Healthcare tilt may
  not generalise. cf [[project_breakout_pool_refinement]], [[project_champion_starttime_dependent]].

## ⚠️ Caveats
- **One year (2025) only** — a single regime. Winner traits (cheap/value, Healthcare) are likely
  2025-specific. Repeat across years before acting.
- Full-universe fwd return ≠ tradable P&L (no exits/sizing/liquidity). Directional, not a strategy result.
