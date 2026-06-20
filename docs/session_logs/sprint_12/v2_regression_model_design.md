# V2 Regression Model Design (Daily Snapshot Continuous Scoring)

## Goal Description
Transition from a discrete breakout-day classification model (predicting ambiguous long-term "Home Run" probability) to a continuous short-horizon regression model trained on dense daily snapshots. 

The goal is to provide specific, actionable trade management guidance (expected return, holding period, and take-profit targets) while aligning the model's training distribution with the new lifecycle-tagged daily scoring architecture. By training on all active days instead of just breakout days, we will massively expand the training data and solve the domain shift problem currently present in daily scoring.

## Open Questions & Hypotheses (Problem Formulation)
During the development phase, we need to empirically test several formulations to optimize the model:

### 1. Target Engineering
*What is the optimal Y-variable to predict?*
- **Absolute Return:** Point-to-point return over $H$ days. (Simple, but ignores intra-period drawdowns).
- **Maximum Favorable Excursion (MFE):** The peak return within $H$ days. (Excellent for setting limit sell orders/take profits).
- **Risk-Adjusted Return:** Return divided by Maximum Adverse Excursion (MAE) or localized volatility. (Trains the model to prefer smooth, low-stress winners over volatile meme stocks).

### 2. Volatility vs. Return Trade-off
*Does filtering out high-volatility setups improve long-term portfolio compounding?*
- **The Problem:** Highly volatile stocks often have the highest absolute expected returns, but they also introduce massive portfolio drawdowns.
- **The Test:** We need to evaluate whether sacrificing the highest absolute expected returns leads to a smoother equity curve and higher Sharpe ratio in the long run. We will backtest portfolios constructed from raw expected return vs. expected risk-adjusted return.

### 3. Optimal Time Horizon ($H$)
*What is the ideal holding period to predict?*
- **The Problem:** We are currently implicitly assuming a holding period, but our features might have varying decay rates for their predictive power.
- **The Test:** Train parallel models predicting horizons of $H \in \{5, 10, 21, 63\}$ trading days (1 week to 1 quarter). We will evaluate the signal-to-noise ratio (e.g., $R^2$, Rank Information Coefficient) across these horizons to find the "sweet spot" where our snapshot features are most predictive.

### 4. Autocorrelation & Data Splitting
> [!CAUTION]
> **Data Leakage Risk:** If we predict 21-day forward returns using daily snapshots, the target variables for day $T$ and $T+1$ are ~95% identical (overlapping return windows). Standard random K-Fold cross-validation will result in massive data leakage and overfitting.

- **The Solution:** We must implement strict **Purged / Embargoed Time-Series Cross Validation**. The training set and validation set must be separated by an "embargo" period of at least $H$ days to ensure no overlapping return window bridges the split. 

---

## Infrastructure Support & Gaps

**What we already have (Support):**
- **Dense Feature Table (`t3_sepa_features`):** We already have a daily dense dataset (~9.3M rows) covering 144 features for the SEPA universe.
- **Data Loading:** `src/evaluation/training_data_loader.py` already supports `mode="dense"` to pull this matrix.
- **Views:** `v_t3_training` is already set up to join the dense features with fundamentals and shares history.

**What we are missing (Gaps):**
- **Missing Dense Targets:** `t3_sepa_features` currently has **no target columns** (it was built for feature auditing, not training). Our current target calculation logic (forward returns, MFE, holding days) lives in `v_d1_candidates` / `v_d2_training`, which enforces a sparse, one-row-per-trade grain.
- **To Build:** We need a new SQL view or pipeline step (e.g., `v_t3_regression_targets`) that densely computes forward $H$-day MFE, MAE, and returns for every single row in `t3_sepa_features`.

---

## Proposed Implementation Plan

### Phase 1: Target Generation Pipeline ✅ BUILT (2026-06-20)
- Build a new SQL/DuckDB view or Python transformer that calculates forward H-day Return, MFE, and MAE for every active ticker on every trading day.
- Ensure efficient rolling window calculations over the 20+ year dataset.

