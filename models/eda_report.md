# Feature Evaluation Report (Quant-Standard)

**Generated:** 2026-02-09 00:09:52
**Target Variable:** `return_pct`
**Composite Weights:** 40% IC + 30% Stability + 30% KS
**Correlation Threshold:** 0.7

---

## Section 0: Dataset Overview

### Target Variable Distribution (`return_pct`)

| Statistic | Value |
|-----------|-------|
| Count | 20,556 |
| Mean | +1.49% |
| Std Dev | 15.99% |
| Min | -95.31% |
| Max | +516.56% |
| Median | -2.11% |
| Q1 (25%) | -5.89% |
| Q3 (75%) | +4.36% |
| Skewness | +6.48 |
| Kurtosis | 108.4 |

| Outcome | Count | % |
|---------|-------|---|
| Positive (> 0%) | 7,658 | 37.3% |
| > +10% | 3,225 | 15.7% |
| > +20% | 1,547 | 7.5% |
| Negative (< 0%) | 12,871 | 62.6% |
| < -10% | 1,813 | 8.8% |

### Return Distribution (5% Buckets)

| Bucket | Count | % | Bar |
|--------|-------|---|-----|
| < -50% | 4 | 0.0% |  |
| [-50, -45)% | 3 | 0.0% |  |
| [-45, -40)% | 4 | 0.0% |  |
| [-40, -35)% | 3 | 0.0% |  |
| [-35, -30)% | 15 | 0.1% |  |
| [-30, -25)% | 29 | 0.1% |  |
| [-25, -20)% | 78 | 0.4% |  |
| [-20, -15)% | 460 | 2.2% | █ |
| [-15, -10)% | 1,217 | 5.9% | ███ |
| [-10, -5)% | 4,422 | 21.5% | █████████████ |
| [-5, 0)% | 6,637 | 32.3% | ████████████████████ |
| [0, 5)% | 2,842 | 13.8% | ████████ |
| [5, 10)% | 1,617 | 7.9% | ████ |
| [10, 15)% | 1,036 | 5.0% | ███ |
| [15, 20)% | 641 | 3.1% | █ |
| [20, 25)% | 395 | 1.9% | █ |
| [25, 30)% | 310 | 1.5% |  |
| [30, 35)% | 188 | 0.9% |  |
| [35, 40)% | 153 | 0.7% |  |
| [40, 45)% | 117 | 0.6% |  |
| [45, 50)% | 85 | 0.4% |  |
| >= 50% | 300 | 1.5% |  |

### Holding Period (`days_held`)

| Statistic | Value |
|-----------|-------|
| Mean | 46.5 days |
| Std Dev | 40.6 days |
| Min | 1 days |
| Max | 403 days |
| Median | 37.0 days |

### Temporal Coverage

- **Date Range:** 2010-01-04 to 2025-12-31
- **Unique Entry Dates:** 3,487

| Year | Samples | % |
|------|---------|---|
| 2010 | 1,318 | 6.4% |
| 2011 | 1,012 | 4.9% |
| 2012 | 990 | 4.8% |
| 2013 | 1,866 | 9.1% |
| 2014 | 1,091 | 5.3% |
| 2015 | 966 | 4.7% |
| 2016 | 1,214 | 5.9% |
| 2017 | 1,450 | 7.1% |
| 2018 | 1,161 | 5.6% |
| 2019 | 1,136 | 5.5% |
| 2020 | 1,121 | 5.5% |
| 2021 | 2,026 | 9.9% |
| 2022 | 598 | 2.9% |
| 2023 | 1,390 | 6.8% |
| 2024 | 1,969 | 9.6% |
| 2025 | 1,248 | 6.1% |

### Ticker Distribution

- **Unique Tickers:** 1,702
- **Top 10 Concentration:** 1.4% of samples

| Ticker | Samples |
|--------|---------|
| DECK | 30 |
| MPWR | 29 |
| NFLX | 29 |
| LRCX | 29 |
| ULTA | 28 |
| TDG | 28 |
| ZBRA | 28 |
| FISV | 27 |
| FICO | 27 |
| WAB | 27 |

### Sector Distribution

| Sector | Samples | % |
|--------|---------|---|
| Industrials | 3,672 | 17.9% |
| Technology | 3,506 | 17.1% |
| Financial Services | 3,166 | 15.4% |
| Healthcare | 2,829 | 13.8% |
| Consumer Cyclical | 2,478 | 12.1% |
| Energy | 1,013 | 4.9% |
| Real Estate | 961 | 4.7% |
| Consumer Defensive | 934 | 4.5% |
| Basic Materials | 859 | 4.2% |
| Communication Services | 615 | 3.0% |
| Utilities | 523 | 2.5% |

### Top 15 Industries

| Industry | Samples | % |
|----------|---------|---|
| Banks - Regional | 1,167 | 5.7% |
| Biotechnology | 841 | 4.1% |
| Semiconductors | 803 | 3.9% |
| Software - Application | 749 | 3.6% |
| Industrial - Machinery | 660 | 3.2% |
| Software - Infrastructure | 543 | 2.6% |
| Hardware, Equipment & Parts | 483 | 2.3% |
| Aerospace & Defense | 471 | 2.3% |
| Chemicals - Specialty | 417 | 2.0% |
| Asset Management | 414 | 2.0% |
| Medical - Devices | 411 | 2.0% |
| Engineering & Construction | 343 | 1.7% |
| Medical - Instruments & Supplies | 341 | 1.7% |
| Financial - Capital Markets | 324 | 1.6% |
| Specialty Retail | 310 | 1.5% |

