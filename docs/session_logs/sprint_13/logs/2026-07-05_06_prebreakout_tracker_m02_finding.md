# Pre-breakout return tracker + m02 knob — finding (2026-07-05)

## Context
Side-quest follow-up: extend the new Watchlist Cohort-Return Tracker (Page 1) to the
**pre-breakout population**, using **m02** as the conviction knob to read "how confident is
m02 that this in-setup name is about to break out / enter the SEPA watchlist", then check
whether high-m02-confidence names actually delivered better forward returns.

## Terminology (aligned this session)
"Pre-breakout population" = names with `trend_ok=TRUE AND breakout_ok=FALSE` — a valid SEPA
setup that has **not** yet broken out / entered the watchlist. Two artifacts carry it:
- **`daily_predictions.cohort = 'pre_breakout'`** — scored rows (m01 P(HomeRun)=`prob_class_3`).
  75,912 rows already in `dashboard.duckdb`.
- **`v_d3_prebreakout`** view — the raw feature panel that feeds that scoring.

The existing tracker's cohort selectbox **already lists `pre_breakout`** → the same plot on
that population, **keyed on m01**, needs zero new code (just pick it in the dropdown).

## The m02 blocker (why we defer the m02-keyed version)
User asked for the knob to be **m02**, and flagged "m02 is binary, so there shouldn't be a
`prob_elite` column." Checked the code:

- **m02 is NOT binary. It's an XGBoost *regressor*** — `train_breakout_model.py` sets
  `objective: reg:squarederror`, `target: breakout_proximity` (continuous). Confirmed in
  `models/m02_breakout/final_20260704_175544/metadata.json` (`"kind": "final_all_period"`,
  `"target": "breakout_proximity"`).
- The panel column **`prob_elite` is a misnomer** — per sprint13_summary it is
  `breakout_proximity` **clipped to [0,1]**, uncalibrated, contract = **RANK-ONLY** ("don't
  threshold the raw value"). Observed range on the full panel is **[0, 0.31]** — never near 1.
- Panel: `models/m02_breakout/final_20260704_175544/score_panel.parquet`, cols
  `date,ticker,prob_elite,calibrated_score`, 9.36M rows, 2001→2026-06-18.
  `calibrated_score == prob_elite` in the sampled rows (calibration is a no-op today).

**Consequence:** a conviction knob like "m02 > 0.6" is exactly the absolute-threshold use the
contract forbids — the units are meaningless and the value never reaches 0.6. Wiring it now
ships false precision.

**Also not wired:** the m02 panel is a `.parquet`, absent from `build_dashboard_db.py`'s
MANIFEST → not in `dashboard.duckdb`, would break the R2 remote app if read directly.

## Decision — DEFER to next sprint (documented, not built)
Do **not** build the m02-keyed pre-breakout tracker this session. To do it honestly, next
sprint needs ONE of:
1. **Rank-percentile knob** instead of absolute threshold — "keep top X% of m02 score that
   day". Honors the RANK-ONLY contract; no calibration needed. **Lowest-effort path.**
2. **Calibrated m02 (G4)** — makes `prob_elite` a real probability, so an absolute knob
   ("> 0.6") becomes meaningful. Larger job.

Either way, wiring = add the pre-breakout-windowed m02 scores as a **table** in the
`build_dashboard_db.py` MANIFEST (parity rule), then a loader variant of
`load_cohort_return_panel` that joins m02 score instead of `prob_class_3`.

## Available now (no build)
The m01-keyed pre-breakout tracker already works: Page 1 → Watchlist Cohort-Return Tracker →
select cohort **`pre_breakout`**. Knob is m01 `prob_class_3`, not m02 — different question, but
the same "did the in-setup cohort pay?" read on the same population.