**Implemented:** `scripts/build_m02_targets.py` → table `m02_prototype_targets`.
- **16.12M rows** (one per ticker/day), **16.03M with a full 21d forward window**
  (the ~87K without = last 21 trading days per ticker → NULL targets, `has_full_window=FALSE`).
- Sourced from `price_data` (contiguous), windowed `ROWS BETWEEN 1 FOLLOWING AND 21
  FOLLOWING` → gap-safe; entry day excluded from excursion (matches v_d2_training L581-582).
- Columns: `ticker, date, entry_close, horizon, has_full_window, fwd_mfe_pct,
  fwd_mae_pct, fwd_ret_pct`. Join onto t3 features by (ticker, date).
- Distribution sanity: MFE P50 +6.8% / P90 +26.4%; ret P50 +0.4%; MAE P10 −22.9%.

> ⚠️ FINDING — OHLC integrity dirt in `price_data`: 21,526 rows have `high < close`
> and 19,996 have `low > close` (penny-stock / bad-tick artifacts; `high < low` = 0).
> Naive `MAX(high)`/`MIN(low)` produced 4,468 rows violating MFE ≥ ret ≥ MAE (worst
> 1.43pp). **Fix (structural, not a tolerance hack):** bound excursions with close —
> `MAX(GREATEST(high,close))`, `MIN(LEAST(low,close))`. Economically correct (you can
> always exit at any day's close) and makes the invariant hold exactly. Violations → 0.

**Data-layer audit (2026-06-20):** row counts confirmed the grains:
  - `price_data` = `m02_prototype_targets` = **16,120,397** (all tickers × all days).
  - `t3_sepa_features` = `v_t3_training` = **9,360,773** (SEPA-candidate days only, 1:1 —
    the ASOF joins do not fan out).
  - The ~6.76M target rows beyond t3 grain are days that are not SEPA candidates. They
    drop harmlessly on the (ticker,date) join. **Kept full 16.1M** (Decision: targets
    double as a generic forward-return/MFE/MAE reference for any ticker/day). m02 loader
    must drive the join from t3 (left side) so the trained grain stays SEPA-only.

**✅ MATERIALIZED (2026-06-20): `t3_training_cache`** — the full feature matrix.
  - `v_t3_training` (t3 features + sector/industry + shares + fundamentals + derived
    pe/ps/pb/peg) was a VIEW re-running two ASOF joins every query (~80s). Now a managed
    table: **9,360,773 rows × 179 cols**, built once (~215s), count drops 80s → 0.00s.
  - Owned by `ViewManager._refresh_t3_training_cache`. **Weekly cadence — NOT in
    create_all()** (ASOF joins cost ~215s; fundamentals/shares change weekly at most).
    Run via `scripts/refresh_t3_training_cache.py` or `ViewManager().refresh_t3_training_cache()`.
    View kept as the definition source.
  - Consumers: m02 training, universe scorer, EDA, backtests.
  - **Date continuity (verified):** cache grain == t3 grain exactly (9,360,773, 1:1, no
    fan-out). It is deliberately NOT calendar-contiguous — t3 is a SEPA-*candidate-day*
    panel, so gaps are semantic ("no SEPA setup that day"), not missing data (e.g. NVDA
    has a 161d gap, AAPL 76d). SAFE for m02: gaps are feature-side only; targets were
    computed on contiguous price_data and joined by exact (ticker,date), so no forward
    window ever spans a t3 hole. INVARIANT: never compute rolling/forward quantities by
    windowing over t3/cache — always source path-dependent values from price_data.
  - ⚠️ NOTE: training-only table; NOT yet in build_dashboard_db MANIFEST (intentionally —
    not a dashboard loader). Add to MANIFEST only if a dashboard view comes to depend on it
    (see project_dashboard_remote_parity).

**Decision 1 REFINED (2026-06-20):** do NOT materialize the full joined product.
The expensive cost Decision 1 cared about is the FEATURE-side ASOF joins (fundamentals
/ shares in `v_t3_training`), NOT the target join. So split the two expensive inputs:
  - **Targets → materialized table** ✅ `m02_prototype_targets` (done; fixed forward
    window, expensive to recompute).
  - **Features → materialize `v_t3_training` as a table** (owned by `ViewManager`) —
    this captures the ASOF-join cost. (TODO)
  - **Final training matrix → join the two ON (ticker, date) at load time.** This is a
    plain equi-join (both keyed identically), cheap — no need to materialize the 16M-row
    wide product, which would force a full rebuild whenever either side changes.

> OHLC dirt is captured as a separate non-blocking ticket:
> `ticket_ohlc_integrity_check.md` (add OHLC check to data_quality.py — it has none).

### Phase 2: Purged CV & Evaluation Framework ✅ BUILT (2026-06-20)
- Implement a robust data-splitting utility that handles overlapping time-series targets without leakage (Purged GroupKFold).
- Define the evaluation metrics: Regression metrics (RMSE, MAE), Ranking metrics (Rank IC, NDCG), and risk-adjusted metrics.

**Implemented** (anchored walk-forward chosen over single holdout — multiple OOS folds
across regimes, mirrors production retrain):
- **Embargo added to the SHARED generator**, not a fork: `walk_forward.anchored_walk_forward`
  gains `embargo_days: int = 0` (additive). `train_end = test_start - 1 - embargo_days`.
  **Default 0 preserves m01's classification path exactly** (verified: all 6 existing
  walk_forward tests still pass).
