# Model Training Report - M01 (SEPA Signal Quality Model)

**Generated:** 2026-02-09 18:15:46
**Training Period:** 2020-01-01 to 2023-12-31
**Model Type:** REGRESSION
**Target:** target

---

## Executive Summary

**Trading Viability:** VIABLE

### Key Metrics

- **Selection Edge:** +1.72% (range: [+1.72%, +1.72%])
- **Edge Consistency:** 1/1 folds positive (100%)
- **Edge Sharpe Ratio:** 0.00
- **Top Decile Return:** 3.01%
- **RMSE:** 18.80%
- **Walk-Forward Folds:** 1
- **Total Test Samples:** 1,390

---

## Walk-Forward Validation Results

| Fold | Test Year | Test Samples | RMSE | Selection Edge | Top Decile Mean |
|------|-----------|--------------|------|----------------|-----------------|
| 1 | 2023.0 | 1,390.0 | 18.80% | +1.72% | 3.01% |

---

## Feature Importance Analysis

**Total Features:** 72

### Top 20 Features by Gain

| Rank | Feature | Gain | % Total | Cumulative % |
|------|---------|------|---------|--------------|
| 1 | alpha046 | 0 | 7.4% | 7.4% |
| 2 | earnings_quality_score | 0 | 3.1% | 10.6% |
| 3 | operating_margin | 0 | 2.7% | 13.3% |
| 4 | turnover_ma20 | 0 | 2.6% | 15.9% |
| 5 | log_Dry_Up_Volume_Delta | 0 | 2.5% | 18.4% |
| 6 | log_High_52W_Delta | 0 | 2.5% | 20.8% |
| 7 | m03_score | 0 | 2.4% | 23.2% |
| 8 | log_Price_vs_SMA_200 | 0 | 2.3% | 25.5% |
| 9 | log_volume_acceleration | 0 | 2.2% | 27.7% |
| 10 | log_Dist_From_20D_Low_Delta | 0 | 2.1% | 29.9% |
| 11 | log_Price_vs_SMA_50 | 0 | 2.0% | 31.9% |
| 12 | log_alpha001 | 0 | 2.0% | 33.8% |
| 13 | log_RS | 0 | 2.0% | 35.8% |
| 14 | sector_id | 0 | 1.9% | 37.7% |
| 15 | eps_stability_score | 0 | 1.9% | 39.6% |
| 16 | m03_delta_20d | 0 | 1.9% | 41.5% |
| 17 | gross_margin | 0 | 1.9% | 43.3% |
| 18 | alpha041 | 0 | 1.8% | 45.1% |
| 19 | log_Price_vs_SMA_50_Lag1 | 0 | 1.7% | 46.9% |
| 20 | Price_vs_SMA_50_Delta | 0 | 1.7% | 48.6% |

---

## Regime-Conditional Performance

Performance bucketed by M03 market regime at entry time.

### Top Decile Performance by Regime

| Regime | N Trades | Win Rate | Mean Return | Median Return |
|--------|----------|----------|-------------|---------------|
| Bear | 16 | 18.8% | +0.06% | -2.62% |
| Neutral | 33 | 24.2% | +14.34% | -1.39% |
| Bull | 55 | 9.1% | -2.15% | -4.61% |
| Strong Bull | 35 | 17.1% | +1.79% | -2.60% |

---

## Decile Performance Analysis

### Win Rate and Return by Predicted Decile

| Decile | N Trades | Win Rate | Mean Return | Median | Min | Max |
|--------|----------|----------|-------------|--------|-----|-----|
| 1 | 139 | 8.6% | +0.46% | -2.98% | -22.9% | +64.8% |
| 2 | 139 | 12.2% | +0.67% | -3.26% | -15.8% | +141.2% |
| 3 | 139 | 6.5% | -0.83% | -2.96% | -18.4% | +68.7% |
| 4 | 139 | 7.9% | -1.00% | -3.58% | -25.0% | +43.8% |
| 5 | 139 | 10.1% | +2.23% | -1.74% | -27.1% | +83.0% |
| 6 | 139 | 9.4% | +1.37% | -2.98% | -18.2% | +79.5% |
| 7 | 139 | 11.5% | +0.61% | -2.55% | -30.3% | +45.4% |
| 8 | 139 | 11.5% | +1.71% | -2.36% | -18.9% | +74.8% |
| 9 | 139 | 15.1% | +4.69% | -2.34% | -16.4% | +279.8% |
| 10 | 139 | 15.8% | +3.01% | -2.70% | -75.2% | +293.4% |

### Detailed Decile Statistics

Return distribution percentiles by predicted decile:

| Decile | N | Mean | Std | Min | P1 | P5 | P25 | P50 | P75 | P95 | P99 | Max |
|--------|---|------|-----|-----|----|----|-----|-----|-----|-----|-----|-----|
| 1 | 139 | +0.5 | 13.6 | -23 | -19 | -16 | -6 | -3 | +5 | +23 | +53 | +65 |
| 2 | 139 | +0.7 | 16.6 | -16 | -15 | -11 | -7 | -3 | +2 | +23 | +58 | +141 |
| 3 | 139 | -0.8 | 11.0 | -18 | -15 | -11 | -6 | -3 | +1 | +18 | +46 | +69 |
| 4 | 139 | -1.0 | 10.2 | -25 | -19 | -11 | -6 | -4 | +1 | +22 | +36 | +44 |
| 5 | 139 | +2.2 | 16.0 | -27 | -18 | -12 | -6 | -2 | +5 | +24 | +78 | +83 |
| 6 | 139 | +1.4 | 13.9 | -18 | -15 | -12 | -5 | -3 | +3 | +33 | +50 | +80 |
| 7 | 139 | +0.6 | 12.7 | -30 | -26 | -13 | -6 | -3 | +3 | +29 | +42 | +45 |
| 8 | 139 | +1.7 | 14.0 | -19 | -15 | -10 | -7 | -2 | +6 | +24 | +58 | +75 |
| 9 | 139 | +4.7 | 28.9 | -16 | -15 | -12 | -6 | -2 | +5 | +47 | +75 | +280 |
| 10 | 139 | +3.0 | 30.5 | -75 | -30 | -16 | -8 | -3 | +7 | +35 | +66 | +293 |

---

## Super Stock Classification

*Super Stock = Return > 50%*

**Market Base Rate:** 26 Super Stocks (1.87% of all trades)

### Precision & Recall

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Precision @ Top 10% | 3.60% | 5/139 top picks are Super Stocks |
| Recall @ Top 10% | 19.2% | 5/26 Super Stocks found in top decile |
| Lift @ Top 10% | 1.9x | vs random (1.87% base rate) |

### Percentile Lift (Granular Selection)

| Percentile | N | Super Stocks | Precision | Lift |
|------------|---|--------------|-----------|------|
| Top 1% | 14 | 1 | 7.1% | 3.8x |
| Top 2% | 28 | 2 | 7.1% | 3.8x |
| Top 5% | 70 | 2 | 2.9% | 1.5x |
| Top 10% | 139 | 5 | 3.6% | 1.9x |
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