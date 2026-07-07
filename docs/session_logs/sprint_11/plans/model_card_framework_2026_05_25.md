# Model Card Framework: Strategy-Free Model Evaluation

**Author:** Hang + Claude
**Date:** 2026-05-25
**Status:** DRAFT — for review before implementation
**Applies to:** `m01_binary/v1`, `m01_prototype_2003_2026/v2`, and all future m01 variants

---

## 0. Why this exists

Every existing "is the edge real?" gate in this repo runs through a backtest. That means whenever a model fails a gate, we cannot tell whether the **model** is bad or the **strategy wrapping the model** is bad.

Concrete example from session log `2026-05-25_binary-pruned-and-deep-rigor.md`:

| Lens | Verdict on `m01_binary/v1` |
|---|---|
| WF backtest mean Sharpe | 0.476 — **FAIL** (gate 0.5) |
| Decile IC | -0.120 (p=0.024) — **FAIL** (negative & significant) |
| Permutation null | percentile 6.5 — **FAIL** (worse than 93.5% random) |
| Strategy S3 (P≥0.30, 5-position cap) | Sharpe **1.59** — **PASS** |

Same model. Different strategies. Opposite verdicts. We currently have no way to say "the *model itself* is good/bad" independent of the wrapper.

This document defines a **deterministic, strategy-free model card** that answers one question: **given the prediction task the model was built to solve, does it solve it well?** Strategy comes later.

---

## 1. Scope & contract

### 1.1 The question both m01 models answer

> Given an active SEPA-watchlist row at date D, what is the probability the trade entered on D produces a "home run" (MFE > 30%) over the label horizon?

- `m01_binary/v1`: binary head — `P(class=1)` where class 1 ≡ MFE > 30%
- `m01_prototype_2003_2026/v2`: 4-class head — `P(class=3)` where class 3 ≡ Home Run; the other 3 classes (Noise/Moderate/Strong) are *finer resolution on the negative-of-interest*

For comparability, the prototype is projected to binary by `P_homerun_prototype = P(class=3)`. All ranker/gate metrics use this projection.

### 1.1a What "good" means for *this* user (anchor for the rubric)

The framework above answers "is the model good as a binary home-run classifier?" That is necessary but not sufficient. The user's stated definition of a good model has three parts:

1. **High precision** — when the model commits (P ≥ T), the trade should actually be a home run.
2. **Recall on super-performers** — among the realised top-tail trades (10x candidates, not merely MFE > 30%), the model should have surfaced them with high P.
3. **Magnitude monotonicity** — P should be ordinal in *realised magnitude*, not just in *probability of crossing 30%*. A 0.9 should mean "bigger winner" than a 0.6, not just "more likely to cross the 30% line."

The card therefore evaluates two distinct things:
- **Binary classifier quality** (Sections B, C, E, G — already covered)
- **Magnitude-aware ranking quality** (Section D, expanded — see §3.D below)

A model that scores 18/18 on the binary view but flat on magnitude diagnostics is a *good 30%-crosser detector*, not a *home-run finder*. The rubric explicitly distinguishes these.

### 1.2 Evaluation universe

**SEPA candidates only** — rows reaching the model in production, sourced from `d2_training_cache` filtered to the SEPA-watchlist population (matching `v_d3_deployment` semantics).

Rationale: metrics computed on the broader `d2_training_cache` would be optimistically biased by non-SEPA rows the model never scores in deployment.

### 1.3 Ranker contract (two evaluation modes)

Verification on 2026-05-25 against `v_d2_training` and `t3_sepa_features` confirmed that the C1/C2/C6 booleans referenced in earlier drafts do **not** exist as separate columns. They were collapsed into a single boolean **`trend_ok`** (close > SMA50 AND close > SMA150 AND close > SMA200) carried on both `t3_sepa_features` and `v_d2_training`. The framework uses `trend_ok` everywhere C1+C2+C6 was previously referenced.

`v_d2_training` is a **per-trade ledger** (one row per SEPA entry, ~38K rows over 2001–2026), not a daily snapshot. Each row carries features-as-of-entry plus the realised outcome (`mfe_pct`, `mae_pct`, `return_pct`, `entry_date`, `exit_date`, `holding_days`, `sl_triggered`). The 4-class and binary labels both derive from `mfe_pct`. This shape supports two evaluation modes:

**Mode A — Entry-only ranker (headline)**

This is the natural reading of `v_d2_training`:
- Pool on date D = all trades with `entry_date = D AND trend_ok = TRUE`
- Each ticker contributes at most once per session (no daily re-rank, no carry-over)
- Each row already has the realised outcome attached
- Rank metrics computed on `(ticker, D, P, mfe_pct, label_binary)` within each D

**Question Mode A answers:** *"On the day a trade was available to enter, was higher P actually a bigger / more likely winner?"*

This is the cleanest signal-detection test and what the headline Section D rubric scores against.

**Mode B — Stateful daily pool (supplementary)**

Mode A doesn't test the *deployment* behaviour, which is: every day, look at all open SEPA candidates with `trend_ok = TRUE`, re-rank by their latest P, and pick top-K. Mode B mirrors that:
- Pool on date D = every `(ticker, D)` from `t3_sepa_features` where `trend_ok = TRUE` AND the ticker has been scored at least once on or before D
- Latest P attached per ticker (the most recent score on or before D, using features as of D−1)
- Realised outcome attached from the trade entered on D (if any) — otherwise the row contributes only to rank-stability metrics, not to outcome-conditional metrics
- Heavier reconstruction (per-date query against `t3_sepa_features`)

**Question Mode B answers:** *"In live deployment, does picking the top-K by current-day P beat random?"*

Mode B is reported in §D as a sub-section, with the same metric set (IC, top-K lift, decile MFE profile, tail recall) computed on the stateful pool. Disagreement between Mode A and Mode B is itself information (e.g., model good at scoring entries but P stales quickly).