- **New `src/evaluation/m02_cv.py`** — m02-specific regression harness reusing the fold
  geometry (`embargo_days = horizon = 21`) and the `gate.py` GateResult primitive:
    - `cross_sectional_rank_ic`: per-test-date Spearman(pred, realized), then averaged
      — within-date IC (the dashboard ranks candidates against each other), NOT pooled.
    - `run_m02_cv`: anchored WF per quantile (P10/P50/P90), returns per-fold IC + RMSE/MAE.
    - **`assert_no_leakage`**: executable form of the Verification Plan's "no overlapping
      dates" — asserts `max(train date) + H < test_start` every fold; raises on violation.
    - Rank IC tripwire emitted as a non-blocking GateResult on the P50 worst fold
      (kill switch, NOT the ship gate — Sharpe is the ship gate per Decision 4).
- **Tests:** `tests/test_m02_cv.py` (8 new) — embargo geometry, leakage catch/pass,
  Rank IC perfect/zero, end-to-end signal recovery. 14/14 pass incl. legacy WF.

**NOT YET (Phase 3 entry):** `train_fn` is currently caller-supplied; the quantile
LightGBM trainer itself is Phase 3. m02_cv defines the harness contract, not the model.

### Phase 3: First training run ✅ RUN (2026-06-20)

`scripts/train_m02_prototype.py` — XGBoost `reg:quantileerror`, one booster per quantile,
features = `fs_m01_prototype` (97, incl. sector/industry; reused to isolate the grain
change). 7 anchored WF folds 2019→2026, 21d embargo. ~25 min, ~7.6 GB.

| Quantile | Target | Mean Rank IC | Worst fold | Read |
|---|---|---|---|---|
| P10 | fwd_mae_pct | **+0.41** | +0.32 | INFLATED — see caveat |
| P50 | fwd_ret_pct | **+0.038** | +0.0095 | the honest signal |
| P90 | fwd_mfe_pct | **+0.39** | +0.34 | INFLATED — see caveat |

