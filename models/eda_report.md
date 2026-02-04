# Feature Evaluation Report (Quant-Standard)

**Generated:** 2026-02-01 18:18:55
**Target Variable:** `return_pct`
**Composite Weights:** 40% IC + 30% Stability + 30% KS
**Correlation Threshold:** 0.7

---

## Executive Summary

- **Total candidates:** 138
- **Final passed:** 62
- **Regime-conditional features:** 95 (flagged for monitoring)

## Section 1: Feature Leaderboard

> **Note:** All scores are normalized 0-1 for comparability. IC (Norm) = raw Spearman IC divided by max IC in dataset.

| Rank | Feature | Composite | IC (Norm) | Stability | KS | Signal Type |
|------|---------|-----------|-----------|-----------|-----|-------------|
| 1 | `alpha011` | 0.835 | 0.671 | 1.000 | 0.889 | linear_pos |
| 2 | `nATR` | 0.808 | 1.000 | 0.695 | 0.667 | linear_pos |
| 3 | `Price_vs_SMA_200` | 0.777 | 0.980 | 0.728 | 0.556 | kinked |
| 4 | `Dist_From_52W_Low` | 0.733 | 0.847 | 0.647 | 0.667 | linear_pos |
| 5 | `eps_stability_score` | 0.602 | 0.484 | 0.806 | 0.556 | kinked |
| 6 | `alpha013` | 0.584 | 0.407 | 0.737 | 0.667 | linear_neg |
| 7 | `operating_margin` | 0.559 | 0.450 | 0.707 | 0.556 | kinked |
| 8 | `alpha060` | 0.552 | 0.470 | 0.658 | 0.556 | kinked |
| 9 | `m03_pillar_risk` | 0.551 | 0.290 | 0.782 | 0.667 | linear_neg |
| 10 | `debt_to_equity` | 0.545 | 0.259 | 0.806 | 0.667 | linear_neg |
| 11 | `m03_pillar_trend` | 0.543 | 0.439 | 0.671 | 0.556 | kinked |
| 12 | `RS_Delta` | 0.541 | 0.499 | 0.473 | 0.667 | linear_pos |
| 13 | `current_ratio` | 0.500 | 0.386 | 0.596 | 0.556 | kinked |
| 14 | `fcf_margin` | 0.450 | 0.234 | 0.522 | 0.667 | linear_neg |
| 15 | `earnings_quality_score` | 0.447 | 0.229 | 0.631 | 0.556 | kinked |
| 16 | `rs_velocity` | 0.443 | 0.253 | 0.472 | 0.667 | linear_neg |
| 17 | `nATR_Delta` | 0.423 | 0.324 | 0.310 | 0.667 | linear_neg |
| 18 | `m03_score` | 0.418 | 0.127 | 0.558 | 0.667 | linear_neg |
| 19 | `log_volume_velocity` | 0.415 | 0.170 | 0.601 | 0.556 | kinked |
| 20 | `alpha001` | 0.414 | 0.310 | 0.412 | 0.556 | kinked |
| 21 | `alpha054` | 0.395 | 0.252 | 0.314 | 0.667 | linear_pos |
| 22 | `alpha101` | 0.387 | 0.185 | 0.376 | 0.667 | linear_neg |
| 23 | `days_since_report` | 0.380 | 0.254 | 0.260 | 0.667 | linear_neg |
| 24 | `roe` | 0.374 | 0.205 | 0.307 | 0.667 | linear_pos |
| 25 | `price_accel_10d` | 0.370 | 0.247 | 0.350 | 0.556 | kinked |
| 26 | `alpha041` | 0.364 | 0.025 | 0.291 | 0.889 | linear_neg |
| 27 | `Price_vs_SMA_50_Delta` | 0.357 | 0.186 | 0.274 | 0.667 | linear_neg |
| 28 | `roa` | 0.356 | 0.231 | 0.324 | 0.556 | kinked |
| 29 | `RSI_14` | 0.351 | 0.181 | 0.262 | 0.667 | linear_pos |
| 30 | `m03_pillar_liq` | 0.345 | 0.286 | 0.102 | 0.667 | linear_pos |

