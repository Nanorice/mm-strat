# Model Training Report - M01 (SEPA Signal Quality Model)

**Generated:** 2026-02-09 18:16:25
**Training Period:** 2020-01-01 to 2023-12-31
**Model Type:** REGRESSION
**Target:** target

---

## Executive Summary

**Trading Viability:** MARGINAL

### Key Metrics

- **Selection Edge:** +0.66% (range: [+0.66%, +0.66%])
- **Edge Consistency:** 1/1 folds positive (100%)
- **Edge Sharpe Ratio:** 0.00
- **Top Decile Return:** 2.79%
- **RMSE:** 0.98%
- **Walk-Forward Folds:** 1
- **Total Test Samples:** 1,390

---

## Walk-Forward Validation Results

| Fold | Test Year | Test Samples | RMSE | Selection Edge | Top Decile Mean |
|------|-----------|--------------|------|----------------|-----------------|
| 1 | 2023.0 | 1,390.0 | 0.98% | +0.66% | 2.79% |

---

## Feature Importance Analysis

**Total Features:** 72

### Top 20 Features by Gain

| Rank | Feature | Gain | % Total | Cumulative % |
|------|---------|------|---------|--------------|
| 1 | log_Price_vs_SMA_200 | 0 | 11.9% | 11.9% |
| 2 | log_Price_vs_SMA_50 | 0 | 6.0% | 17.9% |
| 3 | industry_id | 0 | 2.8% | 20.7% |
| 4 | m03_pillar_risk | 0 | 2.8% | 23.5% |
| 5 | alpha011 | 0 | 2.7% | 26.2% |
| 6 | log_RS | 0 | 1.9% | 28.1% |
| 7 | log_revenue_growth_yoy | 0 | 1.7% | 29.8% |
| 8 | m03_pillar_trend | 0 | 1.6% | 31.4% |
| 9 | alpha054 | 0 | 1.6% | 33.0% |
| 10 | log_vol_ma20 | 0 | 1.5% | 34.5% |
| 11 | m03_regime_vol | 0 | 1.5% | 36.0% |
| 12 | log_revenue_accel | 0 | 1.5% | 37.5% |
| 13 | log_High_52W_Delta | 0 | 1.4% | 39.0% |
| 14 | m03_score | 0 | 1.4% | 40.4% |
| 15 | m03_pillar_liq | 0 | 1.4% | 41.7% |
| 16 | sector_id | 0 | 1.3% | 43.0% |
| 17 | log_volume_acceleration | 0 | 1.2% | 44.3% |
| 18 | gross_margin | 0 | 1.2% | 45.5% |
| 19 | log_days_since_report | 0 | 1.2% | 46.7% |
| 20 | eps_stability_score | 0 | 1.2% | 47.9% |

---

## Regime-Conditional Performance

Performance bucketed by M03 market regime at entry time.

### Top Decile Performance by Regime

| Regime | N Trades | Win Rate | Mean Return | Median Return |
|--------|----------|----------|-------------|---------------|
| Bear | 15 | 20.0% | +1.14% | +0.30% |
| Neutral | 41 | 34.1% | +15.30% | +1.96% |
| Bull | 60 | 10.0% | -0.62% | -5.14% |
| Strong Bull | 23 | 17.4% | +3.37% | -2.26% |

---

## Decile Performance Analysis

### Win Rate and Return by Predicted Decile

| Decile | N Trades | Win Rate | Mean Return | Median | Min | Max |
|--------|----------|----------|-------------|--------|-----|-----|
| 1 | 139 | 4.3% | -1.29% | -2.80% | -13.6% | +22.1% |
| 2 | 139 | 5.8% | -0.38% | -2.26% | -22.9% | +68.7% |
| 3 | 139 | 6.5% | -0.12% | -2.50% | -15.3% | +48.8% |
| 4 | 139 | 11.5% | +1.83% | -2.30% | -12.6% | +43.8% |
| 5 | 139 | 8.6% | +0.14% | -2.70% | -27.1% | +64.8% |
| 6 | 139 | 15.1% | +1.85% | -2.62% | -27.5% | +80.5% |
| 7 | 139 | 7.9% | +1.56% | -2.96% | -18.2% | +141.2% |
| 8 | 139 | 15.1% | +3.16% | -3.91% | -25.0% | +279.8% |
| 9 | 139 | 14.4% | +1.26% | -4.16% | -32.6% | +75.0% |
| 10 | 139 | 19.4% | +4.92% | -2.53% | -75.2% | +293.4% |