> ⚠️ INTERPRETATION — the +0.39/+0.41 IC on MFE/MAE is almost certainly NOT skill.
> MFE/MAE magnitude is mechanically autocorrelated with volatility features (a volatile
> name has both a wide historical range in the features AND a wide forward excursion —
> near-tautology). The model ranks "how volatile is this" and excursion magnitude tracks
> it definitionally. **The real signal is P50 on fwd_ret_pct (direction matters): mean
> +0.038, worst fold +0.0095.** Clears the 0.02 tripwire on average but the worst fold
> FAILS it; 2021 (+0.012) and 2025 (+0.0095) are weak. Marginal-but-plausible for a daily
> equity signal — NOT a slam dunk.

**Bug (cosmetic, not corrupting):** `enable_categorical` was passed in both the params
dict and the DMatrix. XGBoost ignored the params copy (logged a warning every fold) but
the DMatrix copy is the one that matters — sector/industry WERE handled correctly
(verified both are in fs_m01_prototype and object→category cast ran). Clean up the dup.

**Phase 3 follow-ups before any verdict:**
- Test the volatility-autocorrelation hypothesis: re-rank MFE/MAE IC *residualized* on a
  simple vol feature, or evaluate a vol-neutralized target. If IC collapses, confirmed.
- P50 is the gate-relevant number; decide if +0.038 (worst +0.0095) is worth proceeding
  to backtest. Per Decision 4 the SHIP gate is Sharpe, not IC — IC is only the tripwire.
- Smoke-test + checkpoint/resume + live logging on the next run (per feedback memory).

### ✅ Vol-autocorrelation diagnostic — CONCLUSIVE (2026-06-20)

`scripts/diag_vol_autocorrelation.py` — IC of RAW `natr` (one feature, NO model) vs each
forward target, full universe 4.06M rows, 2019+:

| Target | Model IC | Raw natr IC | Verdict |
|---|---|---|---|
| fwd_mfe_pct | +0.39 | **+0.3864** | model added ~NOTHING — pure volatility |
| fwd_mae_pct | +0.41 | **−0.4140** (same magnitude) | pure volatility, just signed |
| fwd_ret_pct | +0.038 | **−0.0213** | model FLIPPED sign + added real signal |

**Findings:**
1. **The MFE/MAE quantile IC was a mirage.** A single vol feature reproduces +0.39/+0.41
   with no model. Excursion *magnitude* ≈ volatility by definition. The "great" P90/P10
   numbers carry ZERO incremental edge.
2. **The P50 directional signal is real.** Raw natr vs forward return is −0.021 (more
   vol → slightly worse return); the model's P50 is +0.038. The model reversed the sign
   and produced positive directional IC — genuine model contribution, ~0.04, small but
   real. **This is the honest, defensible result of the whole exercise.**

**Target-design implication (decision needed — supersedes part of Decision 3):** the
TP/SL value prop assumed quantile MFE/MAE is predictable; it's mostly just volatility.
Options: (A) **vol-neutralize the MFE/MAE targets** (predict MFE/natr or residualized
excursion → "unusually large move FOR its volatility" = real tradeable edge); or (B)
**accept TP/SL = ATR-multiple bands** (no model) and let m02 focus only on P50 directional
ranking (the part with real signal).

### ✅ Phase 3 COMPLETE — 6-variant 5y sweep + calibration eval (2026-06-20)

`scripts/train_m02_prototype.py` (6 variants, train 2016+ / test 2021-2026, 5 folds, 21d
embargo, saved+checkpointed under `models/m02_prototype/20260620_202626/`) and
`scripts/eval_m02_coverage.py` (quantile calibration from saved boosters, no retrain).

**Rank IC + edge (edge = model IC − |raw natr IC|):**

| Variant | Role | IC mean | IC worst | edge |
|---|---|---|---|---|
| raw_ret | P50 raw ret | +0.024 | +0.001 | **−0.033** |
| radj_ret | P50 ret/natr | +0.012 | −0.027 | **−0.040** |
| raw_mfe | P90 raw MFE | +0.388 | +0.330 | +0.001 |
| vadj_mfe | P90 MFE/natr | +0.106 | +0.059 | +0.024 |
| raw_mae | P10 raw MAE | +0.413 | +0.394 | −0.017 |
| vadj_mae | P10 MAE/natr | +0.139 | +0.082 | +0.053 |

