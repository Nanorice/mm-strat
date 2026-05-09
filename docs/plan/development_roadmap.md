# Upcoming Features and Improvements Plan

> Planned improvements and ideas for the SEPA pipeline, risk management, dashboard, and ML models.

---

## 1. Feature Engineering: "Days Since Breakout"
*   **Concept**: The timing of entry and conviction of the strength of a setup might differ for a newly broken out ticker vs. one that broke out last week. 
*   **Current State**: When training the model on M01, we used snapshot data for a ticker when the breakout happened to predict the lifetime return of holding it. Because the backtest evolves this score every day and checks the quality of its setup, and the buy decision is made across many tickers, adding a "days since breakout" feature makes sense. However, in the current training data, this feature is essentially 0 because we train on the breakout day snapshot.
*   **Path Forward**: 
    *   Think about how to better apply the model. We could develop a new model to decide on timing.
    *   Alternatively, we could run the current model for a few days post-breakout to identify the best timing to enter. This approach might also naturally expand our dataset.

## 2. Risk Management: 5-Factor Regime Model
*   **Concept**: We have a prototype risk management model located at `test_field/risk_5_factor/risk_5_factor_model.py` which computes a 5-factor regime-switching risk score (VIX, HY OAS, Term spread, Trend, Slope) with target exposure bands.
*   **Path Forward**:
    *   **Dashboard Integration**: Add this risk model output to the Streamlit dashboard to visualize the current market risk regime.
    *   **Backtest Integration**: Integrate the risk exposure bands into the backtest for dynamic position sizing or vetoing trades (e.g., using the veto flag or target exposure).
    *   **Pipeline Orchestration**: Add this script to the daily orchestrator so it runs daily alongside the rest of the pipeline.

## 3. Dashboard Redesign
*   **Concept**: Overhaul the Streamlit dashboard for better usability, model tracking, and ticker analysis.
*   **Path Forward (New Pages/Views)**:
    *   **Model Registry**: A page showing registered models. Clicking on a model should display its evaluation report (metrics, plots, diffs).
    *   **Feature List**: A cheat sheet view of all features. Hovering over a feature should show how it's calculated.
    *   **SEPA Candidates (Current Page)**: Enhance the active candidates page to show:
        *   Most recent data and scores.
        *   Date added.
        *   Macro data (like M03 regime scores and the new 5-Factor Risk scores from Point 2).
    *   **LLM Ticker Analysis**: An LLM API integration to analyze a chosen ticker's context. Ideally, this will use a locally hosted model. (Note: This is considered a late-stage feature).

## 4. Classification Model Strategy: Addressing M01 Performance
*   **Current Evaluation Context**:
    *   **What's Working**: Top-K Lift is the key metric. The model shows real edge at K=10, 50, 100 for "Home Run (>30%)" and "Strong (10-30%)" classes. At threshold=0.50, we get 807 signals with 61.3% precision on Strong+HomeRun. The model separates Home Run probabilities well (+0.102 separation, ROC AUC 0.693).
    *   **What's Broken**: 
        *   *Poor classification accuracy (29.8%)*: It struggles to predict exactly which of the 4 buckets a trade lands in, though it ranks Home Runs well.
        *   *Dead Zone for "Strong"*: The "Strong (10-30%)" class has terrible metrics (F1=0.195, AUC=0.522) likely because the 10% boundary is economically arbitrary.
        *   *Feature Importance Disagreement*: XGBoost gain favors volatility/VCP features (natr, consolidation_width), while SHAP favors momentum/RS features (rs_ma, sma_50_slope). Need to investigate which is exploited vs. noise.
        *   *Recent Degradation*: Accuracy dropped to 0.246 in 2026 vs 0.318 in 2023. Could be a regime shift or simply trades not fully playing out yet.
*   **Path Forward (Two Options)**:
    *   **Option A (Collapse to Binary)**: Predict "Home Run (>30%)" vs. Rest. Since ROC AUC is already 0.693 for this, a binary model with a tuned threshold is more actionable than the confused 4-class setup.
    *   **Option B (Use as a Ranker)**: Drop the "accuracy" framing. Use `P(HomeRun)` as a continuous score to rank SEPA candidates daily. Top-K lift confirms this already has an edge.
    *   *Action Item*: Deep dive into the feature importance divergence (SHAP vs Gain) before retraining, as reliance on natr/volatility might not generalize.

