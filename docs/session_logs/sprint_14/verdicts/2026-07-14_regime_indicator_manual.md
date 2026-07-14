# Regime-Indicator Test Manual — consolidated verdict

**Date**: 2026-07-14 · **Runbook**: §0.7 completed (Block A full; Block C for the two ladder leads).
**Executes**: `plans/regime_indicator_test_manual.md`. **Deliverable**: `cells/regime-indicator-results.ipynb`.

**Scripts (all reproducible, in `sprint_14/scripts/`):**
- `regime_candidate_features.py` — SPY/QQQ technicals + whole-universe breadth, expanding-z + shift(1), as-of identity self-check → `data/model_output_eda/regime_gauge/candidate_features_daily.parquet`.
- `regime_candidate_blockA.py` — WFO AUC nowcaster sweep (all 15 candidates) → `blockA_results.json`.
- `regime_candidate_cone.py` — Block-C BackTrader cone, candidate-gate swap → `cand_*_cone_summary.json`.
- `build_regime_indicator_nb.py` — regenerates the results notebook from the caches.

---

## TL;DR

**The regime-indicator lever is retired — clean, expected null.** No candidate clears the nowcaster
wall (Block A AUC ≥ 0.65; incumbent 0.53). The best of 15 candidates is **breadth at pooled AUC
0.55**, statistically indistinguishable from the SPY-200d baseline (0.53). The two highest-prior
candidates (§6.8 slope, §4 breadth) were taken to the P&L cone anyway (the manual's realistic
promotion path); the cone verdict is in §3. This is the **fifth independent falsification** of "a
second regime axis beats SPY-200d for this strategy."

---

## 1. Setup

- **Label (L1)**: fwd50 cohort bad-day = bottom-tercile of `loss_mean` (downside-only cohort mean),
  from `gauge_label_fwd50_downside.parquet` (built by `regime_gauge_label.py`). 33% base rate.
- **Features**: 21 raw candidate signals on SPY+QQQ (§6.1–6.9) + whole-universe breadth (§4),
  all expanding-z, shift(1). Liquidity floor $1M/day 63d-avg dollar-vol for breadth (~1200–2800
  names/day). As-of identity self-check PASSES (no look-ahead in the z-norm).
- **WFO**: anchored expanding yearly, first test year 2003, **50d embargo** (fwd50 leakage guard),
  min-train 750 rows. Pooled OOS 2003–2025, 22 folds, n=5787 days.
- **Baseline**: SPY-below-200d (`p_bad = 1 − spy_above200`). Reproduces the manual re-baseline
  **exactly**: pooled AUC **0.531**, crisis 0.594, calm 0.520.

## 2. Block A — Nowcaster (label separation) — ALL FAIL

Best pooled AUC per candidate (across standalone / group-logit / group-XGB modes):

| Candidate | best pooled AUC | Δ vs base | AUC calm | AUC crisis | Verdict |
|---|--:|--:|--:|--:|---|
| **§4 breadth** | **0.550** | +0.019 | **0.709** | 0.554 | FAIL (0.65 wall) — calm-only tell |
| §6.8 SPY 200d slope+dist | 0.536 | +0.005 | 0.565 | 0.589 | FAIL |
| §6.3 Donchian | 0.549 | +0.018 | 0.622 | 0.565 | FAIL |
| §2 RV22 (vol) | 0.519 | −0.012 | 0.692 | 0.510 | FAIL (redundant w/ VIX) |
| §5-batch (6-feat XGB) | 0.519 | −0.012 | 0.481 | 0.579 | FAIL |
| §6.5 SuperTrend | 0.509 | −0.021 | 0.593 | 0.541 | FAIL |
| §6.7 BBW | 0.492 | −0.039 | 0.524 | 0.437 | FAIL (worse, CI excl 0) |
| §6.4 Aroon | 0.485 | −0.046 | 0.508 | 0.478 | FAIL (worse) |
| §6.9 QQQ/SPY-RS | 0.508 | −0.023 | 0.428 | 0.608 | FAIL (worse, CI excl 0) |
| §6.2 ADX | 0.455 | −0.076 | 0.457 | 0.404 | FAIL (worse, CI excl 0) |

**Three reads:**
1. **The field is jammed at coin-flip.** Best candidate (breadth, 0.55) barely clears baseline (0.53)
   and is a country mile from the 0.65 wall. This reproduces the manual's own expectation: **the
   feature class caps ~0.56 on this label.** Block A is a WALL by design — it did its job.
2. **The block-bootstrap CI (50d blocks, 1000 resamples) on the Δ vs baseline includes 0 for every
   candidate that beats baseline** (breadth, slope, Donchian). The only CIs that *exclude* 0 are for
   candidates significantly **WORSE** than baseline (ADX, BBW, QQQ-RS, batch-logit). Not one candidate
   is statistically better than SPY-200d.
3. **The one honest positive is calm-year breadth (AUC-calm 0.71).** Breadth separates bad days in
   *calm* years — the 2015-16-style chop the incumbent flips through — but is *worse* than baseline in
   crises and still sub-bar overall. A calm-only nowcaster is a diagnostic tag, not a strategy input.

**Redundancy (§0.7-11):** breadth ρ=0.78 vs SPY-dist200 (below the 0.85 kill line — genuinely
semi-orthogonal), but no significant marginal lift → null. RV22/BBW ρ≈0.8 with VIX (redundant vol
axis, as predicted). ADX/QQQ-RS orthogonal (ρ≈0) but that's orthogonal *noise* (worst AUC).

