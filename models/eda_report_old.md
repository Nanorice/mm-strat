# Feature Evaluation Report (Quant-Standard)

**Generated:** 2026-02-14 16:37:43
**Target Variable:** `y_max`
**Composite Weights:** 40% IC + 30% Stability + 30% KS
**Correlation Threshold:** 0.7

---

## Section 0: Dataset Overview

### Target Variable Distribution (`y_max`)

| Statistic | Value |
|-----------|-------|
| Count | 12,301 |
| Mean | +3.92% |
| Std Dev | 22.18% |
| Min | -96.32% |
| Max | +492.45% |
| Median | +0.58% |
| Q1 (25%) | -8.11% |
| Q3 (75%) | +9.45% |
| Skewness | +4.71 |
| Kurtosis | 55.6 |

| Outcome | Count | % |
|---------|-------|---|
| Positive (> 0%) | 6,413 | 52.1% |
| > +10% | 2,971 | 24.2% |
| > +20% | 1,638 | 13.3% |
| Negative (< 0%) | 5,880 | 47.8% |
| < -10% | 2,087 | 17.0% |

### Return Distribution (5% Buckets)

| Bucket | Count | % | Bar |
|--------|-------|---|-----|
| < -50% | 9 | 0.1% |  |
| [-50, -45)% | 4 | 0.0% |  |
| [-45, -40)% | 7 | 0.1% |  |
| [-40, -35)% | 10 | 0.1% |  |
| [-35, -30)% | 24 | 0.2% |  |
| [-30, -25)% | 52 | 0.4% |  |
| [-25, -20)% | 160 | 1.3% | █ |
| [-20, -15)% | 501 | 4.1% | ███ |
| [-15, -10)% | 1,320 | 10.7% | ████████ |
| [-10, -5)% | 3,027 | 24.6% | ████████████████████ |
| [-5, 0)% | 766 | 6.2% | █████ |
| [0, 5)% | 2,261 | 18.4% | ██████████████ |
| [5, 10)% | 1,189 | 9.7% | ███████ |
| [10, 15)% | 786 | 6.4% | █████ |
| [15, 20)% | 547 | 4.4% | ███ |
| [20, 25)% | 382 | 3.1% | ██ |
| [25, 30)% | 280 | 2.3% | █ |
| [30, 35)% | 188 | 1.5% | █ |
| [35, 40)% | 158 | 1.3% | █ |
| [40, 45)% | 129 | 1.0% |  |
| [45, 50)% | 88 | 0.7% |  |
| >= 50% | 413 | 3.4% | ██ |

### Holding Period (`days_held`)

| Statistic | Value |
|-----------|-------|
| Mean | 36.3 days |
| Std Dev | 34.7 days |
| Min | 1 days |
| Max | 403 days |
| Median | 26.0 days |

### Temporal Coverage

- **Date Range:** 2018-01-02 to 2025-12-29
- **Unique Entry Dates:** 1,788

| Year | Samples | % |
|------|---------|---|
| 2018 | 1,471 | 12.0% |
| 2019 | 1,239 | 10.1% |
| 2020 | 1,270 | 10.3% |
| 2021 | 2,453 | 19.9% |
| 2022 | 713 | 5.8% |
| 2023 | 1,553 | 12.6% |
| 2024 | 2,243 | 18.2% |
| 2025 | 1,359 | 11.0% |

### Ticker Distribution

- **Unique Tickers:** 1,712
- **Top 10 Concentration:** 1.5% of samples

| Ticker | Samples |
|--------|---------|
| HUBS | 19 |
| FIVN | 18 |
| LLY | 18 |
| AVGO | 18 |
| MCK | 18 |
| TKO | 18 |
| KKR | 18 |
| NVDA | 18 |
| CBZ | 17 |
| RMBS | 17 |

### Sector Distribution

| Sector | Samples | % |
|--------|---------|---|
| Technology | 2,222 | 18.1% |
| Industrials | 2,109 | 17.1% |
| Financial Services | 1,903 | 15.5% |
| Healthcare | 1,809 | 14.7% |
| Consumer Cyclical | 1,350 | 11.0% |
| Energy | 730 | 5.9% |
| Consumer Defensive | 547 | 4.4% |
| Real Estate | 492 | 4.0% |
| Basic Materials | 469 | 3.8% |
| Communication Services | 385 | 3.1% |
| Utilities | 285 | 2.3% |

### Top 15 Industries

| Industry | Samples | % |
|----------|---------|---|
| Biotechnology | 679 | 5.5% |
| Banks - Regional | 596 | 4.8% |
| Software - Application | 554 | 4.5% |
| Semiconductors | 445 | 3.6% |
| Software - Infrastructure | 402 | 3.3% |
| Industrial - Machinery | 365 | 3.0% |
| Aerospace & Defense | 292 | 2.4% |
| Asset Management | 272 | 2.2% |
| Hardware, Equipment & Parts | 259 | 2.1% |
| Medical - Devices | 250 | 2.0% |
| Engineering & Construction | 242 | 2.0% |
| Financial - Capital Markets | 241 | 2.0% |
| Oil & Gas Exploration & Production | 220 | 1.8% |
| Chemicals - Specialty | 204 | 1.7% |
| Specialty Retail | 187 | 1.5% |

### MFE Analysis (Maximum Favorable Excursion)

*Peak return % during trade (best possible exit)*

| Statistic | Value |
|-----------|-------|
| Count | 12,273 |
| Mean | +13.1% |
| Std Dev | 25.0% |
| Min | +0.0% |
| Max | +1438.2% |
| Median | +6.0% |
| > 20% | 18.3% of trades |
| > 50% | 4.7% of trades |

### MAE Analysis (Maximum Adverse Excursion)

*Largest drawdown % during trade*

