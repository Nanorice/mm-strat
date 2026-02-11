# Model Training Report - M01 (SEPA Signal Quality Model)

**Generated:** 2026-02-09 18:16:47
**Training Period:** 2020-01-01 to 2023-12-31
**Model Type:** REGRESSION
**Target:** target

---

## Executive Summary

**Trading Viability:** NOT VIABLE

### Key Metrics

- **Selection Edge:** +0.09% (range: [+0.09%, +0.09%])
- **Edge Consistency:** 1/1 folds positive (100%)
- **Edge Sharpe Ratio:** 0.00
- **Top Decile Return:** 1.48%
- **RMSE:** 2.01%
- **Walk-Forward Folds:** 1
- **Total Test Samples:** 1,390

---

## Walk-Forward Validation Results

| Fold | Test Year | Test Samples | RMSE | Selection Edge | Top Decile Mean |
|------|-----------|--------------|------|----------------|-----------------|
| 1 | 2023.0 | 1,390.0 | 2.01% | +0.09% | 1.48% |

---

## Feature Importance Analysis

**Total Features:** 72

### Top 20 Features by Gain

| Rank | Feature | Gain | % Total | Cumulative % |
|------|---------|------|---------|--------------|
| 1 | industry_id | 0 | 2.7% | 2.7% |
| 2 | alpha011 | 0 | 2.6% | 5.2% |
| 3 | m03_pillar_risk | 0 | 2.2% | 7.5% |
| 4 | log_Price_vs_SMA_200 | 0 | 2.2% | 9.7% |
| 5 | RS_Universe_Rank | 0 | 2.2% | 11.9% |
| 6 | m03_pillar_trend | 0 | 2.0% | 13.8% |
| 7 | log_gross_margin_trend | 0 | 1.8% | 15.6% |
| 8 | VCP_Ratio | 0 | 1.8% | 17.4% |
| 9 | m03_pillar_liq | 0 | 1.7% | 19.1% |
| 10 | RS_vs_Sector | 0 | 1.7% | 20.8% |
| 11 | log_Price_vs_SMA_200_Delta | 0 | 1.7% | 22.5% |
| 12 | log_Price_vs_SMA_50 | 0 | 1.7% | 24.2% |
| 13 | log_alpha060 | 0 | 1.7% | 25.9% |
| 14 | m03_delta_5d | 0 | 1.6% | 27.5% |
| 15 | m03_score | 0 | 1.6% | 29.1% |
| 16 | log_Price_vs_SMA_50_Lag1 | 0 | 1.6% | 30.8% |
| 17 | log_High_52W_Delta | 0 | 1.6% | 32.4% |
| 18 | log_alpha001 | 0 | 1.6% | 34.0% |
| 19 | roa | 0 | 1.5% | 35.5% |
| 20 | m03_regime_vol | 0 | 1.5% | 37.0% |

---

## Regime-Conditional Performance

Performance bucketed by M03 market regime at entry time.

### Top Decile Performance by Regime

| Regime | N Trades | Win Rate | Mean Return | Median Return |
|--------|----------|----------|-------------|---------------|
| Bear | 14 | 28.6% | +28.42% | +6.62% |
| Neutral | 48 | 25.0% | +4.29% | -3.17% |
| Bull | 66 | 12.1% | +1.30% | -2.07% |
| Strong Bull | 11 | 9.1% | +4.80% | -2.81% |

---

## Decile Performance Analysis

### Win Rate and Return by Predicted Decile

| Decile | N Trades | Win Rate | Mean Return | Median | Min | Max |
|--------|----------|----------|-------------|--------|-----|-----|
| 1 | 139 | 9.4% | -1.33% | -4.05% | -75.2% | +74.8% |
| 2 | 139 | 10.8% | +0.88% | -2.95% | -32.6% | +79.5% |
| 3 | 139 | 13.7% | +2.71% | -2.00% | -27.1% | +83.0% |
| 4 | 139 | 10.1% | +0.57% | -2.72% | -20.2% | +68.7% |
| 5 | 139 | 10.8% | +0.92% | -2.80% | -30.3% | +141.2% |
| 6 | 139 | 4.3% | -1.04% | -2.90% | -16.0% | +43.8% |
| 7 | 139 | 10.8% | +3.78% | -2.36% | -16.8% | +293.4% |
| 8 | 139 | 12.2% | +1.50% | -2.07% | -27.5% | +74.7% |
| 9 | 139 | 8.6% | -0.40% | -3.32% | -16.4% | +64.1% |
| 10 | 139 | 18.0% | +5.34% | -2.26% | -25.9% | +279.8% |

### Detailed Decile Statistics

Return distribution percentiles by predicted decile:

| Decile | N | Mean | Std | Min | P1 | P5 | P25 | P50 | P75 | P95 | P99 | Max |
|--------|---|------|-----|-----|----|----|-----|-----|-----|-----|-----|-----|
| 1 | 139 | -1.3 | 16.7 | -75 | -22 | -18 | -10 | -4 | +5 | +23 | +68 | +75 |
| 2 | 139 | +0.9 | 14.4 | -33 | -20 | -12 | -7 | -3 | +4 | +30 | +48 | +80 |
| 3 | 139 | +2.7 | 16.3 | -27 | -15 | -12 | -6 | -2 | +6 | +36 | +71 | +83 |
| 4 | 139 | +0.6 | 12.7 | -20 | -18 | -12 | -6 | -3 | +3 | +26 | +45 | +69 |
| 5 | 139 | +0.9 | 17.0 | -30 | -21 | -11 | -6 | -3 | +3 | +23 | +61 | +141 |
| 6 | 139 | -1.0 | 8.7 | -16 | -16 | -10 | -6 | -3 | +1 | +15 | +28 | +44 |
| 7 | 139 | +3.8 | 27.8 | -17 | -16 | -10 | -6 | -2 | +7 | +24 | +69 | +293 |
| 8 | 139 | +1.5 | 13.9 | -28 | -15 | -11 | -5 | -2 | +2 | +28 | +55 | +75 |
| 9 | 139 | -0.4 | 11.6 | -16 | -15 | -11 | -6 | -3 | +1 | +23 | +41 | +64 |
| 10 | 139 | +5.3 | 29.4 | -26 | -18 | -15 | -7 | -2 | +9 | +47 | +66 | +280 |

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
| Top 1% | 14 | 2 | 14.3% | 7.6x |
| Top 2% | 28 | 2 | 7.1% | 3.8x |
| Top 5% | 70 | 4 | 5.7% | 3.1x |
| Top 10% | 139 | 6 | 4.3% | 2.3x |
| Top 20% | 278 | 7 | 2.5% | 1.3x |

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