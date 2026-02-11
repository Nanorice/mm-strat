# Model Training Report - M01 (SEPA Signal Quality Model)

**Generated:** 2026-02-09 17:47:13
**Training Period:** 2018-01-01 to 2025-12-31
**Model Type:** REGRESSION
**Target:** return_pct

---

## Executive Summary

**Trading Viability:** VIABLE

### Key Metrics

- **Selection Edge:** +3.19% (range: [+0.04%, +7.29%])
- **Edge Consistency:** 5/5 folds positive (100%)
- **Edge Sharpe Ratio:** 1.20
- **Top Decile Return:** 3.99%
- **RMSE:** 18.04%
- **Walk-Forward Folds:** 5
- **Total Test Samples:** 7,231

---

## Walk-Forward Validation Results

| Fold | Test Year | Test Samples | RMSE | Selection Edge | Top Decile Mean |
|------|-----------|--------------|------|----------------|-----------------|
| 1 | 2021.0 | 2,026.0 | 20.07% | +3.67% | 5.15% |
| 2 | 2022.0 | 598.0 | 11.89% | +0.04% | -2.94% |
| 3 | 2023.0 | 1,390.0 | 18.05% | +2.12% | 3.41% |
| 4 | 2024.0 | 1,969.0 | 17.44% | +2.82% | 4.68% |
| 5 | 2025.0 | 1,248.0 | 22.75% | +7.29% | 9.65% |

---

## Feature Importance Analysis

**Total Features:** 57

### Top 20 Features by Gain

| Rank | Feature | Gain | % Total | Cumulative % |
|------|---------|------|---------|--------------|
| 1 | VCP_Ratio | 0 | 4.2% | 4.2% |
| 2 | alpha002 | 0 | 4.1% | 8.2% |
| 3 | log_revenue_accel | 0 | 3.3% | 11.5% |
| 4 | log_RS_Delta | 0 | 3.1% | 14.6% |
| 5 | alpha011 | 0 | 2.8% | 17.4% |
| 6 | log_volume_acceleration | 0 | 2.8% | 20.2% |
| 7 | log_alpha001 | 0 | 2.7% | 23.0% |
| 8 | earnings_quality_score | 0 | 2.6% | 25.6% |
| 9 | Price_vs_SMA_150_Delta | 0 | 2.6% | 28.1% |
| 10 | gross_margin | 0 | 2.5% | 30.7% |
| 11 | eps_stability_score | 0 | 2.5% | 33.2% |
| 12 | log_pb_ratio | 0 | 2.5% | 35.6% |
| 13 | ps_ratio | 0 | 2.4% | 38.0% |
| 14 | days_since_report | 0 | 2.4% | 40.5% |
| 15 | alpha013 | 0 | 2.3% | 42.7% |
| 16 | Dist_From_20D_High_Delta | 0 | 2.3% | 45.0% |
| 17 | SMA_50_Slope | 0 | 2.3% | 47.3% |
| 18 | roe | 0 | 2.3% | 49.6% |
| 19 | alpha009 | 0 | 2.2% | 51.8% |
| 20 | log_current_ratio | 0 | 2.2% | 54.0% |

---

## Regime-Conditional Performance

Performance bucketed by M03 market regime at entry time.

### Top Decile Performance by Regime

| Regime | N Trades | Win Rate | Mean Return | Median Return |
|--------|----------|----------|-------------|---------------|
| Strong Bear | 7 | 28.6% | -0.84% | -7.65% |
| Bear | 22 | 13.6% | -3.12% | -8.92% |
| Neutral | 190 | 26.3% | +8.25% | -0.65% |
| Bull | 225 | 12.4% | +1.69% | -5.59% |
| Strong Bull | 279 | 13.6% | +0.45% | -4.14% |

---

## Decile Performance Analysis

### Win Rate and Return by Predicted Decile

| Decile | N Trades | Win Rate | Mean Return | Median | Min | Max |
|--------|----------|----------|-------------|--------|-----|-----|
| 1 | 724 | 8.0% | -1.51% | -4.12% | -27.4% | +135.3% |
| 2 | 724 | 6.6% | -0.82% | -2.75% | -30.3% | +79.3% |
| 3 | 722 | 9.4% | +0.45% | -2.58% | -31.0% | +133.7% |
| 4 | 723 | 10.8% | +1.46% | -1.42% | -34.2% | +68.7% |
| 5 | 723 | 11.2% | +1.13% | -2.53% | -27.1% | +183.8% |
| 6 | 723 | 11.5% | +1.18% | -2.41% | -27.6% | +143.0% |
| 7 | 723 | 14.1% | +3.13% | -2.39% | -32.0% | +302.2% |
| 8 | 723 | 14.7% | +2.94% | -3.02% | -25.4% | +273.6% |
| 9 | 723 | 14.9% | +2.59% | -3.70% | -32.6% | +334.3% |
| 10 | 723 | 16.7% | +2.76% | -4.08% | -75.2% | +516.6% |

### Detailed Decile Statistics

Return distribution percentiles by predicted decile:

| Decile | N | Mean | Std | Min | P1 | P5 | P25 | P50 | P75 | P95 | P99 | Max |
|--------|---|------|-----|-----|----|----|-----|-----|-----|-----|-----|-----|
| 1 | 724 | -1.5 | 13.9 | -27 | -19 | -16 | -8 | -4 | +0 | +23 | +56 | +135 |
| 2 | 724 | -0.8 | 10.4 | -30 | -20 | -13 | -6 | -3 | +2 | +18 | +35 | +79 |
| 3 | 722 | +0.4 | 13.5 | -31 | -17 | -12 | -6 | -3 | +2 | +22 | +45 | +134 |
| 4 | 723 | +1.5 | 12.0 | -34 | -19 | -12 | -5 | -1 | +5 | +26 | +46 | +69 |
| 5 | 723 | +1.1 | 14.4 | -27 | -18 | -12 | -6 | -3 | +4 | +26 | +54 | +184 |
| 6 | 723 | +1.2 | 14.2 | -28 | -19 | -13 | -6 | -2 | +5 | +26 | +48 | +143 |
| 7 | 723 | +3.1 | 21.8 | -32 | -21 | -13 | -6 | -2 | +5 | +36 | +78 | +302 |
| 8 | 723 | +2.9 | 22.4 | -25 | -19 | -14 | -8 | -3 | +5 | +40 | +74 | +274 |
| 9 | 723 | +2.6 | 26.4 | -33 | -22 | -16 | -9 | -4 | +7 | +36 | +81 | +334 |
| 10 | 723 | +2.8 | 29.3 | -75 | -22 | -18 | -11 | -4 | +8 | +43 | +85 | +517 |

---

## Super Stock Classification

*Super Stock = Return > 50%*

**Market Base Rate:** 133 Super Stocks (1.84% of all trades)

### Precision & Recall

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Precision @ Top 10% | 3.60% | 26/723 top picks are Super Stocks |
| Recall @ Top 10% | 19.5% | 26/133 Super Stocks found in top decile |
| Lift @ Top 10% | 2.0x | vs random (1.84% base rate) |

### Percentile Lift (Granular Selection)

| Percentile | N | Super Stocks | Precision | Lift |
|------------|---|--------------|-----------|------|
| Top 1% | 73 | 2 | 2.7% | 1.5x |
| Top 2% | 145 | 7 | 4.8% | 2.6x |
| Top 5% | 362 | 13 | 3.6% | 2.0x |
| Top 10% | 724 | 26 | 3.6% | 2.0x |
| Top 20% | 1447 | 48 | 3.3% | 1.8x |

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