---

## 5. Dense T3 Dataset: Model Development & Flexibility

> *Added 2026-05-08*

### Context

With the dense T3 table now built, we have a fundamentally more flexible dataset. Previously, T3 only stored rows on the day of breakout for SEPA candidates. Now, T3 carries every SEPA-watchlist ticker's full daily history (gated by `sepa_watchlist` membership). When joined with `shares_history` and `fundamental_features` via the `v_t3_training` view, this produces a complete daily feature matrix suitable for both training and inference.

### What This Unlocks

| Capability | Before (Sparse T3) | Now (Dense T3) |
|---|---|---|
| **Score evaluation** | Only on breakout day | Any trading day |
| **Question the model answers** | "Is this ticker a good setup on breakout day?" | "Is this ticker a good setup today?" |
| **Training data scope** | ~19K breakout snapshots | Full daily panels for all watchlist tickers |
| **Holding-period analysis** | Post-hoc only | Live daily score evolution during holding |
| **Re-scoring for strategy tuning** | Requires re-running feature pipeline | Pre-computed; just re-predict |

### Assessment

This is a **high-impact, foundational improvement**. The dense dataset directly enables items 6–8 below and removes the "breakout-day-only" constraint that limited both the model's training signal and the strategy's ability to time entries. The main risk is data volume (~100x more rows than the sparse version); this has already been addressed by the optimized `compute_t3_features()` with quarterly chunking and the O(N log N) vectorized scorer.

**Infrastructure status**: ✅ Dense T3 pipeline is operational. `v_t3_training` view is created by `UniverseScorer.create_view()` with ASOF JOINs for fundamentals and shares.

**EDA status** *(2026-05-09)*: ✅ `scores_cache.parquet` (4.03M rows × 209 cols) profiled. Signal validated — see item 6 findings. Data quality note: ticker **LIF** removed (3.2M% return on 2024-07-05 — ticker reuse artifact). Policy: do not cap returns; drop confirmed bad tickers by name only.

---

## 6. Score Distribution Analysis & Multi-Horizon Target Validation

> *Added 2026-05-08*

### 6a. Elite Score Distribution Analysis

**Goal**: Understand the statistical distribution of `prob_elite` (P(HomeRun)) and `calibrated_score` (expected MFE) across the universe, and test whether these scores have a statistically significant correlation with realized returns.

**Approach**:
1.  **Distribution profiling**: Histogram + KDE of `prob_elite` across all (date, ticker) pairs in the dense T3 dataset. Segment by regime (`m03_score` buckets) and by `trend_ok` / `breakout_ok` status.
2.  **Correlation with return**: Compute Spearman IC between `prob_elite` and forward returns at various horizons. Use the Newey-West adjustment for autocorrelation in overlapping returns.
3.  **Lift analysis**: Bucket scores into deciles; compute mean realized return per decile. Confirm monotonicity.

**Feasibility**: ✅ Fully doable today with the existing dataset. The scorer already outputs `prob_elite` and `calibrated_score` per (date, ticker). Forward returns (`return_1d`, `return_5d`, `return_20d`, `return_60d`) are pre-computed in T3. This is essentially an EDA notebook exercise.

**EDA findings** *(2026-05-09)*: ✅ Complete.
- `prob_elite` is right-skewed (0.026–0.826). Model is conservative — never assigns very high probabilities.
- `breakout_ok=True` rows are 3.5% of universe (141K rows), mean score = 0.306.
- **Decile 9** (prob_elite ≥ 0.435): Mean 20d return = +13.4%, Median = +12.0%, 402K rows, 1,822 tickers. Broad-based signal — mean and median differ by only 1.4pp.
- **IC within decile 9 = 0.45** — signal is continuous, not binary. Sub-quintile 4 (score ≥ ~0.65): Median 20d = +29.8%, 86.2% hit rate for +10%.
- **Effective live threshold: ~0.60** (sub-quintile 3 entry), not 0.50. The model's score range tops out at 0.83.
- **Regime gate**: IC collapses to −0.01 in Bear regime (m03_score < 40). Gate on `m03_score > 60` improves effective IC from 0.059 → ~0.09. Hard filter only — does not improve in-regime signal quality.
- **Pending**: Redo decile table with cross-sectional demeaned (excess) returns to strip market beta from deciles 0–8.

