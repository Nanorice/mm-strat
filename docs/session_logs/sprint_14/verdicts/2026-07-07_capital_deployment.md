# Verdict: capital deployment — bad-day risk, basket width, model scope (Thread E)

**Date:** 2026-07-07 · **Status:** ✅ re-analysis on the 25-year cache, no re-scoring
**Answers:** RESEARCH_LOG Thread E Q13–15 (user questions following the M1 multi-year result).
**Data:** `data/model_output_eda/multiyear/raw_full_{2001..2025}_fwd.parquet` + `t1_macro`
(daily VIX/SPY back to 2000). Script: `docs/session_logs/sprint_14/scripts/capital_deployment.py`.

> These three tie the M1 pro-cyclicality finding to the actual product question: with LIMITED
> capital, how do we avoid the damage of deploying into a bad regime? Along the way two side-claims
> got corrected (basket width, model scope).

## Q13 — the crash pro-cyclicality is a SCOPE boundary, not a defect

The M1 multi-year result (score anti-ranks the tail in 2001/2008) was measured on the **full
universe**. But live SEPA screening (Stage-2 uptrend, above rising 50/150/200 MAs, high RS)
**structurally excludes the beaten-down reversal names at the moment they bottom** — the exact names
that become crash-moonshots. They only appear in the full-universe test set *later*, after they've
turned and rebuilt a trend the screen recognises.

→ **The model is a CONTINUATION model, not a reversal model.** "Misses crash-moonshots" is a scope
boundary, not a bug — stop treating it as a defect to fix. **Corollary:** the 25-year full-universe
bad-regime floor (lift 0.68× in 2001/2008) is a *pessimistic* read of the live SEPA-gated system,
which would not have been down there trying to rank reversals. Don't over-weight that floor when
judging the champion in M3 — re-cut the bad-regime lift on the SEPA-eligible universe before using it.

## Q14 — widening the basket (top-5 → top-10) does NOT catch more winners

Both top-5 and top-10 are drawn from the same ~284 gated names/day. Pooled over 25 years:

| basket | mean fwd20 | home-run hit-rate |
|---|---:|---:|
| top-5 by score | **+2.36%** | **8.75%** |
| top-10 by score | +2.30% | 8.34% |
| names 6–10 only (implied) | +2.23% | — |

**Statistically identical.** The score's ranking power is a **sharp cliff at the top-5, then flat** —
names 6–10 are no better than 1–5, and inside the 5 there is no order (within-pool IC≈0, confirmed
earlier). **Widening the basket dilutes rather than helps** → this argues *against* the sprint-13
"gate-not-ranker → widen the basket" instinct. The lazy product is a *narrow* top-5, not a wide one.

## Q15 — telling good days from bad EX-ANTE (the limited-capital problem)

The earlier cross-sectional cut (top-score-decile → top-5 return, spearman 0.96) only works with
**unlimited capital buying every day** — it's a within-day *relative* signal, useless for "deploy
today vs wait." The real problem is time-series: **starting on a bad day/regime drags the book.**
Test: does an *ex-ante* macro state (known at the open) separate good FUTURE top-5 days from bad?

| ex-ante state | top-5 fwd20 | % negative days |
|---|---:|---:|
| **SPY below 200d MA** | **+0.6%** | 47.9% |
| **SPY above 200d MA** | **+3.0%** | 42.3% |
| VIX < 15 | +2.1% | 42% |
| VIX 20–30 | +1.9% | 47% |
| VIX > 30 (panic) | **+4.5%** | 36% |

- **SPY-above-200d is a real deploy gate** — +3.0% vs +0.6%, a **5× forward-return gap** from one
  binary you know at the open, holding across 25 years. This is the classic Minervini market filter,
  confirmed. **Biggest single lever for "don't deploy into a downtrend."**
- **VIX is NOT a gate** (corr +0.03). Counterintuitively high VIX (>30) days have the BEST forward
  returns (+4.5%, crash-rebound) — a "reduce when VIX high" rule would be exactly backwards. cf the
  sizing thread where VIX "works" for *exposure* — that's a different axis from *deploy-timing*.
- **Residual: even in the best state 42% of days still go negative.** No single ex-ante flag gets
  below ~42% bad-day rate → the un-removable part is **staggered entry (dose-average the start), not
  day-timing.** Confirms M2 (cone-not-point); SPY-200d tightens the cone's *downside*.

## Design direction (consolidated)

A **continuation-only, SPY-200d-gated, sharp top-5 (not wider), staggered-entry** book:
1. Model is continuation — don't ask it to catch reversals (Q13).
2. Take top-5, not top-10 — width dilutes (Q14).
3. Gate new-capital deployment on SPY > 200d — 5× return gap (Q15).
4. Stagger entry over N days — the 42% residual bad-day rate is dose-averaged, not timed (Q15).

## ⚠️ Caveats
- **No exits/sizing/liquidity** — top-5 fwd20 is directional, not tradable P&L. The SPY-200d gate
  needs confirming as a *Sharpe-distribution* shrinker (next step: does it narrow the start-date
  cone?), not just a mean-shifter.
- **SPY-200d in-sample here** (one threshold, whole history). A 200d MA has ~no free params so
  overfit risk is low, but confirm it survives the start-date cone before hard-wiring.
- Q13's "re-cut bad-regime lift on the SEPA-eligible universe" is deferred — the current numbers are
  full-universe. Read the *direction* (continuation-not-reversal), not the exact 0.68×.
