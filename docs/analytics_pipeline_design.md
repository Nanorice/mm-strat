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


# My Summary:

## Model Prototype:
1. the purpose of this notebook is to explore the methodology to develop a new model, thus m01_baseline -> m01_prototype. 
2. a one off part of this script is some editing on features. 
3. What we have in feature engineering and EDA:
    - features used in model, vs available features
    - added EMA features (now already in pipeline)
    - converted momentum features to slopes
    - converted SMA to ratios
    - starting portion of the training set have major missing data, due to warm up period, so need to first verify if this is indeed warm up, then find the length, and clip it.
    - remove raw price data, leakage cols, and metadata cols
    - check for missing data. ok if majority is from fundamentals, as some companies may not have inventories for example. but we need to have a reporting section on this. any price derived cols we need to make sure there's no missing. Then we visualise the null rate plot. A pending point to address is dist_from_20d_high_delta.
    - target distribution. depending on what model we want to train later, we have different targets. in the example of prototype, we are using snapshot set up data. target being classification based on MFE during holding. here we visualise MFE distribution, class distribution, and holding days density by MFE class. Finding being for better performing stocks we tend to hold longer. There can also be large drawdowns for superperformers. As verified in the other notebook with EDA on dense data, there tend to be a pull back after breakout, so for a better entry either we can predict the breakout, or can be cautious and wait for a potential pullback
4. Statistical EDA:
    - spearman IC
    - mutual info
    - multicollinearity - with manual and systematic trim of features for features selection
5. modelling (we have a established code for this, but worth checking if we have any analytics missing there in the report. also we need to think about if we should include model evaluation in this module or in a new one):
    - walk-forward validation
    - WF XGboost
    - WF stability plot + per-class F1 across folds (relatively stable prediction?)
    - aggregate confusion matrix
    - train prod model using all data. (missing a full evaluation comparison against current model. also the testing stats is a bit invalud given leakage. we should think of a way of leaving 1-2 years for testing, and update both prod and dev model to train on this and then compare apple to apple)
    - OOS performance
    - feature importance
    - predicted probability vs actual outcome -> calibration curves per class

## scores eda
1. this is an eda on scores df, with dense scores and price data for all tickers in sepa watchlist across history. This should be the bbedrock for model training going forward. I know v_d2_training is used for model training of current prod, but we need to make sure it comes from clean data.
2. what we have
    - data audit: null %, bad ticker (with abnormal 1d return calculated, need to check)
    - NOTE: it's important to feedback these finding on data quality back to the pipeline. we should address them early in the loop
    - EDA:
        * score/class distribution
        * rolling IC (identifies regime, say 2019-2021 high and rising IC, 22-23 IC collapses, 24-26 IC recovers but noisier)
        * decile table: Bucket prob_elite into 10 deciles. Compute mean return per decile. With sense check on the most extreme events for data quality issue.
        * (empty) load benchmark data for excess return, then Demean by the daily cross-sectional average = removes market beta
        * Confirmed monotonicity across deciles, then find the threshold of score to use based on decile. and also confirm monotonicity of score vs performance within deciles. i.e. Within Decile 9 — Is Higher Score Better? then What are the actual prob_elite boundaries for each sub-quintile?
        * explore regime gating
        * score trajectory analysis - how scores evolve -> Rising score is the dominant entry signal
        * testing out strategy. (level + rising score + consecutive days)
        * risk management: m03 vs 5-risk-factor. not completed yet, need to systematically evaulate based on major benchmarks. I.e. is these metrics predicting large market vol and pull back? can we combine them to improve performance?
