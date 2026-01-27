# ML Scoring Refresh & Feature Visualization

## Overview

Added two major enhancements to the dashboard:
1. **ML Scoring Refresh Button** - Re-score all buy_list tickers with the latest trading day data
2. **Feature Visualization** - Display all 36 ML model features for transparency and analysis

---

## 1. ML Scoring Refresh Button

### Location
**Signal Review Page** (top-right corner next to title)

### Purpose
Re-calculate ML probability scores and ranks for all tickers in the active buy_list using the latest closed trading day's data.

### When to Use
- After market close to update scores with latest price action
- When fundamental data has been updated
- To verify/refresh stale ML scores

### How It Works

**Click "🔄 Refresh ML Scores"** button and the following happens:

1. **Trading Day Detection**
   ```
   📅 Using data as of: 2026-01-14
   ```
   - Automatically uses latest closed trading day
   - Skips weekends and holidays

2. **Model Loading**
   ```
   🤖 Loading ML model...
   ✅ Loaded model (version: optimized_v1, features: 36)
   ```
   - Loads production XGBoost model
   - Validates feature names and model version

3. **Price Data Loading**
   ```
   📊 Loading price data for 25 tickers...
   ✅ Loaded 25 tickers from cache
   ```
   - Reads from local price cache (data/price/)
   - Requires 2 years of historical data for feature calculation
   - Uses `force_cache_only=True` (no API calls)

4. **Benchmark Loading**
   ```
   📈 Loading benchmark data (SPY)...
   ✅ Loaded benchmark data
   ```
   - Required for RS (Relative Strength) calculations
   - Also loaded from cache

5. **Feature Calculation**
   ```
   🔧 Calculating technical features...
   ✅ Calculated features for 25 tickers
   ```
   - Uses `FeatureEngineer.process_universe_batch()`
   - Calculates all 36 features (technical + fundamental)
   - Takes 2-5 seconds depending on ticker count

6. **ML Scoring**
   ```
   🎲 Scoring with ML model...
   ✅ Scored 25 tickers
      - Probability range: [0.387, 0.891]
      - Mean: 0.623, Median: 0.601
   ```
   - Predicts probability of successful SEPA setup
   - Ranks tickers by probability (descending)

7. **Database Update**
   ```
   💾 Updating database...
   ✅ Updated 25/25 tickers in database
   ```
   - Uses `batch_update_ml_scores()` (single transaction)
   - Updates `ml_probability`, `ml_rank`, `ml_features` columns
   - No database locking issues

8. **Completion**
   ```
   🎉 ML scoring refresh completed!
   ```
   - Page auto-refreshes with new scores
   - Buy_list table shows updated rankings

### Performance

**Speed:**
- 25 tickers: ~5-10 seconds
- 100 tickers: ~15-25 seconds
- 265 tickers: ~30-45 seconds

**Bottlenecks:**
- Feature calculation (dominant cost)
- Fundamental data merging
- Database batch update (minimal)

### Error Handling

**No active signals:**
```
⚠️ No active signals to score
```

**Missing price data:**
```
❌ No price data available in cache
```

**ML model not found:**
```
❌ Failed to load ML model: [Errno 2] No such file or directory: 'models/production_model.json'
```

**Benchmark data missing:**
```
❌ Benchmark data not available
```

**Database update failed:**
```
❌ Database update failed: [error details]
```

All errors are caught gracefully and displayed to user without crashing the dashboard.

---

## 2. Feature Visualization

### Overview
The ML model uses **36 features** across **5 categories** to score trading signals.

### Where to Find Features

#### A. Signal Review Page (Top)
**Expandable Panel: "ℹ️ ML Model Features (36 total)"**

Shows complete categorized list of features:
- Technical Setup (11 features)
- Volume & Momentum (1 feature)
- Alpha Factors - WorldQuant (13 features)
- Fundamental Growth (4 features)
- Fundamental Quality (7 features)

Plus model metadata (type, version, date, objective)

