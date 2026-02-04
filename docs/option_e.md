# Algo Option E: Log-Hybrid (Close-Only Revision)

## 1. Strategy Definition
* **Frequency:** Low Frequency (Daily Scans)
* **Execution Timing:** * *Scan:* Post-Market Close (using confirmed Daily Candles).
    * *Trade:* Market Order at Next Day's Open.
* **Target Variable ($y$):**
    * The target is log-transformed to compress outliers, mixing MFE for winners and Realized P&L for stopped-out losers.
    * Formula: $y = \text{sign}(x) \times \ln(1 + |x|)$

## 2. Logic Flow Table

| Step | Phase | Action / Condition | Logic Note |
| :--- | :--- | :--- | :--- |
| **1** | **Scan (Post-Close)** | Check **Trend Condition**: <br> `Current Close > SMA_50` | Only take long signals if the asset is in a medium-term uptrend. |
| **2** | **Entry Signal** | Check **Trigger**: <br> `Current Close > Max(Close, last 10 days)` | **Donchian Breakout (Close-basis).** Confirms momentum without intraday noise. |
| **3** | **Execution** | If Signal = True: <br> Place **Market Buy Order** for **Next Open**. | We assume passive execution at the start of the next session. |
| **4** | **Stop Loss Monitor** | **Structural Stop:** <br> `Current Close < (Entry Price * 0.90)` | **-10% Hard Stop (Close-basis).** We wait for the daily close to confirm the 10% drop. Wicks are ignored. |
| **5** | **Trailing Stop** | **Technical Stop:** <br> `Current Close < SMA_50` | Trend violation must be confirmed by a Close below the average. |
| **6** | **Outcome Calculation** | **If Winner (No Stop Triggered):** <br> $x = \text{MFE (Max Favorable Excursion based on Highs)}$ <br> **If Loser (Stop Triggered):** <br> $x = \text{Realized Loss (Exit at Next Open)}$ | Winners are rewarded for potential upside; Losers are penalized for actual realized drag. |

## 3. Revised Exit Mechanics (Detailed)

### A. The Structural Stop (-10% Floor)
* **Old Logic:** Triggered if `Low < Entry * 0.90` (Intraday).
* **New Logic:** Triggered only if `Current Close < Entry * 0.90`.
* **Execution:** Sell at **Next Open**.
* **Why:** This prevents "stop hunting" where a stock drops -12% intraday but recovers to -8% by close.

### B. The Technical Stop (Trend Break)
* **Old Logic:** Triggered if `Close < SMA_50`.
* **New Logic:** Same trigger, but strictly enforces **Next Open** execution for the loss calculation.
* **Why:** Aligns the backtest with realistic low-frequency operations.

## 4. Formula Implementation (Python/Pandas)

```python
import numpy as np

def calculate_target_option_e(df, entry_price_col='entry_price'):
    """
    Calculates Option E target using Close-only logic.
    Assumes df has columns: 'close', 'high', 'open_next_day', 'sma_50'.
    """
    # 1. Determine Stop Triggers (Boolean Masks)
    # Structural: Did the CLOSE drop 10% below entry?
    stop_struct = df['close'] < (df[entry_price_col] * 0.90)
    
    # Technical: Did the CLOSE drop below SMA 50?
    stop_tech = df['close'] < df['sma_50']
    
    # 2. Determine Outcome Type
    # If either stop is True, it's a "Loser"
    is_loser = stop_struct | stop_tech
    
    # 3. Calculate 'x' (Raw Value)
    # Initialize x with MFE (Max Favorable Excursion) for everyone first
    # MFE = (High - Entry) / Entry
    df['x'] = (df['high'] - df[entry_price_col]) / df[entry_price_col]
    
    # Overwrite 'x' for Losers using Realized Loss
    # Realized Loss = (Next Open - Entry) / Entry
    # We use Next Open because we exit the morning AFTER the close trigger
    df.loc[is_loser, 'x'] = (df['open_next_day'] - df[entry_price_col]) / df[entry_price_col]
    
    # 4. Apply Log-Hybrid Transform
    # y = sign(x) * ln(1 + |x|)
    df['y'] = np.sign(df['x']) * np.log1p(np.abs(df['x']))
    
    return df['y']