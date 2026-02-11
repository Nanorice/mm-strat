# Model Training Report - M01 (SEPA Signal Quality Model)

**Generated:** 2026-02-09 17:41:05
**Training Period:** 2018-01-01 to 2025-12-31
**Model Type:** REGRESSION
**Target:** return_pct

---

## Executive Summary

**Trading Viability:** VIABLE

### Key Metrics

- **Selection Edge:** +1.88% (range: [-1.37%, +5.16%])
- **Edge Consistency:** 3/5 folds positive (60%)
- **Edge Sharpe Ratio:** 0.61
- **Top Decile Return:** 2.68%
- **RMSE:** 18.27%
- **Walk-Forward Folds:** 5
- **Total Test Samples:** 7,231

---

## Walk-Forward Validation Results

| Fold | Test Year | Test Samples | RMSE | Selection Edge | Top Decile Mean |
|------|-----------|--------------|------|----------------|-----------------|
| 1 | 2021.0 | 2,026.0 | 19.91% | +5.14% | 6.62% |
| 2 | 2022.0 | 598.0 | 12.72% | -1.37% | -4.34% |
| 3 | 2023.0 | 1,390.0 | 18.14% | +0.79% | 2.09% |
| 4 | 2024.0 | 1,969.0 | 17.59% | -0.34% | 1.52% |
| 5 | 2025.0 | 1,248.0 | 23.00% | +5.16% | 7.53% |

---

## Feature Importance Analysis

**Total Features:** 72

### Top 20 Features by Gain

| Rank | Feature | Gain | % Total | Cumulative % |
|------|---------|------|---------|--------------|
| 1 | alpha041 | 0 | 4.0% | 4.0% |
| 2 | roe | 0 | 3.5% | 7.5% |
| 3 | operating_margin | 0 | 3.3% | 10.8% |
| 4 | log_price_momentum_curve | 0 | 3.1% | 13.9% |
| 5 | alpha054 | 0 | 3.0% | 16.8% |
| 6 | pe_ratio | 0 | 2.8% | 19.6% |
| 7 | RS_Universe_Rank | 0 | 2.8% | 22.4% |
| 8 | roa | 0 | 2.7% | 25.1% |
| 9 | current_ratio | 0 | 2.7% | 27.8% |
| 10 | log_pb_ratio | 0 | 2.7% | 30.4% |
| 11 | alpha046 | 0 | 2.6% | 33.0% |
| 12 | Price_vs_SMA_150_Delta | 0 | 2.6% | 35.6% |
| 13 | gross_margin | 0 | 2.4% | 38.0% |
| 14 | log_debt_to_equity | 0 | 2.3% | 40.2% |
| 15 | industry_id | 0 | 2.2% | 42.4% |
| 16 | m03_score | 0 | 2.1% | 44.6% |
| 17 | net_income_growth_yoy | 0 | 2.1% | 46.7% |
| 18 | log_revenue_accel | 0 | 2.1% | 48.8% |
| 19 | log_alpha001 | 0 | 2.0% | 50.8% |
| 20 | m03_delta_5d | 0 | 1.8% | 52.5% |

---

## Regime-Conditional Performance

Performance bucketed by M03 market regime at entry time.

### Top Decile Performance by Regime

| Regime | N Trades | Win Rate | Mean Return | Median Return |
|--------|----------|----------|-------------|---------------|
| Strong Bear | 34 | 11.8% | -3.52% | -5.54% |
| Bear | 87 | 17.2% | +4.69% | -2.65% |
| Neutral | 201 | 23.9% | +6.87% | -2.44% |
| Bull | 191 | 13.6% | +2.47% | -4.91% |
| Strong Bull | 210 | 14.8% | +0.09% | -3.98% |

---

## Decile Performance Analysis

### Win Rate and Return by Predicted Decile

| Decile | N Trades | Win Rate | Mean Return | Median | Min | Max |
|--------|----------|----------|-------------|--------|-----|-----|
| 1 | 724 | 12.6% | +1.14% | -3.37% | -26.1% | +334.3% |
| 2 | 723 | 10.8% | +1.58% | -2.08% | -28.0% | +273.6% |
| 3 | 723 | 12.0% | +1.97% | -2.23% | -30.3% | +151.5% |
| 4 | 723 | 10.9% | +1.76% | -2.48% | -25.0% | +229.1% |
| 5 | 723 | 8.9% | +0.45% | -2.38% | -18.8% | +75.3% |
| 6 | 723 | 11.8% | +1.15% | -3.07% | -34.2% | +121.5% |
| 7 | 723 | 11.1% | +0.83% | -2.71% | -36.0% | +133.7% |
| 8 | 723 | 10.5% | +1.17% | -3.42% | -30.3% | +302.2% |
| 9 | 723 | 12.3% | +0.27% | -3.57% | -32.0% | +201.7% |
| 10 | 723 | 17.2% | +2.99% | -3.79% | -75.2% | +516.6% |

### Detailed Decile Statistics

Return distribution percentiles by predicted decile:

| Decile | N | Mean | Std | Min | P1 | P5 | P25 | P50 | P75 | P95 | P99 | Max |
|--------|---|------|-----|-----|----|----|-----|-----|-----|-----|-----|-----|
| 1 | 724 | +1.1 | 20.4 | -26 | -20 | -15 | -7 | -3 | +3 | +31 | +66 | +334 |
| 2 | 723 | +1.6 | 17.4 | -28 | -19 | -13 | -6 | -2 | +5 | +24 | +53 | +274 |
| 3 | 723 | +2.0 | 16.7 | -30 | -18 | -12 | -6 | -2 | +5 | +29 | +64 | +151 |
| 4 | 723 | +1.8 | 17.6 | -25 | -17 | -12 | -6 | -2 | +4 | +27 | +61 | +229 |
| 5 | 723 | +0.4 | 11.5 | -19 | -16 | -12 | -6 | -2 | +4 | +23 | +41 | +75 |
| 6 | 723 | +1.1 | 15.1 | -34 | -19 | -13 | -7 | -3 | +4 | +31 | +61 | +121 |
| 7 | 723 | +0.8 | 14.7 | -36 | -20 | -14 | -7 | -3 | +5 | +28 | +57 | +134 |
| 8 | 723 | +1.2 | 21.7 | -30 | -20 | -14 | -7 | -3 | +4 | +28 | +64 | +302 |
| 9 | 723 | +0.3 | 16.5 | -32 | -21 | -16 | -9 | -4 | +4 | +28 | +54 | +202 |
| 10 | 723 | +3.0 | 31.0 | -75 | -26 | -18 | -10 | -4 | +8 | +46 | +103 | +517 |

---

## Super Stock Classification

*Super Stock = Return > 50%*

**Market Base Rate:** 133 Super Stocks (1.84% of all trades)

### Precision & Recall

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Precision @ Top 10% | 3.87% | 28/723 top picks are Super Stocks |
| Recall @ Top 10% | 21.1% | 28/133 Super Stocks found in top decile |
| Lift @ Top 10% | 2.1x | vs random (1.84% base rate) |

### Percentile Lift (Granular Selection)

| Percentile | N | Super Stocks | Precision | Lift |
|------------|---|--------------|-----------|------|
| Top 1% | 73 | 4 | 5.5% | 3.0x |
| Top 2% | 145 | 8 | 5.5% | 3.0x |
| Top 5% | 362 | 17 | 4.7% | 2.6x |
| Top 10% | 724 | 28 | 3.9% | 2.1x |
| Top 20% | 1447 | 37 | 2.6% | 1.4x |

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