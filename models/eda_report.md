# Feature Evaluation Report (Quant-Standard)

**Generated:** 2026-02-19 22:16:46
**Target Variable:** `return_pct`
**Composite Weights:** 40% IC + 30% Stability + 30% KS
**Correlation Threshold:** 0.7

---

## Section 0: Dataset Overview

### Target Variable Distribution (`return_pct`)

| Statistic | Value |
|-----------|-------|
| Count | 7,667 |
| Mean | +0.04% |
| Std Dev | 0.17% |
| Min | -0.62% |
| Max | +3.30% |
| Median | +0.00% |
| Q1 (25%) | -0.03% |
| Q3 (75%) | +0.06% |
| Skewness | +5.72 |
| Kurtosis | 64.1 |

| Outcome | Count | % |
|---------|-------|---|
| Positive (> 0%) | 3,534 | 46.1% |
| > +10% | 0 | 0.0% |
| > +20% | 0 | 0.0% |
| Negative (< 0%) | 3,479 | 45.4% |
| < -10% | 0 | 0.0% |

### Return Distribution (5% Buckets)

| Bucket | Count | % | Bar |
|--------|-------|---|-----|
| [-5, 0)% | 3,479 | 45.4% | ████████████████ |
| [0, 5)% | 4,188 | 54.6% | ████████████████████ |

### Temporal Coverage

- **Date Range:** 2020-08-06 to 2026-02-18
- **Unique Entry Dates:** 1,245

| Year | Samples | % |
|------|---------|---|
| 2020 | 581 | 7.3% |
| 2021 | 1,879 | 23.6% |
| 2022 | 639 | 8.0% |
| 2023 | 1,160 | 14.6% |
| 2024 | 1,865 | 23.4% |
| 2025 | 1,429 | 17.9% |
| 2026 | 419 | 5.3% |

### Ticker Distribution

- **Unique Tickers:** 1,460
- **Top 10 Concentration:** 2.0% of samples

| Ticker | Samples |
|--------|---------|
| AVGO | 17 |
| MCK | 16 |
| COR | 16 |
| LLY | 16 |
| HIMS | 16 |
| SMCI | 16 |
| RMBS | 15 |
| HCA | 15 |
| CTAS | 15 |
| SGI | 15 |

### MFE Analysis (Maximum Favorable Excursion)

*Peak return % during trade (best possible exit)*

| Statistic | Value |
|-----------|-------|
| Count | 7,972 |
| Mean | +0.1% |
| Std Dev | 0.1% |
| Min | +0.0% |
| Max | +4.5% |
| Median | +0.1% |
| > 20% | 0.0% of trades |
| > 50% | 0.0% of trades |

### MAE Analysis (Maximum Adverse Excursion)

*Largest drawdown % during trade*

| Statistic | Value |
|-----------|-------|
| Mean | -0.1% |
| Median | -0.1% |
| Min (worst DD) | -0.8% |
| Max (best case) | +0.0% |

## Section 1: SEPA Audit (Entry Criteria Validation)

> **Purpose:** Validate SEPA C1-C11 criteria effectiveness by examining
> how key entry features relate to trade outcomes across deciles.

### rs_rating
*C9 - Relative Strength (core ranking)*

| Decile | Count | Mean | Median | Min | Max | Std | Win% |
|--------|-------|------|--------|-----|-----|-----|------|
| D1 | 700 | +0.0% | +0.0% | -0.2% | +0.6% | 0.1% | 48% |
| D2 | 700 | +0.0% | +0.0% | -0.2% | +0.7% | 0.1% | 45% |
| D3 | 699 | +0.0% | +0.0% | -0.2% | +0.6% | 0.1% | 44% |
| D4 | 700 | +0.0% | +0.0% | -0.2% | +1.6% | 0.1% | 44% |
| D5 | 699 | +0.0% | +0.0% | -0.2% | +0.9% | 0.1% | 43% |
| D6 | 700 | +0.0% | -0.0% | -0.3% | +0.8% | 0.1% | 43% |
| D7 | 699 | +0.0% | -0.0% | -0.3% | +3.2% | 0.2% | 43% |
| D8 | 700 | +0.0% | -0.0% | -0.2% | +1.6% | 0.2% | 43% |
| D9 | 699 | +0.1% | +0.0% | -0.3% | +3.3% | 0.2% | 48% |
| D10 | 700 | +0.1% | +0.0% | -0.3% | +2.0% | 0.3% | 48% |

> **Weak monotonicity:** D10 vs D1 spread of +0.1%

### RS_Universe_Rank
*C9 - RS Percentile (cross-sectional)*

| Decile | Count | Mean | Median | Min | Max | Std | Win% |
|--------|-------|------|--------|-----|-----|-----|------|
| D1 | 700 | +0.0% | +0.0% | -0.2% | +0.6% | 0.1% | 48% |
| D2 | 700 | +0.0% | +0.0% | -0.2% | +0.7% | 0.1% | 45% |
| D3 | 699 | +0.0% | +0.0% | -0.2% | +0.6% | 0.1% | 44% |
| D4 | 700 | +0.0% | +0.0% | -0.2% | +1.6% | 0.1% | 44% |
| D5 | 699 | +0.0% | +0.0% | -0.2% | +0.9% | 0.1% | 43% |
| D6 | 700 | +0.0% | -0.0% | -0.3% | +0.8% | 0.1% | 43% |
| D7 | 699 | +0.0% | -0.0% | -0.3% | +3.2% | 0.2% | 43% |
| D8 | 700 | +0.0% | -0.0% | -0.2% | +1.6% | 0.2% | 43% |
| D9 | 699 | +0.1% | +0.0% | -0.3% | +3.3% | 0.2% | 48% |
| D10 | 700 | +0.1% | +0.0% | -0.3% | +2.0% | 0.3% | 48% |