## Section 2: Monotonicity Deep Dive

### alpha011
- **Signal Type:** linear_pos
- **D1 Mean Return:** -2.97%
- **D10 Mean Return:** +8.34%
- **Decile Returns:**
  ```
  D 1:  -2.97% |-------
  D 2:  -0.67% |-
  D 3:  -0.05% |
  D 4:  +0.81% |+
  D 5:  +1.12% |++
  D 6:  +1.72% |++++
  D 7:  +1.53% |+++
  D 8:  +2.43% |+++++
  D 9:  +2.57% |++++++
  D10:  +8.34% |++++++++++++++++++++
  ```
  > **M02 Warning:** D1 has negative avg return (-2.97%)

### alpha041
- **Signal Type:** linear_neg
- **D1 Mean Return:** +6.77%
- **D10 Mean Return:** -0.39%
- **Decile Returns:**
  ```
  D 1:  +6.77% |++++++++++++++++++++
  D 2:  +2.37% |++++++
  D 3:  +1.84% |+++++
  D 4:  +1.41% |++++
  D 5:  +0.79% |++
  D 6:  +1.00% |++
  D 7:  +0.80% |++
  D 8:  +0.35% |+
  D 9:  -0.11% |
  D10:  -0.39% |-
  ```

### Price_vs_SMA_200_Delta
- **Signal Type:** linear_pos
- **D1 Mean Return:** +0.93%
- **D10 Mean Return:** +2.65%
- **Decile Returns:**
  ```
  D 1:  +0.93% |+++++++
  D 2:  +1.04% |+++++++
  D 3:  +0.52% |+++
  D 4:  +0.77% |+++++
  D 5:  +1.58% |+++++++++++
  D 6:  +1.44% |++++++++++
  D 7:  +1.69% |++++++++++++
  D 8:  +1.75% |+++++++++++++
  D 9:  +2.50% |++++++++++++++++++
  D10:  +2.65% |++++++++++++++++++++
  ```

### Dist_From_20D_Low_Delta
- **Signal Type:** linear_pos
- **D1 Mean Return:** +1.05%
- **D10 Mean Return:** +2.73%
- **Decile Returns:**
  ```
  D 1:  +1.05% |+++++++
  D 2:  +1.13% |++++++++
  D 3:  +0.98% |+++++++
  D 4:  +1.22% |++++++++
  D 5:  +0.86% |++++++
  D 6:  +1.14% |++++++++
  D 7:  +1.22% |++++++++
  D 8:  +2.05% |+++++++++++++++
  D 9:  +2.41% |+++++++++++++++++
  D10:  +2.73% |++++++++++++++++++++
  ```

### alpha006
- **Signal Type:** linear_neg
- **D1 Mean Return:** +2.87%
- **D10 Mean Return:** +0.53%
- **Decile Returns:**
  ```
  D 1:  +2.87% |++++++++++++++++++++
  D 2:  +1.95% |+++++++++++++
  D 3:  +1.68% |+++++++++++
  D 4:  +1.82% |++++++++++++
  D 5:  +1.54% |++++++++++
  D 6:  +1.59% |+++++++++++
  D 7:  +1.26% |++++++++
  D 8:  +0.94% |++++++
  D 9:  +0.66% |++++
  D10:  +0.53% |+++
  ```

### Dist_From_52W_Low
- **Signal Type:** linear_pos
- **D1 Mean Return:** +0.19%
- **D10 Mean Return:** +5.30%
- **Decile Returns:**
  ```
  D 1:  +0.19% |
  D 2:  +0.48% |+
  D 3:  +0.16% |
  D 4:  +0.01% |
  D 5:  +0.85% |+++
  D 6:  +0.39% |+
  D 7:  +1.69% |++++++
  D 8:  +2.61% |+++++++++
  D 9:  +3.17% |+++++++++++
  D10:  +5.30% |++++++++++++++++++++
  ```

