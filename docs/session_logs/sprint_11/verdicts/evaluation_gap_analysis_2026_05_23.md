# Evaluation Gap Analysis — Academic Bar vs Current Capability

> **Created:** 2026-05-23
> **Owner:** Hang
> **Status:** Draft for review.
> **Companion docs:**
>   • [whitepaper](whitepaper_path_forward_2026_05_23.md) §5 sets the
>     academic-grade target.
>   • [`docs/analytics_pipeline_design.md`](../analytics_pipeline_design.md) sets
>     what the notebook-side EDA library already covers.
>   • [`docs/evaluation_framework_implementation.md`](../evaluation_framework_implementation.md)
>     documents the existing `src/evaluation/` library.

---

## 0. Executive summary

We are **further along than the whitepaper §5 narrative implies, but not as
far as the existing `src/evaluation/` library makes it look.** The discrepancy:

- The `src/evaluation/` library is genuinely comprehensive for **point-in-time
  classification evaluation** (confusion matrix, SHAP, ROC/PR, calibration,
  leakage). This is the *per-model snapshot* tier.
- The notebooks contain rich **EDA-tier** content (IC, MI, decile, rolling IC,
  trajectory, regime gating). Per `docs/analytics_pipeline_design.md`, these
  are not yet refactored into the library.
- The whitepaper §5 academic bar is largely the **multi-fold / portfolio /
  significance** tier — walk-forward stability, regime-conditional metrics,
  block-bootstrap, permutation null, paper-trade ground truth. **This tier is
  almost entirely absent from automated code**, even though some of it has
  been done ad-hoc in notebooks.

In plain terms: **we evaluate one model well, we explore data well in
notebooks, we do not yet evaluate a model's robustness across time, regime,
and statistical noise as a reusable pipeline.** That is the gap.

---

## 1. Method

For each of the 8 evaluation pillars in whitepaper §5 (plus three from the
analytics_pipeline_design doc that the whitepaper folded in implicitly), we
record:

| Field | Meaning |
|---|---|
| **Asset** | What we have today (module path / file / notebook reference) |
| **Coverage** | one-shot per-model run, notebook only, partial library, or fully integrated |
| **Reusability** | can be called from a script without copy-paste? |
| **Gap** | what's missing to hit the academic bar |
| **Effort to close** | days |
| **Priority** | P0 (gate any model promotion), P1 (next sprint), P2 (eventually) |

Coverage scale:
- 🟢 **Integrated** — runs automatically in pipeline / training script; reusable library
- 🟡 **Library, manual** — exists in `src/evaluation/` but not auto-invoked
- 🟠 **Notebook only** — ad-hoc in `notebooks/`, not refactored
- 🔴 **Missing** — has never been done in this repo

---

## 2. Pillar-by-pillar gap matrix

### 2.1 Per-class classification metrics

**Whitepaper bar:** confusion matrix, per-class precision/recall/F1, weighted /
macro / accuracy. Required for any model promotion.

| Asset | Coverage | Reuse |
|---|---|---|
| `src/evaluation/classification_evaluator.py` (`ClassificationEvaluator.evaluate`) | 🟢 | Yes — auto-invoked by `scripts/train_mfe_classifier.py` |
| Plots: `confusion_matrix.png`, `confusion_matrix_normalized.png`, `class_distribution.png` | 🟢 | Auto-generated per model run |

**Gap.** None — this pillar is mature. *(Acceptance: ✅ ship.)*

---

### 2.2 ROC / PR curves + AUC

**Whitepaper bar:** one-vs-rest ROC and PR curves with AUC per class.
Threshold-tuning support.

| Asset | Coverage | Reuse |
|---|---|---|
| `classification_evaluator.py` produces ROC/PR via `EvaluationPlotter` | 🟢 | Yes |
| `roc_curves.png`, `pr_curves.png` saved per run | 🟢 | Yes |
| Threshold selection from PR curve | 🔴 | No — done manually in notebooks |

**Gap.** Threshold optimization. Currently the per-class threshold = 0.5 by
default. For the M01_v2_binary work (whitepaper §2.3.1), we need a `find_optimal_threshold(precision_min=0.6)` helper that returns the threshold + the operating point on the PR curve.

**Effort:** 0.5 day. **Priority:** P1 (next modelling sprint needs it).

---

### 2.3 Calibration audit

**Whitepaper bar (§5.3):** reliability diagram per class (10 bins), Brier score,
Expected Calibration Error (ECE). Pass = within ±5% of diagonal.

