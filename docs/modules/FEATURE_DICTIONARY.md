# Feature Dictionary
**Version**: v4.0
**Last Updated**: 2026-03-14
**Purpose**: Comprehensive documentation of all features in the `daily_features` table

---

## 📊 Feature Categories

### **Raw Dollar Features** 💰
Features stored in absolute dollar amounts (not normalized or percentage-based):

| Feature | Description | Calculation | Unit |
|---------|-------------|-------------|------|
| `close` | Closing price | Direct from price_data | USD |
| `open` | Opening price | Direct from price_data | USD |
| `high` | Daily high | Direct from price_data | USD |
| `low` | Daily low | Direct from price_data | USD |
| `sma_50` | 50-day simple moving average | `AVG(close) OVER w50` | USD |
| `sma_150` | 150-day simple moving average | `AVG(close) OVER w150` | USD |
| `sma_200` | 200-day simple moving average | `AVG(close) OVER w200` | USD |
| `high_52w` | 52-week high | `MAX(close) OVER w252` | USD |
| `low_52w` | 52-week low | `MIN(close) OVER w252` | USD |
| `highest_high_20d` | 20-day high of highs | `MAX(high) OVER w20` | USD |
| `lowest_low_20d` | 20-day low of lows | `MIN(low) OVER w20` | USD |
| `atr_20d` | 20-day Average True Range | `AVG(true_range) OVER w20` | USD |
| `turnover` | Daily dollar volume | `close * volume` | USD |

**Log Transformations** (computed in views, not stored):
- All raw dollar features should be log-transformed for ML models
- Example: `log_close = LN(close)`, `log_sma_50 = LN(sma_50)`
- Computed in `v_d2_training` view

---

## 🏗️ Feature Groups

### **1. Moving Averages & Trends** (8 features)

#### `sma_50`, `sma_150`, `sma_200`
- **Type**: Raw Dollar
- **Purpose**: Trend identification (Mark Minervini SEPA trend template)
- **Calculation**: Simple moving average of closing price
  ```sql
  AVG(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN N-1 PRECEDING AND CURRENT ROW)
  ```
- **Usage**: Trend filters (C1: close > SMA150 > SMA200)

#### `close_above_sma200`
- **Type**: Boolean flag
- **Purpose**: Quick trend check
- **Calculation**: `CASE WHEN close > sma_200 THEN TRUE ELSE FALSE END`
- **Usage**: Bullish trend filter

#### `price_vs_sma_50`, `price_vs_sma_150`, `price_vs_sma_200`
- **Type**: Percentage distance
- **Purpose**: How far price is from key moving averages
- **Calculation**: `((close - sma_N) / NULLIF(sma_N, 0)) * 100`
- **Unit**: Percentage (positive = above SMA, negative = below)
- **Usage**: Overbought/oversold conditions

#### `price_vs_sma_50_pct_chg`, `price_vs_sma_150_pct_chg`, `price_vs_sma_200_pct_chg`
- **Type**: Percentage change (delta)
- **Purpose**: Rate of change in price-to-SMA distance
- **Calculation**:
  ```sql
  ((price_vs_sma_N - LAG(price_vs_sma_N, 1) OVER ticker_date)
   / NULLIF(ABS(LAG(price_vs_sma_N, 1) OVER ticker_date), 0)) * 100
  ```
- **Unit**: Percentage
- **Usage**: Acceleration/deceleration of trend strength

#### `sma_50_slope`
- **Type**: Percentage slope (per day)
- **Purpose**: Direction and strength of SMA50 trend
- **Calculation**:
  ```sql
  ((sma_50 - LAG(sma_50, 10) OVER ticker_date)
   / NULLIF(LAG(sma_50, 10) OVER ticker_date, 0)) / 10.0 * 100
  ```
- **Unit**: Percentage per day
- **Usage**: Trend acceleration (positive = uptrend strengthening)

---

### **2. Relative Strength & Momentum** (22 features)

#### `rs_line_log`, `rs_line_delta`
- **Type**: Log ratio, percentage change
- **Purpose**: Price performance vs SPY (relative strength)
- **Calculation**:
  ```sql
  rs_line_log = LN(close / NULLIF(spy_close, 0))
  rs_line_delta = (price_vs_spy / NULLIF(LAG(price_vs_spy, 1) OVER ticker_date, 0) - 1) * 100
  ```
- **Unit**: Log points, percentage
- **Usage**: RS line uptrend detection (outperformance vs market)

