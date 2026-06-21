# Model Training Report - M01 (SEPA Signal Quality Model)

**Generated:** 2026-02-09 21:22:34
**Training Period:** 2018-01-01 to 2025-12-31
**Model Type:** REGRESSION
**Target:** target

---

## Executive Summary

**Trading Viability:** NOT VIABLE

### Key Metrics

- **Selection Edge:** +0.04% (range: [-0.34%, +0.37%])
- **Edge Consistency:** 3/5 folds positive (60%)
- **Edge Sharpe Ratio:** 0.13
- **Top Decile Return:** 1.35%
- **RMSE:** 2.08%
- **Walk-Forward Folds:** 5
- **Total Test Samples:** 7,231

---

## Walk-Forward Validation Results

| Fold | Test Year | Test Samples | RMSE | Selection Edge | Top Decile Mean |
|------|-----------|--------------|------|----------------|-----------------|
| 1 | 2021.0 | 2,026.0 | 1.98% | -0.34% | 1.21% |
| 2 | 2022.0 | 598.0 | 2.18% | +0.37% | 1.31% |
| 3 | 2023.0 | 1,390.0 | 1.96% | +0.21% | 1.61% |
| 4 | 2024.0 | 1,969.0 | 2.01% | +0.20% | 1.64% |
| 5 | 2025.0 | 1,248.0 | 2.27% | -0.24% | 0.98% |

---

## Feature Importance Analysis

**Total Features:** 65

### Top 20 Features by Gain

| Rank | Feature | Gain | % Total | Cumulative % |
|------|---------|------|---------|--------------|
| 1 | industry_id | 0 | 3.7% | 3.7% |
| 2 | inventory_vs_sales_spread | 0 | 3.1% | 6.8% |
| 3 | alpha011 | 0 | 2.7% | 9.5% |
| 4 | log_RS | 0 | 2.6% | 12.1% |
| 5 | log_Price_vs_SMA_50 | 0 | 2.6% | 14.6% |
| 6 | log_High_52W_Delta | 0 | 2.4% | 17.1% |
| 7 | log_Price_vs_SMA_200 | 0 | 2.4% | 19.5% |
| 8 | log_Dist_From_20D_Low_Delta | 0 | 2.4% | 21.8% |
| 9 | current_ratio | 0 | 2.3% | 24.1% |
| 10 | alpha004 | 0 | 2.3% | 26.4% |
| 11 | RS_Universe_Rank | 0 | 2.2% | 28.5% |
| 12 | alpha101 | 0 | 2.1% | 30.7% |
| 13 | log_Price_vs_SMA_50_Lag1 | 0 | 2.0% | 32.7% |
| 14 | log_volume_acceleration | 0 | 2.0% | 34.7% |
| 15 | alpha013 | 0 | 2.0% | 36.7% |
| 16 | sector_id | 0 | 2.0% | 38.6% |
| 17 | alpha006 | 0 | 1.9% | 40.6% |
| 18 | log_mom_63d | 0 | 1.9% | 42.5% |
| 19 | log_breakout_momentum | 0 | 1.9% | 44.3% |
| 20 | net_income_growth_yoy | 0 | 1.8% | 46.1% |

---

## Regime-Conditional Performance

Performance bucketed by M03 market regime at entry time.

### Top Decile Performance by Regime

| Regime | N Trades | Win Rate | Mean Return | Median Return |
|--------|----------|----------|-------------|---------------|
| Strong Bear | 22 | 4.5% | -1.07% | -1.56% |
| Bear | 61 | 13.1% | +4.66% | -2.65% |
| Neutral | 171 | 22.2% | +5.24% | -2.25% |
| Bull | 218 | 8.7% | +0.26% | -3.53% |
| Strong Bull | 251 | 13.5% | +1.45% | -2.08% |

---

## Decile Performance Analysis

### Win Rate and Return by Predicted Decile

