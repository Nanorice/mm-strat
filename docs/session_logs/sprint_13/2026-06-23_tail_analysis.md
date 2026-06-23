# Session Log: 2026-06-23 — bearish-event / tail analysis (`notebooks/sings_of_tail.ipynb`)

> Sprint 13, Goal C. Exploratory notebook: do QQQ bearish events have *leading* signs,
> do they open persistent bearish periods, and do SEPA breakouts / M03 / the 5-risk-factor
> model carry timing information? Can SEPA track sector rotation?

## 🎯 Question
Around QQQ bearish events — are there **leading** signs (early warning), or only
**coincident/lagging** ones? Can SEPA breakout activity flag sector rotation?

## Setup
- QQQ daily returns, 2010+. Bearish cutoff = bottom 5% of daily returns = **−2.07%**. 207 bearish days.
- **Data note:** `adj_close` / `adj_factor` / `vwap` are NULL table-wide in `price_data` →
  analysis uses `close` (fine for QQQ; splits can distort multi-day single-stock fwd
  returns → prefer medians). Flagged for **Goal D** hygiene.

## How the method tightened (the key lesson)
1. First cut: clustered bearish days (5-day gap) → **110 point-events**, ±PRE/POST windows.
   Showed an apparent **lead** — scores drifting down, VIX rising, exposure cutting *before* day 0.
2. Suspected event-clustering contamination → merged overlapping windows into
   **43 distinct bearish periods**, anchored on **onset** (first −2% day of the episode).
3. **De-overlapping erased the lead → it was an artifact.** Proof: **50% of the unmerged
   "pre-crash" days physically sit inside a *prior* event's post-crash window.** A real lead
   survives de-overlapping; this one didn't.
4. Resolution: **merged/onset = the predictive question (our goal)**; unmerged/event = a
   *conditional* question ("−2% days cluster mid-drawdown") — true but different. **Default to merged.**

## ✅ Findings
- **No leading signal for fresh bearish periods.** Onset-anchored, VIX (~16.5), `weighted_z`
  (~−0.22), `target_exposure` (~0.61), M03 (~62) are **flat until day 0**, then jump. The
  day-0 VIX spike is **mechanical** (a −2% day *is* a vol-spike day), not foresight.
- **Risk-factor decomposition** (sensitivity = |pre→event-window swing|):
  **z_vix (0.48)** and **z_trend (0.37)** dominate but are **coincident**; **z_hy (credit)**
  is flat at the event then **widens for ~20 days after** — the only factor carrying *new*
  post-event information; **z_term / z_slope inert**. → `z_hy` is the candidate
  "is this becoming a real bear" tell.
- **Bearish events open persistent regimes.** Post-event VIX stays ~21 (vs 16.9 baseline),
  exposure stays cut (~0.50 vs 0.60) for 20 days. Not predictable, but not a one-day blip.
- **SEPA breakouts do NOT lead** — neither sector rotation before drawdowns (industry
  breakout-rate lift ~0.68–1.12, i.e. noise) nor industry outperformance generally
  (rolling breakout-share change vs fwd 21d relative return: **corr 0.008**, flat quintiles).
  Breakouts are a **coincident** momentum marker.

## Net
For early warning: **risk model ≈ M03 (same-day confirmers) >> SEPA breakouts (no lead)**.
Three clean **negative results** — they close off "use breakouts/regime score to *anticipate*
drawdowns" and redirect toward (a) `z_hy` as a regime-deepening signal and (b) conditional
(post-down-day) de-risking rather than prediction.

## ⏭️ Open / next
- **Rotation, second pass** before abandoning: swap breakout *count* → `rs_universe_rank`
  (textbook rotation signal); lengthen horizons to 63/63; test sustained *level* not Δ.
- **Isolate z_hy** post-event trajectory: does its slope separate one-off dips from real bears?
- **Trough-anchored** view (vs onset) for bottom / recovery shape.
- **Goal D:** `adj_close` / `adj_factor` columns exist but are never populated by the pipeline.

## 📝 Artifacts
- `notebooks/sings_of_tail.ipynb` — analysis (merged onset-anchored windows; M03 + z-factor
  range plots with ±1 SE bands; rotation test).
- Tables used: `price_data`, `t3_sepa_features` (breakout), `company_profiles` (industry),
  `t2_regime_scores` (M03), `t2_risk_scores` (5-factor).
