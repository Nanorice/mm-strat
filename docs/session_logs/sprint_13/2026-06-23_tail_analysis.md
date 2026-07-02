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

## 🔁 Rotation, second pass — DONE (2026-06-23) → still no lead
Re-ran rotation with the upgraded signal (`RS_Universe_Rank`, not breakout count),
63/63 horizons, **merged onset-anchored** windows (80 events), sustained-**level** test.
Two operationalizations, both negative:
- **Intensity** (cross-sectional std of sector mean-ranks): PRE 0.0985 / EVENT 0.0972 /
  POST 0.1000 — **flat into onset, drifts up only after**. Same coincident-to-lagging shape
  as VIX / `z_hy`.
- **Direction** (defensive−cyclical mean-rank): PRE **−0.023** / EVENT −0.009 / POST −0.010 —
  defensives *under*perform right up to onset and **snap up AT day 0** (mechanical). No risk-off
  rotation builds beforehand. Pre-window level vs fwd drawdown depth: **corr +0.019 (n=80)**.
- **Verdict:** three independent rotation proxies (breakout-share Δ 0.008, rank dispersion,
  def−cyc spread) all show **no lead**. Rotation hypothesis is now closed.
- Cells (verified): `2026-06-23_rotation_second_pass_cells.md`.

## 🔬 Regime models reframed — coincident vol meters, NOT drawdown predictors (2026-06-23)
Dropped the drawdown-as-pivot framing (which assumes the signal sits near the drop) for two
cleaner tests. Cells: `2026-06-23_regime_conditional_cells.md`.
- **Lead-lag sweep** (does it lead at ANY horizon?): `corr(z_vix_t, fwd return)` is **+0.09 → +0.30
  rising with horizon** — the *opposite* of a leading bear signal. No danger factor leads.
  "Signal fired too early to show in a ±63d window" is **falsified**.
- **Conditional outcomes** (danger fires → what happens?): danger signals are **contrarian-bullish
  on the MEAN** (z_vix top decile → +4.0% fwd-21d vs +1.6% base; +9.0% fwd-63d vs +4.8%) — the
  volatility risk premium / mean-reversion. But the **left tail fattens** (P5 −10% vs −7%, mean MDD
  −4.2% vs −2.9%). They signal **dispersion, not direction**. `veto_flag` is the lone exception:
  P(neg) 36% @63d vs 24% base with no mean lift — worth a separate look.
- **Position-sizing is the real use, horizon = 1–2 weeks.** `corr(z_vix_t, realized vol next H)`
  **peaks 0.67 at H=5–10d**, decays past 21d. Annualized 5d-fwd vol is **monotone across z_vix
  deciles: 9.4% → 33.7%**. Clean vol-target signal; useless as long/flat market timing.

## ❓ Does M03 drag M01? NO — answered by existing ablation, dropping it costs −0.22 Sharpe
`models/m01_binary/v1/evaluation/full_eval/ablation/ablation_summary.json` (walk-forward,
baseline Sharpe 1.045). All 3 M01 feature sets carry all 7 m03_* cols (group `M03_Regime`).
Δ Sharpe when each group is dropped:
`Core_Volume −0.57 > Fundamentals −0.51 > Momentum_RS −0.41 > Moving_Averages −0.26 >
Categoricals −0.24 > **M03_Regime −0.22** > Fast_Alphas −0.12 > Technical_Oscillators +0.00 >
Volatility_Ranges +0.13`.
- **M03 is a net-positive, mid-pack contributor — NOT a drag.** Removing it cuts total return 198%→114%.
- **Reconciliation:** M03 fails as a *standalone drawdown predictor* (notebook) but helps M01 as a
  *coincident state descriptor* for cross-sectional selection ("given this regime, which names work").
  Good state descriptor ≠ good future predictor; no contradiction. **Keep M03 in M01.**
- **Actual prune candidates:** `Volatility_Ranges` (dropping it *improves* Sharpe +0.13) and
  `Technical_Oscillators` (zero contribution). gain-importance corroborates: M03 = 6.5% of total gain,
  top m03 col = m03_pillar_risk (#15 of 97).

## 🔗 Merge M03 + risk model? NO. Tier calibration? YES (M03 only). (2026-06-23)
Cells: `2026-06-23_regime_merge_tiers_cells.md`.
- **Overlap is ~30%, not redundant.** corr(m03_score, weighted_z) = −0.57; danger-flag Jaccard 0.45
  (disagree on ~55% of flags). Pillar map: `pillar_trend ≈ −0.88 z_trend` (redundant), `pillar_risk
  ≈ −0.66 z_vix` (partial), **`pillar_liq ≈ 0 everywhere` (orthogonal net-liq — risk model has no
  equivalent)**. Incremental fwd-vol corr: weighted_z keeps **+0.42** after removing m03, m03 keeps
  −0.19 after removing weighted_z → both carry independent signal. **Don't merge** — would kill
  pillar_liq + risk-model vol content, and breaks M01's 7-col M03 feature set (retrain cost).
  → For the "cleaner/one-place" goal: present as a **2-axis dashboard panel** (x=m03 regime quality,
  y=weighted_z stress), highlight the both-agree corner. Optionally drop M03 `pillar_trend` as a
  redundant *input* pending an M01 ablation check.
- **Tiers ARE monotone (scores directionally honest) but cut points are mis-placed.** M03 fixed
  0/25/50/75/100 bins are unbalanced (221/916/2125/878 days) and assume a uniform 0–100 spread that
  doesn't exist (median 61, p10 33). Decile scan: fwd vol **cliffs in the bottom ~20%** (m03 23→31%
  vol, 48→17%) then **flat from ~50→90 (17%→12%)** — the score only discriminates below ~40–50.
  → Recalibrate M03 to **empirical-percentile / 3-tier on the real breakpoint**: Danger <40 /
  Neutral 40–70 / Benign >70. **Risk model's `target_exposure` ladder (0.15/0.35/0.75–0.85/1.0) is
  already monotone + well-spaced — leave it.**