| Asset | Coverage | Reuse |
|---|---|---|
| `EvaluationPlotter.plot_calibration_curves` | 🟢 | Yes |
| `calibration_curves.png` per model run | 🟢 | Yes |
| Brier score in `results.json` | 🟢 | Yes |
| **ECE computation** | 🔴 | No — never computed |
| **Pass/fail gate on calibration** | 🔴 | No — visual only |

**Gap.** ECE and an automatic pass/fail gate are both missing. ECE is one
function (~10 lines: bin the predictions, compute |mean_pred − mean_obs| per
bin, weight by bin population). The gate would refuse promotion if ECE > 0.05
on the production class.

**Effort:** 0.5 day. **Priority:** P0 (the backtest uses `predict_proba ×
midpoints` as if calibrated — if it isn't, the entry scoring is wrong).

---

### 2.4 SHAP feature importance + directionality

**Whitepaper bar (§5.5):** SHAP global + per-class top-N + the
SHAP/Gain/Permutation triangulation (currently SHAP and Gain disagree).

| Asset | Coverage | Reuse |
|---|---|---|
| `ClassificationEvaluator` calls SHAP `TreeExplainer` (default sample 1000) | 🟢 | Yes |
| Per-class SHAP top-5 + bar + beeswarm plots | 🟢 | Yes |
| XGBoost gain importance + top-20 chart | 🟢 | Yes |
| **Permutation importance** | 🔴 | No |
| **Ablation backtest** (drop feature group → re-backtest) | 🔴 | No |
| **Resolution of SHAP vs Gain disagreement** | 🟠 | Open question in `development_roadmap.md` §4 |

**Gap.** The third opinion (permutation) and the ablation-backtest tiebreaker
are both missing. Permutation is ~30 lines using sklearn's
`permutation_importance`. The ablation backtest is a small wrapper around
`run_backtest.py` that drops features at training time.

**Effort:** 1.5 days (permutation: 0.5d, ablation harness: 1d).
**Priority:** P1 — needed to resolve the open SHAP-vs-Gain disagreement before
the next training sprint.

---

### 2.5 Walk-forward cross-validation

**Whitepaper bar (§5.1):** anchored walk-forward, 1-year increments; per-fold
classification metrics + per-fold *backtest* metrics; mean / std / worst-fold
reporting. Currently the strongest claim from §5.

| Asset | Coverage | Reuse |
|---|---|---|
| Conceptual scaffolding | 🟠 | Sketched in `notebooks/model_proto.ipynb` (per analytics_pipeline_design §B) |
| Notebook walk-forward XGBoost loop | 🟠 | Hard-coded in the notebook, not library |
| **Library function (anchored WF, n folds, returns per-fold results)** | 🔴 | No |
| **Per-fold backtest** (train fold n → score & backtest fold n+1) | 🔴 | No |
| **Worst-fold reporting / acceptance gate** | 🔴 | No |
| Walk-forward stability plot (per-class F1 across folds) | 🟠 | In notebook (analytics_pipeline_design §B) |
| Aggregate confusion matrix across OOS folds | 🟠 | In notebook |

**Gap.** This is the single biggest gap. The whitepaper makes walk-forward the
mandatory pre-promotion test (§5.1 acceptance: mean Sharpe > 0.5, worst-fold
Sharpe > 0, worst-fold max DD < 35%, mean top-3 Home Run lift > 5×).
**Without a library function and a per-fold backtest harness, this is
prohibitively expensive to run, and so it doesn't get run.**

**Effort:** 5–7 days. (Revised up from the original 3–4d estimate: the per-fold
backtest integration will surface leakage issues in `run_backtest.py` that the
m01_rank case studies — see §7 — already taught us to expect. Cleanup forced
by that integration is part of the cost, not separate.)
- Day 1: `src/evaluation/walk_forward.py` — `anchored_walk_forward(start, end,
  step='YS', train_fn, score_fn)` returns per-fold `{train_window, score_window,
  model, predictions}`.
- Day 2: integration with `train_mfe_classifier.py` so the WF call trains all
  folds and serializes models.
- Day 3–4: integration with `run_backtest.py` per-fold + aggregator producing
  the per-fold metric table + the worst-fold acceptance check. Includes
  whatever leakage / boundary-condition fixes the integration exposes.
- Day 5: stability plots (F1, IC, Sharpe over folds) and aggregate confusion
  matrix.
- Day 6–7: buffer for leakage findings and per-fold backtest debugging.

**Priority:** P0 — this is the gate for any model promotion in the new
methodology.

---

### 2.6 Regime-conditional metrics

**Whitepaper bar (§5.2):** decomposition of every metric by M03 regime category
(Strong Bull / Bull / Neutral / Bear / Strong Bear) at the time of entry. Both
classification metrics (per-regime top-K lift, calibration) and backtest
metrics (per-regime Sharpe, win rate, MFE, MAE).

| Asset | Coverage | Reuse |
|---|---|---|
| Backtest report shows "Performance by Entry Regime" table (see `backtest_report_20260210_012608.md`) | 🟢 | Auto-generated by `run_backtest.py` |
| EDA decile analysis with regime split (`notebooks/scores_eda.ipynb`) | 🟠 | Notebook only |
| **Library function: `metrics_by_regime(df, metric_fn)`** | 🔴 | No |
| **Regime-conditional calibration** | 🔴 | No |
| **Regime-conditional top-K lift / IC** | 🔴 | No (although IC-by-regime is in the EDA notebook) |
| **5-Factor regime decomposition (vs M03)** | 🟠 | Manual comparison in EDA notebook |

**Gap.** Backtest-side reporting exists; classification-side and 5F-side don't.
The 5F vs M03 disagreement-zone analysis in `development_roadmap.md` §9 is the
template — but it's done by hand, not auto-generated.

**Effort:** 2 days. A single `regime_decomposition(df, regime_col, metric_fns)`
helper plus integration into the classification evaluator and the backtest
report. **Priority:** P1.

---

### 2.7 Statistical significance of returns

**Whitepaper bar (§5.6):** block bootstrap of trade outcomes (block ≥ 60d),
permutation null backtest (shuffle entry signal, keep dates). Report median +
5%/95% CI; report what percentile the real backtest lies in vs the null.

| Asset | Coverage | Reuse |
|---|---|---|
| Bootstrap CI on backtest metrics | 🔴 | No |
| Permutation null backtest | 🔴 | No |
| Newey-West–adjusted IC | 🟠 | Mentioned in `development_roadmap.md` §6a; implementation status unclear |
| **Library function: `bootstrap_metric(trades_df, metric_fn, block=60, n=10000)`** | 🔴 | No |
| **`permutation_null_backtest(model, n=1000)`** | 🔴 | No |

**Gap.** Complete. Two notebook days of work that have never been done.

**Effort:** 2 days.
- Day 1: Block bootstrap on trades.parquet — simple resampling with circular
  block bootstrap (`numpy` only).
- Day 2: Permutation null — wraps `run_backtest.py` with a shuffle-entry-signal
  hook. Caveat: 1000 perm runs × ~30s each = 8 hours; need to make a fast path
  (skip BackTrader; reproduce the relevant entry / exit logic in NumPy) for
  this to be tractable. May land at 100 permutations as a compromise.

**Priority:** P1 — most useful for **the +201% number**. Currently we have no
estimate of how far that is from chance.

---

### 2.8 Feature drift (PSI / KL)

**Whitepaper bar (§5.4):** PSI per top-20-SHAP feature, quarter-over-quarter.
PSI > 0.25 = drift alert. Surface on Pipeline Health dashboard.

| Asset | Coverage | Reuse |
|---|---|---|
| Feature null-rate audit | 🟢 | `data_quality.NullReport` in pre-training pipeline |
| Feature distribution comparison | 🟠 | Ad-hoc in EDA notebook |
| **PSI helper** | 🔴 | No |
| **Automated drift report** | 🔴 | No |
| **Drift surfaced in dashboard** | 🔴 | No (Pipeline Health page from dashboard plan) |

**Gap.** Complete. PSI is one function (`compute_psi(reference, current, bins=10)`).
The reference distribution should be locked at training time (saved alongside
the model artifact). The pipeline computes current-quarter PSI and writes to a
log file the dashboard reads.

**Effort:** 1.5 days (PSI helper + reference snapshotting + dashboard surface).
**Priority:** P2 — useful but not blocking. Becomes critical *after* a model is
deployed for 6+ months.

---

### 2.9 Forward paper-trade tracking

**Whitepaper bar (§5.7):** real-time prediction log → ground-truth outcome,
compared to backtest predictions for the same period.

| Asset | Coverage | Reuse |
|---|---|---|
| Daily scoring run via `v_d3_deployment` + `dashboard.py` | 🟢 | Yes — every day generates fresh predictions |
| **Predictions logged with manifest** (date, model_version, ticker, prob_elite, decision-status) | 🔴 | No — predictions are computed at view-time and not persisted |
| **Manual "taken/skipped" toggle** on dashboard | 🔴 | No |
| **Realized outcome backfill** (was it a Home Run? when did it exit?) | 🟠 | Available retroactively via `screener_watchlist`, but not joined to the prediction snapshot |

**Gap.** The infrastructure for *logging* predictions and *joining* them to
realized outcomes does not exist. This is small but currently invisible —
every day's signal is computed and thrown away.

**Effort:** 2 days.
- Day 1: New `daily_predictions` table — one row per (date, ticker, model_version)
  with `prob_elite`, `calibrated_score`, `decision_taken` (NULL by default).
  Written at the end of Phase 8.
- Day 2: Manual "taken/skipped" toggle on the dashboard's Today page;
  retroactive outcome join via `screener_watchlist`.

**Priority:** P0, unconditional. The cost of logging is ~0; the cost of *not*
having a year of historical real-time predictions when we eventually want to
compare backtest-vs-live is irreversible. Start logging now even if no manual
"taken/skipped" toggle exists yet — that toggle is back-fillable, the
prediction history is not.

---

### 2.10 Feature predictiveness EDA (pre-modelling)

*From `docs/analytics_pipeline_design.md` §A — these are upstream of the
whitepaper but feed it.*

**Notebook bar:** Spearman IC per feature vs target; Mutual Information;
multicollinearity matrix; feature redundancy clustering.

| Asset | Coverage | Reuse |
|---|---|---|
| `feature_signal.compute_ic` (model_proto cell 42 ported exactly) | 🟢 | Library function |
| `feature_signal.compute_mutual_information` | 🟢 | Library |
| `feature_signal.compute_redundancy` (Spearman corr) | 🟢 | Library |
| `pretrain_report.run_pretrain_audit` → HTML report | 🟢 | Sequencer wires all three |
| `html_report.build_html_report` (Plotly, offline, self-contained) | 🟢 | Yes |
| **Auto-invoked by training script** | 🟡 | Has to be triggered manually |

**Gap.** Wiring. The pretrain audit exists as a library but the training script
doesn't yet call it. Add one step to `train_mfe_classifier.py` to
`run_pretrain_audit` before training, save the HTML alongside the model.

**Effort:** 0.5 day. **Priority:** P1 — each training run should produce its
own pre-training report.

---

### 2.11 Rolling IC / score-trajectory analytics

*From `docs/analytics_pipeline_design.md` §C and §6/§7 of the development
roadmap. Already partially in EDA notebooks.*

| Asset | Coverage | Reuse |
|---|---|---|
| Rolling IC across time | 🟠 | EDA notebook only (`scores_eda.ipynb`) |
| Decile analysis with monotonicity check | 🟠 | EDA notebook only |
| Score trajectory T-30 → T+30 around breakout | 🟠 | EDA notebook only |
| Excess-return demeaning (strip market beta) | 🟠 | Pending — `development_roadmap.md` §6a explicit TODO |
| **Library functions for all three** | 🔴 | No |
| **Auto-invoked at scoring time** | 🔴 | No |

**Gap.** All three live in notebooks. The score-trajectory analysis is the
direct foundation for the M01-Hold (degradation classifier) work — refactor it
into `src/analytics/` (new module) before that sprint.

**Effort:** 2 days.
- Day 1: `src/analytics/rolling_ic.py`, `decile_analysis.py`,
  `score_trajectory.py`.
- Day 2: integration into the post-training evaluation step + an `analytics/`
  HTML page reusing `html_report.build_html_report`.

**Priority:** P1 — direct enabler of M01-Hold (whitepaper §2.3.3).

---

### 2.12 Label-quality / target-definition audit

*Not in the original whitepaper §5 list, but the m01_rank case studies
(see [`docs/session_logs/2026-05-22_backtest-cases.md`](../session_logs/2026-05-22_backtest-cases.md))
made it clear that **label leakage dominates metric drift**. A model evaluated
against a leaky label is worse than no evaluation at all — every other pillar
in this document is only as trustworthy as the labels feeding it.*

**Bar:** for every training label used by a promoted model, prove that
(a) the label is computable using only information available at training-time
end-of-day, and (b) the deployment-time scoring path constructs the *identical*
feature vector that the training path saw for the same `(ticker, date)`.

| Asset | Coverage | Reuse |
|---|---|---|
| `leakage_guard.py` (`LeakageGuard.check`) for feature-side time leakage | 🟢 | Yes — auto-invoked by training script |
| **Label-side leakage audit** (does the MFE/HR label use future bars beyond the labelling window?) | 🟠 | Done manually for m01_prototype; never codified |
| **Training-vs-deployment feature parity check** (same ticker × same date → identical feature vector under both code paths) | 🔴 | No — m01_rank case 2 surfaced a categorical-encoding parity bug that took days to find |
| **Label definition registry** (what the label means, the lookahead horizon, the assumed exit logic) | 🔴 | No |
| **Label-stability check** across re-runs of the label-generation script | 🔴 | No |

**Gap.** Significant and high-risk. The whole multi-fold / bootstrap /
permutation apparatus in §2.5–§2.7 is mathematically sound but operationally
worthless if the labels it's evaluating against were computed with a
look-ahead bias or a feature-parity bug. The m01_rank `28×` figure that was
ultimately invalidated is the case study — the *metrics* weren't lying; the
*labels and features* were.

**Effort:** 2 days.
- Day 1: `src/evaluation/label_audit.py` — `audit_label(label_df, max_horizon_d,
  reference_price_data)` proves the label uses only data within the declared
  window. Plus a `label_registry` JSON that every model artifact must carry
  (label name, horizon, exit rule, source query).
- Day 2: `feature_parity_check(train_path, deploy_path, sample_n=100)` — pick
  100 random `(ticker, date)` pairs that exist in both the training cache and
  `v_d3_deployment`, assert byte-identical feature vectors.

**Priority:** **P0**. This is upstream of every other P0 — walk-forward of a
leaky label is theatre.

---

## 3. Roll-up matrix

| Pillar | Have | Library? | Auto-run? | Acceptance gate? | Priority |
|---|---|---|---|---|---|
| Per-class metrics (CM, P/R/F1) | ✅ | 🟢 | 🟢 | partial (manual) | done |
| ROC/PR + threshold | ✅ | 🟢 | 🟢 (plot) / 🔴 (threshold) | 🔴 | P1 |
| Calibration (Brier, ECE) | partial | 🟢 (Brier) / 🔴 (ECE) | 🟢 (Brier) | 🔴 | P0 |
| SHAP / Gain | ✅ | 🟢 | 🟢 | partial | done |
| Permutation importance | 🔴 | 🔴 | 🔴 | 🔴 | P1 |
| Ablation backtest | 🔴 | 🔴 | 🔴 | 🔴 | P1 |
| Walk-forward CV (classification + backtest, one effort) | 🟠 | 🔴 | 🔴 | 🔴 | **P0** |
| Regime-conditional (backtest) | ✅ | 🟢 | 🟢 (via report.md) | 🔴 | done (partial) |
| Regime-conditional (classification) | 🟠 | 🔴 | 🔴 | 🔴 | **P0** (gates regime-routing sprint) |
| Label-quality / target-definition audit | 🟠 (manual) | 🟢 (feature side) / 🔴 (label side) | partial | 🔴 | **P0** (upstream of every other P0) |
| Bootstrap CI on backtest | 🔴 | 🔴 | 🔴 | 🔴 | P1 |
| Permutation null backtest | 🔴 | 🔴 | 🔴 | 🔴 | P1 |
| Feature drift (PSI) | 🔴 | 🔴 | 🔴 | 🔴 | P2 |
| Pre-modelling EDA (IC/MI/redundancy) | ✅ | 🟢 | 🟡 (manual) | 🔴 | P1 (wiring) |
| Rolling IC | 🟠 | 🔴 | 🔴 | 🔴 | P1 |
| Decile analysis | 🟠 | 🔴 | 🔴 | 🔴 | P1 |
| Score trajectory | 🟠 | 🔴 | 🔴 | 🔴 | P1 |
| Paper-trade tracking | 🔴 | 🔴 | 🔴 | 🔴 | P0 (if trading) |

**Summary counts.**
- 🟢 Integrated, library-quality: **5 pillars** (per-class metrics, ROC/PR plotting, SHAP, regime backtest, pretrain EDA library).
- 🟡 Library exists, manual to run: **3 pillars**.
- 🟠 Notebook / manual only: **6 pillars** (incl. label-quality audit).
- 🔴 Missing: **9 pillars** (ECE gate, permutation importance, ablation, walk-forward, classification regime split, bootstrap, permutation null, PSI, paper-trade, label/feature-parity audit).

---

## 4. Critical-path build sequence

Tied to the whitepaper's modelling sprints (S1 = M01_v2_binary; S2 = M01-Watch;
etc.). Each evaluation work item is sized to **unblock** rather than to be
shipped alongside model work.