> **Weak monotonicity:** D10 vs D1 spread of +0.1%

### Dist_From_52W_High
*C8 - Proximity to 52W High*

| Decile | Count | Mean | Median | Min | Max | Std | Win% |
|--------|-------|------|--------|-----|-----|-----|------|
| D1 | 767 | +0.1% | +0.0% | -0.2% | +1.9% | 0.2% | 42% |
| D2 | 767 | +0.0% | +0.0% | -0.3% | +3.3% | 0.2% | 45% |
| D3 | 766 | +0.1% | +0.0% | -0.6% | +3.2% | 0.2% | 46% |
| D4 | 767 | +0.1% | +0.0% | -0.4% | +2.0% | 0.2% | 48% |
| D5 | 767 | +0.0% | +0.0% | -0.2% | +1.6% | 0.2% | 46% |
| D6 | 766 | +0.0% | +0.0% | -0.3% | +2.8% | 0.2% | 47% |
| D7 | 767 | +0.0% | +0.0% | -0.3% | +0.8% | 0.1% | 49% |
| D8 | 766 | +0.0% | +0.0% | -0.2% | +1.4% | 0.1% | 45% |
| D9 | 767 | +0.0% | +0.0% | -0.2% | +1.6% | 0.2% | 49% |
| D10 | 767 | +0.0% | +0.0% | -0.3% | +1.5% | 0.1% | 46% |

> **⚠️ Inverted:** D1 outperforms D10 by +0.0%

### Dist_From_52W_Low
*C7 - Distance from 52W Low*

| Decile | Count | Mean | Median | Min | Max | Std | Win% |
|--------|-------|------|--------|-----|-----|-----|------|
| D1 | 767 | +0.0% | +0.0% | -0.2% | +0.4% | 0.1% | 42% |
| D2 | 767 | +0.0% | +0.0% | -0.2% | +0.5% | 0.1% | 47% |
| D3 | 766 | +0.0% | -0.0% | -0.2% | +1.6% | 0.1% | 39% |
| D4 | 767 | +0.0% | +0.0% | -0.2% | +0.8% | 0.1% | 46% |
| D5 | 767 | +0.0% | +0.0% | -0.3% | +1.5% | 0.1% | 46% |
| D6 | 766 | +0.0% | +0.0% | -0.4% | +1.9% | 0.1% | 44% |
| D7 | 767 | +0.1% | +0.0% | -0.6% | +3.2% | 0.2% | 47% |
| D8 | 766 | +0.1% | +0.0% | -0.3% | +3.3% | 0.2% | 48% |
| D9 | 767 | +0.1% | +0.0% | -0.4% | +2.8% | 0.2% | 52% |
| D10 | 767 | +0.1% | +0.0% | -0.3% | +2.0% | 0.3% | 50% |

> **Weak monotonicity:** D10 vs D1 spread of +0.1%

## Executive Summary

- **Total candidates:** 225
- **Final passed:** 85
- **Regime-conditional features:** 203 (flagged for monitoring)

## Section 2: Feature Leaderboard

> **Note:** All scores are normalized 0-1 for comparability. IC (Norm) = raw Spearman IC divided by max IC in dataset.

| Rank | Feature | Composite | IC (Norm) | Stability | KS | Signal Type |
|------|---------|-----------|-----------|-----------|-----|-------------|
| 1 | `exit_price` | 0.867 | 1.000 | 1.000 | 0.556 | kinked |
| 2 | `industry_encoded` | 0.802 | 0.542 | 0.952 | 1.000 | linear_pos |
| 3 | `alpha013` | 0.679 | 0.807 | 0.631 | 0.556 | kinked |
| 4 | `alpha001` | 0.658 | 0.723 | 0.562 | 0.667 | linear_pos |
| 5 | `Price_vs_SMA_150_Delta` | 0.543 | 0.379 | 0.750 | 0.556 | kinked |
| 6 | `market_cap` | 0.488 | 0.608 | 0.261 | 0.556 | kinked |
| 7 | `alpha011` | 0.485 | 0.385 | 0.549 | 0.556 | kinked |
| 8 | `alpha054` | 0.477 | 0.179 | 0.350 | 1.000 | linear_pos |
| 9 | `dist_from_20d_high_lag1` | 0.476 | 0.343 | 0.462 | 0.667 | linear_neg |
| 10 | `inventory_vs_sales_spread` | 0.472 | 0.439 | 0.431 | 0.556 | kinked |
| 11 | `pct_from_high_52w` | 0.467 | 0.298 | 0.495 | 0.667 | linear_neg |
| 12 | `gross_margin_trend` | 0.458 | 0.340 | 0.518 | 0.556 | kinked |
| 13 | `Dist_From_52W_High_Delta` | 0.450 | 0.377 | 0.442 | 0.556 | kinked |
| 14 | `rs_ma_delta` | 0.432 | 0.291 | 0.384 | 0.667 | linear_pos |
| 15 | `m03_pillar_trend` | 0.431 | 0.449 | 0.281 | 0.556 | kinked |
| 16 | `Price_vs_SMA_50_Delta` | 0.430 | 0.224 | 0.357 | 0.778 | linear_pos |
| 17 | `m03_pillar_liq` | 0.404 | 0.365 | 0.193 | 0.667 | linear_pos |
| 18 | `log_Dist_From_52W_Low_Delta` | 0.400 | 0.256 | 0.324 | 0.667 | linear_pos |
| 19 | `rs_lag1` | 0.397 | 0.275 | 0.400 | 0.556 | kinked |
| 20 | `m03_pillar_risk` | 0.395 | 0.526 | 0.058 | 0.556 | kinked |
| 21 | `alpha060` | 0.389 | 0.284 | 0.364 | 0.556 | kinked |
| 22 | `alpha101` | 0.389 | 0.336 | 0.293 | 0.556 | kinked |
| 23 | `consolidation_width_delta` | 0.377 | 0.125 | 0.536 | 0.556 | kinked |
| 24 | `revenue_accel` | 0.377 | 0.233 | 0.279 | 0.667 | linear_pos |
| 25 | `Sector_Momentum` | 0.375 | 0.046 | 0.632 | 0.556 | kinked |
| 26 | `dist_from_52w_high_lag1` | 0.375 | 0.317 | 0.270 | 0.556 | kinked |
| 27 | `Dist_From_20D_High` | 0.374 | 0.206 | 0.303 | 0.667 | linear_neg |
| 28 | `Dist_From_20D_High_Delta` | 0.365 | 0.256 | 0.320 | 0.556 | kinked |
| 29 | `revenue_cagr_3y` | 0.350 | 0.074 | 0.290 | 0.778 | linear_pos |
| 30 | `VCP_Ratio` | 0.343 | 0.232 | 0.169 | 0.667 | linear_pos |