| Statistic | Value |
|-----------|-------|
| Mean | -6.9% |
| Median | -5.6% |
| Min (worst DD) | -78.7% |
| Max (best case) | +0.0% |

### Regret Analysis (MFE - Actual Return)

*How much return was left on the table*

- **Mean Regret:** +12.0%
- **Median Regret:** +9.7%

## Section 1: SEPA Audit (Entry Criteria Validation)

> **Purpose:** Validate SEPA C1-C11 criteria effectiveness by examining
> how key entry features relate to trade outcomes across deciles.

### rs_rating
*C9 - Relative Strength (core ranking)*

| Decile | Count | Mean | Median | Min | Max | Std | Win% |
|--------|-------|------|--------|-----|-----|-----|------|
| D1 | 1,230 | +2.6% | +1.5% | -28.0% | +67.5% | 9.9% | 69% |
| D2 | 1,230 | +2.8% | +1.1% | -25.1% | +302.2% | 14.7% | 60% |
| D3 | 1,230 | +2.3% | +0.7% | -39.5% | +101.3% | 12.7% | 55% |
| D4 | 1,230 | +2.2% | +0.3% | -25.6% | +133.6% | 14.9% | 51% |
| D5 | 1,230 | +2.9% | -2.9% | -34.2% | +104.1% | 15.4% | 50% |
| D6 | 1,229 | +2.8% | -4.5% | -28.5% | +165.1% | 17.8% | 47% |
| D7 | 1,230 | +3.6% | -4.8% | -44.2% | +191.7% | 20.1% | 47% |
| D8 | 1,230 | +5.3% | -5.3% | -34.0% | +196.7% | 24.4% | 48% |
| D9 | 1,230 | +5.5% | -6.5% | -66.0% | +348.9% | 29.1% | 45% |
| D10 | 1,230 | +9.1% | -8.7% | -96.3% | +492.4% | 42.2% | 48% |

> **Strong monotonicity:** D10 outperforms D1 by +6.4% (Win%: -21pp)

### RS_Universe_Rank
*C9 - RS Percentile (cross-sectional)*

| Decile | Count | Mean | Median | Min | Max | Std | Win% |
|--------|-------|------|--------|-----|-----|-----|------|
| D1 | 1,333 | +3.2% | +1.3% | -25.2% | +302.2% | 14.7% | 64% |
| D2 | 1,130 | +3.9% | +1.6% | -25.1% | +191.7% | 15.2% | 62% |
| D3 | 1,346 | +3.5% | +1.0% | -22.2% | +165.1% | 14.8% | 58% |
| D4 | 1,860 | +3.1% | +0.6% | -39.5% | +148.0% | 17.0% | 53% |
| D5 | 563 | +3.1% | -4.0% | -34.0% | +196.7% | 18.2% | 48% |
| D6 | 1,333 | +3.2% | -3.0% | -47.0% | +147.9% | 18.2% | 50% |
| D7 | 1,128 | +3.3% | -5.4% | -62.6% | +188.9% | 21.4% | 44% |
| D8 | 1,149 | +3.8% | -5.3% | -75.8% | +242.4% | 23.7% | 46% |
| D9 | 2,457 | +6.1% | -5.8% | -96.3% | +492.4% | 34.2% | 46% |

> **Weak monotonicity:** D10 vs D1 spread of +2.9%

### Price_vs_SMA_200
*C1-C6 - Trend Structure*

| Decile | Count | Mean | Median | Min | Max | Std | Win% |
|--------|-------|------|--------|-----|-----|-----|------|
| D1 | 1,231 | +2.9% | +1.5% | -24.6% | +101.3% | 9.6% | 71% |
| D2 | 1,230 | +3.3% | +1.5% | -19.8% | +302.2% | 14.1% | 65% |
| D3 | 1,230 | +2.3% | +0.9% | -28.5% | +78.5% | 11.8% | 57% |
| D4 | 1,230 | +2.3% | +0.3% | -39.5% | +125.4% | 14.7% | 51% |
| D5 | 1,230 | +2.4% | -4.0% | -28.0% | +108.7% | 14.8% | 48% |
| D6 | 1,230 | +3.6% | -3.9% | -34.0% | +100.1% | 17.6% | 49% |
| D7 | 1,230 | +3.3% | -5.5% | -28.0% | +348.9% | 22.6% | 45% |
| D8 | 1,230 | +4.2% | -5.9% | -62.6% | +182.6% | 23.0% | 45% |
| D9 | 1,230 | +5.9% | -7.4% | -66.0% | +492.4% | 31.0% | 44% |
| D10 | 1,230 | +9.1% | -9.7% | -96.3% | +457.7% | 41.3% | 46% |

> **Strong monotonicity:** D10 outperforms D1 by +6.2% (Win%: -25pp)

### Dist_From_52W_Low
*C7 - Distance from 52W Low*

| Decile | Count | Mean | Median | Min | Max | Std | Win% |
|--------|-------|------|--------|-----|-----|-----|------|
| D1 | 1,231 | +2.2% | +1.2% | -19.5% | +65.9% | 8.1% | 69% |
| D2 | 1,230 | +1.3% | +0.7% | -24.6% | +78.5% | 10.4% | 54% |
| D3 | 1,230 | +1.2% | -2.5% | -34.2% | +125.4% | 13.1% | 50% |
| D4 | 1,230 | +1.7% | -3.0% | -39.5% | +107.7% | 14.1% | 49% |
| D5 | 1,230 | +2.0% | -3.8% | -25.9% | +191.7% | 15.4% | 49% |
| D6 | 1,230 | +4.5% | +0.7% | -27.7% | +189.5% | 20.0% | 52% |
| D7 | 1,230 | +3.7% | -4.3% | -62.6% | +302.2% | 20.7% | 49% |
| D8 | 1,230 | +5.1% | -4.8% | -49.4% | +196.7% | 25.0% | 49% |
| D9 | 1,230 | +7.6% | +0.7% | -66.0% | +348.9% | 30.5% | 51% |
| D10 | 1,230 | +9.9% | +1.8% | -96.3% | +492.4% | 41.0% | 51% |