### Phase A — before S1 (M01_v2_binary)

These are P0 because the binary-vs-prototype comparison is meaningless without
them. Two items have been pulled in from later phases: **label-quality audit**
(every other gate is theatre against a leaky label) and **paper-trade
logging** (zero-cost to start now, irreversible cost to delay).

| Item | Effort | Output |
|---|---|---|
| Label-quality + feature-parity audit | 2d | `label_audit(...)`, `feature_parity_check(...)`, `label_registry.json` carried by every model artifact |
| ECE computation + calibration gate | 0.5d | `calibration_audit(probs, y) → {ece, brier, pass}` + plotted reliability per bin |
| Walk-forward CV harness (classification only, no backtest yet) | 2d | `anchored_walk_forward(...) → per-fold {model, X_test, y_test, preds}`; reused by training script |
| Threshold optimization helper | 0.5d | `find_optimal_threshold(probs, y, mode='precision_min', target=0.6)` |
| Paper-trade prediction logging (`daily_predictions` table, no UI yet) | 1d | One row per `(date, ticker, model_version)` written by Phase 8; manual toggle deferred to Phase D |
| **Total before S1** | **6d** | |

### Phase B — between S1 and S2 (during M01-Watch substrate work)

Walk-forward backtest integration is sized larger here than the original
estimate: the per-fold backtest will surface leakage issues in
`run_backtest.py` (see §2.5 commentary) — cleanup is part of the work, not a
follow-up. Regime-conditional classification is promoted to P0 because S3
(regime routing) cannot be validated without it.

