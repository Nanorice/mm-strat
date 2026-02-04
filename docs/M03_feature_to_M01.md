# M03 Feature Engineering Strategy

**Module:** M03 Integration -> M01 Trainer
**Goal:** Provide "Macro Context" to the stock prediction engine.
**Feature Count:** 8 Features (Expanded)

---

## 1. Feature List

These features are appended to every row of stock training data based on the date. All continuous features are **normalized to 0.0 - 1.0** to match M01's input standards.

| Feature Name | Type | Range (Norm) | Source Logic | Rationale |
| :--- | :--- | :--- | :--- | :--- |
| **`m03_score`** | Float | 0.0 – 1.0 | `Raw Score / 100` | **The Signal.** Allows model to learn its own thresholds. |
| **`m03_regime_cat`** | Int | 0 – 4 | `Ordinal Encoding` | **The Human Logic.** Enforces calibrated "Safety Zones" (0=Strong Bear ... 4=Strong Bull). |
| **`m03_delta_5d`** | Float | -1.0 – 1.0 | `(Score - Score_T-5) / 100` | **Velocity (Sprint).** Detects sudden shocks (e.g., Flash Crash). |
| **`m03_delta_20d`** | Float | -1.0 – 1.0 | `(Score - Score_T-20) / 100` | **Velocity (Marathon).** Detects slow deterioration (e.g., 2022 Bear). |
| **`m03_regime_vol`** | Float | 0.0 – 1.0 | `Score.rolling(10).std() / 100` | **Stability.** Captures "Choppiness." High vol = low confidence regime. |
| **`m03_pillar_trend`** | Float | 0.0 – 1.0 | `Trend Pillar / 100` | **Market Structure.** SPY vs SMA200 context. |
| **`m03_pillar_liq`** | Float | 0.0 – 1.0 | `Liquidity Pillar / 100` | **The Fed.** "Don't fight the Fed" context. |
| **`m03_pillar_risk`** | Float | 0.0 – 1.0 | `Risk Pillar / 100` | **Fear Gauge.** VIX/Credit context. |

---

## 2. Encoding & Normalization Details

### A. Regime Category (Ordinal)
Mapped using the Calibrated Thresholds from `m03_config.json` (Hybrid Production Config).

| Score Range | Category | Ordinal Value | Meaning |
| :--- | :--- | :--- | :--- |
| **0 – 30** | Strong Bear | **0** | **NO GO.** Breakouts here have 90% failure rate. |
| **30 – 45** | Bear | **1** | Defensive. High failure rate. |
| **45 – 60** | Neutral | **2** | Choppy. 50/50 odds. |
| **60 – 75** | Bull | **3** | Standard. Good odds. |
| **75 – 100** | Strong Bull | **4** | **GO.** Aggressive environment. |

### B. Velocity Logic (Absolute vs Percentage)
We use **Absolute Delta** (scaled /100) instead of Percentage Change.
* **Reason:** Percentage change explodes when the score is low (e.g., moving from 5 to 2 is -60%).
* **Logic:** A 5-point drop is significant regardless of whether we are at 80 or 40.

---

## 3. Data Integrity & Safety

### A. Lag Handling (The "Knowledge Date" Rule)
* **Question:** "How do we handle the T+1 shift when joining?"
* **Answer:** The shift is handled **upstream** inside `M03RegimeCalculator`.
    * The M03 engine outputs a row for Date `T` using only data available *prior* to the scanner run on Date `T`.
    * **Example:** On Thursday (T), the Liquidity Pillar uses Wednesday's data (shifted).
    * **Result:** We perform a **direct join** (`on='date'`) between Stock Data and M03 Data. No additional shifting is required at the join stage.

### B. Handling Missing Regimes (Holidays)
* **Scenario:** Stock market is open (e.g., Columbus Day) but Bond market/FRED is closed/delayed.
* **Solution:** `ffill()` (Forward Fill).
* **Logic:** "If the Macro Regime hasn't updated today, assume the Regime is the same as yesterday."