> **Strong monotonicity:** D10 outperforms D1 by +7.7% (Win%: -17pp)

### Vol_Ratio
*C11 - Volume Confirmation*

| Decile | Count | Mean | Median | Min | Max | Std | Win% |
|--------|-------|------|--------|-----|-----|-----|------|
| D1 | 1,231 | +5.3% | +1.9% | -45.0% | +169.6% | 18.5% | 60% |
| D2 | 1,230 | +4.5% | +1.0% | -29.6% | +492.4% | 22.5% | 58% |
| D3 | 1,230 | +4.8% | +1.4% | -43.4% | +188.9% | 19.4% | 60% |
| D4 | 1,230 | +5.9% | +1.3% | -34.6% | +236.1% | 22.7% | 57% |
| D5 | 1,230 | +3.8% | +0.5% | -38.0% | +165.1% | 18.8% | 52% |
| D6 | 1,230 | +3.6% | +0.6% | -96.3% | +182.6% | 19.6% | 52% |
| D7 | 1,230 | +4.8% | +0.7% | -32.9% | +242.4% | 23.9% | 52% |
| D8 | 1,230 | +4.5% | +0.2% | -44.2% | +457.7% | 27.5% | 50% |
| D9 | 1,230 | +1.2% | -5.8% | -62.6% | +211.8% | 21.0% | 41% |
| D10 | 1,230 | +1.0% | -7.4% | -95.3% | +244.0% | 25.7% | 39% |

> **⚠️ Inverted:** D1 outperforms D10 by +4.3%

## Executive Summary

- **Total candidates:** 242
- **Final passed:** 71
- **Regime-conditional features:** 137 (flagged for monitoring)

## Section 2: Feature Leaderboard

> **Note:** All scores are normalized 0-1 for comparability. IC (Norm) = raw Spearman IC divided by max IC in dataset.

| Rank | Feature | Composite | IC (Norm) | Stability | KS | Signal Type |
|------|---------|-----------|-----------|-----------|-----|-------------|
| 1 | `breakout_momentum` | 0.879 | 1.000 | 0.818 | 0.778 | linear_neg |
| 2 | `VCP_Ratio_Delta` | 0.838 | 0.913 | 0.798 | 0.778 | linear_neg |
| 3 | `price_momentum_curve` | 0.709 | 0.622 | 0.756 | 0.778 | linear_neg |
| 4 | `Dist_From_52W_Low_Delta` | 0.689 | 0.866 | 0.475 | 0.667 | linear_neg |
| 5 | `Dist_From_20D_Low_Delta` | 0.611 | 0.746 | 0.374 | 0.667 | linear_neg |
| 6 | `Dry_Up_Volume_Delta` | 0.609 | 0.674 | 0.465 | 0.667 | linear_neg |
| 7 | `alpha013` | 0.602 | 0.571 | 0.466 | 0.778 | linear_pos |
| 8 | `Price_vs_SMA_50` | 0.595 | 0.894 | 0.234 | 0.556 | kinked |
| 9 | `RS_Delta` | 0.588 | 0.692 | 0.369 | 0.667 | linear_neg |
| 10 | `Dist_From_52W_High_Delta` | 0.573 | 0.683 | 1.000 | 0.000 | unknown |
| 11 | `alpha101` | 0.563 | 0.684 | 0.407 | 0.556 | kinked |
| 12 | `alpha060` | 0.555 | 0.637 | 0.446 | 0.556 | kinked |
| 13 | `Price_vs_SMA_200_Delta` | 0.549 | 0.661 | 0.280 | 0.667 | linear_neg |
| 14 | `log_volume_velocity` | 0.545 | 0.589 | 0.365 | 0.667 | linear_neg |
| 15 | `Price_vs_SMA_150` | 0.526 | 0.738 | 0.212 | 0.556 | kinked |
| 16 | `High_52W_Delta` | 0.525 | 0.847 | 0.622 | 0.000 | unknown |
| 17 | `Price_vs_SMA_150_Delta` | 0.502 | 0.576 | 0.239 | 0.667 | linear_neg |
| 18 | `RSI_14` | 0.483 | 0.503 | 0.384 | 0.556 | kinked |
| 19 | `mom_63d` | 0.470 | 0.589 | 0.228 | 0.556 | kinked |
| 20 | `alpha009` | 0.470 | 0.358 | 0.312 | 0.778 | linear_pos |
| 21 | `rs_velocity` | 0.470 | 0.590 | 0.223 | 0.556 | kinked |
| 22 | `industry_id_encoded` | 0.437 | 0.228 | 0.151 | 1.000 | linear_pos |
| 23 | `Dist_From_20D_High_Delta` | 0.437 | 0.347 | 0.215 | 0.778 | linear_pos |
| 24 | `VCP_Ratio` | 0.433 | 0.431 | 0.202 | 0.667 | linear_neg |
| 25 | `price_vs_spy_ma63` | 0.396 | 0.210 | 0.151 | 0.889 | linear_neg |
| 26 | `Dry_Up_Volume` | 0.380 | 0.294 | 0.208 | 0.667 | linear_neg |
| 27 | `alpha011` | 0.380 | 0.192 | 0.120 | 0.889 | linear_pos |
| 28 | `m03_pillar_risk` | 0.373 | 0.308 | 0.054 | 0.778 | linear_neg |
| 29 | `RS_Universe_Rank` | 0.371 | 0.578 | 0.465 | 0.000 | unknown |
| 30 | `alpha054` | 0.355 | 0.261 | 0.169 | 0.667 | linear_pos |

## Section 3: Monotonicity Deep Dive

