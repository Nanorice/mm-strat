# EDA & Analytics Pipeline Design Review

> **Date**: 2026-05-17
> **Source**: Review of `notebooks/model_proto.ipynb` and `notebooks/scores_eda.ipynb`
> **Objective**: Summarize exploratory data analysis (EDA) and evaluation techniques used in prototyping, assess their strengths and weaknesses, and define requirements for building a systematic analytics library.

---

## 1. Analytical Elements Performed
To build a systematic analytics pipeline, we need to extract the analytical components currently embedded in the Jupyter notebooks. The analysis performed across both notebooks can be categorized into four core modules:

### A. Feature Introspection (Pre-Modeling)
Techniques used to understand individual feature predictiveness before throwing them into a complex model.
*   **Spearman Rank Information Coefficient (IC)**: Used to measure the monotonic relationship between features and the target variable.
*   **Mutual Information**: Evaluated non-linear dependencies and feature importance.
*   **Multicollinearity Checks**: Correlation matrices to identify redundant features that could destabilize the model or distort SHAP values.

### B. Temporal & Model Evaluation
Techniques used to validate the machine learning model without lookahead bias.
*   **Walk-Forward Validation Setup**: Training on expanding/rolling windows and testing on the immediate out-of-sample (OOS) period.
*   **Walk-Forward Stability Plots**: Tracking performance metrics (e.g., F1, Precision) across time to ensure the model doesn't degrade in certain market conditions.
*   **Calibration Curves (Reliability Diagrams)**: Plotting the predicted probability against the actual outcome frequency to see if a predicted "30% chance of breakout" actually happens 30% of the time.
*   **Aggregate Confusion Matrices**: Summing predictions across all OOS folds to get a global view of false positives vs. true positives.
*   **Feature Importance (SHAP)**: Using Shapley values to explain both global feature importance and local, individual predictions.

### C. Quantitative Strategy Analytics
Techniques used to map model scores to financial reality.
*   **Decile Analysis**: Grouping predictions into 10 buckets (deciles) to verify that higher scores strictly correlate with higher forward returns (monotonicity).
*   **Rolling IC**: Tracking the Spearman IC of the model's predictions over time to see when the model loses edge.
*   **Score Trajectory Analysis**: Tracking how the M01 score evolves *after* the entry day (T+1, T+2, etc.). This is critical for the `M01-Hold` variant.

### D. Regime & Risk Analytics
Techniques used to understand how the macro environment impacts the model.
*   **5-Factor vs. M03 Gating Comparison**: Evaluating how applying different regime filters (the baseline M03 vs the experimental 5-factor risk model) impacts candidate selection and performance.
*   **Exposure vs. Portfolio Correlation**: Tracking how the strategy's equity curve correlates with underlying market factors (e.g., SPY/QQQ returns).

---

## 2. Assessment: What We Did Well

1.  **Strict Avoidance of Lookahead Bias**: Implementing walk-forward validation rather than standard k-fold cross-validation is the absolute correct approach for financial time series.
2.  **Comprehensive Introspection**: Relying on Spearman IC and Mutual Information alongside SHAP provides a highly robust view of feature validity. We aren't treating the XGBoost model as a black box.
3.  **Score Trajectory Analysis**: Moving beyond point-in-time entry predictions to look at *how scores degrade during a hold* is a massive operational leap. This provides the exact foundation needed for the `M01-Hold` model.
4.  **Calibration Focus**: Focusing on probability calibration ensures that the raw scores can be safely used as ranking signals or position sizing inputs, not just binary triggers.

---

## 3. Assessment: What Needs Improvement (The Gaps)

1.  **Lack of Modularity (The Jupyter Trap)**: 
    *   *Issue:* All of these incredible analytics are trapped in monolithic notebook cells. 
    *   *Fix:* We need to refactor these into a standalone `src/evaluation/` or `src/analytics/` library so they can be called systematically during nightly pipeline runs or hyperparameter sweeps.
2.  **Missing Automated Data Quality Gates**:
    *   *Issue:* The notebooks have placeholder sections like `"Address Missing Values - need to fix dist_from_20d_high_delta"`. The EDA assumes relatively clean data.
    *   *Fix:* The analytics pipeline must begin with a strict data audit module that flags NaNs, infinite values, or zero-variance columns *before* attempting to calculate IC or SHAP.
3.  **Ambiguous Target Definitions for Variants**:
    *   *Issue:* While the current setup evaluates the breakout day well, the targets for `M01-Watch` (pre-breakout) and `M01-Hold` (post-breakout monitoring) are not formalized in the data prep steps.
    *   *Fix:* Create explicit label generators in the pipeline for `breakout_within_5d` and `sl_hit_within_K_days`.
4.  **Manual Regime Evaluation**:
    *   *Issue:* The comparison between 5-Factor and M03 is highly manual. 
    *   *Fix:* We need standard statistical tests (e.g., comparing Sharpe ratios or generating regime-conditional precision/recall metrics automatically) to definitively prove if a regime filter adds alpha.
5.  **No Automated "Tear Sheet"**:
    *   *Issue:* To review a model, someone has to run a notebook.
    *   *Fix:* The pipeline should automatically generate a standard validation report (Markdown or HTML) summarizing IC, Calibration, Walk-Forward stability, and Decile Returns whenever a new model is trained.
