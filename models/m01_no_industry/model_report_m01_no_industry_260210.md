# Model Training Report - M01 (SEPA Signal Quality Model)

**Generated:** 2026-02-10 01:03:28
**Training Period:** 2018-01-01 to 2025-12-31
**Model Type:** REGRESSION
**Target:** target

---

## Executive Summary

**Trading Viability:** NOT VIABLE

### Key Metrics

- **Selection Edge:** +0.17% (range: [-0.07%, +0.28%])
- **Edge Consistency:** 4/5 folds positive (80%)
- **Edge Sharpe Ratio:** 1.19
- **Top Decile Return:** 1.47%
- **RMSE:** 2.08%
- **Walk-Forward Folds:** 5
- **Total Test Samples:** 7,231

---

## Walk-Forward Validation Results

| Fold | Test Year | Test Samples | RMSE | Selection Edge | Top Decile Mean |
|------|-----------|--------------|------|----------------|-----------------|
| 1 | 2021.0 | 2,026.0 | 1.97% | +0.15% | 1.70% |
| 2 | 2022.0 | 598.0 | 2.20% | +0.28% | 1.21% |
| 3 | 2023.0 | 1,390.0 | 1.97% | -0.07% | 1.33% |
| 4 | 2024.0 | 1,969.0 | 1.99% | +0.27% | 1.70% |
| 5 | 2025.0 | 1,248.0 | 2.26% | +0.22% | 1.43% |

---

## Feature Importance Analysis

**Total Features:** 71

### Top 20 Features by Gain

| Rank | Feature | Gain | % Total | Cumulative % |
|------|---------|------|---------|--------------|
| 1 | alpha011 | 0 | 2.5% | 2.5% |
| 2 | log_Price_vs_SMA_50_Lag1 | 0 | 1.8% | 4.3% |
| 3 | net_income_growth_yoy | 0 | 1.8% | 6.1% |
| 4 | m03_pillar_liq | 0 | 1.8% | 7.8% |
| 5 | m03_delta_5d | 0 | 1.8% | 9.6% |
| 6 | m03_pillar_risk | 0 | 1.8% | 11.4% |
| 7 | log_revenue_growth_yoy | 0 | 1.8% | 13.1% |
| 8 | log_gross_margin_trend | 0 | 1.7% | 14.9% |
| 9 | log_mom_63d | 0 | 1.7% | 16.6% |
| 10 | inventory_vs_sales_spread | 0 | 1.7% | 18.2% |
| 11 | Price_vs_SMA_150_Delta | 0 | 1.7% | 19.9% |
| 12 | roe | 0 | 1.6% | 21.6% |
| 13 | log_Price_vs_SMA_200_Delta | 0 | 1.6% | 23.2% |
| 14 | m03_regime_vol | 0 | 1.6% | 24.9% |
| 15 | log_eps_accel | 0 | 1.6% | 26.5% |
| 16 | log_Price_vs_SMA_50 | 0 | 1.6% | 28.2% |
| 17 | alpha006 | 0 | 1.6% | 29.8% |
| 18 | Price_vs_SMA_50_Delta | 0 | 1.6% | 31.4% |
| 19 | log_Dry_Up_Volume_Lag1 | 0 | 1.6% | 33.0% |
| 20 | alpha013 | 0 | 1.6% | 34.6% |

---

## Regime-Conditional Performance

Performance bucketed by M03 market regime at entry time.

### Top Decile Performance by Regime

| Regime | N Trades | Win Rate | Mean Return | Median Return |
|--------|----------|----------|-------------|---------------|
| Strong Bear | 34 | 8.8% | -0.06% | -2.27% |
| Bear | 125 | 8.8% | -1.25% | -4.27% |
| Neutral | 231 | 16.5% | +2.44% | -2.75% |
| Bull | 173 | 7.5% | +1.16% | -3.74% |
| Strong Bull | 160 | 13.8% | +2.19% | -2.41% |