## Section 3: Monotonicity Deep Dive

### alpha054
- **Signal Type:** linear_pos
- **D1 Mean Return:** +0.02%
- **D10 Mean Return:** +0.06%
- **Decile Returns:**
  ```
  D 1:  +0.02% |++++++++
  D 2:  +0.03% |++++++++++
  D 3:  +0.03% |+++++++++++
  D 4:  +0.03% |+++++++++++
  D 5:  +0.04% |+++++++++++++
  D 6:  +0.05% |++++++++++++++++
  D 7:  +0.05% |+++++++++++++++++
  D 8:  +0.05% |++++++++++++++++++
  D 9:  +0.05% |++++++++++++++++++
  D10:  +0.06% |++++++++++++++++++++
  ```

### industry_encoded
- **Signal Type:** linear_pos
- **D1 Mean Return:** +0.01%
- **D10 Mean Return:** +0.09%
- **Decile Returns:**
  ```
  D 1:  +0.01% |++
  D 2:  +0.02% |++++
  D 3:  +0.03% |++++++
  D 4:  +0.04% |++++++++
  D 5:  +0.04% |+++++++++
  D 6:  +0.04% |++++++++++
  D 7:  +0.05% |+++++++++++
  D 8:  +0.06% |+++++++++++++
  D 9:  +0.06% |++++++++++++++
  D10:  +0.09% |++++++++++++++++++++
  ```

### revenue_cagr_3y
- **Signal Type:** linear_pos
- **D1 Mean Return:** +0.04%
- **D10 Mean Return:** +0.07%
- **Decile Returns:**
  ```
  D 1:  +0.04% |++++++++++++
  D 2:  +0.04% |++++++++++
  D 3:  +0.05% |+++++++++++++
  D 4:  +0.03% |++++++++
  D 5:  +0.03% |++++++++
  D 6:  +0.03% |++++++++
  D 7:  +0.03% |++++++++++
  D 8:  +0.04% |++++++++++++
  D 9:  +0.05% |+++++++++++++
  D10:  +0.07% |++++++++++++++++++++
  ```

### eps_diluted
- **Signal Type:** linear_neg
- **D1 Mean Return:** +0.06%
- **D10 Mean Return:** +0.03%
- **Decile Returns:**
  ```
  D 1:  +0.06% |+++++++++++++++++
  D 2:  +0.07% |++++++++++++++++++++
  D 3:  +0.06% |+++++++++++++++++
  D 4:  +0.04% |++++++++++++
  D 5:  +0.04% |+++++++++++
  D 6:  +0.03% |+++++++++
  D 7:  +0.03% |++++++++
  D 8:  +0.03% |++++++++
  D 9:  +0.03% |++++++++
  D10:  +0.03% |++++++++
  ```

### Price_vs_SMA_50_Delta
- **Signal Type:** linear_pos
- **D1 Mean Return:** +0.04%
- **D10 Mean Return:** +0.04%
- **Decile Returns:**
  ```
  D 1:  +0.04% |+++++++++++++++++
  D 2:  +0.03% |+++++++++++++
  D 3:  +0.03% |+++++++++++++
  D 4:  +0.03% |++++++++++++++
  D 5:  +0.03% |+++++++++++++++
  D 6:  +0.04% |+++++++++++++++++
  D 7:  +0.05% |++++++++++++++++++++
  D 8:  +0.03% |+++++++++++++++
  D 9:  +0.04% |++++++++++++++++++
  D10:  +0.04% |+++++++++++++++++++
  ```