| Item | Effort | Output |
|---|---|---|
| Walk-forward backtest harness + per-fold integration | 3–5d | per-fold trades + equity; aggregator; whatever `run_backtest.py` cleanup the integration exposes |
| Regime-conditional classification metrics (**P0**) | 1d | `metrics_by_regime(...)` |
| Permutation importance + ablation backtest | 1.5d | Resolves SHAP-vs-Gain disagreement |
| **Total between S1 and S2** | **5.5–7.5d** | |

### Phase C — parallel to S2 (M01-Watch) or S3 (regime routing)

| Item | Effort | Output |
|---|---|---|
| Block bootstrap on trades | 1d | 95% CI on Sharpe, return, max DD |
| Permutation null backtest | 1.5d | "Top-1% vs null distribution" check |
| Rolling IC / decile / score-trajectory library | 2d | `src/analytics/` — enables M01-Hold |
| **Total** | **4.5d** | |

### Phase D — operational

| Item | Effort | Output |
|---|---|---|
| Paper-trade dashboard toggle ("taken/skipped" + outcome backfill view) | 1d | UI on top of the `daily_predictions` table already being written in Phase A |
| PSI / feature drift + Pipeline Health surface | 1.5d | Drift alerts |
| Pretrain audit auto-invoked in training script | 0.5d | One HTML report per model run |
| **Total** | **3d** | |