## Section 1: SEPA Audit (Entry Criteria Validation)

> **Purpose:** Validate SEPA C1-C11 criteria effectiveness by examining
> how key entry features relate to trade outcomes across deciles.

### rs_rating
*C9 - Relative Strength (core ranking)*

| Decile | Count | Mean | Median | Min | Max | Std | Win% |
|--------|-------|------|--------|-----|-----|-----|------|
| D1 | 2,056 | +0.8% | -1.3% | -21.3% | +75.6% | 8.4% | 35% |
| D2 | 2,056 | +0.8% | -1.6% | -25.9% | +94.3% | 9.2% | 34% |
| D3 | 2,055 | +1.0% | -1.7% | -23.0% | +302.2% | 11.8% | 35% |
| D4 | 2,056 | +0.7% | -2.2% | -37.6% | +82.8% | 9.9% | 36% |
| D5 | 2,055 | +0.9% | -2.4% | -23.5% | +141.3% | 11.7% | 37% |
| D6 | 2,056 | +1.4% | -2.5% | -31.0% | +293.4% | 15.6% | 38% |
| D7 | 2,055 | +1.5% | -2.8% | -34.4% | +141.2% | 14.8% | 38% |
| D8 | 2,056 | +2.0% | -2.9% | -43.5% | +165.3% | 16.2% | 40% |
| D9 | 2,055 | +1.7% | -3.5% | -62.1% | +279.8% | 18.7% | 38% |
| D10 | 2,056 | +4.0% | -4.7% | -95.3% | +516.6% | 30.7% | 40% |

> **Weak monotonicity:** D10 vs D1 spread of +3.2%

### RS_Universe_Rank
*C9 - RS Percentile (cross-sectional)*

| Decile | Count | Mean | Median | Min | Max | Std | Win% |
|--------|-------|------|--------|-----|-----|-----|------|
| D1 | 2,056 | +1.0% | -1.5% | -20.5% | +302.2% | 11.7% | 35% |
| D2 | 2,232 | +1.2% | -1.5% | -34.4% | +143.0% | 10.6% | 37% |
| D3 | 1,896 | +0.7% | -1.9% | -25.0% | +121.9% | 10.2% | 35% |
| D4 | 3,158 | +1.5% | -1.9% | -30.3% | +293.4% | 13.7% | 36% |
| D5 | 960 | +1.2% | -2.3% | -20.4% | +214.0% | 14.2% | 38% |
| D6 | 2,113 | +1.1% | -2.4% | -44.1% | +139.5% | 13.8% | 37% |
| D7 | 2,394 | +1.3% | -3.0% | -62.0% | +165.3% | 15.2% | 38% |
| D8 | 1,711 | +2.0% | -2.9% | -48.2% | +273.6% | 18.9% | 39% |
| D9 | 4,036 | +2.4% | -3.0% | -95.3% | +516.6% | 23.2% | 39% |

> **Weak monotonicity:** D10 vs D1 spread of +1.4%

### Price_vs_SMA_200
*C1-C6 - Trend Structure*

| Decile | Count | Mean | Median | Min | Max | Std | Win% |
|--------|-------|------|--------|-----|-----|-----|------|
| D1 | 2,056 | +0.5% | -1.2% | -15.2% | +80.1% | 7.2% | 36% |
| D2 | 2,056 | +0.8% | -1.5% | -18.2% | +94.3% | 8.9% | 35% |
| D3 | 2,055 | +1.0% | -1.8% | -24.5% | +302.2% | 11.6% | 34% |
| D4 | 2,056 | +0.7% | -2.2% | -27.5% | +141.3% | 10.7% | 35% |
| D5 | 2,055 | +0.9% | -2.6% | -37.6% | +121.4% | 11.7% | 36% |
| D6 | 2,056 | +1.3% | -2.3% | -25.9% | +95.6% | 12.4% | 40% |
| D7 | 2,055 | +1.6% | -2.6% | -41.6% | +197.0% | 14.4% | 40% |
| D8 | 2,056 | +1.6% | -3.4% | -27.6% | +293.4% | 18.4% | 37% |
| D9 | 2,055 | +2.5% | -3.4% | -62.1% | +229.1% | 20.0% | 40% |
| D10 | 2,056 | +4.0% | -4.6% | -95.3% | +516.6% | 30.5% | 40% |

> **Weak monotonicity:** D10 vs D1 spread of +3.5%

### Dist_From_52W_Low
*C7 - Distance from 52W Low*

| Decile | Count | Mean | Median | Min | Max | Std | Win% |
|--------|-------|------|--------|-----|-----|-----|------|
| D1 | 2,056 | +0.4% | -1.3% | -10.7% | +69.8% | 6.3% | 26% |
| D2 | 2,056 | +0.8% | -1.9% | -16.6% | +68.7% | 8.4% | 38% |
| D3 | 2,055 | +0.6% | -2.1% | -24.5% | +121.9% | 10.2% | 37% |
| D4 | 2,056 | +0.1% | -2.5% | -31.0% | +70.9% | 9.5% | 36% |
| D5 | 2,055 | +1.1% | -2.4% | -37.6% | +214.0% | 13.2% | 38% |
| D6 | 2,056 | +1.2% | -2.6% | -27.1% | +139.5% | 12.9% | 38% |
| D7 | 2,055 | +1.9% | -2.8% | -27.7% | +197.0% | 16.1% | 39% |
| D8 | 2,056 | +2.2% | -2.9% | -62.0% | +302.2% | 18.8% | 39% |
| D9 | 2,055 | +2.6% | -2.9% | -43.5% | +279.8% | 20.1% | 41% |
| D10 | 2,056 | +3.9% | -4.2% | -95.3% | +516.6% | 29.8% | 41% |