### alpha011
- **Signal Type:** linear_pos
- **D1 Mean Return:** -1.00%
- **D10 Mean Return:** +10.21%
- **Decile Returns:**
  ```
  D 1:  -1.00% |-
  D 2:  +2.66% |+++++
  D 3:  +2.90% |+++++
  D 4:  +3.42% |++++++
  D 5:  +3.97% |+++++++
  D 6:  +3.43% |++++++
  D 7:  +4.27% |++++++++
  D 8:  +4.66% |+++++++++
  D 9:  +4.71% |+++++++++
  D10: +10.21% |++++++++++++++++++++
  ```

### price_vs_spy_ma63
- **Signal Type:** linear_neg
- **D1 Mean Return:** +8.10%
- **D10 Mean Return:** +2.33%
- **Decile Returns:**
  ```
  D 1:  +8.10% |++++++++++++++++++++
  D 2:  +4.71% |+++++++++++
  D 3:  +4.68% |+++++++++++
  D 4:  +4.67% |+++++++++++
  D 5:  +3.64% |++++++++
  D 6:  +3.46% |++++++++
  D 7:  +3.17% |+++++++
  D 8:  +2.10% |+++++
  D 9:  +2.35% |+++++
  D10:  +2.33% |+++++
  ```

### breakout_momentum
- **Signal Type:** linear_neg
- **D1 Mean Return:** +6.71%
- **D10 Mean Return:** -3.82%
- **Decile Returns:**
  ```
  D 1:  +6.71% |++++++++++++++++++++
  D 2:  +5.08% |+++++++++++++++
  D 3:  +5.74% |+++++++++++++++++
  D 4:  +5.42% |++++++++++++++++
  D 5:  +5.09% |+++++++++++++++
  D 6:  +5.31% |+++++++++++++++
  D 7:  +4.28% |++++++++++++
  D 8:  +4.11% |++++++++++++
  D 9:  +1.31% |+++
  D10:  -3.82% |-----------
  ```

### m03_pillar_risk
- **Signal Type:** linear_neg
- **D1 Mean Return:** +7.42%
- **D10 Mean Return:** +1.06%
- **Decile Returns:**
  ```
  D 1:  +7.42% |++++++++++++++++++++
  D 2:  +6.32% |+++++++++++++++++
  D 3:  +5.93% |+++++++++++++++
  D 4:  +4.43% |+++++++++++
  D 5:  +2.92% |+++++++
  D 6:  +2.87% |+++++++
  D 7:  +3.19% |++++++++
  D 8:  +3.38% |+++++++++
  D 9:  +2.46% |++++++
  D10:  +1.06% |++
  ```

### log_Price_vs_SMA_50_Lag1
- **Signal Type:** linear_pos
- **D1 Mean Return:** +2.11%
- **D10 Mean Return:** +10.52%
- **Decile Returns:**
  ```
  D 1:  +2.11% |++++
  D 2:  +3.04% |+++++
  D 3:  +2.08% |+++
  D 4:  +2.24% |++++
  D 5:  +3.61% |++++++
  D 6:  +3.88% |+++++++
  D 7:  +3.52% |++++++
  D 8:  +3.90% |+++++++
  D 9:  +4.33% |++++++++
  D10: +10.52% |++++++++++++++++++++
  ```

### price_momentum_curve
- **Signal Type:** linear_neg
- **D1 Mean Return:** +6.01%
- **D10 Mean Return:** +0.19%
- **Decile Returns:**
  ```
  D 1:  +6.01% |+++++++++++++++++++
  D 2:  +6.29% |++++++++++++++++++++
  D 3:  +5.49% |+++++++++++++++++
  D 4:  +5.10% |++++++++++++++++
  D 5:  +5.09% |++++++++++++++++
  D 6:  +3.91% |++++++++++++
  D 7:  +3.22% |++++++++++
  D 8:  +1.68% |+++++
  D 9:  +2.24% |+++++++
  D10:  +0.19% |
  ```

### gross_margin
- **Signal Type:** linear_neg
- **D1 Mean Return:** +4.76%
- **D10 Mean Return:** +2.73%
- **Decile Returns:**
  ```
  D 1:  +4.76% |++++++++++++++++++++
  D 2:  +3.65% |+++++++++++++++
  D 3:  +3.17% |+++++++++++++
  D 4:  +4.24% |+++++++++++++++++
  D 5:  +3.77% |+++++++++++++++
  D 6:  +3.72% |+++++++++++++++
  D 7:  +3.53% |++++++++++++++
  D 8:  +3.53% |++++++++++++++
  D 9:  +4.58% |+++++++++++++++++++
  D10:  +2.73% |+++++++++++
  ```

### roa
- **Signal Type:** linear_neg
- **D1 Mean Return:** +7.54%
- **D10 Mean Return:** +3.93%
- **Decile Returns:**
  ```
  D 1:  +7.54% |++++++++++++++++++++
  D 2:  +5.98% |+++++++++++++++
  D 3:  +3.46% |+++++++++
  D 4:  +3.05% |++++++++
  D 5:  +2.55% |++++++
  D 6:  +3.37% |++++++++
  D 7:  +3.31% |++++++++
  D 8:  +3.02% |++++++++
  D 9:  +2.91% |+++++++
  D10:  +3.93% |++++++++++
  ```

### alpha013
- **Signal Type:** linear_pos
- **D1 Mean Return:** +0.30%
- **D10 Mean Return:** +7.30%
- **Decile Returns:**
  ```
  D 1:  +0.30% |
  D 2:  +1.37% |+++
  D 3:  +2.97% |++++++++
  D 4:  +3.96% |++++++++++
  D 5:  +3.44% |+++++++++
  D 6:  +4.36% |+++++++++++
  D 7:  +4.69% |++++++++++++
  D 8:  +4.33% |+++++++++++
  D 9:  +6.51% |+++++++++++++++++
  D10:  +7.30% |++++++++++++++++++++
  ```

