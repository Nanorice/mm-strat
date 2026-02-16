# Model Training Report - M01 (SEPA Signal Quality Model)

**Generated:** 2026-02-14 17:31:19
**Training Period:** 2020-01-01 to 2023-12-31
**Model Type:** REGRESSION
**Target:** target

---

## Executive Summary

**Trading Viability:** MARGINAL

### Key Metrics

- **Selection Edge:** +1.14% (range: [+1.14%, +1.14%])
- **Edge Consistency:** 1/1 folds positive (100%)
- **Edge Sharpe Ratio:** 0.00
- **Top Decile Return:** 4.81%
- **RMSE:** 4.52%
- **Walk-Forward Folds:** 1
- **Total Test Samples:** 1,553

---

## Walk-Forward Validation Results

| Fold | Test Year | Test Samples | RMSE | Selection Edge | Top Decile Mean |
|------|-----------|--------------|------|----------------|-----------------|
| 1 | 2023.0 | 1,553.0 | 4.52% | +1.14% | 4.81% |

---

## Feature Importance Analysis

**Total Features:** 72

### Top 20 Features by Gain

| Rank | Feature | Gain | % Total | Cumulative % |
|------|---------|------|---------|--------------|
| 1 | m03_pillar_risk | 0 | 2.7% | 2.7% |
| 2 | industry_id | 0 | 2.7% | 5.3% |
| 3 | alpha011 | 0 | 2.6% | 7.9% |
| 4 | log_Price_vs_SMA_50_Lag1 | 0 | 2.5% | 10.4% |
| 5 | log_Price_vs_SMA_200 | 0 | 2.5% | 12.9% |
| 6 | log_Price_vs_SMA_50 | 0 | 2.3% | 15.2% |
| 7 | m03_pillar_trend | 0 | 2.3% | 17.6% |
| 8 | Dist_From_20D_High_Delta | 0 | 1.8% | 19.4% |
| 9 | VCP_Ratio | 0 | 1.8% | 21.1% |
| 10 | m03_score | 0 | 1.8% | 22.9% |
| 11 | log_fcf_margin | 0 | 1.8% | 24.6% |
| 12 | alpha054 | 0 | 1.7% | 26.3% |
| 13 | log_Dry_Up_Volume_Lag1 | 0 | 1.6% | 28.0% |
| 14 | alpha015 | 0 | 1.6% | 29.5% |
| 15 | log_revenue_cagr_3y | 0 | 1.6% | 31.1% |
| 16 | RSI_14 | 0 | 1.6% | 32.7% |
| 17 | log_volume_velocity | 0 | 1.5% | 34.3% |
| 18 | alpha013 | 0 | 1.5% | 35.8% |
| 19 | sector_id | 0 | 1.5% | 37.3% |
| 20 | roa | 0 | 1.5% | 38.8% |

---

## Regime-Conditional Performance

Performance bucketed by M03 market regime at entry time.

### Top Decile Performance by Regime

| Regime | N Trades | Win Rate | Mean Return | Median Return |
|--------|----------|----------|-------------|---------------|
| Bear | 12 | 16.7% | +24.69% | -1.48% |
| Neutral | 33 | 21.2% | +3.80% | -2.91% |
| Bull | 68 | 11.8% | -0.93% | -4.99% |
| Strong Bull | 43 | 11.6% | +0.22% | -3.85% |

---

## Decile Performance Analysis

### Win Rate and Return by Predicted Decile

| Decile | N Trades | Win Rate | Mean Return | Median | Min | Max |
|--------|----------|----------|-------------|--------|-----|-----|
| 1 | 156 | 3.8% | -0.65% | -2.34% | -22.9% | +50.6% |
| 2 | 155 | 5.8% | -0.95% | -1.99% | -16.9% | +27.4% |
| 3 | 155 | 6.5% | +0.76% | -2.10% | -18.1% | +79.5% |
| 4 | 155 | 10.3% | +1.23% | -1.30% | -19.5% | +55.4% |
| 5 | 156 | 13.5% | +3.76% | -1.88% | -18.1% | +115.9% |
| 6 | 155 | 9.7% | +0.95% | -3.00% | -19.9% | +141.2% |
| 7 | 155 | 13.5% | +1.50% | -2.11% | -75.2% | +73.5% |
| 8 | 155 | 8.4% | +0.28% | -2.02% | -25.0% | +113.9% |
| 9 | 155 | 7.1% | +1.33% | -2.71% | -23.1% | +293.4% |
| 10 | 156 | 14.1% | +2.36% | -3.91% | -42.6% | +279.8% |

### Detailed Decile Statistics

Return distribution percentiles by predicted decile:

| Decile | N | Mean | Std | Min | P1 | P5 | P25 | P50 | P75 | P95 | P99 | Max |
|--------|---|------|-----|-----|----|----|-----|-----|-----|-----|-----|-----|
| 1 | 156 | -0.7 | 8.8 | -23 | -17 | -9 | -5 | -2 | +0 | +14 | +37 | +51 |
| 2 | 155 | -1.0 | 7.8 | -17 | -15 | -11 | -5 | -2 | +1 | +16 | +24 | +27 |
| 3 | 155 | +0.8 | 12.9 | -18 | -14 | -11 | -5 | -2 | +2 | +21 | +61 | +80 |
| 4 | 155 | +1.2 | 11.9 | -19 | -15 | -10 | -5 | -1 | +3 | +29 | +44 | +55 |
| 5 | 156 | +3.8 | 18.9 | -18 | -17 | -10 | -5 | -2 | +2 | +40 | +77 | +116 |
| 6 | 155 | +1.0 | 16.7 | -20 | -17 | -11 | -5 | -3 | +1 | +30 | +54 | +141 |
| 7 | 155 | +1.5 | 15.3 | -75 | -16 | -12 | -6 | -2 | +6 | +23 | +63 | +73 |
| 8 | 155 | +0.3 | 13.6 | -25 | -18 | -12 | -6 | -2 | +2 | +20 | +39 | +114 |
| 9 | 155 | +1.3 | 25.9 | -23 | -17 | -12 | -6 | -3 | +3 | +23 | +47 | +293 |
| 10 | 156 | +2.4 | 29.2 | -43 | -31 | -17 | -10 | -4 | +4 | +43 | +70 | +280 |

### Survivor Rate by Decile

| Decile | N | Survivor Rate | Crash Rate | Avg MFE | Avg MAE |
|--------|---|---------------|------------|---------|---------|
| 1 | 156 | 57.7% | 42.3% | +6.4% | -5.3% |
| 2 | 155 | 58.1% | 41.9% | +7.6% | -5.6% |
| 3 | 155 | 53.5% | 46.5% | +10.3% | -5.8% |
| 4 | 155 | 53.5% | 46.5% | +10.6% | -5.9% |
| 5 | 156 | 44.2% | 55.8% | +14.8% | -6.3% |
| 6 | 155 | 43.2% | 56.8% | +12.7% | -6.8% |
| 7 | 155 | 46.5% | 53.5% | +14.5% | -7.2% |
| 8 | 155 | 52.3% | 47.7% | +11.9% | -7.0% |
| 9 | 155 | 45.2% | 54.8% | +14.6% | -7.9% |
| 10 | 156 | 41.7% | 58.3% | +19.7% | -9.4% |

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
| Top 2% | 32 | 1 | 3.1% | 1.8x |
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