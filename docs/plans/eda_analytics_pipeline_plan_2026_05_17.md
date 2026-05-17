# EDA & Analytics Pipeline — Implementation Plan

> **Date**: 2026-05-17
> **Source**: `docs/analytics_pipeline_design.md` (fact-checked against `notebooks/model_proto.ipynb` + `notebooks/scores_eda.ipynb`)
> **Objective**: Define `src/evaluation/` as a standalone analytics library for training data auditing and model performance evaluation. Not wired into the daily pipeline — called explicitly during model development and promotion decisions.
> **Status**: Draft — awaiting approval before any code changes.

---

## 0. Purpose & Function Catalogue

### What this suite is for

The notebooks `model_proto.ipynb` and `scores_eda.ipynb` contain all the analytical techniques needed to develop, validate, and compare models. The problem is they are ad-hoc: logic is duplicated across cells, findings are not reproducible without re-running the notebook, and there is no enforcement mechanism to stop a bad model reaching production.

This suite extracts those techniques into an importable library under `src/evaluation/`. It is **not** part of the daily pipeline — it is called explicitly by a developer when training or promoting a model. The two entry points are:

```python
# 1. Before training: is the data clean and which features have signal?
audit_training_data(feature_matrix_df) -> TrainingDataReport

# 2. After training: does the model generalise, and is it better than prod?
evaluate_model_performance(model, test_df, scores_df) -> ModelEvalReport
```

These can be called independently or chained via:

```python
run_full_evaluation(model, feature_matrix_df, test_df, scores_df) -> FullReport
```

### Function catalogue by category

| Category | Functions | Purpose |
|---|---|---|
| **A. Training Data Quality** | `audit_feature_matrix()` | Null rates, zero-variance, infinite values, warm-up clip detection, leakage guard, bad ticker flagging. Halts on P0 violations. Findings surfaced for manual upstream fix — not auto-applied. |
| **B. Feature Analysis** | `compute_ic()`, `compute_mutual_information()`, `compute_correlation_matrix()`, `rank_scatter()` | Measure individual feature predictiveness (Spearman IC, MI) and redundancy (correlation). MI tiebreaking within correlated clusters. Informs feature selection before training. |
| **C. Model Validation** | `walk_forward_cv()`, `calibration_analysis()`, `shap_analysis()` | Temporally disciplined OOS evaluation: expanding-window walk-forward, per-class calibration curves, SHAP global/local importance. Per-fold stability plots surface regime-conditional degradation. |
| **D. Model Comparison** | `compare_models()`, `held_out_eval()` | Evaluate two models on the same frozen test window (2024+ holdout) to produce apple-to-apple comparison. Required before any new model replaces prod. |
| **E. Promotion Gate** | `check_promotion_gates()` | Hard P0 gates (macro F1, weighted F1, calibration error) enforced in `ModelRegistry.set_prod()`. P1 warnings for rolling IC and feature drift (PSI). |
| **F. Strategy Analytics** | `decile_analysis()`, `rolling_ic()`, `score_trajectory()`, `entry_rule_analysis()`, `score_momentum_ic()`, `regime_gated_ic()` | Map model scores to financial reality: monotonicity of score vs returns, time-varying IC, score ramp/decay around breakout events, entry rule candidates, regime conditionality of the edge. |

### Two pipelines, one handoff point

The suite serves two distinct analytical questions:

**Training data pipeline** (Categories A + B) — runs on `t3_sepa_features / feature_matrix`:
- Is the data clean enough to train on?
- Which features carry signal vs. noise vs. redundancy?
- Findings are surfaced as a report; any fixes go back to `feature_pipeline.py` manually.

**Model performance pipeline** (Categories C + D + E + F) — runs on OOS predictions + `scores_df`:
- Does the model generalise across time and market regimes?
- Is the calibrated score a reliable ranking signal?
- Is the new model strictly better than prod on the same held-out window?

The handoff between the two is the **held-out cutoff date** (proposed: 2024-01-01). Training data must exclude this window; performance evaluation must use only it. This date is set once and hardcoded in `config.py`.

---

---

## 1. Module Map

All modules live under `src/evaluation/`. Standalone — not imported by the daily pipeline. Only imports from `src/model_registry.py`, `src/feature_config.py`, and standard libraries.