### volume_acceleration
- **Signal Type:** linear_pos
- **D1 Mean Return:** +1.15%
- **D10 Mean Return:** +4.01%
- **Decile Returns:**
  ```
  D 1:  +1.15% |+++++
  D 2:  +0.91% |++++
  D 3:  +1.06% |+++++
  D 4:  +1.19% |+++++
  D 5:  +0.83% |++++
  D 6:  +1.44% |+++++++
  D 7:  +1.97% |+++++++++
  D 8:  +1.08% |+++++
  D 9:  +1.19% |+++++
  D10:  +4.01% |++++++++++++++++++++
  ```

### rs_velocity
- **Signal Type:** linear_neg
- **D1 Mean Return:** +2.25%
- **D10 Mean Return:** +0.04%
- **Decile Returns:**
  ```
  D 1:  +2.25% |++++++++++++++++++
  D 2:  +2.21% |++++++++++++++++++
  D 3:  +2.41% |++++++++++++++++++++
  D 4:  +1.59% |+++++++++++++
  D 5:  +1.50% |++++++++++++
  D 6:  +1.24% |++++++++++
  D 7:  +1.34% |+++++++++++
  D 8:  +1.06% |++++++++
  D 9:  +1.21% |++++++++++
  D10:  +0.04% |
  ```

### VCP_Ratio
- **Signal Type:** linear_pos
- **D1 Mean Return:** +0.91%
- **D10 Mean Return:** +2.43%
- **Decile Returns:**
  ```
  D 1:  +0.91% |+++++++
  D 2:  +2.04% |++++++++++++++++
  D 3:  +1.04% |++++++++
  D 4:  +1.44% |+++++++++++
  D 5:  +0.89% |+++++++
  D 6:  +0.39% |+++
  D 7:  +1.52% |++++++++++++
  D 8:  +1.91% |+++++++++++++++
  D 9:  +2.27% |++++++++++++++++++
  D10:  +2.43% |++++++++++++++++++++
  ```

### nATR
- **Signal Type:** linear_pos
- **D1 Mean Return:** +0.32%
- **D10 Mean Return:** +6.22%
- **Decile Returns:**
  ```
  D 1:  +0.32% |+
  D 2:  +0.65% |++
  D 3:  +0.40% |+
  D 4:  +0.77% |++
  D 5:  +0.51% |+
  D 6:  +0.87% |++
  D 7:  +1.49% |++++
  D 8:  +0.95% |+++
  D 9:  +2.67% |++++++++
  D10:  +6.22% |++++++++++++++++++++
  ```

## Section 3: Stability Analysis (Per-Year IC)

