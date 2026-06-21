# Model Training Report - M01 (SEPA Signal Quality Model)

**Generated:** 2026-02-10 22:09:25
**Training Period:** 2018-01-01 to 2025-12-31
**Model Type:** REGRESSION
**Target:** target

---

## Executive Summary

**Trading Viability:** NOT VIABLE

### Key Metrics

- **Selection Edge:** +0.17% (range: [-0.06%, +0.51%])
- **Edge Consistency:** 3/5 folds positive (60%)
- **Edge Sharpe Ratio:** 0.63
- **Top Decile Return:** 1.48%
- **RMSE:** 2.09%
- **Walk-Forward Folds:** 5
- **Total Test Samples:** 7,231

---

## Walk-Forward Validation Results

| Fold | Test Year | Test Samples | RMSE | Selection Edge | Top Decile Mean |
|------|-----------|--------------|------|----------------|-----------------|
| 1 | 2021.0 | 2,026.0 | 1.98% | -0.06% | 1.49% |
| 2 | 2022.0 | 598.0 | 2.21% | +0.51% | 1.44% |
| 3 | 2023.0 | 1,390.0 | 1.98% | +0.01% | 1.40% |
| 4 | 2024.0 | 1,969.0 | 2.00% | +0.43% | 1.86% |
| 5 | 2025.0 | 1,248.0 | 2.28% | -0.02% | 1.19% |

---

## Feature Importance Analysis

**Total Features:** 72

### Top 20 Features by Gain

| Rank | Feature | Gain | % Total | Cumulative % |
|------|---------|------|---------|--------------|
| 1 | industry_id | 0 | 3.1% | 3.1% |
| 2 | inventory_vs_sales_spread | 0 | 2.7% | 5.8% |
| 3 | log_Price_vs_SMA_200 | 0 | 2.5% | 8.4% |
| 4 | alpha011 | 0 | 2.3% | 10.7% |
| 5 | log_Price_vs_SMA_50 | 0 | 2.3% | 13.0% |
| 6 | log_RS | 0 | 2.3% | 15.3% |
| 7 | log_Dist_From_20D_Low_Delta | 0 | 2.2% | 17.5% |
| 8 | Price_vs_SMA_150_Delta | 0 | 2.2% | 19.7% |
| 9 | m03_pillar_liq | 0 | 2.1% | 21.8% |
| 10 | net_income_growth_yoy | 0 | 2.1% | 23.8% |
| 11 | alpha101 | 0 | 1.9% | 25.7% |
| 12 | alpha013 | 0 | 1.8% | 27.5% |
| 13 | alpha006 | 0 | 1.7% | 29.2% |
| 14 | m03_score | 0 | 1.7% | 30.9% |
| 15 | log_mom_63d | 0 | 1.7% | 32.7% |
| 16 | log_alpha001 | 0 | 1.7% | 34.4% |
| 17 | log_alpha060 | 0 | 1.7% | 36.1% |
| 18 | current_ratio | 0 | 1.7% | 37.8% |
| 19 | log_VCP_Ratio_Delta | 0 | 1.7% | 39.4% |
| 20 | alpha012 | 0 | 1.6% | 41.1% |

---

## Regime-Conditional Performance

Performance bucketed by M03 market regime at entry time.

### Top Decile Performance by Regime

| Regime | N Trades | Win Rate | Mean Return | Median Return |
|--------|----------|----------|-------------|---------------|
| Strong Bear | 52 | 3.8% | -3.22% | -3.30% |
| Bear | 112 | 8.0% | -0.99% | -3.85% |
| Neutral | 216 | 15.7% | +2.08% | -3.50% |
| Bull | 183 | 8.7% | +1.52% | -3.09% |
| Strong Bull | 160 | 18.8% | +3.13% | -2.18% |

---

## Decile Performance Analysis

### Win Rate and Return by Predicted Decile

| Decile | N Trades | Win Rate | Mean Return | Median | Min | Max |
|--------|----------|----------|-------------|--------|-----|-----|
| 1 | 724 | 15.7% | +1.16% | -5.35% | -75.2% | +334.3% |
| 2 | 723 | 10.5% | +0.44% | -3.35% | -36.0% | +140.5% |
| 3 | 723 | 9.7% | +0.15% | -3.31% | -35.0% | +302.2% |
| 4 | 723 | 10.1% | +0.92% | -2.63% | -46.0% | +141.3% |
| 5 | 723 | 10.7% | +0.87% | -2.66% | -30.3% | +150.7% |
| 6 | 723 | 10.8% | +1.15% | -1.87% | -32.0% | +141.2% |
| 7 | 723 | 12.3% | +2.72% | -1.94% | -22.1% | +279.8% |
| 8 | 723 | 13.4% | +1.92% | -2.46% | -27.5% | +151.5% |
| 9 | 723 | 12.2% | +2.66% | -2.67% | -31.0% | +516.6% |
| 10 | 723 | 12.6% | +1.32% | -3.26% | -42.1% | +149.5% |

### Detailed Decile Statistics

Return distribution percentiles by predicted decile:

| Decile | N | Mean | Std | Min | P1 | P5 | P25 | P50 | P75 | P95 | P99 | Max |
|--------|---|------|-----|-----|----|----|-----|-----|-----|-----|-----|-----|
| 1 | 724 | +1.2 | 25.9 | -75 | -23 | -18 | -11 | -5 | +5 | +38 | +82 | +334 |
| 2 | 723 | +0.4 | 16.1 | -36 | -26 | -15 | -7 | -3 | +2 | +28 | +74 | +141 |
| 3 | 723 | +0.2 | 17.4 | -35 | -18 | -14 | -7 | -3 | +3 | +24 | +48 | +302 |
| 4 | 723 | +0.9 | 14.4 | -46 | -21 | -13 | -7 | -3 | +4 | +26 | +57 | +141 |
| 5 | 723 | +0.9 | 14.3 | -30 | -19 | -13 | -7 | -3 | +4 | +25 | +56 | +151 |
| 6 | 723 | +1.1 | 14.4 | -32 | -19 | -12 | -6 | -2 | +5 | +26 | +56 | +141 |
| 7 | 723 | +2.7 | 21.7 | -22 | -16 | -12 | -6 | -2 | +5 | +27 | +90 | +280 |
| 8 | 723 | +1.9 | 15.7 | -28 | -17 | -13 | -7 | -2 | +6 | +30 | +56 | +151 |
| 9 | 723 | +2.7 | 26.8 | -31 | -20 | -13 | -7 | -3 | +5 | +34 | +74 | +517 |
| 10 | 723 | +1.3 | 17.3 | -42 | -20 | -15 | -8 | -3 | +5 | +33 | +72 | +150 |

---

## Super Stock Classification

*Super Stock = Return > 50%*

**Market Base Rate:** 133 Super Stocks (1.84% of all trades)

### Precision & Recall

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Precision @ Top 10% | 2.77% | 20/723 top picks are Super Stocks |
| Recall @ Top 10% | 15.0% | 20/133 Super Stocks found in top decile |
| Lift @ Top 10% | 1.5x | vs random (1.84% base rate) |

### Percentile Lift (Granular Selection)

| Percentile | N | Super Stocks | Precision | Lift |
|------------|---|--------------|-----------|------|
| Top 1% | 73 | 4 | 5.5% | 3.0x |
| Top 2% | 145 | 6 | 4.1% | 2.2x |
| Top 5% | 362 | 14 | 3.9% | 2.1x |
| Top 10% | 724 | 20 | 2.8% | 1.5x |
| Top 20% | 1447 | 36 | 2.5% | 1.4x |

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