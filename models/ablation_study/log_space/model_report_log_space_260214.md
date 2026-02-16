# Model Training Report - M01 (SEPA Signal Quality Model)

**Generated:** 2026-02-14 17:31:55
**Training Period:** 2020-01-01 to 2023-12-31
**Model Type:** REGRESSION
**Target:** target

---

## Executive Summary

**Trading Viability:** MARGINAL

### Key Metrics

- **Selection Edge:** +0.70% (range: [+0.70%, +0.70%])
- **Edge Consistency:** 1/1 folds positive (100%)
- **Edge Sharpe Ratio:** 0.00
- **Top Decile Return:** 2.68%
- **RMSE:** 0.97%
- **Walk-Forward Folds:** 1
- **Total Test Samples:** 1,553

---

## Walk-Forward Validation Results

| Fold | Test Year | Test Samples | RMSE | Selection Edge | Top Decile Mean |
|------|-----------|--------------|------|----------------|-----------------|
| 1 | 2023.0 | 1,553.0 | 0.97% | +0.70% | 2.68% |

---

## Feature Importance Analysis

**Total Features:** 72

### Top 20 Features by Gain

| Rank | Feature | Gain | % Total | Cumulative % |
|------|---------|------|---------|--------------|
| 1 | log_Price_vs_SMA_200 | 0 | 9.9% | 9.9% |
| 2 | log_Price_vs_SMA_50 | 0 | 9.5% | 19.5% |
| 3 | industry_id | 0 | 2.7% | 22.2% |
| 4 | m03_pillar_risk | 0 | 2.6% | 24.8% |
| 5 | alpha011 | 0 | 2.5% | 27.3% |
| 6 | alpha054 | 0 | 2.0% | 29.2% |
| 7 | log_RS | 0 | 1.7% | 30.9% |
| 8 | log_mom_63d | 0 | 1.6% | 32.5% |
| 9 | m03_pillar_trend | 0 | 1.5% | 34.1% |
| 10 | m03_score | 0 | 1.5% | 35.6% |
| 11 | sector_id | 0 | 1.5% | 37.1% |
| 12 | alpha004 | 0 | 1.4% | 38.5% |
| 13 | alpha013 | 0 | 1.4% | 39.9% |
| 14 | log_revenue_growth_yoy | 0 | 1.4% | 41.3% |
| 15 | m03_regime_vol | 0 | 1.4% | 42.7% |
| 16 | alpha041 | 0 | 1.4% | 44.0% |
| 17 | m03_pillar_liq | 0 | 1.3% | 45.4% |
| 18 | VCP_Ratio | 0 | 1.3% | 46.7% |
| 19 | operating_margin | 0 | 1.2% | 47.9% |
| 20 | log_Price_vs_SMA_50_Lag1 | 0 | 1.2% | 49.1% |

---

## Regime-Conditional Performance

Performance bucketed by M03 market regime at entry time.

### Top Decile Performance by Regime

| Regime | N Trades | Win Rate | Mean Return | Median Return |
|--------|----------|----------|-------------|---------------|
| Bear | 11 | 27.3% | +3.28% | +7.80% |
| Neutral | 43 | 27.9% | +4.70% | +0.59% |
| Bull | 78 | 11.5% | -1.03% | -5.24% |
| Strong Bull | 24 | 20.8% | +5.43% | +1.47% |

---

## Decile Performance Analysis

### Win Rate and Return by Predicted Decile

| Decile | N Trades | Win Rate | Mean Return | Median | Min | Max |
|--------|----------|----------|-------------|--------|-----|-----|
| 1 | 156 | 3.2% | -0.48% | -1.87% | -11.5% | +41.7% |
| 2 | 155 | 5.2% | -0.53% | -1.89% | -11.9% | +40.5% |
| 3 | 155 | 5.2% | +0.14% | -1.68% | -15.0% | +56.9% |
| 4 | 155 | 4.5% | +0.10% | -1.71% | -22.9% | +50.6% |
| 5 | 156 | 9.0% | +0.06% | -2.53% | -15.0% | +42.2% |
| 6 | 155 | 10.3% | +1.31% | -2.63% | -25.9% | +74.8% |
| 7 | 155 | 7.7% | +0.96% | -2.91% | -27.5% | +141.2% |
| 8 | 155 | 10.3% | +0.87% | -4.12% | -19.9% | +79.5% |
| 9 | 155 | 18.7% | +6.31% | -4.16% | -32.6% | +293.4% |
| 10 | 156 | 18.6% | +1.85% | -2.49% | -75.2% | +74.9% |

