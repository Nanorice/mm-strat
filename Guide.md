# Master Project Handover: QSS System (Gen 2)
**Date:** January 2026
**Current Phase:** Gen 2.1 - Ignition Engine Pivot
**Objective:** Capture "Superperformance" (SEPA) stocks by decoupling **Velocity Prediction** (AI) from **Trend Capture** (Execution).

---

## **1. How to Resume This Project**
**Immediate Action Required:**
We are currently in **Phase 1** of the execution plan.
1.  **Task:** Modify `scripts/optimize_barriers.py`.
2.  **Action:** Add `ignition_score` metric (separation between TP and Time outcomes).
3.  **Goal:** Run grid search to find barrier parameters (`k_tp`, `k_sl`) that maximize the distinction between "Igniters" (Winners) and "Drifters" (Time-outs).

---

## **2. Core Philosophy & Strategic Pivot**
We have shifted from a "Guardrail" approach to an **"Ignition Engine"** architecture.

* **The Problem:** SEPA finds winners ("Marathon Runners") but entries are often too early ("Drifters"), tying up capital. Existing models predicted "Quality" (Margins/PE), failing to predict "Speed."
* **The Solution:**
    1.  **Decouple Prediction:** Train `M01_3bar` purely to find **Velocity** (immediate 3x ATR move), ignoring long-term trends.
    2.  **Decouple Execution:** Move complex exits (Barbell Strategy) out of the ML layer.
* **The Key Insight:** A low Profit Target (TP) rate (~11%) is **not a failure**. It is the signal of scarcity. We optimize the model to hunt this 11%, accepting that "Time-Outs" are safe failures (+3% avg return).

---

## **3. Model Ecosystem (Dual-Engine)**

| Feature | **M01 (Quality Engine)** | **M01_3bar (Ignition Engine)** |
| :--- | :--- | :--- |
| **Type** | **Regressor** | **Classifier** |
| **Role** | **Return Predictor** | **Timing Filter** |
| **Goal** | Predict the *magnitude* of return over 3-6 months. | Predict the *probability* of a 3x ATR move within 20 days. |
| **Labeling** | Continuous (Max Return over horizon). | Triple Barrier (Hit dynamic TP before SL/Time). |
| **Key Features** | **Fundamentals & Trend**<br>(PE Ratio, EPS Growth, SMA deviations). | **Velocity & Momentum**<br>(RS Velocity, Vol Accel, Breakout Thrust). |
| **Output** | **Expected Return %** (e.g., `0.45` for 45%) | **Ignition Probability** (e.g., `0.82`) |

---

## **4. System Architecture**

### **Data Flow Diagram**
```mermaid
graph TD
    A[Raw Market Data] --> B(Feature Factory);
    
    %% Parallel Model Processing
    B -->|Fundamental/Trend Features| C{M01 Regressor};
    B -->|Velocity/Momentum Features| D{M01_3bar Classifier};
    
    %% SEPA Logic
    A --> E[SEPA Scanner];
    E -->|Candidates| F[Signal Aggregator];
    
    %% Decision Layer
    C -->|Predicted Return %| F;
    D -->|Ignition Probability| F;
    
    F --> G{Entry Logic};
    G -->|Pred Return > 15% AND Ignition Prob > 0.6| H[EXECUTE TRADE];
    G -->|Else| I[Watchlist / Reject];
    
    %% Execution Layer
    H --> J[Barbell Strategy];
    J --> K(Exit A: 50% @ 3x ATR Limit);
    J --> L(Exit B: 50% @ SMA 50 Trail);

Step,Name,Logic,Data Used,Output
1,Label Generation,"""Grid Search"" (Optimization)",FUTURE (Day 1 to 30),The Target (y)  (1 or 0)
2,Feature Engineering,"""Signal Extraction""",PAST (Day -20 to 0),"The Inputs (X)  (Velocity, etc.)"
3,Model Training,"""Pattern Recognition""",PAST + FUTURE,The Model  (Ignition Engine)

<!-- How does the M02 model work -->
"Two-Step Machine Learning Pipeline."

Here is the breakdown of exactly how each step works, confirming your understanding.

Step 1: The "God Mode" Optimization (Label Generation)
Goal: Define "What does a perfect trade look like?"

Input: Future Price Data (The data after the buy signal).

Is there a Model? NO. There is no AI here. It is purely Brute Force Math.

How we optimize to get the answer (tp=4, sl=1):

The Grid Search: We define a list of possibilities.

Try: TP=2x, SL=1x

Try: TP=3x, SL=1x

Try: TP=4x, SL=1x ... and so on.

The Simulation: The script runs every single trade in your history through every single combination.

Scenario A: If we used TP=2, how much money would we have made? What is the Win Rate?

Scenario B: If we used TP=4, does the "Ignition Score" (separation between winners and losers) go up?

The Selection: We look at the results table (like the CSV you generated) and pick the row with the best score.

Result: "The math says TP=4 / SL=1 / Time=30 creates the clearest signal."

The Labeling: We then stamp every trade in the dataset with a 1 (if it hit that 4x Target) or a 0 (if it failed).

Analogy: This is the Teacher making the Answer Key. The Teacher looks at the textbook (Future Data) to decide the correct answers.

Step 2: The "Blindfolded" Training (Feature Engineering)
Goal: Teach the model to predict the Answer Key without looking at the future.

Input: Past Price Data (The data before the buy signal).

Is there a Model? YES. This is where XGBoost comes in.

How it works:

The Challenge: The model sees a trade at Time=0. It does NOT know if it hit TP or SL (that's the future).

The Features (Clues): We give it volume_acceleration, alpha101, RS_Delta.

The Training: The model tries to find patterns.

Observation: "Hey, every time volume_acceleration is high, the Label turns out to be 1."

Observation: "Every time nATR is high, the Label turns out to be 0."

The Prediction: It outputs a probability: "Based on these features, I am 80% sure this is a 1."

Analogy: This is the Student taking the Test. The Student studies the Clues (Features) to guess the Answer Key (Labels) created in Step 1.