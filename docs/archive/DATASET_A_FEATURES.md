# Dataset A Feature Catalog

This document lists all features available in Dataset A after running with `--mode full --include-fundamentals`.

## Feature Categories

### 📊 Core Price Features (4)
Always present in the dataset:
- `Close` - Closing price
- `Volume` - Trading volume
- `date` - Trading date
- `ticker` - Stock symbol

---

## 💹 Technical Indicators (20 features)

### Trend Indicators
1. **`SMA_50`** - 50-day Simple Moving Average
2. **`SMA_150`** - 150-day Simple Moving Average  
3. **`SMA_200`** - 200-day Simple Moving Average
4. **`Price_vs_SMA_50`** - Price as % of SMA_50 (e.g., 1.05 = 5% above)
5. **`Price_vs_SMA_150`** - Price as % of SMA_150
6. **`Price_vs_SMA_200`** - Price as % of SMA_200

### Volatility & Risk
7. **`ATR`** - Average True Range (14-day, volatility measure)
8. **`nATR`** - Normalized ATR (ATR / Close × 100, volatility as % of price)

### Price Extremes
9. **`High_52W`** - 52-week high
10. **`Low_52W`** - 52-week low
11. **`High_20D`** - 20-day high (for VCP breakout detection)

### Volume Analysis
12. **`Vol_MA`** - 50-day Volume Moving Average
13. **`Vol_Ratio`** - Current Volume / Vol_MA (volume spike indicator)
14. **`Dry_Up_Volume`** - Volume contraction metric for VCP (Vol_Ratio normalized)

### Strength & Momentum
15. **`RS`** - Relative Strength vs SPY benchmark
16. **`RS_MA`** - 10-day Moving Average of RS (smoothed strength)

### Pattern Recognition
17. **`Breakout`** - Boolean: Price broke above 20-day high
18. **`VCP_Ratio`** - Volatility Contraction Pattern ratio (current range / historical range)
19. **`Consolidation_Width`** - Width of consolidation pattern (High_20D - Low_20D) / Close

---

## 🧬 Alpha Factors (6 features)
Heavyweight WorldQuant-style alpha signals (only in `--mode full`):

20. **`alpha001`** - Mean reversion on volume-weighted returns
21. **`alpha006`** - Correlation-based momentum  
22. **`alpha009`** - Price reversal after extreme moves
23. **`alpha012`** - Volume-price divergence
24. **`alpha041`** - Max(High - Low) over period
25. **`alpha101`** - Rank-based price momentum

---

## 📈 Fundamental Features (15+ features)
Only present when `--include-fundamentals` is enabled:

### Raw Financials
26. **`revenue`** - Quarterly revenue
27. **`netIncome`** - Net income
28. **`eps`** - Earnings per share
29. **`grossProfit`** - Gross profit
30. **`operatingIncome`** - Operating income
31. **`totalAssets`** - Total assets
32. **`totalLiabilities`** - Total liabilities
33. **`totalEquity`** - Shareholders' equity (book value)
34. **`totalDebt`** - Total debt
35. **`cash`** - Cash and equivalents
36. **`totalCurrentAssets`** - Current assets
37. **`totalCurrentLiabilities`** - Current liabilities
38. **`inventory`** - Inventory

### Growth Metrics  
39. **`revenue_growth_yoy`** - YoY revenue growth %
40. **`eps_growth_yoy`** - YoY EPS growth %
41. **`net_income_growth_yoy`** - YoY net income growth %

### Safety & Liquidity Ratios
42. **`debt_to_equity`** - Total Debt / Total Equity
43. **`current_ratio`** - Current Assets / Current Liabilities ✅ **FIXED**
44. **`quick_ratio`** - (Current Assets - Inventory) / Current Liabilities ✅ **FIXED**

### Profitability Metrics
45. **`gross_margin`** - Gross Profit / Revenue × 100
46. **`operating_margin`** - Operating Income / Revenue × 100  
47. **`roe`** - Return on Equity (Net Income / Total Equity × 100)
48. **`roa`** - Return on Assets (Net Income / Total Assets × 100)

### Valuation Ratios (Hybrid Price + Fundamental)
49. **`pe_ratio`** - Price / Earnings (Close / EPS)
50. **`ps_ratio`** - Price / Sales (Market Cap / Revenue) ✅ **FIXED**
51. **`pb_ratio`** - Price / Book (Market Cap / Total Equity)