**Total to close every pillar:** ~19 days, or roughly **4 weeks of one
developer's time**. The increase over the previous "16 days" estimate reflects
(a) the added label-quality pillar, (b) the realistic WF backtest sizing, and
(c) pulling paper-trade logging forward to Phase A. Work is spreadable across
the modelling sprints in [whitepaper](whitepaper_path_forward_2026_05_23.md)
§2.4 because most items unblock specific sprints rather than running before
them — but Phase A (6d) is the hard prerequisite for S1.

---

## 5. What "we have done enough" looks like

A model is **promotion-ready** when *all* the following are auto-generated and
green:

1. `confusion_matrix`, `roc_curves`, `pr_curves`, `calibration_curves`,
   `feature_importance`, SHAP — already automatic. ✅
2. **ECE < 0.05** on the production class. *(Phase A)*
3. **Walk-forward** mean classification metrics within ±10% of in-sample; worst
   fold's ROC-AUC ≥ 0.65. *(Phase A)*
4. **Walk-forward backtest** mean Sharpe > 0.5; worst-fold Sharpe > 0;
   worst-fold max DD < 35%; mean top-3 Home Run lift > 5×. *(Phase B)*
5. **Regime-conditional**: positive Sharpe in ≥ 3 of 5 regimes; in the failing
   regime, behavior must be "doesn't bleed" (max DD < 15%) rather than "wins big
   then loses big". *(Phase B)*
