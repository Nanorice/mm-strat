# Quantitative Implementation Plan: 5-Factor Regime-Switching Model

This document serves as the executable blueprint for building the 5-factor regime-switching risk management model. It is structured for an AI agent or quantitative developer to translate directly into Python code.

## 1. Data Acquisition Pipeline

### 1.1 Data Sources
* **Equities & Volatility:** `yfinance` API.
    * VIX Index: `^VIX`
    * S&P 500: `^GSPC`
* **Rates & Credit:** `pandas_datareader` linked to the FRED (Federal Reserve Economic Data) API.
    * US High Yield OAS: `BAMLH0A0HYM2` (ICE BofA US High Yield Index Option-Adjusted Spread)
    * 10-Year Treasury Constant Maturity Rate: `DGS10`
    * 2-Year Treasury Constant Maturity Rate: `DGS2`

### 1.2 Preprocessing Logic
* **Calendar Alignment:** Forward-fill (ffill) missing data across all series to align with the S&P 500 trading calendar. Drop rows where S&P 500 data is natively missing (market holidays).
* **Lookback Requirements:** Pull data starting from at least 2000 (ideally earlier) to allow for the 365-week (approx. 2555 trading days) rolling windows without starving the backtest.

---

## 2. Raw Factor Engineering & Directional Alignment

All factors must be aligned so that a **positive value implies increasing market risk**.

1.  **VIX (Weight: 0.25)**
    * *Calculation:* Spot daily close.
    * *Direction:* `+1` (Higher VIX = Higher Risk).
2.  **High-Yield Change (Weight: 0.25)**
    * *Calculation:* 20-trading-day (1 month) absolute change in the HY OAS. `OAS_today - OAS_20d_ago`.
    * *Direction:* `+1` (Widening spreads = Higher Risk).
3.  **Term Spread Inversion (Weight: 0.15)**
    * *Calculation:* 10Y Yield - 2Y Yield.
    * *Direction:* `-1` (Inverting/Negative spread = Higher Risk). Multiply the raw spread by `-1`.
4.  **S&P Trend Reversal (Weight: 0.15)**
    * *Calculation:* Spot S&P 500 / 200-day Simple Moving Average (SMA) - 1.
    * *Direction:* `-1` (Price falling below SMA = Higher Risk). Multiply the result by `-1`.
5.  **MA Slope Reversal (Weight: 0.20)**
    * *Calculation:* 20-trading-day change of the 200-day SMA. `SMA200_today / SMA200_20d_ago - 1`.
    * *Direction:* `-1` (Flattening/Negative slope = Higher Risk). Multiply the result by `-1`.

---

## 3. Statistical Normalization & Aggregation

### 3.1 Rolling Z-Score Calculation
* **Window:** 365 weeks (translate to `2555` trading days).
* **Methodology:** For each of the 5 aligned raw factors, calculate the rolling mean and rolling standard deviation over the window.
* **Formula:** `Z_t = (Raw_t - Rolling_Mean_t) / Rolling_Std_t`

### 3.2 Aggregation & Single-Factor Veto
* **Weighted Sum:** `Z_Aggregate = (0.25 * Z_VIX) + (0.25 * Z_HY) + (0.15 * Z_Term) + (0.15 * Z_Trend) + (0.2 * Z_Slope)`
* **Veto Trigger Detection:** Create a daily boolean mask: `Veto_Flag = True` if *any* of the 5 individual Z-scores is $\ge 2.0$.

---

## 4. Band Mapping & Target Exposure

### 4.1 Empirical CDF (Percentile)
* **Calculation:** Compute the rolling 365-week percentile ranking (from 0.0 to 1.0) of the `Z_Aggregate` score. 
* *Implementation Tip:* Use `pandas.Series.rolling(window=2555).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1])` or a more optimized NumPy equivalent to prevent computational bottleneck.

### 4.2 Allocation Matrix
Map the rolling percentile (0 to 1) to the target exposure bands.

* 0.00 to 0.20 $\rightarrow$ 100% Exposure
* 0.20 to 0.40 $\rightarrow$ 85% Exposure
* 0.40 to 0.55 $\rightarrow$ 75% Exposure
* 0.55 to 0.70 $\rightarrow$ 50% Exposure
* 0.70 to 0.85 $\rightarrow$ 35% Exposure
* 0.85 to 1.00 $\rightarrow$ 15% Exposure

**Apply Veto Overlay:** If `Veto_Flag == True`, instantly override the mapped exposure and force it to **15%**.

---

## 5. Implementation Execution Plan

| Session | Component | Description | Target Deliverable |
| :--- | :--- | :--- | :--- |
| Session 1 | Data Ingestion | Script to fetch `yfinance` (^VIX, ^GSPC) and FRED API (BAMLH0A0HYM2, DGS10, DGS2) using `pandas_datareader`. Handle ffill and missing data logic. | Cleaned, aligned pandas DataFrame spanning 2000-Present. |
| Session 2 | Raw Factor Calculation | Compute 20d HY change, 10Y-2Y spread, 200d SMA distance, and 20d SMA slope. Apply -1 multipliers to duration, trend, and slope to map positive to risk. | DataFrame appended with 5 correctly oriented raw factor columns. |
| Session 3 | Normalization & Z-Scores | Implement 2555-trading-day rolling mean and standard deviation for all 5 factors. Calculate daily Z-scores and map the $Z \ge 2$ veto boolean array. | DataFrame with 5 rolling Z-score columns and 1 boolean Veto column. |
| Session 4 | Aggregation & Percentile Rank | Compute the weighted sum of Z-scores. Apply rolling 2555-day percentile calculation to map the sum to a bounded 0-1 scale. | DataFrame containing `Weighted_Z` and `Rolling_Percentile` columns. |
| Session 5 | Exposure Mapping & Veto Overlay | Discretize the percentile scores into the 6 allocation bands (100% to 15%). Apply the hard override mapping any `True` veto day to 15% target exposure. | Final `Target_Exposure` column ready for Strategy module backtesting. |