### Fundamental Metadata
52. **`fiscal_date`** - Fiscal period end date
53. **`filing_date_matched`** - When fundamental data was filed (no look-ahead!)
54. **`fiscal_period`** - Q1, Q2, Q3, Q4, FY
55. **`days_since_report`** - Days since last fundamental report
56. **`is_stale`** - Boolean: Is fundamental data >400 days old?
57. **`has_fundamentals`** - Boolean: Does ticker have fundamental data?

---

## 📊 Feature Summary

| Category | Count | Notes |
|----------|-------|-------|
| **Core** | 4 | Always present |
| **Technical Indicators** | 20 | Lightweight, always calculated |
| **Alpha Factors** | 6 | Heavyweight, only in `--mode full` |
| **Fundamentals** | 30+ | Only with `--include-fundamentals` |
| **Total (Full Mode + Fundamentals)** | **~60 features** | |

---

## 🎯 Derivative Feature Recommendations

Based on the current feature set, here are potential **derivative features** you might consider:

### Missing Cross-Sectional Features
Currently, all features are **ticker-specific**. Consider adding:
- **Sector/Industry rankings** (e.g., "How does this stock's RS compare to its sector?")
- **Percentile ranks** across universe (e.g., "Top 10% by revenue growth")
- **Z-scores** for fundamental metrics

### Missing Momentum Features
- **Rate of change** features (e.g., `RS` acceleration, `Volume` trend)
- **Multi-timeframe momentum** (10/20/50/100-day returns)
- **Momentum consistency** (how many days has stock been above MA50?)

### Missing Fundamental Derivatives
- **Fundamental momentum** (e.g., QoQ revenue growth trend)
- **Earnings surprise** (actual vs estimate, if you have consensus data)
- **Cash flow metrics** (operating cash flow, free cash flow)
- **Efficiency ratios** (asset turnover, inventory turnover)

### Missing Interaction Features
- **Price-Volume interaction** (e.g., Volume spike + Price breakout)
- **Growth-Quality interaction** (e.g., High revenue growth + High ROE)
- **Valuation-Growth** (PEG ratio = PE / EPS Growth)

### Pattern-Based Features  
- **Consecutive up/down days** counter
- **Distance from support/resistance** levels
- **Consolidation duration** (days in tight range)
- **Volume profile** (volume distribution across price levels)

---

## 💡 Recommendations

1. **Start with what you have** - 60+ features is already comprehensive
2. **Feature selection** is more important than feature creation - use correlation analysis to remove redundant features
3. **Test incrementally** - Add derivative features in small batches and measure ML performance impact
4. **Domain-driven** - VCP patterns suggest focusing on volatility contraction and volume drying metrics
5. **Consider compute cost** - Cross-sectional features require full universe context (expensive!)

---

## 🔍 Next Steps

1. **Run Dataset A generation**:
   ```bash
   python build_dataset_a.py --start 2021-01-01 --end 2025-11-28 --mode full --include-fundamentals --n-jobs -1
   ```

2. **Inspect actual features**:
   ```bash
   python -c "
   import pandas as pd
   ds = pd.read_parquet('data/ml/dataset_a.parquet')
   print(f'Total features: {len(ds.columns)}')
   print('\\nAll columns:')
   for i, col in enumerate(ds.columns, 1):
       print(f'{i:3d}. {col}')
   "
   ```

3. **Feature correlation analysis**:
   ```python
   import pandas as pd
   import seaborn as sns
   import matplotlib.pyplot as plt
   
   ds = pd.read_parquet('data/ml/dataset_a.parquet')
   
   # Get numeric columns only
   numeric_cols = ds.select_dtypes(include=['float64', 'int64']).columns
   
   # Calculate correlation matrix
   corr = ds[numeric_cols].corr()
   
   # Find highly correlated pairs (>0.95)
   high_corr = []
   for i in range(len(corr.columns)):
       for j in range(i+1, len(corr.columns)):
           if abs(corr.iloc[i, j]) > 0.95:
               high_corr.append((corr.columns[i], corr.columns[j], corr.iloc[i, j]))
   
   print("Highly correlated features (>0.95):")
   for f1, f2, val in high_corr:
       print(f"  {f1} <-> {f2}: {val:.3f}")
   ```
