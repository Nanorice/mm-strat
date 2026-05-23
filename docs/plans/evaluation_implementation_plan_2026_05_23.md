# Evaluation Framework — Implementation Plan

> **Created:** 2026-05-23
> **Owner:** Hang
> **Status:** Draft for review.
> **Companion docs:**
>   • [`evaluation_gap_analysis_2026_05_23.md`](evaluation_gap_analysis_2026_05_23.md)
>     — strategy / what's missing / why it matters (read first).
>   • [`whitepaper_path_forward_2026_05_23.md`](whitepaper_path_forward_2026_05_23.md)
>     §5 — academic-grade target.
>   • [`dashboard_implementation_plan_2026_05_23.md`](dashboard_implementation_plan_2026_05_23.md)
>     — where each pillar surfaces to the user.

---

## 0. How to use this document

The gap analysis says **what** is missing and **why** it matters.
This plan says **what to build** and **how it plugs into the existing code**.

Each work item has the same shape:

| Field | Meaning |
|---|---|
| **Module** | Concrete file path + new vs. modified |
| **API** | Function/class signatures with types |
| **Inputs** | Where the data comes from (DuckDB table / training script / artifact dir) |
| **Outputs** | What gets written (file path, table, JSON shape, plot) |
| **Integration** | Where it gets wired into the existing pipeline |
| **Acceptance test** | The concrete check that says "this is done" |
| **Effort** | Days |
| **Depends on** | Other items that must land first |

Pillars not listed here are already done (per-class metrics, ROC/PR plotting,
SHAP, Brier score, regime-conditional backtest, pretrain audit library).

**Important convention.** Every new evaluator module returns a `dict`
serializable to JSON (matching the pattern of `ClassificationEvaluator.evaluate`)
and optionally writes a `.png` + a `.json` to
`models/<model_name>/<version>/evaluation/`. No new directory conventions; no
new persistence patterns.

---

## 1. Cross-cutting infrastructure (foundational, ~0.5d)

Two pieces of shared scaffolding land before any pillar work. They cost half a
day combined and remove ~30 lines of boilerplate from every later module.

### 1.1 `EvaluationGate` — pass/fail recording

**Module.** [`src/evaluation/gate.py`](../../src/evaluation/gate.py) (new).

**API.**
```python
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class GateResult:
    name: str                    # e.g. "calibration_ece"
    status: Literal["pass", "fail", "warn", "n/a"]
    value: float | None          # the observed metric
    threshold: float | None      # the bar we tested against
    detail: str                  # human-readable explanation
    blocking: bool               # True ⇒ blocks set_prod()

class EvaluationGate:
    def __init__(self, model_version: str): ...
    def record(self, result: GateResult) -> None: ...
    def is_promotable(self) -> bool: ...   # True iff no blocking 'fail'
    def to_dict(self) -> dict: ...         # for results.json
```

**Output.** Appended to `results.json` under a top-level `gates: list[dict]`
key. `set_prod()` reads this back to enforce promotion (see §6).

**Acceptance test.** [`test/test_evaluation_gate.py`](../../test/test_evaluation_gate.py)
constructs three results (one pass, one warn, one blocking fail), asserts
`is_promotable()` returns False, asserts serialization round-trips.

**Effort.** 0.25d.

---

### 1.2 Standardized `evaluator_run` metadata block

**Module.** Extend `BaseEvaluator._save_metrics_json` in
[`src/evaluation/base_evaluator.py`](../../src/evaluation/base_evaluator.py).

**Change.** Today the `_metadata` block holds `model_name`, `model_version`,
`evaluation_timestamp`, `evaluator_class`. Add: `git_sha` (via
`subprocess.check_output(['git', 'rev-parse', 'HEAD'])`), `python_version`,
`label_registry_id` (the `label_id` from §2.1), `feature_set_id`,
`pipeline_run_id` (read from `pipeline_runs` table, latest completed).

**Why it's foundational.** Without it, audits done a year apart can't prove
they were on comparable inputs. The label-quality work in §2.1 depends on this
existing.

**Acceptance test.** Existing
[`test/test_classification_evaluator.py`](../../test/test_classification_evaluator.py)
extended to assert the new fields exist and are populated.

**Effort.** 0.25d.

---

## 2. Phase A — pre-S1 (M01_v2_binary), 6 days

These items are **gating** for the binary-classifier sprint. They land first;
they land together; the S1 sprint does not start until §5's promotion-readiness
checklist can run end-to-end (even if some gates fail — what matters is the
checklist runs).

### 2.1 Label-quality + feature-parity audit  *(P0, 2d)*

**Why it's first.** Every other pillar in this plan evaluates a model against
labels and features. If either is silently broken, every other gate is theatre.
The m01_rank case studies in
[`docs/session_logs/2026-05-22_backtest-cases.md`](../session_logs/2026-05-22_backtest-cases.md)
are the cautionary tale.

#### 2.1.1 Label registry

**Module.** [`src/evaluation/label_registry.py`](../../src/evaluation/label_registry.py)
(new).

**API.**
```python
from dataclasses import dataclass
import json
from pathlib import Path

@dataclass(frozen=True)
class LabelDefinition:
    label_id: str           # e.g. "mfe_4class_30d_v1"
    description: str        # one-paragraph human description
    target_col: str         # the column name in v_d2_training
    horizon_days: int       # forward window the label scans
    exit_rule: str          # SQL or function reference describing exit logic
    bins: list[float] | None  # MFE thresholds, if multi-class
    source_query: str       # the SQL that produced the label
    git_sha: str            # commit at which the label was generated
    generated_at: str       # ISO timestamp

    @classmethod
    def from_json(cls, path: Path) -> "LabelDefinition": ...
    def to_json(self, path: Path) -> None: ...
    def fingerprint(self) -> str:  # sha256 of canonical JSON
        ...
```