### Detailed Decile Statistics

Return distribution percentiles by predicted decile:

| Decile | N | Mean | Std | Min | P1 | P5 | P25 | P50 | P75 | P95 | P99 | Max |
|--------|---|------|-----|-----|----|----|-----|-----|-----|-----|-----|-----|
| 1 | 156 | -0.5 | 6.8 | -12 | -9 | -6 | -4 | -2 | +0 | +8 | +31 | +42 |
| 2 | 155 | -0.5 | 7.9 | -12 | -11 | -8 | -4 | -2 | -0 | +15 | +38 | +41 |
| 3 | 155 | +0.1 | 9.2 | -15 | -10 | -8 | -4 | -2 | +1 | +16 | +38 | +57 |
| 4 | 155 | +0.1 | 8.6 | -23 | -14 | -8 | -4 | -2 | +2 | +15 | +29 | +51 |
| 5 | 156 | +0.1 | 10.0 | -15 | -13 | -9 | -6 | -3 | +2 | +20 | +36 | +42 |
| 6 | 155 | +1.3 | 12.5 | -26 | -14 | -11 | -6 | -3 | +5 | +24 | +41 | +75 |
| 7 | 155 | +1.0 | 19.3 | -28 | -21 | -12 | -7 | -3 | +1 | +21 | +96 | +141 |
| 8 | 155 | +0.9 | 16.8 | -20 | -17 | -13 | -8 | -4 | +4 | +32 | +73 | +80 |
| 9 | 155 | +6.3 | 37.6 | -33 | -17 | -15 | -10 | -4 | +9 | +49 | +191 | +293 |
| 10 | 156 | +1.8 | 20.5 | -75 | -36 | -18 | -10 | -2 | +8 | +43 | +66 | +75 |

### Survivor Rate by Decile

| Decile | N | Survivor Rate | Crash Rate | Avg MFE | Avg MAE |
|--------|---|---------------|------------|---------|---------|
| 1 | 156 | 61.5% | 38.5% | +4.8% | -4.0% |
| 2 | 155 | 57.4% | 42.6% | +5.8% | -4.6% |
| 3 | 155 | 59.4% | 40.6% | +7.8% | -4.9% |
| 4 | 155 | 51.6% | 48.4% | +7.9% | -5.1% |
| 5 | 156 | 41.7% | 58.3% | +9.4% | -6.0% |
| 6 | 155 | 49.7% | 50.3% | +12.8% | -6.3% |
| 7 | 155 | 45.2% | 54.8% | +13.1% | -7.2% |
| 8 | 155 | 38.7% | 61.3% | +15.3% | -8.4% |
| 9 | 155 | 41.9% | 58.1% | +22.9% | -9.0% |
| 10 | 156 | 48.7% | 51.3% | +23.0% | -11.7% |

---

## Super Stock Classification

*Super Stock = Return > 50%*

**Market Base Rate:** 27 Super Stocks (1.74% of all trades)

### Precision & Recall

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Precision @ Top 10% | 3.85% | 6/156 top picks are Super Stocks |
| Recall @ Top 10% | 22.2% | 6/27 Super Stocks found in top decile |
| Lift @ Top 10% | 2.2x | vs random (1.74% base rate) |

### Percentile Lift (Granular Selection)

| Percentile | N | Super Stocks | Precision | Lift |
|------------|---|--------------|-----------|------|
| Top 1% | 16 | 1 | 6.2% | 3.6x |
| Top 2% | 32 | 2 | 6.2% | 3.6x |
| Top 5% | 78 | 3 | 3.8% | 2.2x |
| Top 10% | 156 | 6 | 3.8% | 2.2x |
| Top 20% | 311 | 14 | 4.5% | 2.6x |

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