**Gates apply only to Mode A** (the headline). Mode B is diagnostic — failures there generate warnings, not blocks.

### 1.4 What this framework does NOT do

- It does **not** evaluate strategies (position sizing, stop logic, max-positions, transaction costs). Those live in the WF backtest and its derivatives.
- It does **not** replace the deep-rigor suite. The deep-rigor suite tests whether the *strategy + model* has a real edge; the model card tests whether the *model* has a real edge.
- It does **not** judge live deployment readiness. A model can pass the card and still fail in production due to drift, regime change, or strategy interaction — those are separate gates.

---

## 2. Three-layer verdict structure

| Layer | What it answers | Output |
|---|---|---|
| **Scorecard rubric** | "How good is this model on each dimension?" | 0–3 score per metric family (Poor / Marginal / Good / Strong), aggregate band |
| **Gates** | "Does the model meet minimum thresholds for deployment?" | PASS/FAIL per gate, blocking vs warning |
| **Benchmarks** | "How much better is this than a baseline?" | Delta vs random / majority / prior version |

All three are produced in one report. They serve different consumers:
- Scorecard = quick read for the modeller
- Gates = deployment go/no-go
- Benchmarks = lift quantification for the whitepaper / decision log

---

## 3. The seven evaluation sections

Each section has: **what it tests**, **why it matters**, **how to read the numbers**, **scorecard rubric**, **gates**, **benchmarks**.

### Section A — Input data integrity

**What it tests:** is the data we trained/evaluated on what we think it is?

**Why it matters:** every downstream metric is meaningless if the labels are leaked or the features are mis-aligned. Garbage in, garbage out — and you cannot detect this from confusion matrices.

**Checks:**

| Check | How | Why |
|---|---|---|
| A1. No temporal leakage | `leakage_guard.py` already exists — confirm every feature column has `as_of_date ≤ entry_date`. Verify `mfe_pct`, `mae_pct`, `exit_date`, `holding_days` are excluded from the feature set (these are outcome columns) | Future information in features → inflated metrics that vanish in production. Outcome columns on the same row as features is a known footgun on `v_d2_training` |
| A2. Label horizon correctness | Spot-check 100 rows: `exit_date > entry_date`, `mfe_pct >= 0`, label_binary = (mfe_pct > 30). Reconcile binning logic against `label_registry/mfe_binary_homerun_v1.json` and `mfe_4class_v1.json` (registry version `a2bb79a`) | Label drift between training and registry has happened (binary reformulation, May 2026) |
| A3. SEPA candidate match | The eval universe row-count equals `v_d3_deployment` row-count for the same date window. Verified 2026-05-25: 1976 rows match exactly across both. **Caveat:** `v_d3_deployment` window is 2025-09-12 → 2026-05-22 (rolling 252d). Eval windows wider than this date range cannot use `v_d3_deployment` semantics directly and must apply the SEPA filter to `d2_training_cache` themselves | If they differ, you're evaluating on the wrong universe |
| A4. Class balance | Report `mfe_pct > 30` prevalence in train / val / test splits. Registry states ~14.5% base rate; verify against the actual eval window. **Caveat:** `v_d2_training.mfe_pct` mean=14.3, median=7.25 — base rate may be window-dependent. Report per-fold prevalence in WF-CV setup, not just pooled | Establishes the random-guess baseline. If class 1 is 14%, predicting "always 0" has 86% accuracy — meaningless. Per-fold prevalence matters because regime-dependent base-rate drift inflates apparent stability |
| A5. BAD_TICKERS exclusion | Confirm `LIF`, `CUE`, etc. (from memory `bad_tickers_not_filtered`) are excluded from eval data. Verified 2026-05-25: not in `v_d3_deployment`. For wider eval windows on `d2_training_cache`, the filter must be applied explicitly | Per memory: bad tickers reach backtests; same risk for eval if window predates the fix |
| A6. trend_ok consistency | Confirm `trend_ok` semantics match SEPA exit logic per memory `sepa_exit_logic`: close > SMA50 AND close > SMA150 AND close > SMA200. Cross-check between `v_d2_training.trend_ok` and `t3_sepa_features.trend_ok` for the same `(ticker, date)` pairs | The framework treats `trend_ok` as the canonical active-pool gate. Any drift between the two sources invalidates §D-Mode-B vs §D-Mode-A comparison |

**How to read:**
- A1–A3 are binary PASS/FAIL gates. Any FAIL invalidates the entire card.
- A4 establishes the floor that all downstream metrics must beat to be non-trivial.

**Scorecard:** This section is gate-only (no rubric scoring). Either the data is sound or the card is void.

**Output artifact:** `model_card/section_a_data_integrity.json`

---

### Section B — Discrimination (classification quality)

**What it tests:** does the model separate positives from negatives at all?

**Why it matters:** before asking "is the threshold right?" or "are probabilities calibrated?" we have to know there's signal to threshold or calibrate. A model with random discrimination cannot be fixed by post-processing.

**Metrics:**

| Metric | What it means | How to read |
|---|---|---|
| B1. **ROC-AUC** | Probability a random positive scores higher than a random negative | 0.5 = random; 0.6 = weak; 0.7 = decent; 0.8+ = strong. **For rare-event problems (8% home runs), be skeptical above 0.85 — likely leakage** |
| B2. **PR-AUC** | Average precision across all recall levels | More honest than ROC-AUC when classes are imbalanced. Baseline = class-1 prevalence (~8%); 0.15 = 2× lift; 0.30 = 4× lift |
| B3. **Brier score** | Mean squared error of probabilities vs realised outcomes | Lower is better. Baseline = predicting class prevalence for all rows. Beats baseline ⇒ probabilities carry information |
| B4. **Log-loss** | Penalty for confidently wrong predictions | Lower is better. Useful for comparing two models, less useful in absolute |