### 6b. Multi-Horizon Target Experiments

**Goal**: Test whether the model trained on a random holding period (lifetime MFE until trend break) generalizes to predict returns over *defined* horizons: 1-day, 3-day, 5-day, 20-day, and "lifetime" (until `trend_ok` flips to False).

**Approach**:
1.  **New target columns**: Compute forward returns at {1d, 3d, 5d, 20d, 60d} for every (date, ticker) row in the dense T3 dataset. Most already exist in T3 (`return_1d`, `return_5d`, `return_20d`, `return_60d`); we need to add `return_3d` and the "lifetime return until trend break" target.
2.  **Re-score without re-training**: Use the existing M01 classifier as-is. For each horizon, correlate `prob_elite` with the forward return at that horizon. The question is: *does a model trained on lifetime MFE also rank well for short-term returns?*
3.  **If promising**: Retrain separate models per horizon (e.g., `M01_5d`, `M01_20d`) and compare lift curves.

**Assessment**: This is a **critical validation step** before investing in strategy development. If the current model's score correlates well across multiple horizons, it suggests the signal is structural (quality of setup), not tied to the specific training target. If it only predicts lifetime MFE well but not 5-day returns, then the model is capturing something real but unusable for tactical timing.

**Dependencies**: Dense T3 dataset (item 5 ✅). Minimal new code — mostly notebook analysis.

**EDA findings** *(2026-05-09)*: ✅ Core complete.

| Horizon | Mean IC | t-stat | Verdict |
|---|---|---|---|
| 1d | −0.014 | −2.89 | ❌ Inverts — mean reversion on breakout day |
| 5d | +0.015 | +3.08 | ✅ Weak positive |
| **20d** | **+0.059** | **+10.54** | ✅✅ Primary horizon |
| 60d | +0.044 | +8.46 | ✅ Strong |

**Conclusion**: Signal is **structural** — a model trained on lifetime MFE correlates with returns at all positive horizons. The 1d inversion confirms do not enter at breakout-day close. Score momentum (`score_delta_5d`) IC vs return_20d = 0.166 — independent secondary signal.

**Remaining**: `return_3d` and "lifetime until trend break" targets not yet computed. Per-horizon model retraining (M01_5d, M01_20d) deferred pending OOS validation.

---

## 7. Strategy: Score Evolution & Entry Timing

> *Added 2026-05-08*

### Goal

Given a model that scores setups daily (enabled by dense T3), analyze how the score evolves over time for each ticker and identify patterns for optimal entry timing.

### Approach

1.  **Score trajectory analysis**: For each ticker that eventually becomes a "Home Run," plot the time series of `prob_elite` from T−30 to T+30 around the breakout date. Look for common patterns:
    *   Does the score ramp up before breakout? (early signal)
    *   Does it peak on breakout day? (current assumption)
    *   Does it plateau or decline after entry? (conviction decay)

2.  **Sliding-window re-scoring**: Apply the model with a 1-day shift in the training date cutoff (walk-forward style). Compare how the same ticker's score changes as the model "sees" more recent data. This tests stability of the signal.

3.  **Entry rule candidates**:
    *   **Momentum entry**: Enter when `prob_elite` crosses above a threshold AND is rising (positive delta over 3d).
    *   **Confirmation entry**: Wait N days post-breakout; enter only if score remains above threshold.
    *   **Relative entry**: Enter the top-K scoring tickers each day, regardless of breakout timing.

### Assessment

This is **the core strategy question** — and it only becomes answerable with the dense dataset. Previously we could only ask "should I buy on breakout day?"; now we can ask "when is the best day to buy?" The risk is overfitting entry rules to historical patterns. Mitigation: use walk-forward validation with strict train/test separation.

