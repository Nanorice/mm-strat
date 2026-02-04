# M03 Evaluation & Integration Plan

**Component:** `M03 Market Regime`
**Target Granularity:** Monthly
**Validation Period:** 2001-01 to 2026-01

---

## 0. Regime tagging data for validation
start_date,end_date,regime,rationale,source
2001-01-01,2002-10-09,BEAR,Dot-Com Bust. Nasdaq -78%. S&P broke trend. Liquidity dried.,LSEG/Wikipedia
2002-10-10,2007-10-09,BULL,Housing Boom. Low rates. Strong Trend.,LSEG
2007-10-10,2009-03-09,STRONG_BEAR,GFC. Subprime Crisis. Trend broken. Credit Spreads exploded.,LSEG/Morningstar
2009-03-10,2010-04-23,BULL,Post-Crisis Recovery. QE1. Trend > 200 SMA.,WisdomTree
2010-04-24,2010-08-31,NEUTRAL,Flash Crash (May 2010). Euro Crisis I. Choppy.,Wiki
2010-09-01,2011-07-31,BULL,QE2 Rally.,WisdomTree
2011-08-01,2011-10-04,BEAR,US Debt Downgrade. VIX Spike > 40. Trend broken.,Wikipedia/SeekingAlpha
2011-10-05,2015-05-19,BULL,Slow Grind Up. QE3.,Investopedia
2015-05-20,2016-02-11,NEUTRAL,China Devaluation / Oil Crash. Trend flat/broken.,AvaTrade/Wikipedia
2016-02-12,2018-01-26,STRONG_BULL,Trump Rally / Global Growth. Extremely low Vol.,WisdomTree
2018-01-27,2018-03-31,NEUTRAL,Volmageddon (VIX ETN blowup).,GovUK
2018-04-01,2018-09-20,BULL,Recovery.,GovUK
2018-09-21,2018-12-24,BEAR,Fed Tightening (Auto-pilot). Liquidity Drain.,LSEG
2018-12-26,2020-02-19,BULL,Powell Pivot. 2019 Rally.,Charles Schwab
2020-02-20,2020-03-23,STRONG_BEAR,COVID Crash. Speed test (1 month drop).,LSEG/Charles Schwab
2020-03-24,2021-12-31,STRONG_BULL,Fed Stimulus. Tech Boom.,WisdomTree
2022-01-03,2022-10-12,BEAR,Inflation / Rate Hikes. Tech Crash.,Wikipedia/LSEG
2022-10-13,2023-02-28,NEUTRAL,Bottoming Process.,Charles Schwab
2023-03-01,2023-03-31,BEAR,SVB Regional Bank Crisis. VIX Spike.,Wikipedia
2023-04-01,2023-07-31,BULL,AI Rally (Nvidia).,Wikipedia
2023-08-01,2023-10-27,NEUTRAL,Higher for Longer (Yields > 5%).,Wikipedia
2023-10-30,2024-03-31,STRONG_BULL,Fed Pivot Rally.,Albert Bridge
2024-04-01,2024-04-30,NEUTRAL,Inflation Scare pullback.,Albert Bridge
2024-05-01,2024-07-15,BULL,Summer Rally.,Albert Bridge
2024-07-16,2024-08-15,BEAR,Yen Carry Trade Crash (VIX > 65).,Albert Bridge
2024-08-16,2025-12-31,BULL,Election & Post-Election Rally. US Outperformance.,Albert Bridge
2026-01-01,2026-01-31,NEUTRAL,Current Evaluation Period.,(Live Data)

## 1. Validation Logic (The "Stress Test")

We validate the M03 score against the "Consensus Truth" CSV above.

### A. Accuracy Metrics
* **Crash Capture Rate:** % of "STRONG_BEAR" days where M03 Score < 20.
* **False Alarm Rate:** % of "STRONG_BULL" days where M03 Score < 40.
* **Lag:** Days between `Ground Truth Start` and `M03 Switch`. (Must be < 7 days for fast crashes like 2020/2024).


# M03 Evaluation & Optimization Plan