6. **Permutation + ablation**: SHAP, permutation, and ablation agreement on
   feature importance top-5 (≥ 3 features in common). *(Phase B)*
7. **Block bootstrap**: 5% percentile Sharpe > 0; permutation-null backtest
   sits in the top 5% of the null distribution. *(Phase C)*
8. **PSI vs training reference**: < 0.25 on every top-20 feature. *(Phase D)*

That checklist becomes the body of `ModelRegistry.set_prod()` — refusing
promotion if any item is red. **This is the single most leveraged piece of
infrastructure we can build**: it turns the whitepaper §5 "academic bar" from
aspiration into a green/red light on the Model Lab page.

---

## 6. What we are NOT building (and why)

- **K-fold cross-validation.** Standard k-fold violates the temporal structure
  of financial data. Walk-forward replaces it entirely.
- **Bayesian model averaging / stacking.** Overkill for a single XGBoost
  classifier; reach for it only after every other pillar above is green and
  the model is still under-performing.
- **Tear-sheet generation in pyfolio / quantstats.** Our backtest report.md +
  Backtest Studio dashboard page (per dashboard plan) cover the same surface
  using infrastructure we already control. Adding a third format is churn.
- **Multi-objective hyperparameter optimization.** Premature. Hyperparameters
  for XGBoost on tabular data are near-saturated by the existing defaults
  (`max_depth=4`, `lr=0.05`); we get more leverage from features and labels.
