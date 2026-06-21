# Model Training Report - M01 (SEPA Signal Quality Model)

**Generated:** 2026-02-14 17:31:04
**Training Period:** 2020-01-01 to 2023-12-31
**Model Type:** REGRESSION
**Target:** target

---

## Executive Summary

**Trading Viability:** VIABLE

### Key Metrics

- **Selection Edge:** +7.92% (range: [+7.92%, +7.92%])
- **Edge Consistency:** 1/1 folds positive (100%)
- **Edge Sharpe Ratio:** 0.00
- **Top Decile Return:** 12.80%
- **RMSE:** 23.03%
- **Walk-Forward Folds:** 1
- **Total Test Samples:** 1,553

---

## Walk-Forward Validation Results

| Fold | Test Year | Test Samples | RMSE | Selection Edge | Top Decile Mean |
|------|-----------|--------------|------|----------------|-----------------|
| 1 | 2023.0 | 1,553.0 | 23.03% | +7.92% | 12.80% |

---

## Feature Importance Analysis

**Total Features:** 72

### Top 20 Features by Gain

| Rank | Feature | Gain | % Total | Cumulative % |
|------|---------|------|---------|--------------|
| 1 | log_debt_to_equity | 0 | 4.2% | 4.2% |
| 2 | log_Price_vs_SMA_50_Lag1 | 0 | 3.0% | 7.2% |
| 3 | log_pb_ratio | 0 | 2.7% | 9.9% |
| 4 | log_volume_acceleration | 0 | 2.7% | 12.6% |
| 5 | alpha011 | 0 | 2.2% | 14.8% |
| 6 | industry_id | 0 | 2.1% | 16.9% |
| 7 | log_Price_vs_SMA_200 | 0 | 2.0% | 18.9% |
| 8 | alpha101 | 0 | 2.0% | 20.9% |
| 9 | turnover_ma20 | 0 | 1.9% | 22.8% |
| 10 | m03_pillar_risk | 0 | 1.9% | 24.8% |
| 11 | log_Price_vs_SMA_50 | 0 | 1.9% | 26.7% |
| 12 | Dist_From_20D_High_Delta | 0 | 1.9% | 28.5% |
| 13 | alpha041 | 0 | 1.9% | 30.4% |
| 14 | log_alpha001 | 0 | 1.8% | 32.2% |
| 15 | m03_delta_20d | 0 | 1.8% | 34.0% |
| 16 | roe | 0 | 1.8% | 35.8% |
| 17 | log_VCP_Ratio_Delta | 0 | 1.7% | 37.5% |
| 18 | operating_margin | 0 | 1.7% | 39.2% |
| 19 | current_ratio | 0 | 1.7% | 40.9% |
| 20 | m03_regime_vol | 0 | 1.7% | 42.6% |

---

## Regime-Conditional Performance

Performance bucketed by M03 market regime at entry time.

### Top Decile Performance by Regime

| Regime | N Trades | Win Rate | Mean Return | Median Return |
|--------|----------|----------|-------------|---------------|
| Bear | 14 | 35.7% | +32.46% | +8.86% |
| Neutral | 41 | 14.6% | -0.62% | -3.37% |
| Bull | 55 | 9.1% | +1.98% | -1.52% |
| Strong Bull | 46 | 19.6% | +1.69% | -0.85% |

---

## Decile Performance Analysis

### Win Rate and Return by Predicted Decile

| Decile | N Trades | Win Rate | Mean Return | Median | Min | Max |
|--------|----------|----------|-------------|--------|-----|-----|
| 1 | 156 | 9.6% | +1.91% | -2.86% | -18.2% | +115.9% |
| 2 | 155 | 7.1% | -0.35% | -1.88% | -15.4% | +38.5% |
| 3 | 155 | 7.7% | +2.21% | -1.94% | -22.9% | +293.4% |
| 4 | 155 | 6.5% | +0.38% | -2.60% | -15.0% | +66.0% |
| 5 | 156 | 6.4% | +1.10% | -1.15% | -19.9% | +113.9% |
| 6 | 155 | 11.6% | +1.42% | -2.42% | -25.0% | +141.2% |
| 7 | 155 | 11.0% | +0.96% | -2.94% | -19.5% | +72.5% |
| 8 | 155 | 7.1% | -0.45% | -2.90% | -27.5% | +79.5% |
| 9 | 155 | 9.7% | -0.59% | -3.36% | -75.2% | +63.2% |
| 10 | 156 | 16.0% | +3.95% | -1.50% | -42.6% | +279.8% |