### m03_regime_vol
- **Signal Type:** linear_neg
- **D1 Mean Return:** +5.35%
- **D10 Mean Return:** +3.94%
- **Decile Returns:**
  ```
  D 1:  +5.35% |+++++++++++++++++
  D 2:  +4.99% |++++++++++++++++
  D 3:  +3.49% |+++++++++++
  D 4:  +2.66% |++++++++
  D 5:  +6.20% |++++++++++++++++++++
  D 6:  +5.09% |++++++++++++++++
  D 7:  +2.95% |+++++++++
  D 8:  +2.75% |++++++++
  D 9:  +2.55% |++++++++
  D10:  +3.94% |++++++++++++
  ```

## Section 4: Stability Analysis (Per-Year IC)

| Feature | IC_2018 | IC_2019 | IC_2020 | IC_2021 | IC_2022 | IC_2023 | IC_2024 | IC_2025 | Stability | Regime? |
|---------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|
| `Dist_From_52W_High_Delta` | 0.167 | 0.144 | 0.154 | 0.123 | 0.133 | 0.118 | 0.130 | 0.164 | 8.10 | No |
| `alpha013` | 0.135 | 0.135 | 0.124 | 0.107 | 0.044 | 0.155 | 0.147 | 0.132 | 3.78 | No |
| `alpha060` | 0.158 | 0.069 | 0.141 | 0.084 | 0.153 | 0.089 | 0.147 | 0.152 | 3.61 | No |
| `alpha009` | 0.125 | 0.076 | 0.057 | 0.084 | 0.047 | 0.032 | 0.056 | 0.061 | 2.53 | No |
| `alpha046` | 0.058 | 0.053 | 0.031 | 0.066 | 0.055 | 0.024 | 0.025 | 0.088 | 2.40 | No |
| `log_turnover_ma20` | 0.038 | 0.073 | 0.014 | 0.028 | 0.094 | 0.090 | 0.103 | 0.051 | 1.96 | Yes |
| `turnover_ma20` | 0.037 | 0.073 | 0.014 | 0.028 | 0.094 | 0.090 | 0.103 | 0.051 | 1.96 | Yes |
| `Dist_From_20D_High_Delta` | 0.071 | 0.029 | 0.111 | 0.018 | 0.022 | 0.053 | 0.115 | 0.089 | 1.74 | Yes |
| `alpha015` | 0.040 | -0.004 | 0.035 | 0.039 | 0.040 | 0.017 | 0.012 | 0.047 | 1.71 | Yes |
| `operating_margin` | 0.089 | 0.082 | -0.016 | 0.058 | 0.040 | 0.039 | 0.027 | 0.080 | 1.51 | Yes |
| `alpha006` | 0.020 | -0.004 | 0.015 | 0.045 | 0.065 | 0.051 | 0.106 | 0.041 | 1.35 | Yes |
| `industry_id_encoded` | 0.010 | 0.035 | 0.130 | 0.062 | 0.059 | -0.002 | 0.049 | 0.029 | 1.23 | Yes |
| `price_vs_spy_ma63` | 0.034 | 0.018 | -0.015 | 0.005 | 0.058 | 0.047 | 0.072 | 0.067 | 1.22 | Yes |
| `roa` | 0.054 | 0.013 | -0.020 | 0.036 | 0.039 | 0.028 | 0.034 | 0.014 | 1.17 | Yes |
| `fcf_margin` | 0.048 | 0.026 | 0.000 | 0.060 | 0.022 | -0.008 | 0.032 | 0.004 | 1.04 | Yes |

### Regime-Conditional Features (High IC Variance)

These features have inconsistent IC across years. Monitor closely:

- `log_turnover_ma20`
- `turnover_ma20`
- `Dist_From_20D_High_Delta`
- `alpha015`
- `operating_margin`
- `alpha006`
- `industry_id_encoded`
- `price_vs_spy_ma63`
- `roa`
- `fcf_margin`

## Section 5: Correlation Clusters

### Cluster 66
- **Members:** `Price_vs_SMA_50`, `mom_21d`, `nATR`, `Consolidation_Width`, `Dist_From_20D_Low`, `log_Price_vs_SMA_50`, `log_mom_21d`, `log_nATR`, `log_Consolidation_Width`, `log_Dist_From_20D_Low`, `log_nATR_Lag1`, `log_Consolidation_Width_Lag1`, `log_Dist_From_20D_Low_Lag1`, `structural_stop`
- **Keep:** `Price_vs_SMA_50` (highest weighted score (IC=0.180, Stab=1.90))
- **Drop:** `log_Price_vs_SMA_50`, `mom_21d`, `log_mom_21d`, `Dist_From_20D_Low`, `log_Dist_From_20D_Low`, `Consolidation_Width`, `log_Consolidation_Width`, `nATR`, `log_nATR`, `structural_stop`, `log_Consolidation_Width_Lag1`, `log_nATR_Lag1`, `log_Dist_From_20D_Low_Lag1`