- **Live A/B testing of models.** No live capital deployment yet; A/B is a
  post-deployment concern.

---

## 7. How this composes with the other plans

| Question | Answer (link) |
|---|---|
| What is the high-level priority shift? | [whitepaper §0 / §2](whitepaper_path_forward_2026_05_23.md) — evaluation > new models |
| Where does this work surface to the user? | [dashboard plan §2 page 3 (Model Lab) + §2 page 4 (Backtest Studio) + §2 page 5 (Pipeline Health)](dashboard_implementation_plan_2026_05_23.md) |
| What was already in the notebooks? | [`docs/analytics_pipeline_design.md`](../analytics_pipeline_design.md) §1 |
| What is already library-grade? | [`docs/evaluation_framework_implementation.md`](../evaluation_framework_implementation.md) |
| Why this matters operationally (the m01_rank lesson) | [`docs/session_logs/2026-05-22_backtest-cases.md`](../session_logs/2026-05-22_backtest-cases.md) — leakage-clean negative > unverified positive |

---

## 8. Open decisions for sign-off

1. **Promotion-readiness gate.** Should `ModelRegistry.set_prod()` auto-refuse
   on any red item from §5, or is it advisory only? Recommend: **enforce
   automatically, with `--force` override that logs to the registry.** Failure
   to enforce is what got us m01_rank's 28×.
2. **Permutation null compute budget.** Should we limit it to 100 permutations
   (1 hour) for routine use, with a "deep" 1000-permutation mode reserved for
   pre-promotion? Recommend yes.
3. **Phase A timing.** Should the 3 days of Phase A work happen *before* the
   S1 modelling sprint starts, or in parallel? Recommend before — without ECE
   and walk-forward, the S1 result is unactionable.
4. **PSI reference baseline.** Frozen at training time per-model, or rolling
   12-month window? Recommend: frozen reference (each model carries its own
   training-time PSI baseline). Rolling baseline drifts in lockstep with the
   data and hides the drift we want to detect.
5. **Walk-forward "worst-fold" threshold.** §5 currently inherits the
   whitepaper's "worst-fold Sharpe > 0" rule unmodified. For a 10-year
   anchored WF on 1y increments that's 9 folds — requiring zero
   negative-Sharpe folds is statistically very strict and may never pass even
   for a genuinely good model. Recommend relaxing to **"≥ 7 of 9 folds with
   positive Sharpe, and worst-fold Sharpe > −0.3"**, which preserves the
   spirit (no catastrophic regime) without demanding perfection. To be
   confirmed once the WF harness produces a first set of fold-level numbers.