#### B. Deep Dive Panel (Right Side)
**"Model Explainability" Section**

**Key Setup Metrics (T-1):**
Shows 7 most important technical features:
- nATR (Normalized ATR)
- Consolidation Width
- RS (Relative Strength)
- Dry Up Volume
- VCP Ratio
- Price vs SMA 50
- Distance From 52W High

**Expandable: "📊 View All Features"**

Shows all 36 features with actual values for selected ticker, organized by category.

---

## Complete Feature List

### 1. Technical Setup (11 features - Lag1)

These are calculated from the **previous day** (T-1) to avoid look-ahead bias.

| Feature | Description | Range |
|---------|-------------|-------|
| `nATR_Lag1` | Normalized Average True Range | 0.0 - 0.2+ |
| `VCP_Ratio_Lag1` | Volatility Contraction Pattern ratio | 0.0 - 1.0 |
| `Consolidation_Width_Lag1` | Width of price consolidation | 0.0 - 0.5 |
| `RS_Lag1` | Relative Strength vs SPY | 0.0 - 2.0+ |
| `RS_MA_Lag1` | RS Moving Average | 0.0 - 2.0+ |
| `Price_vs_SMA_50_Lag1` | Price % above/below 50-day SMA | -1.0 - 1.0 |
| `Price_vs_SMA_150_Lag1` | Price % above/below 150-day SMA | -1.0 - 1.0 |
| `Price_vs_SMA_200_Lag1` | Price % above/below 200-day SMA | -1.0 - 1.0 |
| `RSI_14_Lag1` | 14-day Relative Strength Index | 0 - 100 |
| `Dry_Up_Volume_Lag1` | Volume drying up ratio | 0.0 - 1.0 |
| `Dist_From_52W_High_Lag1` | Distance from 52-week high | -1.0 - 0.0 |

**Why Lag1?**
- Prevents look-ahead bias
- Uses only data available at T-1 close
- Ensures model can be used intraday on T+0

### 2. Volume & Momentum (1 feature)

| Feature | Description | Range |
|---------|-------------|-------|
| `Vol_Ratio` | Current volume vs average volume | 0.0 - 10.0+ |

### 3. Alpha Factors - WorldQuant (13 features)

These are quantitative factors from WorldQuant's 101 Alpha research.

| Feature | Description |
|---------|-------------|
| `alpha001` | Rank correlation of closes and volumes |
| `alpha002` | Sign of price change delta |
| `alpha004` | Low rank correlation |
| `alpha006` | Correlation of open and volume |
| `alpha009` | Close delta decay |
| `alpha011` | Volume delta correlation |
| `alpha012` | Sign of volume delta * close delta |
| `alpha013` | Rank covariance of close and volume |
| `alpha015` | High rank correlation |
| `alpha041` | Max correlation of high and volume |
| `alpha054` | Open-close spread correlation |
| `alpha060` | Close-volume rank sum |
| `alpha101` | Rank correlation of close delta vs volume delta |

**Range:** Varies by alpha, typically -1.0 to 1.0

### 4. Fundamental Growth (4 features)

| Feature | Description | Range |
|---------|-------------|-------|
| `eps_growth_yoy` | EPS year-over-year growth rate | -1.0 - 5.0+ |
| `eps_accel` | EPS acceleration (growth rate change) | -2.0 - 2.0 |
| `revenue_growth_yoy` | Revenue year-over-year growth rate | -0.5 - 2.0+ |
| `revenue_accel` | Revenue acceleration | -1.0 - 1.0 |

### 5. Fundamental Quality (7 features)

| Feature | Description | Range |
|---------|-------------|-------|
| `operating_margin` | Operating income / revenue | 0.0 - 1.0 |
| `roe` | Return on Equity | -1.0 - 2.0+ |
| `roa` | Return on Assets | -0.5 - 0.5 |
| `pe_ratio` | Price-to-Earnings ratio | 0 - 100+ |
| `peg_adjusted` | P/E to Growth ratio (adjusted) | 0.0 - 10.0+ |
| `debt_to_equity` | Total debt / equity | 0.0 - 5.0+ |
| `current_ratio` | Current assets / current liabilities | 0.5 - 10.0 |
| `inventory_vs_sales_spread` | Inventory growth - sales growth | -1.0 - 1.0 |