**Scorecard rubric (per metric, ranker + gate use):**

| Score | ROC-AUC | PR-AUC (relative to prevalence) |
|---|---|---|
| 0 (Poor) | < 0.55 | < 1.5× prevalence |
| 1 (Marginal) | 0.55–0.60 | 1.5–2× |
| 2 (Good) | 0.60–0.68 | 2–3× |
| 3 (Strong) | > 0.68 | > 3× |

**Gates:**
- B-gate-1 (blocking): ROC-AUC > 0.55 on SEPA universe
- B-gate-2 (blocking): PR-AUC > 1.5× class-1 prevalence
- B-gate-3 (warning): Brier score beats prevalence baseline

**Benchmarks:**
- vs `DummyClassifier(strategy="prior")` — predicting class prevalence
- vs `DummyClassifier(strategy="stratified")` — random with class balance

(Cross-model comparison lives in the companion comparison doc per §6 R5.)

**Already implemented:** ROC-AUC, PR-AUC, Brier in `classification_evaluator.py`. New: explicit benchmarking & rubric scoring.

**Output artifact:** `model_card/section_b_discrimination.json`

---

### Section C — Calibration (probability trustworthiness)

**What it tests:** when the model says "0.6", does it actually mean ~60% chance?

**Why it matters:** your deployment uses thresholds (P ≥ 0.6) and prefers higher scores. If 0.6 actually means "30% of the time it works out," every threshold decision is corrupted. This is the single most important section for your use case.

**Metrics:**

| Metric | What it means | How to read |
|---|---|---|
| C1. **ECE (Expected Calibration Error)** | Average gap between predicted P and realised frequency, across probability bins | < 0.05 is good; > 0.10 is poor. For binary, computed on `P(class=1)` |
| C2. **Reliability diagram** | Plot of predicted P vs observed frequency per bin | Should hug the diagonal. Systematic under/over-confidence shows as curve away from diagonal |
| C3. **Brier decomposition** | Brier = reliability + resolution − uncertainty | Reliability component isolates miscalibration from intrinsic noise |
| C4. **Sharpness** | Variance of predicted probabilities | A model that always predicts ~0.08 is perfectly calibrated but useless. Sharpness measures how much it commits |

**Scorecard rubric:**

| Score | ECE | Reliability curve |
|---|---|---|
| 0 (Poor) | > 0.10 | Off-diagonal in critical zone (P > 0.5) |
| 1 (Marginal) | 0.05–0.10 | Off-diagonal in tails only |
| 2 (Good) | 0.02–0.05 | Near-diagonal, small deviations |
| 3 (Strong) | < 0.02 | On-diagonal across all bins |

**Gates:**
- C-gate-1 (blocking): ECE < 0.05 on production-class probabilities
- C-gate-2 (blocking, threshold-specific): for each candidate threshold T ∈ {0.3, 0.4, 0.5, 0.6, 0.7}, predicted P in bin [T, T+0.1] matches realised frequency within ±0.05
- C-gate-3 (warning): sharpness > random baseline (model commits, not just hedges)

**Benchmarks:**
- vs uncalibrated raw model (already trained) — quantifies isotonic calibrator value

**Already implemented:** ECE, calibration_audit in `calibration.py`. New: per-threshold-bin calibration check (which directly answers "is P ≥ 0.6 a meaningful gate?"), reliability diagram plot.

**Output artifact:** `model_card/section_c_calibration.json` + reliability diagram PNG

**Critical reader note:** if Section C fails, do NOT proceed to use the model with thresholds. Either fit a fresh calibrator (you have `IsotonicCalibrator`) or interpret outputs as ordinal scores only.

---

### Section D — Ranker performance (stateful pool)

**What it tests:** given the active SEPA pool with latest probabilities, does sorting by P select better trades?

**Why it matters:** your deployment is rank-based: among candidates above threshold, take the highest. This section answers "would I have been better off picking randomly from the qualifying pool?"

**Pool construction:** see §1.3. Headline (Mode A) is the entry-only ledger from `v_d2_training` filtered to `trend_ok = TRUE`. Supplementary (Mode B) reconstructs the daily active pool from `t3_sepa_features`. All metrics below are computed for both modes; gates apply only to Mode A.

Section D is split into **D-binary** (does the model rank home-runs above non-home-runs?) and **D-magnitude** (does the model rank bigger winners above smaller ones?). Both must pass for the model to satisfy the user's goal.

#### D-binary — ranking against the 30% MFE label

**Metrics:**

| Metric | What it means | How to read |
|---|---|---|
| D1. **Spearman rank IC per day** | Rank correlation of P with binary label, within each day's active pool | Median IC > 0.05 = real signal; > 0.10 = strong; near 0 = no rank info |
| D2. **IC t-stat** | IC mean / (IC std / √N_days) | t-stat > 2 ⇒ rank signal is statistically distinguishable from zero across days |
| D3. **Top-K lift (hit rate)** | (mean binary label of top-K by P) / (mean binary label of full pool), for K ∈ {1, 3, 5, 10} | > 2 = top picks contain 2× more positives than baseline. Tracks deployment behaviour (top-5 etc.) |
| D4. **Decile monotonicity (binary)** | Mean binary label per decile of P. Should rise monotonically | Non-monotone deciles (Section D4 failed on m01_binary, IC -0.120) ⇒ model ranks worse than chance in some bands |
| D5. **Hit rate at threshold** | Fraction of label=1 among P ≥ T, for T ∈ {0.3, 0.5, 0.7} | Plot threshold-vs-hit-rate. Steepness shows whether higher P actually means better picks |

#### D-magnitude — ranking against realised MFE (the user's core goal)

