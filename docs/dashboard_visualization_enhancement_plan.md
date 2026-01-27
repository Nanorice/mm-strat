# Dashboard Visualization Enhancement Plan
**Date:** 2026-01-27
**Objective:** Enhance 5 ML report pages with industry-standard visualizations leveraging existing EDA notebook analyses

---

## Executive Summary

### Current State
- **5 Dashboard Reports:** D1 Analysis, M01 Report, M02 Report, Dual-Model, Backtest (placeholder)
- **Data Source:** Pre-generated JSON files (fast loading, no raw parquet)
- **EDA Notebook:** Comprehensive_Model_EDA.ipynb with 4 major sections analyzing trade physics, M01, M02 (M01_3BAR), and portfolio backtesting
- **Current Visualizations:** Matplotlib/Seaborn-based, static, no interactive elements
- **Visualization Library:** Dashboard uses Plotly, notebook uses Matplotlib/Seaborn

### Enhancement Strategy
1. **Port Key Analyses** from EDA notebook to dashboard reports as interactive Plotly visualizations
2. **Add Industry-Standard Metrics** based on ML best practices (2026)
3. **Create Reusable Visualization Library** (`src/viz_library.py`) to avoid code duplication
4. **Enhance Report Generation** in trainer modules to save visualization data to JSON

---

## Industry-Standard ML Evaluation Best Practices (2026)

### Regression Models (M01)
**Essential Visualizations:**
1. **Residual Plots** - Check for bias and heteroscedasticity
2. **Actual vs Predicted Scatter** - Assess prediction accuracy with R² overlay
3. **Decile Performance Charts** - Validate selection edge (top decile outperformance)
4. **Feature Importance Waterfall** - Identify key drivers (using SHAP or XGBoost gain)
5. **Learning Curves** - Detect overfitting (train vs test error over time)
6. **Error Distribution** - Histogram of prediction errors (should be normal, centered at 0)
7. **Q-Q Plot** - Validate normality assumption of residuals