**Dependencies**: Items 5 (dense T3 ✅) and 6 (score validation — should be done first to confirm the score is predictive at all).

**EDA findings** *(2026-05-09)*: 🔄 In progress — `notebooks/scores_eda.ipynb`.

**Score trajectory** (Home Run vs Non-event, T−30 to T+30):
- Score **ramps from T−10** before breakout (0.37 → 0.51) — leading indicator exists
- Score **peaks at T=0** (breakout day) then decays to ~0.40 by T+30
- Non-event tickers flat at ~0.18 throughout — structurally different, not just a different moment
- **Exit signal candidate**: monitor score daily; exit when it drops below 0.435 (decile 9 floor)

**Entry rule comparison** *(in-sample / data leakage — structural ordering only)*:

| Rule | Median 20d | Hit >10% | N | Notes |
|---|---|---|---|---|
| Level only (≥0.60) | 39.0% | 93.8% | 27,886 | Baseline |
| Level + rising score | 39.0% | 94.6% | 20,456 | No improvement; cuts 27% of signals |
| **Level + 3 consecutive days** | **42.0%** | **94.2%** | **13,654** | ✅ Best rule |

**Top-K daily**: Top-10 (Mean 37.5%, Median 29.1%) is the practical sweet spot. Top-5 is too concentrated.

**Recommended strategy prototype**: `prob_elite ≥ 0.60` for 3+ consecutive days + `m03_score > 60` regime gate + Top-10 daily selection. Requires OOS validation before backtesting.

---

## 8. Sector Rotation: Daily Setup Density by Sector

> *Added 2026-05-08*

### Goal

Surface sector-level intelligence on the dashboard: today, how many tickers have a good SEPA setup, and which sector has the densest concentration of high-scoring setups?

### Approach

1.  **Daily sector heatmap**: Group the daily scored universe (`v_t3_training` + scorer output) by `sector` from `company_profiles`. For each sector on each day:
    *   Count of tickers where `trend_ok = TRUE`
    *   Count of tickers where `trend_ok = TRUE AND breakout_ok = TRUE`
    *   Count of tickers where `prob_elite >= threshold` (e.g., 0.25)
    *   Mean / median `prob_elite` for the sector

2.  **"Hottest sector" widget**: A dashboard component showing today's densest sector (by count of high-scoring setups) and a 5-day rolling comparison to detect rotation.

3.  **Historical sector rotation chart**: Time series of sector setup density (sparkline or stacked area chart). This visually shows sector leadership shifts — e.g., "last week Tech led, this week it's Industrials."

### Assessment

This is **highly actionable and low-effort**. The data already exists:
- `company_profiles` has `sector` and `industry` per ticker
- T3 has `trend_ok` and `breakout_ok` daily
- The scorer outputs `prob_elite` per (date, ticker)

The only new work is the dashboard page and a lightweight aggregation query. The cross-sectional rank features (`RS_Sector_Rank`, `Sector_Momentum`, `RS_Industry_Rank`) already computed in T2/T3 provide additional context.