### Cluster 67
- **Members:** `Price_vs_SMA_150`, `Price_vs_SMA_200`, `rs_rating`, `RS`, `mom_126d`, `mom_189d`, `mom_252d`, `Dist_From_52W_Low`, `Sector_Momentum`, `Industry_Momentum`, `log_Price_vs_SMA_150`, `log_Price_vs_SMA_200`, `log_rs_rating`, `log_RS`, `log_RS_MA`, `log_mom_126d`, `log_mom_189d`, `log_mom_252d`, `log_Dist_From_52W_Low`, `log_Price_vs_SMA_150_Lag1`, `log_Price_vs_SMA_200_Lag1`, `log_RS_Lag1`, `log_RS_MA_Lag1`, `log_Dist_From_52W_Low_Lag1`, `log_Sector_Momentum`, `log_Industry_Momentum`
- **Keep:** `Price_vs_SMA_150` (highest weighted score (IC=0.155, Stab=1.72))
- **Drop:** `log_Price_vs_SMA_150`, `Price_vs_SMA_200`, `log_Price_vs_SMA_200`, `rs_rating`, `RS`, `log_rs_rating`, `log_RS`, `mom_189d`, `log_mom_189d`, `Industry_Momentum`, `log_Industry_Momentum`, `mom_126d`, `log_mom_126d`, `log_Dist_From_52W_Low`, `Dist_From_52W_Low`, `Sector_Momentum`, `log_Sector_Momentum`, `log_Price_vs_SMA_200_Lag1`, `log_Price_vs_SMA_150_Lag1`, `mom_252d`, `log_mom_252d`, `log_RS_Lag1`, `log_Dist_From_52W_Low_Lag1`, `log_RS_MA`, `log_RS_MA_Lag1`

### Cluster 40
- **Members:** `Vol_Ratio`, `Dry_Up_Volume_Delta`, `log_Vol_Ratio`, `log_Dry_Up_Volume_Delta`
- **Keep:** `Dry_Up_Volume_Delta` (highest weighted score (IC=0.130, Stab=3.77))
- **Drop:** `log_Dry_Up_Volume_Delta`, `Vol_Ratio`, `log_Vol_Ratio`

### Cluster 33
- **Members:** `price_vs_spy`, `price_vs_spy_ma63`, `alpha041`
- **Keep:** `price_vs_spy_ma63` (highest weighted score (IC=0.036, Stab=1.22))
- **Drop:** `alpha041`, `price_vs_spy`

### Cluster 65
- **Members:** `mom_63d`, `SMA_50_Slope`, `log_mom_63d`
- **Keep:** `mom_63d` (highest weighted score (IC=0.118, Stab=1.85))
- **Drop:** `log_mom_63d`, `SMA_50_Slope`

### Cluster 26
- **Members:** `turnover`, `turnover_ma20`
- **Keep:** `turnover_ma20` (highest weighted score (IC=0.061, Stab=1.96))
- **Drop:** `turnover`

### Cluster 27
- **Members:** `vol_ma20`, `vol_ma50`, `log_Volume`, `log_Vol_MA`, `log_turnover_ma20`, `log_vol_ma20`, `log_vol_ma50`
- **Keep:** `log_turnover_ma20` (highest weighted score (IC=0.061, Stab=1.96))
- **Drop:** `vol_ma20`, `log_vol_ma20`, `vol_ma50`, `log_Vol_MA`, `log_vol_ma50`, `log_Volume`

### Cluster 37
- **Members:** `VCP_Ratio`, `log_VCP_Ratio_Lag1`
- **Keep:** `VCP_Ratio` (highest weighted score (IC=0.076, Stab=1.63))
- **Drop:** `log_VCP_Ratio_Lag1`

### Cluster 38
- **Members:** `Dry_Up_Volume`, `log_Dry_Up_Volume`, `log_Dry_Up_Volume_Lag1`
- **Keep:** `Dry_Up_Volume` (highest weighted score (IC=0.052, Stab=1.68))
- **Drop:** `log_Dry_Up_Volume`, `log_Dry_Up_Volume_Lag1`

### Cluster 28
- **Members:** `Dist_From_52W_High`, `Dist_From_52W_High_Delta`, `log_Dist_From_52W_High`
- **Keep:** `Dist_From_52W_High_Delta` (highest weighted score (IC=0.142, Stab=8.10))
- **Drop:** `Dist_From_52W_High`, `log_Dist_From_52W_High`

## Section 6: Distributional Warnings

| Feature | Issue | Action |
|---------|-------|--------|
| `mom_63d` | Kurtosis=54.2 | Consider winsorizing at 1/99% |
| `turnover_ma20` | Kurtosis=24.4 | Consider winsorizing at 1/99% |
| `rs_velocity` | Kurtosis=1539.1 | Consider winsorizing at 1/99% |
| `price_momentum_curve` | Kurtosis=12.3 | Consider winsorizing at 1/99% |
| `price_accel_10d` | Kurtosis=10.3 | Consider winsorizing at 1/99% |
| `VCP_Ratio_Delta` | Kurtosis=58.4 | Consider winsorizing at 1/99% |
| `Price_vs_SMA_50_Delta` | Kurtosis=14.0 | Consider winsorizing at 1/99% |
| `Price_vs_SMA_150_Delta` | Kurtosis=14.8 | Consider winsorizing at 1/99% |
| `Price_vs_SMA_200_Delta` | Kurtosis=81.2 | Consider winsorizing at 1/99% |
| `RS_Delta` | Kurtosis=83.6 | Consider winsorizing at 1/99% |
| `RS_MA_Delta` | Kurtosis=683.8 | Consider winsorizing at 1/99% |
| `Dry_Up_Volume_Delta` | Kurtosis=20.3 | Consider winsorizing at 1/99% |
| `High_52W_Delta` | Kurtosis=821.3 | Consider winsorizing at 1/99% |
| `Dist_From_52W_Low_Delta` | Kurtosis=627.7 | Consider winsorizing at 1/99% |
| `Dist_From_20D_Low_Delta` | Kurtosis=23.5 | Consider winsorizing at 1/99% |
| `Dist_From_20D_High_Delta` | Kurtosis=16.1 | Consider winsorizing at 1/99% |
| `alpha001` | Kurtosis=162.3 | Consider winsorizing at 1/99% |
| `alpha004` | Kurtosis=11.7 | Consider winsorizing at 1/99% |
| `alpha060` | Kurtosis=16.9 | Consider winsorizing at 1/99% |
| `eps_stability_score` | Kurtosis=19.7 | Consider winsorizing at 1/99% |

## Section 7: Transformation Summary