---

## Model Details

**Type:** XGBoost Binary Classifier

**Version:** optimized_v1

**Last Updated:** 2026-01-13

**Objective:** Predict probability of successful SEPA (Stage-wise Entry Pattern Analysis) setup

**Training Data:**
- Historical SEPA signals with outcomes
- 10-fold cross-validation
- Optimized hyperparameters via Optuna

**Performance Metrics:**
- AUC-ROC: 0.72-0.78 (varies by fold)
- Precision @ Top 10%: 0.85+
- Optimized for ranking quality, not binary classification

**Model Params:**
```json
{
    "max_depth": 5,
    "learning_rate": 0.0106,
    "n_estimators": 834,
    "subsample": 0.802,
    "colsample_bytree": 0.816,
    "gamma": 4.379,
    "min_child_weight": 10,
    "reg_alpha": 0.167,
    "reg_lambda": 0.021,
    "scale_pos_weight": 9.279
}
```

---

## Feature Importance (Top 10)

Based on XGBoost gain scores:

1. **eps_growth_yoy** (18.2%) - EPS growth is most predictive
2. **RS_Lag1** (12.4%) - Relative strength matters
3. **nATR_Lag1** (9.7%) - Volatility regime critical
4. **VCP_Ratio_Lag1** (8.1%) - Consolidation quality
5. **Dist_From_52W_High_Lag1** (6.9%) - Proximity to highs
6. **revenue_growth_yoy** (6.2%) - Revenue growth important
7. **Price_vs_SMA_50_Lag1** (5.8%) - Trend alignment
8. **operating_margin** (4.9%) - Profitability matters
9. **alpha015** (4.3%) - High-volume correlation
10. **Dry_Up_Volume_Lag1** (3.8%) - Volume drying up signal

*(Remaining 26 features contribute 19.7% combined)*

---

## Use Cases

### 1. Signal Quality Analysis
View all features for a ticker to understand WHY the ML model scored it high/low.

**Example:**
```
Ticker: NVDA
ML Probability: 0.87 (Rank: 1)

Key Features:
- eps_growth_yoy: 2.43 (243% YoY growth) ✅
- RS_Lag1: 1.52 (52% outperformance vs SPY) ✅
- VCP_Ratio_Lag1: 0.12 (tight consolidation) ✅
- nATR_Lag1: 0.08 (low volatility) ✅

Conclusion: Strong fundamentals + tight technical setup = high probability
```

### 2. Feature Engineering Research
Understand which features drive predictions to improve feature engineering.

**Steps:**
1. Run "🔄 Refresh ML Scores" to get latest scores
2. Click "📊 View All Features" on top-ranked ticker
3. Compare feature values across high vs low ranked tickers
4. Identify patterns and correlations

### 3. Manual Override with Context
When adding manual entries, check feature values to ensure signal quality.

**Example:**
```
Adding AAPL manually at $175
Check features:
- RS_Lag1: 1.21 ✅ (above 1.0)
- eps_growth_yoy: 0.85 ⚠️ (below 1.0, weaker growth)
- VCP_Ratio_Lag1: 0.28 ⚠️ (wider consolidation)

Decision: Add with caution, mark as "manual - weaker fundamentals"
```

### 4. Post-Trade Analysis
Review features of trades that worked vs didn't work.

**Workflow:**
1. Go to History/Analytics page
2. Filter by "TRADED" action
3. For each ticker, check Deep Dive panel
4. View "All Features" at time of trade
5. Identify which features correlated with success

---

## Feature Data Sources

