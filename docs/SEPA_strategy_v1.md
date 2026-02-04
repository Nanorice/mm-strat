# Strategy Specification: SEPA Hybrid V1

**Type:** Trend Following (Long Only)
**Components:**
1.  **Selection (M01):** Technical Ranking Model.
2.  **Gating (M03):** Macro Regime Filter.
3.  **Execution:** Multi-Tranche Scaling & Trailing Stops.

---

## 1. Risk & Sizing Rules (The Brain)

### A. Regime-Based Exposure (M03)
Position sizing is dynamic based on the `m03_regime_cat` (0-4) at the time of entry.

| Regime | Code | Bias | Position Size | Max Positions | Max Portfolio Risk |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Strong Bear** | 0 | **Hard Stop** | **0% (No New Entries)** | 0 | 0% |
| **Bear** | 1 | Defensive | 2.5% | 4 | 10% |
| **Neutral** | 2 | Cautious | 5.0% | 8 | 40% |
| **Bull** | 3 | Aggressive | 7.5% | 10 | 75% |
| **Strong Bull** | 4 | Max Aggression | 10.0% | 12 | 120% (Leverage) |

**Hard Gate Rule:**
* If `Regime == 0` (Strong Bear), **ALL** existing positions must be liquidated immediately at Market Open. No new signals are processed.

### B. Portfolio Constraint
* **Max Positions:** Hard cap based on regime (see above).
* **Ranking:** If `Signal Count > Available Slots`, sort candidates by `M01_Score` (descending) and take the top N.

---

## 2. Entry Logic (The Filter)

**Frequency:** Daily (End of Day scan for Next Open entry).

### A. Universe Filter
* **Liquidity:** Min Daily Volume > $10M (approx).
* **Price:** Min Price > $5.00.

### B. Signal Criteria
A trade is triggered if **ALL** conditions are met:
1.  **Regime Check:** `M03_Regime > 0`.
2.  **Cooldown Check:** Ticker has not been stopped out in the last **3 Days**.
3.  **M01 Score Check:**
    * **Dynamic:** Score is in the **Top 5th Percentile** of daily candidates.
    * **Hard Floor:** Score must be **> 70.0** (Prevents buying "best of junk").

---

## 3. Execution & Exit Logic (The Body)

**Order Type:** Market Orders at Open (Next Day).

### A. Initial Stop Loss (Protection)
* **Calculation:** `Entry_Price - MIN(2.0 * ATR, 10% * Entry_Price)`
* **Gap Rule:** If Stock Opens below Stop Price, **Market Sell immediately**.

### B. Profit Taking (3-Tranche Scale Out)

**Tranche 1 (The Bank): Sell 33%**
* **Target:** `Entry + MAX(3.0 * ATR, 15%)`
* **Action:**
    * Sell 1/3 of position.
    * **Move Stop:** `New_SL = Target_1 - MAX(1.0 * ATR, 5%)`. (Breakeven+ Protection).

**Tranche 2 (The Continuation): Sell 33%**
* **Target:** `Target_1 + (2.0 * ATR)`
* **Action:**
    * Sell 1/3 of *original* position.
    * **Move Stop:** `New_SL = Target_2 - (1.0 * ATR)`. (Tight Trail).

**Tranche 3 (The Runner): Sell Remaining**
* **Trigger:** Trend Breakdown.
* **Condition:** `Close < SMA(50)`.
* **Action:** Liquidate remaining shares at Market.

### C. Trailing Logic (General)
* Aside from the specific Tranche moves, the Stop Loss is **never moved down**.

---

## 4. Backtesting Assumptions (Simulation Config)

* **Starting Capital:** $100,000.
* **Commission:** $0.005 per share (or 0.1% estimate).
* **Slippage:** 0.1% (Variable based on volatility is preferred, but 0.1% fixed for V1).
* **Execution Price:** Next Open.
* **Data Resolution:** Daily.
* **Warm-Up Period:** 250 Days (Required for SMA200 and ATR calculation before first trade).