> Features with high kurtosis were automatically transformed during EDA:
> - **Log Transform** (`sign(x) * log(1+|x|)`): Preserves magnitude (explosive/TAR>1.2)
> - **Winsorization** (1%/99%): Clips outliers as noise (bounded/standard/TAR<=1.2)

| Feature | Transform | Category | TAR |
|---------|-----------|----------|-----|
| `Price_vs_SMA_50` | Log | Explosive | - |
| `Price_vs_SMA_150` | Log | Explosive | - |
| `Price_vs_SMA_200` | Log | Explosive | - |
| `Vol_Ratio` | Log | Explosive | - |
| `rs_rating` | Log | TAR-based | 3.52 |
| `RS` | Log | Explosive | - |
| `mom_21d` | Log | TAR-based | 3.43 |
| `mom_63d` | Log | TAR-based | 3.07 |
| `mom_126d` | Log | TAR-based | 3.32 |
| `mom_189d` | Log | TAR-based | 3.39 |
| `mom_252d` | Log | TAR-based | 3.16 |
| `vol_ma20` | Log | TAR-based | 2.23 |
| `vol_ma50` | Log | TAR-based | 2.34 |
| `nATR` | Log | Explosive | - |
| `Consolidation_Width` | Log | TAR-based | 4.03 |
| `Dry_Up_Volume` | Log | Explosive | - |
| `Dist_From_20D_Low` | Log | TAR-based | 3.78 |
| `Dist_From_52W_Low` | Log | Explosive | - |
| `rs_velocity` | Log | TAR-based | 3.96 |
| `volume_acceleration` | Log | Explosive | - |
| `log_volume_velocity` | Log | TAR-based | 2.24 |
| `nATR_Delta` | Log | TAR-based | 1.33 |
| `ATR_Delta` | Log | TAR-based | 2.18 |
| `VCP_Ratio_Delta` | Log | TAR-based | 2.53 |
| `Consolidation_Width_Delta` | Log | TAR-based | 1.65 |
| `Price_vs_SMA_200_Delta` | Log | TAR-based | 1.83 |
| `RS_Delta` | Log | TAR-based | 1.89 |
| `RS_MA_Delta` | Log | TAR-based | 1.53 |
| `Dry_Up_Volume_Delta` | Log | TAR-based | 2.84 |
| `High_52W_Delta` | Log | TAR-based | 3.23 |
| `Lowest_Low_20D_Delta` | Log | TAR-based | 1.55 |
| `Highest_High_20D_Delta` | Log | TAR-based | 3.44 |
| `RSI_14_Delta` | Log | TAR-based | 1.33 |
| `Dist_From_52W_Low_Delta` | Log | TAR-based | 2.76 |
| `Dist_From_20D_Low_Delta` | Log | TAR-based | 1.39 |
| `alpha001` | Log | TAR-based | 2.97 |
| `alpha060` | Log | TAR-based | 2.01 |
| `revenue_growth_yoy` | Log | Explosive | - |
| `net_income_growth_yoy` | Log | TAR-based | 1.26 |
| `eps_growth_yoy` | Log | Explosive | - |
| `eps_accel` | Log | Explosive | - |
| `revenue_accel` | Log | Explosive | - |
| `revenue_cagr_3y` | Log | TAR-based | 2.07 |
| `debt_to_equity` | Log | TAR-based | 1.69 |
| `current_ratio` | Log | TAR-based | 1.40 |
| `quick_ratio` | Log | TAR-based | 1.43 |
| `fcf_margin` | Log | TAR-based | 1.39 |
| `gross_margin_trend` | Log | TAR-based | 2.03 |
| `days_since_report` | Log | TAR-based | 1.36 |
| `days_since_earnings` | Log | TAR-based | 1.36 |
| `pb_ratio` | Log | Explosive | - |
| `Sector_Momentum` | Log | TAR-based | 2.48 |
| `Industry_Momentum` | Log | TAR-based | 2.82 |
| `RS_vs_Industry` | Log | TAR-based | 1.29 |
| `log_rs_rating` | Log | TAR-based | 3.52 |
| `log_RS` | Log | TAR-based | 3.52 |
| `log_RS_MA` | Log | TAR-based | 2.62 |
| `log_mom_21d` | Log | TAR-based | 3.43 |
| `log_mom_63d` | Log | TAR-based | 3.07 |
| `log_mom_126d` | Log | TAR-based | 3.32 |
| `log_mom_189d` | Log | TAR-based | 3.39 |
| `log_mom_252d` | Log | TAR-based | 3.16 |
| `log_Dist_From_20D_Low` | Log | TAR-based | 3.78 |
| `log_Dist_From_52W_Low` | Log | TAR-based | 3.31 |
| `log_rs_velocity` | Log | TAR-based | 3.96 |
| `log_RS_Lag1` | Log | TAR-based | 2.66 |
| `log_RS_MA_Lag1` | Log | TAR-based | 2.62 |
| `log_Dist_From_52W_Low_Lag1` | Log | TAR-based | 2.79 |
| `log_Dist_From_20D_Low_Lag1` | Log | TAR-based | 2.78 |
| `log_nATR_Delta` | Log | TAR-based | 1.33 |
| `log_ATR_Delta` | Log | TAR-based | 2.18 |
| `log_VCP_Ratio_Delta` | Log | TAR-based | 2.53 |
| `log_Price_vs_SMA_200_Delta` | Log | TAR-based | 1.83 |
| `log_RS_Delta` | Log | TAR-based | 1.89 |
| `log_RS_MA_Delta` | Log | TAR-based | 1.53 |
| `log_Dry_Up_Volume_Delta` | Log | TAR-based | 2.84 |
| `log_High_52W_Delta` | Log | TAR-based | 3.23 |
| `log_Lowest_Low_20D_Delta` | Log | TAR-based | 1.55 |
| `log_Highest_High_20D_Delta` | Log | TAR-based | 3.44 |
| `log_Dist_From_52W_Low_Delta` | Log | TAR-based | 2.76 |
| `log_Dist_From_20D_Low_Delta` | Log | TAR-based | 1.39 |
| `log_alpha001` | Log | TAR-based | 2.97 |
| `log_alpha060` | Log | TAR-based | 2.01 |
| `log_debt_to_equity` | Log | TAR-based | 1.69 |
| `log_current_ratio` | Log | TAR-based | 1.40 |
| `log_quick_ratio` | Log | TAR-based | 1.43 |
| `log_Sector_Momentum` | Log | TAR-based | 2.48 |
| `log_Industry_Momentum` | Log | TAR-based | 2.82 |
| `log_RS_vs_Industry` | Log | TAR-based | 1.29 |
| `price_vs_spy` | Winsorize | TAR-based | 0.73 |
| `price_vs_spy_ma63` | Winsorize | TAR-based | 0.71 |
| `turnover` | Winsorize | TAR-based | 1.16 |
| `turnover_ma20` | Winsorize | TAR-based | 1.20 |
| `consolidation_duration` | Winsorize | TAR-based | 1.17 |
| `price_momentum_curve` | Winsorize | TAR-based | 1.16 |
| `immediate_thrust` | Winsorize | TAR-based | 1.16 |
| `price_accel_10d` | Winsorize | TAR-based | 1.00 |
| `Price_vs_SMA_50_Delta` | Winsorize | TAR-based | 0.98 |
| `Price_vs_SMA_150_Delta` | Winsorize | TAR-based | 1.02 |
| `Low_52W_Delta` | Winsorize | TAR-based | 0.96 |
| `Dist_From_20D_High_Delta` | Winsorize | TAR-based | 1.03 |
| `alpha009` | Winsorize | TAR-based | 1.09 |
| `alpha004` | Winsorize | TAR-based | 0.87 |
| `eps_stability_score` | Winsorize | TAR-based | 1.11 |
| `operating_margin` | Winsorize | Standard | - |
| `roe` | Winsorize | Standard | - |
| `net_margin` | Winsorize | Standard | - |
| `inventory_growth_yoy` | Winsorize | TAR-based | 0.97 |
| `inventory_vs_sales_spread` | Winsorize | TAR-based | 0.98 |
| `earnings_quality_score` | Winsorize | Bounded | - |
| `log_Low_52W_Delta` | Winsorize | TAR-based | 0.96 |

