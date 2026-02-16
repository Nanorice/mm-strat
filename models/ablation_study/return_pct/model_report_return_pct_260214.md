# Model Training Report - M01 (SEPA Signal Quality Model)

**Generated:** 2026-02-14 17:30:52
**Training Period:** 2020-01-01 to 2023-12-31
**Model Type:** REGRESSION
**Target:** target

---

## Executive Summary

**Trading Viability:** VIABLE

### Key Metrics

- **Selection Edge:** +1.64% (range: [+1.64%, +1.64%])
- **Edge Consistency:** 1/1 folds positive (100%)
- **Edge Sharpe Ratio:** 0.00
- **Top Decile Return:** 2.70%
- **RMSE:** 18.21%
- **Walk-Forward Folds:** 1
- **Total Test Samples:** 1,553

---

## Walk-Forward Validation Results

| Fold | Test Year | Test Samples | RMSE | Selection Edge | Top Decile Mean |
|------|-----------|--------------|------|----------------|-----------------|
| 1 | 2023.0 | 1,553.0 | 18.21% | +1.64% | 2.70% |

---

## Feature Importance Analysis

**Total Features:** 72

### Top 20 Features by Gain

| Rank | Feature | Gain | % Total | Cumulative % |
|------|---------|------|---------|--------------|
| 1 | alpha046 | 0 | 4.7% | 4.7% |
| 2 | earnings_quality_score | 0 | 4.6% | 9.4% |
| 3 | alpha041 | 0 | 2.8% | 12.2% |
| 4 | turnover_ma20 | 0 | 2.8% | 14.9% |
| 5 | log_alpha001 | 0 | 2.7% | 17.7% |
| 6 | log_RS | 0 | 2.6% | 20.3% |
| 7 | m03_delta_20d | 0 | 2.3% | 22.6% |
| 8 | log_Price_vs_SMA_50 | 0 | 2.2% | 24.8% |
| 9 | log_pb_ratio | 0 | 2.2% | 27.0% |
| 10 | eps_stability_score | 0 | 2.1% | 29.1% |
| 11 | Price_vs_SMA_150_Delta | 0 | 2.0% | 31.1% |
| 12 | log_volume_acceleration | 0 | 2.0% | 33.1% |
| 13 | log_vol_ma20 | 0 | 2.0% | 35.0% |
| 14 | alpha012 | 0 | 1.9% | 36.9% |
| 15 | m03_regime_vol | 0 | 1.8% | 38.7% |
| 16 | m03_pillar_risk | 0 | 1.7% | 40.4% |
| 17 | ps_ratio | 0 | 1.7% | 42.2% |
| 18 | sector_id | 0 | 1.7% | 43.9% |
| 19 | industry_id | 0 | 1.7% | 45.6% |
| 20 | m03_pillar_liq | 0 | 1.7% | 47.2% |

---

## Regime-Conditional Performance

Performance bucketed by M03 market regime at entry time.

### Top Decile Performance by Regime

| Regime | N Trades | Win Rate | Mean Return | Median Return |
|--------|----------|----------|-------------|---------------|
| Bear | 15 | 13.3% | -2.52% | -0.18% |
| Neutral | 32 | 18.8% | +9.69% | -2.30% |
| Bull | 61 | 13.1% | +0.86% | -3.20% |
| Strong Bull | 48 | 16.7% | +2.01% | -1.56% |

---

## Decile Performance Analysis

### Win Rate and Return by Predicted Decile

| Decile | N Trades | Win Rate | Mean Return | Median | Min | Max |
|--------|----------|----------|-------------|--------|-----|-----|
| 1 | 156 | 10.3% | +1.51% | -1.85% | -18.1% | +141.2% |
| 2 | 155 | 3.2% | -2.20% | -3.52% | -23.1% | +63.8% |
| 3 | 155 | 10.3% | +1.61% | -2.32% | -18.2% | +115.9% |
| 4 | 155 | 7.7% | +0.86% | -2.23% | -19.5% | +80.5% |
| 5 | 156 | 7.1% | +1.03% | -2.25% | -25.0% | +74.7% |
| 6 | 155 | 6.5% | +0.22% | -2.16% | -27.5% | +74.8% |
| 7 | 155 | 14.2% | +2.31% | -1.56% | -13.4% | +56.9% |
| 8 | 155 | 9.0% | +0.60% | -2.26% | -42.6% | +66.0% |
| 9 | 155 | 9.0% | +1.90% | -2.54% | -20.2% | +279.8% |
| 10 | 156 | 15.4% | +2.70% | -2.24% | -75.2% | +293.4% |

### Detailed Decile Statistics

Return distribution percentiles by predicted decile:

| Decile | N | Mean | Std | Min | P1 | P5 | P25 | P50 | P75 | P95 | P99 | Max |
|--------|---|------|-----|-----|----|----|-----|-----|-----|-----|-----|-----|
| 1 | 156 | +1.5 | 16.0 | -18 | -18 | -12 | -6 | -2 | +4 | +23 | +53 | +141 |
| 2 | 155 | -2.2 | 9.3 | -23 | -21 | -13 | -7 | -4 | +0 | +13 | +27 | +64 |
| 3 | 155 | +1.6 | 17.5 | -18 | -16 | -12 | -5 | -2 | +2 | +32 | +82 | +116 |
| 4 | 155 | +0.9 | 14.1 | -19 | -14 | -10 | -5 | -2 | +1 | +27 | +74 | +81 |
| 5 | 156 | +1.0 | 14.1 | -25 | -15 | -9 | -6 | -2 | +2 | +23 | +73 | +75 |
| 6 | 155 | +0.2 | 11.7 | -28 | -15 | -9 | -5 | -2 | +1 | +19 | +47 | +75 |
| 7 | 155 | +2.3 | 13.0 | -13 | -12 | -11 | -5 | -2 | +4 | +29 | +50 | +57 |
| 8 | 155 | +0.6 | 13.4 | -43 | -22 | -12 | -6 | -2 | +4 | +29 | +51 | +66 |
| 9 | 155 | +1.9 | 25.2 | -20 | -16 | -11 | -6 | -3 | +2 | +24 | +52 | +280 |
| 10 | 156 | +2.7 | 29.3 | -75 | -29 | -17 | -9 | -2 | +7 | +34 | +70 | +293 |

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
| Top 5% | 78 | 3 | 3.8% | 2.2x |
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