### log_nATR
- **Signal Type:** linear_pos
- **D1 Mean Return:** +0.01%
- **D10 Mean Return:** +0.10%
- **Decile Returns:**
  ```
  D 1:  +0.01% |++
  D 2:  +0.03% |+++++
  D 3:  +0.02% |++++
  D 4:  +0.03% |+++++
  D 5:  +0.03% |++++++
  D 6:  +0.03% |+++++
  D 7:  +0.04% |++++++++
  D 8:  +0.05% |++++++++++
  D 9:  +0.08% |+++++++++++++++
  D10:  +0.10% |++++++++++++++++++++
  ```

### peg_adjusted
- **Signal Type:** linear_neg
- **D1 Mean Return:** +0.07%
- **D10 Mean Return:** +0.02%
- **Decile Returns:**
  ```
  D 1:  +0.07% |++++++++++++++++++++
  D 2:  +0.06% |+++++++++++++++++
  D 3:  +0.04% |+++++++++++++
  D 4:  +0.05% |++++++++++++++
  D 5:  +0.02% |+++++++
  D 6:  +0.04% |++++++++++++
  D 7:  +0.03% |++++++++++
  D 8:  +0.03% |++++++++
  D 9:  +0.03% |+++++++
  D10:  +0.02% |++++++
  ```

### alpha001
- **Signal Type:** linear_pos
- **D1 Mean Return:** +0.07%
- **D10 Mean Return:** +0.07%
- **Decile Returns:**
  ```
  D 1:  +0.07% |++++++++++++++++++
  D 2:  +0.04% |+++++++++++
  D 3:  +0.04% |++++++++++++
  D 4:  +0.03% |+++++++++
  D 5:  +0.04% |++++++++++++
  D 6:  +0.03% |+++++++
  D 7:  +0.03% |+++++++++
  D 8:  +0.04% |++++++++++
  D 9:  +0.04% |+++++++++++
  D10:  +0.07% |++++++++++++++++++++
  ```

### volume_acceleration
- **Signal Type:** linear_pos
- **D1 Mean Return:** +0.05%
- **D10 Mean Return:** +0.07%
- **Decile Returns:**
  ```
  D 1:  +0.05% |+++++++++++++
  D 2:  +0.03% |+++++++++
  D 3:  +0.03% |+++++++++
  D 4:  +0.04% |++++++++++++
  D 5:  +0.03% |+++++++++
  D 6:  +0.03% |+++++++++
  D 7:  +0.04% |++++++++++
  D 8:  +0.06% |++++++++++++++++
  D 9:  +0.04% |++++++++++++
  D10:  +0.07% |++++++++++++++++++++
  ```

### pct_from_high_52w
- **Signal Type:** linear_neg
- **D1 Mean Return:** +0.06%
- **D10 Mean Return:** +0.03%
- **Decile Returns:**
  ```
  D 1:  +0.06% |++++++++++++++++++++
  D 2:  +0.05% |++++++++++++++++
  D 3:  +0.05% |+++++++++++++++++
  D 4:  +0.05% |+++++++++++++++++
  D 5:  +0.04% |+++++++++++++
  D 6:  +0.04% |++++++++++++
  D 7:  +0.03% |+++++++++++
  D 8:  +0.04% |++++++++++++
  D 9:  +0.04% |+++++++++++++
  D10:  +0.03% |+++++++++++
  ```

## Section 4: Stability Analysis (Per-Year IC)

| Feature | IC_2020 | IC_2021 | IC_2022 | IC_2023 | IC_2024 | IC_2025 | IC_2026 | Stability | Regime? |
|---------|-------|-------|-------|-------|-------|-------|-------|-------|-------|
| `exit_price` | -0.007 | 0.070 | 0.073 | 0.106 | 0.113 | 0.087 | 0.155 | 1.84 | Yes |
| `industry_encoded` | 0.061 | 0.034 | 0.041 | 0.036 | 0.015 | 0.109 | 0.095 | 1.75 | Yes |
| `alpha013` | 0.110 | 0.090 | 0.017 | 0.088 | 0.058 | 0.119 | -0.044 | 1.16 | Yes |
| `alpha011` | -0.014 | 0.035 | -0.012 | 0.033 | 0.039 | 0.040 | 0.049 | 1.01 | Yes |
| `consolidation_width_delta` | 0.008 | 0.034 | 0.038 | -0.005 | -0.009 | 0.031 | 0.025 | 0.98 | Yes |
| `gross_margin_trend` | 0.125 | 0.015 | 0.018 | 0.055 | 0.027 | 0.010 | 0.009 | 0.95 | Yes |
| `dist_from_20d_high_lag1` | -0.004 | 0.060 | 0.021 | -0.012 | 0.069 | 0.002 | 0.039 | 0.85 | Yes |
| `rs_ma_delta` | 0.000 | -0.012 | 0.081 | 0.050 | 0.013 | -0.019 | 0.034 | 0.71 | Yes |
| `alpha060` | 0.040 | 0.043 | -0.014 | 0.004 | 0.018 | -0.011 | 0.018 | 0.67 | Yes |
| `alpha054` | 0.056 | 0.016 | -0.006 | -0.023 | 0.005 | 0.027 | 0.038 | 0.64 | Yes |
| `log_Dist_From_52W_Low_Delta` | -0.011 | -0.024 | 0.022 | 0.017 | 0.012 | 0.036 | 0.037 | 0.60 | Yes |
| `rs_line_delta` | 0.052 | -0.033 | 0.046 | -0.001 | -0.012 | 0.018 | 0.082 | 0.58 | Yes |
| `revenue_growth_yoy` | -0.013 | -0.008 | 0.016 | -0.009 | 0.018 | 0.036 | 0.101 | 0.55 | Yes |
| `revenue_cagr_3y` | -0.030 | 0.017 | 0.047 | -0.014 | 0.036 | -0.000 | 0.055 | 0.53 | Yes |
| `revenue_accel` | 0.053 | 0.032 | 0.025 | -0.030 | -0.020 | -0.006 | 0.072 | 0.51 | Yes |

