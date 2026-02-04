---
title: Quantamental SEPA System - Technical Manual
type: overview
layer: all
status: stable
created: 2026-01-27
updated: 2026-01-29
tags:
  - architecture
  - index
  - navigation
  - sepa
  - ml
  - dual-model
---

# Quantamental SEPA System - Technical Manual

## Purpose

The Quantamental project is a **SEPA-style equity screening and ML pipeline** for identifying super-performing stocks. It combines:
- **Minervini SEPA methodology** for fundamental + technical screening
- **Machine learning models** for ranking and risk filtering
- **Rigorous walk-forward validation** to avoid look-ahead bias

## System Architecture

The system is organized into five layers, from data acquisition to visualization:

### 1. Data Layer

**Purpose:** Acquire and cache market data with intelligent updates

**Components:**
- [[07_Data_Layer#DataRepository|DataRepository]] ([data_engine.py](../../src/data_engine.py)) - Price data cache with smart validation
- [[07_Data_Layer#FundamentalEngine|FundamentalEngine]] ([fundamental_engine.py](../../src/fundamental_engine.py)) - Financial statements
- [[07_Data_Layer#EarningsEngine|EarningsEngine]] ([earnings_engine.py](../../src/earnings_engine.py)) - Earnings calendar tracking
- **data_curator.py** - Daily data maintenance script

**Key Features:**
- Parquet-based caching for fast access
- Earnings-driven fundamental updates (90% API reduction)
- IPO date validation (prevents pre-IPO data leakage)
- Rate-limited FMP API integration

---

### 2. Feature Engineering Layer

**Purpose:** Transform raw data into ML-ready features

**Components:**
- **FeatureEngineer** ([features.py](../../src/features.py)) - Technical indicators
- **AlphaFactors** ([alpha_factors.py](../../src/alpha_factors.py)) - WorldQuant-style factors
- **FundamentalMerger** - Merge fundamental metrics with price features
- [[06_Feature_Config|Feature Config]] ([feature_config.py](../../src/feature_config.py)) - Single source of truth for features

**Feature Categories:**
- **Technical:** RSI, MACD, Bollinger Bands, ATR
- **Price Structure:** Support/resistance, consolidation, breakouts
- **Alpha Factors:** Momentum, mean reversion, volume patterns
- **Fundamental:** EPS growth, margins, debt ratios

---

### 3. Strategy & Simulation Layer

**Purpose:** Run SEPA screener and simulate historical trades

**Components:**
- [[08_Strategy_Layer#SEPAStrategy|SEPAStrategy]] ([strategy.py](../../src/strategy.py)) - Minervini screening logic
- [[08_Strategy_Layer#Trade Simulator|FastTradeSimulator]] ([trade_simulator_fast.py](../../src/trade_simulator_fast.py)) - Historical backtesting
- [[08_Strategy_Layer#Triple Barrier Labeler|TripleBarrierLabeler]] ([triple_barrier_labeler.py](../../src/triple_barrier_labeler.py)) - Meta-labeling
- **DatasetRehydrator** ([dataset_rehydrator.py](../../src/dataset_rehydrator.py)) - Multi-day trajectories

**SEPA Screening Criteria:**
- Price > 10-week MA > 30-week MA
- RS Rating > 80 (vs SPY)
- Volume surge on breakout
- Price near 52-week high

---

### 4. Model Runner Suite → [[01_Model_Runner_Suite|View Details]]

**Purpose:** Train and deploy ML models for trade prediction

**Components:**
- [[02_Data_Pipeline|DataPipeline]] ([data_pipeline.py](../../src/pipeline/data_pipeline.py)) - Orchestrates D1→D2→D2R→D3 workflow
- [[03_M01_Trainer|M01 Trainer]] ([m01_trainer.py](../../src/pipeline/m01_trainer.py)) - Return predictor (XGBoost Regression)
- [[04_M02_Trainer|M02 Loser Detector]] ([m02_trainer.py](../../src/pipeline/m02_trainer.py)) - Stop-loss predictor (XGBoost Classification)
- [[06_M03_Regime|M03 Regime Calculator]] ([m03_regime.py](../../src/pipeline/m03_regime.py)) - Market regime scoring
- [[05_Model_Entry_Point|Model CLI]] ([model_runner.py](../../model_runner.py)) - Command-line interface
- **M01Workflow** ([m01_workflow.py](../../src/pipeline/m01_workflow.py)) - Automated EDA + training pipeline
- **FeatureScreener** ([feature_screener.py](../../src/evaluation/feature_screener.py)) - KS-based feature selection
- **ProductionScorer** ([production_scorer.py](../../src/pipeline/production_scorer.py)) - Dual-model scoring
- **MacroEngine** ([macro_engine.py](../../src/macro_engine.py)) - FRED data fetching for M03

**Model Outputs:**
- **M01:** Predicts expected return % → Ranks candidates
- **M02:** Predicts P(stop-loss hit) → Filters high-risk trades
- **M03:** Scores market regime (0-100) → Gates position sizing
- **Final Score:** `M01_adj × (1 - P(loser)) × regime_multiplier` → Risk-adjusted ranking

---

### 5. Visualization Layer

**Purpose:** Interactive dashboard for analysis and monitoring

**Components:**
- [[09_Dashboard|Streamlit Dashboard]] ([dashboard.py](../../dashboard.py)) - Main UI
- **VizLibrary** ([viz_library.py](../../src/viz_library.py)) - Plotly charts
- **DashboardReports** ([dashboard_reports.py](../../src/dashboard_reports.py)) - Report generators

**Dashboard Pages:**
- Model performance (M01/M02 metrics)
- Trade physics (MAE/MFE, E-Ratio)
- Feature importance
- Prediction analysis

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                         DATA SOURCES                             │
│  FMP API (Prices, Fundamentals, Earnings) + SSGA (SP500 List)   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                         DATA LAYER                               │
│  DataRepository → Price Cache (data/price/*.parquet)             │
│  FundamentalEngine → Fundamental Cache (data/fundamentals/)      │
│  EarningsEngine → Earnings Cache (data/earnings/)                │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    STRATEGY & SIMULATION                         │
│  SEPAStrategy + FastTradeSimulator → D1 (Trade Candidates)       │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                      DATA PIPELINE                               │
│  scan() → D1 (trades)                                            │
│  features() → D2 (trades + features)                             │
│  hydrate() → D2R (multi-day trajectories)                        │
│  label() → D3 (triple barrier labels)                            │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                      MODEL TRAINING                              │
│  M01: D2 → XGBoost Regressor → m01.json (return predictor)      │
│  M02: D3 → XGBoost Classifier → m02.json (ignition classifier)  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                      VISUALIZATION                               │
│  Streamlit Dashboard → Performance analysis + Trade insights     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Training Models

```bash
# M01 (Return Predictor)
python model_runner.py m01 --start 2018-01-01 --end 2023-12-31 --report

# M02 (Loser Detector)
python model_runner.py m02 --start 2018-01-01 --end 2023-12-31 --report

# M03 (Market Regime)
python model_runner.py m03 --history --start 2003-03-01 --end 2024-12-31 --csv

# Full Workflow (EDA + Feature Selection + Training)
python model_runner.py workflow --start 2018-01-01 --end 2023-12-31
```

### Production Scoring

```bash
# Daily scanner with dual-model scoring
python daily_scanner.py --use-ml
```

See [[05_Model_Entry_Point|CLI Documentation]] for detailed usage.

### Running Dashboard

```bash
streamlit run dashboard.py
```

### Daily Data Maintenance

```bash
python data_curator.py --source sp500 --update-all
```

---

## Documentation Index

### Model Runner Suite (Core Focus)
1. [[01_Model_Runner_Suite|Model Runner Suite Overview]]
2. [[02_Data_Pipeline|Data Pipeline (D1→D2→D3)]]
3. [[03_M01_Trainer|M01: Return Predictor]]
4. [[04_M02_Trainer|M02: Ignition Classifier]]
5. [[05_Model_Entry_Point|CLI Reference]]
6. [[06_M03_Regime|M03: Market Regime Calculator]]

### Supporting Layers
- [[06_Feature_Config|Feature Configuration]]
- [[07_Data_Layer|Data Layer (Repositories & Engines)]]
- [[08_Strategy_Layer|Strategy & Simulation]]
- [[09_Dashboard|Dashboard & Visualization]]

---

## Project Philosophy

> [!important] Academic Rigor
> The system prioritizes **predictive validity** over curve-fitting:
> - Walk-forward validation (no look-ahead bias)
> - Out-of-sample testing on unseen years
> - Decile analysis (do top predictions actually win?)
> - Feature importance tracking

> [!tip] SEPA + ML Synthesis
> Combines Minervini's fundamental + technical screens (SEPA) with modern ML for:
> - **M01:** Ranking candidates by expected return
> - **M02:** Filtering low-probability setups (TP vs SL)

---

## Key Concepts

**Walk-Forward Validation:**
- Train on 3 years → Test on 1 year
- Example: Train [2018-2020] → Test [2021]
- Ensures models generalize to future unseen data

**Triple Barrier Labeling:**
- Labels trades as TP (profit target hit) or SL (stop-loss hit)
- Accounts for path-dependency (when exit happens)
- Used by M02 for loser detection

**Dual-Model Scoring:**
- M01 ranks candidates by expected return
- M02 predicts P(stop-loss hit) - "Loser Detector"
- Final Score = M01_adj × (1 - P(loser))
- Filters out high-risk trades while preserving ranking

**M03 Market Regime:**
- Three-pillar scoring: Trend (SPY vs SMA) + Liquidity (Fed Net Liq) + Risk Appetite (VIX + HY spread)
- Score 0-100 → Categories: strong_bear, bear, neutral, bull, strong_bull
- Gates position sizing: strong_bear = 0x, bear = 0x, neutral = 0.5x, bull = 1.0x
- Uses T+1 publication lag to avoid lookahead bias in backtests

**Feature Selection Pipeline:**
- Uses KS (Kolmogorov-Smirnov) test
- Compares Q1 (bottom 25%) vs Q4 (top 25%) return distributions
- Features with significant distribution shift pass screening
- Recommended threshold: 0.10

**Survivor Model:**
- M01 variant that filters "crashed" trades (MAE < structural stop)
- Trains on y_max (MFE) instead of return_pct
- Predicts maximum achievable upside for survivors

---

## File Structure

```
quantamental/
├── model_runner.py               # CLI entry point
├── daily_scanner.py              # Daily stock scanner with ML
├── data_curator.py               # Daily data maintenance
├── dashboard.py                  # Streamlit UI
├── src/
│   ├── pipeline/
│   │   ├── data_pipeline.py      # D1→D2→D3 orchestration
│   │   ├── m01_trainer.py        # Return regression
│   │   ├── m02_trainer.py        # Loser detection
│   │   ├── m03_regime.py         # Market regime calculator
│   │   ├── m01_workflow.py       # Automated EDA + training
│   │   ├── production_scorer.py  # Dual-model scoring
│   │   └── base_trainer.py       # Shared training logic
│   ├── evaluation/
│   │   ├── feature_screener.py   # KS-based feature selection
│   │   ├── metrics.py            # IC, Precision@K, Recall@K
│   │   └── targets.py            # Target engineering
│   ├── data_engine.py            # Price cache
│   ├── fundamental_engine.py     # Fundamental cache
│   ├── earnings_engine.py        # Earnings tracking
│   ├── macro_engine.py           # FRED data for M03
│   ├── features.py               # Feature engineering
│   ├── strategy.py               # SEPA screener
│   ├── trade_simulator_fast.py   # Historical simulation
│   ├── triple_barrier_labeler.py # Meta-labeling
│   └── feature_config.py         # Feature definitions
├── scripts/
│   ├── run_m01_ablation_study.py # Target comparison study
│   └── run_m01_phase4_deployment.py # Production deployment
├── data/
│   ├── ml/                       # ML datasets (D1, D2, D3)
│   ├── price/                    # Price cache
│   ├── fundamentals/             # Fundamental cache
│   ├── earnings/                 # Earnings cache
│   └── macro/                    # FRED macro cache (WALCL, VIX, etc.)
├── models/
│   ├── m01.json                  # M01 model
│   ├── m02.json                  # M02 Loser Detector
│   ├── m03_config.json           # M03 regime thresholds
│   ├── m03_history.parquet       # Historical regime scores
│   ├── production_scoring_config.json # Position sizing
│   └── *_config.json             # Model configs
└── docs/
    └── manual/                   # This documentation
```

---

*Last updated: 2026-01-31*