#### `rs_line_uptrend`
- **Type**: Boolean flag
- **Purpose**: Is stock outperforming market?
- **Calculation**: `price_vs_spy > AVG(price_vs_spy) OVER w63`
- **Usage**: SEPA C9 filter

#### `rs_line_lag_delta`
- **Type**: Percentage change (lagged)
- **Purpose**: Previous period's RS momentum
- **Calculation**: `LAG(rs_line_delta, 1) OVER ticker_date`
- **Usage**: Momentum continuation signals

#### `rs_rating` (Composite RS Score)
- **Type**: Weighted momentum score
- **Purpose**: Minervini-style RS rating (multi-timeframe momentum)
- **Calculation**:
  ```sql
  0.4 * mom_63d + 0.2 * mom_126d + 0.2 * mom_189d + 0.2 * mom_252d
  ```
- **Unit**: Decimal (e.g., 0.25 = 25% weighted average return)
- **Usage**: Identifies strongest momentum stocks

#### `rs`, `rs_ma`
- **Type**: Momentum score, smoothed momentum
- **Purpose**: Current RS and trend
- **Calculation**:
  ```sql
  rs = rs_rating  -- Alias for consistency
  rs_ma = AVG(rs_rating) OVER w63  -- 63-day smoothing
  ```
- **Usage**: RS breakout detection (rs > rs_ma)

#### `rs_pct_chg`, `rs_ma_pct_chg`
- **Type**: Percentage change
- **Purpose**: Acceleration of RS momentum
- **Calculation**:
  ```sql
  ((rs - LAG(rs, 1) OVER ticker_date) / NULLIF(ABS(LAG(rs, 1) OVER ticker_date), 0)) * 100
  ```
- **Unit**: Percentage
- **Usage**: Detect inflection points in momentum

#### `mom_21d`, `mom_63d`, `mom_126d`, `mom_189d`, `mom_252d`
- **Type**: Percentage returns
- **Purpose**: Multi-timeframe momentum (1m, 3m, 6m, 9m, 12m)
- **Calculation**:
  ```sql
  (close / NULLIF(LAG(close, N) OVER ticker_date, 0) - 1) * 100
  ```
- **Unit**: Percentage
- **Usage**: Weighted RS rating components

#### `rs_velocity`
- **Type**: Rate of change (acceleration)
- **Purpose**: How fast RS is changing
- **Calculation**: `(rs_rating - LAG(rs_rating, 5) OVER ticker_date) / 5.0`
- **Unit**: RS points per day
- **Usage**: Early ignition detection

#### `price_accel_10d`
- **Type**: Price acceleration
- **Purpose**: Change in price velocity
- **Calculation**:
  ```sql
  ((close - LAG(close, 10) OVER ticker_date) / 10.0)
  - ((LAG(close, 10) OVER ticker_date - LAG(close, 20) OVER ticker_date) / 10.0)
  ```
- **Unit**: USD per day (acceleration)
- **Usage**: Detect momentum inflection

#### Cross-Sectional Ranks (Phase C features)
- **`RS_Sector_Rank`**: Percentile rank within sector (0-100)
- **`RS_vs_Sector`**: Stock RS minus sector median RS
- **`Sector_Momentum`**: Sector-wide RS median
- **`RS_Industry_Rank`**: Percentile rank within industry
- **`RS_vs_Industry`**: Stock RS minus industry median RS
- **`Industry_Momentum`**: Industry-wide RS median
- **Purpose**: Sector/industry rotation analysis
- **Usage**: Identify sector leaders

---

### **3. Volume & Liquidity** (7 features)

#### `volume`
- **Type**: Raw count
- **Purpose**: Trading activity
- **Unit**: Shares
- **Calculation**: Direct from price_data (`UBIGINT`)
- **Note**: Always cast to BIGINT for subtraction operations

#### `vol_avg_20`, `vol_avg_50`
- **Type**: Raw volume average
- **Purpose**: Volume baselines
- **Calculation**: `AVG(volume) OVER wN`
- **Unit**: Shares
- **Usage**: Volume ratio calculations

#### `vol_ratio`
- **Type**: Volume ratio
- **Purpose**: Current volume vs 50-day average
- **Calculation**: `volume / NULLIF(vol_avg_50, 0)`
- **Unit**: Decimal (1.0 = average, 1.5 = 50% above average)
- **Usage**: SEPA C10 breakout volume filter (>1.3)

