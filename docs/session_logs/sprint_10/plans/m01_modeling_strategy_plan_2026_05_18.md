# M01 Modeling and Strategy Plan
Date: 2026-05-18

## 1. Nomenclature & Model Definitions
To avoid confusion, we define the three distinct models we are developing or referencing:

1. **`m01_proto` (The Baseline)**
   *   *What it is:* The current 4-class classifier trained to predict lifetime Maximum Favorable Excursion (MFE). 
   *   *Status:* Functional but flawed. It struggles to differentiate between intermediate classes (10% vs 30%), confusing the loss function and degrading feature importance clarity.

2. **`m01_breakout` (The Timing Engine)**
   *   *What it is:* A new binary classification model designed to predict *when* a breakout will occur (e.g., probability of breakout in the next 1-3 days).
   *   *Data Feasibility:* The new dense `t3_sepa_features` table stores the *full daily history* of every ticker that passes the `trend_ok` gate, not just the day it breaks out. Therefore, we already have millions of rows of "non-breakout" days (negative samples) to train this model. No external dataset is required.

3. **`m01_rank` (The Conviction Engine)**
   *   *What it is:* A binary classifier predicting "Home Run" vs. "Rest" (or a regressor predicting 20-day return). The output probability is used purely as a continuous continuous score (`prob_elite`) to rank setups daily.
   *   *Why not just use `class3` from `m01_proto`?* We *can* and currently *do* use the `class3` score to rank. The issue is mathematical: training a 4-class model forces XGBoost to spend learning capacity trying to separate a 12% return from a 28% return. By collapsing to a binary target (Home Run vs Rest), the algorithm's loss function focuses 100% on finding elite setups, yielding a much cleaner, less noisy probability score.

---

## 2. Strategy Lifecycle (How it all fits together)

The use case is not too narrow; it represents a complete, dynamic lifecycle for a trade. 

### Phase 1: The Watchlist (Screener)
The universe is filtered using the SEPA `trend_ok` gate. Tickers that pass this gate form the active watchlist. 

### Phase 2: The Entry (m01_breakout + m01_rank)
We do not blindly buy just because a breakout happened. 
*   We use `m01_rank` to score the watchlist daily.
*   *Proposed Rule:* We only enter when the setup has high conviction (e.g., `prob_elite >= 0.60` for 3 consecutive days) AND the macro regime is supportive (`m03_score > 60`). 

### Phase 3: The Hold & Exit (Ongoing Monitoring)
Once in the trade, the holding period is completely dynamic (adhering to SEPA's philosophy of holding winners longer).
*   We continue scoring the holding with `m01_rank` daily.
*   If the `prob_elite` score decays rapidly (e.g., drops back below 0.40), it signals the structural integrity of the setup is failing, and we can exit early before hitting a hard stop loss.
*   If the score remains high, we ride the trend indefinitely until the trend breaks.

---

## 3. Workflow & Methodology Checkpoints

To safely build and validate `m01_breakout` and `m01_rank`, we will use a strict EDA-to-Prototyping workflow to ensure we do not overfit to noise.

**Step 1: Target Construction**
*   Create an experimental script/notebook to engineer the new targets on the `t3` dataset:
    *   For `m01_rank`: Create a binary `y_homerun` column, or a `return_20d` target.
    *   For `m01_breakout`: Create a binary `y_breakout_next_3d` target.

**Step 2: Pretrain Audit (Using `PretrainReport`)**
*   Pass the experimental dataset through the new `run_pretrain_audit` HTML generator.
*   *Goal:* Validate that the new target has a balanced distribution. Most importantly, use the IC (Information Coefficient) table in the report to verify that momentum/volatility features correlate with the new target.

**Step 3: XGBoost Prototyping**
*   Train the models on the validated features.
*   Run SHAP analysis (using `analyze_high_scores_shap` from `eda_utils.py`) to confirm the model's decision drivers match the IC table from Step 2, resolving the previous SHAP vs. Gain discrepancy.

**Step 4: Vectorized Backtest Validation**
*   Codify the "3 consecutive days > 0.60" entry rule into the vectorized backtester.
*   Validate the Out-Of-Sample portfolio returns before promoting the logic to the daily pipeline.

---

## 4. Regime Model (M03 & 5-Factor) Integration
*   Evaluate the new Z-score based M03 pillars using the `src/evaluation/m03_evaluator.py` framework to confirm they improve Crash Capture Rate and False Alarm Rate over the baseline.
*   Integrate the best-performing regime flags as a hard gate in the entry rules (e.g., veto trades if 5-Factor risk is elevated).