> **Weak monotonicity:** D10 vs D1 spread of +3.5%

### Vol_Ratio
*C11 - Volume Confirmation*

| Decile | Count | Mean | Median | Min | Max | Std | Win% |
|--------|-------|------|--------|-----|-----|-----|------|
| D1 | 2,056 | +0.7% | -2.3% | -34.2% | +165.3% | 12.1% | 35% |
| D2 | 2,056 | +1.1% | -2.0% | -41.6% | +197.0% | 13.5% | 36% |
| D3 | 2,055 | +1.0% | -2.0% | -28.0% | +214.0% | 13.5% | 35% |
| D4 | 2,056 | +1.5% | -2.1% | -32.6% | +315.3% | 15.6% | 36% |
| D5 | 2,055 | +1.0% | -2.2% | -31.0% | +150.4% | 13.3% | 35% |
| D6 | 2,056 | +1.4% | -2.1% | -62.1% | +140.5% | 14.7% | 37% |
| D7 | 2,055 | +1.4% | -2.3% | -34.4% | +165.6% | 15.3% | 38% |
| D8 | 2,056 | +2.3% | -2.1% | -36.0% | +334.3% | 21.0% | 38% |
| D9 | 2,055 | +1.4% | -2.2% | -62.0% | +143.0% | 14.7% | 38% |
| D10 | 2,056 | +3.1% | -1.6% | -95.3% | +516.6% | 22.7% | 44% |

> **Weak monotonicity:** D10 vs D1 spread of +2.4%

## Executive Summary

- **Total candidates:** 207
- **Final passed:** 70
- **Regime-conditional features:** 162 (flagged for monitoring)

## Section 2: Feature Leaderboard

> **Note:** All scores are normalized 0-1 for comparability. IC (Norm) = raw Spearman IC divided by max IC in dataset.

| Rank | Feature | Composite | IC (Norm) | Stability | KS | Signal Type |
|------|---------|-----------|-----------|-----------|-----|-------------|
| 1 | `alpha011` | 0.837 | 0.759 | 1.000 | 0.778 | linear_pos |
| 2 | `rs_rating` | 0.806 | 0.977 | 0.607 | 0.778 | linear_pos |
| 3 | `Price_vs_SMA_200` | 0.798 | 1.000 | 0.550 | 0.778 | linear_pos |
| 4 | `log_nATR_Lag1` | 0.726 | 0.925 | 0.409 | 0.778 | linear_pos |
| 5 | `alpha013` | 0.702 | 0.729 | 0.701 | 0.667 | linear_pos |
| 6 | `mom_63d` | 0.566 | 0.664 | 0.447 | 0.556 | kinked |
| 7 | `RS_Universe_Rank` | 0.525 | 0.733 | 0.774 | 0.000 | unknown |
| 8 | `m03_pillar_risk` | 0.471 | 0.353 | 0.433 | 0.667 | linear_neg |
| 9 | `log_Price_vs_SMA_50_Lag1` | 0.462 | 0.513 | 0.299 | 0.556 | kinked |
| 10 | `operating_margin` | 0.447 | 0.400 | 0.402 | 0.556 | kinked |
| 11 | `alpha060` | 0.435 | 0.398 | 0.364 | 0.556 | kinked |
| 12 | `alpha012` | 0.424 | 0.352 | 0.276 | 0.667 | linear_pos |
| 13 | `m03_pillar_trend` | 0.423 | 0.375 | 0.243 | 0.667 | linear_pos |
| 14 | `eps_stability_score` | 0.421 | 0.392 | 0.323 | 0.556 | kinked |
| 15 | `current_ratio` | 0.420 | 0.353 | 0.376 | 0.556 | kinked |
| 16 | `Highest_High_20D_Delta` | 0.410 | 0.436 | 0.231 | 0.556 | kinked |
| 17 | `debt_to_equity` | 0.393 | 0.268 | 0.397 | 0.556 | kinked |
| 18 | `roa` | 0.391 | 0.266 | 0.283 | 0.667 | linear_neg |
| 19 | `nATR_Delta` | 0.388 | 0.302 | 0.223 | 0.667 | linear_neg |
| 20 | `alpha001` | 0.381 | 0.283 | 0.336 | 0.556 | kinked |
| 21 | `fcf_margin` | 0.378 | 0.257 | 0.361 | 0.556 | kinked |
| 22 | `roe` | 0.372 | 0.270 | 0.323 | 0.556 | kinked |
| 23 | `alpha101` | 0.372 | 0.245 | 0.357 | 0.556 | kinked |
| 24 | `days_since_report` | 0.369 | 0.227 | 0.151 | 0.778 | linear_neg |
| 25 | `alpha054` | 0.367 | 0.211 | 0.164 | 0.778 | linear_pos |
| 26 | `ps_ratio` | 0.367 | 0.236 | 0.242 | 0.667 | linear_neg |
| 27 | `m03_pillar_liq` | 0.337 | 0.272 | 0.095 | 0.667 | linear_pos |
| 28 | `price_momentum_curve` | 0.332 | 0.203 | 0.171 | 0.667 | linear_neg |
| 29 | `earnings_quality_score` | 0.331 | 0.159 | 0.223 | 0.667 | linear_pos |
| 30 | `pb_ratio` | 0.326 | 0.185 | 0.174 | 0.667 | linear_neg |

## Section 3: Monotonicity Deep Dive