#### `dry_up_volume`
- **Type**: Volume contraction ratio
- **Purpose**: Detect volume drying up during consolidation
- **Calculation**: `vol_avg_5 / NULLIF(vol_avg_50, 0)`
- **Unit**: Decimal (<0.7 = significant contraction)
- **Usage**: VCP pattern detection

#### `dry_up_volume_pct_chg`
- **Type**: Percentage change
- **Purpose**: Rate of volume contraction/expansion
- **Calculation**:
  ```sql
  ((dry_up_volume - LAG(dry_up_volume, 1) OVER ticker_date)
   / NULLIF(LAG(dry_up_volume, 1) OVER ticker_date, 0)) * 100
  ```
- **Unit**: Percentage
- **Usage**: Detect acceleration in volume drying up

#### `turnover`
- **Type**: Raw Dollar
- **Purpose**: Dollar volume (liquidity measure)
- **Calculation**: `close * volume`
- **Unit**: USD
- **Note**: Should be log-transformed for ML

#### `volume_acceleration`
- **Type**: Volume change (second derivative)
- **Purpose**: Rate of change in volume change
- **Calculation**:
  ```sql
  (CAST(volume AS BIGINT) - LAG(CAST(volume AS BIGINT), 1) OVER ticker_date)
  - (LAG(CAST(volume AS BIGINT), 1) OVER ticker_date
     - LAG(CAST(volume AS BIGINT), 2) OVER ticker_date)
  ```
- **Unit**: Shares (acceleration)
- **Usage**: Detect volume surges

#### `return_1d`, `return_5d`
- **Type**: Percentage return
- **Purpose**: Short-term price performance
- **Calculation**:
  ```sql
  (close / NULLIF(LAG(close, N) OVER ticker_date, 0) - 1) * 100
  ```
- **Unit**: Percentage
- **Usage**: Daily/weekly momentum

---

### **4. Volatility & Range** (18 features)

#### `atr_20d`
- **Type**: Raw Dollar (Average True Range)
- **Purpose**: Volatility measure for position sizing
- **Calculation**:
  ```sql
  true_range = GREATEST(high - low, ABS(high - prev_close), ABS(low - prev_close))
  atr_20d = AVG(true_range) OVER w20
  ```
- **Unit**: USD
- **Usage**: Stop-loss placement (2× ATR), position sizing

#### `natr` (Normalized ATR)
- **Type**: Percentage volatility
- **Purpose**: Price-normalized volatility (comparable across stocks)
- **Calculation**: `(atr_20d / NULLIF(close, 0)) * 100`
- **Unit**: Percentage of price
- **Usage**: Cross-stock volatility comparison

#### `natr_pct_chg`
- **Type**: Percentage change
- **Purpose**: Change in volatility (volatility acceleration)
- **Calculation**:
  ```sql
  ((natr - LAG(natr, 1) OVER ticker_date) / NULLIF(LAG(natr, 1) OVER ticker_date, 0)) * 100
  ```
- **Unit**: Percentage
- **Usage**: Detect volatility expansion/contraction

#### `atr_pct_chg`
- **Type**: Percentage change
- **Purpose**: Raw ATR momentum
- **Calculation**: Same as natr_pct_chg but for atr_20d
- **Unit**: Percentage
- **Usage**: Volatility trend

#### `vcp_ratio` (Volatility Contraction Pattern)
- **Type**: Volatility ratio
- **Purpose**: Detect volatility squeeze (VCP setup)
- **Calculation**: `atr_10 / NULLIF(atr_50, 0)`
- **Unit**: Decimal (<0.5 = significant contraction)
- **Usage**: Mark O'Neil VCP pattern detection

#### `vcp_ratio_pct_chg`
- **Type**: Percentage change
- **Purpose**: Rate of volatility contraction
- **Calculation**: Standard pct_chg formula
- **Unit**: Percentage
- **Usage**: Identify tightening coil patterns

#### `consolidation_width`
- **Type**: Percentage range
- **Purpose**: How tight is the 20-day consolidation?
- **Calculation**: `((highest_high_20d - lowest_low_20d) / NULLIF(close, 0)) * 100`
- **Unit**: Percentage
- **Usage**: VCP width criterion (<10% for tight base)

#### `consolidation_width_pct_chg`
- **Type**: Percentage change
- **Purpose**: Rate of base tightening
- **Calculation**: Standard pct_chg formula
- **Unit**: Percentage
- **Usage**: Detect coiling action

