# Model Training Report - M01 (SEPA Signal Quality Model)

**Generated:** 2026-02-14 18:18:11
**Training Period:** 2018-01-01 to 2025-12-31
**Model Type:** REGRESSION
**Target:** target

---

## Executive Summary

**Trading Viability:** NOT VIABLE

### Key Metrics

- **Selection Edge:** +0.07% (range: [-0.06%, +0.21%])
- **Edge Consistency:** 3/5 folds positive (60%)
- **Edge Sharpe Ratio:** 0.60
- **Top Decile Return:** 1.42%
- **RMSE:** 1.91%
- **Walk-Forward Folds:** 5
- **Total Test Samples:** 8,321

---

## Walk-Forward Validation Results

| Fold | Test Year | Test Samples | RMSE | Selection Edge | Top Decile Mean |
|------|-----------|--------------|------|----------------|-----------------|
| 1 | 2021.0 | 2,453.0 | 1.74% | +0.21% | 1.84% |
| 2 | 2022.0 | 713.0 | 2.10% | -0.01% | 1.04% |
| 3 | 2023.0 | 1,553.0 | 1.81% | +0.04% | 1.45% |
| 4 | 2024.0 | 2,243.0 | 1.78% | +0.18% | 1.70% |
| 5 | 2025.0 | 1,359.0 | 2.13% | -0.06% | 1.07% |

---

## Feature Importance Analysis

**Total Features:** 73

### Top 20 Features by Gain

| Rank | Feature | Gain | % Total | Cumulative % |
|------|---------|------|---------|--------------|
| 1 | industry_id | 0 | 2.8% | 2.8% |
| 2 | log_Price_vs_SMA_50 | 0 | 2.7% | 5.4% |
| 3 | alpha011 | 0 | 2.6% | 8.0% |
| 4 | log_Price_vs_SMA_200 | 0 | 2.4% | 10.4% |
| 5 | inventory_vs_sales_spread | 0 | 2.0% | 12.4% |
| 6 | m03_pillar_risk | 0 | 1.8% | 14.2% |
| 7 | net_income_growth_yoy | 0 | 1.8% | 16.0% |
| 8 | alpha046 | 0 | 1.8% | 17.8% |
| 9 | log_net_income_growth_yoy | 0 | 1.7% | 19.5% |
| 10 | log_Price_vs_SMA_50_Lag1 | 0 | 1.7% | 21.3% |
| 11 | sector_id | 0 | 1.7% | 23.0% |
| 12 | log_mom_63d | 0 | 1.7% | 24.6% |
| 13 | roe | 0 | 1.6% | 26.3% |
| 14 | ps_ratio | 0 | 1.5% | 27.8% |
| 15 | Price_vs_SMA_50_Delta | 0 | 1.5% | 29.3% |
| 16 | log_volume_acceleration | 0 | 1.5% | 30.9% |
| 17 | log_alpha001 | 0 | 1.5% | 32.4% |
| 18 | log_RS | 0 | 1.5% | 33.8% |
| 19 | m03_pillar_liq | 0 | 1.5% | 35.3% |
| 20 | log_gross_margin_trend | 0 | 1.4% | 36.7% |

---

## Regime-Conditional Performance

Performance bucketed by M03 market regime at entry time.

### Top Decile Performance by Regime

| Regime | N Trades | Win Rate | Mean Return | Median Return |
|--------|----------|----------|-------------|---------------|
| Strong Bear | 58 | 6.9% | -1.62% | -1.72% |
| Bear | 146 | 6.8% | -2.32% | -4.76% |
| Neutral | 283 | 17.3% | +2.03% | -3.14% |
| Bull | 223 | 14.3% | +3.28% | -2.98% |
| Strong Bull | 122 | 13.9% | +0.78% | -3.41% |

---

## Decile Performance Analysis

### Win Rate and Return by Predicted Decile

| Decile | N Trades | Win Rate | Mean Return | Median | Min | Max |
|--------|----------|----------|-------------|--------|-----|-----|
| 1 | 833 | 14.3% | +1.58% | -4.68% | -75.2% | +516.6% |
| 2 | 832 | 7.5% | +0.36% | -2.59% | -33.3% | +302.2% |
| 3 | 832 | 7.2% | +0.38% | -2.20% | -36.0% | +164.8% |
| 4 | 832 | 7.7% | +0.24% | -1.86% | -31.3% | +121.5% |
| 5 | 832 | 8.3% | +0.85% | -1.90% | -27.4% | +141.2% |
| 6 | 832 | 8.1% | +0.52% | -2.13% | -46.0% | +75.2% |
| 7 | 832 | 9.0% | +0.51% | -2.16% | -32.0% | +80.1% |
| 8 | 832 | 10.5% | +1.53% | -2.12% | -27.5% | +182.9% |
| 9 | 832 | 10.1% | +1.36% | -2.83% | -30.3% | +293.4% |
| 10 | 832 | 13.5% | +1.16% | -3.31% | -42.6% | +151.5% |

### Detailed Decile Statistics

Return distribution percentiles by predicted decile:

| Decile | N | Mean | Std | Min | P1 | P5 | P25 | P50 | P75 | P95 | P99 | Max |
|--------|---|------|-----|-----|----|----|-----|-----|-----|-----|-----|-----|
| 1 | 833 | +1.6 | 31.0 | -75 | -25 | -18 | -11 | -5 | +4 | +42 | +101 | +517 |
| 2 | 832 | +0.4 | 18.8 | -33 | -20 | -12 | -6 | -3 | +1 | +19 | +59 | +302 |
| 3 | 832 | +0.4 | 12.5 | -36 | -19 | -12 | -5 | -2 | +2 | +20 | +49 | +165 |
| 4 | 832 | +0.2 | 10.6 | -31 | -16 | -10 | -5 | -2 | +2 | +19 | +38 | +121 |
| 5 | 832 | +0.9 | 12.7 | -27 | -17 | -11 | -5 | -2 | +2 | +23 | +50 | +141 |
| 6 | 832 | +0.5 | 12.2 | -46 | -17 | -12 | -5 | -2 | +3 | +20 | +51 | +75 |
| 7 | 832 | +0.5 | 12.1 | -32 | -18 | -12 | -6 | -2 | +3 | +24 | +48 | +80 |
| 8 | 832 | +1.5 | 15.2 | -28 | -17 | -11 | -6 | -2 | +4 | +24 | +53 | +183 |
| 9 | 832 | +1.4 | 20.3 | -30 | -18 | -13 | -7 | -3 | +3 | +28 | +77 | +293 |
| 10 | 832 | +1.2 | 17.3 | -43 | -20 | -15 | -8 | -3 | +5 | +30 | +70 | +151 |

---

## Super Stock Classification

*Super Stock = Return > 50%*

**Market Base Rate:** 131 Super Stocks (1.57% of all trades)

### Precision & Recall

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Precision @ Top 10% | 2.28% | 19/832 top picks are Super Stocks |
| Recall @ Top 10% | 14.5% | 19/131 Super Stocks found in top decile |
| Lift @ Top 10% | 1.5x | vs random (1.57% base rate) |

### Percentile Lift (Granular Selection)

| Percentile | N | Super Stocks | Precision | Lift |
|------------|---|--------------|-----------|------|
| Top 1% | 84 | 1 | 1.2% | 0.8x |
| Top 2% | 167 | 4 | 2.4% | 1.5x |
| Top 5% | 417 | 12 | 2.9% | 1.8x |
| Top 10% | 833 | 19 | 2.3% | 1.4x |
| Top 20% | 1665 | 36 | 2.2% | 1.4x |

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