### Regime-Conditional Features (High IC Variance)

These features have inconsistent IC across years. Monitor closely:

- `exit_price`
- `industry_encoded`
- `alpha013`
- `alpha011`
- `consolidation_width_delta`
- `gross_margin_trend`
- `dist_from_20d_high_lag1`
- `rs_ma_delta`
- `alpha060`
- `alpha054`

## Section 5: Correlation Clusters

### Cluster 51
- **Members:** `sma_20`, `sma_200_lag20`, `price_vs_spy`, `price_vs_spy_ma20`, `price_vs_spy_ma50`, `price_vs_spy_ma63`, `price_vs_spy_ma200`, `rs_line_log`, `atr_14`, `volatility_20d`, `highest_high_20d`, `lowest_low_20d`, `high_20d`, `entry_price`, `exit_price`, `atr_lag1`, `high_52w_lag1`, `low_52w_lag1`, `lowest_low_20d_lag1`, `highest_high_20d_lag1`
- **Keep:** `exit_price` (highest weighted score (IC=0.085, Stab=1.84))
- **Drop:** `atr_lag1`, `high_52w_lag1`, `lowest_low_20d_lag1`, `highest_high_20d_lag1`, `low_52w_lag1`, `lowest_low_20d`, `volatility_20d`, `entry_price`, `sma_200_lag20`, `sma_20`, `price_vs_spy_ma50`, `price_vs_spy_ma200`, `price_vs_spy_ma20`, `high_20d`, `highest_high_20d`, `price_vs_spy_ma63`, `price_vs_spy`, `rs_line_log`, `atr_14`

### Cluster 71
- **Members:** `price_vs_sma_50`, `consolidation_width`, `Dist_From_20D_Low`, `return_20d`, `mom_21d`, `log_Price_vs_SMA_50`, `log_Dist_From_20D_Low`
- **Keep:** `price_vs_sma_50` (highest weighted score (IC=0.023, Stab=0.24))
- **Drop:** `log_Price_vs_SMA_50`, `consolidation_width`, `Dist_From_20D_Low`, `log_Dist_From_20D_Low`, `return_20d`, `mom_21d`

### Cluster 69
- **Members:** `price_vs_sma_150`, `price_vs_sma_200`, `rs`, `rs_ma`, `pct_above_low_52w`, `Dist_From_52W_Low`, `mom_126d`, `mom_189d`, `mom_252d`, `rs_lag1`, `rs_ma_lag1`, `dist_from_52w_low_lag1`, `log_RS`, `log_Price_vs_SMA_200`, `log_Price_vs_SMA_150`, `log_Dist_From_52W_Low`
- **Keep:** `rs_lag1` (highest weighted score (IC=0.025, Stab=0.74))
- **Drop:** `rs`, `log_RS`, `price_vs_sma_150`, `log_Price_vs_SMA_150`, `rs_ma`, `price_vs_sma_200`, `log_Price_vs_SMA_200`, `mom_126d`, `rs_ma_lag1`, `mom_252d`, `mom_189d`, `pct_above_low_52w`, `Dist_From_52W_Low`, `log_Dist_From_52W_Low`, `dist_from_52w_low_lag1`

### Cluster 72
- **Members:** `rs_line_delta`, `return_1d`, `log_rs_line_delta`
- **Keep:** `rs_line_delta` (highest weighted score (IC=0.022, Stab=0.58))
- **Drop:** `log_rs_line_delta`, `return_1d`

### Cluster 14
- **Members:** `rs_line_lag_delta`, `log_rs_line_lag_delta`
- **Keep:** `rs_line_lag_delta` (highest weighted score (IC=0.015, Stab=0.33))
- **Drop:** `log_rs_line_lag_delta`

### Cluster 66
- **Members:** `rs_rating`, `RS_Universe_Rank`, `RS_Sector_Rank`, `RS_vs_Sector`
- **Keep:** `RS_vs_Sector` (highest weighted score (IC=0.019, Stab=0.33))
- **Drop:** `RS_Sector_Rank`, `rs_rating`, `RS_Universe_Rank`

### Cluster 43
- **Members:** `vol_avg_50`, `vol_ma20`, `vol_ma50`, `log_vol_ma20`
- **Keep:** `vol_ma20` (highest weighted score (IC=0.003, Stab=0.05))
- **Drop:** `log_vol_ma20`, `vol_avg_50`, `vol_ma50`

### Cluster 29
- **Members:** `vol_ratio`, `vol_ratio_50`, `log_volume_velocity`
- **Keep:** `vol_ratio` (highest weighted score (IC=0.007, Stab=0.26))
- **Drop:** `vol_ratio_50`, `log_volume_velocity`

### Cluster 42
- **Members:** `dollar_volume_avg_20`, `turnover_ma20`, `log_turnover_ma20`
- **Keep:** `dollar_volume_avg_20` (highest weighted score (IC=0.006, Stab=0.07))
- **Drop:** `turnover_ma20`, `log_turnover_ma20`

