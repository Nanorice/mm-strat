# EDA & Analytics Pipeline — Implementation Plan

> **Date**: 2026-05-17 (revised after codebase fact-check)
> **Source**: Fact-checked against `notebooks/model_proto.ipynb`, `notebooks/scores_eda.ipynb`, `src/managers/view_manager.py`, existing `src/evaluation/`.
> **Objective**: Add the **missing** pre-training analytics layer to `src/evaluation/`. Standalone — called explicitly during model development, not wired into the daily pipeline.
> **Status**: ✅ Phase 1 COMPLETE (2026-05-17). Phases 2+ remain draft.

---

## Reality Check (must read before implementing)

Three corrections to the original draft, verified against source:

1. **`src/evaluation/` already exists** (~4,700 lines): `ClassificationEvaluator`, `ClassificationReportGenerator`, `EvaluationPlotter`, `LeakageGuard`, `M03Evaluator`. The original plan's Modules C/D/E (model eval, calibration, SHAP, confusion matrix) **already exist** inside `ClassificationEvaluator`. **Do not rebuild them.** The genuine gap is **pre-training data audit + feature analysis** — that does not exist.

2. **Verified data lineage** (from `view_manager.py` + live DB counts 2026-05-17):
   ```
   t3_sepa_features        dense, 9,298,701 rows, daily, 144 cols, NO outcome/target   ← TRUE DENSE input
     └─ v_d1_candidates    C1–C11 SEPA signal, ONE ROW PER TRADE (entry_date only, Step 4)
         └─ v_d2_features  + fundamentals/valuation, SPARSE ~38K (same grain as trades!)
             ├─ v_d3_deployment   last 252d slice (scoring input)
             └─ v_d2_training     + MFE/MAE/SL outcomes, 1 row per trade, SPARSE ~38K   ← SPARSE input
                 └─ d2_training_cache   materialized v_d2_training (70× faster load)
   ```
   ⚠️ **CORRECTION vs. original draft**: `v_d2_features` is **NOT** a dense daily table. `v_d1_candidates` Step 4 explicitly keeps "only entry_date row (one row per trade)", so `v_d2_features` = **38,248 rows** — sparse, same grain as `v_d2_training`, just without outcome columns. The genuine dense daily table is `t3_sepa_features` (9.3M rows). `v_d2_training` is correct: sparse ~38K, trade-level, with outcomes. `d2_training_cache` mirrors it exactly (refreshed by `scripts/refresh_training_cache.py`, Phase 7 of daily pipeline).

3. **The notebooks use two different inputs, never reconciled**:
   - `model_proto.ipynb`: `SELECT * FROM v_d2_training ORDER BY date, ticker` → all audit/IC/MI/CV runs here. Target = **`target_class`** (NOT `mfe_class`), derived in-notebook from `mfe_pct` bins: `<=2→0, (2,10]→1, (10,30]→2, >30→3`.
   - `scores_eda.ipynb`: `pq.read_table("scores_cache.parquet")` — a pre-baked `prob_elite` parquet, **not** `t3_sepa_features`, no DB, no model applied in-notebook.

### Phase 1 scope decisions (locked + implemented)