| Feature | IC_2015 | IC_2016 | IC_2017 | IC_2018 | IC_2019 | IC_2020 | IC_2021 | IC_2022 | IC_2023 | IC_2024 | IC_2025 | Stability | Regime? |
|---------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|
| `alpha011` | 0.034 | 0.051 | 0.078 | 0.032 | 0.059 | 0.075 | 0.127 | 0.009 | 0.022 | 0.111 | 0.045 | 1.67 | Yes |
| `debt_to_equity` | 0.032 | 0.019 | 0.021 | 0.010 | 0.063 | -0.014 | 0.024 | 0.035 | 0.043 | 0.078 | 0.055 | 1.35 | Yes |
| `alpha013` | 0.086 | -0.060 | 0.145 | 0.068 | 0.091 | 0.091 | 0.006 | 0.062 | 0.106 | 0.031 | 0.094 | 1.23 | Yes |
| `operating_margin` | 0.096 | 0.109 | 0.041 | 0.082 | 0.100 | -0.046 | 0.125 | -0.015 | 0.061 | 0.057 | 0.040 | 1.18 | Yes |
| `alpha060` | 0.077 | 0.011 | 0.017 | 0.075 | 0.005 | -0.007 | 0.071 | 0.190 | 0.085 | 0.046 | 0.061 | 1.10 | Yes |
| `earnings_quality_score` | 0.021 | 0.013 | 0.008 | 0.022 | 0.065 | -0.020 | 0.048 | 0.048 | 0.029 | 0.036 | -0.000 | 1.06 | Yes |
| `fcf_margin` | 0.037 | 0.052 | 0.035 | 0.076 | 0.056 | -0.029 | 0.088 | 0.020 | 0.026 | 0.053 | -0.044 | 0.87 | Yes |
| `peg_adjusted` | 0.055 | 0.040 | 0.008 | 0.058 | 0.101 | -0.105 | 0.119 | 0.077 | 0.057 | 0.020 | -0.014 | 0.65 | Yes |
| `Dist_From_52W_High` | 0.064 | 0.062 | 0.071 | 0.018 | 0.035 | 0.049 | -0.057 | -0.042 | -0.040 | 0.072 | 0.083 | 0.58 | Yes |
| `roa` | -0.015 | -0.020 | 0.109 | 0.089 | 0.039 | -0.058 | 0.067 | -0.013 | 0.068 | 0.058 | -0.015 | 0.54 | Yes |
| `nATR_Delta` | -0.014 | 0.181 | 0.007 | 0.094 | 0.007 | -0.102 | -0.001 | 0.105 | 0.075 | 0.064 | -0.003 | 0.52 | Yes |
| `roe` | -0.016 | 0.043 | 0.106 | 0.089 | 0.054 | -0.101 | 0.072 | 0.000 | 0.026 | 0.068 | -0.020 | 0.51 | Yes |
| `alpha015` | 0.005 | -0.038 | 0.042 | 0.040 | 0.021 | 0.016 | -0.005 | 0.069 | 0.048 | -0.037 | 0.019 | 0.51 | Yes |
| `alpha041` | 0.024 | -0.025 | 0.041 | 0.001 | 0.028 | -0.037 | -0.025 | 0.017 | 0.055 | 0.065 | 0.028 | 0.49 | Yes |
| `RSI_14` | -0.027 | 0.012 | 0.057 | -0.012 | 0.089 | 0.077 | 0.012 | -0.036 | 0.002 | -0.037 | 0.091 | 0.44 | Yes |

### Regime-Conditional Features (High IC Variance)

These features have inconsistent IC across years. Monitor closely:

- `alpha011`
- `debt_to_equity`
- `alpha013`
- `operating_margin`
- `alpha060`
- `earnings_quality_score`
- `fcf_margin`
- `peg_adjusted`
- `Dist_From_52W_High`
- `roa`

## Section 4: Correlation Clusters

### Cluster 15
- **Members:** `Price_vs_SMA_50`, `Price_vs_SMA_150`, `Price_vs_SMA_200`
- **Keep:** `Price_vs_SMA_200` (highest weighted score (IC=0.132, Stab=1.22))
- **Drop:** `Price_vs_SMA_150`, `Price_vs_SMA_50`

### Cluster 36
- **Members:** `Vol_Ratio`, `Dry_Up_Volume_Delta`
- **Keep:** `Dry_Up_Volume_Delta` (highest weighted score (IC=0.024, Stab=0.56))
- **Drop:** `Vol_Ratio`

### Cluster 29
- **Members:** `RS`, `alpha041`
- **Keep:** `alpha041` (highest weighted score (IC=0.016, Stab=0.49))
- **Drop:** `RS`

### Cluster 14
- **Members:** `nATR`, `Consolidation_Width`, `Dist_From_20D_Low`
- **Keep:** `nATR` (highest weighted score (IC=0.116, Stab=1.16))
- **Drop:** `Dist_From_20D_Low`, `Consolidation_Width`

### Cluster 12
- **Members:** `Dist_From_52W_High`, `Dist_From_52W_High_Delta`
- **Keep:** `Dist_From_52W_High` (highest weighted score (IC=0.029, Stab=0.58))
- **Drop:** `Dist_From_52W_High_Delta`

### Cluster 6
- **Members:** `Dist_From_20D_High`, `alpha054`
- **Keep:** `alpha054` (highest weighted score (IC=0.026, Stab=0.53))
- **Drop:** `Dist_From_20D_High`

### Cluster 41
- **Members:** `breakout_momentum`, `Consolidation_Width_Delta`
- **Keep:** `breakout_momentum` (highest weighted score (IC=0.005, Stab=0.10))
- **Drop:** `Consolidation_Width_Delta`

