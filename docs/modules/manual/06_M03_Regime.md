---
title: M03 Market Regime Calculator
type: component
layer: model
status: stable
created: 2026-01-31
updated: 2026-01-31
version: 1.4.0
tags:
  - m03
  - regime
  - macro
  - risk-gating
  - fred
---

# M03: Market Regime Calculator

## Overview

M03 is a **factor-based market regime scoring system** that classifies market conditions on a 0-100 scale. It serves two purposes:

1. **Gatekeeper** - Reduces position sizing or blocks trades during adverse regimes
2. **Feature Provider** - Supplies regime context to M01/M02 models

Unlike M01 (stock-level return predictor) and M02 (trade-level loser detector), M03 operates at the **market level** and runs independently of individual stock analysis.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         DATA SOURCES                             │
│  FRED API: WALCL, WTREGEN, RRPONTSYD, BAMLH0A0HYM2, VIXCLS      │
│  Price API: SPY (for trend pillar)                               │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                       MACRO ENGINE                               │
│  src/macro_engine.py                                             │
│  - Fetches & caches FRED series (data/macro/*.parquet)          │
│  - Calculates Net Liquidity = WALCL - WTREGEN - RRPONTSYD       │
│  - Data indexed by observation date (lag handled downstream)    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    M03 REGIME CALCULATOR                         │
│  src/pipeline/m03_regime.py                                      │
│  - Three-pillar scoring (Trend + Liquidity + Risk Appetite)     │
│  - Applies T+1 publication lag for lookahead-free backtesting   │
│  - Outputs: score (0-100), category, pillar breakdown           │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                         OUTPUTS                                  │
│  1. Gatekeeper: daily_scanner.py position sizing                │
│  2. Features: regime_cat, liquidity_trend for M01/M02           │
│  3. History: models/m03_history.parquet for backtesting         │
└─────────────────────────────────────────────────────────────────┘
```

## Three-Pillar Scoring System

### Pillar 1: Trend (40% weight)
**Signal:** SPY price relative to 200-day SMA

| Condition | Score Impact |
|-----------|--------------|
| SPY > SMA_200 by 10%+ | ~100 (strong bull) |
| SPY = SMA_200 | 50 (neutral) |
| SPY < SMA_200 by 10%+ | ~0 (strong bear) |

**Formula:** `score = 50 + 50 * tanh(pct_above_sma * 10)`

### Pillar 2: Liquidity (20% weight)
**Signal:** Fed Net Liquidity 10-day slope

```
Net Liquidity = Fed Assets (WALCL) - TGA (WTREGEN) - RRP (RRPONTSYD)
```

| Condition | Score Impact |
|-----------|--------------|
| Rising liquidity (positive slope) | High score (bullish) |
| Flat liquidity | 50 (neutral) |
| Falling liquidity (negative slope) | Low score (bearish) |

**Formula:** `score = 50 + 50 * tanh(slope_pct * 50)`

### Pillar 3: Risk Appetite (40% weight)
**Signals:** VIX level + HY credit spread (BAMLH0A0HYM2)

| VIX | Score (0-50) |
|-----|--------------|
| < 15 | ~50 (calm) |
| 20 | ~25 (elevated) |
| > 30 | ~0 (panic) |

| HY Spread | Score (0-50) |
|-----------|--------------|
| < 4% | ~50 (risk-on) |
| 5% | ~25 (cautious) |
| > 7% | ~0 (risk-off) |

**Combined:** `risk_appetite_score = vix_score + spread_score` (0-100)

## Regime Categories

| Score Range | Category | Position Sizing | Description |
|-------------|----------|-----------------|-------------|
| 75-100 | STRONG_BULL | 1.2x (leverage) | All pillars aligned bullish |
| 60-75 | BULL | 1.0x (full) | Standard conditions |
| 45-60 | NEUTRAL | 0.5x (reduced) | Conflicting signals |
| 25-45 | BEAR | 0.0x (cash) | Trend broken or risk elevated |
| 0-25 | STRONG_BEAR | -0.5x (hedge) | Active crash |

## Publication Lag Handling

### The Problem: Lookahead Bias
FRED data is indexed by **observation date** but released with a **publication lag**:

| Data Source | Observation | Release | Lag |
|-------------|-------------|---------|-----|
| WALCL | Wednesday | Thursday 4:30 PM ET | T+1 |
| WTREGEN | Wednesday | Thursday 4:30 PM ET | T+1 |
| RRPONTSYD | Daily | Same day after close | T+1* |
| HY Spread | Daily | Next day | T+1 |
| VIX | Intraday | Real-time | T+0 |

*RRP is released same-day but after market close, so we treat it as T+1 for trading.

### The Solution: Fixed T+1 Shift
We apply a 1-day shift at the consumption layer:

```python
# In M03RegimeCalculator.calculate_history_vectorized()
macro_df = macro_df.shift(freq='1D')
```

**Result:** "Wednesday's Fed data" appears on "Thursday's trading row"

### Holiday Handling
`ffill()` handles holidays automatically:
- If Thursday is a holiday (e.g., Thanksgiving), there's no trading row
- Data naturally carries forward to Friday via forward-fill
- Effective lag becomes T+2 for that week (conservative, correct)

## Files

| File | Purpose |
|------|---------|
| [src/macro_engine.py](../../src/macro_engine.py) | FRED data fetching & caching |
| [src/pipeline/m03_regime.py](../../src/pipeline/m03_regime.py) | Regime calculation logic |
| [model_runner.py](../../model_runner.py) | CLI entry point (`m03` subcommand) |
| [models/m03_config.json](../../models/m03_config.json) | Pillar weights & thresholds |
| [data/macro/*.parquet](../../data/macro/) | Cached FRED series |

## CLI Usage

### Current Regime (Single Date)
```bash
# Latest available
python model_runner.py m03

# Specific date
python model_runner.py m03 --date 2024-01-15
```

**Output:**
```
[REGIME] Score: 72.3 / 100
   Category: BULL
   Date: 2024-01-15

[PILLARS]
   Trend               : 78.5 (weight: 40%)
   Liquidity           : 62.1 (weight: 30%)
   Risk Appetite       : 71.2 (weight: 30%)
```

### Historical Regimes
```bash
# Daily history with CSV export
python model_runner.py m03 --history --start 2003-03-01 --end 2024-12-31 --csv

# Weekly (Friday) frequency
python model_runner.py m03 --history --start 2020-01-01 --end 2024-12-31 --freq W-FRI

# Monthly frequency
python model_runner.py m03 --history --start 2010-01-01 --end 2024-12-31 --freq M
```

**Frequency Options:** `D` (daily), `W-FRI`, `W-MON`, `M` (monthly), `Q` (quarterly)

### Update Macro Cache
```bash
# Force re-download all FRED data
python -c "from src.macro_engine import MacroEngine; MacroEngine().update_macro_cache(force=True)"
```

## Python API

### Basic Usage
```python
from src.pipeline.m03_regime import M03RegimeCalculator

calc = M03RegimeCalculator()

# Current regime
result = calc.calculate()
print(f"Score: {result['score']}, Category: {result['category']}")

# Specific date
result = calc.calculate(as_of_date='2024-01-15')

# Historical regimes
df = calc.calculate_history('2020-01-01', '2024-12-31', freq='D')
```

### Gating Check
```python
# Check if signals should be gated
gate = calc.should_gate_signal(as_of_date='2024-01-15')
if not gate['allow_longs']:
    print("⛔ Regime too bearish, no longs allowed")
elif gate['reduced_sizing']:
    print("⚠️ Neutral regime, reduce position size")
```

### Access Pillar Breakdown
```python
result = calc.calculate()
for pillar_name, pillar_data in result['pillars'].items():
    print(f"{pillar_name}: {pillar_data['score']} (weight: {pillar_data['weight']*100}%)")
```

## Integration Points

### 1. Daily Scanner Gatekeeper
```python
# In daily_scanner.py
from src.pipeline.m03_regime import M03RegimeCalculator

calc = M03RegimeCalculator()
regime = calc.calculate()

if regime['score'] < 20:
    print("⛔ STRONG BEAR: Emergency Cash Mode. No Buys.")
    position_multiplier = 0.0
elif regime['score'] < 40:
    print("🛑 BEAR: No New Longs.")
    position_multiplier = 0.0
elif regime['score'] < 60:
    print("⚠️ NEUTRAL: Half Size.")
    position_multiplier = 0.5
else:
    print("✅ BULL: Full Risk.")
    position_multiplier = 1.0
```

### 2. M01 Feature Engineering
```python
# Regime features for M01 training
def add_regime_features(df, regime_history):
    # Ordinal encoding (tree-split optimized)
    regime_map = {'strong_bear': 0, 'bear': 1, 'neutral': 2, 'bull': 3, 'strong_bull': 4}
    df['regime_cat'] = regime_history['category'].map(regime_map)

    # Raw signals
    df['liquidity_trend'] = regime_history['liq_slope_pct']
    df['vix_level'] = regime_history['vix']

    # Regime stability (10-day rolling std of score)
    df['regime_volatility'] = regime_history['score'].rolling(10).std()

    return df
```

## Evaluation System

### CLI Commands

```bash
# Evaluate production config
python model_runner.py m03eval --start 2007-01-01 --end 2024-12-31

# Run grid search (12 archetypes)
python model_runner.py m03grid

# Evaluate specific config
python model_runner.py m03eval --config models/m03_configs/hybrid_tight.json

# Calibrate thresholds from score distributions
python model_runner.py m03calibrate --start 2007-01-01 --end 2024-12-31
python model_runner.py m03calibrate --save  # Updates m03_config.json
```

### Discrimination Metrics (Phase 1)

| Metric | Description | Target |
|--------|-------------|--------|
| **ROC-AUC Bear** | P(crash day score < bull day score) | ≥ 0.90 |
| **ROC-AUC Bull** | P(bull day score > neutral day score) | ≥ 0.90 |
| **Cohen's D** | Standard deviations between Bull/Bear means | ≥ 2.0 |
| **Fitness** | `(AUC_Bear × 0.6) + (AUC_Bull × 0.4) - Lag_Penalty` | Maximize |

### Calibration Metrics (Phase 2)

| Metric | Description | Target |
|--------|-------------|--------|
| **CCR** | Crash Capture Rate (% STRONG_BEAR days flagged) | ≥ 80% |
| **FAR** | False Alarm Rate (% STRONG_BULL days mis-flagged) | ≤ 5% |
| **Lag** | Days to first bear signal after crash start | ≤ 7 days |

### Threshold Calibration

Thresholds are calibrated from actual score distributions using percentile targets:

```bash
python model_runner.py m03calibrate --start 2003-01-01 --end 2025-12-31 --save
```

**Calibration Logic:**
- **CCR Threshold:** 80th percentile of STRONG_BEAR scores → captures 80% of crash days
- **FAR Threshold:** 5th percentile of STRONG_BULL scores → only 5% false alarms

**Calibrated Values (v1.4.0):**

| Threshold | Value | Purpose |
|-----------|-------|--------|
| CCR Score | 42 | Score < 42 during STRONG_BEAR = crash captured |
| FAR Score | 30 | Score < 30 during STRONG_BULL = false alarm |
| LAG Score | 30 | Score < 30 = bear signal detected |

### Production Metrics (v1.4.0 Hybrid)

| Metric | Value | Status |
|--------|-------|--------|
| Cohen's D | 2.24 | ✅ PASS |
| AUC Bear | 0.882 | Close to target |
| GFC Lag | 10 days | ✅ Fast |
| COVID Lag | 5 days | ✅ Fast |
| Fitness | 0.793 | Best achieved |

### Key Validation Periods

| Period | Ground Truth | Expected M03 Score |
|--------|--------------|--------------|
| 2007-10 to 2009-03 | STRONG_BEAR (GFC) | < 25 |
| 2020-02-20 to 2020-03-23 | STRONG_BEAR (COVID) | < 25 |
| 2016-02 to 2018-01 | STRONG_BULL (Trump rally) | > 75 |
| 2020-03-24 to 2021-12 | STRONG_BULL (Fed stimulus) | > 75 |

## Configuration

Production config stored in `models/m03_config.json` (v1.3.0 Hybrid):

```json
{
  "model_name": "M03",
  "version": "1.3.0",
  "rationale": "Hybrid: Trend=0.4 (Separation), Risk=0.4 (Speed), Liq=0.2 (Support)",
  "pillars": {
    "trend": {"weight": 0.40, "sma_period": 200},
    "liquidity": {"weight": 0.20, "slope_lookback": 10},
    "risk_appetite": {
      "weight": 0.40,
      "vix_bull_threshold": 15,
      "vix_bear_threshold": 20,
      "vix_extreme_threshold": 30,
      "spread_bull_threshold": 4.0,
      "spread_bear_threshold": 5.0,
      "spread_extreme_threshold": 7.0
    }
  },
  "thresholds": {
    "strong_bull": 75,
    "bull": 60,
    "neutral": 45,
    "bear": 25
  },
  "gating_rules": {
    "long_allow_min": 30,
    "long_reduced_min": 50
  }
}
```

### Configuration History

| Version | Date | Key Changes |
|---------|------|-------------|
| 1.0.0 | 2026-01-30 | Initial (40/30/30 weights) |
| 1.3.0 | 2026-01-31 | Hybrid (40/20/40), tight VIX, 10d liq lookback |
| 1.4.0 | 2026-01-31 | Added calibrated thresholds (CCR=42, FAR=30, LAG=30) |

## Data Sources

### FRED Series
| Series ID | Description | Frequency | Units |
|-----------|-------------|-----------|-------|
| WALCL | Fed Total Assets | Weekly (Wed) | Millions USD |
| WTREGEN | Treasury General Account | Weekly (Wed) | Millions USD |
| RRPONTSYD | Overnight Reverse Repo | Daily | Billions USD |
| BAMLH0A0HYM2 | ICE BofA US High Yield Spread | Daily | Percent |
| VIXCLS | CBOE VIX | Daily | Index |

### Data Availability
- WALCL/WTREGEN: December 2002 onwards
- RRPONTSYD: February 2003 onwards
- Default start date: 2003-01-01 (captures 2008 crisis)

---

*Last updated: 2026-01-31*
