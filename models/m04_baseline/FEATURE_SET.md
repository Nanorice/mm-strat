# M04 MFE Classifier - Feature Set Analysis

## Summary
- **Model**: M04 (MFE 4-Class Classifier)
- **Total Features**: 105 (out of 106 requested)
- **Missing**: 1 feature (`atr_delta` - not in v_d2_training)
- **Data Source**: `v_d2_training` view
- **Target**: `mfe_pct` (Maximum Favorable Excursion %) → 4 classes

## ✅ Data Leakage Check

**Status**: **CLEAN** - No leakage detected

The following columns exist in `v_d2_training` but are **correctly excluded** from features:

### Excluded Leakage Columns (used only for labeling):
```
mae_pct              ← Future outcome (lowest point in trade)
mfe_pct              ← Future outcome (highest point in trade) [TARGET ONLY]
return_at_exit       ← Future outcome (final return)
exit_date            ← Future date
exit_price           ← Future price
holding_days         ← Future duration
mae_date             ← Future date
mfe_date             ← Future date
sepa_exit_date       ← Future date
sl_exit_date         ← Future date
return_pct           ← Alias for return_at_exit
```

### Excluded Metadata Columns:
```
ticker               ← Identifier (not predictive)
date                 ← Timestamp
trade_id             ← Identifier
feature_version      ← Schema version
entry_date           ← Redundant with date
entry_price          ← Raw price (non-stationary)
```

### ⚠️ Potentially Leaky Features (kept for now)
```
return_1d            ← 1-day forward return (T+1)
return_5d            ← 5-day forward return (T+5)
return_20d           ← 20-day forward return (T+20)
return_60d           ← 60-day forward return (T+60)
```

**Note**: `return_1d/5d/20d/60d` are technically **forward-looking** if computed at entry time. Need to verify if these are lagged (T-1) or forward (T+1). If forward, they constitute **mild leakage**.

---

## Feature Groups (105 features)

### 1. Moving Averages (8 features)
Price position relative to SMAs + slopes:
```
1.  close_above_sma200           Binary flag
2.  price_vs_sma_50               % distance
3.  price_vs_sma_150              % distance
4.  price_vs_sma_200              % distance
5.  sma_50_slope                  Trend direction
6.  price_vs_sma_50_delta         Rate of change
7.  price_vs_sma_150_delta        Rate of change
8.  price_vs_sma_200_delta        Rate of change
```

### 2. Momentum & Relative Strength (21 features)
Trend strength, sector/industry rankings:
```
1.  rs_line_uptrend              Binary flag
2.  rs_line_delta                Rate of change
3.  rs_line_lag_delta            Lagged change
4.  rs_rating                    Composite momentum score
5.  rs                           Relative strength ratio
6.  rs_ma                        RS moving average
7.  rs_delta                     RS rate of change
8.  rs_ma_delta                  RS MA rate of change
9.  mom_21d                      1-month momentum
10. mom_63d                      3-month momentum
11. mom_126d                     6-month momentum
12. mom_189d                     9-month momentum
13. mom_252d                     12-month momentum
14. rs_velocity                  RS acceleration
15. price_accel_10d              Price acceleration
16. RS_Sector_Rank               Percentile rank in sector
17. RS_vs_Sector                 Z-score vs sector
18. Sector_Momentum              Mean sector RS
19. RS_Industry_Rank             Percentile rank in industry
20. RS_vs_Industry               Z-score vs industry
21. Industry_Momentum            Mean industry RS
```

### 3. Core Volume (7 features)
Liquidity and demand signals:
```
1. vol_ratio                     Today vs 50d avg
2. dry_up_volume                 Low volume tightness
3. dry_up_volume_delta           Rate of change
4. turnover                      Dollar volume
5. volume_acceleration           Volume surge
6. return_1d                     ⚠️ 1-day return (check lag)
7. return_5d                     ⚠️ 5-day return (check lag)
```

### 4. Volatility & Ranges (19 features)
VCP, ATR, 52w/20d highs/lows:
```
1.  natr                         Normalized ATR
2.  natr_delta                   ATR rate of change
3.  vcp_ratio                    Volatility contraction
4.  vcp_ratio_delta              VCP rate of change
5.  consolidation_width          Base width
6.  consolidation_width_delta    Base tightening
7.  consolidation_duration       Days in base
8.  dist_from_52w_high           Distance from high
9.  dist_from_52w_high_delta     Rate approaching high
10. dist_from_52w_low            Distance from low
11. dist_from_52w_low_delta      Rate leaving low
12. low_52w_delta                52w low rate of change
13. high_52w_delta               52w high rate of change
14. dist_from_20d_high           Distance from 20d high
15. dist_from_20d_high_delta     Rate approaching 20d high
16. highest_high_20d_delta       20d high rate of change
17. dist_from_20d_low            Distance from 20d low
18. dist_from_20d_low_delta      Rate leaving 20d low
19. lowest_low_20d_delta         20d low rate of change
```

**Missing**:
- `atr_delta` (ATR rate of change) - column not in v_d2_training