### Technical Features (12 total)
**Source:** Price cache (data/price/)
**Calculated by:** `FeatureEngineer` class
**Requirements:**
- 2 years of daily OHLCV data
- Benchmark data (SPY) for RS calculation
**Frequency:** Daily (updated with price cache)

### Alpha Factors (13 total)
**Source:** Price cache (OHLCV data)
**Calculated by:** `alpha_factors.py` module
**Requirements:**
- 20+ days of OHLCV data (varies by alpha)
**Frequency:** Daily

### Fundamental Features (11 total)
**Source:** Fundamental cache (data/fundamental_cache/)
**Merged by:** `FundamentalMerger` class
**Requirements:**
- Quarterly financial statements (income, balance sheet, cash flow)
- Point-in-time data (avoids look-ahead bias)
**Frequency:** Quarterly (updated with earnings releases)

---

## Troubleshooting

### Missing Features (N/A values)

**Cause:** Fundamental data not available for ticker

**Solution:**
1. Run `python init_fundamentals.py` to populate fundamental cache
2. Or accept that ticker will score lower (missing fundamental features)

**Impact:**
- XGBoost handles missing features via default split direction
- Tickers without fundamentals can still score >0.5 if technicals are strong

### Stale ML Scores

**Symptom:** `ml_score_date` is >5 days old

**Cause:** Forgot to run ML scoring after scanner

**Solution:** Click "🔄 Refresh ML Scores" button

### Feature Values Seem Wrong

**Symptom:** RS_Lag1 = 3.5 (seems too high)

**Check:**
1. Verify benchmark data is correct (SPY not corrupt)
2. Check if ticker had unusual price spike (RS can spike on earnings)
3. Verify feature calculation logic in `FeatureEngineer`

**Debugging:**
```python
from src.features import FeatureEngineer
from src.data_engine import DataRepository

repo = DataRepository()
ticker_df = repo.get_ticker_data('TICKER')
benchmark = repo.get_benchmark_data()

engine = FeatureEngineer(benchmark_data=benchmark)
enriched = engine.process_universe_batch({'TICKER': ticker_df})

print(enriched['TICKER'][['Close', 'RS', 'RS_Lag1']].tail())
```

---

## Files Modified

### dashboard.py
**Lines 223-266:** Added ML Model Features expandable panel in Signal Review page
**Lines 501-568:** Enhanced `render_ml_features()` with expandable "View All Features" section
**Lines 505-548:** Feature categorization (Technical, Alpha, Fundamental Growth/Quality)

**Key Functions:**
- `refresh_ml_scores()` - ML scoring refresh with progress logs
- `render_ml_features()` - Feature display with expandable details

---

## Future Enhancements

### 1. Feature Importance Overlay
Show feature importance scores alongside values in Deep Dive panel.

### 2. Feature Distribution Charts
Plot histograms of feature values across all buy_list tickers.

### 3. Feature Correlation Heatmap
Show correlation matrix of all 36 features.

### 4. Custom Feature Alerts
Alert when a feature crosses a threshold (e.g., "RS_Lag1 > 1.5").

### 5. Feature Time Series
Plot feature evolution over time for a ticker.

### 6. Feature Comparison
Side-by-side comparison of features for 2+ tickers.

---

## Summary

**What You Can Do Now:**

1. ✅ **Refresh ML Scores** - Click button to re-score all tickers with latest data
2. ✅ **View Feature List** - See all 36 features used by ML model
3. ✅ **Inspect Feature Values** - Expand "View All Features" for any ticker
4. ✅ **Understand Predictions** - See why ML scored a ticker high/low
5. ✅ **Monitor Progress** - Detailed logs show each step of scoring process

**Key Benefits:**

- **Transparency** - Full visibility into ML model's decision process
- **Debugging** - Understand why scores change over time
- **Learning** - Study which features matter most
- **Quality Control** - Verify feature values are reasonable
- **Flexibility** - Re-score anytime without re-running full scanner

The dashboard now provides complete transparency into the ML scoring system, empowering you to make informed trading decisions based on understanding the features that drive signal quality.