**Quantile calibration (the RIGHT metric for MFE/MAE levels — coverage vs 0.10 target):**

| Variant | Coverage | Pinball |
|---|---|---|
| raw_mfe (P90) | 0.129 | 2.36 |
| vadj_mfe (P90) | 0.132 | 0.65 |
| raw_mae (P10) | 0.133 | 1.78 |
| vadj_mae (P10) | 0.129 | **0.52** |

**CONCLUSIONS (honest synthesis — corrected 2026-06-20 after two follow-up questions):**

#### Finding 1 — m02 FAILED as a ranker (no monotonic agreement with realized ordering)
raw_ret / radj_ret have NEGATIVE edge: ranking today's candidates by m02's predicted
forward return orders them WORSE than ranking by raw `natr`. The model's ordering does not
match the realized future ordering any better than a single volatility feature. The
all-data +0.038 did NOT survive on recent-5y data (and was itself regime-driven: carried
by 2019-2020 folds, weak 2025). → **do NOT ship m02 for the daily rank / bump chart.**

#### Finding 2 — the TP/SL calibration is the QUANTILE LOSS working, NOT model skill
The question "how come it's a good TP/SL estimator — does it have anything to do with the
model?" has an uncomfortable answer: **almost nothing comes from the model.**

- Pinball (quantile) loss at α is *mathematically driven* to place its output where the
  realized target falls below it ~α of the time. **Calibration is a property of the
  OBJECTIVE, not of the model finding signal.** Even a model that predicts "a
  volatility-scaled constant per stock" would be well-calibrated, because the loss forces
  the level into the right place in the distribution. Coverage ~0.13 mostly says "XGBoost
  correctly minimized pinball loss" — table stakes, not skill.
- Our own two numbers prove it when read together:
  - Rank IC on MAE ≈ pure volatility (edge ≈ 0) → the model's *ordering* of drawdowns is
    the tautology "volatile names draw down more."
  - MAE quantile well-calibrated → the model's *level* is correctly placed.
  - Together: **m02's SL output ≈ "a volatility-scaled band, correctly calibrated"** —
    which is essentially what an ATR-multiple stop already is. The model wrapped
    volatility in a calibration layer; it did not demonstrate independent edge.

→ **Do NOT claim "m02 estimates TP/SL well" as evidence the model is doing meaningful
work.** The accurate claim: *quantile loss produces calibrated volatility bands, and m02
is at best a slightly-better-than-fixed-multiple way to set the band width.*

#### Finding 3 — vol-adjustment wins on pinball, but same caveat
vadj_mae 0.52 vs raw_mae 1.78; vadj_mfe 0.65 vs raw_mfe 2.36. Real improvement in level
accuracy from normalizing by natr (Option A), BUT much of the raw-vs-vadj pinball gap is
also a units effect (dividing by natr shrinks the target scale). Treat as suggestive.

#### NET / DECISION INPUT
- m02 has **no demonstrated edge** — not as a ranker (failed), not as a TP/SL estimator
  (calibration is the loss function, not the model).
- The ONLY remaining way m02 could earn its place: a backtest showing its calibrated
  vol-adjusted bands beat a plain **k×ATR** baseline on Sharpe (Decision 4 ship gate).
  That is the decisive and only honest test left. If calibrated-band ≈ k×ATR on Sharpe,
  the correct call is **Option B** (ATR bands, no model) and m02 is retired.
- This is a legitimate, well-evidenced spike OUTCOME (likely negative), not a failure of
  the infra — the harness, embargo, targets, calibration eval all worked and are reusable.