### 5. Technical Oscillators (7 features)
RSI, breakout flags, green day ratios:
```
1. rsi_14                        RSI oscillator
2. rsi_14_delta                  RSI rate of change
3. is_green_day                  Binary flag
4. green_days_ratio_20d          Bullish candle %
5. breakout                      Binary flag
6. breakout_momentum             Thrust strength
7. immediate_thrust              Initial velocity
```

### 6. Fundamentals (21 features)
Earnings, margins, ratios, quality scores:
```
1.  eps_diluted                  Earnings per share
2.  revenue_growth_yoy           YoY revenue growth
3.  eps_growth_yoy               YoY EPS growth
4.  net_income_growth_yoy        YoY income growth
5.  eps_accel                    QoQ EPS growth change
6.  revenue_accel                QoQ revenue growth change
7.  revenue_cagr_3y              3-year CAGR
8.  eps_stability_score          Earnings consistency
9.  debt_to_equity               Leverage ratio
10. current_ratio                Liquidity ratio
11. gross_margin                 Profitability %
12. operating_margin             Operating efficiency
13. roe                          Return on Equity
14. roa                          Return on Assets
15. fcf_margin                   Free cash flow margin
16. earnings_quality_score       OCF / Net Income
17. gross_margin_trend           Margin expansion/contraction
18. days_since_report            Staleness indicator
19. pe_ratio                     Price / Earnings
20. ps_ratio                     Price / Sales
21. pb_ratio                     Price / Book
```

### 7. Fast Alphas (15 features)
WorldQuant 101 factors:
```
1.  alpha001                     Rank of returns
2.  alpha002                     Volume/Price rank correlation
3.  alpha004                     Rank of lows (trend consistency)
4.  alpha006                     Volume/Open correlation
5.  alpha009                     Delta close stability
6.  alpha011                     VWAP divergence
7.  alpha012                     Directional volume force
8.  alpha013                     Price/Volume covariance
9.  alpha015                     Rank correlation (High/Vol)
10. alpha041                     Delta of (High * Low)
11. alpha046                     Slope acceleration
12. alpha049                     Slope deceleration
13. alpha054                     Structure (Open/Close/Low)
14. alpha060                     Volume-weighted sum
15. alpha101                     Candle body strength
```

### 8. M03 Regime (7 features)
Macro environment context:
```
1. m03_score                     Composite regime score (0-100)
2. m03_pillar_trend              Trend pillar score
3. m03_pillar_liq                Liquidity pillar score
4. m03_pillar_risk               Risk appetite pillar score
5. m03_delta_5d                  5-day regime change
6. m03_delta_20d                 20-day regime change
7. m03_regime_vol                Regime volatility
```

---

## Feature Engineering Insights

### Delta Features (rate of change)
Many features have `_delta` variants capturing momentum:
- Price vs SMAs: `price_vs_sma_50_delta`, etc.
- Volatility: `natr_delta`, `vcp_ratio_delta`, `consolidation_width_delta`
- RS: `rs_delta`, `rs_ma_delta`, `rs_line_delta`
- Ranges: `dist_from_52w_high_delta`, etc.

**Pattern**: Delta features eliminate 18 LAG() operations by pre-computing % change in database.

### Cross-Sectional Features (6 features)
Relative rankings within peer groups:
- `RS_Sector_Rank`, `RS_vs_Sector`, `Sector_Momentum`
- `RS_Industry_Rank`, `RS_vs_Industry`, `Industry_Momentum`

**Value**: Captures relative strength vs peers, not just absolute.

### Multi-Timeframe Momentum (5 features)
Momentum across different lookback periods:
- `mom_21d`, `mom_63d`, `mom_126d`, `mom_189d`, `mom_252d`

**Value**: Captures both short-term and long-term trends.

---

## Potential Issues

### 1. Forward-Looking Returns (⚠️ VERIFY)
Features that might leak:
- `return_1d`, `return_5d`, `return_20d`, `return_60d`

**Action Required**: Check if these are T-1 (lagged) or T+1 (forward). If forward, remove from feature set.

### 2. Missing ATR Delta
`atr_delta` was requested but not found in `v_d2_training`. Impact likely minimal (we have `natr_delta`).

### 3. Extreme Class Imbalance
- Class 3 (>30% MFE): 79.4% of samples
- Class 0-2: Only 20.6% combined

**Impact**: Model heavily biased toward predicting Class 3. SMOTE or undersampling may help.

---

## Verification Checklist

- [x] MAE/MFE excluded from features ✅
- [x] Exit dates/prices excluded ✅
- [x] Holding period excluded ✅
- [x] Raw prices excluded ✅
- [ ] Verify `return_1d/5d/20d/60d` are lagged, not forward ⚠️
- [ ] Add `atr_delta` to database (optional)
- [ ] Consider SMOTE for class imbalance

---

## Next Steps

1. **Verify return_* features** - Check if they're T-1 or T+1
2. **Re-train without suspicious features** - If `return_*` are forward, exclude them
3. **Add evaluation framework** - SHAP, confusion matrix, feature importance
4. **Address class imbalance** - SMOTE, cost-sensitive learning, or threshold tuning