```
src/evaluation/
├── __init__.py             # exports: audit_training_data, evaluate_model_performance, run_full_evaluation
├── data_quality.py         # Category A — training data audit (null, leakage, bad tickers, warm-up)
├── feature_analysis.py     # Category B — IC, MI, multicollinearity, feature selection
├── model_eval.py           # Category C — walk-forward CV, calibration, SHAP
├── model_comparison.py     # Category D — held-out eval, compare_models (apple-to-apple)
├── strategy_analytics.py   # Category F — decile, rolling IC, score trajectory, entry rules, regime gating
└── report.py               # Assembly: audit_training_data(), evaluate_model_performance(), run_full_evaluation()
```

Supporting scripts (standalone, not imported by daily pipeline):

```
scripts/
├── run_training_data_audit.py    # Category A+B: data quality + feature analysis report
└── run_model_evaluation.py       # Category C+D+E+F: full model validation + comparison report
```

---

## 2. Module A — Data Quality (`data_quality.py`)

**Purpose**: Block downstream analysis on dirty data. Must run before IC or SHAP.

This addresses the gap in `analytics_pipeline_design.md §3.2`: the notebooks *do* perform these checks but they're ad-hoc. This module makes them mandatory and automated.

### Functions

```python
def audit_feature_matrix(df: pd.DataFrame) -> DataQualityReport:
    """
    Returns a structured report; raises DataQualityError if any P0 gate fails.
    """
```

**P0 gates (HALT pipeline if triggered)**:
- Any column with null rate > 50%
- Any column with zero variance (constant)
- Any column with >10% infinite values
- Target column (`mfe_class`) is null for >1% of rows

**Warnings (log but continue)**:
- Null rate 1–50% per column (bar chart in report)
- Extreme values: single-period return >500%, 20d return >1000%
- Warm-up rows: first N rows per ticker with >30% nulls (clip to `warmup_cutoff`)

**Bad ticker detection** (from `scores_eda.ipynb`):
- Flag tickers where any single return exceeds economic limit (300% for 20d, 500% for 60d)
- Output: `bad_tickers` list for caller to decide on exclusion

**Leakage guard**:
- Reject columns matching: `exit_*`, `return_*`, `mfe_*`, `mae_*`, `breakout_ok` — these were confirmed as leakage candidates in `scores_eda.ipynb`

**Output**: `DataQualityReport` dataclass with `passed: bool`, `null_rates: pd.Series`, `bad_tickers: list[str]`, `warnings: list[str]`.

---

## 3. Module B — Feature Analysis (`feature_analysis.py`)

**Purpose**: Understand individual feature predictiveness before training. Source: `model_proto.ipynb` cells 1-4.

### Functions

```python
def compute_ic(
    df: pd.DataFrame,
    features: list[str],
    target: str,
    method: Literal["spearman", "pearson"] = "spearman"
) -> pd.Series:
    """Rank IC of each feature vs target. Returns Series sorted by abs(IC)."""

def compute_mutual_information(
    df: pd.DataFrame,
    features: list[str],
    target: str
) -> pd.Series:
    """Sklearn mutual_info_classif. Returns Series sorted by MI score."""

def rank_scatter(ic: pd.Series, mi: pd.Series) -> plt.Figure:
    """IC rank vs MI rank scatter — surfaces features where IC and MI disagree."""

def compute_correlation_matrix(
    df: pd.DataFrame,
    features: list[str],
    threshold: float = 0.75
) -> tuple[pd.DataFrame, list[tuple[str, str]]]:
    """
    Returns (corr_matrix, redundant_pairs).
    redundant_pairs: feature pairs with abs(corr) > threshold.
    Used upstream by caller to prune before SHAP.
    """
```

**Notebook finding to encode as default thresholds**:
- `threshold=0.75` for multicollinearity — matches the `model_proto.ipynb` TODO note on hierarchical clustering cutoff
- IC bar chart: show top-30 by abs(IC); flag features with IC < 0.01 as "low signal"
- MI tiebreaking: within correlated clusters, keep feature with higher MI (not IC)

**Output**: `FeatureAnalysisReport` dataclass containing all series + figures. Figures included in final report.

---

## 4. Module C — Model Evaluation (`model_eval.py`)

**Purpose**: Validate the trained model with strict temporal discipline. Source: `model_proto.ipynb` walk-forward cells.

### 4.1 Walk-Forward Validation