### Cluster 28
- **Members:** `price_momentum_curve`, `immediate_thrust`, `alpha009`, `alpha012`, `alpha049`, `alpha051`
- **Keep:** `alpha012` (highest weighted score (IC=0.023, Stab=0.43))
- **Drop:** `alpha051`, `alpha049`, `alpha009`, `price_momentum_curve`, `immediate_thrust`

### Cluster 40
- **Members:** `nATR_Delta`, `ATR_Delta`, `VCP_Ratio_Delta`
- **Keep:** `nATR_Delta` (highest weighted score (IC=0.038, Stab=0.52))
- **Drop:** `VCP_Ratio_Delta`, `ATR_Delta`

### Cluster 39
- **Members:** `RS_Delta`, `High_52W_Delta`, `Highest_High_20D_Delta`, `Dist_From_52W_Low_Delta`
- **Keep:** `RS_Delta` (highest weighted score (IC=0.061, Stab=0.79))
- **Drop:** `Highest_High_20D_Delta`, `Dist_From_52W_Low_Delta`, `High_52W_Delta`

## Section 5: Distributional Warnings

| Feature | Issue | Action |
|---------|-------|--------|
| `Is_Green_Day` | Kurtosis=14.2 | Consider winsorizing at 1/99% |
| `Dist_From_52W_Low` | Kurtosis=26.9 | Consider winsorizing at 1/99% |
| `price_accel_10d` | Kurtosis=11.2 | Consider winsorizing at 1/99% |
| `nATR_Delta` | Kurtosis=276.7 | Consider winsorizing at 1/99% |
| `Price_vs_SMA_50_Delta` | Kurtosis=15.7 | Consider winsorizing at 1/99% |
| `Price_vs_SMA_150_Delta` | Kurtosis=15.9 | Consider winsorizing at 1/99% |
| `Price_vs_SMA_200_Delta` | Kurtosis=80.6 | Consider winsorizing at 1/99% |
| `RS_Delta` | Kurtosis=422.8 | Consider winsorizing at 1/99% |
| `RS_MA_Delta` | Kurtosis=1580.2 | Consider winsorizing at 1/99% |
| `Dry_Up_Volume_Delta` | Kurtosis=28.8 | Consider winsorizing at 1/99% |
| `Dist_From_20D_Low_Delta` | Kurtosis=26.4 | Consider winsorizing at 1/99% |
| `Dist_From_20D_High_Delta` | Kurtosis=21.4 | Consider winsorizing at 1/99% |
| `alpha001` | Kurtosis=189.7 | Consider winsorizing at 1/99% |
| `alpha060` | Kurtosis=24.4 | Consider winsorizing at 1/99% |
| `eps_stability_score` | Kurtosis=24.2 | Consider winsorizing at 1/99% |
| `debt_to_equity` | Kurtosis=14.5 | Consider winsorizing at 1/99% |
| `current_ratio` | Kurtosis=20.2 | Consider winsorizing at 1/99% |
| `operating_margin` | Kurtosis=56.8 | Consider winsorizing at 1/99% |
| `roe` | Kurtosis=13.7 | Consider winsorizing at 1/99% |
| `inventory_growth_yoy` | Kurtosis=14.4 | Consider winsorizing at 1/99% |

## Section 6: Transformation Summary

> Features with high kurtosis were automatically transformed during EDA:
> - **Log Transform** (`sign(x) * log(1+|x|)`): Preserves magnitude (explosive/TAR>1.2)
> - **Winsorization** (1%/99%): Clips outliers as noise (bounded/standard/TAR<=1.2)