### alpha041
- **Signal Type:** linear_neg
- **D1 Mean Return:** +5.46%
- **D10 Mean Return:** +0.14%
- **Decile Returns:**
  ```
  D 1:  +5.46% |++++++++++++++++++++
  D 2:  +2.33% |++++++++
  D 3:  +1.62% |+++++
  D 4:  +1.18% |++++
  D 5:  +1.49% |+++++
  D 6:  +0.71% |++
  D 7:  +0.88% |+++
  D 8:  +0.80% |++
  D 9:  +0.32% |+
  D10:  +0.14% |
  ```

### alpha054
- **Signal Type:** linear_pos
- **D1 Mean Return:** +0.36%
- **D10 Mean Return:** +2.84%
- **Decile Returns:**
  ```
  D 1:  +0.36% |++
  D 2:  +0.78% |+++++
  D 3:  +0.74% |+++++
  D 4:  +1.74% |++++++++++++
  D 5:  +1.22% |++++++++
  D 6:  +1.41% |+++++++++
  D 7:  +1.74% |++++++++++++
  D 8:  +2.00% |++++++++++++++
  D 9:  +2.11% |++++++++++++++
  D10:  +2.84% |++++++++++++++++++++
  ```

### Price_vs_SMA_200
- **Signal Type:** linear_pos
- **D1 Mean Return:** +0.51%
- **D10 Mean Return:** +4.03%
- **Decile Returns:**
  ```
  D 1:  +0.51% |++
  D 2:  +0.83% |++++
  D 3:  +1.00% |++++
  D 4:  +0.67% |+++
  D 5:  +0.87% |++++
  D 6:  +1.32% |++++++
  D 7:  +1.63% |++++++++
  D 8:  +1.59% |+++++++
  D 9:  +2.48% |++++++++++++
  D10:  +4.03% |++++++++++++++++++++
  ```

### rs_rating
- **Signal Type:** linear_pos
- **D1 Mean Return:** +0.83%
- **D10 Mean Return:** +4.03%
- **Decile Returns:**
  ```
  D 1:  +0.83% |++++
  D 2:  +0.84% |++++
  D 3:  +1.03% |+++++
  D 4:  +0.68% |+++
  D 5:  +0.86% |++++
  D 6:  +1.42% |+++++++
  D 7:  +1.54% |+++++++
  D 8:  +2.04% |++++++++++
  D 9:  +1.67% |++++++++
  D10:  +4.03% |++++++++++++++++++++
  ```

### m03_delta_20d
- **Signal Type:** linear_neg
- **D1 Mean Return:** +1.41%
- **D10 Mean Return:** +1.28%
- **Decile Returns:**
  ```
  D 1:  +1.41% |++++++++
  D 2:  +1.31% |++++++++
  D 3:  +0.86% |+++++
  D 4:  +3.18% |++++++++++++++++++++
  D 5:  +1.97% |++++++++++++
  D 6:  +1.72% |++++++++++
  D 7:  +1.46% |+++++++++
  D 8:  +1.26% |+++++++
  D 9:  +1.47% |+++++++++
  D10:  +1.28% |++++++++
  ```

### log_nATR_Lag1
- **Signal Type:** linear_pos
- **D1 Mean Return:** +0.43%
- **D10 Mean Return:** +3.90%
- **Decile Returns:**
  ```
  D 1:  +0.43% |++
  D 2:  +0.15% |
  D 3:  +1.00% |+++++
  D 4:  +1.16% |+++++
  D 5:  +0.67% |+++
  D 6:  +1.04% |+++++
  D 7:  +1.67% |++++++++
  D 8:  +2.10% |++++++++++
  D 9:  +2.82% |++++++++++++++
  D10:  +3.90% |++++++++++++++++++++
  ```

### pe_ratio
- **Signal Type:** linear_neg
- **D1 Mean Return:** +2.90%
- **D10 Mean Return:** +0.76%
- **Decile Returns:**
  ```
  D 1:  +2.90% |+++++++++++++++++
  D 2:  +3.31% |++++++++++++++++++++
  D 3:  +2.13% |++++++++++++
  D 4:  +1.23% |+++++++
  D 5:  +1.12% |++++++
  D 6:  +1.04% |++++++
  D 7:  +0.97% |+++++
  D 8:  +0.89% |+++++
  D 9:  +0.61% |+++
  D10:  +0.76% |++++
  ```

### alpha011
- **Signal Type:** linear_pos
- **D1 Mean Return:** -2.02%
- **D10 Mean Return:** +5.35%
- **Decile Returns:**
  ```
  D 1:  -2.02% |-------
  D 2:  +0.36% |+
  D 3:  +0.69% |++
  D 4:  +1.14% |++++
  D 5:  +1.54% |+++++
  D 6:  +1.06% |+++
  D 7:  +1.90% |+++++++
  D 8:  +1.69% |++++++
  D 9:  +3.22% |++++++++++++
  D10:  +5.35% |++++++++++++++++++++
  ```
  > **M02 Warning:** D1 has negative avg return (-2.02%)

### days_since_report
- **Signal Type:** linear_neg
- **D1 Mean Return:** +2.22%
- **D10 Mean Return:** +0.95%
- **Decile Returns:**
  ```
  D 1:  +2.22% |++++++++++++++++++
  D 2:  +2.12% |+++++++++++++++++
  D 3:  +1.24% |++++++++++
  D 4:  +2.36% |++++++++++++++++++++
  D 5:  +1.41% |+++++++++++
  D 6:  +1.13% |+++++++++
  D 7:  +1.41% |+++++++++++
  D 8:  +1.03% |++++++++
  D 9:  +0.96% |++++++++
  D10:  +0.95% |++++++++
  ```