The binary metrics above cap testable upside at "did MFE cross 30%." But the user's goal is "P=0.9 should mean *bigger* MFE than P=0.6." These metrics test that directly using **realised MFE** as the target (not the binarised label).

**Metrics:**

| Metric | What it means | How to read |
|---|---|---|
| D6. **Spearman IC vs realised MFE per day** | Rank correlation of P with continuous MFE, within each day's active pool | Distinguishes "30%-crosser detector" from "magnitude ranker." Median > 0.05 = real magnitude signal |
| D7. **Magnitude lift, top-K** | (mean realised MFE of top-K by P) / (mean realised MFE of full pool), K ∈ {1, 3, 5, 10} | > 2 ⇒ top picks are 2× bigger winners on average, not just 2× more frequent winners |
| D8. **Decile MFE profile** | Mean / median / 90th-pct realised MFE per decile of P | Should rise monotonically. The 90th-pct column is the "did it find the outliers?" diagnostic |
| D9. **Tail recall (super-performer recall)** | Of the realised top-1% MFE trades in eval window, fraction scored in the model's top decile of P | Direct answer to "does the model surface 10-baggers?" Baseline (random ranker) = 10%; > 30% = real tail-finding skill |
| D10. **Tail concentration** | Fraction of total realised MFE captured by the model's top decile / top quintile | Connects ranker quality to economic value. > 30% in top decile = strong concentration |

**Scorecard rubric (D-binary):**

| Score | Median daily IC (binary) | Top-5 lift (hit rate) | Decile monotonicity |
|---|---|---|---|
| 0 (Poor) | < 0 | < 1.2× | Non-monotone, top decile not best |
| 1 (Marginal) | 0–0.03 | 1.2–1.5× | Roughly monotone but noisy |
| 2 (Good) | 0.03–0.08 | 1.5–2.5× | Monotone, top decile clearly best |
| 3 (Strong) | > 0.08 | > 2.5× | Strictly monotone with wide spread |

**Scorecard rubric (D-magnitude):**

| Score | Median daily IC vs MFE | Magnitude lift top-5 | Tail recall (top 1% MFE → top decile P) |
|---|---|---|---|
| 0 (Poor) | < 0 | < 1.2× | ≤ 10% (random) |
| 1 (Marginal) | 0–0.03 | 1.2–1.5× | 10–20% |
| 2 (Good) | 0.03–0.08 | 1.5–2.5× | 20–35% |
| 3 (Strong) | > 0.08 | > 2.5× | > 35% |

**Gates (D-binary):**
- D-gate-1 (blocking): median daily binary IC > 0 with t-stat > 2
- D-gate-2 (blocking): top-5 hit-rate lift > 1.5× pool baseline
- D-gate-3 (blocking): top decile mean binary label > bottom decile mean binary label by ≥ 2×, AND top decile mean ≥ 1.5× pool prevalence (absolute floor — guards against weak gate when bottom decile ≈ 0)

**Gates (D-magnitude):**
- D-gate-4 (blocking): median daily MFE-IC > 0 with t-stat > 2
- D-gate-5 (blocking): magnitude lift top-5 > 1.5× pool baseline
- D-gate-6 (warning): tail recall ≥ 20% (i.e., model surfaces ≥ 2× the random rate of true top-1% trades into its top decile)

**Benchmarks (both halves):**
- vs random ranker (same pool, shuffled P) — bootstrap 1000× to get null distribution for IC, top-K lift, magnitude lift, tail recall
- vs "rank by composite SEPA score" (existing `universe_scorer`) — answers "does the ML add over the rule-based rank?"

**Already implemented:** decile analysis on binary label (in `run_decile_analysis.py`).
**NOT implemented:** per-day IC (both binary and MFE), top-K lift on stateful pool, threshold-vs-hit-rate sweep, **all D-magnitude metrics**, tail-recall computation.

**Output artifact:** `model_card/section_d_ranker.json` + decile (binary + MFE) + threshold curves + tail-recall plot PNG

**Critical reader note:** if D-binary passes but D-magnitude fails, the model is a *gate* (useful for filtering at threshold) but not a *ranker* for selection-by-magnitude. Strategy logic must then pick at threshold and size equally, not size by P.

---

### Section E — Gate performance (threshold operating points)

**What it tests:** at each candidate decision threshold T, what does the model deliver?

**Why it matters:** your deployment is a combined gate ("P ≥ T") + ranker. The gate dimension needs its own evaluation. A 90% precision threshold with 1% recall is useless if it fires twice a year.

**Metrics:**

| Metric | What it means | How to read |
|---|---|---|
| E1. **Precision at threshold T** | Of predictions with P ≥ T, fraction that were label=1 | Should be ≥ prevalence to be useful. Track for T ∈ {0.2, 0.3, …, 0.8} |
| E2. **Recall at threshold T** | Of label=1 rows, fraction captured by P ≥ T | Track trade-off vs precision |
| E3. **Coverage at threshold T** | Fraction of pool above T | If only 0.5% of pool clears T=0.6, threshold is too high to be operational |
| E4. **Trade frequency at threshold T** | Expected trades per month for P ≥ T (using stateful pool) | Links eval to deployment realism. If T=0.6 fires once/year, it doesn't matter how precise it is |
| E5. **Threshold stability** | Variance of precision-at-T across yearly folds | If precision at T=0.5 ranges 30% → 80% across years, threshold is unstable |
| E6. **Magnitude-conditional precision at T** | Of P ≥ T predictions, fraction whose realised MFE exceeds {30%, 50%, 100%}. Three precision curves per threshold | Discriminates "lots of marginal 31% winners" from "real home runs." User's stated goal: high P should produce big winners, not just frequent 30%-crossers |
| E7. **Mean / median realised MFE conditional on P ≥ T** | Among trades passing the gate, what was the average outcome? | A threshold where E[MFE \| P≥T] = 35% is qualitatively different from one where E[MFE \| P≥T] = 80% |