#### `consolidation_duration`
- **Type**: Day count
- **Purpose**: How many tight days in past 20?
- **Calculation**: `SUM(CASE WHEN (high-low) < 0.5*atr_14 THEN 1 ELSE 0 END) OVER w20`
- **Unit**: Days
- **Usage**: VCP duration filter (>10 days preferred)

#### Distance from Highs/Lows

**`dist_from_52w_high`, `Dist_From_52W_High`**
- **Type**: Percentage distance
- **Purpose**: How far from 52-week high?
- **Calculation**: `(close - high_52w) / NULLIF(high_52w, 0) * 100`
- **Unit**: Percentage (negative, e.g., -5% = 5% below high)
- **Usage**: SEPA C8 (must be >85% of high)

**`dist_from_52w_low`, `Dist_From_52W_Low`**
- **Type**: Percentage distance
- **Purpose**: How far above 52-week low?
- **Calculation**: `(close / NULLIF(low_52w, 0) - 1) * 100`
- **Unit**: Percentage (positive, e.g., 30% = 30% above low)
- **Usage**: SEPA C7 (must be >30% above low)

**`dist_from_20d_high`, `Dist_From_20D_High`**
- **Type**: Percentage distance
- **Purpose**: Distance from recent high
- **Calculation**: `(close / NULLIF(highest_high_20d, 0) - 1) * 100`
- **Unit**: Percentage
- **Usage**: Pullback depth measurement

**`dist_from_20d_low`, `Dist_From_20D_Low`**
- **Type**: Percentage distance
- **Purpose**: Distance from recent low
- **Calculation**: `(close / NULLIF(lowest_low_20d, 0) - 1) * 100`
- **Unit**: Percentage
- **Usage**: Rally strength measurement

#### Delta Features (Percentage Change)

**`Dist_From_52W_High_pct_chg`, `dist_from_52w_low_pct_chg`**
- **Purpose**: How fast is stock approaching/leaving highs/lows?
- **Calculation**: Standard pct_chg formula
- **Unit**: Percentage
- **Usage**: Breakout momentum

**`low_52w_pct_chg`, `high_52w_pct_chg`**
- **Purpose**: How fast are the 52w boundaries moving?
- **Calculation**: Standard pct_chg formula
- **Unit**: Percentage
- **Usage**: Trend strength (rising lows = uptrend)

**`Dist_From_20D_High_pct_chg`, `dist_from_20d_low_pct_chg`**
- **Purpose**: Short-term range expansion/contraction
- **Calculation**: Standard pct_chg formula
- **Unit**: Percentage

**`highest_high_20d_pct_chg`, `lowest_low_20d_pct_chg`**
- **Purpose**: Rate of change in 20-day boundaries
- **Calculation**: Standard pct_chg formula
- **Unit**: Percentage
- **Usage**: Consolidation vs expansion detection

---

### **5. Technical Oscillators** (7 features)

#### `rsi_14`
- **Type**: Oscillator (0-100)
- **Purpose**: Overbought/oversold conditions
- **Calculation**:
  ```sql
  avg_gain = AVG(CASE WHEN close > prev_close THEN close - prev_close ELSE 0 END) OVER w14
  avg_loss = AVG(CASE WHEN close < prev_close THEN prev_close - close ELSE 0 END) OVER w14
  rsi_14 = 100 - (100 / (1 + (avg_gain / NULLIF(avg_loss, 0))))
  ```
- **Unit**: 0-100 scale (>70 overbought, <30 oversold)
- **Usage**: Divergence detection, entry timing

#### `rsi_14_pct_chg`
- **Type**: Percentage change
- **Purpose**: RSI momentum
- **Calculation**: Standard pct_chg formula
- **Unit**: Percentage
- **Usage**: RSI trend strength

#### `is_green_day`
- **Type**: Boolean flag
- **Purpose**: Up day vs down day
- **Calculation**: `CASE WHEN close >= open THEN 1 ELSE 0 END`
- **Usage**: Accumulation/distribution patterns

#### `green_days_ratio_20d`
- **Type**: Ratio (0-1)
- **Purpose**: Percentage of up days in past 20
- **Calculation**: `AVG(CAST(is_green_day AS DOUBLE)) OVER w20`
- **Unit**: Decimal (0.65 = 65% green days)
- **Usage**: Accumulation strength

#### `breakout`
- **Type**: Boolean flag
- **Purpose**: Price broke above 20-day high?
- **Calculation**:
  ```sql
  CASE WHEN close > MAX(close) OVER (PARTITION BY ticker ORDER BY date
       ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) THEN 1 ELSE 0 END
  ```