**Fast-moving markets observation**: The user correctly notes that sector leadership rotates quickly. This widget surfaces that rotation empirically rather than relying on intuition. It also naturally complements the "relative entry" strategy from item 7 (enter the densest sector's top picks).

**Dependencies**: Dashboard (item 3), scorer, `company_profiles` table. All available today.

---

## 9. M03 Feature Review: Memory, History, and Z-Score Enhancement

> *Added 2026-05-08*

### Current M03 Architecture

The M03 regime calculator (`src/pipeline/m03_regime.py`) uses a **point-in-time formula** approach:
- **Trend pillar** (40%): `50 + 50 * tanh(pct_above_sma_200 * 10)` — a memoryless function of today's SPY price vs SMA-200.
- **Liquidity pillar** (30%): 20-day linear regression slope of net liquidity — has a 20-day lookback window but no longer-term context.
- **Risk appetite pillar** (30%): Linear interpolation of VIX and HY spread against fixed thresholds — completely memoryless.

The M01 features derived from M03 add some temporal memory:
- `m03_delta_5d` and `m03_delta_20d`: 5/20-day velocity (diff of composite score)
- `m03_regime_vol`: 10-day rolling std of composite score

**Key limitation**: The raw pillar scores have **no distributional memory**. A VIX of 18 always maps to the same score, whether the market has been at VIX=12 for a year (18 is elevated) or at VIX=30 for months (18 is a relief rally). The thresholds are hardcoded constants, not adaptive.

### 5-Factor Risk Model Comparison

The 5-factor risk model (`test_field/risk_5_factor/risk_5_factor_model.py`) takes a fundamentally different approach using **rolling z-scores**:

| Aspect | M03 (Current) | 5-Factor (Prototype) |
|---|---|---|
| **Normalization** | Fixed formula with hardcoded thresholds | 10-year rolling z-score (ROLLING_WINDOW_Z = 2555 days) |
| **Memory** | None (point-in-time) + 5d/20d deltas | Full distributional memory — a z-score of +1σ means "elevated relative to the last 10 years" |
| **Output** | 0–100 score → category | Weighted z-score → 5-year rolling percentile → exposure band |
| **Extreme detection** | Threshold comparison (VIX > 25 = bearish) | Veto flag when ANY z-score ≥ 2.0σ — adapts to the prevailing regime |
| **Factors** | 3 pillars (trend, liquidity, risk appetite) | 5 factors (VIX, HY, term spread, trend, slope), all risk-oriented |

### What We Can Leverage

1.  **Z-score normalization for M03 pillars**: Replace the `tanh(pct_above * 10)` and linear-interpolation formulas with rolling z-scores. This gives each pillar distributional context:
    *   VIX = 18 when the 2-year mean is 14 → z = +1.2 (elevated)
    *   VIX = 18 when the 2-year mean is 25 → z = −1.5 (calm)
    *   The same raw value maps to different risk signals depending on history.

2.  **Rolling percentile for the composite score**: Instead of fixed category thresholds (>80 = strong_bull, etc.), use a rolling percentile rank of the composite score. This prevents the model from being "stuck" in one regime when the macro environment structurally shifts.

3.  **Veto mechanism**: The 5-factor model's veto flag (any single z ≥ 2.0σ) is more robust than M03's simple threshold gating. A single extreme reading in one factor overrides the composite — this catches tail events that a weighted average would dilute.

### Proposed Path Forward

| Step | Description | Effort |
|---|---|---|
| **9a** | Add rolling z-score variants of each M03 pillar as **new** features (e.g., `m03_trend_z`, `m03_liq_z`, `m03_risk_z`). Keep existing features for backward compatibility. | Medium |
| **9b** | Add a rolling percentile rank of the M03 composite score (`m03_pct_rank_252d`) as a new feature. | Low |
| **9c** | Add a veto flag feature (`m03_veto`) that fires when any pillar z-score exceeds a threshold. | Low |
| **9d** | Run feature importance analysis (SHAP) comparing old M03 features vs. new z-score variants. If the z-score versions have higher predictive power, promote them as primary features. | Medium |
| **9e** | Consider merging the 5-factor model's factors (term spread, slope) into M03 to consolidate into a single regime model. The 5-factor model currently runs standalone with its own FRED data fetch — it should share M03's `MacroEngine` data source. | High |

### Assessment

This is a **well-motivated enhancement**. The M03 features are currently the weakest link in the feature set — they are simple math formulas without distributional awareness. The 5-factor model already demonstrates the z-score approach works for risk scoring. The key question is whether rolling z-scores improve M01's predictions (testable via SHAP analysis in step 9d). The risk is adding redundant features that the model can't exploit — mitigated by running 9d before committing to a full rollout.

**Dependencies**: None — M03 and the 5-factor model are both operational. Steps 9a–9c can be done independently of the other roadmap items.

### EDA Findings (2026-05-09): M03 Pillar Decomposition

Tested each M03 pillar as a standalone gate vs the composite:

| Gate | IC | Rows | Verdict |
|------|-----|------|---------|
| No gate | 0.065 | 100% | Baseline |
| **Trend pillar > 60** | **0.118** | 70% | ✅ Best single filter |
| **Trend + Liq > 60** | **0.126** | 38% | ✅ Best combo |
| Composite > 60 | 0.116 | 58% | Suboptimal weighting |
| Liquidity pillar > 60 | 0.080 | 52% | Marginal standalone value |
| Risk pillar > 60 | 0.066 | 58% | ❌ No value — same as no gate |
| All 3 pillars > 60 | 0.082 | 27% | ❌ Risk pillar dilutes signal |

**Key conclusions:**
1. **Trend pillar is doing all the work.** Use `m03_pillar_trend > 60` instead of `m03_score > 60` for gating.
2. **Liquidity pillar adds marginal value.** Trend + Liq (IC=0.126) beats Trend alone (IC=0.118).
3. **Risk pillar is useless or harmful.** Adding it to any combination reduces IC. The VIX/HY thresholds are poorly calibrated.
4. **Composite weighting is suboptimal.** The 40/30/30 split dilutes the trend signal.

**Revised recommendations:**
- **9a (z-score variants)**: Still valuable, but prioritize `m03_pillar_liq_z` — liquidity is the only pillar worth enhancing. Trend already works well with fixed thresholds (SPY vs SMA-200 is inherently normalized).
- **9c (veto flag)**: Deprioritize — the risk pillar's failure suggests VIX/HY-based veto would not add value.
- **9e (merge 5F into M03)**: The liquidity pillar (net liquidity slope) is the only M03 component to consider adding to 5-factor — it's not captured by VIX/HY/term spread.

### M03 vs 5-Factor Comparison (2026-05-09)

Tested both models as regime gates on `prob_elite` IC vs `return_20d`:

| Gate | IC | Rows | Notes |
|------|-----|------|-------|
| No gate | 0.059 | 100% | Baseline |
| M03 > 60 | 0.094 | 58% | +60% IC lift |
| 5F exposure ≥ 0.75 | 0.097 | 55% | +65% IC lift |
| **M03>60 AND 5F≥0.75** | **0.105** | 45% | ✅ Best — models are additive |
| Both reduce (agree bad) | −0.005 | 32% | Correct to avoid |
| Disagree (M03 bull / 5F cautious) | 0.059 | 13% | Neither dominates |
| Disagree (M03 bear / 5F low-risk) | 0.064 | 11% | Neither dominates |

**Key conclusions:**
1. **Both models work, and they're additive.** Combined gate (IC=0.105) beats either alone.
2. **5F veto is not useful.** "No veto" gate has lower IC than no gate (0.058 vs 0.059).
3. **Neither model dominates in disagreement zones.** When they conflict, IC is weaker but still positive.
4. **5F's advantage is marginal.** 0.097 vs 0.094 — not a clear winner on its own.

---

## 10. Data Quality: Return Calculation Validation

> *Added 2026-05-09*

### Issue Identified

During EDA on `scores_cache.parquet`, discovered inconsistent `return_1d` calculations for certain tickers:
- **CUE** (2026-04-24): `return_1d = 30.93` (3093%) but actual close prices show ~6% move (16.63 → 17.70)
- **LIF**: 3.2M% return on 2024-07-05 — ticker reuse / near-zero denominator artifact

Other tickers (GME, KODK) have correct return calculations for their known spike dates.

### Suspected Cause

Misaligned price join in T3 pipeline — possibly stale previous-day close being used for return calculation, or adjusted/unadjusted price mismatch.

### Path Forward

| Step | Description | Effort |
|---|---|---|
| **10a** | Add validation check in T3 pipeline: flag rows where `return_1d` implies a previous close inconsistent with actual data | Low |
| **10b** | Cross-check `return_Xd` columns against raw price series for a sample of high-return rows | Low |
| **10c** | Investigate root cause — check ASOF join logic for price lookups, especially around ticker changes or missing dates | Medium |

### Current Workaround

Maintain `BAD_TICKERS` exclusion list: `{'LIF', 'CUE'}`. Remove all rows for these tickers from analysis. This is a temporary fix — root cause should be addressed in the pipeline.