**Scorecard rubric:** evaluated at the *intended deployment threshold* T* (you specify T* = 0.6 currently? or scan):

| Score | Precision @ T* | Coverage @ T* | Stability across folds |
|---|---|---|---|
| 0 (Poor) | < prevalence | < 0.1% (too rare) or > 50% (no selectivity) | Variance > 0.20 |
| 1 (Marginal) | 1–1.5× prevalence | 0.1–0.3% | Variance 0.10–0.20 |
| 2 (Good) | 1.5–3× prevalence | 0.3–2% | Variance 0.05–0.10 |
| 3 (Strong) | > 3× prevalence | 0.5–2% with smooth degradation | Variance < 0.05 |

**Gates:**
- E-gate-1 (blocking): precision at T* > class prevalence × 1.5
- E-gate-2 (blocking): coverage at T* gives ≥ 3 expected trades/month
- E-gate-3 (warning): threshold-precision variance < 0.10 across WF folds

**Benchmarks:**
- vs always-predict-1 (precision = prevalence)
- vs SEPA-score top quintile (rule-based threshold equivalent)

**NOT currently implemented.** This section needs new code.

**Output artifact:** `model_card/section_e_gates.json` + threshold sweep PNG

---

### Section F — Regime & temporal robustness

**What it tests:** does the model work everywhere/everywhen, or only in friendly conditions?

**Why it matters:** a model that's strong in bull markets and broken in bear markets is dangerous — you'll deploy it on the average and lose money on the half it doesn't fit. Regime decomposition has saved more deployments than any other check.

**Regime taxonomy (per §6 R2, verified 2026-05-25):** Section F runs twice, once per taxonomy, both reported:
- **Taxonomy 1: M03 quintiles** — bucket eval dates by `t2_regime_scores.m03_score` (continuous DOUBLE; column also already joined into `v_d2_training`, `v_d3_deployment`, `t3_sepa_features`, `d2_training_cache`) into Q1–Q5 (Q1 = worst, Q5 = best)
- **Taxonomy 2: 5-factor risk model `target_exposure`** — `t2_risk_scores.target_exposure` is naturally discrete (observed values: 0.0, 0.25, 0.5, 0.75, 0.85, 1.0). Use these levels as regime buckets directly — no quintile bucketing needed. (`weighted_z` is continuous and could also be bucketed; `target_exposure` is preferred because it's the *acted-on* signal — it's the actual exposure the risk model recommends, which is the operationally meaningful regime carve-out)

If the two taxonomies disagree about which regimes the model fails in, that disagreement is itself information (one taxonomy captures something the other misses). Don't reconcile — report both.

**Metrics:**

| Metric | What it means | How to read |
|---|---|---|
| F1. **Per-regime AUC, IC, top-5 lift, ECE** | All metrics from B/C/D, computed within each regime | Look for any regime where the model is *worse than random* — that's a deployment carve-out |
| F2. **Year-over-year stability** | Same metrics computed per calendar year | Drift detector. If 2024 AUC = 0.72 and 2025 AUC = 0.54, something broke |
| F3. **Per-sector performance** | Same metrics computed per sector (Energy, Tech, etc.) | Concentration risk. If 80% of the edge comes from Tech, the model is a Tech bet wearing a generalist mask |
| F4. **PSI feature drift** | Population Stability Index of features between train and eval window | PSI > 0.25 ⇒ feature distribution materially shifted; metrics may not generalise forward |

**Scorecard rubric (worst across the two taxonomies):**

| Score | Regime AUC pass rate (min across taxonomies) | YoY stability |
|---|---|---|
| 0 (Poor) | ≤ 2/5 regimes AUC > 0.55 in either taxonomy | Range > 0.15 across years |
| 1 (Marginal) | 3/5 regimes (min) | Range 0.10–0.15 |
| 2 (Good) | 4/5 regimes (min) | Range 0.05–0.10 |
| 3 (Strong) | 5/5 regimes in both taxonomies | Range < 0.05 |

**Gates:**
- F-gate-1 (blocking): ≥ 3/5 regimes have AUC > 0.55 in **both** taxonomies (must satisfy independently for M03 quintiles AND 5-factor buckets)
- F-gate-2 (warning): no individual year worse than random (AUC < 0.50)
- F-gate-3 (warning): no sector has IC < 0 with > 50 samples
- F-gate-4 (blocking): PSI < 0.25 between train window and eval window

**Already implemented:** PSI library. NEW: regime decomposition under both taxonomies, per-year + per-sector breakdown. (Existing regime decomposition tooling needs to be parameterised on the bucketing column.)

**Output artifact:** `model_card/section_f_robustness.json` + regime heatmap PNG

---

### Section G — Edge existence (statistical)

**What it tests:** is the model's apparent skill distinguishable from luck?

**Why it matters:** small samples + many free parameters + many evaluations = false discovery. A model can look great on one metric purely by chance. This section asks "if we shuffled the labels, how often would we see this performance?"

**Metrics:**

| Metric | What it means | How to read |
|---|---|---|
| G1. **Permutation null on AUC, IC, top-5 lift** | Shuffle labels 1000×, recompute metric. Where does observed metric sit in null distribution? | Observed metric at > 95th percentile of null ⇒ real edge. m01_binary failed this at backtest level; need to retest at metric level |
| G2. **Block bootstrap CI on AUC, IC, top-5 lift** | Resample with temporal blocks (size 60d per existing impl), recompute metric. 95% CI | CI excluding zero/random ⇒ edge is robust to temporal sampling. m01_binary Sharpe CI straddled zero — same risk here |
| G3. **Sample size adequacy** | Number of label=1 events in eval window | < 50 positives ⇒ all metrics are noisy. < 100 ⇒ marginal. > 500 ⇒ statistically meaningful |

