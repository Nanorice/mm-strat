# prob_elite gate sensitivity — raising the floor is a VARIANCE knob (OPEN)

**Date**: 2026-07-11 · **Thread**: J (portfolio layer) · **Status**: ⚠️ OPEN — do NOT treat
as resolved. The headline (raising the gate does not help the champion) is settled; the user
has further checks to run before the topic closes.
**Arms**: `champion_trail_spygate_g20` / `_g25` / `_g30` (registry) vs `champion_trail_spygate`.
**Plan**: `plans/2026-07-11_prob_elite_gate_mismatch.md`.

---

## Why the question was raised

During the Q44 rotation-anatomy follow-up we noticed **two different `prob_elite` scales**
share one column name (the isotonic naming trap, `project_isotonic_flattens_ranking`):

| Context | Scale | Median | Gate |
|---|---|---|---|
| EDA panel parquets (`sprint_summary_eda`, multiyear) | **RAW** p_pos | ~0.55 | 0.6 raw |
| Backtest score cache (`m01_binary_calibrated_…`) → the cone | **CALIBRATED** (iso) | ~0.12 | **0.15** |

The backtest's `min_prob_elite=0.15` (in `strategy_registry._base_kwargs`) is on the CALIBRATED
scale ≈ **raw p_pos 0.48 = the model's coin-flip line**. It was set as a "coin-flip floor" and
never reconciled against the EDA's deliberate 0.6-raw gate. On famine days the day's *best*
breakout can itself be low-score, so the 0.15 floor lets the book enter "the best of a bad lot".

**Verified raw→cal mapping** (`iso.transform`, `models/m01_binary/v1/calibrator.joblib`, 2026-07-12):
cal 0.15 ⇔ raw **0.482** (coin-flip line ✅); raw **0.60 ⇔ cal 0.19**; cal 0.20 (`g20`) ⇔ raw 0.64;
cal 0.25 (`g25`) ⇔ raw 0.67; cal 0.30 (`g30`) ⇔ raw 0.80. **The EDA's 0.6-raw gate ≈ cal 0.19, best
proxied by `g20`** (marginally *stricter*), NOT g25 — an earlier note's "0.6 raw ≈ g25 / 0.20+ cal"
was off. Doesn't move the verdict: raw 0.6 lands between champion and g20, both bracketing arms lose
median Sharpe → interpolation-safe, the EDA gate cannot rescue the median.

**The concrete stake (measured on the current champion book, 2,072 pooled trades):** raising the
floor removes REAL entries — `(prob_elite < gate)`: **415 (20%) blocked at 0.20**, 532 (26%) at
0.25, 1,580 (76%) at 0.30. The 0.15–0.20 gap zone is the worst cohort (mean −0.42, 17.8% of book).
So this is NOT a cosmetic relabel — a higher gate materially changes the entry set. It earns a
real rerun (a persisted-trade post-filter is INVALID here: refusing an entry frees a slot the
rotating book refills — `feedback_rerun_dont_postfilter`).