- **Usage**: SEPA C10 breakout detection

#### `breakout_momentum`
- **Type**: ATR-normalized distance
- **Purpose**: How explosive is the breakout?
- **Calculation**: `(close - high_20d) / NULLIF(atr_14, 0)`
- **Unit**: ATR multiples (>1.0 = strong thrust)
- **Usage**: Breakout quality filter

#### `immediate_thrust`
- **Type**: Price acceleration
- **Purpose**: Second derivative of price (jerk)
- **Calculation**: `close - 2*LAG(close,1) + LAG(close,2)`
- **Unit**: USD (acceleration)
- **Usage**: Detect explosive moves

---

### **6. Fundamentals** (24 features)
**Source**: Joined from `fundamentals` table (point-in-time via `report_date`)

#### Growth Metrics
- **`eps_diluted`**: Earnings per share (raw, TTM)
- **`revenue_growth_yoy`**: Revenue growth % YoY
- **`eps_growth_yoy`**: EPS growth % YoY
- **`net_income_growth_yoy`**: Net income growth % YoY
- **`eps_accel`**: EPS growth acceleration (QoQ)
- **`revenue_accel`**: Revenue growth acceleration (QoQ)
- **`revenue_cagr_3y`**: 3-year revenue CAGR
- **`eps_stability_score`**: Consistency of EPS growth (0-1)

#### Quality Metrics
- **`debt_to_equity`**: Debt-to-equity ratio
- **`current_ratio`**: Current assets / current liabilities
- **`gross_margin`**: Gross margin %
- **`operating_margin`**: Operating margin %
- **`roe`**: Return on equity %
- **`roa`**: Return on assets %
- **`fcf_margin`**: Free cash flow margin %
- **`earnings_quality_score`**: Composite quality (0-1)
- **`gross_margin_trend`**: 4Q trend in gross margin

#### Valuation Metrics
- **`pe_ratio`**: Price-to-earnings ratio ⚠️ **Currently NULL** (needs backfill)
- **`ps_ratio`**: Price-to-sales ratio ⚠️ **Currently NULL**
- **`pb_ratio`**: Price-to-book ratio ⚠️ **Currently NULL**

#### Timing
- **`days_since_report`**: Days since last earnings report
- **Purpose**: Staleness of fundamental data
- **Calculation**: `date - report_date`
- **Usage**: Weight recent reports higher

**Note**: All fundamentals should be log-transformed for ML (except ratios/percentages)

---

### **7. WQ101 Fast Alphas** (15 features)
**Source**: Phase B (Python groupby operations)

| Alpha | Description | Key Components |
|-------|-------------|----------------|
| `alpha001` | Volume-return correlation surprise | `corr(rank(Δlog(vol)), rank((close-open)/open), 6)` |
| `alpha002` | Sign reversal on volume change | `sign(Δclose) × (-1 × Δvolume)` |
| `alpha004` | Low momentum with volume | Conditional on `min/max(Δclose,1)` over 5d |
| `alpha006` | Open-VWAP correlation | `corr(open, volume, 10)` |
| `alpha009` | VWAP spread momentum | `rank(ts_max(vwap-close,3)) + rank(Δvol,3)` |
| `alpha011` | Volume concentration | `(close - low) - (high - close) / vol` |
| `alpha012` | Volume-weighted spread | `sign(Δvolume) × (-(close - open))` |
| `alpha013` | VWAP deviation | `rank(covariance(rank(close), rank(vol), 5))` |
| `alpha015` | High-volume correlation | `corr(rank(high), rank(vol), 3)` |
| `alpha041` | High-VWAP spread power | `(high × low)^0.5 - vwap` |
| `alpha046` | Close-delay spread normalized | `(close - prev_close) / prev_close` variations |
| `alpha049` | High ratio delay | Complex lagged high ratios |
| `alpha054` | Open-close correlation | `corr(open, close, 10)` variations |
| `alpha060` | Volume-weighted close rank | `2×rank(close)-rank(high)-rank(low) / vol` |
| `alpha101` | High-low log ratio | `(close - open) / ((high - low) + 0.001)` |

**Notes**:
- All alphas are **cross-sectionally ranked** (not time-series ranked)
- Use `include_groups=False` in pandas groupby to avoid FutureWarning
- Replace infinities/NaNs with 0 after computation
- **alpha051** removed (not in target feature set)

---

### **8. M03 Regime Features** (7 features)
**Source**: Phase D (parquet ingest) + Phase E (derived)