**Scorecard rubric:**

| Score | Permutation percentile | Bootstrap CI |
|---|---|---|
| 0 (Poor) | < 90th | CI includes baseline |
| 1 (Marginal) | 90–95th | CI lower bound within 10% of baseline |
| 2 (Good) | 95–99th | CI lower bound clearly above baseline |
| 3 (Strong) | > 99th | CI tight and well above baseline |

**Gates:**
- G-gate-1 (blocking): permutation null percentile > 95th for at least 2 of {AUC, IC, top-5 lift}
- G-gate-2 (blocking): bootstrap 95% CI excludes the random baseline for at least 1 of {AUC, IC, top-5 lift}
- G-gate-3 (warning): N positives ≥ 100 in eval window

**Already implemented:** permutation null and block bootstrap exist but at *backtest* level. NEW: same tests at *classification metric* level.

**Output artifact:** `model_card/section_g_edge.json`

---

## 4. Final verdict aggregation

After all seven sections run, produce a single page. Section D is reported as two sub-scores (binary / magnitude); they aggregate as independent dimensions, not averaged.

```
MODEL CARD: m01_binary/v1
=========================
Section A (Data integrity)         [GATE-ONLY]  PASS
Section B (Discrimination)         Score 2/3    GATES 2/3 pass   AUC=0.62  PR-AUC=0.14 (1.75× prev)
Section C (Calibration)            Score 1/3    GATES 1/3 pass   ECE=0.082 — UNRELIABLE @ thresholds
Section D-binary (Ranker, hit)     Score 0/3    GATES 0/3 pass   Median IC=-0.04  Top-5 hit lift=0.9×
Section D-magnitude (Ranker, MFE)  Score 0/3    GATES 0/3 pass   MFE-IC=-0.02  Tail recall=8% (random)
Section E (Gates)                  Score 1/3    GATES 1/3 pass   Precision @ 0.6 = 1.3× prev; E[MFE|P≥0.6]=32%
Section F (Robustness)             Score 2/3    GATES 3/4 pass   4/5 regimes pass, 2024 weak
Section G (Edge existence)         Score 0/3    GATES 0/3 pass   AUC permutation pct = 42nd

AGGREGATE SCORE: 6/21  (BAND: WEAK)
DEPLOYMENT VERDICT: BLOCKED (Section D-binary + D-magnitude + G blocking gates failed)
USE-CASE VERDICT:
  - As selection ranker (size-by-P):  REJECT  (D-magnitude fail — P is not ordinal in MFE)
  - As hit-rate ranker (equal-size):  REJECT  (D-binary fail)
  - As gate (P ≥ T filter):           MARGINAL  (E1 pass but C fail — threshold semantics unreliable)
  - As probability (sizing input):    REJECT  (C fail)

vs BASELINE (DummyClassifier 'prior'):
  AUC +0.12, PR-AUC +1.75×, Brier −0.02
vs BASELINE (SEPA composite-score ranker):
  binary-IC +0.05, MFE-IC +0.02, tail recall +4pp
```

(Inter-model comparison — e.g., vs prior `m01_prototype/v2` — lives in the companion comparison doc, not here. See §6 R5.)

The aggregate is **not** a single number used to rank models — it's a structured readout where weak sections are unambiguous. Sections B–G score 0–3 each (21 points total with D split). Score bands:

| Aggregate / 21 | Band |
|---|---|
| 0–6 | Broken |
| 7–12 | Weak |
| 13–17 | Acceptable |
| 18–21 | Strong |

**Use-case verdict matrix** — different deployments demand different sections pass:

| Use case | Required passing sections |
|---|---|
| Selection ranker (pick top-K, size by P) | A, D-binary, D-magnitude, G |
| Hit-rate ranker (pick top-K, size equally) | A, D-binary, G |
| Threshold gate (filter P ≥ T) | A, C, E, G |
| Probability for sizing/Kelly | A, B, C, G |
| Composite (gate + rank-by-P) | A, C, D-binary, D-magnitude, E, G |

Deployment as **composite** (the current m01 production mode) requires the union of those gates plus F-gate-1 (regime robustness). The user's stated goal ("high scores for super-performers, high precision") maps to the composite row.

---

## 5. What's needed to ship

The framework is implementation-ready when the four prerequisites below are met. After that, the work is sequenced into four phases. Each phase ends with something runnable; the user can stop at any phase and have a working subset.

### 5.0 Prerequisites

All design questions resolved — see §6. Recap of what was decided:
- Threshold: scan {0.3, 0.4, 0.5, 0.6, 0.7}, no single T*
- Regime taxonomy: M03 quintiles + 5-factor risk model, side-by-side
- Active pool: `c1_ok AND c2_ok AND c6_ok` on D AND ticker scored at least once on or before D
- Scope: single-model standalone; comparison work goes to a separate companion doc
- 4-class handling: project to binary via home-run class probability only

### 5.1 Data dependencies — verified 2026-05-25

All blockers resolved. `scripts/verify_model_card_prereqs.py` is the canonical re-verification script.

