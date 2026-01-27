# M01 Evaluation Framework & Target Engineering Upgrade

**Document Type:** Architecture Proposal
**Status:** Draft
**Date:** 2026-01-27

---

## 1. Current State ("What We Have")

The current M01 model is an **XGBoost Regressor** designed to predict the expected return of SEPA trade candidates. While the infrastructure is stable, the learning objective and evaluation methods have critical theoretical gaps.

### The "Survivor Only" Limitation
Currently, the model runs in a "Survivor Mode" where:
* **Filtering:** Trades that hit a structural stop (e.g., > 2x ATR loss) are removed from the training set.
* **Target:** The model trains on `y_max` (Maximum Favorable Excursion) only for the survivors.

### The Risks
1.  **Survivorship Bias:** By removing losers, the model learns "conditional upside" (how high it goes *if* it doesn't crash). It fails to penalize volatile setups that frequently crash.
2.  **Mediocrity Learning:** The majority of "survivors" are actually flat/mediocre trades (e.g., +2% gain). Training on raw MFE forces the model to treat these similarly to massive winners, diluting the signal of Super Performers.
3.  **Evaluation Gap:** The current reporting provides basic regression metrics (RMSE) but lacks systematic testing for ranking capability or volatility bias.

---

## 2. Objective ("What We Want to Build")

We are moving from a simple regression reporter to a **Systematic Ranking Scorecard**. This involves formalizing the target options and running a comparative study.

### A. Target Label Candidates (The Options)
We will systematically generate and evaluate the following four target definitions to determine which signal best identifies super-performers without overfitting to volatility:

* **Option A (Baseline): Survivor MFE**
    * *Definition:* `y = MFE` (Calculated only on trades that did not hit the structural stop).
    * *Status:* Current production default.
    * *Role:* Control group for survivorship bias.

* **Option B: Hybrid Floor (Capped Loser)**
    * *Definition:*
        * If Winner: `y = MFE`
        * If Loser (hit stop): `y = max(-10%, -2 * ATR)`
    * *Hypothesis:* Provides a "soft penalty" for crashing, preventing the model from seeing -50% gaps (which might be noise) while still penalizing failure.

* **Option C: Risk-Adjusted (Volatility Normalization)**
    * *Definition:* `y = MFE / ATR_entry`
    * *Hypothesis:* Normalizes the target to "R-multiples." This penalizes high-volatility stocks that move fast but don't effectively cover their risk, preventing the model from becoming a "volatility detector."

* **Option D: Log-Space (Tail Smoothing)**
    * *Definition:* `y = log(1 + MFE)`
    * *Hypothesis:* Compresses massive outliers (e.g., +200% runners) so they don't dominate the loss function, while still preserving their rank order against mediocre trades.

### B. The Scorecard Infra (The Evaluator)
We will build a `ModelEvaluator` class that generates a "Scorecard" for every model run. This scorecard prioritizes **Ranking Quality** over Point Accuracy.

**Key Metrics to Monitor:**
1.  **Information Coefficient (IC):** Spearman rank correlation between Predicted Rank and Realized Rank.
2.  **Top Decile Lift:** How much better is the Top 10% compared to the average trade?
3.  **Precision@K:** What % of the actual top 5% Super Performers did the model capture in its top decile?
4.  **Volatility Correlation Check:** The "Vol Detector" test. Does the model just output high scores for high ATR stocks? (Target: Low correlation).

### C. The Comparison Step (The Decision)
After implementing the Scorecard Infra, we will run an **Ablation Study**:
1.  Train four separate models (M01_A, M01_B, M01_C, M01_D) on the same historical D2 dataset.
2.  Pass all four models through the `ModelEvaluator` using the Walk-Forward validation logic.
3.  **Select the Winner:** The final production target will be chosen based on which Option yields the highest **IC** and **Lift** while maintaining a low **Volatility Correlation**.

---

## 3. Rationale ("Why")

### 1. Ranking > Regression
In trading, we do not care if the model predicts a 15.2% return and the reality is 18.5% (high RMSE error). We only care that it ranks the 100% winner *above* the 5% winner. Shifting focus to Ranking Metrics (IC, Lift) aligns the ML objective with the P&L objective.

### 2. Solving the "Vol Detector" Trap
A common failure mode for "Upside Predictors" is that they simply learn to identify high-beta/high-volatility stocks.
* **Scenario:** High vol stocks move a lot (both up and down). If we filter out the "down" moves (Survivor Bias), the model thinks High Vol = Free Money.
* **Result:** The model buys risky stocks in a bear market and suffers massive drawdowns.
* **Fix:** Comparing Option C (Risk-Adjusted) against Option A allows us to explicitly measure if normalizing for risk creates a more robust signal.

### 3. Data Integrity
Filtering out losers (Option A) is theoretically unsound for a ranking model. The model must learn what a "bad trade" looks like to effectively down-rank it. Options B and D reintroduce the losers into the dataset with specific transformations to handle their negative signal appropriately.