| Feature | Transform | Category | TAR |
|---------|-----------|----------|-----|
| `Price_vs_SMA_50` | Log | Explosive | - |
| `Price_vs_SMA_150` | Log | Explosive | - |
| `Price_vs_SMA_200` | Log | Explosive | - |
| `Vol_Ratio` | Log | Explosive | - |
| `RS` | Log | Explosive | - |
| `nATR` | Log | Explosive | - |
| `Consolidation_Width` | Log | TAR-based | 3.64 |
| `Dry_Up_Volume` | Log | Explosive | - |
| `Dist_From_20D_Low` | Log | TAR-based | 3.72 |
| `Dist_From_52W_Low` | Log | Explosive | - |
| `volume_acceleration` | Log | Explosive | - |
| `breakout_momentum` | Log | TAR-based | 1.85 |
| `consolidation_duration` | Log | TAR-based | 1.32 |
| `log_volume_velocity` | Log | TAR-based | 3.03 |
| `nATR_Delta` | Log | TAR-based | 1.26 |
| `ATR_Delta` | Log | TAR-based | 2.16 |
| `VCP_Ratio_Delta` | Log | TAR-based | 2.06 |
| `Consolidation_Width_Delta` | Log | TAR-based | 1.45 |
| `Price_vs_SMA_200_Delta` | Log | TAR-based | 1.64 |
| `RS_Delta` | Log | TAR-based | 3.43 |
| `RS_MA_Delta` | Log | TAR-based | 3.90 |
| `Dry_Up_Volume_Delta` | Log | TAR-based | 2.87 |
| `High_52W_Delta` | Log | TAR-based | 2.77 |
| `Low_52W_Delta` | Log | TAR-based | 1.40 |
| `Lowest_Low_20D_Delta` | Log | TAR-based | 1.84 |
| `Highest_High_20D_Delta` | Log | TAR-based | 3.11 |
| `RSI_14_Delta` | Log | TAR-based | 1.57 |
| `Dist_From_52W_Low_Delta` | Log | TAR-based | 2.51 |
| `Dist_From_20D_Low_Delta` | Log | TAR-based | 1.42 |
| `alpha001` | Log | TAR-based | 2.78 |
| `alpha060` | Log | TAR-based | 1.95 |
| `revenue_growth_yoy` | Log | Explosive | - |
| `net_income_growth_yoy` | Log | TAR-based | 1.36 |
| `eps_growth_yoy` | Log | Explosive | - |
| `eps_accel` | Log | Explosive | - |
| `revenue_accel` | Log | Explosive | - |
| `revenue_cagr_3y` | Log | TAR-based | 1.93 |
| `debt_to_equity` | Log | TAR-based | 1.48 |
| `current_ratio` | Log | TAR-based | 1.25 |
| `quick_ratio` | Log | TAR-based | 1.25 |
| `fcf_margin` | Log | TAR-based | 1.21 |
| `gross_margin_trend` | Log | TAR-based | 1.98 |
| `days_since_report` | Log | TAR-based | 1.23 |
| `days_since_earnings` | Log | TAR-based | 1.23 |
| `pb_ratio` | Log | Explosive | - |
| `VCP_Ratio` | Winsorize | Standard | - |
| `RSI_Regime` | Winsorize | TAR-based | 1.00 |
| `Is_Green_Day` | Winsorize | TAR-based | 1.00 |
| `SMA_50_Slope` | Winsorize | Standard | - |
| `Dist_From_20D_High` | Winsorize | TAR-based | 1.10 |
| `rs_velocity` | Winsorize | TAR-based | 1.13 |
| `price_momentum_curve` | Winsorize | TAR-based | 1.01 |
| `immediate_thrust` | Winsorize | TAR-based | 1.01 |
| `price_accel_10d` | Winsorize | TAR-based | 1.04 |
| `Price_vs_SMA_50_Delta` | Winsorize | TAR-based | 1.14 |
| `Price_vs_SMA_150_Delta` | Winsorize | TAR-based | 1.13 |
| `Dist_From_20D_High_Delta` | Winsorize | TAR-based | 0.86 |
| `alpha009` | Winsorize | TAR-based | 1.08 |
| `alpha012` | Winsorize | TAR-based | 0.92 |
| `alpha041` | Winsorize | TAR-based | 0.87 |
| `alpha004` | Winsorize | TAR-based | 0.99 |
| `alpha046` | Winsorize | TAR-based | 0.97 |
| `alpha049` | Winsorize | TAR-based | 0.94 |
| `alpha051` | Winsorize | TAR-based | 0.92 |
| `eps_stability_score` | Winsorize | TAR-based | 1.10 |
| `gross_margin` | Winsorize | Standard | - |
| `operating_margin` | Winsorize | Standard | - |
| `roe` | Winsorize | Standard | - |
| `roa` | Winsorize | Standard | - |
| `net_margin` | Winsorize | Standard | - |
| `inventory_growth_yoy` | Winsorize | TAR-based | 0.87 |
| `inventory_vs_sales_spread` | Winsorize | TAR-based | 0.84 |
| `earnings_quality_score` | Winsorize | Bounded | - |