```python
def walk_forward_cv(
    df: pd.DataFrame,
    features: list[str],
    target: str,
    model_cls,
    n_folds: int = 5,
    min_train_years: int = 2
) -> WalkForwardResult:
    """
    Expanding-window walk-forward. Each fold trains on [T0, Tn], tests on [Tn, Tn+1].
    min_train_years: minimum history before first test fold begins.
    Returns per-fold metrics + aggregate.
    """
```

**Per-fold metrics**: accuracy, weighted F1, macro F1, per-class F1, log-loss.

**Stability plot**: line chart of per-fold metrics over time — surfaces regime-conditional degradation (the 2022-2023 IC collapse pattern seen in `scores_eda.ipynb` should show up here as low F1 folds).

**Aggregate confusion matrix**: sum OOS predictions across all folds, normalise. Both count and percentage versions.

### 4.2 Calibration

```python
def calibration_analysis(
    y_true: np.ndarray,
    y_proba: np.ndarray,
    n_classes: int = 4
) -> CalibrationResult:
    """
    One reliability diagram per class.
    Flags conservative bias at top end (per scores_eda.ipynb finding: model understates
    confidence at high scores).
    """
```

### 4.3 SHAP (deferred to first implementation sprint)

SHAP was a TODO in `model_proto.ipynb` — not yet implemented. Include the stub now; implement in sprint 2.

```python
def shap_analysis(
    model,
    X: pd.DataFrame,
    max_display: int = 20
) -> ShapResult:
    """Global bar chart + beeswarm. Local waterfall for top-10 predictions."""
    # Sprint 2 — stub raises NotImplementedError until implemented
```

### 4.4 Promotion Gate

This is the T3.1 enforcement point. `evaluate_model()` calls this at the end.

```python
def check_promotion_gates(result: WalkForwardResult) -> GateCheckResult:
    """
    P0 gates (BLOCK promotion):
    - macro F1 OOS < 0.20
    - weighted F1 OOS < 0.50
    - calibration: mean abs deviation > 0.15 across probability buckets
    - any fold has accuracy < 0.55 (consecutive bad folds indicate regime failure)
    P1 gates (WARN, human decision):
    - rolling IC (from strategy_analytics) < 0.02 over last 6 months
    - PSI on top-10 features > 0.2 (feature drift)
    """
```

Thresholds are set to cause the current `M01_baseline_v0.1` (acc=0.6705, wF1=0.582, macroF1=0.248) to **pass** P0 gates as a baseline. Tighten thresholds as variants improve.

---

## 5. Module D — Strategy Analytics (`strategy_analytics.py`)

**Purpose**: Map model scores to financial reality. Source: `scores_eda.ipynb` in full.

### 5.1 Decile Analysis

```python
def decile_analysis(
    scores: pd.Series,
    returns: pd.DataFrame,      # columns: return_1d, return_5d, return_20d, return_60d
    excess: bool = True         # demean by daily cross-sectional average
) -> DecileResult:
    """
    Bins scores into 10 deciles using pd.qcut().
    Returns table: mean/median return + hit rate per decile, per horizon.
    Also runs sub-quintile analysis on decile 9 (top bucket concentration test).
    Monotonicity check: flag if any decile violates rank ordering.
    """
```

### 5.2 Rolling IC

```python
def rolling_ic(
    scores: pd.Series,
    returns: pd.Series,
    window: int = 60,           # trading days
    horizons: list[str] = ["return_1d", "return_5d", "return_20d"]
) -> pd.DataFrame:
    """
    Per-date Spearman IC, rolling window.
    Key metric: mean IC / std IC — a ratio < 0.3 signals regime-conditional edge only.
    From scores_eda: IC std is 3-4x mean IC (0.21-0.24 vs ~0.06). This is by design but
    must be reported so caller knows gating is mandatory, not optional.
    """
```

### 5.3 Score Trajectory Analysis

```python
def score_trajectory(
    scores_df: pd.DataFrame,    # columns: ticker, date, score, is_home_run_event
    window_before: int = 30,
    window_after: int = 30
) -> TrajectoryResult:
    """
    Aligns score time series on T=0 (breakout day) for Home Run events vs non-events.
    Key finding from scores_eda to reproduce:
    - T-30 to T-5: gradual ramp ~0.37 → 0.45 (early warning)
    - T=0: peak ~0.51
    - T+1 to T+30: decay to ~0.40 (conviction decay)
    This is the primary evidence base for M01-Hold design.
    """
```