- **Build only the missing gap.** Reuse `LeakageGuard` and `EvaluationPlotter` as-is. Do not touch model-eval code. ✅
- **Phase 1 input = two modes (`dense` / `trades`):**
  - `dense` → `t3_sepa_features WHERE feature_version='v3.1'` (~9.3M rows). Audits feature hygiene *before* trade aggregation, no target column. ✅ (**corrected** from original plan's `v_d2_features`)
  - `trades` → `v_d2_training` (prefers `d2_training_cache` when fresh). 38K sparse trade rows + outcomes. ✅
- **Target binning = function parameter, default = notebook bins.** `derive_target_class(df, bins=DEFAULT_MFE_BINS)` with `DEFAULT_MFE_BINS` in `training_data_loader.py`. ✅
- **Columns lowercased on load** via `df.columns.str.lower()` — matches `model_proto.ipynb` and is stable against DuckDB's TitleCase cross-sectional rank columns. ✅
- **`detect_bad_tickers` thresholds scale-corrected**: `return_*` columns are fractional (1.0=100%), so defaults are `5.0` (=500% 1d) / `10.0` (=1000% 20d), not the notebook's bare `500`/`1000` which never fired. ✅

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

# PHASE 1 — Pre-Training Data Analytics (runnable now)

> **Phase 1 goal**: a working pipeline the user can run *today* to prepare for the next model-development cycle. Answers two questions on the pre-training data: **(a) is it clean?** and **(b) what does the target look like and which features carry signal?**
>
> Out of scope for Phase 1: model evaluation, walk-forward CV, calibration, SHAP, promotion gates, strategy/score analytics. Those either already exist (`ClassificationEvaluator`) or belong to later phases.

## P1.1 Module Map (new files only)

New files under `src/evaluation/` — small, single-responsibility, frequently-reused functions. **No god function.** Reuse existing `LeakageGuard` and `EvaluationPlotter`.

```
src/evaluation/
├── training_data_loader.py   # NEW — load + mode switch (dense / trades) + target derivation
├── data_quality.py           # NEW — null/variance/inf audit, bad-ticker detection, warm-up clip
├── feature_signal.py         # NEW — IC, MI, correlation/redundancy (the 3 most-reused funcs)
└── pretrain_report.py        # NEW — thin assembler: calls the above, emits Markdown + figures
```

Reused as-is (do **not** modify):
- `LeakageGuard.check_feature_leakage()` — already has the exact notebook forbidden-pattern list (`mfe`, `mae`, `return_at_exit`, `final_`, `outcome_`, `exit_`, `result_`).
- `EvaluationPlotter` — bar charts, distributions.

Supporting script:
```
scripts/run_pretrain_audit.py   # CLI: --mode {dense,trades} [--mfe-bins ...] → report
```

## P1.2 `training_data_loader.py` — one loader, two modes ✅ IMPLEMENTED

```python
DEFAULT_MFE_BINS = [(-inf, 2.0, 0), (2.0, 10.0, 1), (10.0, 30.0, 2), (30.0, inf, 3)]

def load_pretrain_data(
    mode: Literal["dense", "trades"] = "trades",
    db_path: str = DB_PATH,
) -> pd.DataFrame:
    """
    mode="dense"  -> SELECT * FROM t3_sepa_features WHERE feature_version='v3.1'
                     (~9.3M rows, daily, NO target — true dense feature hygiene audit)
                     ⚠️ NOT v_d2_features (which is sparse ~38K, same grain as trades)
    mode="trades" -> d2_training_cache if fresh, else v_d2_training
                     ORDER BY date, ticker (matches model_proto.ipynb exactly)
    Columns lowercased on load (df.columns.str.lower()).
    Cache freshness: cache max(date) >= t3_sepa_features max(date).
    """

def derive_target_class(
    df: pd.DataFrame,
    source_col: str = "mfe_pct",
    bins=DEFAULT_MFE_BINS,
) -> pd.Series:
    """np.select on mfe_pct -> target_class (0..3). NaN source -> default=0 (class Dud).
    Only valid in mode='trades' (dense has no mfe_pct)."""
```

Why two modes matter: `dense` audits feature hygiene *before* sparse aggregation (9.3M rows catch broken features at the `t3_sepa_features` source); `trades` audits the actual training matrix + target distribution. Same functions, different input — no logic duplicated.

## P1.3 `data_quality.py` — small functions, not one auditor ✅ IMPLEMENTED

```python
def null_audit(df, feature_cols) -> NullReport:
    """Per-column null rate. P0: >50%. WARN: 1–50%."""

def variance_audit(df, feature_cols) -> list[str]:
    """Zero-variance / constant columns (P0). Skips non-numeric."""

def infinite_audit(df, feature_cols) -> dict[str, float]:
    """Columns with >10% inf (P0).
    ⚠️ Uses to_numpy(dtype='float64', na_value=np.nan) — np.isinf fails on pandas
    nullable integer/boolean types without this cast."""

def detect_bad_tickers(
    df,
    return_1d_thresh: float = 5.0,    # ⚠️ CORRECTED: fractional scale (5.0=500%), NOT 500
    return_20d_thresh: float = 10.0,  # ⚠️ CORRECTED: fractional scale (10.0=1000%), NOT 1000
    dominance_ratio: float = 0.8,
) -> list[str]:
    """scores_eda.ipynb logic, scale-corrected: any 1d>5.0 (=500%), OR 20d>10.0 (=1000%)
    AND return_1d/return_20d > 0.8. Reported, never auto-dropped.
    The notebook's bare 500/1000 never fired because return_* is fractional."""

def warmup_clip(df, sentinels=("rs","m03_score","dist_from_20d_high_delta")) -> pd.DataFrame:
    """Per-ticker cumsum drop of leading-NULL rows (model_proto cell 18).
    Interior NULLs kept — only leading rows before first fully-valid sentinel row dropped."""

def check_leakage(feature_cols) -> dict:
    """Thin wrapper over LeakageGuard.check_feature_leakage() — do not reimplement."""

def run_quality_gate(df, feature_cols, mode) -> DataQualityReport:
    """Composes the above. raises DataQualityError on any P0. WARN logged + in report.
    In mode='dense' the target-null P0 is skipped (no target column)."""
```

`DataQualityReport`: `passed: bool`, `null_rates: pd.Series`, `null_p0_cols`, `zero_variance_cols`, `infinite_cols`, `bad_tickers: list[str]`, `leakage_cols: list[str]`, `warnings: list[str]`, `action_required: list[str]`.

## P1.4 `feature_signal.py` — the 3 reused functions + target distribution ✅ IMPLEMENTED

```python
def target_distribution(y: pd.Series, class_names=("Dud","Noise","Solid","Elite")) -> TargetDist:
    """Class counts, proportions, imbalance ratio. trades-mode only.
    Actual result: Dud 18%, Noise 42%, Solid 29%, Elite 11%, imbalance 3.65×."""

def compute_ic(df, features, target, method="spearman", min_obs=100) -> pd.DataFrame:
    """Per-feature rank IC vs target, ≥min_obs non-null (model_proto cell 42).
    Skips non-numeric columns (sector/industry handled by MI, not IC).
    Returns DataFrame with [feature, spearman_ic, pval, abs_ic, low_signal]."""

def compute_mutual_information(df, features, target, sample_n=20000, seed=42) -> pd.DataFrame:
    """mutual_info_classif on ≤sample_n sample (model_proto cell 44 params exactly).
    sector/industry label-encoded with fresh LabelEncoder per column.
    discrete_features=False (matches notebook, treats encoded categoricals as continuous)."""

def compute_redundancy(df, features, threshold=0.80) -> tuple[pd.DataFrame, list[tuple]]:
    """Spearman corr matrix + pairs |r|>threshold (strict >).
    Default 0.80 = notebook cell 47 actual value (a code comment said 0.85 — wrong).
    Returns (corr_matrix, [(feat_a, feat_b, abs_corr), ...] sorted desc).
    Actual result on current data: 285 redundant pairs."""
```

⚠️ **`rank_scatter` and clustermap** are plotting concerns → delegate to `EvaluationPlotter`. Not added (plan said don't).
⚠️ **IC is trades-mode only in practice** — dense mode has no target column, so `compute_ic`/`compute_mi`/`compute_redundancy` are skipped in the dense assembler path.

## P1.5 `pretrain_report.py` — thin assembler ✅ IMPLEMENTED

```python
def run_pretrain_audit(
    mode: Literal["dense","trades"] = "trades",
    mfe_bins=DEFAULT_MFE_BINS,
    output_path: Path | None = None,
) -> PretrainReport:
    """
    1. load_pretrain_data(mode)
    2. trades only: warmup_clip + derive_target_class
    3. _select_feature_cols (excludes METADATA + RAW_PRICE + LEAKAGE + TARGET cols)
    4. run_quality_gate(...)           # raises DataQualityError on any P0
    5. trades only: target_distribution + compute_ic + compute_mi + compute_redundancy
    6. assemble Markdown to output_path (default: docs/reports/pretrain_audit_<mode>_<ts>.md)
    7. save IC/MI bar charts to docs/reports/figures/ via EvaluationPlotter
    """
```

Feature exclusion sets in `_select_feature_cols` (all lowercased):
- `METADATA_COLS`: ticker, date, feature_version, trade_id, is_new_trigger, company_name, fundamental_filing_date, fiscal_period, entry_date, ingested_at, updated_at, **cached_at** (cache artifact)
- `RAW_PRICE_COLS`: open, high, low, close, volume, entry_price, exit_price
- `LEAKAGE_COLS`: mfe_pct, mfe_date, mae_pct, mae_date, return_at_exit, return_pct, exit_date, exit_price, sepa_exit_date, holding_days, days_observed, sl_triggered, sl_date, sl_exit_date, sl_pct
- `TARGET_COLS`: target_class, target_label (**added during implementation** — derive_target_class adds this column, which would appear as IC=1.0 if not excluded)
- `FORBIDDEN_PATTERNS`: mfe, mae, return_at_exit, final\_, outcome\_, exit\_, result\_

Report sections: Data Quality (null table, bad tickers, leakage, **Action Required**), Target Distribution (trades only), Feature Signal (IC top-30, MI top-30, redundant pairs > 0.80).

---

# PHASE 2+ — Model & Strategy Analytics (DRAFT — re-scope before starting)

> ⚠️ **Most of Phase 2 already exists.** `src/evaluation/ClassificationEvaluator` already implements confusion matrix, per-class metrics, temporal stability, top-K precision, threshold sweep, ROC/PR/Brier, SHAP, feature importance, and calibration. `ClassificationReportGenerator` already assembles the report. **Before implementing anything below, audit `ClassificationEvaluator` and treat these sections as a gap-list against it, not a greenfield build.** Sections 4–9 below are the *original* draft, retained for reference only — their data-source and target-column claims are wrong (see Reality Check at top). Walk-forward CV is the one genuine gap (notebook has rolling + expanding variants, codebase has none).

---

## 4. Module C — Model Evaluation (`model_eval.py`) — *mostly exists in ClassificationEvaluator*

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

## 8. Implementation Plan

### Phase 1 — Pre-training data analytics ✅ COMPLETE (2026-05-17)

The deliverable: `python scripts/run_pretrain_audit.py --mode trades` produces a Markdown report + figures you can act on before the next training cycle.

| Order | File | Status | Content |
|---|---|---|---|
| 1 | `src/evaluation/training_data_loader.py` | ✅ | `load_pretrain_data(mode)` (dense=`t3_sepa_features`, trades=`v_d2_training`/cache), `derive_target_class(df, bins=DEFAULT_MFE_BINS)` |
| 2 | `src/evaluation/data_quality.py` | ✅ | `null_audit`, `variance_audit`, `infinite_audit`, `detect_bad_tickers`, `warmup_clip`, `check_leakage` (wraps `LeakageGuard`), `run_quality_gate` |
| 3 | `src/evaluation/feature_signal.py` | ✅ | `target_distribution`, `compute_ic`, `compute_mutual_information`, `compute_redundancy` |
| 4 | `src/evaluation/pretrain_report.py` | ✅ | `run_pretrain_audit()` — sequences the above, emits Markdown + `figures/` (plots via existing `EvaluationPlotter`) |
| 5 | `src/evaluation/__init__.py` | ✅ | exports: `load_pretrain_data`, `derive_target_class`, `DEFAULT_MFE_BINS`, `run_pretrain_audit`, `PretrainReport` |
| 6 | `scripts/run_pretrain_audit.py` | ✅ | CLI: `--mode {dense,trades}`, `--mfe-bins`, `--out PATH` |

**Phase 1 acceptance (all verified 2026-05-17)**:
1. ✅ `run_pretrain_audit(mode="trades")` runs end-to-end: 35,656 rows (after warmup clip), 187 features, quality PASS.
2. ✅ Leakage design: `_select_feature_cols` pre-strips `mfe_*`/`exit_*`/`mae_*`/`sl_*` columns before `LeakageGuard` runs (exclude-then-verify). Guard reports 0 leakage (correct — backstop confirms no stragglers). Note: the report does not separately list *what was stripped* — if explicit listing of stripped leakage columns is wanted, add a "Excluded from feature set" section to `pretrain_report.py`.
3. ✅ Report contains target distribution (Dud 18%, Noise 42%, Solid 29%, Elite 11%), IC top-30, MI top-30, 285 redundant pairs > 0.80.
4. ✅ `run_pretrain_audit(mode="dense")` runs on 9,298,701 rows, skips target/IC/MI sections, quality PASS, 8 bad tickers detected.
5. ✅ "Action Required" section present (empty when no P0 violations; populated with copy-pasteable fix lines on P0 failures).

**Implementation bugs found and fixed during build** (not in original plan):
- `v_d2_features` is sparse ~38K, not dense (see corrected lineage above). `dense` mode points at `t3_sepa_features`.
- `target_class` column (added by `derive_target_class`) must be excluded from the feature set — fixed in `_select_feature_cols` via `TARGET_COLS`.
- `cached_at` TIMESTAMP (cache artifact, absent from `v_d2_training`) must be excluded — fixed in `METADATA_COLS`.
- `np.isinf` fails on pandas nullable types — fixed via `to_numpy(dtype="float64", na_value=np.nan)`.
- `compute_ic` must skip non-numeric (object) columns — fixed with `is_numeric_dtype` guard.
- Bad-ticker thresholds `500`/`1000` are percentage-scale but `return_*` columns are fractional — corrected to `5.0`/`10.0`.

No auto-fix. Findings are surfaced; the user decides what goes back upstream.

### Phase 2 — Walk-forward CV + close the gap vs ClassificationEvaluator — DRAFT

**First task is an audit, not code**: enumerate what `ClassificationEvaluator` already covers vs. the original Modules C/D/E/F. Only walk-forward CV (rolling + expanding, from `model_proto.ipynb` cells 59/60) is a confirmed gap. Re-scope this phase against that audit before writing anything. Original sections 4–7 are reference-only and contain known data-source errors.

### Phase 3 — Strategy/score analytics — DRAFT

Source is `scores_eda.ipynb`, which reads `notebooks/scores_cache.parquet` (pre-baked `prob_elite`), **not** `t3`. Decide the canonical score input (regenerate the parquet via `UniverseScorer.score_from_t3`, or read `v_d3_deployment`) before designing. Defer.

### Phase 4 — T3.2 label generators — DRAFT (after Phase 2 approved)

`breakout_within_5d()`, `sl_hit_within_K_days()` for M01-Watch/Hold. Not needed for Phases 1–3.

---

## 9. Open Questions

**Phase 1 (none blocking)** — scope is locked; proceed.

**Phase 2+ (resolve before that phase)**

1. **Score trajectory definition**: What is the `is_home_run_event` flag — trades that hit MFE > 30% (Class 3), or trades where `prob_elite` at entry was > threshold? The two populations may not overlap.
2. **Return horizon for entry rules**: `scores_eda` tested against `return_20d`. For M01-Hold, should entry rule IC be measured against a continuation return (T+5 to T+20) rather than absolute return from entry?
3. **Regime gate comparison**: When T2.2 (regime v2) is ready, `regime_gated_ic()` should accept both `m03_score` and `regime_v2_score` in the same call to produce a side-by-side comparison. Design the interface now even if T2.2 doesn't exist yet.
4. **Report format**: Markdown (git-friendly, human-readable) or HTML (charts inline)? Markdown requires saving figures as separate PNGs. HTML is self-contained but harder to diff. Recommendation: Markdown + `figures/` subfolder, generate HTML only on explicit `--html` flag.