**Total:** 89 log-transformed, 22 winsorized

> **TAR (Tail Alpha Ratio):** Ratio of mean |return| in 99-100th percentile vs 10-90th percentile.
> TAR > 1.2 suggests tail values are predictive (log transform); TAR <= 1.2 suggests noise (winsorize).

## Recommended Feature List

Copy this to `src/feature_config.py` → `M01_FEATURES` after review:

> **Note:** Features with `log_` prefix are log-transformed during preprocessing.
> The preprocessor will apply these transforms automatically at training/inference.

```python
M01_FEATURES = [
    'breakout_momentum',
    'log_VCP_Ratio_Delta',  # log-transformed
    'price_momentum_curve',
    'log_Dist_From_52W_Low_Delta',  # log-transformed
    'log_Dist_From_20D_Low_Delta',  # log-transformed
    'log_Dry_Up_Volume_Delta',  # log-transformed
    'alpha013',
    'log_Price_vs_SMA_50',  # log-transformed
    'log_RS_Delta',  # log-transformed
    'Dist_From_52W_High_Delta',
    'alpha101',
    'log_alpha060',  # log-transformed
    'log_Price_vs_SMA_200_Delta',  # log-transformed
    'log_volume_velocity',  # already log-transformed
    'log_Price_vs_SMA_150',  # log-transformed
    'log_High_52W_Delta',  # log-transformed
    'Price_vs_SMA_150_Delta',
    'RSI_14',
    'log_mom_63d',  # log-transformed
    'alpha009',
    'log_rs_velocity',  # log-transformed
    'industry_id_encoded',
    'Dist_From_20D_High_Delta',
    'VCP_Ratio',
    'price_vs_spy_ma63',
    'log_Dry_Up_Volume',  # log-transformed
    'alpha011',
    'm03_pillar_risk',
    'RS_Universe_Rank',
    'alpha054',
    'operating_margin',
    'Price_vs_SMA_50_Delta',
    'alpha006',
    'log_turnover_ma20',
    'turnover_ma20',
    'log_volume_acceleration',  # log-transformed
    'roa',
    'alpha002',
    'alpha015',
    'm03_regime_vol',
    'log_Price_vs_SMA_50_Lag1',
    'price_accel_10d',
    'log_alpha001',  # log-transformed
    'log_current_ratio',  # log-transformed
    'log_RS_MA_Delta',  # log-transformed
    'log_fcf_margin',  # log-transformed
    'log_gross_margin_trend',  # log-transformed
    'log_eps_growth_yoy',  # log-transformed
    'log_days_since_report',  # log-transformed
    'log_pe_ratio',
    'm03_delta_20d',
    'roe',
    'alpha004',
    'gross_margin',
    'log_debt_to_equity',  # log-transformed
    'm03_pillar_liq',
    'log_eps_accel',  # log-transformed
    'eps_stability_score',
    'log_revenue_accel',  # log-transformed
    'RS_vs_Sector',
    'log_pb_ratio',  # log-transformed
    'earnings_quality_score',
    'inventory_growth_yoy',
    'm03_pillar_trend',
    'alpha046',
    'log_revenue_growth_yoy',  # log-transformed
    'm03_score',
    'log_revenue_cagr_3y',  # log-transformed
    'ps_ratio',
    'm03_delta_5d',
    'log_RS_vs_Industry',  # log-transformed
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