### Price_vs_SMA_200_Delta
- **Signal Type:** linear_pos
- **D1 Mean Return:** +1.57%
- **D10 Mean Return:** +2.53%
- **Decile Returns:**
  ```
  D 1:  +1.57% |++++++++++++
  D 2:  +1.30% |++++++++++
  D 3:  +0.97% |+++++++
  D 4:  +1.07% |++++++++
  D 5:  +1.26% |+++++++++
  D 6:  +0.60% |++++
  D 7:  +1.63% |++++++++++++
  D 8:  +1.96% |+++++++++++++++
  D 9:  +2.07% |++++++++++++++++
  D10:  +2.53% |++++++++++++++++++++
  ```

## Section 4: Stability Analysis (Per-Year IC)

| Feature | IC_2010 | IC_2011 | IC_2012 | IC_2013 | IC_2014 | IC_2015 | IC_2016 | IC_2017 | IC_2018 | IC_2019 | IC_2020 | IC_2021 | IC_2022 | IC_2023 | IC_2024 | IC_2025 | Stability | Regime? |
|---------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|
| `alpha011` | 0.108 | 0.063 | 0.010 | 0.092 | 0.013 | 0.088 | 0.091 | 0.110 | 0.049 | 0.100 | 0.112 | 0.104 | 0.058 | 0.047 | 0.118 | 0.073 | 2.33 | No |
| `alpha013` | 0.132 | 0.094 | 0.136 | 0.155 | 0.107 | 0.097 | -0.063 | 0.193 | 0.066 | 0.088 | 0.077 | 0.003 | 0.092 | 0.114 | 0.100 | 0.088 | 1.63 | Yes |
| `operating_margin` | 0.005 | 0.058 | 0.063 | 0.006 | 0.090 | 0.068 | 0.119 | 0.039 | 0.061 | 0.089 | -0.063 | 0.135 | -0.044 | 0.061 | 0.036 | 0.041 | 0.94 | Yes |
| `debt_to_equity` | 0.001 | 0.038 | 0.092 | -0.010 | 0.032 | 0.029 | 0.032 | 0.039 | -0.021 | 0.042 | -0.038 | 0.024 | 0.056 | 0.048 | 0.071 | 0.093 | 0.92 | Yes |
| `alpha060` | 0.030 | 0.071 | -0.036 | 0.014 | 0.089 | 0.059 | 0.010 | 0.011 | 0.071 | -0.034 | -0.006 | 0.034 | 0.171 | 0.068 | 0.050 | 0.074 | 0.85 | Yes |
| `fcf_margin` | 0.044 | 0.031 | 0.057 | 0.016 | 0.020 | 0.056 | 0.053 | 0.074 | 0.040 | 0.060 | -0.020 | 0.095 | -0.034 | 0.045 | 0.045 | -0.058 | 0.84 | Yes |
| `roe` | 0.077 | 0.005 | 0.024 | 0.001 | 0.101 | 0.030 | 0.020 | 0.078 | 0.071 | 0.041 | -0.084 | 0.089 | 0.016 | 0.037 | 0.069 | -0.020 | 0.75 | Yes |
| `alpha015` | 0.029 | 0.025 | 0.030 | 0.047 | -0.003 | 0.016 | -0.042 | 0.042 | 0.048 | -0.001 | -0.004 | -0.022 | 0.054 | 0.030 | -0.001 | 0.056 | 0.68 | Yes |
| `roa` | 0.069 | 0.052 | 0.030 | -0.008 | 0.136 | 0.026 | -0.058 | 0.094 | 0.086 | 0.038 | -0.053 | 0.075 | -0.016 | 0.071 | 0.058 | -0.031 | 0.66 | Yes |
| `alpha012` | 0.099 | 0.040 | 0.037 | 0.004 | 0.042 | 0.034 | -0.046 | 0.040 | 0.003 | -0.026 | -0.004 | 0.072 | 0.116 | -0.045 | 0.044 | 0.051 | 0.64 | Yes |
| `earnings_quality_score` | -0.024 | 0.020 | 0.014 | -0.015 | 0.047 | 0.043 | 0.018 | -0.013 | 0.025 | 0.041 | -0.036 | 0.044 | -0.010 | 0.050 | 0.029 | -0.006 | 0.52 | Yes |
| `nATR_Delta` | -0.018 | 0.039 | 0.033 | 0.055 | -0.017 | 0.051 | 0.178 | 0.007 | 0.099 | -0.011 | -0.110 | 0.030 | 0.083 | 0.087 | -0.002 | 0.010 | 0.52 | Yes |
| `log_Dry_Up_Volume_Lag1` | 0.016 | 0.046 | 0.022 | 0.095 | 0.058 | 0.103 | -0.024 | 0.003 | 0.044 | -0.016 | -0.027 | -0.006 | 0.078 | -0.007 | 0.001 | -0.044 | 0.49 | Yes |
| `peg_adjusted` | -0.001 | 0.095 | 0.010 | 0.020 | 0.011 | 0.018 | 0.040 | -0.015 | 0.003 | 0.109 | -0.094 | 0.072 | 0.021 | 0.082 | 0.012 | -0.017 | 0.48 | Yes |
| `Dist_From_20D_High_Delta` | 0.028 | 0.035 | -0.009 | 0.037 | 0.044 | -0.032 | 0.015 | -0.022 | 0.003 | -0.020 | -0.001 | 0.010 | -0.006 | -0.018 | 0.043 | 0.056 | 0.39 | Yes |

### Regime-Conditional Features (High IC Variance)