### 5.4 Entry Rule Optimization

```python
def entry_rule_analysis(
    scores_df: pd.DataFrame,
    threshold: float,
    returns: pd.Series
) -> EntryRuleResult:
    """
    Tests 3 candidate rules from scores_eda.ipynb:
    - Rule 1: score > threshold (baseline)
    - Rule 2: score > threshold AND rising (score_delta > 0)
    - Rule 3: 3 consecutive days with score > threshold
    Returns per-rule: signal count, mean return, hit rate, IC.
    scores_eda finding: Rule 3 wins (higher mean return, comparable hit rate, fewer false starts).
    This finding should be reproduced, not assumed.
    """
```

### 5.5 Score Momentum IC

```python
def score_momentum_ic(
    scores: pd.Series,
    returns: pd.Series,
    momentum_window: int = 5
) -> float:
    """
    IC of score delta (score_t - score_{t-5}) vs forward 20d return.
    scores_eda finding: IC = 0.166 — meaningful independent predictor.
    Relevant for M01-Hold: can score changes predict continuation vs. mean-reversion.
    """
```

### 5.6 Regime-Gated IC

```python
def regime_gated_ic(
    scores: pd.Series,
    returns: pd.Series,
    regime_col: pd.Series,      # m03_score or future regime_v2 score
    gates: dict = {"bull": (60, 100), "neutral": (40, 60), "bear": (0, 40)}
) -> dict[str, float]:
    """
    Computes IC within each regime bucket.
    Compares baseline (m03_score) vs 5-factor gate — whichever produces higher
    bull-regime IC and lower bear-regime IC wins.
    scores_eda finding: m03_score < 40 should suppress all signals; > 60 = full effectiveness.
    """
```

---

## 6. Report Assembly (`report.py`)

```python
def evaluate_model(
    model,
    df: pd.DataFrame,
    features: list[str],
    target: str,
    scores_df: pd.DataFrame | None = None,   # if provided, runs Module D
    output_path: Path | None = None
) -> ValidationReport:
    """
    Full pipeline:
    1. Module A: data_quality.audit_feature_matrix(df) — halts on P0 fail
    2. Module B: feature_analysis (IC, MI, multicollinearity)
    3. Module C: walk_forward_cv → calibration → check_promotion_gates
    4. Module D (optional): decile, rolling IC, trajectory, entry rules (requires scores_df)
    5. Assemble → Markdown report → save to output_path or return as string
    """
```

**Report sections** (maps to T3.1 model validation report template):

```
## Model Validation Report — {model_id} — {date}

### 1. Data Quality
  - Null rate table (top offenders)
  - Bad tickers flagged
  - Leakage columns excluded

### 2. Feature Analysis
  - IC bar chart (top 30)
  - MI bar chart (top 30)
  - IC vs MI rank scatter
  - Redundant pairs (corr > 0.75)

### 3. Walk-Forward Validation
  - Per-fold metrics table
  - Stability line plots (F1, accuracy by fold)
  - Aggregate confusion matrix
  - Calibration curves (4 classes)

### 4. Promotion Gate Results
  - PASS / FAIL per gate with values
  - Decision: PROMOTE / HOLD / REJECT

### 5. Strategy Analytics (if scores provided)
  - Decile return table (1d/5d/20d/60d)
  - Rolling IC plot (60d window)
  - Score trajectory (T-30 to T+30)
  - Entry rule comparison
  - Regime-gated IC table
```

---

## 7. Sequencing & Dependencies

This pipeline is a **prerequisite for T3.1** in the system action plan, not a standalone project.

```
[T1.x — data quality complete]
        │
        ▼
Module A (data_quality.py)       ← unblocked now, no model needed
        │
        ▼
Module B (feature_analysis.py)   ← requires clean feature matrix
        │
        ▼
Module C (model_eval.py)         ← requires trained model (M01_baseline_v0.1 exists)
   walk_forward + calibration
        │
        ▼
T3.1 gate enforced in ModelRegistry.set_prod()
        │
        ├──▶ Module D (strategy_analytics.py) ← requires scored deployment data
        │         score_trajectory → informs M01-Hold label design
        │
        ▼
T3.2 M01 variants (Watch/Hold)
```

SHAP (Module C stub) is explicitly deferred to sprint 2 — it is not on the critical path for T3.1 promotion gating.

---

## 8. Implementation Sprints