| Dependency | Status | Notes |
|---|---|---|
| `mfe_pct` continuous column on `v_d2_training` and `d2_training_cache` | ✅ **100% populated**, 38,122 rows | Mean=14.3, median=7.25, max=2232.84, p99=101.57. D-magnitude metrics unblocked |
| Binary label derivable as `mfe_pct > 30` (registry: `mfe_binary_homerun_v1`) | ✅ trivially derivable | No separate column needed; compute on the fly |
| 4-class label derivable from `mfe_pct` (registry: `mfe_4class_v1`) | ✅ trivially derivable from bins `[2, 10, 30]` | Projected-binary card uses `mfe_pct > 30` regardless of model head |
| `v_d3_deployment` SEPA filter matches `d2_training_cache` | ✅ verified — 1976 rows match exactly | Window: 2025-09-12 → 2026-05-22 (~8 months). Wider eval windows must apply SEPA filter to `d2_training_cache` directly |
| `trend_ok` (single boolean, not C1/C2/C6 triple) | ✅ exists on `t3_sepa_features` AND `v_d2_training` | Replaces all earlier C1+C2+C6 logic. Pool query confirmed on 2026-05-22: 2401 rows total, 342 with trend_ok=TRUE |
| `t2_regime_scores.m03_score` (Taxonomy 1) | ✅ continuous DOUBLE; joined into `v_d2_training`, `v_d3_deployment`, `t3_sepa_features`, `d2_training_cache` | Bucket into quintiles in §F |
| `t2_risk_scores.target_exposure` (Taxonomy 2) | ✅ naturally discrete: {0.0, 0.25, 0.5, 0.75, 0.85, 1.0} | No bucketing needed. Stored only on `t2_risk_scores` (not joined into d2/d3); join on `date` |
| Trained models on disk | ✅ `m01_binary/v1`, `m01_prototype_2003_2026/v2/model.json` both present | |
| BAD_TICKERS exclusion | ✅ `LIF`/`CUE` not in `v_d3_deployment` | For wider eval windows over `d2_training_cache`, apply filter explicitly |
| `leakage_guard.py` covers outcome columns | ⚠️ Need to confirm | `v_d2_training` has `mfe_pct`, `mae_pct`, `return_pct`, `exit_date`, `holding_days`, `sl_*` on the same row as features. These MUST be in the leakage_guard exclude list. Verify before Phase 2 |

**No data-side blockers remain.** Phase 1 is ready to start.

### 5.2 Phase 1 — Mechanical card (1 day, fully reusable existing code)

Produces a working card for Sections A, B, C, F using existing libraries. No new metrics, no new stateful pool. The point of Phase 1 is to validate the orchestrator and reporting skeleton before adding the harder sections.

- `src/evaluation/model_card.py` — orchestrator class `ModelCardBuilder`
  - Accepts: `model_id`, `eval_universe_df`, `T*` (or scan list), `regime_column`, `prior_model_id` (optional)
  - Returns: dict of section results, serialisable to JSON
- `src/evaluation/sections/section_a_integrity.py` — wraps `leakage_guard.py`, adds A3 reconciliation query, A5 BAD_TICKERS check
- `src/evaluation/sections/section_b_discrimination.py` — wraps `classification_evaluator.py`, adds DummyClassifier benchmarks + rubric scoring
- `src/evaluation/sections/section_c_calibration.py` — wraps `calibrator.py` + `calibration_audit`, adds per-threshold-bin check
- `src/evaluation/sections/section_f_robustness.py` — wraps existing regime decomposition + PSI library, adds per-year + per-sector breakdown
- `scripts/build_model_card.py` — CLI: `python scripts/build_model_card.py --model m01_binary/v1 --output model_cards/m01_binary_v1.html`
- HTML renderer reusing `html_report.py` patterns
- Unit test on a known-good model snapshot to lock the output schema

**Exit criterion for Phase 1:** running the CLI on `m01_binary/v1` produces a partial card with Sections A/B/C/F populated and gates evaluated. Sections D/E/G show "NOT YET IMPLEMENTED" placeholders.

### 5.3 Phase 2 — Stateful pool + ranker (1.5 days, the hard part)

- `src/evaluation/sections/_stateful_pool.py` — `build_stateful_pool(start_date, end_date) -> pd.DataFrame`
  - Per-date: enumerate tickers where `c1_ok AND c2_ok AND c6_ok` on D (P3 confirmed)
  - Attach latest P on or before D using features as of D−1 (no lookahead)
  - Join binary label + `realised_mfe_pct`
  - Cache to parquet keyed by `(model_id, start_date, end_date)` — pool construction is expensive, must be reused across sections
- `src/evaluation/sections/section_d_ranker.py`
  - D-binary: per-day Spearman IC vs binary label, top-K hit-rate lift, decile monotonicity (binary), hit rate at threshold
  - D-magnitude: per-day Spearman IC vs `realised_mfe_pct`, magnitude lift top-K, decile MFE profile (mean/median/90th-pct), tail recall (top-1% MFE → top decile P), tail concentration
  - Rubric scoring for both halves independently
- `src/evaluation/sections/section_e_gates.py`
  - Threshold sweep (E1–E5) using stateful pool
  - E6 magnitude-conditional precision at MFE thresholds {30%, 50%, 100%}
  - E7 conditional mean/median MFE given P ≥ T
  - Trade frequency / coverage analysis
- Test fixtures: three synthetic models (random / perfect / slightly-better-than-random) against a synthetic pool to confirm metrics match closed-form expectations

**Exit criterion for Phase 2:** card runs end-to-end except Section G; D-magnitude metrics produce sensible values on the perfect-model fixture (IC ≈ 1.0, tail recall ≈ 100%).

### 5.4 Phase 3 — Edge existence + benchmarks + verdict (1 day)

- `src/evaluation/sections/section_g_edge.py`
  - Permutation null on classification metrics (AUC, IC, top-5 lift, tail recall) — 1000× shuffle of `realised_mfe_pct` AND binary label
  - Block bootstrap (60-day blocks per existing impl) on the same metrics
  - Sample-size adequacy check
- Benchmark scaffolding (standalone baselines only — per R5, inter-model comparison is out of scope for this doc):
  - `DummyClassifier(strategy='prior')` and `'stratified'`
  - SEPA composite-score ranker (rule-based baseline from `universe_scorer`)
- Verdict aggregator:
  - Section scores → aggregate band
  - Use-case verdict matrix (selection / hit-rate / gate / probability / composite)
  - Final HTML page with the §4 readout block
