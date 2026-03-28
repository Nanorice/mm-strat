# Model Evaluation Framework - Gap Analysis & Proposal

## Executive Summary

**Issue**: M04 MFE Classifier shows 97% recall on Class 3 (home runs) due to **severe data leakage** - `v_d2_training` includes future outcomes (MFE/MAE) computed from the entire trade horizon.

**Root Cause**: View joins `v_d2r_hydrated` which calculates MFE/MAE from **future price data**, making them available at entry time.

**Impact**: Model is learning "what happened" instead of "what will happen" - invalidates all results.

---

## 1. Current State - Existing Evaluation Components

### ✅ Available (from `src/evaluation/` and `src/pipeline/`)

| Component | File | Purpose | Status |
|-----------|------|---------|--------|
| **M01Evaluator** | `m01_evaluator.py` | Regression model evaluation (IC, RMSE, Edge) | ✅ Production |
| **ReportGenerator** | `reports.py` | Markdown scorecard generation | ✅ Production |
| **Metrics Library** | `metrics.py` | IC, Precision@K, Lift, Volatility Correlation | ✅ Production |
| **Ranking Analysis** | `ranking.py` | Decile analysis, Edge calculation | ✅ Production |
| **Error Analysis** | `errors.py` | FOMO vs Toxic trade breakdown | ✅ Production |
| **Feature Analyzer** | `feature_analyzer.py` | Mutual info, monotonicity, correlation | ✅ Production |
| **Feature Importance** | `m01_trainer.py:731` | XGBoost gain-based importance | ✅ Production |
| **M03Evaluator** | `m03_evaluator.py` | Regime classifier evaluation | ✅ Production |

### ❌ Missing for Classification Models

| Component | Needed For | Status |
|-----------|------------|--------|
| **MultiClass Evaluator** | M04 MFE Classifier | ❌ Missing |
| **Confusion Matrix Analysis** | Classification quality | ❌ Missing |
| **Class-wise Metrics** | Per-class precision/recall/F1 | ❌ Missing |
| **SHAP Integration** | Feature importance + directionality | ❌ Missing |
| **ROC/PR Curves** | Threshold-independent metrics | ❌ Missing |
| **Calibration Analysis** | Probability calibration (Brier score) | ❌ Missing |
| **Temporal Split Validation** | Prevent leakage in train/test split | ⚠️ Ad-hoc (not enforced) |

---

## 2. Data Leakage Issue - Root Cause Analysis

### Problem: `v_d2_training` View Design

**Current View Logic**:
```sql
WITH outcomes AS (
    SELECT
        trade_id,
        MIN(low) AS mae_pct,        -- ❌ FUTURE DATA (lowest point in trade)
        MAX(high) AS mfe_pct,        -- ❌ FUTURE DATA (highest point in trade)
        LAST(close) AS return_at_exit -- ❌ FUTURE DATA (final exit price)
    FROM v_d2r_hydrated              -- ❌ Contains entire trade horizon
    GROUP BY trade_id
)
SELECT f.*, o.mfe_pct, o.mae_pct, ...
FROM v_d2_features f
JOIN outcomes o ON f.trade_id = o.trade_id
```

**Why This Causes Leakage**:
1. `v_d2r_hydrated` contains **all future days** of a trade (entry → exit)
2. `MIN(low)` and `MAX(high)` are computed **across the entire future**
3. These values are joined to features **at entry date** (`f.date`)
4. Model sees: "On 2024-01-15, ticker XYZ will reach +120% MFE"

**Evidence from Database**:
```python
# Sample row from v_d2_training:
# entry_date = 2024-12-30, mfe_pct = 115.38%
# This means: On Dec 30, model knows the trade will gain 115%
```

---

## 3. Evaluation Components - Detailed Gap Analysis

### 3.1 What We Have (Regression - M01)

**From `src/evaluation/m01_evaluator.py`**:
- ✅ Information Coefficient (IC) - Spearman rank correlation
- ✅ Precision@K / Recall@K - Top-K selection quality
- ✅ Decile Lift - Top decile vs mean
- ✅ Edge Metrics - Selection edge, Top2 edge
- ✅ RMSE/MAE - Regression error
- ✅ Volatility Correlation - Does model predict volatility?
- ✅ Walk-forward validation - Temporal folds
- ✅ Error analysis - FOMO (missed) vs Toxic (wrong)

**From `src/pipeline/m01_trainer.py`**:
- ✅ Feature importance (XGBoost gain)
- ✅ Feature importance CSV export
- ✅ Cumulative gain percentage
- ✅ Rank order