**Component:** `M03 Market Regime`
**Goal:** Calibrate the "Risk Score" (0-100) to accurately predict crashes without triggering false alarms.
**Status:** Calibration Phase

---

## 1. The Evaluation Metrics (The "Exam")

We grade the M03 model on three specific metrics. The model must pass these thresholds before being deployed to the `daily_scanner`.

### Metric A: Crash Capture Rate (Sensitivity)
* **Definition:** The percentage of "Deep Bear" days where the model correctly flagged high risk.
* **Target:** **> 80%**
* **Formula:**
  $$\text{CCR} = \frac{\text{Days}(\text{Score} < 30 \cap \text{Truth} = \text{'STRONG\_BEAR'})}{\text{Total Days}(\text{Truth} = \text{'STRONG\_BEAR'})}$$
* **Why:** If this is low, the model is "sleeping" during crashes (e.g., missed 2020 or 2008).

### Metric B: False Alarm Rate (Precision)
* **Definition:** The percentage of "Strong Bull" days where the model incorrectly panicked.
* **Target:** **< 5%**
* **Formula:**
  $$\text{FAR} = \frac{\text{Days}(\text{Score} < 40 \cap \text{Truth} = \text{'STRONG\_BULL'})}{\text{Total Days}(\text{Truth} = \text{'STRONG\_BULL'})}$$
* **Why:** If this is high, the model is "paranoid" and will cash you out of profitable rallies (whipsaw).

### Metric C: Reaction Lag (Speed)
* **Definition:** The number of days between the *start* of a crash (Ground Truth) and the model's first "Bear" signal (Score < 40).
* **Target:** **< 7 Days** (Average)
* **Critical Tests:**
    * **COVID (Feb 2020):** Must switch by Feb 27.
    * **Yen Carry (Aug 2024):** Must switch by Aug 7.

### B. The "Sizing Gate" Simulation
Run a historical simulation on SPY using the M03 Score as a position sizer.

| M03 Score | Regime Category | Position Size | Rationale |
| :--- | :--- | :--- | :--- |
| **80-100** | **STRONG BULL** | **1.2x** (Leverage) | Trend, Liq, & Risk are aligned. |
| **60-80** | **BULL** | **1.0x** | Standard condition. |
| **40-60** | **NEUTRAL** | **0.5x** | Choppy/Conflicting signals. |
| **20-40** | **BEAR** | **0.0x** | Cash. |
| **0-20** | **STRONG BEAR** | **-0.5x** (Short/Hedge) | Active crash. |

**Success Criteria:**
1.  **Drawdown Reduction:** Max DD should be < 50% of SPY Buy & Hold (e.g., if SPY -55% in 2008, Strategy < -27%).
2.  **Calmar Ratio:** > 1.0.
 
---

## 2. Integration Outputs

### Output A: The Feature (for M01 Training)
We cannot just feed the raw score (0-100) to M01, as it creates noise. We feed structured context.

**Preprocessing Logic (`src/features.py`):**
1.  **`regime_cat` (Ordinal):** 0=Bear, 1=Neutral, 2=Bull. (Tree split optimized).
2.  **`liquidity_trend` (Float):** 20-day Slope of Net Liquidity. (Captures Fed pivot momentum).
3.  **`vix_level` (Float):** Raw VIX.
4.  **`regime_volatility` (Float):** Std Dev of M03 Score over last 10 days. (Detects regime instability).

### Output B: The Gatekeeper (for `daily_scanner.py`)
**Logic:**
```python
# Pseudo-code for Gatekeeper
regime = m03.get_current_regime()

if regime['score'] < 20:
    print("⛔ STRONG BEAR: Emergency Cash Mode. No Buys.")
    allowed_risk = 0.0
elif regime['score'] < 40:
    print("🛑 BEAR: Selling Strength. No New Longs.")
    allowed_risk = 0.0
elif regime['score'] < 60:
    print("⚠️ NEUTRAL: Half Size. Tight Stops.")
    allowed_risk = 0.5
else:
    print("✅ BULL: Full Risk.")
    allowed_risk = 1.0