#### SPIKE CLOSED (2026-06-20) — backtest DEFERRED to a new "strategy arena" goal
The decisive backtest (m02 calibrated bands vs k×ATR on Sharpe) is **NOT m02-specific and
must NOT be built as a one-off.** The repo already has the shared infra:
  - `src/backtest/runner.py::SEPABacktestRunner` — full engine that ALREADY implements
    ATR stops/targets (params `atr_stop_mult`, `max_stop_pct`, `atr_target1_mult`,
    `atr_target2_add`, `sma_exit_period`). **The k×ATR baseline already exists.**
  - `src/evaluation/walk_forward_backtest.py` — model-agnostic WF backtest harness
    (delegated `backtest_fn`), emits Sharpe / max-DD / worst-fold gates.
  - `src/backtest/vectorized_backtest.py::VectorizedSEPABacktest` — fast variant.

→ A one-off m02 backtest would reinvent this AND answer only a narrow question. The right
container is a **new goal: "Strategy Arena"** — run m02 (calibrated TP/SL bands), m01,
the SEPA rule-based exit, and k×ATR baselines through the SAME harness with the SAME
Sharpe gate. m02's role there is precise: supply P90(MFE/natr)=TP and P10(MAE/natr)=SL as
an exit policy, benchmarked vs atr_*_mult. This also finally settles the m01 directional
question on equal footing.

**m02 deliverables this sprint (all saved/reusable):**
- `scripts/build_m02_targets.py` → `m02_prototype_targets` (16.1M, gap-safe forward 21d).
- `t3_training_cache` materialized feature matrix (weekly refresh).
- `src/evaluation/m02_cv.py` (embargoed WF + Rank IC + leakage assert) + 8 tests.
- `scripts/train_m02_prototype.py` (6-variant sweep, saved/checkpointed) +
  `scripts/eval_m02_coverage.py` (calibration). Artifacts under
  `models/m02_prototype/20260620_202626/`.
- Finding: no demonstrated edge; value-if-any = calibrated vol bands → prove-or-retire in
  the Strategy Arena backtest.

### Phase 3: Model Training Suite
- Train continuous regression models (e.g., LightGBM or XGBoost Regressor) on the daily snapshots.
- Run hyperparameter tuning and feature selection specific to regression targets.
- Execute the tests outlined in the "Open Questions" section (comparing MFE vs Return, varying $H$).

**✅ DECISION (2026-06-20): XGBoost, not LightGBM.** Original draft hedged "LightGBM or
XGBoost". Resolved to **XGBoost** for this codebase:
  - XGBoost 3.1.2 supports quantile regression natively (`objective="reg:quantileerror"`,
    `quantile_alpha`) — the original reason to reach for LightGBM (quantile loss) no
    longer holds since XGBoost 2.0.
  - **LightGBM is not installed** — choosing it adds a dependency for zero m02-specific gain.
  - Consistency: m01, `walk_forward.py`, model registry + model-card all use XGBoost;
    `enable_categorical` already proven on sector/industry. LightGBM would mean a second
    boosting lib, a new serialization format, and re-validating categoricals.
  - Plan: one booster per quantile α ∈ {0.10, 0.50, 0.90}, `enable_categorical=True`,
    satisfying the `train_fn(X, y, alpha)` contract in `m02_cv.py`; serializes as standard
    `model.json` → drops into existing registry / model-card tooling.

### Phase 4: Dashboard Integration
- Surface the V2 Expected Return, Expected MFE (Take Profit target), and Expected MAE (Stop Loss guidance) on the frontend.
- Update the daily rank bump chart to utilize the new regression scores.

---

## Verification Plan
- **Data Integrity:** Verify that the Purged CV framework completely eliminates overlapping dates between train and validation folds.
- **Model Viability:** Ensure the regression model achieves a statistically significant Rank Information Coefficient (Rank IC > 0.02) on out-of-sample data.
- **Business Logic:** Backtest the suggested Take Profit / Stop Loss levels generated by the model to confirm they improve the strategy's Sharpe ratio compared to the current unguided entry/exit approach.

---

# Review Notes & Open Decisions (2026-06-20)

> Findings from design review. The original draft above is unchanged. Items below
> are either factual corrections to the "Support/Gaps" section or open decisions to
> resolve before implementation. Resolved decisions are marked ✅.