These features have inconsistent IC across years. Monitor closely:

- `alpha013`
- `operating_margin`
- `debt_to_equity`
- `alpha060`
- `fcf_margin`
- `roe`
- `alpha015`
- `roa`
- `alpha012`
- `earnings_quality_score`

## Section 5: Correlation Clusters

### Cluster 45
- **Members:** `Price_vs_SMA_50`, `mom_21d`, `nATR`, `Consolidation_Width`, `Dist_From_20D_Low`, `log_Price_vs_SMA_50`, `log_nATR`, `log_Consolidation_Width`, `log_Dist_From_20D_Low`, `log_nATR_Lag1`, `log_Consolidation_Width_Lag1`, `log_Dist_From_20D_Low_Lag1`
- **Keep:** `log_nATR_Lag1` (highest weighted score (IC=0.090, Stab=0.95))
- **Drop:** `log_Consolidation_Width_Lag1`, `nATR`, `log_nATR`, `Dist_From_20D_Low`, `log_Dist_From_20D_Low`, `log_Dist_From_20D_Low_Lag1`, `Consolidation_Width`, `log_Consolidation_Width`, `Price_vs_SMA_50`, `log_Price_vs_SMA_50`, `mom_21d`

### Cluster 46
- **Members:** `Price_vs_SMA_150`, `Price_vs_SMA_200`, `mom_126d`, `log_Price_vs_SMA_150`, `log_Price_vs_SMA_200`, `log_Price_vs_SMA_150_Lag1`, `log_Price_vs_SMA_200_Lag1`
- **Keep:** `Price_vs_SMA_200` (highest weighted score (IC=0.116, Stab=1.28))
- **Drop:** `log_Price_vs_SMA_200`, `log_Price_vs_SMA_200_Lag1`, `Price_vs_SMA_150`, `log_Price_vs_SMA_150`, `mom_126d`, `log_Price_vs_SMA_150_Lag1`

### Cluster 69
- **Members:** `Vol_Ratio`, `Dry_Up_Volume_Delta`, `log_Vol_Ratio`, `log_Dry_Up_Volume_Delta`
- **Keep:** `Dry_Up_Volume_Delta` (highest weighted score (IC=0.008, Stab=0.20))
- **Drop:** `log_Dry_Up_Volume_Delta`, `Vol_Ratio`, `log_Vol_Ratio`

### Cluster 47
- **Members:** `rs_rating`, `mom_189d`, `mom_252d`, `Dist_From_52W_Low`, `Sector_Momentum`, `Industry_Momentum`, `log_Dist_From_52W_Low`, `log_Dist_From_52W_Low_Lag1`
- **Keep:** `rs_rating` (highest weighted score (IC=0.116, Stab=1.42))
- **Drop:** `log_Dist_From_52W_Low_Lag1`, `log_Dist_From_52W_Low`, `Dist_From_52W_Low`, `Industry_Momentum`, `mom_189d`, `Sector_Momentum`, `mom_252d`

### Cluster 44
- **Members:** `mom_63d`, `SMA_50_Slope`
- **Keep:** `mom_63d` (highest weighted score (IC=0.068, Stab=1.04))
- **Drop:** `SMA_50_Slope`

### Cluster 20
- **Members:** `turnover`, `vol_ma20`, `vol_ma50`, `log_Volume`, `log_Vol_MA`
- **Keep:** `turnover` (highest weighted score (IC=0.017, Stab=0.35))
- **Drop:** `vol_ma20`, `log_Volume`, `vol_ma50`, `log_Vol_MA`

### Cluster 60
- **Members:** `VCP_Ratio`, `log_VCP_Ratio_Lag1`
- **Keep:** `log_VCP_Ratio_Lag1` (highest weighted score (IC=0.016, Stab=0.28))
- **Drop:** `VCP_Ratio`

### Cluster 61
- **Members:** `Dry_Up_Volume`, `log_Dry_Up_Volume`, `log_Dry_Up_Volume_Lag1`
- **Keep:** `log_Dry_Up_Volume_Lag1` (highest weighted score (IC=0.021, Stab=0.49))
- **Drop:** `Dry_Up_Volume`, `log_Dry_Up_Volume`

### Cluster 55
- **Members:** `Dist_From_52W_High`, `Dist_From_52W_High_Delta`
- **Keep:** `Dist_From_52W_High_Delta` (highest weighted score (IC=0.009, Stab=0.19))
- **Drop:** `Dist_From_52W_High`

### Cluster 36
- **Members:** `Dist_From_20D_High`, `alpha054`
- **Keep:** `alpha054` (highest weighted score (IC=0.018, Stab=0.38))
- **Drop:** `Dist_From_20D_High`

## Section 6: Distributional Warnings

