# Verdict: coincident trade-gauge — multivariate macro barely beats SPY-200d, and only via XGBoost in crises

**Date:** 2026-07-13 · **Status:** ✅ BUILT + RUN (walk-forward 2004-2025, both label variants).
Executes §0.5.3 of `plans/2026-07-13_regime_tiering_and_system_usage.md` — the user's angle:
build a model-agnostic cohort-loss label and test whether a MULTIVARIATE live-safe macro model
tells bad breakout-days from good ones better than the incumbent SPY-200d binary.
**Scripts:** `regime_gauge_label.py` (label), `regime_gauge_train.py` (walk-forward train/eval).
**Artifact:** `data/model_output_eda/regime_gauge/gauge_label_fwd20_downside.parquet`.

---

## 1. What was built (the uncovered angle from §0.5.2)
- **LABEL (model-agnostic, NEW):** one row/day over the t3-scored SEPA cohort (~650 names/day,
  `multiyear/raw_full_*_fwd.parquet` — uses ONLY fwd returns, m01 score dropped). Two variants,
  both tested: **(A) loss_mean** = cohort mean of downside-only fwd (`min(fwd,0)`; weight is a
  one-line-swappable registry — `semivar`/`plain` also available); **(B) hostility** = fraction of
  cohort with fwd ≤ −15% (the stop). The two agree strongly (spearman −0.95) — they flag the same
  bad days, as they should.
- **TARGET:** binary BAD-day = bottom tercile of label-goodness (~35% base rate).
- **FEATURES (live-safe):** spy_ret20/60/120, vix_close, vix_chg20, stress_ew_vix, stress_cr,
  stress_ew_rank — the expanding-z composites from `entry_timing_features.py` (raw pillar LEVELS
  excluded as non-stationary). **Multivariate — the thing C7 never tried.**
- **VALIDATION:** expanding walk-forward by year; pooled + per-year OOS AUC vs the SPY-200d baseline.
- **HORIZON** parameterized (fwd20 this cut; fwd50/100 swappable next iteration).

## 2. Result — pooled OOS AUC (2004-2025)
| model | loss_mean target | hostility target |
|---|--:|--:|
| **SPY-200d baseline** | 0.537 | 0.568 |
| logistic (multivar) | 0.491 | 0.554 |
| xgboost (multivar) | 0.520 | **0.602** |

**Three honest reads:**
1. **Coincident bad-days are HARD to nowcast — SPY-200d itself is barely above coin-flip (0.54–0.57).**
   The 5× *forward-return* gap from Q15 (`capital_deployment`) is a MEAN-SHIFT, not day-level
   separability: knowing the regime tilts the average return, it does NOT cleanly classify which
   individual days will be hostile. This reframes the whole "gauge" ambition — the ex-ante signal is
   a distribution-shifter, not a per-day oracle.
2. **Logistic LOSES to the baseline on both labels.** Its top coef is `stress_ew_vix` **+0.85 (wrong
   sign** — says high stress ⇒ bad day, but stress precedes the rebound). **This is C7's wrong-sign
   finding reconfirmed at the multivariate level:** a LINEAR combination of the pillars cannot beat
   one binary, because the pillars individually point the wrong way and linearity can't rescue them.
3. **XGBoost beats the baseline only on hostility (0.602 vs 0.568), and only via crises.** Per-year
   lift is concentrated in **2016 (+0.23) and 2022 (+0.37)**; it LOSES in most calm years. This is a
   real non-linear interaction (stress matters *conditional on* trend — the sign-flip §0.5 predicted)
   but it's **fragile and crash-concentrated**, not a durable calm-market edge.

## 3. Verdict against the plan's kill-criterion
The §0.5.3 kill-criterion was: *no AUC lift + wrong-sign pillars → SPY-200d is the whole tool.*
- **Logistic: KILLED cleanly** (no lift, wrong sign — C7 confirmed multivariate).
- **XGBoost: PARTIAL survive** — a +0.03 pooled lift on hostility, but crisis-only and label-dependent.
  Not enough to promote as a standing gauge; enough to say the *interaction* is real.

**Bottom line: SPY-200d stands as the primary regime tool.** No multivariate macro model earns a
durable, calm-market lift over it for *per-day* go/no-go. The one thing that helps (XGB in 2016/2022)
is a **crash-detector**, which is the stress axis the sprint already banked as DD-control, not alpha
([[project_entry_timing_macro_axis]]) — arriving here again by a third independent route.

## 4. What this closes / implies for §1.2
- **Closes** the "do the pillars JOINTLY separate bad days" question left open by C7: they don't,
  linearly; non-linearly only in crashes. The gauge is not a second validated regime axis.
- **§1.2 (per-regime strategy split) should therefore split on SPY-200d only** — coarse, as its own
  caveat demanded. We do NOT have a second axis to tier on.
- The XGB crisis-interaction is a candidate **overlay** (a "crash-day" flag stacked ON the 200d gate),
  NOT a replacement — same role as the governor. Park it as such; don't build a tiered gauge on it.

## 4b. fwd50 re-baseline (added 2026-07-14 — the production-target horizon)
The regime-indicator manual (`plans/regime_indicator_test_manual.md`) uses **fwd50** (production
target), so the baseline was re-run at fwd50. It is WORSE, not better, than fwd20:

| model | fwd20 (this verdict) | fwd50 |
|---|--:|--:|
| SPY-200d baseline (loss_mean / hostility) | 0.537 / 0.568 | **0.531 / 0.541** |
| logistic | 0.491 / 0.554 | 0.478 / 0.497 |
| xgboost | 0.520 / 0.602 | 0.541 / 0.558 |

**The longer horizon LOWERS day-level AUC.** The Thread-F "signal grows with horizon" is a *mean-gap*
fact (stress-calm gap ×3 fwd20→fwd100); it does NOT carry to per-day *classification*. So the incumbent
is even closer to coin-flip on the production label (0.53), and the whole feature class caps ~0.56.
Reinforces the verdict: SPY-200d stands; per-day nowcasting of bad days is near-impossible at any horizon.

## 5. Caveats
- **Directional fwd, no exits/sizing** — the label is close-to-close cohort fwd20 (optimistic; same
  caveat as every multiyear cut). A stop-aware label (variant B partially addresses this) doesn't
  change the verdict.
- **AUC on autocorrelated days** — pooled AUC treats days iid; the per-year table is the honest read
  and it's where the crisis-concentration shows. No block-bootstrap CI run (the point estimate is
  decisive enough: ~coin-flip baseline, no durable lift).
- **fwd20 only.** Next iteration: re-run at fwd50/100 (label builder + trainer already parameterized).
  Prior (m01×regime) says the regime SIGNAL grows with horizon — but that's the mean-gap, and this
  verdict is about day-level *classification*, which the horizon may not rescue. Worth one check.
- **8 features, expanding WF.** Not exhaustively tuned; but the failure is structural (wrong-sign
  pillars), not a tuning miss — more trees won't flip the sign.

## 6. Files
- `docs/session_logs/sprint_14/scripts/regime_gauge_label.py` — cohort→day label (both variants, swappable weight, self-check).
- `docs/session_logs/sprint_14/scripts/regime_gauge_train.py` — walk-forward train/eval vs SPX200 baseline.
- `data/model_output_eda/regime_gauge/gauge_label_fwd20_downside.parquet` — the 25y label (regenerable).