## Factual corrections to "Infrastructure Support & Gaps"

- **`v_t3_training` is a VIEW, not a materialized table.** Defined in
  `src/backtest/universe_scorer.py` (`UniverseScorer.create_view`, ~L416) as a pure
  `CREATE OR REPLACE VIEW`, lazily created on first call to `score_from_t3()`. It is
  NOT registered in `ViewManager.create_all()`. Every `SELECT * FROM v_t3_training`
  re-runs the full join at query time:
    - `t3_sepa_features` (base)
    - `LEFT JOIN company_profiles` (sector / industry / ticker_type)
    - `ASOF LEFT JOIN shares_history`
    - `ASOF LEFT JOIN fundamental_features` (point-in-time fundamentals + derived
      pe/ps/pb/peg ratios) ← the expensive leg.
  Consequences: (1) cost is paid on every training-matrix load (bad for tuning loops);
  (2) ownership smell — the backtest scorer should not own the training-data definition.

- **`~9.3M rows / 144 features` is unverified.** Do not commit the number until a
  scoped `COUNT(*)` confirms it (bare counts on these tables OOM the session — see
  `feedback_large_dataset_queries`).

- **Loader contract is pinned.** `training_data_loader.py` hard-filters
  `feature_version = 'v3.1'` and lowercases all columns. Any new target table/view
  must emit lowercase, v3.1-consistent columns.

## ✅ DECISION 1: Materialize training data as a table (not a view)

Agreed. Replace runtime view re-execution with a materialized `t3_training_cache`
table, mirroring the existing `v_d2_training → d2_training_cache` pattern:
  - **Built by `ViewManager.create_all()`** (moves ownership out of the backtest scorer).
  - **Freshness check** reuses the loader's existing rule: cache is fresh iff
    `MAX(cache.date) >= MAX(t3_sepa_features.date)`.
  - The lazy view in `universe_scorer.py` becomes a thin fallback (or is retired).
  - This table is also where the dense targets (Decision 3) get joined/stored.

## ✅ DECISION 2: Gappy-panel — source targets from `price_data`, not t3 windows

A date-consistency check before split is necessary but NOT sufficient — it catches
*whether* gaps exist, but the corruption happens upstream at target computation and
cannot be undone downstream.

**The trap:** `t3_sepa_features` is not calendar-contiguous per ticker (lazy
materialization leaves forward-only holes — see `project_t3_forward_only_holes`).
A forward H-day MFE/MAE computed with a window function ordered over *t3 rows* will
reach across structural holes — e.g. the "21-rows-ahead" window from a given day
lands far past calendar day+21, producing a target measured over the wrong future
window and contaminated across the gap. No split-time check can detect that the
*number itself* is wrong.

**Fix (structural):** Compute forward Return / MFE / MAE from `price_data` (the
calendar-contiguous source; compute from `close`, not `adj_close` which is 100% NULL),
then **ASOF-join the targets back onto t3 snapshot rows by (ticker, date)**. Targets
live on the real trading calendar; t3 supplies features only for the days it has.
The consistency check stays as a belt-and-suspenders guardrail, not the fix.

## ✅ DECISION 3 — RESOLVED (2026-06-20): H = 21d, quantile MFE/MAE

**Locked spec:**
- **Horizon H = 21 trading days**, fixed forward window per active day.
  Rationale: V2 is a daily conviction / trade-management signal, NOT an exit policy
  (exit stays governed by SEPA C1+C2+C6). 21d gives tighter feature→target coupling,
  more samples, and cleaner decay than 63d; finding the "definitive exit horizon" is
  explicitly a non-goal. The real exit length (median 40d) is irrelevant because V2
  doesn't decide the exit.
- **Objective = quantile regression** (LightGBM `objective=quantile`) on the
  forward-21d favorable/adverse paths:
    - **P90(MFE)** → realistic take-profit target (NOT raw peak — avoids sell-at-top fiction)
    - **P10(MAE)** → stop-loss guidance
    - **P50(return)** → expected case