**Total:** 45 log-transformed, 28 winsorized

> **TAR (Tail Alpha Ratio):** Ratio of mean |return| in 99-100th percentile vs 10-90th percentile.
> TAR > 1.2 suggests tail values are predictive (log transform); TAR <= 1.2 suggests noise (winsorize).

## Recommended Feature List

Copy this to `src/feature_config.py` → `M01_FEATURES` after review:

> **Note:** Features with `log_` prefix are log-transformed during preprocessing.
> The preprocessor will apply these transforms automatically at training/inference.

```python
M01_FEATURES = [
    'alpha011',
    'log_nATR',  # log-transformed
    'log_Price_vs_SMA_200',  # log-transformed
    'log_Dist_From_52W_Low',  # log-transformed
    'eps_stability_score',
    'alpha013',
    'operating_margin',
    'log_alpha060',  # log-transformed
    'm03_pillar_risk',
    'log_debt_to_equity',  # log-transformed
    'm03_pillar_trend',
    'log_RS_Delta',  # log-transformed
    'log_current_ratio',  # log-transformed
    'log_fcf_margin',  # log-transformed
    'earnings_quality_score',
    'rs_velocity',
    'log_nATR_Delta',  # log-transformed
    'm03_score',
    'log_volume_velocity',  # already log-transformed
    'log_alpha001',  # log-transformed
    'alpha054',
    'alpha101',
    'log_days_since_report',  # log-transformed
    'roe',
    'price_accel_10d',
    'alpha041',
    'Price_vs_SMA_50_Delta',
    'roa',
    'RSI_14',
    'm03_pillar_liq',
    'alpha012',
    'log_RS_MA_Delta',  # log-transformed
    'log_Dry_Up_Volume_Delta',  # log-transformed
    'alpha015',
    'pe_ratio',
    'log_revenue_growth_yoy',  # log-transformed
    'is_declining_earnings',
    'log_Dry_Up_Volume',  # log-transformed
    'log_Dist_From_20D_Low_Delta',  # log-transformed
    'SMA_50_Slope',
    'peg_adjusted',
    'log_revenue_cagr_3y',  # log-transformed
    'gross_margin',
    'log_Price_vs_SMA_200_Delta',  # log-transformed
    'inventory_growth_yoy',
    'alpha006',
    'Dist_From_20D_High_Delta',
    'log_pb_ratio',  # log-transformed
    'log_revenue_accel',  # log-transformed
    'log_eps_accel',  # log-transformed
    'alpha002',
    'log_volume_acceleration',  # log-transformed
    'ps_ratio',
    'm03_delta_5d',
    'log_gross_margin_trend',  # log-transformed
    'VCP_Ratio',
    'Dist_From_52W_High',
    'log_breakout_momentum',  # log-transformed
    'Price_vs_SMA_150_Delta',
    'm03_regime_vol',
    'm03_delta_20d',
    'Is_Green_Day',
]
```

---

## Next Steps (User Action Required)

**The workflow does NOT auto-save models.** To deploy new features:

1. **Review** this report and the passed/failed features
2. **Copy** the recommended feature list above to `src/feature_config.py` → `M01_FEATURES`
3. **Train** the production model:
   ```bash
   python model_runner.py m01 --steps train
   ```
4. **Verify** the model works with `daily_scanner.py --ml`

> **Why manual approval?** Auto-saving overwrote production models during testing.
> This safeguard ensures only reviewed features reach production.

---

*Report generated by FeatureScreener (Quant-Standard Pipeline)*