**Output.** One `label_registry/<label_id>.json` per label, version-controlled.
Model artifacts (`models/<name>/<version>/`) gain a `label_definition.json`
that is a copy of the registry entry the model was trained against, frozen at
training time.

**Integration.** Add to
[`scripts/train_mfe_classifier.py`](../../scripts/train_mfe_classifier.py) at
the top of `main()`:
```python
label_def = LabelDefinition.from_json(
    Path("label_registry") / f"{args.label_id}.json"
)
# carry into artifact dir:
label_def.to_json(model_artifact_dir / "label_definition.json")
```

**Acceptance test.** [`test/test_label_registry.py`](../../test/test_label_registry.py)
asserts: (a) round-trip JSON, (b) `fingerprint()` is stable across re-serialization,
(c) `LabelDefinition` with a different `horizon_days` produces a different
fingerprint.

**Effort.** 0.5d.

---

#### 2.1.2 Label-side leakage audit

**Module.** Extend [`src/evaluation/leakage_guard.py`](../../src/evaluation/leakage_guard.py).

**API.**
```python
class LeakageGuard:
    @staticmethod
    def audit_label(
        labels_df: pd.DataFrame,      # (ticker, date, label) at minimum
        price_data_view: str,         # DuckDB view name (e.g. "v_d3_deployment")
        label_def: LabelDefinition,
        db_path: Path,
        max_horizon_days: int | None = None,  # defaults to label_def.horizon_days
    ) -> dict:
        """
        Verify every (ticker, date) label uses only price_data within the
        declared horizon. Returns:
          {
            "checked_n": int,
            "horizon_violations": list[dict],  # rows referencing bars beyond horizon
            "missing_price_rows": list[dict],  # labels with no matching prices
            "max_observed_horizon_days": int,
            "passed": bool,
          }
        """
```

**Method.** For each `(ticker, label_date)`, query `price_data` for the
horizon window declared in `label_def`. Re-derive the label from those prices
using a reference implementation (small function — `recompute_mfe_label`) and
compare to the stored label. Any disagreement = violation. Any label that
references prices beyond `horizon_days` from `label_date` = horizon violation.

**Output.** Section in `results.json` under `label_audit:`. If violations > 0,
records a blocking `GateResult(name="label_horizon", status="fail")`.

**Acceptance test.** A synthetic fixture in
[`test/test_label_audit.py`](../../test/test_label_audit.py): build a tiny
parquet with 10 tickers × 60 days, stash a deliberately-leaky label
(uses bar at `t + 45` when horizon is 30), assert the audit flags it.

**Effort.** 1d.

---

#### 2.1.3 Training-vs-deployment feature parity

**Module.** Extend [`src/evaluation/leakage_guard.py`](../../src/evaluation/leakage_guard.py).

**API.**
```python
class LeakageGuard:
    @staticmethod
    def feature_parity_check(
        train_view: str,        # e.g. "v_d2_training"
        deploy_view: str,       # e.g. "v_d3_deployment"
        feature_set_id: str,    # which features to compare
        db_path: Path,
        sample_n: int = 100,
        rtol: float = 1e-6,
    ) -> dict:
        """
        Sample N (ticker, date) pairs present in both views. For each pair,
        load the feature vector from train and from deploy. Assert numerical
        equality (np.allclose with rtol) and dtype equality.
        Returns:
          {
            "sampled_pairs": int,
            "matched": int,
            "mismatches": list[{ticker, date, feature, train_val, deploy_val}],
            "dtype_mismatches": list[dict],
            "passed": bool,
          }
        """
```

**Why it matters.** m01_rank case 2 (per the case-studies session log) was a
categorical-encoding parity bug: training saw the raw VARCHAR sector;
deployment passed integer codes. The result was a backtest that "looked great"
because of feature ordering noise. This check would have caught it in 30
seconds.

**Output.** Section in `results.json` under `feature_parity:`. Records a
blocking `GateResult(name="feature_parity", status="fail")` if any mismatch
beyond `rtol` or any dtype mismatch.

**Integration.** Auto-invoked at training time (before fitting): the training
script runs `feature_parity_check` and aborts with a clear error if mismatches
> 0. Optional override via `--skip-parity` for emergencies (logs a warning).

**Acceptance test.** [`test/test_feature_parity.py`](../../test/test_feature_parity.py):
deliberately corrupt one feature in `v_d3_deployment` (via a temporary view),
assert the check catches it.

**Effort.** 0.5d.

---

### 2.2 ECE + calibration gate  *(P0, 0.5d)*

**Module.** [`src/evaluation/calibration.py`](../../src/evaluation/calibration.py)
(new).

**API.**
```python
import numpy as np

def expected_calibration_error(
    y_true_binary: np.ndarray,    # 0/1 array (this class vs rest)
    y_prob: np.ndarray,           # predicted probability for this class
    n_bins: int = 10,
) -> dict:
    """
    Returns:
      {
        "ece": float,                 # weighted |bin_acc - bin_pred|
        "max_calibration_error": float,
        "n_bins": int,
        "bin_data": list[{lo, hi, n, mean_pred, mean_obs, gap}],
      }
    """

def calibration_audit(
    y_true: np.ndarray,           # multi-class labels
    y_pred_proba: np.ndarray,     # (n, n_classes)
    class_names: list[str],
    production_class_idx: int,    # class for which the gate enforces ECE
    ece_threshold: float = 0.05,
) -> dict:
    """
    Runs ECE per class. Records a blocking GateResult for the production class
    if ECE > ece_threshold.
    Returns:
      {
        "ece_per_class": {class_name: ece_dict},
        "production_class": class_name,
        "production_class_ece": float,
        "gate": GateResult,
      }
    """
```