### Cluster 38
- **Members:** `Dry_Up_Volume`, `dry_up_volume_delta`, `log_Dry_Up_Volume`, `log_Dry_Up_Volume_Delta`
- **Keep:** `Dry_Up_Volume` (highest weighted score (IC=0.020, Stab=0.51))
- **Drop:** `log_Dry_Up_Volume`, `dry_up_volume_delta`, `log_Dry_Up_Volume_Delta`

## Section 6: Distributional Warnings

| Feature | Issue | Action |
|---------|-------|--------|
| `rs_line_delta` | Kurtosis=55.2 | Consider winsorizing at 1/99% |
| `rs_line_lag_delta` | Kurtosis=68.5 | Consider winsorizing at 1/99% |
| `return_60d` | Kurtosis=21.1 | Consider winsorizing at 1/99% |
| `rs_velocity` | Kurtosis=220.7 | Consider winsorizing at 1/99% |
| `alpha001` | Kurtosis=106.7 | Consider winsorizing at 1/99% |
| `alpha041` | Kurtosis=10.1 | Consider winsorizing at 1/99% |
| `Sector_Momentum` | Kurtosis=736.0 | Consider winsorizing at 1/99% |
| `rs_lag1` | Kurtosis=12.9 | Consider winsorizing at 1/99% |
| `dry_up_volume_lag1` | Kurtosis=10.9 | Consider winsorizing at 1/99% |
| `dist_from_20d_high_lag1` | Kurtosis=10.3 | Consider winsorizing at 1/99% |
| `rs_ma_delta` | Kurtosis=10.3 | Consider winsorizing at 1/99% |
| `net_income` | Kurtosis=25.3 | Consider winsorizing at 1/99% |
| `eps_stability_score` | Kurtosis=18.2 | Consider winsorizing at 1/99% |
| `debt_to_equity` | Kurtosis=10.9 | Consider winsorizing at 1/99% |
| `current_ratio` | Kurtosis=22.6 | Consider winsorizing at 1/99% |
| `gross_margin` | Kurtosis=10.4 | Consider winsorizing at 1/99% |
| `net_margin` | Kurtosis=55.6 | Consider winsorizing at 1/99% |
| `roe` | Kurtosis=14.3 | Consider winsorizing at 1/99% |
| `earnings_quality_score` | Kurtosis=14.1 | Consider winsorizing at 1/99% |
| `inventory_vs_sales_spread` | Kurtosis=12.5 | Consider winsorizing at 1/99% |

## Section 7: Transformation Summary

> Features with high kurtosis were automatically transformed during EDA:
> - **Log Transform** (`sign(x) * log(1+|x|)`): Preserves magnitude (explosive/TAR>1.2)
> - **Winsorization** (1%/99%): Clips outliers as noise (bounded/standard/TAR<=1.2)