---

## Decile Performance Analysis

### Win Rate and Return by Predicted Decile

| Decile | N Trades | Win Rate | Mean Return | Median | Min | Max |
|--------|----------|----------|-------------|--------|-----|-----|
| 1 | 724 | 15.5% | +0.64% | -5.51% | -35.0% | +183.8% |
| 2 | 723 | 10.9% | +0.87% | -3.56% | -75.2% | +516.6% |
| 3 | 723 | 9.3% | -0.03% | -3.45% | -46.0% | +302.2% |
| 4 | 723 | 10.1% | +0.95% | -2.62% | -31.0% | +150.7% |
| 5 | 723 | 10.4% | +1.32% | -2.45% | -36.0% | +334.3% |
| 6 | 723 | 12.2% | +2.07% | -1.91% | -23.1% | +229.1% |
| 7 | 723 | 10.8% | +1.73% | -2.19% | -42.1% | +140.5% |
| 8 | 723 | 13.8% | +2.24% | -2.26% | -25.9% | +164.8% |
| 9 | 723 | 13.0% | +2.20% | -2.76% | -22.3% | +293.4% |
| 10 | 723 | 12.0% | +1.32% | -3.13% | -25.2% | +149.5% |

### Detailed Decile Statistics

Return distribution percentiles by predicted decile:

| Decile | N | Mean | Std | Min | P1 | P5 | P25 | P50 | P75 | P95 | P99 | Max |
|--------|---|------|-----|-----|----|----|-----|-----|-----|-----|-----|-----|
| 1 | 724 | +0.6 | 21.3 | -35 | -26 | -18 | -12 | -6 | +5 | +42 | +82 | +184 |
| 2 | 723 | +0.9 | 27.0 | -75 | -24 | -18 | -8 | -4 | +3 | +31 | +64 | +517 |
| 3 | 723 | -0.0 | 17.7 | -46 | -21 | -14 | -7 | -3 | +2 | +24 | +47 | +302 |
| 4 | 723 | +1.0 | 14.4 | -31 | -17 | -13 | -6 | -3 | +4 | +24 | +61 | +151 |
| 5 | 723 | +1.3 | 21.3 | -36 | -20 | -13 | -7 | -2 | +4 | +25 | +50 | +334 |
| 6 | 723 | +2.1 | 16.3 | -23 | -16 | -11 | -6 | -2 | +5 | +28 | +64 | +229 |
| 7 | 723 | +1.7 | 14.9 | -42 | -19 | -12 | -6 | -2 | +5 | +28 | +66 | +141 |
| 8 | 723 | +2.2 | 16.3 | -26 | -16 | -13 | -6 | -2 | +5 | +29 | +65 | +165 |
| 9 | 723 | +2.2 | 20.2 | -22 | -16 | -12 | -7 | -3 | +4 | +30 | +68 | +293 |
| 10 | 723 | +1.3 | 16.1 | -25 | -18 | -14 | -8 | -3 | +6 | +32 | +63 | +150 |

---

## Super Stock Classification

*Super Stock = Return > 50%*

**Market Base Rate:** 133 Super Stocks (1.84% of all trades)

### Precision & Recall

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Precision @ Top 10% | 1.94% | 14/723 top picks are Super Stocks |
| Recall @ Top 10% | 10.5% | 14/133 Super Stocks found in top decile |
| Lift @ Top 10% | 1.1x | vs random (1.84% base rate) |

### Percentile Lift (Granular Selection)

| Percentile | N | Super Stocks | Precision | Lift |
|------------|---|--------------|-----------|------|
| Top 1% | 73 | 4 | 5.5% | 3.0x |
| Top 2% | 145 | 5 | 3.4% | 1.9x |
| Top 5% | 362 | 11 | 3.0% | 1.7x |
| Top 10% | 724 | 14 | 1.9% | 1.1x |
| Top 20% | 1447 | 29 | 2.0% | 1.1x |

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