### Sprint 1 — Training data audit + feature analysis — ~3 days

| File | Content | Day |
|---|---|---|
| `src/evaluation/__init__.py` | exports only | 1 |
| `src/evaluation/data_quality.py` | Category A complete: null audit, warm-up clip, leakage guard, bad ticker detection (1d return + dominance ratio) | 1-2 |
| `src/evaluation/feature_analysis.py` | Category B: IC, MI, corr matrix, rank scatter, MI tiebreaking | 2-3 |
| `scripts/run_training_data_audit.py` | CLI: `python scripts/run_training_data_audit.py` → prints DataQualityReport + saves FeatureAnalysisReport | 3 |

**Sprint 1 acceptance**: audit run on current `t3_sepa_features` produces a report flagging `dist_from_20d_high_delta` nulls and the `breakout_ok` leakage column. Findings are reported only — no auto-fix.

**Data quality feedback convention**: findings from this report go back to the pipeline manually. The report includes a dedicated "Action Required" section listing columns/tickers that need upstream fixes, formatted so they can be copy-pasted into a `feature_pipeline.py` ticket.

### Sprint 2 — Model validation + promotion gate — ~3 days

| File | Content | Day |
|---|---|---|
| `src/evaluation/model_eval.py` | Category C: walk-forward CV, per-class calibration, SHAP stub | 4-5 |
| `src/evaluation/model_comparison.py` | Category D: `held_out_eval()`, `compare_models()` with frozen 2024+ test window | 5-6 |
| `src/evaluation/report.py` | Assembly: `audit_training_data()`, `evaluate_model_performance()`, `run_full_evaluation()` | 6 |
| `scripts/run_model_evaluation.py` | CLI: `python scripts/run_model_evaluation.py --model M01_baseline_v0.1` | 6 |

**Held-out protocol**: cutoff date `2024-01-01` set in `config.py`. Both prod and dev models retrained on pre-2024 data, evaluated on the same 2024-2026 window. `compare_models()` produces a side-by-side table of all P0 gate metrics.

**Sprint 2 acceptance**: `ModelRegistry.set_prod()` refuses promotion with "macro F1 below threshold" on a deliberately degraded model. `compare_models(baseline, candidate)` produces a valid side-by-side report.

### Sprint 3 — Strategy analytics + SHAP — ~3 days

| File | Content | Day |
|---|---|---|
| `src/evaluation/strategy_analytics.py` | Category F: decile analysis (with excess return / SPY demean), rolling IC, score trajectory, entry rule analysis, score momentum IC, regime-gated IC | 7-9 |
| `src/evaluation/model_eval.py` | SHAP implementation replaces stub (Category C) | 8 |

**Excess return dependency**: `decile_analysis(excess=True)` requires SPY daily returns loaded from `macro_data` table. Flag as blocked if SPY data is missing — do not silently fall back to raw returns.

**Sprint 3 acceptance**: score trajectory reproduces the T-30→T+30 ramp/decay shape from `scores_eda.ipynb`. Entry rule analysis confirms Rule 3 finding. These are regression tests against known notebook results.

### Sprint 4 — T3.2 label generators — ~1 day (after T3.1 approved)

| File | Content |
|---|---|
| `src/evaluation/label_generators.py` | `breakout_within_5d()`, `sl_hit_within_K_days()` |

These feed M01-Watch and M01-Hold training data prep. Not needed for Sprints 1-3.

---

## 9. Open Questions (resolve before Sprint 2)

1. **Score trajectory definition**: What is the `is_home_run_event` flag — trades that hit MFE > 30% (Class 3), or trades where `prob_elite` at entry was > threshold? The two populations may not overlap.
2. **Return horizon for entry rules**: `scores_eda` tested against `return_20d`. For M01-Hold, should entry rule IC be measured against a continuation return (T+5 to T+20) rather than absolute return from entry?
3. **Regime gate comparison**: When T2.2 (regime v2) is ready, `regime_gated_ic()` should accept both `m03_score` and `regime_v2_score` in the same call to produce a side-by-side comparison. Design the interface now even if T2.2 doesn't exist yet.
4. **Report format**: Markdown (git-friendly, human-readable) or HTML (charts inline)? Markdown requires saving figures as separate PNGs. HTML is self-contained but harder to diff. Recommendation: Markdown + `figures/` subfolder, generate HTML only on explicit `--html` flag.