**Block-A GATE (§0.7-8):** pooled < 0.62 AND worst-fold < 0.55 for ALL candidates → the manual says
STOP and bank as null for everything except the two leads carried to the cone by §7's ladder rule.

## 3. Block C — Governor (BackTrader P&L cone)

Same 90-cell rolling cone as `champion_trail_spygate` (2003–2026, quarterly starts, 12m horizons);
the SPY-200d deploy gate is swapped for the candidate gate (live-safe, shift(1)).

- **§6.8 slope**: deploy iff `SPY>200d AND 200d-slope>0` (strong-bull only). Gate deploys 6075/8418 days.
- **§4 breadth**: deploy iff `breadth_200d > 0.5`.
- **composed (OR)**: deploy iff `SPY>200d OR candidate`.
- **Baseline** cone (existing artifact) reproduces the manual reference **exactly**: median Sharpe
  **0.757**, p25 −0.05, floor **−1.93**, %neg **28%**.

| Arm | n | median Sh | p25 | floor | %neg | vs baseline |
|---|--:|--:|--:|--:|--:|---|
| Baseline (SPY-200d gate) | 89 | 0.757 | −0.046 | −1.934 | 28.1% | — |
| §6.8 slope — candidate-only | 86 | **0.593** | −0.119 | −2.520 | 29.1% | median **−0.16**, floor −0.59, %neg +1pp |
| §6.8 slope — composed (OR) | 89 | 0.762 | −0.125 | −1.903 | 31.5% | median +0.005, floor +0.03, %neg **+3.4pp** |
| §4 breadth — candidate-only | 90 | **0.464** | −0.123 | −2.582 | 30.0% | median **−0.29**, floor −0.65, %neg +1.9pp |
| §4 breadth — composed (OR) | 90 | 0.753 | −0.027 | −1.934 | 26.7% | median −0.004, floor 0.00, %neg −1.4pp |

**§4 breadth — FAILS both cone criteria.** The `breadth>0.5` gate standalone is the *worst* arm in
the whole study: median Sharpe collapses 0.29 below the incumbent and the floor deepens to −2.58 —
breadth sits out too many good days (it's a slower, noisier version of the price gate). The SPY-OR-
breadth arm is a **wash** (−0.004 median, identical floor): breadth>0.5 and SPY>200d overlap so
heavily that their union ≈ SPY-200d alone (the §0.9-3 overlap trap — the candidate ≡ the incumbent).
**BANK as curio.** Note this is the candidate whose Block A calm-year AUC (0.71) looked most
promising — and it still can't convert that into P&L, the textbook "label lift ≠ trade edge" outcome.

**§6.8 slope — FAILS both cone criteria.** The stricter "strong-bull only" gate (candidate-only)
*hurts*: median Sharpe drops 0.16 and the floor deepens to −2.52 (it sits out good-but-weak-bull
runs the incumbent rides). The looser SPY-OR-slope gate is a **wash** (+0.005 median, and %neg
actually rises 3.4pp). Classic GATE×TILT: adding the slope condition either subtracts real
deployment or adds nothing. **BANK as curio.** _(cone crashed once mid-run on a foreign DB
read-write lock — PID 4988, an open kernel; fixed by hoisting the SPY-gate to a single DB load +
retry, then resumed to completion. Result unaffected.)_

**Promotion criteria** (must clear ≥1): (b) median-Sharpe uplift ≥ +0.15 & floor loss ≤ 0.05, or
(c) max-DD reduction ≥ 20pp & median drop ≤ 0.10.

## 4. Decision (pre-registered)

- **§6.2 ADX, §6.3 Donchian, §6.4 Aroon, §6.5 SuperTrend, §6.7 BBW, §6.9 QQQ-RS, §2 RV22, §5-batch:**
  **KILL** at the Block-A gate. None reached even 0.55 pooled; several significantly worse than
  baseline. (§3 SRISK / §5 NFCI external pulls were NOT run — the manual flags them as completeness
  theater once the batch retrain shows no credit-shaped hole, which it doesn't.)
- **§6.8 slope, §4 breadth:** Block-A FAIL **and** Block-C FAIL. Both standalone gates score *worse*
  than SPY-200d on the cone (slope −0.16, breadth −0.29 median Sharpe); both composed-OR arms are
  washes (≈ SPY-200d, because the candidate deploy-days overlap the incumbent's). **BANK both as
  curios.** No promotion. The §7 stopping rule triggers here: the two highest-prior candidates both
  missed the cone, so the ladder terminates — the batch/HMM rungs are not reached (Block A already
  killed them as nowcasters, and neither offers an orthogonal cone mechanism the two leads lacked).

**Standing conclusion:** SPY-200d remains the whole regime tool. Per-day nowcasting of bad days for a
50d continuation strategy is near-impossible at this horizon (the regime signal is a *mean-shift*, not
day-level *separability* — reconfirmed from a fresh feature set). Lever retired.

## 5. Caveats

- **Directional fwd label** (close-to-close, no exits) for Block A — optimistic, same caveat as every
  multiyear cut; Block C (real stops/gaps/rotation) is the honest promotion bar and is why it's run.
- **Breadth universe** = liquid price_data names, not full CRSP; small-cap tilt would make breadth
  *lead* SPY-200d (a feature, per §4) — didn't help here.
- **AUC on autocorrelated days** — mitigated by 50d-block bootstrap CIs (never raw p-values, per §0.9-6).
