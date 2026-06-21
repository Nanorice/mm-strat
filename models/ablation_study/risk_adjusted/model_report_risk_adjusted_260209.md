# Model Training Report - M01 (SEPA Signal Quality Model)

**Generated:** 2026-02-09 18:16:11
**Training Period:** 2020-01-01 to 2023-12-31
**Model Type:** REGRESSION
**Target:** target

---

## Executive Summary

**Trading Viability:** MARGINAL

### Key Metrics

- **Selection Edge:** +1.08% (range: [+1.08%, +1.08%])
- **Edge Consistency:** 1/1 folds positive (100%)
- **Edge Sharpe Ratio:** 0.00
- **Top Decile Return:** 5.43%
- **RMSE:** 4.96%
- **Walk-Forward Folds:** 1
- **Total Test Samples:** 1,390

---

## Walk-Forward Validation Results

| Fold | Test Year | Test Samples | RMSE | Selection Edge | Top Decile Mean |
|------|-----------|--------------|------|----------------|-----------------|
| 1 | 2023.0 | 1,390.0 | 4.96% | +1.08% | 5.43% |

---

## Feature Importance Analysis

**Total Features:** 72

### Top 20 Features by Gain

| Rank | Feature | Gain | % Total | Cumulative % |
|------|---------|------|---------|--------------|
| 1 | alpha011 | 0 | 3.0% | 3.0% |
| 2 | m03_pillar_risk | 0 | 2.9% | 5.9% |
| 3 | industry_id | 0 | 2.7% | 8.6% |
| 4 | m03_pillar_trend | 0 | 2.4% | 11.0% |
| 5 | log_Price_vs_SMA_200 | 0 | 2.2% | 13.2% |
| 6 | m03_score | 0 | 2.0% | 15.1% |
| 7 | log_gross_margin_trend | 0 | 1.8% | 17.0% |
| 8 | pe_ratio | 0 | 1.8% | 18.8% |
| 9 | VCP_Ratio | 0 | 1.7% | 20.5% |
| 10 | log_Dist_From_20D_Low_Delta | 0 | 1.7% | 22.2% |
| 11 | log_Price_vs_SMA_50 | 0 | 1.6% | 23.8% |
| 12 | log_fcf_margin | 0 | 1.6% | 25.5% |
| 13 | log_revenue_accel | 0 | 1.6% | 27.1% |
| 14 | Price_vs_SMA_150_Delta | 0 | 1.5% | 28.6% |
| 15 | alpha046 | 0 | 1.5% | 30.2% |
| 16 | log_Price_vs_SMA_50_Lag1 | 0 | 1.5% | 31.7% |
| 17 | Price_vs_SMA_50_Delta | 0 | 1.5% | 33.2% |
| 18 | turnover_ma20 | 0 | 1.5% | 34.7% |
| 19 | log_days_since_report | 0 | 1.5% | 36.2% |
| 20 | m03_regime_vol | 0 | 1.5% | 37.7% |

---

## Regime-Conditional Performance

Performance bucketed by M03 market regime at entry time.

### Top Decile Performance by Regime

| Regime | N Trades | Win Rate | Mean Return | Median Return |
|--------|----------|----------|-------------|---------------|
| Bear | 15 | 33.3% | +27.69% | +0.30% |
| Neutral | 30 | 26.7% | +7.32% | -0.54% |
| Bull | 65 | 10.8% | -1.76% | -5.20% |
| Strong Bull | 29 | 13.8% | +4.39% | +1.94% |

---

## Decile Performance Analysis

### Win Rate and Return by Predicted Decile

| Decile | N Trades | Win Rate | Mean Return | Median | Min | Max |
|--------|----------|----------|-------------|--------|-----|-----|
| 1 | 139 | 4.3% | -1.51% | -2.98% | -22.9% | +38.5% |
| 2 | 139 | 9.4% | +0.43% | -3.22% | -12.6% | +68.7% |
| 3 | 139 | 7.2% | +0.16% | -2.94% | -18.8% | +80.5% |
| 4 | 139 | 11.5% | +1.08% | -2.98% | -18.4% | +74.8% |
| 5 | 139 | 11.5% | +0.75% | -2.56% | -27.1% | +74.7% |
| 6 | 139 | 9.4% | -0.29% | -2.81% | -75.2% | +35.3% |
| 7 | 139 | 12.9% | +1.88% | -2.61% | -30.3% | +141.2% |
| 8 | 139 | 10.1% | +3.05% | -1.81% | -15.2% | +293.4% |
| 9 | 139 | 15.1% | +2.70% | -2.60% | -32.6% | +75.0% |
| 10 | 139 | 17.3% | +4.66% | -2.76% | -25.9% | +279.8% |