| Decile | N Trades | Win Rate | Mean Return | Median | Min | Max |
|--------|----------|----------|-------------|--------|-----|-----|
| 1 | 724 | 16.7% | +2.25% | -5.08% | -75.2% | +334.3% |
| 2 | 723 | 10.7% | -0.20% | -3.60% | -30.3% | +112.2% |
| 3 | 723 | 8.0% | -0.36% | -3.35% | -34.2% | +302.2% |
| 4 | 723 | 9.0% | +0.44% | -2.66% | -30.3% | +164.8% |
| 5 | 723 | 11.6% | +1.95% | -2.15% | -30.3% | +133.7% |
| 6 | 723 | 10.8% | +1.44% | -2.12% | -21.7% | +229.1% |
| 7 | 723 | 12.3% | +1.58% | -2.31% | -46.0% | +109.3% |
| 8 | 723 | 13.8% | +2.98% | -2.63% | -42.1% | +516.6% |
| 9 | 723 | 11.2% | +1.07% | -2.78% | -32.0% | +293.4% |
| 10 | 723 | 13.8% | +2.18% | -2.59% | -32.6% | +279.8% |

### Detailed Decile Statistics

Return distribution percentiles by predicted decile:

| Decile | N | Mean | Std | Min | P1 | P5 | P25 | P50 | P75 | P95 | P99 | Max |
|--------|---|------|-----|-----|----|----|-----|-----|-----|-----|-----|-----|
| 1 | 724 | +2.2 | 27.8 | -75 | -24 | -18 | -11 | -5 | +6 | +45 | +102 | +334 |
| 2 | 723 | -0.2 | 13.9 | -30 | -24 | -14 | -7 | -4 | +2 | +26 | +55 | +112 |
| 3 | 723 | -0.4 | 17.1 | -34 | -20 | -14 | -7 | -3 | +2 | +23 | +46 | +302 |
| 4 | 723 | +0.4 | 14.1 | -30 | -19 | -13 | -7 | -3 | +3 | +22 | +61 | +165 |
| 5 | 723 | +1.9 | 15.7 | -30 | -19 | -12 | -6 | -2 | +6 | +28 | +62 | +134 |
| 6 | 723 | +1.4 | 15.6 | -22 | -18 | -12 | -6 | -2 | +5 | +23 | +41 | +229 |
| 7 | 723 | +1.6 | 14.3 | -46 | -17 | -13 | -6 | -2 | +5 | +31 | +55 | +109 |
| 8 | 723 | +3.0 | 26.1 | -42 | -19 | -12 | -6 | -3 | +5 | +34 | +69 | +517 |
| 9 | 723 | +1.1 | 18.4 | -32 | -20 | -15 | -7 | -3 | +5 | +28 | +64 | +293 |
| 10 | 723 | +2.2 | 20.2 | -33 | -20 | -15 | -8 | -3 | +6 | +34 | +75 | +280 |

---

## Super Stock Classification

*Super Stock = Return > 50%*

**Market Base Rate:** 133 Super Stocks (1.84% of all trades)

### Precision & Recall

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Precision @ Top 10% | 2.90% | 21/723 top picks are Super Stocks |
| Recall @ Top 10% | 15.8% | 21/133 Super Stocks found in top decile |
| Lift @ Top 10% | 1.6x | vs random (1.84% base rate) |

### Percentile Lift (Granular Selection)

| Percentile | N | Super Stocks | Precision | Lift |
|------------|---|--------------|-----------|------|
| Top 1% | 73 | 4 | 5.5% | 3.0x |
| Top 2% | 145 | 6 | 4.1% | 2.2x |
| Top 5% | 362 | 15 | 4.1% | 2.3x |
| Top 10% | 724 | 21 | 2.9% | 1.6x |
| Top 20% | 1447 | 32 | 2.2% | 1.2x |

---

## Model Configuration

```python
XGBRegressor(
    objective='reg:squarederror',
    n_estimators=300,
    learning_rate=0.03,
    max_depth=4,
    subsample=0.8,
    colsample_bytree=0.8,
    reg_alpha=5.0,
    reg_lambda=3.0,
    random_state=42
)
```

---

*Report generated by M01Trainer*