#### Base Features (Phase D)
- **`m03_score`**: Composite macro regime score (-1 to +1)
- **`m03_pillar_trend`**: Trend pillar component
- **`m03_pillar_liq`**: Liquidity pillar component
- **`m03_pillar_risk`**: Risk appetite pillar component

#### Derived Features (Phase E)
- **`m03_delta_5d`**: 5-day change in M03 score (regime shift detection)
- **`m03_delta_20d`**: 20-day change (longer-term regime trend)
- **`m03_regime_vol`**: 20-day rolling std of M03 score (regime stability)

**Purpose**: Market regime context for stock selection
**Usage**: Weight stock picks by macro environment

---

## 🔢 Calculation Patterns

### **Standard Percentage Change Formula**
For all `*_pct_chg` delta features:
```sql
((current_value - LAG(current_value, 1) OVER ticker_date)
 / NULLIF(ABS(LAG(current_value, 1) OVER ticker_date), 0)) * 100
```

**Key Points**:
- ✅ Use `ABS()` in denominator to handle negative values correctly
- ✅ Handle NULL on first row per ticker (warm-up period)
- ✅ Use percentage change, NOT absolute spread
- ✅ Multiply by 100 to get percentage unit

**Example**:
```
price_vs_sma_50:      t0 = -2%,  t1 = -1%
price_vs_sma_50_pct_chg = ((-1) - (-2)) / ABS(-2) * 100 = 50%  (moving toward SMA)
```

### **Window Definitions**
```sql
WINDOW
    ticker_date AS (PARTITION BY ticker ORDER BY date),
    w5  AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
    w10 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW),
    w14 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW),
    w20 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
    w50 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW),
    w63 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 62 PRECEDING AND CURRENT ROW),
    w150 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 149 PRECEDING AND CURRENT ROW),
    w200 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW),
    w252 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW)
```

---

## 📐 Feature Type Summary

| Type | Count | Examples | ML Preprocessing |
|------|-------|----------|------------------|
| **Raw Dollar** | 13 | close, sma_50, atr_20d, turnover | **Log transform** |
| **Percentage** | 35 | price_vs_sma_50, mom_21d, natr | Direct use (already normalized) |
| **Ratio** | 12 | vol_ratio, vcp_ratio, dry_up_volume | Direct use (0-2 range typically) |
| **Boolean** | 4 | close_above_sma200, is_green_day, breakout | Direct use (0/1) |
| **Count/Days** | 2 | consolidation_duration, days_since_report | Log transform or direct |
| **Rank (0-100)** | 6 | RS_Sector_Rank, RS_Industry_Rank | Direct use (percentile) |
| **Score** | 8 | rs_rating, m03_score, alphas | Direct use (normalized) |

**Total**: 72 features (excluding OHLCV raw inputs)

---

## ⚠️ Important Notes

### **NULL Handling**
1. **First-row NULLs**: All `*_pct_chg` features will be NULL on first row per ticker (no prior data)
   - **Solution**: Filter training data to exclude first N days per ticker, or use `COALESCE(delta, 0)`

2. **Missing Fundamentals**: `pe_ratio`, `ps_ratio`, `pb_ratio` are 100% NULL
   - **Root Cause**: Not computed in `fundamental_processor.py`
   - **Action**: Data backfill required (Milestone 3.6)

3. **Volume Casting**: `volume` is `UBIGINT`, must cast to `BIGINT` for subtraction
   ```sql
   CAST(volume AS BIGINT) - LAG(CAST(volume AS BIGINT), 1)
   ```

### **Log Transforms**
- Computed in `v_d2_training` view (not stored in `daily_features`)
- Apply to all raw dollar features before ML training
- Use `LN(NULLIF(feature, 0))` to handle zeros

### **Feature Versioning**
- Current version: **v4.0**
- Breaking changes (add/remove features) require version bump
- Models track `feature_version` in registry

---

## 🔗 Related Documentation

- [Feature Pipeline](c:/Users/Hang/PycharmProjects/quantamental/src/feature_pipeline.py) - Computation logic
- [View Manager](c:/Users/Hang/PycharmProjects/quantamental/src/view_manager.py) - View definitions
- [Feature Config](c:/Users/Hang/PycharmProjects/quantamental/src/feature_config.py) - M01/M02 feature lists
- [MEMORY.md](C:/Users/Hang/.claude/projects/c--Users-Hang-PycharmProjects-quantamental/memory/MEMORY.md) - Architecture overview
