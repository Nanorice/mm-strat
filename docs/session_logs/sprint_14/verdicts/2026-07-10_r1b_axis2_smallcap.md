# R1b addendum — second watchlist axis: YES, and it's SIZE (with coverage-missing as an additive flag)

**Date:** 2026-07-10 · **Parent:** `2026-07-10_r1b_step2_screen.md` §6 (the missing-fundamental lead)
**Question:** does the missing-fundamental/small-cap cohort deserve a spot as a second watchlist axis next to RS?
**Repro:** `scripts/r1b_axis2.py` · **Cache:** `data/research_cache/r1b/axis2_*.csv`
**Answer: YES — label-level.** The axis survives all four disqualification tests. Best expressed as
**per-date market-cap rank (small)** as the second axis, with **fundamental-coverage-missing** as an
additive boolean tag — the two carry *independent* signal. All claims label-level; trade conversion is R3's.

## Test 1 — Incremental to RS (not RS-redundant): PASS

Missing-fund beats has-fund ~2× *inside every RS band* — it is not re-slicing RS:

| RS band | has_fund lift | missing lift |
|---|---:|---:|
| 70–80 | 0.37 | 0.84 |
| 80–90 | 0.60 | 1.38 |
| 90+ | 1.85 | **3.23** |

## Test 2 — The underlying axis is SIZE, but missingness is not just size: BOTH real

Cap-decile ramp is strongly monotone: unconditional D1 (smallest) **2.19×** → D10 (largest) 0.43×;
within RS-D10: 3.16× → 1.70×. Missingness concentrates in small caps (31.5% of cap-D1 vs 2.5% of
cap-D10) — but has **residual lift within every cap tercile** (T1: 2.39 vs 1.48; T3: 1.43 vs 0.48 —
3× even among large caps). Sparse coverage marks something beyond size (under-followed names).

## Test 3 — Volatility matching (is it just MFE vol-inflation?): PASS

Within per-date `volatility_20d` quintiles the lifts barely move — and the hot cell is *strongest in
the least-volatile quintile*:

| vol quintile | missing | has_fund | RS-D10 ∧ smallcap-T1 |
|---|---:|---:|---:|
| Q1 (calm) | 2.04 | 0.95 | **2.74** |
| Q3 | 2.09 | 0.85 | 2.52 |
| Q5 (wild) | 2.36 | 0.85 | 2.47 |

Not a volatility artifact.

## Test 4 — Era stability: PASS · Tradability: the real constraint

RS-D10 ∧ smallcap-T1: 2.94 / 2.89 / 2.38 across date-thirds; RS-D10 ∧ missing: 3.05 / 3.90 / 2.81.
(Contrast: RS-D10 ∧ bigcap ∧ full-fundamentals = 1.17–1.49.) ~49 names/day in P3 — watchlist-sized.
**But**: median dollar volume of the hot cell is **$7.5–8.6M/day**, only ~64% above $5M/day and
~18–31% above $20M/day → position-size ceiling, more slippage than the champion's population. This
is the number R3 must price.

## Recommendation

1. **Adopt (label-level):** watchlist ordering = RS rank (primary) × per-date cap rank ascending
   (secondary), with `fundamental-coverage-missing` as a boost tag. Hot cell = RS-D10 ∧ small-cap
   tercile: ~2.4–3.2× era-stable, vol-robust tail lift.
2. **Do NOT ship as strategy.** MFE has no downside twin here — small caps likely carry worse
   MAE/stop-out rates and wider spreads; per [[population-reframe-tail-ranker]] M4 already showed
   label lift dying under tranche exits. The R3 2×2 should add a size-tilted selection arm so
   the coupling question prices this cohort's liquidity and stop behaviour directly.
3. Coverage-missingness as a *feature* needs a live-safety check before any production use (is
   "missing" knowable ex-ante at scoring time the same way it appears in t3? — it is a pipeline
   artifact as much as a company property).