### Detailed Decile Statistics

Return distribution percentiles by predicted decile:

| Decile | N | Mean | Std | Min | P1 | P5 | P25 | P50 | P75 | P95 | P99 | Max |
|--------|---|------|-----|-----|----|----|-----|-----|-----|-----|-----|-----|
| 1 | 139 | -1.5 | 9.1 | -23 | -19 | -15 | -6 | -3 | +2 | +14 | +30 | +38 |
| 2 | 139 | +0.4 | 12.1 | -13 | -12 | -10 | -6 | -3 | +1 | +22 | +51 | +69 |
| 3 | 139 | +0.2 | 12.7 | -19 | -14 | -11 | -6 | -3 | +4 | +17 | +63 | +81 |
| 4 | 139 | +1.1 | 14.3 | -18 | -17 | -12 | -6 | -3 | +3 | +27 | +57 | +75 |
| 5 | 139 | +0.8 | 14.9 | -27 | -17 | -13 | -7 | -3 | +2 | +30 | +59 | +75 |
| 6 | 139 | -0.3 | 12.0 | -75 | -19 | -12 | -6 | -3 | +5 | +20 | +32 | +35 |
| 7 | 139 | +1.9 | 18.5 | -30 | -21 | -13 | -6 | -3 | +3 | +31 | +70 | +141 |
| 8 | 139 | +3.0 | 27.5 | -15 | -14 | -13 | -7 | -2 | +4 | +23 | +48 | +293 |
| 9 | 139 | +2.7 | 16.8 | -33 | -26 | -15 | -6 | -3 | +9 | +29 | +71 | +75 |
| 10 | 139 | +4.7 | 30.2 | -26 | -20 | -16 | -9 | -3 | +7 | +47 | +77 | +280 |

### Survivor Rate by Decile

| Decile | N | Survivor Rate | Crash Rate | Avg MFE | Avg MAE |
|--------|---|---------------|------------|---------|---------|
| 1 | 139 | 44.6% | 55.4% | +8.7% | -6.9% |
| 2 | 139 | 49.6% | 50.4% | +10.1% | -5.7% |
| 3 | 139 | 46.0% | 54.0% | +11.1% | -6.3% |
| 4 | 139 | 42.4% | 57.6% | +13.8% | -6.9% |
| 5 | 139 | 45.3% | 54.7% | +12.4% | -7.1% |
| 6 | 139 | 43.9% | 56.1% | +12.4% | -7.0% |
| 7 | 139 | 41.7% | 58.3% | +14.7% | -7.2% |
| 8 | 139 | 46.8% | 53.2% | +17.0% | -6.9% |
| 9 | 139 | 43.2% | 56.8% | +17.0% | -7.6% |
| 10 | 139 | 39.6% | 60.4% | +21.2% | -9.2% |

---

## Super Stock Classification

*Super Stock = Return > 50%*

**Market Base Rate:** 26 Super Stocks (1.87% of all trades)

### Precision & Recall

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Precision @ Top 10% | 4.32% | 6/139 top picks are Super Stocks |
| Recall @ Top 10% | 23.1% | 6/26 Super Stocks found in top decile |
| Lift @ Top 10% | 2.3x | vs random (1.87% base rate) |

### Percentile Lift (Granular Selection)

| Percentile | N | Super Stocks | Precision | Lift |
|------------|---|--------------|-----------|------|
| Top 1% | 14 | 1 | 7.1% | 3.8x |
| Top 2% | 28 | 2 | 7.1% | 3.8x |
| Top 5% | 70 | 3 | 4.3% | 2.3x |
| Top 10% | 139 | 6 | 4.3% | 2.3x |
| Top 20% | 278 | 11 | 4.0% | 2.1x |

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