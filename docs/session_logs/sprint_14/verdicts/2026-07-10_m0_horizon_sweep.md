# M0 verdict — horizon & target selection for m01_tail: GATE PASSES, pick N=63, tail-magnitude label

**Date:** 2026-07-10 · **Status:** ✅ M0 of `../plans/m01a_tail_ranker_plan.md` (read-only, no training).
Answers RESEARCH_LOG Q31. Supersedes the unconditional 5.7×/60d probe in
`2026-07-09_population_reframe_tail_ranker.md` with the entry-conditioned, multi-horizon version.

## Setup

- Population: full `trend_ok` panel (`t3_sepa_features`, RS_Universe_Rank NOT NULL, LIF/CUE excluded),
  2010–2024, NTILE(10) by RS per date. ~1.04M rows.
- **Entry-conditioned MFE:** enter at day-t close; MFE = max(GREATEST(high, close)) over bars t+1..t+N
  from `price_data` (calendar-safe), requiring a **full** N-bar forward window (truncated paths dropped —
  mild survivorship on within-window delists, noted).
- Stats per decile: home-run rate P(MFE>30%), P90(MFE), tail-magnitude E[max(MFE−30%, 0)].
- Stability: split into date-thirds 2010–14 / 2015–19 / 2020–24.

## Result — home-run rate P(MFE_N > 30%) by RS decile (ALL period)

| N | D1 | D5 | D8 | D9 | D10 | D10/D1 | monotone-to-D10 (ALL) |
|---|--:|--:|--:|--:|--:|--:|:--|
| 21 | 0.49% | 1.03% | 2.75% | 4.44% | 8.95% | **18.5×** | ✅ strict |
| 42 | 2.21% | 3.79% | 8.08% | 11.95% | 19.66% | **8.9×** | ✅ strict |
| **63** | 4.69% | 7.63% | 14.44% | 19.44% | **28.45%** | **6.1×** | ✅ strict |
| 126 | 14.78% | 20.25% | 29.73% | 35.30% | 44.45% | 3.0× | ❌ (D1/D2 swap only) |

Date-third stability of the D10/D1 home-run ratio:

| N | 2010–14 | 2015–19 | 2020–24 |
|---|--:|--:|--:|
| 21 | 20.1× | 13.9× | 20.0× |
| 42 | 9.8× | 8.4× | 8.8× |
| **63** | **6.7×** | **5.7×** | **5.9×** |
| 126 | 3.1× | 2.8× | 3.1× |

Tail-magnitude E[max(MFE63−30%,0)] ×100, ALL: D1 0.55 → D9 3.83 → D10 **7.62** (13.9×, sharp D9→D10
cliff — edge concentrated in the very top, consistent with [[project_capital_deployment]]'s top-5 cliff).

## The m02 anti-test & the gate

- **Top-end is strictly monotone everywhere:** D6<D7<D8<D9<D10 in every horizon × every date-third, on
  all three stats. No "peaks at D7, dies at D10" — the m02 failure signature is absent. **PASS.**
- Honest wrinkle: D1/D2/D3 wiggle (≤0.4pp swaps) in the pre-2020 thirds at every N, and that tiny bottom
  swap is what flips the strict-monotone flag at N=126. The bottom of the weakest-RS junk region is
  unordered; the top — where selection actually happens — is clean. Gate intent (monotone TO the top) met.
- Level shifts ~2× higher in 2020–24 across all deciles (pro-cyclical, known:
  [[project_tail_magnitude_objective]]); the *ranking* survives all three thirds.

## Decision

- **N = 63** (one quarter). Most date-stable ratio (5.7–6.7× across thirds — tightest band), strictly
  monotone ALL + top-end in every third, base rate learnable (universe ~11% positive, D10 28%), and
  continuous with the original 60d evidence. N=21/42 are steeper but positives are sparse pre-2020
  (D1 0.2–0.5% at N=21 → label noise); N=126's 30% threshold saturates (D1 ≈ 15%) and discrimination
  compresses to 3×.
- **Label form = continuous tail-magnitude** `max(MFE_63 − 0.30, 0)` (primary): steeper monotone ramp
  (13.9× vs 6.1×), richer gradient, and it's the objective [[project_tail_magnitude_objective]] already
  banked as regime-robust. Binary home-run `1[MFE_63 > 0.30]` kept as the diagnostic/secondary stat
  (outlier-robust cross-check — tail_mag is an unwinsorized mean, sensitive to residual price dirt).

**→ M0 gate passes. Proceed to M1 (label build + LeakageGuard) on user confirmation.**

> **Post-script (M1):** a corrupt-high dirt class was found after this sweep (isolated highs >2×
> the bar body, e.g. EXEL 999.99 sentinel — see `2026-07-10_m1_label_m2_rs_baseline.md`) and fixed
> at source (178 highs nulled, clean_dirty_shares_price.py part G). This sweep's home-run rates /
> P90 are unaffected (dirt-robust stats, and the affected entries fall outside 2010–24); only
> unwinsorized tail_mag cells could shift slightly. The N=63 decision stands.

## Reproduce

`scratchpad/m0_horizon_sweep.py` (session scratchpad; single read-only DuckDB query, ~5s): trend_ok
panel × price_data forward-window MAX(GREATEST(high,close)) OVER (ROWS 1..N FOLLOWING) with full-window
guard, NTILE(10) per date, GROUPING SETS (third, dec)/(dec).