### Detailed Decile Statistics

Return distribution percentiles by predicted decile:

| Decile | N | Mean | Std | Min | P1 | P5 | P25 | P50 | P75 | P95 | P99 | Max |
|--------|---|------|-----|-----|----|----|-----|-----|-----|-----|-----|-----|
| 1 | 139 | -1.3 | 6.5 | -14 | -11 | -9 | -5 | -3 | +0 | +14 | +21 | +22 |
| 2 | 139 | -0.4 | 9.7 | -23 | -11 | -9 | -5 | -2 | +1 | +16 | +34 | +69 |
| 3 | 139 | -0.1 | 8.7 | -15 | -14 | -11 | -5 | -2 | +3 | +18 | +25 | +49 |
| 4 | 139 | +1.8 | 11.2 | -13 | -11 | -9 | -5 | -2 | +6 | +25 | +42 | +44 |
| 5 | 139 | +0.1 | 11.9 | -27 | -16 | -12 | -7 | -3 | +2 | +19 | +43 | +65 |
| 6 | 139 | +1.9 | 14.8 | -28 | -23 | -13 | -6 | -3 | +6 | +27 | +59 | +81 |
| 7 | 139 | +1.6 | 18.2 | -18 | -13 | -10 | -6 | -3 | +2 | +24 | +77 | +141 |
| 8 | 139 | +3.2 | 28.7 | -25 | -18 | -14 | -9 | -4 | +5 | +39 | +68 | +280 |
| 9 | 139 | +1.3 | 17.5 | -33 | -22 | -16 | -10 | -4 | +8 | +35 | +64 | +75 |
| 10 | 139 | +4.9 | 33.0 | -75 | -26 | -17 | -10 | -3 | +8 | +52 | +80 | +293 |

### Survivor Rate by Decile

| Decile | N | Survivor Rate | Crash Rate | Avg MFE | Avg MAE |
|--------|---|---------------|------------|---------|---------|
| 1 | 139 | 47.5% | 52.5% | +5.7% | -4.7% |
| 2 | 139 | 48.2% | 51.8% | +8.0% | -5.2% |
| 3 | 139 | 51.1% | 48.9% | +8.8% | -5.3% |
| 4 | 139 | 45.3% | 54.7% | +11.9% | -5.4% |
| 5 | 139 | 44.6% | 55.4% | +11.1% | -6.6% |
| 6 | 139 | 46.0% | 54.0% | +15.2% | -6.7% |
| 7 | 139 | 36.0% | 64.0% | +13.8% | -7.0% |
| 8 | 139 | 38.1% | 61.9% | +19.1% | -8.9% |
| 9 | 139 | 43.2% | 56.8% | +17.9% | -9.4% |
| 10 | 139 | 43.2% | 56.8% | +27.0% | -11.4% |

---

## Super Stock Classification

*Super Stock = Return > 50%*

**Market Base Rate:** 26 Super Stocks (1.87% of all trades)

### Precision & Recall

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Precision @ Top 10% | 5.76% | 8/139 top picks are Super Stocks |
| Recall @ Top 10% | 30.8% | 8/26 Super Stocks found in top decile |
| Lift @ Top 10% | 3.1x | vs random (1.87% base rate) |

### Percentile Lift (Granular Selection)

| Percentile | N | Super Stocks | Precision | Lift |
|------------|---|--------------|-----------|------|
| Top 1% | 14 | 1 | 7.1% | 3.8x |
| Top 2% | 28 | 1 | 3.6% | 1.9x |
| Top 5% | 70 | 5 | 7.1% | 3.8x |
| Top 10% | 139 | 8 | 5.8% | 3.1x |
| Top 20% | 278 | 12 | 4.3% | 2.3x |

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