**From `src/evaluation/feature_analyzer.py`**:
- ✅ Mutual Information (non-linear relationships)
- ✅ Decile Monotonicity - Signal shape analysis
- ✅ Correlation Analysis

### 3.2 What We Need (Classification - M04)

**Missing Components for Multi-Class Evaluation**:

1. **Confusion Matrix Visualization** ❌
   - Heatmap with percentages
   - Per-class error breakdown
   - Misclassification patterns

2. **Class-Wise Metrics** ❌
   - Precision/Recall/F1 per class
   - Support (sample count) per class
   - Weighted vs Macro averages

3. **SHAP Integration** ❌
   - Tree explainer for XGBoost
   - Summary plot (bar + beeswarm)
   - Per-class feature importance
   - Direction of impact (high feature → high class probability)

4. **Probability Calibration** ❌
   - Reliability diagrams
   - Brier score (calibration quality)
   - Expected Calibration Error (ECE)

5. **ROC/PR Curves** ❌ (Multi-class)
   - One-vs-Rest ROC curves
   - PR curves for imbalanced classes
   - AUC scores per class

6. **Temporal Split Enforcement** ⚠️ (Ad-hoc, not enforced)
   - Chronological train/test split
   - No data leakage validation
   - Date range tracking in metadata

7. **Training Metadata** ✅ Partial (exists in M01, not standardized)
   - Train/val/test date ranges
   - Sample counts per split
   - Class distribution per split
   - Feature list used

---

## 4. Proposed Solution - Unified Evaluation Framework

### 4.1 Design Philosophy

**Principles**:
1. **Leakage Prevention First** - Temporal splits enforced at framework level
2. **Model Registry Integration** - All evaluations saved to DuckDB `models` table
3. **Reusable Components** - Shared base class for regression/classification
4. **Standardized Outputs** - Consistent folder structure, JSON + MD reports
5. **Visualization Consistency** - Matplotlib + Seaborn, saved as PNG/SVG

### 4.2 Proposed Architecture

```
src/evaluation/
├── base_evaluator.py          # BaseEvaluator (abstract class)
├── regression_evaluator.py    # M01Evaluator (existing, refactored)
├── classification_evaluator.py # NEW - M04Evaluator (multi-class)
├── metrics.py                  # Shared metrics (IC, Lift, etc.)
├── plotting.py                 # NEW - Visualization library
└── leakage_guard.py            # NEW - Temporal split validator
```

### 4.3 Base Evaluator Interface

```python
class BaseEvaluator(ABC):
    """Abstract base for all model evaluators."""

    def __init__(self, model_name: str, model_version: str, output_dir: Path):
        self.model_name = model_name
        self.model_version = model_version
        self.output_dir = output_dir / model_name / model_version
        self.registry = ModelRegistry()

    @abstractmethod
    def evaluate(self, X_test, y_test, **kwargs) -> Dict:
        """Core evaluation logic (model-specific)."""
        pass

    def save_results(self, metrics: Dict, plots: Dict[str, Path]):
        """Save metrics to JSON + register in DuckDB."""
        # 1. Save JSON
        metrics_path = self.output_dir / 'evaluation_results.json'

        # 2. Register in models table
        self.registry.update_metrics(self.model_version, **metrics)

        # 3. Generate markdown report
        report_path = self.generate_report(metrics, plots)

    @abstractmethod
    def generate_report(self, metrics: Dict, plots: Dict) -> Path:
        """Generate markdown scorecard (model-specific)."""
        pass
```

### 4.4 Classification Evaluator (M04)