**Why a single production class.** ECE is meaningful per-class; the gate is
only blocking on the class we *use* (e.g., "Home Run" for MFE). Other classes
are reported, not gated, to avoid blocking promotion on an unused class.

**Integration.** Called from `ClassificationEvaluator.evaluate` (step 7,
alongside the existing Brier score block). `production_class_idx` derived from
`actionable_classes` (last actionable class by convention; overridable).

**Output.** New keys in `results.json`: `ece_per_class`, `production_class_ece`,
`gates: [{name: "calibration_ece", ...}]`. New plot
`calibration_reliability_<class>.png` per class (one diagram showing
mean_pred vs mean_obs with bin-population histogram beneath).

**Acceptance test.** [`test/test_calibration.py`](../../test/test_calibration.py):
build perfectly-calibrated probabilities (ECE ≈ 0, passes); shift them by +0.2
(ECE >> 0.05, fails); verify gate behavior.

**Effort.** 0.5d.

---

### 2.3 Walk-forward classification harness  *(P0, 2d)*

This is the core multi-fold scaffolding. Walk-forward backtest integration is
deferred to §3.1 (Phase B) — that step is heavier and surfaces in `run_backtest.py`
cleanup work.

**Module.** [`src/evaluation/walk_forward.py`](../../src/evaluation/walk_forward.py)
(new).

**API.**
```python
from dataclasses import dataclass
from datetime import date
from typing import Callable, Iterator
import pandas as pd

@dataclass(frozen=True)
class FoldSpec:
    fold_idx: int                  # 0, 1, 2, ...
    train_start: date
    train_end: date                # inclusive
    test_start: date               # always > train_end
    test_end: date

@dataclass
class FoldResult:
    spec: FoldSpec
    model_path: Path               # saved booster
    X_test: pd.DataFrame
    y_test: pd.Series
    y_pred_proba: np.ndarray
    metrics: dict                  # per-fold classification metrics
    train_seconds: float

def anchored_walk_forward(
    df: pd.DataFrame,              # full panel with `date` column
    date_col: str,
    train_start: date,
    test_start: date,              # first fold's test_start
    test_end: date,                # final fold's test_end
    step: str = "1Y",              # "1Y", "6M", "1Q"
    min_train_years: int = 3,
) -> Iterator[FoldSpec]:
    """Yield anchored folds: train_end advances, train_start is fixed."""

def run_walk_forward(
    df: pd.DataFrame,
    date_col: str,
    feature_cols: list[str],
    target_col: str,
    fold_specs: list[FoldSpec],
    train_fn: Callable[[pd.DataFrame, pd.DataFrame], xgb.Booster],
    output_dir: Path,
) -> list[FoldResult]:
    """Train one model per fold, serialize, return per-fold results."""

def aggregate_walk_forward(
    fold_results: list[FoldResult],
    class_names: list[str],
    production_class_idx: int,
) -> dict:
    """Aggregate per-fold metrics:
       - mean / std / worst-fold for accuracy, weighted_f1, macro_f1, ROC-AUC
       - aggregate confusion matrix (sum across OOS folds)
       - stability plot data (metric vs fold_idx)
       - GateResult: worst-fold ROC-AUC ≥ 0.65 on production class
       - GateResult: mean classification metric within ±10% of in-sample baseline
    """
```

**Method (anchored, not sliding).** The whitepaper §5.1 spec is anchored:
`train_start` is fixed (e.g. 2010-01-01), `train_end` advances by `step`, each
fold tests on `[train_end + 1d, train_end + step]`. With 10y of data and 1y
steps this yields ~7 folds (years 4-10 as test windows, with at least
`min_train_years=3` of training data in fold 0).

**Why anchored.** Sliding-window WF cuts old regime data the model could
benefit from. Anchored mirrors how the production system will eventually be
retrained: cumulative history, fresh test window.

**Integration with `train_mfe_classifier.py`.** New mode:
`python scripts/train_mfe_classifier.py --walk-forward --fold-step 1Y`.
When `--walk-forward` is set, the script:
1. Loads data once.
2. Generates folds via `anchored_walk_forward`.
3. For each fold, calls a closure `train_fn(X_train, y_train) -> booster`
   that wraps the existing training logic.
4. Saves per-fold booster to `models/<name>/<version>/folds/fold_<i>.model`.
5. Calls `aggregate_walk_forward` to produce `walk_forward_summary.json` +
   `walk_forward_stability.png`.
6. Records gate results.

**Output.**
- `models/<name>/<version>/folds/` — one `.model` per fold + per-fold JSON.
- `models/<name>/<version>/evaluation/walk_forward_summary.json`.
- Plots: `walk_forward_stability.png` (F1 by fold), `walk_forward_confusion_aggregate.png`.

**Acceptance test.** [`test/test_walk_forward.py`](../../test/test_walk_forward.py):
synthetic panel of 5 years × 100 tickers, run 1Y-step WF, assert (a) folds are
chronologically disjoint, (b) `aggregate_walk_forward` returns expected shape,
(c) gate fires when worst-fold ROC-AUC dips below 0.65.

**Effort.** 2d.
- 0.5d: `FoldSpec` generation + tests.
- 1d: `run_walk_forward` + serialization + per-fold metric capture.
- 0.5d: aggregator + stability plot + gate.

---

### 2.4 Threshold optimization helper  *(P1, 0.5d)*

**Module.** [`src/evaluation/thresholding.py`](../../src/evaluation/thresholding.py)
(new).

**API.**
```python
from typing import Literal

def find_optimal_threshold(
    y_true: np.ndarray,           # binary 0/1
    y_prob: np.ndarray,
    mode: Literal["precision_min", "f1_max", "youden"],
    target: float | None = None,  # required for "precision_min"
) -> dict:
    """
    Returns:
      {
        "threshold": float,
        "precision_at_threshold": float,
        "recall_at_threshold": float,
        "f1_at_threshold": float,
        "n_signals": int,
        "mode": str,
        "achievable": bool,        # False if precision_min target cannot be hit
      }
    """
```