### Detailed Decile Statistics

Return distribution percentiles by predicted decile:

| Decile | N | Mean | Std | Min | P1 | P5 | P25 | P50 | P75 | P95 | P99 | Max |
|--------|---|------|-----|-----|----|----|-----|-----|-----|-----|-----|-----|
| 1 | 156 | +1.9 | 17.3 | -18 | -17 | -13 | -6 | -3 | +4 | +31 | +74 | +116 |
| 2 | 155 | -0.3 | 8.8 | -15 | -13 | -11 | -5 | -2 | +2 | +17 | +32 | +38 |
| 3 | 155 | +2.2 | 25.7 | -23 | -15 | -10 | -5 | -2 | +2 | +19 | +54 | +293 |
| 4 | 155 | +0.4 | 11.6 | -15 | -13 | -9 | -5 | -3 | +2 | +20 | +53 | +66 |
| 5 | 156 | +1.1 | 14.7 | -20 | -17 | -11 | -5 | -1 | +2 | +24 | +59 | +114 |
| 6 | 155 | +1.4 | 16.8 | -25 | -18 | -12 | -6 | -2 | +2 | +30 | +56 | +141 |
| 7 | 155 | +1.0 | 13.6 | -19 | -15 | -11 | -6 | -3 | +2 | +27 | +54 | +72 |
| 8 | 155 | -0.4 | 13.4 | -28 | -22 | -13 | -6 | -3 | +1 | +20 | +70 | +80 |
| 9 | 155 | -0.6 | 15.4 | -75 | -26 | -15 | -8 | -3 | +1 | +35 | +49 | +63 |
| 10 | 156 | +3.9 | 27.4 | -43 | -25 | -15 | -7 | -1 | +7 | +35 | +69 | +280 |

### Survivor Rate by Decile

| Decile | N | Survivor Rate | Crash Rate | Avg MFE | Avg MAE |
|--------|---|---------------|------------|---------|---------|
| 1 | 156 | 27.6% | 72.4% | +12.9% | -8.2% |
| 2 | 155 | 44.5% | 55.5% | +8.9% | -6.2% |
| 3 | 155 | 47.1% | 52.9% | +11.9% | -6.0% |
| 4 | 155 | 45.2% | 54.8% | +9.9% | -5.9% |
| 5 | 156 | 60.9% | 39.1% | +10.5% | -5.6% |
| 6 | 155 | 47.1% | 52.9% | +12.0% | -6.3% |
| 7 | 155 | 51.0% | 49.0% | +11.9% | -6.4% |
| 8 | 155 | 57.4% | 42.6% | +11.0% | -6.6% |
| 9 | 155 | 53.5% | 46.5% | +13.9% | -7.5% |
| 10 | 156 | 61.5% | 38.5% | +20.0% | -8.4% |

---

## Super Stock Classification

*Super Stock = Return > 50%*

**Market Base Rate:** 27 Super Stocks (1.74% of all trades)

### Precision & Recall

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Precision @ Top 10% | 2.56% | 4/156 top picks are Super Stocks |
| Recall @ Top 10% | 14.8% | 4/27 Super Stocks found in top decile |
| Lift @ Top 10% | 1.5x | vs random (1.74% base rate) |

### Percentile Lift (Granular Selection)

| Percentile | N | Super Stocks | Precision | Lift |
|------------|---|--------------|-----------|------|
| Top 1% | 16 | 0 | 0.0% | 0.0x |
| Top 2% | 32 | 1 | 3.1% | 1.8x |
| Top 5% | 78 | 2 | 2.6% | 1.5x |
| Top 10% | 156 | 4 | 2.6% | 1.5x |
| Top 20% | 311 | 6 | 1.9% | 1.1x |

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