```python
class ClassificationEvaluator(BaseEvaluator):
    """Multi-class classification evaluator with SHAP."""

    def evaluate(
        self,
        model: xgb.Booster,
        X_test: pd.DataFrame,
        y_test: pd.Series,
        feature_names: List[str],
        class_names: List[str] = None
    ) -> Dict:
        """
        Comprehensive classification evaluation.

        Returns:
            metrics: {
                'accuracy': float,
                'weighted_f1': float,
                'macro_f1': float,
                'confusion_matrix': ndarray,
                'classification_report': dict,
                'feature_importance': DataFrame,
                'shap_values': ndarray,
                'class_metrics': {0: {...}, 1: {...}, ...}
            }
        """
        # 1. Predictions
        y_pred_proba = model.predict(xgb.DMatrix(X_test))
        y_pred = np.argmax(y_pred_proba, axis=1)

        # 2. Basic metrics
        accuracy = accuracy_score(y_test, y_pred)
        f1_weighted = f1_score(y_test, y_pred, average='weighted')
        f1_macro = f1_score(y_test, y_pred, average='macro')
        cm = confusion_matrix(y_test, y_pred)

        # 3. Classification report (per-class)
        report = classification_report(y_test, y_pred, output_dict=True)

        # 4. Feature importance (XGBoost gain)
        importance_df = self._get_feature_importance(model, feature_names)

        # 5. SHAP analysis
        shap_values = self._compute_shap(model, X_test)

        # 6. ROC/PR curves (one-vs-rest)
        roc_auc = self._compute_multiclass_roc(y_test, y_pred_proba)

        # 7. Calibration (Brier score)
        brier_score = self._compute_brier_score(y_test, y_pred_proba)

        return {
            'accuracy': accuracy,
            'weighted_f1': f1_weighted,
            'macro_f1': f1_macro,
            'confusion_matrix': cm.tolist(),
            'classification_report': report,
            'feature_importance': importance_df,
            'shap_values': shap_values,
            'roc_auc': roc_auc,
            'brier_score': brier_score
        }

    def _compute_shap(self, model, X_test) -> Dict:
        """SHAP tree explainer for XGBoost."""
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X_test)

        # Save plots
        self._plot_shap_summary(shap_values, X_test)  # Bar + Beeswarm

        return {
            'shap_values': shap_values,  # Per-class
            'shap_base_value': explainer.expected_value
        }
```

### 4.5 Visualization Library (`plotting.py`)

```python
class EvaluationPlotter:
    """Standardized plotting for model evaluation."""

    @staticmethod
    def plot_confusion_matrix(cm: np.ndarray, class_names: List[str], output_path: Path):
        """Confusion matrix heatmap with percentages."""
        fig, ax = plt.subplots(figsize=(8, 6))
        sns.heatmap(cm, annot=True, fmt='d', cmap='Blues',
                    xticklabels=class_names, yticklabels=class_names)
        plt.xlabel('Predicted')
        plt.ylabel('Actual')
        plt.title('Confusion Matrix')
        plt.tight_layout()
        plt.savefig(output_path, dpi=150)
        plt.close()

    @staticmethod
    def plot_feature_importance(importance_df: pd.DataFrame, output_path: Path, top_n=20):
        """Feature importance bar plot."""
        fig, ax = plt.subplots(figsize=(10, 8))
        top_features = importance_df.head(top_n)
        ax.barh(range(len(top_features)), top_features['gain'])
        ax.set_yticks(range(len(top_features)))
        ax.set_yticklabels(top_features['feature'])
        ax.invert_yaxis()
        ax.set_xlabel('Gain')
        ax.set_title(f'Top {top_n} Feature Importance')
        plt.tight_layout()
        plt.savefig(output_path, dpi=150)
        plt.close()

    @staticmethod
    def plot_shap_summary(shap_values, X_test, class_idx: int, output_path: Path):
        """SHAP summary plot for single class."""
        # Bar plot (importance)
        fig1 = plt.figure(figsize=(10, 6))
        shap.summary_plot(shap_values[class_idx], X_test, plot_type='bar', show=False)
        plt.tight_layout()
        plt.savefig(output_path.replace('.png', '_bar.png'), dpi=150)
        plt.close()

        # Beeswarm plot (directionality)
        fig2 = plt.figure(figsize=(10, 8))
        shap.summary_plot(shap_values[class_idx], X_test, plot_type='dot', show=False)
        plt.tight_layout()
        plt.savefig(output_path.replace('.png', '_beeswarm.png'), dpi=150)
        plt.close()
```

### 4.6 Leakage Guard (`leakage_guard.py`)

```python
class LeakageGuard:
    """Prevent temporal leakage in train/test splits."""

    @staticmethod
    def validate_temporal_split(
        df: pd.DataFrame,
        date_col: str,
        train_indices: np.ndarray,
        test_indices: np.ndarray
    ) -> Dict:
        """
        Ensure no test data appears before train data.

        Returns:
            {
                'is_valid': bool,
                'train_date_range': (min, max),
                'test_date_range': (min, max),
                'overlap': bool,
                'leakage_rows': int
            }
        """
        train_dates = df.iloc[train_indices][date_col]
        test_dates = df.iloc[test_indices][date_col]

        train_max = train_dates.max()
        test_min = test_dates.min()

        # Check for leakage: any test date before train max?
        leakage_mask = test_dates < train_max
        leakage_count = leakage_mask.sum()

        return {
            'is_valid': leakage_count == 0,
            'train_date_range': (train_dates.min(), train_dates.max()),
            'test_date_range': (test_dates.min(), test_dates.max()),
            'overlap': test_min < train_max,
            'leakage_rows': int(leakage_count)
        }
```

