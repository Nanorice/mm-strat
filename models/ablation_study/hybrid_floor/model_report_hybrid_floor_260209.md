# Model Training Report - M01 (SEPA Signal Quality Model)

**Generated:** 2026-02-09 18:15:59
**Training Period:** 2020-01-01 to 2023-12-31
**Model Type:** REGRESSION
**Target:** target

---

## Executive Summary

**Trading Viability:** VIABLE

### Key Metrics

- **Selection Edge:** +5.95% (range: [+5.95%, +5.95%])
- **Edge Consistency:** 1/1 folds positive (100%)
- **Edge Sharpe Ratio:** 0.00
- **Top Decile Return:** 11.33%
- **RMSE:** 22.80%
- **Walk-Forward Folds:** 1
- **Total Test Samples:** 1,390

---

## Walk-Forward Validation Results

| Fold | Test Year | Test Samples | RMSE | Selection Edge | Top Decile Mean |
|------|-----------|--------------|------|----------------|-----------------|
| 1 | 2023.0 | 1,390.0 | 22.80% | +5.95% | 11.33% |

---

## Feature Importance Analysis

**Total Features:** 72

### Top 20 Features by Gain

| Rank | Feature | Gain | % Total | Cumulative % |
|------|---------|------|---------|--------------|
| 1 | log_Price_vs_SMA_50_Lag1 | 0 | 3.4% | 3.4% |
| 2 | log_debt_to_equity | 0 | 3.4% | 6.7% |
| 3 | m03_delta_20d | 0 | 3.4% | 10.1% |
| 4 | log_pb_ratio | 0 | 3.2% | 13.3% |
| 5 | turnover_ma20 | 0 | 3.0% | 16.2% |
| 6 | operating_margin | 0 | 2.4% | 18.6% |
| 7 | log_Price_vs_SMA_200_Delta | 0 | 2.0% | 20.6% |
| 8 | industry_id | 0 | 2.0% | 22.6% |
| 9 | alpha011 | 0 | 2.0% | 24.7% |
| 10 | roe | 0 | 1.9% | 26.6% |
| 11 | m03_pillar_risk | 0 | 1.9% | 28.5% |
| 12 | log_Price_vs_SMA_50 | 0 | 1.8% | 30.3% |
| 13 | Dist_From_20D_High_Delta | 0 | 1.8% | 32.1% |
| 14 | alpha041 | 0 | 1.7% | 33.8% |
| 15 | net_income_growth_yoy | 0 | 1.7% | 35.5% |
| 16 | log_alpha001 | 0 | 1.6% | 37.2% |
| 17 | log_alpha009 | 0 | 1.6% | 38.8% |
| 18 | log_volume_velocity | 0 | 1.6% | 40.4% |
| 19 | alpha101 | 0 | 1.6% | 42.0% |
| 20 | m03_pillar_trend | 0 | 1.6% | 43.6% |

---

## Regime-Conditional Performance

Performance bucketed by M03 market regime at entry time.

### Top Decile Performance by Regime

| Regime | N Trades | Win Rate | Mean Return | Median Return |
|--------|----------|----------|-------------|---------------|
| Bear | 14 | 28.6% | +26.92% | +2.21% |
| Neutral | 38 | 13.2% | +0.11% | -2.64% |
| Bull | 55 | 9.1% | -1.28% | -4.49% |
| Strong Bull | 32 | 15.6% | +0.19% | -0.72% |

---

## Decile Performance Analysis

### Win Rate and Return by Predicted Decile

| Decile | N Trades | Win Rate | Mean Return | Median | Min | Max |
|--------|----------|----------|-------------|--------|-----|-----|
| 1 | 139 | 9.4% | +1.18% | -2.11% | -18.4% | +64.8% |
| 2 | 139 | 7.2% | -0.15% | -2.80% | -27.1% | +73.5% |
| 3 | 139 | 10.1% | +2.74% | -2.28% | -19.9% | +293.4% |
| 4 | 139 | 10.8% | +1.22% | -2.02% | -18.8% | +75.0% |
| 5 | 139 | 5.0% | -1.05% | -3.12% | -75.2% | +64.1% |
| 6 | 139 | 10.1% | +0.38% | -3.36% | -15.0% | +66.0% |
| 7 | 139 | 13.7% | +1.74% | -3.33% | -27.5% | +141.2% |
| 8 | 139 | 14.4% | +3.63% | -1.14% | -16.0% | +83.0% |
| 9 | 139 | 14.4% | +0.95% | -4.12% | -30.3% | +66.7% |
| 10 | 139 | 13.7% | +2.28% | -2.98% | -32.6% | +279.8% |