**Sources:**
- [12 Important Model Evaluation Metrics (Analytics Vidhya)](https://www.analyticsvidhya.com/blog/2019/08/11-important-model-evaluation-error-metrics/)
- [Evaluating Machine Learning Models (Jeremy Jordan)](https://www.jeremyjordan.me/evaluating-a-machine-learning-model/)

### Classification Models (M02)
**Essential Visualizations:**
1. **Confusion Matrix** - True/False Positives/Negatives breakdown
2. **ROC Curve + AUC** - Trade-off between TPR and FPR
3. **Precision-Recall Curve** - Critical for imbalanced classes (TP rate: 5.6% vs SL: 61.6%)
4. **Calibration Plot** - Predicted probability vs actual outcomes (reliability)
5. **Class Distribution** - Visualize imbalance (Barrier outcomes: TP/SL/Time)
6. **Feature Importance** - Top features driving ignition probability
7. **Decision Boundary Visualization** - 2D projection of classification space (PCA/t-SNE)
8. **Lift Chart** - Model effectiveness vs random baseline

**Sources:**
- [EDA Prior to Classification Model (Codecademy)](https://www.codecademy.com/article/eda-prior-to-fitting-a-classification-model)
- [Machine Learning Model Evaluation (GeeksforGeeks)](https://www.geeksforgeeks.org/machine-learning-model-evaluation/)

### Trade-Specific Visualizations (Quantitative Finance)
1. **MAE/MFE Scatter Plot** - E-Ratio validation (benchmark >3.0)
2. **Time-to-Peak Distribution** - Optimal holding period analysis
3. **Walk-Forward Performance** - Rolling validation edge over time
4. **Survivor vs Crash Analysis** - Structural stop validation
5. **Equity Curve** - Cumulative PnL with drawdown overlay
6. **Monthly Returns Heatmap** - Seasonality and consistency

---

## Gap Analysis: EDA Notebook vs Dashboard Reports

| Analysis Type | In EDA Notebook? | In Dashboard? | Action Required |
|---------------|------------------|---------------|-----------------|
| **D1: Trade Physics** |
| MAE/MFE Scatter | ✅ (matplotlib) | ❌ | PORT to Plotly |
| E-Ratio Distribution | ✅ (histogram) | ❌ | PORT to Plotly |
| Survivor Analysis | ✅ (complex subplot) | ❌ | PORT + Simplify |
| Time-to-Peak | ✅ (distribution) | ❌ | PORT to Plotly |
| **M01: Regression** |
| Decile Bar Charts | ✅ (bar) | ❌ | PORT to Plotly |
| Actual vs Predicted | ✅ (scatter) | ❌ | PORT to Plotly |
| Feature Importance | ✅ (CSV export) | ✅ (basic bar) | ENHANCE with waterfall |
| Error Analysis (FOMO/Toxic) | ✅ (matrix) | ❌ | PORT to Plotly |
| Residual Plot | ❌ | ❌ | CREATE new |
| Q-Q Plot | ❌ | ❌ | CREATE new |
| **M02: Classification** |
| Confusion Matrix | ❌ | ❌ | CREATE new |
| ROC Curve | ❌ | ❌ | CREATE new |
| Precision-Recall Curve | ❌ | ❌ | CREATE new |
| Calibration Plot | ✅ (line plot) | ❌ | PORT to Plotly |
| Barrier Distribution | ✅ (CSV summary) | ✅ (pie chart) | ENHANCE |
| SHAP Analysis | ✅ (force plot) | ❌ | PORT to Plotly |
| **Dual-Model** |
| Complementarity Analysis | ✅ (scatter) | ❌ | PORT to Plotly |
| Combined Scoring | ✅ (correlation) | ❌ | PORT to Plotly |
| **Backtest** |
| Equity Curve | ✅ (line) | ❌ (placeholder) | PORT to Plotly |
| Monthly Heatmap | ❌ | ❌ | CREATE new |
| Drawdown Analysis | ✅ (line) | ❌ | PORT to Plotly |

**Legend:** ✅ Exists | ❌ Missing | PORT = Port from notebook | CREATE = Build new

---

## Detailed Enhancement Plan by Report

### Report 1: D1 Analysis (Trade Physics)

**Current State:**
- 4 metrics: Total Trades, Median MFE, Median MAE, Median E-Ratio
- 2 metrics: Crash Rate, Survived Rate
- No visualizations

**Enhancements:**

1. **MAE/MFE Scatter Plot** (Priority: HIGH)
   - Source: Section 1.1 of EDA notebook
   - X-axis: MAE (%), Y-axis: MFE (%)
   - Color by: Survivor status
   - Add diagonal E-Ratio lines (1.0, 2.0, 3.0)
   - Annotations: Median MAE, Median MFE, % above E-Ratio 3.0
   - Data source: D2 rehydrated parquet → Save to `models/d1_mae_mfe.json`

2. **E-Ratio Distribution** (Priority: HIGH)
   - Histogram with KDE overlay
   - Vertical line at benchmark (E-Ratio = 3.0)
   - Stats: % above benchmark, median, mean
   - Data source: Same as scatter plot

3. **Time-to-Peak Analysis** (Priority: MEDIUM)
   - Histogram: Days to reach MFE
   - Stats: Median, 75th percentile
   - Insight: Informs optimal holding period
   - Data source: D2R with trajectory analysis

4. **Survivor vs Crash Breakdown** (Priority: LOW)
   - Enhanced pie chart or donut chart
   - Show structural stop level
   - Add MAE distribution for each group

**New JSON Schema:**
```json
{
  "d1_analysis.json": {
    "summary_stats": { ... existing ... },
    "mae_mfe_scatter": [
      {"trade_id": "...", "MAE": -5.2, "MFE": 12.3, "E_Ratio": 2.36, "is_survivor": true},
      ...
    ],
    "e_ratio_distribution": {
      "bins": [0, 0.5, 1.0, ...],
      "counts": [12, 45, ...],
      "pct_above_3": 34.5
    },
    "time_to_peak": {
      "bins": [0, 5, 10, ...],
      "counts": [23, 67, ...]
    }
  }
}
```

---

### Report 2: M01 Report (Return Regressor)

**Current State:**
- Walk-forward table (clean)
- Selection edge bar chart by year
- Feature importance horizontal bar (basic)

**Enhancements:**

1. **Decile Performance Bar Chart** (Priority: HIGH)
   - Source: Section 2.2 of EDA notebook
   - X-axis: Deciles 1-10
   - Y-axis: Mean return %
   - Color: Gradient (red → green)
   - Overlay: Median baseline
   - Data source: Add to `m01_config.json` → `decile_performance`

2. **Actual vs Predicted Scatter** (Priority: HIGH)
   - Source: Section 2.2 of EDA notebook
   - X-axis: Predicted return %
   - Y-axis: Actual return %
   - Add diagonal line (y=x)
   - Color by: Decile rank
   - Stats overlay: R², RMSE
   - Data source: `m01_config.json` → `predictions_sample` (1000 rows max)

3. **Feature Importance Waterfall** (Priority: MEDIUM)
   - Upgrade from horizontal bar
   - Show cumulative contribution
   - Highlight top 80% features
   - Data source: Existing `feature_importance_m01.csv`

4. **Residual Analysis** (Priority: MEDIUM)
   - Subplot: Residuals vs Predicted, Residual histogram
   - Detect bias and heteroscedasticity
   - Data source: Same as scatter plot

5. **Error Matrix: FOMO vs Toxic** (Priority: LOW)
   - Source: Section 2.3 of EDA notebook
   - 2x2 matrix: Predicted High/Low × Actual High/Low
   - Insight: Identify model failure modes
   - Data source: `m01_config.json` → `error_analysis`

**New JSON Schema:**
```json
{
  "m01_config.json": {
    ... existing ...
    "decile_performance": [
      {"decile": 1, "mean_return": 25.3, "count": 150},
      ...
    ],
    "predictions_sample": [
      {"ticker": "AAPL", "date": "2024-06-15", "y_pred": 15.2, "y_true": 18.7, "decile": 1},
      ...  // Max 1000 rows
    ],
    "error_analysis": {
      "FOMO": {"count": 45, "avg_missed_return": 12.3},  // Predicted low, actual high
      "Toxic": {"count": 67, "avg_loss": -5.6},  // Predicted high, actual low
      "True_Positive": {"count": 120},
      "True_Negative": {"count": 230}
    }
  }
}
```

---

### Report 3: M02 Report (Ignition Classifier)

**Current State:**
- Barrier outcome pie chart (TP/SL/Time)
- Walk-forward table (if trained)

**Enhancements:**

1. **Confusion Matrix** (Priority: HIGH)
   - Source: Standard classification metric (NEW)
   - 2x2 heatmap: TP, FP, TN, FN
   - Annotations: Counts + percentages
   - Data source: `m02_config.json` → `confusion_matrix`

2. **ROC Curve** (Priority: HIGH)
   - Source: Standard classification metric (NEW)
   - Plot TPR vs FPR
   - Add AUC score
   - Diagonal baseline (random classifier)
   - Data source: `m02_config.json` → `roc_curve`

3. **Precision-Recall Curve** (Priority: HIGH)
   - Critical for imbalanced data (TP: 5.6%, SL: 61.6%)
   - Show optimal threshold
   - Data source: `m02_config.json` → `pr_curve`

4. **Calibration Plot** (Priority: HIGH)
   - Source: Section 3.1 of EDA notebook
   - X-axis: Predicted probability bins
   - Y-axis: Actual TP rate
   - Diagonal line (perfect calibration)
   - Insight: Model confidence reliability
   - Data source: `m02_config.json` → `calibration_data`

5. **Barrier Outcome Analysis** (Priority: MEDIUM)
   - Upgrade pie chart to stacked bar by probability decile
   - Show how outcome changes with model score
   - Data source: `m02_config.json` → `outcome_by_decile`

6. **Feature Importance (M02-specific)** (Priority: MEDIUM)
   - Horizontal bar chart (like M01)
   - Velocity features should dominate
   - Data source: Existing `feature_importance_m02.csv`

7. **NPV Analysis (Negative Predictive Value)** (Priority: LOW)
   - Source: Section 3.2 of EDA notebook
   - Validate low scores = reliable crash prediction
   - Bar chart: SL rate by probability bin
   - Data source: `m02_config.json` → `npv_analysis`

**New JSON Schema:**
```json
{
  "m02_config.json": {
    ... existing ...
    "confusion_matrix": {
      "TP": 120, "FP": 450, "TN": 1200, "FN": 30
    },
    "roc_curve": [
      {"threshold": 0.0, "fpr": 1.0, "tpr": 1.0},
      {"threshold": 0.1, "fpr": 0.85, "tpr": 0.95},
      ...
    ],
    "auc": 0.82,
    "pr_curve": [
      {"threshold": 0.0, "precision": 0.05, "recall": 1.0},
      ...
    ],
    "calibration_data": [
      {"prob_bin": "0.0-0.1", "predicted": 0.05, "actual": 0.02, "count": 200},
      ...
    ],
    "outcome_by_decile": [
      {"decile": 1, "TP": 0.12, "SL": 0.50, "Time": 0.38},
      ...
    ],
    "npv_analysis": [
      {"prob_bin": "0.0-0.1", "SL_rate": 0.85, "count": 150},
      ...
    ]
  }
}
```

---

### Report 4: Dual-Model Analysis

**Current State:**
- Side-by-side metrics (M01 avg edge, M02 avg AUC)
- Text description of combined scoring strategy

**Enhancements:**

1. **Complementarity Scatter** (Priority: HIGH)
   - Source: Section 4.5 of EDA notebook
   - X-axis: M01 expected return %
   - Y-axis: M02 ignition probability
   - Color by: Actual outcome (TP, SL, Time)
   - Quadrants: High/High (best), High/Low, Low/High, Low/Low
   - Data source: NEW `models/dual_model_analysis.json`

2. **Combined Score Distribution** (Priority: MEDIUM)
   - Histogram: M01 rank × M02 prob composite score
   - Show filter threshold (e.g., M01_rank ≤ 3 AND M02_prob > 0.5)
   - Stats: % passing filter, avg return of filtered
   - Data source: Same as scatter

3. **Feature Overlap Heatmap** (Priority: LOW)
   - Correlation heatmap: M01 features vs M02 features
   - Identify redundant vs complementary features
   - Data source: Feature importance correlation

4. **Signal Agreement Analysis** (Priority: LOW)
   - 2x2 matrix: M01 top decile × M02 top decile
   - Insight: How often do models agree?
   - Data source: `dual_model_analysis.json` → `agreement_matrix`

**New JSON Schema:**
```json
{
  "dual_model_analysis.json": {
    "complementarity_scatter": [
      {"ticker": "AAPL", "date": "2024-06-15", "m01_pred": 18.5, "m02_prob": 0.72, "outcome": "TP", "actual_return": 22.3},
      ...  // Max 1000 rows
    ],
    "agreement_matrix": {
      "both_high": {"count": 45, "avg_return": 28.5, "TP_rate": 0.35},
      "m01_high_m02_low": {"count": 78, "avg_return": 12.3, "TP_rate": 0.08},
      "m01_low_m02_high": {"count": 62, "avg_return": 8.7, "TP_rate": 0.15},
      "both_low": {"count": 340, "avg_return": -2.1, "TP_rate": 0.02}
    },
    "filter_performance": {
      "threshold": {"m01_rank": 3, "m02_prob": 0.5},
      "passing_count": 67,
      "avg_return": 22.8,
      "TP_rate": 0.28
    }
  }
}
```

---

### Report 5: Backtest (Currently Placeholder)

**Current State:**
- Placeholder page with planned features

**Enhancements:**

1. **Equity Curve** (Priority: HIGH)
   - Source: Section 4.6 of EDA notebook
   - Line chart: Cumulative PnL over time
   - Overlay: Drawdown shading
   - Benchmark: Buy-and-hold SPY
   - Data source: NEW `models/backtest_results.json`

2. **Monthly Returns Heatmap** (Priority: HIGH)
   - Rows: Years, Columns: Months
   - Color scale: Red (loss) → Green (gain)
   - Total row/column for aggregates
   - Data source: Same as equity curve

3. **Performance Metrics Panel** (Priority: HIGH)
   - Total return, CAGR, Sharpe ratio, Max drawdown
   - Win rate, profit factor, avg win/loss
   - Data source: `backtest_results.json` → `summary_metrics`

4. **Trade Distribution Analysis** (Priority: MEDIUM)
   - Histogram: Return % per trade
   - Stats overlay: Mean, median, std dev
   - Insight: Validate edge distribution
   - Data source: `backtest_results.json` → `trade_returns`

5. **Position Heatmap** (Priority: LOW)
   - Source: Section 4.4 of EDA notebook
   - Visualize portfolio composition over time
   - Y-axis: Tickers, X-axis: Date
   - Color: Position size
   - Data source: `backtest_results.json` → `position_history`

**New JSON Schema:**
```json
{
  "backtest_results.json": {
    "summary_metrics": {
      "total_return": 0.85,
      "cagr": 0.12,
      "sharpe_ratio": 1.45,
      "max_drawdown": -0.18,
      "win_rate": 0.58,
      "profit_factor": 2.1,
      "total_trades": 234
    },
    "equity_curve": [
      {"date": "2020-01-15", "portfolio_value": 100000, "drawdown": 0.0},
      ...
    ],
    "monthly_returns": [
      {"year": 2020, "month": 1, "return": 0.03},
      ...
    ],
    "trade_returns": [
      {"ticker": "AAPL", "entry_date": "2020-01-15", "exit_date": "2020-02-10", "return": 0.18},
      ...
    ],
    "position_history": [
      {"date": "2020-01-15", "positions": {"AAPL": 100, "MSFT": 50}},
      ...
    ]
  }
}
```

---

## Implementation Architecture

### 1. Reusable Visualization Library (`src/viz_library.py`)

**Purpose:** Centralize all Plotly visualization functions to avoid duplication

**Structure:**
```python
# src/viz_library.py
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from typing import Dict, List, Optional

# ============================================================================
# D1 ANALYSIS VISUALIZATIONS
# ============================================================================

def create_mae_mfe_scatter(data: List[Dict]) -> go.Figure:
    """MAE/MFE scatter plot with E-Ratio lines."""
    ...

def create_e_ratio_histogram(data: List[float], benchmark: float = 3.0) -> go.Figure:
    """E-Ratio distribution with benchmark line."""
    ...

# ============================================================================
# M01 VISUALIZATIONS (REGRESSION)
# ============================================================================

def create_decile_bar_chart(decile_data: List[Dict]) -> go.Figure:
    """Decile performance bar chart."""
    ...

def create_actual_vs_predicted_scatter(predictions: List[Dict]) -> go.Figure:
    """Actual vs predicted scatter with R² overlay."""
    ...

def create_feature_importance_waterfall(importance_df: pd.DataFrame, top_n: int = 20) -> go.Figure:
    """Feature importance waterfall chart."""
    ...

def create_residual_plot(predictions: List[Dict]) -> go.Figure:
    """Residuals vs predicted values."""
    ...

# ============================================================================
# M02 VISUALIZATIONS (CLASSIFICATION)
# ============================================================================

def create_confusion_matrix(cm_data: Dict) -> go.Figure:
    """Confusion matrix heatmap."""
    ...

def create_roc_curve(roc_data: List[Dict], auc: float) -> go.Figure:
    """ROC curve with AUC score."""
    ...

def create_precision_recall_curve(pr_data: List[Dict]) -> go.Figure:
    """Precision-Recall curve."""
    ...

def create_calibration_plot(calibration_data: List[Dict]) -> go.Figure:
    """Calibration plot (predicted vs actual)."""
    ...

# ============================================================================
# DUAL-MODEL VISUALIZATIONS
# ============================================================================

def create_complementarity_scatter(dual_data: List[Dict]) -> go.Figure:
    """M01 vs M02 scatter colored by outcome."""
    ...

# ============================================================================
# BACKTEST VISUALIZATIONS
# ============================================================================

def create_equity_curve(equity_data: List[Dict]) -> go.Figure:
    """Equity curve with drawdown shading."""
    ...

def create_monthly_returns_heatmap(monthly_data: List[Dict]) -> go.Figure:
    """Monthly returns heatmap."""
    ...
```

### 2. Enhanced Report Generation in Trainer Modules

**Modify:**
- `src/pipeline/m01_trainer.py` → `generate_report()` method
- `src/pipeline/m02_trainer.py` → `generate_report()` method

**Add:**
- Calculate visualization-specific data during walk-forward validation
- Save to JSON in addition to markdown report

**Example (M01):**
```python
# src/pipeline/m01_trainer.py

def generate_report(self, model, metrics_df, start_date, end_date):
    """Enhanced report generation with visualization data."""

    # Existing markdown report generation
    report_path = self._generate_markdown_report(...)

    # NEW: Generate visualization data
    viz_data = {
        'decile_performance': self._calculate_decile_performance(),
        'predictions_sample': self._sample_predictions(max_rows=1000),
        'error_analysis': self._analyze_errors(),
        'residuals': self._calculate_residuals()
    }

    # Save to m01_config.json
    config_path = self.output_dir / 'm01_config.json'
    config = json.load(open(config_path)) if config_path.exists() else {}
    config.update(viz_data)

    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

    return report_path
```

### 3. Enhanced Dashboard Report Functions

**Modify:**
- `src/dashboard_reports.py` → All 5 render functions

**Pattern:**
1. Load JSON data (existing)
2. Import `viz_library` functions
3. Create Plotly figures
4. Display with `st.plotly_chart()`

**Example (D1 Analysis):**
```python
# src/dashboard_reports.py

from src.viz_library import create_mae_mfe_scatter, create_e_ratio_histogram

def render_d1_analysis():
    """Enhanced D1 Analysis with MAE/MFE visualizations."""

    # Load data
    d1_report = load_d1_report()

    # Existing metrics
    st.metric("Median MFE", f"{d1_report['median_mfe']:.1f}%")
    ...

    # NEW: MAE/MFE Scatter
    if 'mae_mfe_scatter' in d1_report:
        st.markdown("### MAE/MFE Analysis")
        fig = create_mae_mfe_scatter(d1_report['mae_mfe_scatter'])
        st.plotly_chart(fig, use_container_width=True)

    # NEW: E-Ratio Distribution
    if 'e_ratio_distribution' in d1_report:
        st.markdown("### E-Ratio Distribution")
        fig = create_e_ratio_histogram(
            d1_report['e_ratio_distribution']['data'],
            benchmark=3.0
        )
        st.plotly_chart(fig, use_container_width=True)
```

---

## Implementation Phases

### Phase 1: Foundation (2-3 hours)
1. Create `src/viz_library.py` with stub functions
2. Update trainer modules to save visualization data to JSON
3. Test data generation with existing models

### Phase 2: D1 + M01 Enhancements (3-4 hours)
1. Implement D1 visualizations (MAE/MFE, E-Ratio)
2. Implement M01 visualizations (Decile, Actual vs Predicted, Waterfall)
3. Update `render_d1_analysis()` and `render_m01_report()`

### Phase 3: M02 Enhancements (3-4 hours)
1. Implement M02 visualizations (Confusion Matrix, ROC, PR Curve, Calibration)
2. Update `render_m02_report()`

### Phase 4: Dual-Model + Backtest (2-3 hours)
1. Implement Dual-Model visualizations (Complementarity Scatter)
2. Implement Backtest visualizations (Equity Curve, Monthly Heatmap)
3. Update `render_dual_model()` and `render_backtest()`

**Total Estimated Time:** 10-14 hours

---

## Success Criteria

### Functional Requirements
- [ ] All 5 reports load in <2 seconds (JSON-based, no raw parquet)
- [ ] All visualizations are interactive (Plotly hover, zoom, pan)
- [ ] Visualizations update when models are retrained
- [ ] No code duplication (reusable viz_library)

### Quality Requirements
- [ ] Visualizations follow industry-standard ML practices
- [ ] Each chart has clear title, axis labels, and tooltips
- [ ] Color schemes are consistent and accessible
- [ ] Mobile-responsive layout (Streamlit default)

### User Value
- [ ] Users can identify model strengths/weaknesses at a glance
- [ ] Users can debug model failures (FOMO/Toxic errors, calibration issues)
- [ ] Users can validate trade viability (E-Ratio, survivor analysis)
- [ ] Users can optimize strategy (decile analysis, dual-model complementarity)

---

## References

### Industry Standards
- [12 Important Model Evaluation Metrics (Analytics Vidhya)](https://www.analyticsvidhya.com/blog/2019/08/11-important-model-evaluation-error-metrics/)
- [A Holistic Guide to EDA (Medium)](https://medium.com/@post.gourang/a-holistic-guide-to-exploratory-data-analysis-eda-for-machine-learning-and-deep-learning-bc4f18f0143b)
- [Evaluating Machine Learning Models (Jeremy Jordan)](https://www.jeremyjordan.me/evaluating-a-machine-learning-model/)
- [ML Model Evaluation and Selection (Neptune.ai)](https://neptune.ai/blog/ml-model-evaluation-and-selection)

### Internal Documentation
- `docs/session_logs/2026-01-26_handover.md` - Project context
- `notebooks/Comprehensive_Model_EDA.ipynb` - Source of visualizations
- `src/dashboard_reports.py` - Current dashboard implementation
- `src/pipeline/m01_trainer.py` - M01 report generation
- `src/pipeline/m02_trainer.py` - M02 report generation

---

**Next Action:** Review plan with user, get approval, then proceed to Phase 1 implementation.