---

## 5. Proposed Folder Structure

```
models/
├── m04_baseline/
│   ├── model.json                          # XGBoost model
│   ├── metadata.json                       # Training config
│   ├── evaluation/
│   │   ├── results.json                    # Metrics JSON
│   │   ├── report.md                       # Scorecard
│   │   ├── confusion_matrix.png
│   │   ├── feature_importance.png
│   │   ├── shap_class_0_bar.png
│   │   ├── shap_class_0_beeswarm.png
│   │   ├── shap_class_3_bar.png
│   │   ├── shap_class_3_beeswarm.png
│   │   ├── roc_curve_multiclass.png
│   │   ├── pr_curve_multiclass.png
│   │   └── calibration_curve.png
│   └── feature_importance.csv              # Legacy (from trainer)
```

---

## 6. Implementation Plan

### Phase 1: Fix Data Leakage (CRITICAL)
1. ❌ **DO NOT USE `v_d2_training` for MFE prediction** - view is contaminated
2. ✅ Create new view `v_training_clean` that:
   - Uses `v_d1_candidates` (entry date features only)
   - Joins `trade_outcomes` table (exit outcomes) ONLY if used for **labeling after-the-fact**
   - **Never** includes MFE/MAE in feature set
3. ✅ Re-train M04 with clean features (expect ~25-30% accuracy baseline)

### Phase 2: Build Classification Evaluator
1. Create `src/evaluation/classification_evaluator.py`
2. Create `src/evaluation/plotting.py`
3. Create `src/evaluation/leakage_guard.py`
4. Refactor `m01_evaluator.py` to inherit from `BaseEvaluator`

### Phase 3: Update Model Training Scripts
1. Integrate `ClassificationEvaluator` into `scripts/train_mfe_classifier.py`
2. Add SHAP analysis
3. Add confusion matrix visualization
4. Add temporal split validation

### Phase 4: Standardize Model Registry
1. Add `evaluation_results_path` column to `models` table
2. Store JSON path reference instead of inline metrics
3. Update `ModelRegistry.update_metrics()` to accept classification metrics

---

## 7. Components to Keep vs Remove

| Component | Keep? | Reason |
|-----------|-------|--------|
| **Feature Importance (XGBoost gain)** | ✅ Keep | Standard for tree models |
| **Mutual Information** | ✅ Keep | Captures non-linear relationships |
| **SHAP** | ✅ Add | Directional feature impact |
| **Confusion Matrix** | ✅ Add | Essential for classification |
| **ROC/PR Curves** | ✅ Add | Threshold-independent metrics |
| **Calibration Analysis** | ⚠️ Optional | Nice-to-have for probability models |
| **IC (Spearman)** | ❌ Remove | Only for regression/ranking |
| **RMSE/MAE** | ❌ Remove | Only for regression |
| **Decile Lift** | ❌ Remove | Regression-specific |
| **Error Analysis (FOMO/Toxic)** | ⚠️ Adapt | Rename to "False Positive/Negative" |

---

## 8. Next Steps

### Option A: Fix Leakage + Quick Eval (2-3 hours)
1. Create `v_training_clean` view (exclude MFE/MAE)
2. Re-run `train_mfe_classifier.py` with clean data
3. Add SHAP to existing script (quick integration)

### Option B: Build Full Framework (6-8 hours)
1. Implement `BaseEvaluator`, `ClassificationEvaluator`, `EvaluationPlotter`
2. Integrate with ModelRegistry
3. Update all training scripts (M01, M04)

### Option C: Hybrid (4-5 hours)
1. Fix leakage first (Option A)
2. Create standalone `evaluate_classifier.py` script (not refactored framework)
3. Defer full framework to later

---

## 9. Recommended Action

**Immediate**: Option A (Fix leakage + Quick eval)
**Next Sprint**: Option B (Full framework) - enables M05, M06, etc.

**Rationale**:
- Leakage makes current M04 results meaningless → fix first
- Quick SHAP integration validates model learns legitimate patterns
- Full framework is investment for future models (not urgent)