- End-to-end test: run on `m01_binary/v1` and separately on `m01_prototype_2003_2026/v2` (projected to binary). Eyeball each card against the existing deep-rigor outputs (Sharpe contradiction example) and confirm the card explains why the strategy-level signal and model-level signal disagreed.

**Exit criterion for Phase 3:** standalone card produced for each model by a single CLI call; verdict block populated; use-case matrix correctly identifies which deployment modes each model qualifies for.

### 5.5 Phase 4 — Polish + integration (0.5 day, optional but recommended)

- Wire model card output into `models` registry table (`models.model_card_path` column)
- Add to `daily_pipeline_orchestrator` as a manual gate before model promotion (not automatic — human review of card precedes any `is_production=true` flip)
- Document threshold T* selection process in `docs/manual_for_me.md` if a single T* is chosen post-Phase-3 evidence
- Decision log entry (`docs/decision_log/`) capturing why the card supersedes the previous ad-hoc pass/fail process

**Exit criterion for Phase 4:** the card is the documented gate for model promotion; no model goes to `is_production=true` without a passing card review.

### 5.6 Total cost & sequencing

| Phase | Duration | Blocking? | Deliverable |
|---|---|---|---|
| Prereqs | 30 min talk | Yes | P1–P4 decided, data verified |
| Phase 1 | 1 day | Independent | Partial card (A/B/C/F) |
| Phase 2 | 1.5 days | Needs Phase 1 orchestrator | Full card minus G |
| Phase 3 | 1 day | Needs Phase 2 | Card with verdict |
| Phase 4 | 0.5 day | Optional | Card wired into promotion gate |

**Total: ~4 days** (3 days without Phase 4). Phase 1 alone is independently useful — it gives a structured A/B/C/F readout immediately and tells you whether the current models have data-integrity or calibration problems before sinking effort into ranker analysis.

### 5.7 Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| `realised_mfe_pct` not materialised on label rows | Medium | §5.1 verification step before Phase 2; if missing, add to label registry first (~2 hours) |
| Stateful pool reconstruction slower than expected (per-date C1/C2/C6 replay) | Medium | Cache pool parquet by `(model_id, window)`; pre-compute once per eval window |
| Rubric thresholds (e.g., AUC > 0.60 = Good) don't match domain reality | Medium | Phase 3 produces cards on two existing models — recalibrate thresholds against those outputs before locking |
| Card becomes "another gate that's argued away" — same fate as deep-rigor | High if Phase 4 skipped | Phase 4 wires it into promotion flow with explicit human sign-off recorded in decision log |
| Tail-recall metric is noisy (top 1% of MFE = few hundred rows) | Low | Already addressed by G-gate-3 (N positives ≥ 100) and bootstrap CI |

---

## 6. Resolved design decisions

These were open questions in earlier drafts. Resolved on 2026-05-25.

| # | Question | Resolution | Implication |
|---|---|---|---|
| R1 | Threshold T* for Section E | **Scan {0.3, 0.4, 0.5, 0.6, 0.7}** — no single fixed T* | Section E reports a 5×N matrix per metric. Rubric scoring picks the best T per fold and reports stability across thresholds as a separate sub-metric |
| R2 | Regime taxonomy for Section F | **Both M03 quintiles AND 5-factor risk model output, side-by-side** | Section F runs twice. If a regime-dependence shows up in one taxonomy but not the other, that itself is information |
| R3 | Production active pool definition (§D) | **`c1_ok AND c2_ok AND c6_ok` on date D AND ticker has been scored at least once on or before D** | Pool reconstruction queries `t3_sepa_features` per date with the C1/C2/C6 filter and joins to the most recent scored row per ticker. No staleness cap on the score — latest P is used however old |
| R4 | Calibration bin tolerance (§C-gate-2) | **±0.05 tolerance for now** | Revisit after first card if too lenient. Tighter (±0.02) would fail usable-in-practice models per current intuition |
| R5 | Scope of this document | **Single-model standalone evaluation only.** Inter-model comparison (m01_binary vs m01_prototype, native 4-class vs projected binary) moves to a separate companion doc | This doc evaluates one model at a time. Comparison framework (and the question of whether m01_prototype deserves a native 4-class card) is out of scope here |
| R6 | 4-class vs binary projection | **Projected binary only** for 4-class models — score taken from the home-run class (`P(class=3)` for m01_prototype). Native 4-class metrics deferred to the comparison doc | Simplifies the card. Loses some information (other-class probabilities ignored) but matches how the user actually consumes the model |

### Companion doc placeholder

`docs/proposals/model_comparison_framework_<date>.md` — to be drafted later. Scope: side-by-side cards, delta-vs-prior, native multi-class evaluation, model-selection criteria. Out of scope for this document.

---

## 7. What you do next

Phase ordering and exit criteria are in §5. Open items before coding begins:

1. **§5.1 data verification** — confirm `realised_mfe_pct` (or equivalent continuous MFE column) exists on the rows that carry the binary home-run label. The D-magnitude metrics are dead without it. 15-minute query.
2. **Rubric calibration** — the thresholds in §B–§G rubrics (e.g., "AUC > 0.60 = Good") are informed guesses. Phase 1 produces a real card on `m01_binary/v1`; if the verdict feels mis-aligned with intuition, recalibrate thresholds against that output before Phase 2.
3. **Gate severity** — every gate is currently labeled blocking or warning. Worth a pass after Phase 1: any warning that you'd actually never deploy past should be promoted to blocking, and vice versa.
4. **Sign-off** — once §5.1 is verified and §5.0 prerequisites are resolved (already done — see §6), Phase 1 is unblocked.

The aggregate score (/21) is intentionally crude — it's a summary readout, not a model-selection oracle. The use-case verdict matrix in §4 is what actually drives deployment decisions.
