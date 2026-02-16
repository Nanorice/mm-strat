# Model Training Report - M01 (SEPA Signal Quality Model)

**Generated:** 2026-02-14 17:32:55
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
- **Top Decile Return:** 1.50%
- **RMSE:** 1.82%
- **Walk-Forward Folds:** 1
- **Total Test Samples:** 1,553

---

## Walk-Forward Validation Results

| Fold | Test Year | Test Samples | RMSE | Selection Edge | Top Decile Mean |
|------|-----------|--------------|------|----------------|-----------------|
| 1 | 2023.0 | 1,553.0 | 1.82% | +0.09% | 1.50% |

---

## Feature Importance Analysis

**Total Features:** 72

### Top 20 Features by Gain

| Rank | Feature | Gain | % Total | Cumulative % |
|------|---------|------|---------|--------------|
| 1 | m03_pillar_risk | 0 | 2.6% | 2.6% |
| 2 | industry_id | 0 | 2.5% | 5.1% |
| 3 | alpha011 | 0 | 2.3% | 7.5% |
| 4 | log_alpha009 | 0 | 2.1% | 9.6% |
| 5 | log_Price_vs_SMA_200 | 0 | 2.0% | 11.6% |
| 6 | m03_pillar_trend | 0 | 2.0% | 13.6% |
| 7 | log_Price_vs_SMA_50 | 0 | 2.0% | 15.6% |
| 8 | m03_pillar_liq | 0 | 2.0% | 17.6% |
| 9 | log_gross_margin_trend | 0 | 2.0% | 19.5% |
| 10 | log_alpha060 | 0 | 2.0% | 21.5% |
| 11 | log_High_52W_Delta | 0 | 1.8% | 23.3% |
| 12 | RS_Universe_Rank | 0 | 1.8% | 25.0% |
| 13 | log_Dist_From_52W_Low_Delta | 0 | 1.7% | 26.8% |
| 14 | log_Price_vs_SMA_50_Lag1 | 0 | 1.7% | 28.5% |
| 15 | m03_delta_5d | 0 | 1.6% | 30.1% |
| 16 | alpha101 | 0 | 1.6% | 31.7% |
| 17 | m03_score | 0 | 1.6% | 33.3% |
| 18 | RS_vs_Sector | 0 | 1.6% | 34.8% |
| 19 | m03_regime_vol | 0 | 1.5% | 36.4% |
| 20 | log_Dist_From_20D_Low_Delta | 0 | 1.5% | 37.9% |

---

## Regime-Conditional Performance

Performance bucketed by M03 market regime at entry time.

### Top Decile Performance by Regime

| Regime | N Trades | Win Rate | Mean Return | Median Return |
|--------|----------|----------|-------------|---------------|
| Bear | 12 | 16.7% | +29.38% | +8.49% |
| Neutral | 75 | 16.0% | +1.61% | -3.37% |
| Bull | 58 | 10.3% | +2.51% | -3.86% |
| Strong Bull | 11 | 9.1% | -0.59% | -2.26% |

---

## Decile Performance Analysis

### Win Rate and Return by Predicted Decile

| Decile | N Trades | Win Rate | Mean Return | Median | Min | Max |
|--------|----------|----------|-------------|--------|-----|-----|
| 1 | 156 | 8.3% | -2.14% | -3.80% | -75.2% | +57.7% |
| 2 | 155 | 10.3% | +0.80% | -1.84% | -32.6% | +73.5% |
| 3 | 155 | 7.1% | +0.29% | -2.25% | -20.2% | +115.9% |
| 4 | 155 | 6.5% | -1.11% | -2.95% | -30.3% | +74.8% |
| 5 | 156 | 5.1% | +0.21% | -1.80% | -18.9% | +79.5% |
| 6 | 155 | 14.2% | +5.34% | -1.66% | -27.5% | +293.4% |
| 7 | 155 | 10.3% | +2.62% | -1.67% | -25.0% | +141.2% |
| 8 | 155 | 9.7% | +0.99% | -2.60% | -12.3% | +63.2% |
| 9 | 155 | 7.7% | -0.35% | -2.30% | -25.9% | +74.9% |
| 10 | 156 | 13.5% | +3.92% | -3.10% | -42.6% | +279.8% |

### Detailed Decile Statistics

Return distribution percentiles by predicted decile:

| Decile | N | Mean | Std | Min | P1 | P5 | P25 | P50 | P75 | P95 | P99 | Max |
|--------|---|------|-----|-----|----|----|-----|-----|-----|-----|-----|-----|
| 1 | 156 | -2.1 | 13.7 | -75 | -21 | -17 | -9 | -4 | +4 | +17 | +44 | +58 |
| 2 | 155 | +0.8 | 12.2 | -33 | -17 | -12 | -6 | -2 | +4 | +25 | +39 | +73 |
| 3 | 155 | +0.3 | 13.6 | -20 | -17 | -11 | -5 | -2 | +3 | +21 | +38 | +116 |
| 4 | 155 | -1.1 | 12.1 | -30 | -20 | -14 | -7 | -3 | +0 | +22 | +50 | +75 |
| 5 | 156 | +0.2 | 10.7 | -19 | -15 | -10 | -5 | -2 | +2 | +16 | +40 | +80 |
| 6 | 155 | +5.3 | 28.3 | -28 | -13 | -7 | -4 | -2 | +4 | +40 | +89 | +293 |
| 7 | 155 | +2.6 | 17.4 | -25 | -14 | -9 | -5 | -2 | +3 | +34 | +65 | +141 |
| 8 | 155 | +1.0 | 12.8 | -12 | -12 | -9 | -6 | -3 | +1 | +28 | +54 | +63 |
| 9 | 155 | -0.4 | 12.0 | -26 | -18 | -13 | -6 | -2 | +1 | +20 | +44 | +75 |
| 10 | 156 | +3.9 | 28.3 | -43 | -17 | -13 | -7 | -3 | +5 | +40 | +77 | +280 |

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
| Top 1% | 16 | 0 | 0.0% | 0.0x |
| Top 2% | 32 | 2 | 6.2% | 3.6x |
| Top 5% | 78 | 4 | 5.1% | 2.9x |
| Top 10% | 156 | 6 | 3.8% | 2.2x |
| Top 20% | 311 | 8 | 2.6% | 1.5x |

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