- **Target definition reuses the proven `view_manager.py` MFE/MAE logic** (L581-582),
  which is already `price_data`-sourced (gap-safe per Decision 2). V2 densifies it:
  same SQL shape, but every active day is a pseudo-entry over a fixed forward-21d
  window, instead of once per real trade over the variable trade window.
- **Embargo = 21d** (= H) in purged CV.

**Shelved for V2:** dynamic time-to-exit target — reintroduces sparse one-row-per-trade
grain and a path-dependent (lookahead-prone) exit date. Revisit post-V2 if needed.

### Original discussion (kept for context)

Context: SEPA is a long-hold strategy (median hold 40d, max 715d), so a 21-day
point-to-point return *understates* the opportunity. This is a valid argument for
MFE/MAE over point return, and for pushing the horizon H up.

Two refinements raised in review:
  1. **Raw MFE bakes in a sell-at-the-top fiction** (it's the peak of the path).
     The honest version of the same instinct is **quantile regression**: predict
     P90 of the favorable path (realistic take-profit) and P10 of the adverse path
     (stop), e.g. LightGBM `objective=quantile`. Keeps the "amplify the horizon"
     intent without assuming a perfect exit. Subsumes the draft's separate
     "Risk-Adjusted Return" experiment.
  2. **Horizon vs. objective are separate knobs.** The long-hold argument pushes H
     up (63d, or a dynamic time-to-exit target) — it does NOT argue against ranking.
     Keep Rank IC as an eval metric because the dashboard's job is to *order today's
     candidates*. Possible two heads: point/quantile estimates for TP/SL display,
     ranking score for the daily bump chart.

OPEN: pick H (21 vs 63 vs dynamic exit) and confirm quantile vs raw-MFE target.

## ✅ DECISION 4 — RESOLVED (2026-06-20): model name, scope, gate, baseline

**Model name: `m02_prototype`** (this version) — the dense quantile-regression
iteration of m01. The `_prototype` suffix mirrors the existing m01 naming convention
(`m01_prototype`).
> ⚠️ NAME COLLISION NOTE: an earlier "M02 = 38-feature velocity-only ignition
> classifier" appears in CLAUDE.md, and `m01_rank` (the TIMING model) already exists.
> This `m02_prototype` = the **dense forward-21d quantile MFE/MAE regression model**.
> The old M02 classifier reference is stale; reusing the m02 family intentionally.

**Sprint-12 deliverable: proof-of-viability slice.**
  - Phase 1 (dense target table) → Phase 2 (purged CV, embargo=21) → Phase 3 (one
    trained quantile model) → **GATE CHECK**.
  - Phase 4 (dashboard integration) only if the gate passes AND time remains. Do not
    wire the dashboard to an unproven signal.

**Ship gate: two-tier.**
  - **Tripwire (cheap, during training):** OOS Rank IC > ~0.02. Below this → model is
    dead, stop. Not a ship criterion, just a kill switch.
  - **Real gate:** backtest Sharpe improvement over baseline, AND the P90(MFE)/P10(MAE)
    levels must demonstrably improve TP/SL outcomes vs. the current unguided exit.

**Baseline (this slice): naive benchmark** — equal-weight / rule-based portfolio over
the same dense candidate population. Answers "is m02 worth anything at all."
  - ⚠️ This does NOT prove the domain-shift thesis. Beating naive ≠ dense-training beats
    breakout-training.
  - **Fast-follow (post-slice):** head-to-head vs. **current m01 scored on the same
    dense daily lifecycle population**. That is the real test of the domain-shift claim;
    do not drop it — just sequenced after viability is shown.

## Remaining (now trivial / deferred)

- **Embargo** is fixed at **21d** (= H) — no per-horizon parametrization needed since
  H is locked. Purged CV harness still takes H as a param for future sweeps.