| Feature | Transform | Category | TAR |
|---------|-----------|----------|-----|
| `price_vs_sma_50` | Log | TAR-based | 2.52 |
| `price_vs_sma_150` | Log | TAR-based | 2.27 |
| `price_vs_sma_200` | Log | TAR-based | 2.29 |
| `rs_line_delta` | Log | TAR-based | 2.46 |
| `rs_line_lag_delta` | Log | TAR-based | 1.75 |
| `rs` | Log | TAR-based | 2.91 |
| `rs_ma` | Log | TAR-based | 2.33 |
| `vol_avg_50` | Log | TAR-based | 1.54 |
| `vol_ratio` | Log | TAR-based | 2.00 |
| `vol_ratio_50` | Log | TAR-based | 2.00 |
| `vol_ma20` | Log | TAR-based | 1.49 |
| `vol_ma50` | Log | TAR-based | 1.54 |
| `dollar_volume_avg_20` | Log | TAR-based | 1.39 |
| `Dry_Up_Volume` | Log | Explosive | - |
| `turnover_ma20` | Log | TAR-based | 1.21 |
| `volatility_20d` | Log | TAR-based | 1.24 |
| `pct_above_low_52w` | Log | TAR-based | 2.28 |
| `Dist_From_52W_Low` | Log | Explosive | - |
| `Dist_From_20D_Low` | Log | TAR-based | 2.21 |
| `return_1d` | Log | TAR-based | 2.46 |
| `return_5d` | Log | TAR-based | 2.58 |
| `return_20d` | Log | TAR-based | 2.47 |
| `return_60d` | Log | TAR-based | 2.34 |
| `mom_21d` | Log | TAR-based | 2.56 |
| `mom_63d` | Log | TAR-based | 2.33 |
| `mom_126d` | Log | TAR-based | 2.38 |
| `mom_189d` | Log | TAR-based | 2.61 |
| `mom_252d` | Log | TAR-based | 2.77 |
| `sma_50_slope` | Log | TAR-based | 2.37 |
| `adr_20d` | Log | TAR-based | 1.84 |
| `rs_velocity` | Log | TAR-based | 3.08 |
| `volume_acceleration` | Log | Explosive | - |
| `price_momentum_curve` | Log | TAR-based | 1.27 |
| `immediate_thrust` | Log | TAR-based | 1.27 |
| `alpha001` | Log | TAR-based | 2.10 |
| `RS_vs_Sector` | Log | TAR-based | 2.90 |
| `Sector_Momentum` | Log | TAR-based | 1.42 |
| `Industry_Momentum` | Log | TAR-based | 2.20 |
| `vcp_ratio_lag1` | Log | TAR-based | 2.13 |
| `price_vs_sma_50_lag1` | Log | TAR-based | 2.79 |
| `price_vs_sma_150_lag1` | Log | TAR-based | 2.71 |
| `price_vs_sma_200_lag1` | Log | TAR-based | 2.62 |
| `rs_lag1` | Log | TAR-based | 3.01 |
| `rs_ma_lag1` | Log | TAR-based | 2.50 |
| `dry_up_volume_lag1` | Log | TAR-based | 1.29 |
| `dist_from_52w_low_lag1` | Log | TAR-based | 2.66 |
| `dist_from_20d_low_lag1` | Log | TAR-based | 2.88 |
| `dist_from_20d_high_lag1` | Log | TAR-based | 1.57 |
| `consolidation_width_delta` | Log | TAR-based | 1.30 |
| `Price_vs_SMA_50_Delta` | Log | TAR-based | 1.54 |
| `Price_vs_SMA_150_Delta` | Log | TAR-based | 1.66 |
| `price_vs_sma_200_delta` | Log | TAR-based | 1.83 |
| `rs_delta` | Log | TAR-based | 1.66 |
| `rs_ma_delta` | Log | TAR-based | 1.24 |
| `dry_up_volume_delta` | Log | TAR-based | 1.86 |
| `high_52w_delta` | Log | TAR-based | 1.87 |
| `lowest_low_20d_delta` | Log | TAR-based | 2.63 |
| `highest_high_20d_delta` | Log | TAR-based | 1.89 |
| `Dist_From_52W_High_Delta` | Log | TAR-based | 1.49 |
| `dist_from_52w_low_delta` | Log | TAR-based | 2.34 |
| `dist_from_20d_low_delta` | Log | TAR-based | 1.93 |
| `Dist_From_20D_High_Delta` | Log | TAR-based | 1.35 |
| `revenue_growth_yoy` | Log | Explosive | - |
| `eps_growth_yoy` | Log | Explosive | - |
| `net_income_growth_yoy` | Log | TAR-based | 1.21 |
| `eps_accel` | Log | Explosive | - |
| `revenue_accel` | Log | Explosive | - |
| `revenue_cagr_3y` | Log | TAR-based | 2.16 |
| `debt_to_equity` | Log | TAR-based | 1.33 |
| `current_ratio` | Log | TAR-based | 1.59 |
| `quick_ratio` | Log | TAR-based | 1.60 |
| `fcf_margin` | Log | TAR-based | 1.44 |
| `gross_margin_trend` | Log | TAR-based | 1.81 |
| `pe_ratio` | Log | Explosive | - |
| `log_RS` | Log | TAR-based | 2.91 |
| `log_mom_63d` | Log | TAR-based | 2.33 |
| `log_alpha001` | Log | TAR-based | 2.10 |
| `log_RS_MA_Delta` | Log | TAR-based | 1.24 |
| `log_Dry_Up_Volume_Lag1` | Log | TAR-based | 1.29 |
| `log_rs_line_delta` | Log | TAR-based | 2.46 |
| `log_rs_line_lag_delta` | Log | TAR-based | 1.75 |
| `log_rs_velocity` | Log | TAR-based | 3.08 |
| `log_Dist_From_52W_Low` | Log | TAR-based | 2.28 |
| `log_Lowest_Low_20D_Delta` | Log | TAR-based | 2.63 |
| `log_debt_to_equity` | Log | TAR-based | 1.33 |
| `log_current_ratio` | Log | TAR-based | 1.59 |
| `log_Dist_From_20D_Low` | Log | TAR-based | 2.21 |
| `sma_20` | Winsorize | TAR-based | 0.58 |
| `sma_200_lag20` | Winsorize | TAR-based | 0.58 |
| `price_vs_spy` | Winsorize | TAR-based | 0.63 |
| `price_vs_spy_ma20` | Winsorize | TAR-based | 0.60 |
| `price_vs_spy_ma50` | Winsorize | TAR-based | 0.59 |
| `price_vs_spy_ma63` | Winsorize | TAR-based | 0.59 |
| `price_vs_spy_ma200` | Winsorize | TAR-based | 0.59 |
| `turnover` | Winsorize | TAR-based | 1.16 |
| `atr_14` | Winsorize | TAR-based | 1.01 |
| `VCP_Ratio` | Winsorize | Standard | - |
| `highest_high_20d` | Winsorize | TAR-based | 0.56 |
| `lowest_low_20d` | Winsorize | TAR-based | 0.59 |
| `high_20d` | Winsorize | TAR-based | 0.56 |
| `Dist_From_20D_High` | Winsorize | TAR-based | 1.15 |
| `price_accel_10d` | Winsorize | TAR-based | 1.02 |
| `alpha004` | Winsorize | TAR-based | 0.72 |
| `alpha041` | Winsorize | TAR-based | 0.84 |
| `entry_price` | Winsorize | TAR-based | 0.56 |
| `exit_price` | Winsorize | TAR-based | 1.03 |
| `atr_lag1` | Winsorize | TAR-based | 0.66 |
| `high_52w_lag1` | Winsorize | TAR-based | 0.64 |
| `low_52w_lag1` | Winsorize | TAR-based | 0.59 |
| `lowest_low_20d_lag1` | Winsorize | TAR-based | 0.60 |
| `highest_high_20d_lag1` | Winsorize | TAR-based | 0.62 |
| `natr_delta` | Winsorize | TAR-based | 1.09 |
| `low_52w_delta` | Winsorize | TAR-based | 1.19 |
| `net_income` | Winsorize | TAR-based | 0.77 |
| `eps_diluted` | Winsorize | TAR-based | 0.68 |
| `total_assets` | Winsorize | TAR-based | 0.69 |
| `total_equity` | Winsorize | TAR-based | 0.73 |
| `eps_stability_score` | Winsorize | TAR-based | 0.78 |
| `gross_margin` | Winsorize | Standard | - |
| `operating_margin` | Winsorize | Standard | - |
| `net_margin` | Winsorize | Standard | - |
| `roe` | Winsorize | Standard | - |
| `roa` | Winsorize | Standard | - |
| `earnings_quality_score` | Winsorize | Bounded | - |
| `inventory_growth_yoy` | Winsorize | TAR-based | 0.70 |
| `inventory_vs_sales_spread` | Winsorize | TAR-based | 0.67 |
| `days_since_report` | Winsorize | TAR-based | 0.93 |
| `market_cap` | Winsorize | TAR-based | 0.98 |
| `peg_adjusted` | Winsorize | TAR-based | 0.68 |