Overlap check (the plan's key question): the gap-zone trades EXIST in `champion_trail_spygate`,
which zeroes entries when SPY≤200d → they entered with the SPY gate OPEN (regime 3 dominant).
**Regime-gate overlap ≈ 0%, not >80%** — these are genuinely unprotected bull-regime entries.

## Reconciliation with the EDA (why "gate helps" and "gate is a variance knob" are BOTH true)

The EDA (`sprint_summary_eda` §2b) tested the gate on the **RAW panel, fixed-horizon fwd return,
NO exits** — and found the score gate IS sensitive: raising raw 0.5→0.6 lifts mean fwd100
+6.8→+7.5% and fattens the tail (p95 +48→+55%). But the **median is flat-to-inverted** (5.4→4.1%
at 0.7) and loss-rate WORSENS (40→44%). i.e. even at the label level the gate buys **mean + tail,
not safety** — it concentrates jackpots while the median/loss-rate degrade.

The cone adds the **exit engine** on top. Per-trade realized pnl by calibrated bucket shows EVERY
bucket has a deeply negative median (−4 to −8%) and ~70% loss rate — the stop/trail exits realize
the median path and **truncate the exact right tail the gate was concentrating** (label p95 +55%
→ realized p95 ≈ +23–46%). So the gate's label edge lives in a tail the champion's exits largely
discard. "label lift ≠ trade edge" (`project_minervini_progfills_fails_bt`,
`project_vec_engine_optimistic`), restated on the selection floor.

## Result — the rerun (paired 90-cell cone, 2003–2026, same start-dates)

| Gate | med Sharpe | floor | p25 | %neg | med totret | p90 totret | med maxDD | med trades | wins vs base |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **0.15 (champion)** | **0.592** | −1.74 | −0.11 | 30% | **13.3%** | 50.7% | 18.5% | 28 | — |
| 0.20 | 0.462 | −1.45 | −0.01 | 27% | 9.9% | 52.1% | 20.5% | 28.5 | 36/89 |
| 0.25 | 0.505 | −1.44 | **+0.03** | **24%** | 11.7% | 50.3% | 19.3% | 28 | 36/89 |
| 0.30 | 0.349 | −1.76 | −0.28 | 34% | 6.2% | **30.5%** | 17.6% | **16** | 36/89 |

**Headline: the current 0.15 floor WINS the median-Sharpe cone.** Raising it lowers median Sharpe
(0.59 → 0.46/0.51 → 0.35) and median return. The plan's proposed fix (raise to 0.20/0.25) makes
the champion WORSE on the headline.

**The trade-off is real (variance knob, as the EDA predicted):** 0.20/0.25 buy CONSISTENCY —
floor −1.74→−1.44, p25 turns positive at 0.25 (+0.03), %neg 30%→24% — paid for in the MEDIAN, and
at 0.30 in the TAIL (p90 totret 50.7→30.5%, trades halve to 16 → book starves). Same
tail-vs-consistency signature as the governor / TP / tight stops.

**On the paired 36/89 win count:** stable across all three gates, but this is NOT "no effect" —
the distributions genuinely differ (floor/p25/%neg/median all move). The gate arms win the SAME
~36 bad-regime cells (cutting weak entries helps in bears) and lose the ~53 bull cells (cutting
entries just forgoes upside). Which cells benefit is structural (bears); the aggregate cone still
differs per gate. Keep relative-invariant (win count) and absolute-level (the cone) claims separate.

## Verdict so far (NOT final — user has more to confirm)

1. The gate mismatch is REAL and the fix as proposed is **wrong-signed** — do not raise
   `min_prob_elite` to improve the champion; 0.15 is the median-Sharpe optimum.
2. Higher gate = a **defensive variant**, not an upgrade. `g0.25` is a clean drawdown-floor trade
   (p25 +0.03, %neg 24%, floor −1.44) at ~1.6pp median-return cost — bank as a candidate ONLY,
   do NOT promote.
3. `champion_trail_spygate` stays champion, `min_prob_elite=0.15` unchanged.

**Still open (why this verdict is not marked resolved):** further user checks pending — e.g.
whether a higher gate pays off under a DIFFERENT exit (tail-harvesting vs the current trail),
combined gate × selection variants, or a different objective than median Sharpe. Hold the topic
open.

---

## Replication spec

**Registry arms** (`src/backtest/strategy_registry.py`): `champion_trail_spygate_g{20,25,30}` —
each `{**_trail_only(_champion_kwargs()), "spy_deploy_gate": {}, "min_prob_elite": <gate>}`.
Identical to the champion except `min_prob_elite` (self-check verifies diff-from-champion == that
one key). signal = `binary_gated`.

**Score cache**: `data/score_cache/m01_binary_calibrated_2003-01-01_2026-05-22_sepa_gated.parquet`
(calibrated prob_elite = `iso_calibrator.transform(p_pos)`; genuine breakouts only). The gate
filters this calibrated column in `VectorizedSEPABacktest` / `SEPAHybridV1` at entry.

**Run** (resume-safe; MUST pass the full span or it silently defaults to 2021-only — 55 cells, no
bear market):
```
for g in g20 g25 g30; do
  .venv/Scripts/python.exe scripts/run_starttime_sweep.py --strategy champion_trail_spygate_$g \
    --grid rolling --cache-start 2003-01-01 --cache-end 2026-05-22 --workers 3
done
```
Gate arms ran MONTHLY starts (269 h12 cells); the baseline champion cone is QUARTERLY (90 h12
cells). **Compare on the 90-cell intersection** (baseline ⊂ gate arms) for a true paired cone —
per-cell `metrics.json` → `sharpe_ratio` / `total_return` / `max_drawdown` / `total_trades`.
Compare script: pull `metrics.json` per `r_*_h12` cell, intersect ids, tabulate as above.

**Output**: `data/selection_sweep/starttime/champion_trail_spygate_g{20,25,30}/rolling/`.

**Gotcha log**: (i) first run defaulted `--cache-start` to 2021 → 55 cells, no bear — always pass
2003. (ii) `entry_score` in run logs is `normalized_score` (=prob_elite×100), NOT the prob_elite
the gate filters — verify gate with `trades.prob_elite.min() >= gate`, not the log. (iii) exit-aware
median is dominated by −15% stop-outs; judge on the Sharpe cone distribution, not pooled trade mean.