| Feature | Issue | Action |
|---------|-------|--------|
| `rs_rating` | Kurtosis=61.2 | Consider winsorizing at 1/99% |
| `mom_63d` | Kurtosis=63.5 | Consider winsorizing at 1/99% |
| `turnover_ma20` | Kurtosis=19.5 | Consider winsorizing at 1/99% |
| `Is_Green_Day` | Kurtosis=11.5 | Consider winsorizing at 1/99% |
| `nATR_Delta` | Kurtosis=200.6 | Consider winsorizing at 1/99% |
| `Price_vs_SMA_50_Delta` | Kurtosis=14.8 | Consider winsorizing at 1/99% |
| `Price_vs_SMA_150_Delta` | Kurtosis=16.8 | Consider winsorizing at 1/99% |
| `Price_vs_SMA_200_Delta` | Kurtosis=65.3 | Consider winsorizing at 1/99% |
| `Dry_Up_Volume_Delta` | Kurtosis=24.5 | Consider winsorizing at 1/99% |
| `Highest_High_20D_Delta` | Kurtosis=511.4 | Consider winsorizing at 1/99% |
| `RSI_14_Delta` | Kurtosis=10.8 | Consider winsorizing at 1/99% |
| `Dist_From_52W_Low_Delta` | Kurtosis=600.0 | Consider winsorizing at 1/99% |
| `Dist_From_20D_High_Delta` | Kurtosis=16.1 | Consider winsorizing at 1/99% |
| `alpha001` | Kurtosis=164.7 | Consider winsorizing at 1/99% |
| `alpha012` | Kurtosis=11.5 | Consider winsorizing at 1/99% |
| `alpha041` | Kurtosis=10.4 | Consider winsorizing at 1/99% |
| `alpha060` | Kurtosis=18.9 | Consider winsorizing at 1/99% |
| `net_income_growth_yoy` | Kurtosis=16.0 | Consider winsorizing at 1/99% |
| `eps_stability_score` | Kurtosis=25.2 | Consider winsorizing at 1/99% |
| `debt_to_equity` | Kurtosis=14.5 | Consider winsorizing at 1/99% |

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
| `rs_rating` | Log | TAR-based | 2.87 |
| `mom_21d` | Log | TAR-based | 3.10 |
| `mom_63d` | Log | TAR-based | 3.23 |
| `mom_126d` | Log | TAR-based | 3.09 |
| `mom_189d` | Log | TAR-based | 2.79 |
| `mom_252d` | Log | TAR-based | 2.82 |
| `turnover` | Log | TAR-based | 1.57 |
| `vol_ma20` | Log | TAR-based | 1.87 |
| `vol_ma50` | Log | TAR-based | 1.95 |
| `nATR` | Log | Explosive | - |
| `Consolidation_Width` | Log | TAR-based | 3.16 |
| `Dry_Up_Volume` | Log | Explosive | - |
| `Dist_From_52W_High` | Log | Explosive | - |
| `Dist_From_20D_Low` | Log | TAR-based | 3.14 |
| `Dist_From_52W_Low` | Log | Explosive | - |
| `volume_acceleration` | Log | Explosive | - |
| `breakout_momentum` | Log | TAR-based | 1.58 |
| `consolidation_duration` | Log | TAR-based | 1.59 |
| `price_momentum_curve` | Log | TAR-based | 1.22 |
| `immediate_thrust` | Log | TAR-based | 1.22 |
| `log_volume_velocity` | Log | TAR-based | 2.00 |
| `nATR_Delta` | Log | TAR-based | 1.26 |
| `ATR_Delta` | Log | TAR-based | 1.87 |
| `VCP_Ratio_Delta` | Log | TAR-based | 2.02 |
| `Consolidation_Width_Delta` | Log | TAR-based | 1.37 |
| `Price_vs_SMA_200_Delta` | Log | TAR-based | 1.59 |
| `Dry_Up_Volume_Delta` | Log | TAR-based | 2.35 |
| `High_52W_Delta` | Log | TAR-based | 2.66 |
| `Low_52W_Delta` | Log | TAR-based | 1.23 |
| `Lowest_Low_20D_Delta` | Log | TAR-based | 1.61 |
| `Highest_High_20D_Delta` | Log | TAR-based | 2.93 |
| `RSI_14_Delta` | Log | TAR-based | 1.38 |
| `Dist_From_52W_Low_Delta` | Log | TAR-based | 2.19 |
| `Dist_From_20D_Low_Delta` | Log | TAR-based | 1.32 |
| `alpha001` | Log | TAR-based | 2.53 |
| `alpha009` | Log | TAR-based | 1.21 |
| `alpha060` | Log | TAR-based | 1.98 |
| `revenue_growth_yoy` | Log | Explosive | - |
| `eps_growth_yoy` | Log | Explosive | - |
| `eps_accel` | Log | Explosive | - |
| `revenue_accel` | Log | Explosive | - |
| `revenue_cagr_3y` | Log | TAR-based | 1.89 |
| `debt_to_equity` | Log | TAR-based | 1.39 |
| `fcf_margin` | Log | TAR-based | 1.27 |
| `gross_margin_trend` | Log | TAR-based | 1.64 |
| `days_since_report` | Log | TAR-based | 1.33 |
| `days_since_earnings` | Log | TAR-based | 1.33 |
| `pb_ratio` | Log | Explosive | - |
| `Sector_Momentum` | Log | TAR-based | 2.39 |
| `Industry_Momentum` | Log | TAR-based | 2.45 |
| `RS_vs_Industry` | Log | TAR-based | 1.31 |
| `log_Dist_From_20D_Low` | Log | TAR-based | 3.14 |
| `log_Dist_From_52W_Low` | Log | TAR-based | 2.74 |
| `log_Dist_From_52W_Low_Lag1` | Log | TAR-based | 2.65 |
| `log_Dist_From_20D_Low_Lag1` | Log | TAR-based | 2.78 |
| `log_nATR_Delta` | Log | TAR-based | 1.26 |
| `log_ATR_Delta` | Log | TAR-based | 1.87 |
| `log_VCP_Ratio_Delta` | Log | TAR-based | 2.02 |
| `log_Price_vs_SMA_200_Delta` | Log | TAR-based | 1.59 |
| `log_Dry_Up_Volume_Delta` | Log | TAR-based | 2.35 |
| `log_High_52W_Delta` | Log | TAR-based | 2.66 |
| `log_Low_52W_Delta` | Log | TAR-based | 1.23 |
| `log_Lowest_Low_20D_Delta` | Log | TAR-based | 1.61 |
| `log_Highest_High_20D_Delta` | Log | TAR-based | 2.93 |
| `log_RSI_14_Delta` | Log | TAR-based | 1.38 |
| `log_Dist_From_52W_Low_Delta` | Log | TAR-based | 2.19 |
| `log_Dist_From_20D_Low_Delta` | Log | TAR-based | 1.32 |
| `log_alpha001` | Log | TAR-based | 2.53 |
| `log_alpha060` | Log | TAR-based | 1.98 |
| `log_debt_to_equity` | Log | TAR-based | 1.39 |
| `turnover_ma20` | Winsorize | TAR-based | 1.19 |
| `Is_Green_Day` | Winsorize | TAR-based | 1.00 |
| `price_accel_10d` | Winsorize | TAR-based | 1.12 |
| `Price_vs_SMA_50_Delta` | Winsorize | TAR-based | 1.04 |
| `Price_vs_SMA_150_Delta` | Winsorize | TAR-based | 1.12 |
| `Dist_From_20D_High_Delta` | Winsorize | TAR-based | 1.01 |
| `alpha012` | Winsorize | TAR-based | 1.00 |
| `alpha041` | Winsorize | TAR-based | 0.93 |
| `alpha004` | Winsorize | TAR-based | 1.01 |
| `alpha049` | Winsorize | TAR-based | 0.97 |
| `alpha051` | Winsorize | TAR-based | 0.94 |
| `net_income_growth_yoy` | Winsorize | TAR-based | 1.17 |
| `eps_stability_score` | Winsorize | TAR-based | 1.14 |
| `current_ratio` | Winsorize | TAR-based | 1.12 |
| `quick_ratio` | Winsorize | TAR-based | 1.13 |
| `operating_margin` | Winsorize | Standard | - |
| `roe` | Winsorize | Standard | - |
| `net_margin` | Winsorize | Standard | - |
| `inventory_growth_yoy` | Winsorize | TAR-based | 1.14 |
| `inventory_vs_sales_spread` | Winsorize | TAR-based | 1.13 |
| `earnings_quality_score` | Winsorize | Bounded | - |
| `log_current_ratio` | Winsorize | TAR-based | 1.12 |
| `log_quick_ratio` | Winsorize | TAR-based | 1.13 |