**Total:** 87 log-transformed, 42 winsorized

> **TAR (Tail Alpha Ratio):** Ratio of mean |return| in 99-100th percentile vs 10-90th percentile.
> TAR > 1.2 suggests tail values are predictive (log transform); TAR <= 1.2 suggests noise (winsorize).

## Recommended Feature List

Copy this to `src/feature_config.py` → `M01_FEATURES` after review:

> **Note:** Features with `log_` prefix are log-transformed during preprocessing.
> The preprocessor will apply these transforms automatically at training/inference.

```python
M01_FEATURES = [
    'exit_price',
    'industry_encoded',
    'alpha013',
    'log_alpha001',  # log-transformed
    'log_Price_vs_SMA_150_Delta',  # log-transformed
    'market_cap',
    'alpha011',
    'alpha054',
    'log_dist_from_20d_high_lag1',  # log-transformed
    'inventory_vs_sales_spread',
    'pct_from_high_52w',
    'log_gross_margin_trend',  # log-transformed
    'log_Dist_From_52W_High_Delta',  # log-transformed
    'log_rs_ma_delta',  # log-transformed
    'm03_pillar_trend',
    'log_Price_vs_SMA_50_Delta',  # log-transformed
    'm03_pillar_liq',
    'log_Dist_From_52W_Low_Delta',
    'log_rs_lag1',  # log-transformed
    'm03_pillar_risk',
    'alpha060',
    'alpha101',
    'log_consolidation_width_delta',  # log-transformed
    'log_revenue_accel',  # log-transformed
    'log_Sector_Momentum',  # log-transformed
    'dist_from_52w_high_lag1',
    'Dist_From_20D_High',
    'log_Dist_From_20D_High_Delta',  # log-transformed
    'log_revenue_cagr_3y',  # log-transformed
    'VCP_Ratio',
    'log_Dry_Up_Volume',  # log-transformed
    'log_Industry_Momentum',  # log-transformed
    'breakout_momentum',
    'log_rs_line_delta',  # log-transformed
    'alpha015',
    'log_RS_vs_Sector',  # log-transformed
    'eps_diluted',
    'log_revenue_growth_yoy',  # log-transformed
    'peg_adjusted',
    'log_return_60d',  # log-transformed
    'log_price_vs_sma_50',  # log-transformed
    'alpha041',
    'earnings_quality_score',
    'log_days_since_report',
    'rsi_14_delta',
    'log_nATR',
    'log_eps_accel',  # log-transformed
    'm03_delta_5d',
    'alpha002',
    'log_debt_to_equity',  # log-transformed
    'alpha006',
    'RSI_14',
    'vcp_ratio_delta',
    'gross_margin',
    'log_price_momentum_curve',  # log-transformed
    'net_income',
    'log_net_income_growth_yoy',  # log-transformed
    'log_rs_velocity',  # log-transformed
    'log_vol_ratio',  # log-transformed
    'm03_score',
    'log_High_52W_Delta',
    'natr_delta',
    'log_vcp_ratio_lag1',  # log-transformed
    'log_current_ratio',  # log-transformed
    'RS_vs_Industry',
    'alpha009',
    'eps_stability_score',
    'roe',
    'roa',
    'log_rs_line_lag_delta',  # log-transformed
    'rsi_14_lag1',
    'm03_regime_vol',
    'log_volume_acceleration',  # log-transformed
    'log_fcf_margin',  # log-transformed
    'log_dry_up_volume_lag1',  # log-transformed
    'net_margin',
    'price_accel_10d',
    'log_pe_ratio',  # log-transformed
    'm03_delta_20d',
    'log_dollar_volume_avg_20',  # log-transformed
    'log_vol_ma20',  # log-transformed
    'alpha046',
    'low_52w_delta',
    'sector_encoded',
    'alpha049',
]
```

---

## Next Steps (User Action Required)

**The workflow does NOT auto-save models.** To deploy new features:

1. **Review** this report and the passed/failed features
2. **Copy** the recommended feature list above to `src/feature_config.py` → `M01_FEATURES`
3. **Train** the production model:
   ```bash
   python model_runner.py m01 --steps train
   ```
4. **Verify** the model works with `daily_scanner.py --ml`

> **Why manual approval?** Auto-saving overwrote production models during testing.
> This safeguard ensures only reviewed features reach production.

---

*Report generated by FeatureScreener (Quant-Standard Pipeline)*