### Detailed Decile Statistics

Return distribution percentiles by predicted decile:

| Decile | N | Mean | Std | Min | P1 | P5 | P25 | P50 | P75 | P95 | P99 | Max |
|--------|---|------|-----|-----|----|----|-----|-----|-----|-----|-----|-----|
| 1 | 139 | +1.2 | 13.8 | -18 | -17 | -12 | -6 | -2 | +2 | +33 | +59 | +65 |
| 2 | 139 | -0.2 | 12.5 | -27 | -21 | -13 | -7 | -3 | +4 | +21 | +49 | +73 |
| 3 | 139 | +2.7 | 27.1 | -20 | -16 | -10 | -6 | -2 | +5 | +20 | +57 | +293 |
| 4 | 139 | +1.2 | 12.8 | -19 | -15 | -11 | -5 | -2 | +4 | +23 | +51 | +75 |
| 5 | 139 | -1.1 | 13.0 | -75 | -18 | -12 | -6 | -3 | +1 | +15 | +48 | +64 |
| 6 | 139 | +0.4 | 12.2 | -15 | -15 | -11 | -6 | -3 | +2 | +22 | +54 | +66 |
| 7 | 139 | +1.7 | 18.6 | -28 | -18 | -13 | -7 | -3 | +6 | +28 | +76 | +141 |
| 8 | 139 | +3.6 | 16.7 | -16 | -15 | -12 | -5 | -1 | +9 | +27 | +78 | +83 |
| 9 | 139 | +1.0 | 16.5 | -30 | -24 | -15 | -8 | -4 | +4 | +38 | +57 | +67 |
| 10 | 139 | +2.3 | 28.4 | -33 | -24 | -16 | -9 | -3 | +4 | +35 | +71 | +280 |

### Survivor Rate by Decile

| Decile | N | Survivor Rate | Crash Rate | Avg MFE | Avg MAE |
|--------|---|---------------|------------|---------|---------|
| 1 | 139 | 29.5% | 70.5% | +12.3% | -7.8% |
| 2 | 139 | 32.4% | 67.6% | +11.6% | -7.0% |
| 3 | 139 | 41.7% | 58.3% | +14.2% | -6.7% |
| 4 | 139 | 48.9% | 51.1% | +12.1% | -5.9% |
| 5 | 139 | 46.0% | 54.0% | +10.5% | -6.6% |
| 6 | 139 | 48.9% | 51.1% | +11.9% | -6.2% |
| 7 | 139 | 43.2% | 56.8% | +14.2% | -7.0% |
| 8 | 139 | 52.5% | 47.5% | +16.9% | -6.6% |
| 9 | 139 | 47.5% | 52.5% | +15.7% | -8.0% |
| 10 | 139 | 52.5% | 47.5% | +18.9% | -9.0% |

---

## Super Stock Classification

*Super Stock = Return > 50%*

**Market Base Rate:** 26 Super Stocks (1.87% of all trades)

### Precision & Recall

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Precision @ Top 10% | 2.88% | 4/139 top picks are Super Stocks |
| Recall @ Top 10% | 15.4% | 4/26 Super Stocks found in top decile |
| Lift @ Top 10% | 1.5x | vs random (1.87% base rate) |

### Percentile Lift (Granular Selection)

| Percentile | N | Super Stocks | Precision | Lift |
|------------|---|--------------|-----------|------|
| Top 1% | 14 | 0 | 0.0% | 0.0x |
| Top 2% | 28 | 2 | 7.1% | 3.8x |
| Top 5% | 70 | 2 | 2.9% | 1.5x |
| Top 10% | 139 | 4 | 2.9% | 1.5x |
| Top 20% | 278 | 6 | 2.2% | 1.2x |

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