**Output.** Used by the binary M01_v2 work to set a deployment threshold that
guarantees ≥ 60% precision. Saved to model artifact as
`thresholds.json`: `{"production_class": "Home Run", "threshold": 0.42, ...}`.

**Integration.** Called from `train_mfe_classifier.py` after evaluation. Not a
gate — just a helper.

**Acceptance test.** [`test/test_thresholding.py`](../../test/test_thresholding.py):
build a known PR curve, assert `precision_min=0.6` returns the leftmost
threshold satisfying it; assert `achievable=False` when no threshold meets the
target.

**Effort.** 0.5d.

---

### 2.5 Paper-trade prediction logging  *(P0, 1d)*

Pulled forward from Phase D because the cost of logging is ~0 and the cost of
not logging is irreversible.

#### 2.5.1 Schema

**New table.** Created by a migration script
[`scripts/migrations/2026_05_24_create_daily_predictions.sql`](../../scripts/migrations/2026_05_24_create_daily_predictions.sql)
(new).

```sql
CREATE TABLE IF NOT EXISTS daily_predictions (
    prediction_date  DATE        NOT NULL,
    ticker           VARCHAR     NOT NULL,
    model_version_id VARCHAR     NOT NULL,        -- FK to models.version_id
    prob_class_0     DOUBLE,
    prob_class_1     DOUBLE,
    prob_class_2     DOUBLE,
    prob_class_3     DOUBLE,                       -- nullable for binary models
    predicted_class  INTEGER,
    rank_within_day  INTEGER,                     -- rank by prob_elite, 1 = top
    decision_taken   VARCHAR DEFAULT NULL,        -- 'taken' | 'skipped' | NULL
    taken_at         TIMESTAMP DEFAULT NULL,
    notes            VARCHAR DEFAULT NULL,
    ingested_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (prediction_date, ticker, model_version_id)
);
CREATE INDEX idx_daily_predictions_date ON daily_predictions(prediction_date);
CREATE INDEX idx_daily_predictions_model ON daily_predictions(model_version_id);
```

The `decision_taken` column stays NULL until the Phase D UI lands. That's
intentional — we want every prediction recorded regardless of action.

#### 2.5.2 Writer

**Module.** [`src/evaluation/prediction_logger.py`](../../src/evaluation/prediction_logger.py)
(new).

**API.**
```python
def log_daily_predictions(
    db_path: Path,
    prediction_date: date,
    model_version_id: str,
    predictions: pd.DataFrame,  # cols: ticker, prob_class_*, predicted_class
) -> int:
    """
    Writes one row per (date, ticker, model_version_id). Computes rank by
    prob_elite (the configured production class). Idempotent: INSERT OR REPLACE.
    Returns rows written.
    """
```

**Integration.** Modify
[`src/orchestrators/daily_pipeline_orchestrator.py`](../../src/orchestrators/daily_pipeline_orchestrator.py)
Phase 8: after the existing monitoring step, call `log_daily_predictions` if
a prod model is registered (`registry.get_prod_version()`). On model absence,
skip silently and log a single warning.

**Acceptance test.** [`test/test_prediction_logger.py`](../../test/test_prediction_logger.py):
in-memory DuckDB, simulate two days × 50 tickers, verify rows match expected
count and ranks; re-run same date and verify idempotency (no duplicate-key
errors, no doubled rows).

**Effort.** 1d.
- 0.25d: migration + table creation.
- 0.5d: writer + integration in Phase 8.
- 0.25d: tests.

**Note on UI toggle.** The dashboard "taken/skipped" UI is Phase D §5.1.
Without it, `decision_taken` stays NULL — that's expected and not a bug. The
predictions accumulate; the analysis layer becomes useful as soon as the UI
lands, with full history backfillable.

---

## 3. Phase B — between S1 and S2, 5.5-7.5 days

These run alongside the M01-Watch substrate work. They convert the raw
walk-forward data from Phase A into actual backtest-validated robustness
claims, and close the SHAP-vs-Gain disagreement that's been open since the
roadmap was written.

### 3.1 Walk-forward backtest harness  *(P0, 3-5d)*

**Module.** [`src/evaluation/walk_forward_backtest.py`](../../src/evaluation/walk_forward_backtest.py)
(new).

**API.**
```python
@dataclass
class FoldBacktestResult:
    fold_spec: FoldSpec
    trades: pd.DataFrame           # exit_date, ticker, return, hold_days, ...
    equity_curve: pd.DataFrame     # date, equity
    metrics: dict                  # sharpe, max_dd, win_rate, top_3_home_run_lift

def run_walk_forward_backtest(
    fold_results: list[FoldResult],   # from §2.3
    backtest_config: dict,
    output_dir: Path,
) -> list[FoldBacktestResult]:
    """For each fold, score test-window features with that fold's model,
    feed the resulting signals into run_backtest, capture per-fold trades/equity.
    """

def aggregate_walk_forward_backtest(
    bt_results: list[FoldBacktestResult],
) -> dict:
    """
    Returns:
      - per-fold table of Sharpe/return/max_dd/win_rate/HR_lift
      - mean / std / worst-fold for each metric
      - aggregate equity curve (concatenated OOS windows)
      - GateResult: mean Sharpe > 0.5
      - GateResult: worst-fold Sharpe > -0.3 AND ≥ 7 of 9 folds positive
        (per §8 open decision #5 in the gap analysis)
      - GateResult: worst-fold max DD < 35%
      - GateResult: mean top-3 Home Run lift > 5×
    """
```