## 🧬 Unified factor space — PCA/clustering + a WEIGHT BUG (2026-06-23)
Cells: `2026-06-23_unified_factor_cells.md`. Pushed past "merge?" into structure + correctness.
- **2-axis (M03 × weighted_z) DOES add info, but marginally.** R² explaining 5d fwd vol: m03 0.20,
  weighted_z 0.32, both 0.34, both+interaction 0.35. Second axis worth ~+0.02–0.04 R². Real but small
  — value is the **off-diagonal disagreement** (trend/liq fine but stress spiking, or weak trend yet
  calm), not the bulk.
- **PCA on the unified 7-factor set has clean meaning.** EVR [0.46, 0.18, 0.13, 0.11, 0.07, 0.04, 0.01].
  **PC1 = broad risk-on/off** (z_trend 0.54, z_slope 0.44, z_vix 0.40). **PC2 = credit-vs-curve**
  (z_hy +0.47 vs z_term −0.61). **PC3 ≈ pure net-liquidity** (m03_pillar_liq 0.88) — confirms net-liq
  is a genuinely independent axis the 5-factor model lacks. So a unified model should be **PCA/IC-weighted,
  not hand-summed.**
- **KMeans(4) → interpretable regimes:** calm/weak-trend low-liq | risk-OFF high-vol (run~11d) |
  calm high-liq (best fwd return) | **CRISIS cluster (n≈29, all Mar–Apr 2020, fwd_vol 0.72, run~15d)**.
  Clusters persist (run-lengths 6–15d) → not noise; position in factor space = market condition.
- **❌ RETRACTED "weight bug": there is NO weight bug.** Earlier claim (f_vix 93.5%) was an ERROR —
  it measured the raw `f_*` columns (f_vix = VIX *spot* ≈9–82; f_trend ≈±0.04), whose magnitude is
  dominated by VIX purely due to *units*, not importance. The model z-scores each factor FIRST, then
  applies `WEIGHTS={z_vix .25, z_hy .25, z_term .15, z_trend .15, z_slope .20}`
  (`src/pipeline/risk_5_factor.py:40,237`). `weighted_z = sum(z*W)` reconstructs the stored column
  EXACTLY (corr 1.0, diff 0.0). **Correct variance-share of weighted_z:** z_vix 29.5%, z_hy 24.8%,
  z_slope 21.7%, z_trend 19.1%, **z_term 4.9%**. Genuinely balanced, properly normalized — exactly the
  "z-score the bases" design. The "looks like just VIX" effect is **factor CO-MOVEMENT in stress**
  (z_trend corr w/ weighted_z 0.87 > z_vix 0.78), not VIX domination. Only real takeaway: **z_term is
  near-inert (4.9%)** — candidate to drop/re-spec; minor, not a bug.
- **Data completeness — VERIFIED availability (2026-06-23):**
  - **✅ FIXED (2026-06-23): orphaned derived macro rows deleted.** Correction to earlier framing —
    this was NOT a live bug degrading M03. M03 derives net-liquidity **on-read** from raw
    WALCL/WTREGEN/RRPONTSYD (`MacroEngine.get_all_macro_data`, fresh to 2026-06-22); it never reads the
    stored rows. The issue was 6 DERIVED symbols (`net_liquidity, fed_assets, tga, rrp, hy_spread, vix`)
    frozen at 2026-02-19 in `macro_data`, written once by commit cfcadc0, read by no live code (only
    archive/ legacy). Duplicate-of-raw landmine. **Action:** backed up 36,150 rows →
    `data/_backup_macro_derived_20260624.parquet`, then DELETEd. `macro_data` is now raw-series-only
    (8 symbols, single source of truth). M03 verified unaffected post-delete.
  - **Binding constraint:** risk model uses 2555d (10yr) rolling z → any new factor needs ~10yr history
    before first valid z. Disqualifies short series.
  - **DFII10 (10Y real yield):** ✅ FRED, 2003+, one-line add to `config.FRED_SERIES`. Captures real-rate
    regime nominal term-spread misses (e.g. 2022). **Best add.**
  - **DXY/USD:** UUP proxy in price_data (2007+); corr +0.13 vs z_vix → independent. Or DTWEXBGS from FRED.
  - **Credit HYG/LQD:** both in price_data (2007+); HYG/LQD 20d ret corr −0.25 vs z_hy → partly new.
  - **MOVE (bond vol):** in price_data but **2021+ only (1318d)** → too short for 10yr z. **Reject for now.**
  - **VIX term-structure (^VIX3M) / equity breadth:** not in DB → need new ingestion. Defer.
  - **Recommendation order:** (1) fix net-liq staleness, (2) add DFII10 as factor 6, (3) add net_liquidity
    as explicit risk factor (in M03, NOT in 5-factor; PC3 showed independent), (4) defer MOVE/VIX-term/breadth.

## ⏭️ Open / next
- **Isolate z_hy** post-event trajectory: does its slope separate one-off dips from real bears?
- **Trough-anchored** view (vs onset) for bottom / recovery shape.
- **Goal D:** `adj_close` / `adj_factor` columns exist but are never populated by the pipeline.

## 📝 Artifacts
- `notebooks/sings_of_tail.ipynb` — analysis (merged onset-anchored windows; M03 + z-factor
  range plots with ±1 SE bands; rotation test).
- Tables used: `price_data`, `t3_sepa_features` (breakout), `company_profiles` (industry),
  `t2_regime_scores` (M03), `t2_risk_scores` (5-factor).