**Total:** 74 log-transformed, 23 winsorized

> **TAR (Tail Alpha Ratio):** Ratio of mean |return| in 99-100th percentile vs 10-90th percentile.
> TAR > 1.2 suggests tail values are predictive (log transform); TAR <= 1.2 suggests noise (winsorize).

## Recommended Feature List

Copy this to `src/feature_config.py` → `M01_FEATURES` after review:

> **Note:** Features with `log_` prefix are log-transformed during preprocessing.
> The preprocessor will apply these transforms automatically at training/inference.

```python
M01_FEATURES = [
    'alpha011',
    'log_rs_rating',  # log-transformed
    'log_Price_vs_SMA_200',  # log-transformed
    'log_nATR_Lag1',
    'alpha013',
    'log_mom_63d',  # log-transformed
    'RS_Universe_Rank',
    'm03_pillar_risk',
    'log_Price_vs_SMA_50_Lag1',
    'operating_margin',
    'log_alpha060',  # log-transformed
    'alpha012',
    'm03_pillar_trend',
    'eps_stability_score',
    'current_ratio',
    'log_Highest_High_20D_Delta',  # log-transformed
    'log_debt_to_equity',  # log-transformed
    'roa',
    'log_nATR_Delta',  # log-transformed
    'log_alpha001',  # log-transformed
    'log_fcf_margin',  # log-transformed
    'roe',
    'alpha101',
    'log_days_since_report',  # log-transformed
    'alpha054',
    'ps_ratio',
    'm03_pillar_liq',
    'log_price_momentum_curve',  # log-transformed
    'earnings_quality_score',
    'log_pb_ratio',  # log-transformed
    'industry_id_encoded',
    'alpha015',
    'log_volume_velocity',  # already log-transformed
    'log_alpha009',  # log-transformed
    'm03_score',
    'log_Dist_From_52W_Low_Delta',  # log-transformed
    'RS_vs_Sector',
    'net_income_growth_yoy',
    'alpha041',
    'log_VCP_Ratio_Lag1',
    'log_revenue_accel',  # log-transformed
    'log_Dry_Up_Volume_Lag1',
    'log_eps_accel',  # log-transformed
    'm03_delta_20d',
    'Dist_From_20D_High_Delta',
    'log_revenue_growth_yoy',  # log-transformed
    'm03_regime_vol',
    'log_volume_acceleration',  # log-transformed
    'alpha006',
    'turnover_ma20',
    'log_breakout_momentum',  # log-transformed
    'pe_ratio',
    'Price_vs_SMA_50_Delta',
    'RSI_14',
    'log_Price_vs_SMA_200_Delta',  # log-transformed
    'log_Dry_Up_Volume_Delta',  # log-transformed
    'Price_vs_SMA_150_Delta',
    'log_turnover',  # log-transformed
    'inventory_vs_sales_spread',
    'log_RSI_14_Delta',  # log-transformed
    'sector_id_encoded',
    'gross_margin',
    'alpha002',
    'm03_delta_5d',
    'log_revenue_cagr_3y',  # log-transformed
    'log_gross_margin_trend',  # log-transformed
    'peg_adjusted',
    'Is_Green_Day',
    'is_declining_earnings',
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