**Realism budget for the leakage cleanup.** The current `run_backtest.py`
assumes a single trained model. Per-fold backtesting will surface at least
three issues we know about from m01_rank:
1. Entry-signal date boundary (does the model use today's close, or
   yesterday's?). Per-fold testing makes this visible because boundary errors
   cause fold-1 and fold-2 to behave inconsistently.
2. Universe membership at signal time (whether the ticker was screener-eligible
   *then*). Easy to get wrong with materialized views.
3. Categorical encoding parity (the one §2.1.3 already catches; this fold
   sweep will exercise it across multiple training windows).

Budget 2d for the harness itself + 1-3d for these fixes. Worst-case 5d total.

**Output.**
- `models/<name>/<version>/folds/fold_<i>/trades.parquet` + `equity.parquet`.
- `models/<name>/<version>/evaluation/walk_forward_backtest_summary.json`.
- `models/<name>/<version>/evaluation/walk_forward_equity.png` (all folds + aggregate).

**Acceptance test.** [`test/test_walk_forward_backtest.py`](../../test/test_walk_forward_backtest.py):
two synthetic folds with deterministic signals, assert per-fold trades match
hand-computed expected; assert gates fire correctly when fed degraded folds.

**Effort.** 3-5d (see realism budget above).

**Depends on.** §2.3 (`FoldResult` structure).

---

### 3.2 Regime-conditional classification metrics  *(P0, 1d)*

Promoted to P0 because S3 (regime routing) cannot be validated without it.

**Module.** [`src/evaluation/regime_decomposition.py`](../../src/evaluation/regime_decomposition.py)
(new).

**API.**
```python
from typing import Callable

REGIME_NAMES = ["Strong Bull", "Bull", "Neutral", "Bear", "Strong Bear"]

def metrics_by_regime(
    df: pd.DataFrame,                  # one row per prediction; must include 'regime_cat'
    y_col: str,
    y_pred_col: str,
    y_prob_col: str,
    metric_fns: dict[str, Callable] | None = None,
    min_samples_per_regime: int = 30,
) -> dict:
    """
    Returns:
      {
        regime_name: {
          'n': int,
          'accuracy': float,
          'weighted_f1': float,
          'top_3_lift': float,
          'calibration_ece': float,
          'roc_auc_production_class': float,
        }
      }
    Regimes with n < min_samples_per_regime get status='insufficient_data'.
    """

def regime_decomposition_gate(
    by_regime: dict,
    min_regimes_passing: int = 3,
    failing_regime_max_dd_threshold: float = 0.15,  # for backtest variant
) -> GateResult:
    """Positive ROC-AUC in ≥ N regimes; in failing regime, no catastrophic
    behavior (this version is classification-side, so 'no catastrophic' is
    interpreted as ROC-AUC ≥ 0.5)."""
```

**Integration.** `ClassificationEvaluator.evaluate` gains a new step that, if
the test data has a `regime_cat` column (joined from `m03_regime_history`),
runs `metrics_by_regime`. Plot: `metrics_by_regime.png` — grouped bars,
metric × regime.

**Output.** New `results.json` keys: `regime_decomposition: {by_regime: ..., gate: ...}`.

**Acceptance test.** [`test/test_regime_decomposition.py`](../../test/test_regime_decomposition.py):
synthetic predictions with deliberately-bad performance in one regime, assert
the failing regime is flagged and `min_regimes_passing` gate fires correctly.

**Effort.** 1d.

---

### 3.3 Permutation importance + ablation backtest  *(P1, 1.5d)*

Resolves the SHAP-vs-Gain disagreement open since
[`docs/development_roadmap.md`](../development_roadmap.md) §4.

#### 3.3.1 Permutation importance

**Module.** Extend `ClassificationEvaluator` with `_compute_permutation_importance`.

**API.** Internal method; wraps `sklearn.inspection.permutation_importance`
with a thin adapter for XGBoost (predict_proba → log-loss as scorer).

```python
def _compute_permutation_importance(
    model: xgb.Booster,
    X_test: pd.DataFrame,
    y_test: np.ndarray,
    n_repeats: int = 5,
    n_jobs: int = -1,
) -> pd.DataFrame:
    """Returns DataFrame[feature, mean_importance, std_importance]
    sorted descending."""
```

**Output.** `results.json` key `permutation_importance: list[{feature, ...}]`.
Plot: `permutation_importance.png` (top-20 bar chart with std error bars).
**No gate.** This is a diagnostic.

**Effort.** 0.5d.

---

#### 3.3.2 Ablation backtest

**Module.** [`scripts/ablation_backtest.py`](../../scripts/ablation_backtest.py)
(new).

**API (CLI).**
```
python scripts/ablation_backtest.py \
  --model-version M01_baseline_v0.1 \
  --feature-groups Momentum,RegimeContext,Volume \
  --output models/M01_baseline_v0.1/ablation/
```

**Method.** For each feature group passed: (a) retrain the model dropping that
group's features, (b) run a backtest on the same time window, (c) capture
delta-Sharpe and delta-return vs the full-feature baseline.

**Output.** `models/<name>/<version>/ablation/ablation_summary.json`:
```json
{
  "baseline": {"sharpe": 1.2, "return": 0.85, ...},
  "ablations": [
    {"group_dropped": "Momentum", "sharpe": 0.7, "delta_sharpe": -0.5, ...}
  ]
}
```

Plot: `ablation_impact.png` — horizontal bar chart of delta-Sharpe by group.

**The triangulation rule** (for §5 promotion gate later): a model is "feature-
robust" if **SHAP top-5, permutation top-5, and ablation top-3 share ≥ 3
features**. Implemented as a `triangulation_check()` helper called by §6's
promotion gate.

**Acceptance test.** [`test/test_ablation_backtest.py`](../../test/test_ablation_backtest.py):
minimal smoke test on the existing m01_baseline checkpoint with one feature
group; assert output JSON shape.

**Effort.** 1d.

---

## 4. Phase C — parallel to S2/S3, 4.5 days

### 4.1 Block bootstrap on trades  *(P1, 1d)*

**Module.** [`src/evaluation/bootstrap.py`](../../src/evaluation/bootstrap.py)
(new).

**API.**
```python
def circular_block_bootstrap(
    trades_df: pd.DataFrame,         # one row per trade with 'return' col
    metric_fn: Callable[[pd.DataFrame], float],  # e.g. sharpe, total_return
    block_size: int = 60,            # days; trades are first re-grouped by exit_date
    n_iterations: int = 10_000,
    seed: int = 42,
) -> dict:
    """
    Returns:
      {
        "metric_observed": float,
        "metric_median": float,
        "ci_5": float,
        "ci_95": float,
        "n_iterations": int,
        "block_size": int,
        "gate": GateResult,    # CI_5(sharpe) > 0 = pass
      }
    """
```

**Method.** Sort trades by `exit_date`. Construct blocks of size `block_size`
calendar days (so consecutive trades likely fall in the same block, preserving
serial correlation). Resample blocks with replacement to reconstruct a
"shadow" trade list of the original length; compute `metric_fn`; repeat
`n_iterations` times.

**Integration.** Called from `run_backtest.py` post-trade-generation, when
`--bootstrap` flag is set. Saved to backtest output dir.

**Acceptance test.** [`test/test_bootstrap.py`](../../test/test_bootstrap.py):
synthetic trades with known Sharpe; assert observed value sits inside its own
CI; assert larger `n_iterations` shrinks CI width as expected.

**Effort.** 1d.

---

### 4.2 Permutation null backtest  *(P1, 1.5d)*

**Module.** [`src/evaluation/permutation_null.py`](../../src/evaluation/permutation_null.py)
(new).

**API.**
```python
def permutation_null_backtest(
    signals_df: pd.DataFrame,        # date, ticker, signal_flag
    price_data: pd.DataFrame,        # date, ticker, close
    backtest_fn: Callable[[pd.DataFrame], dict],  # numpy fast-path
    n_permutations: int = 100,       # 1000 for "deep" mode, see budget
    seed: int = 42,
) -> dict:
    """
    Per iteration: shuffle the signal column within each date (preserves
    universe size and signal density per day, destroys ticker-signal link).
    Run the fast-path backtest, capture sharpe.
    Returns:
      {
        "observed_sharpe": float,
        "null_distribution": list[float],
        "percentile": float,         # where the observed value sits
        "p_value": float,            # 1 - percentile/100
        "n_permutations": int,
        "gate": GateResult,          # percentile > 95 = pass
      }
    """
```

**NumPy fast-path note.** A full backtrader-based backtest is ~30s; 100
permutations × 30s = 50min, tractable. 1000 × 30s = 8h, not tractable for
routine use. The "deep" 1000-permutation mode reuses the same code path but is
invoked only pre-promotion (per §8 open decision #2 in the gap analysis).

**No new backtest engine.** We reuse `run_backtest.py` in a "headless mode"
(`--no-backtrader --numpy-engine`). The numpy engine path needs to exist
already; if it doesn't, **expand effort to 2.5d** to add it. As of this draft,
assume it does (the m01_rank scorer at
[`scripts/m01_rank_scorer.py`](../../scripts/m01_rank_scorer.py) suggests
numpy-only paths exist in this repo).

**Acceptance test.** [`test/test_permutation_null.py`](../../test/test_permutation_null.py):
synthetic dataset where the "real" signal is pure noise; assert observed
percentile sits near 50 (not at the tail); flip to a deterministic-edge signal,
assert percentile > 99.

**Effort.** 1.5d.

---

### 4.3 Rolling IC / decile / score-trajectory library  *(P1, 2d)*

Direct enabler of M01-Hold (whitepaper §2.3.3).

**New module tree.** [`src/analytics/`](../../src/analytics/) (new package).

#### 4.3.1 `src/analytics/rolling_ic.py`

```python
def rolling_ic(
    df: pd.DataFrame,              # date, ticker, score, forward_return
    window_days: int = 252,
    score_col: str = "score",
    return_col: str = "forward_return_5d",
    method: Literal["spearman", "pearson"] = "spearman",
) -> pd.DataFrame:
    """Per-date Spearman/Pearson IC + rolling mean + rolling t-stat (NW-adjusted)."""
```

#### 4.3.2 `src/analytics/decile_analysis.py`

```python
def decile_analysis(
    df: pd.DataFrame,              # date, ticker, score, forward_return
    score_col: str,
    return_col: str,
    n_buckets: int = 10,
) -> dict:
    """Returns per-decile mean return + monotonicity score (Spearman rank corr
    between decile index and mean return)."""
```

#### 4.3.3 `src/analytics/score_trajectory.py`

```python
def score_trajectory(
    scores_df: pd.DataFrame,       # date, ticker, score
    event_dates_df: pd.DataFrame,  # ticker, event_date (e.g., breakout date)
    window_before: int = 30,
    window_after: int = 30,
) -> pd.DataFrame:
    """Score path T-30 → T+30 around each event; returns mean ± CI by relative day."""
```

**Output.** Each function returns DataFrames, optionally rendered to an HTML
report via the existing `html_report.build_html_report`. New page:
`analytics_report.html` saved per model.

**Integration.** Optional post-evaluation step in `train_mfe_classifier.py`:
`--with-analytics` flag. Not in the promotion gate — these are exploratory.

**Acceptance test.** [`test/test_analytics_module.py`](../../test/test_analytics_module.py):
three smoke tests, one per file, with synthetic data verifying shape and
sanity (monotonic score → monotonic decile returns).

**Effort.** 2d.

---

## 5. Phase D — operational, 3 days

### 5.1 Paper-trade dashboard toggle  *(P0, 1d)*

The `daily_predictions` table is already being written from Phase A §2.5.
This phase adds the UI.

**Module.** [`src/dashboard/pages/today.py`](../../src/dashboard/pages/today.py)
(modified) and a new component file
[`src/dashboard/components/decision_toggle.py`](../../src/dashboard/components/decision_toggle.py).

**Spec.**
- The "Today's Signals" table in the Today page gets a new column
  "Decision" with a 3-state select widget per row: `[—]` / `[Taken]` / `[Skipped]`.
- Selecting updates the `decision_taken` + `taken_at` columns via a
  parametrized `UPDATE`.
- A second view "Performance of past decisions" joins `daily_predictions`
  (where `decision_taken IS NOT NULL`) against `screener_watchlist` to surface
  realized outcomes.

**Integration with existing dashboard plan.** This is a partial implementation
of the Model Lab "Today" page from
[`dashboard_implementation_plan_2026_05_23.md`](dashboard_implementation_plan_2026_05_23.md)
§2.3. Tag the components so they're reusable.

**Acceptance test.** Manual: load dashboard, select Taken/Skipped on three
rows, query DuckDB to confirm rows updated; reload page to confirm persistence.

**Effort.** 1d.

---

### 5.2 PSI / feature drift  *(P2, 1.5d)*

**Module.** [`src/evaluation/drift.py`](../../src/evaluation/drift.py) (new).

**API.**
```python
def compute_psi(
    reference: np.ndarray,
    current: np.ndarray,
    bins: int = 10,
    epsilon: float = 1e-6,
) -> float:
    """PSI = sum_i (curr_pct_i - ref_pct_i) * ln(curr_pct_i / ref_pct_i).
    Bins from reference quantiles (so the binning is fixed at training time)."""

def reference_snapshot(
    train_df: pd.DataFrame,
    feature_cols: list[str],
    output_path: Path,
) -> None:
    """Save per-feature quantiles + bin counts. Called once at training time."""

def quarterly_drift_report(
    reference_snapshot_path: Path,
    current_view: str,             # e.g. "v_d3_deployment"
    db_path: Path,
    quarter: str,                  # "2026Q1"
) -> dict:
    """Compute PSI per feature for the current quarter. PSI > 0.25 = drift.
    Returns:
      {
        "quarter": str,
        "model_version": str,
        "per_feature": {feature: {psi, status}},
        "drifted_features": list[str],
      }
    """
```

**Why frozen reference.** Per §8 open decision #4 in the gap analysis: a
rolling baseline drifts in lockstep with the data and hides the drift we want
to detect. Each model's `reference_snapshot.json` is its own immutable
baseline.

**Integration.**
- Training script: `reference_snapshot` is called at the end and saved to
  `models/<name>/<version>/reference_snapshot.json`.
- Daily pipeline Phase 8: optional quarterly invocation of
  `quarterly_drift_report`, writing to `logs/drift/`.
- Dashboard "Pipeline Health" page reads `logs/drift/` and surfaces drifted
  features.

**Acceptance test.** [`test/test_drift.py`](../../test/test_drift.py): two
synthetic distributions (identical → PSI ≈ 0; shifted by 1σ → PSI > 0.25);
verify thresholds.

**Effort.** 1.5d.

---

### 5.3 Pretrain audit auto-invocation  *(P1, 0.5d)*

**Module.** Modify
[`scripts/train_mfe_classifier.py`](../../scripts/train_mfe_classifier.py).

**Change.** Before training, call `run_pretrain_audit(df, target_col,
feature_cols, output_dir)`. Save the resulting HTML to
`models/<name>/<version>/pretrain_audit.html`.

**Integration.** One-line addition in `main()`. The library function already
exists; this is pure wiring.

**Acceptance test.** Run `python scripts/train_mfe_classifier.py
--smoke-test`; assert `pretrain_audit.html` appears in the artifact dir.

**Effort.** 0.5d.

---

## 6. Promotion-readiness gate — `ModelRegistry.set_prod()` integration

This is the keystone. Without it, the entire framework is advisory. With it,
red gates physically block promotion.

**Module.** Modify
[`src/model_registry.py`](../../src/model_registry.py) `set_prod()`.

**Current behavior** (per
[`src/model_registry.py:210-228`](../../src/model_registry.py#L210-L228)):
unconditionally archives the previous prod model and promotes the new one.

**New behavior.**
```python
def set_prod(self, version_id: str, force: bool = False, force_reason: str = "") -> None:
    # 1. Load results.json for this version.
    results_path = self.get_artifacts_path(version_id) / "evaluation" / "results.json"
    if not results_path.exists():
        raise PromotionError(f"No evaluation results for {version_id}; cannot promote.")

    with results_path.open() as f:
        results = json.load(f)

    # 2. Collect all gates from results.
    gates = results.get("gates", [])
    blocking_failures = [g for g in gates if g["blocking"] and g["status"] == "fail"]

    # 3. Enforce.
    if blocking_failures and not force:
        msg = "Promotion blocked by failing gates:\n"
        for g in blocking_failures:
            msg += f"  - {g['name']}: observed={g['value']} threshold={g['threshold']} — {g['detail']}\n"
        msg += "Override with set_prod(..., force=True, force_reason='...')"
        raise PromotionError(msg)

    if blocking_failures and force:
        if not force_reason:
            raise PromotionError("force=True requires force_reason")
        # Log to a new table:
        self._log_force_promotion(version_id, blocking_failures, force_reason)

    # 4. Proceed with existing set_prod logic.
    ...
```

**New table.**
```sql
CREATE TABLE IF NOT EXISTS forced_promotions (
    version_id   VARCHAR PRIMARY KEY,
    reason       VARCHAR NOT NULL,
    failed_gates JSON    NOT NULL,
    promoted_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    promoted_by  VARCHAR
);
```

**Why force-with-logging beats force-without.** §8 open decision #1 in the gap
analysis recommends auto-enforce with `--force` override. The forced_promotions
log makes the override expensive to use (you have to write a reason and that
reason is permanently visible in the registry) without making it impossible.

**Acceptance test.** [`test/test_promotion_gate.py`](../../test/test_promotion_gate.py):
- Construct a results.json with one blocking fail; assert `set_prod()` raises.
- Same, with `force=True` and reason; assert promotion succeeds and `forced_promotions` row exists.
- Same, with `force=True` no reason; assert PromotionError.
- All-passing gates; assert normal promotion.

**Effort.** 0.5d (the gates themselves are the work; this is plumbing).

---

## 7. Sequencing and dependencies

```
Phase A (6d, gate for S1)
├─ §1.1 EvaluationGate            (0.25d, foundational)
├─ §1.2 Metadata block            (0.25d, foundational)
├─ §2.1 Label + parity audit       (2d)
├─ §2.2 ECE + calibration gate     (0.5d)
├─ §2.3 Walk-forward classification (2d)        ← §2.1 must land first
├─ §2.4 Threshold helper           (0.5d)
└─ §2.5 Paper-trade logging        (1d)

Phase B (5.5-7.5d, during S1 and M01-Watch)
├─ §3.1 WF backtest harness        (3-5d)       ← §2.3 required
├─ §3.2 Regime-conditional         (1d)
└─ §3.3 Permutation + ablation     (1.5d)

Phase C (4.5d, parallel to S2/S3)
├─ §4.1 Block bootstrap            (1d)
├─ §4.2 Permutation null backtest  (1.5d)
└─ §4.3 Analytics library          (2d)

Phase D (3d, operational)
├─ §5.1 Paper-trade UI             (1d)         ← §2.5 already wrote rows
├─ §5.2 PSI / drift                (1.5d)
└─ §5.3 Pretrain audit wiring      (0.5d)

§6 Promotion gate                  (0.5d)       ← lands at end of Phase A,
                                                  enforces every gate added since
```

**Critical path** = §1.1 + §1.2 + §2.1 + §2.3 + §6 = **5 days** to a working
gated promotion flow. Everything else extends what the gate checks but isn't
strictly required to *start* using the promotion-blocking pattern.

**Total to close every pillar:** ~19 days (matches the gap analysis §4 revised
total).

---

## 8. Definition of done (per item and overall)

### Per-item DoD checklist

Each work item is "done" only when **all five** are true:

1. **Library function exists** at the specified path and matches the API above.
2. **Unit tests** pass under `pytest test/test_<item>.py`.
3. **Integration** — the appropriate calling script (`train_mfe_classifier.py`,
   `run_backtest.py`, orchestrator) is modified to invoke it automatically;
   no copy-paste in user scripts.
4. **Gate (if applicable)** — a `GateResult` is recorded to `results.json` and
   the §6 promotion check reads it.
5. **One real model** has been run end-to-end through the new check; the
   output artifact (plot, JSON, dashboard page) has been visually confirmed.

### Overall DoD

The framework is "done" when:
- `ModelRegistry.set_prod()` refuses to promote a model that fails any
  blocking gate, end-to-end on a real artifact.
- The `M01_baseline_v0.1` model has been re-evaluated under the new framework
  and either passes all gates or fails with a written explanation per failure
  (since it was registered before this framework existed, expect some failures
  — that is the point).
- The dashboard "Today" page shows the day's predictions logged to
  `daily_predictions` with the decision toggle live.
- The whitepaper §5 acceptance criteria are testable from a single command:
  `python scripts/evaluate_model.py --version <id> --gate-check`.

---

## 9. Open questions for sign-off

Inherited from the gap analysis (sections §8 #1-5 there), plus implementation-
specific:

1. **`EvaluationGate` storage.** Inline in `results.json`, or in a separate
   `gates` table in DuckDB? Recommend **inline first; promote to table once
   the dashboard's Model Lab page wants to query across models**.
   (Decision deferrable.)
2. **WF step size.** `1Y` everywhere, or per-model? Recommend **1Y default,
   per-model override via training config**, so M03 (which has fewer regime
   transitions per year) can use longer steps.
3. **NumPy fast-path for `permutation_null_backtest`.** Per §4.2, this assumes
   a numpy-only backtest engine exists. **Confirm before starting §4.2** —
   if not, expand effort by 1d.
4. **`force=True` audit policy.** Should forced promotions auto-notify
   anyone (e.g., log a warning to a separate alerts channel)? Recommend
   **logging to the forced_promotions table is sufficient; a noisier
   notification can be added if forced promotions become routine, which would
   itself be a signal the gates are wrong**.
5. **Real-time prediction logging when no prod model exists.** Currently §2.5
   skips silently if `registry.get_prod_version()` returns None. Should the
   pipeline log *all registered models'* predictions for comparison?
   Recommend **only prod for now; add others when M01_v2 lands and we want
   shadow comparison**.

---

## 10. What this plan deliberately does NOT cover

- **The S1/S2/S3 modelling work itself.** This plan unblocks them; it doesn't
  do them. Sprint plans for the binary classifier, M01-Watch, and regime
  routing are separate documents.
- **Backfilling the prediction log to before §2.5 lands.** Once logging starts,
  it starts. Pre-logging history isn't reconstructible at the per-day grain;
  pretending otherwise would be a worse mistake than admitting we start from
  here.
- **The dashboard chrome around all of this.** This plan adds API surfaces and
  one page extension (§5.1); the broader dashboard plan covers integration.
- **Live A/B testing of models.** No live capital deployment yet; A/B is a
  post-deployment concern (gap analysis §6).
