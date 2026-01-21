# Quantamental SEPA System (QSS)

A production-grade machine learning framework for stock screening and trade signal ranking that combines Mark Minervini's SEPA (Specific Entry Point Analysis) methodology with quantitative alpha factors and fundamental analysis.

## Overview

The Quantamental SEPA System (QSS) is a meta-labeling ML framework designed to identify high-probability growth stock entry points by filtering SEPA technical signals through ML-powered quality scoring. The system combines:

- **Technical Analysis**: SEPA methodology (Stage 2 uptrend detection, VCP patterns, breakout triggers)
- **Fundamental Analysis**: Financial statement data (revenue growth, margins, debt ratios)
- **Quantitative Factors**: WorldQuant 101 alpha library (momentum, volatility, volume indicators)
- **Machine Learning**: XGBoost models trained on historical trade outcomes to predict success probability

### Trading Philosophy

**Entry Criteria**:
- Only trade stocks with ML rank 9+ (top decile)
- Must pass all SEPA technical requirements (Stage 2, VCP, breakout confirmation)
- Minimum market cap $300M, price $5, volume 200K shares/day

**Risk Management**:
- Hard stop loss: -8% from entry
- Time stop: Exit if P/L ≤ 0 at Day 15
- Target: Trail stop at 50-day SMA to capture 2-6 month "campaign" runs of +40%

**Label Definition** (for ML training):
- Success (1): Trade returns ≥ 15%
- Failure (0): Trade hits stop loss or time stop

## Project Structure

```
quantamental/
├── src/                          # Core library modules
│   ├── data_engine.py           # Price data acquisition & caching
│   ├── fundamental_engine.py    # Fundamental data fetching
│   ├── features.py              # Technical indicator calculation
│   ├── alpha_factors.py         # WorldQuant alpha library wrapper
│   ├── fundamental_processor.py # Growth metrics & ratio calculation
│   ├── fundamental_merger.py    # Point-in-time fundamental joins
│   ├── strategy.py              # SEPA signal generation
│   ├── trade_simulator_fast.py  # Historical backtesting engine
│   ├── model_preparation.py     # Temporal splitting & feature selection
│   ├── train_model.py           # XGBoost training pipeline
│   ├── evaluate_model.py        # Model evaluation & reporting
│   ├── ml_scorer.py             # Production ML inference
│   └── database.py              # SQLite buy list management
│
├── data/
│   ├── price/                   # Parquet cache (OHLCV data)
│   ├── fundamentals/            # FMP fundamental data cache
│   ├── company_info/            # Company metadata
│   └── ml/                      # Training datasets
│       ├── dataset_a.parquet    # Feature snapshots
│       ├── dataset_b.parquet    # Trade labels
│       └── training_dataset_final.parquet
│
├── models/                      # Trained XGBoost models
│   └── model_m01.json
│
├── database/
│   └── trades.db                # SQLite (buy_list, trades tables)
│
├── docs/                        # 30+ markdown documentation files
├── test/                        # 35+ test scripts
├── notebooks/                   # Jupyter analysis notebooks
│
├── daily_scanner.py             # ML-enhanced stock scanner
├── dashboard.py                 # Streamlit web dashboard
├── data_curator.py              # Data maintenance utility
├── model_trainer.py             # Complete model training pipeline
├── prepare_training_dataset.py  # Dataset merging & validation
└── config.py                    # Central configuration
```

## Quick Start

### 1. Installation

#### Prerequisites
- Python 3.8+
- Virtual environment recommended

#### Setup
```bash
# Clone repository (or navigate to project directory)
cd quantamental

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

#### Dependencies Overview
- **Data**: pandas, numpy, yfinance, requests, pyarrow, fastparquet
- **ML**: xgboost, scikit-learn, optuna, shap
- **Visualization**: matplotlib, seaborn, streamlit, plotly
- **Database**: sqlite3 (built-in)

### 2. Configuration

#### API Keys
Create a `.env` file in the project root:

```bash
FMP_API_KEY=your_fmp_api_key_here
```

Get your free FMP API key at: https://site.financialmodelingprep.com/developer/docs

#### Settings ([config.py](config.py))

Key configuration parameters:

```python
# Universe Settings
UNIVERSE_SOURCE = 'FMP_SCREENER'  # ~1,730 tickers
FMP_SCREENER_PARAMS = {
    "marketCapMoreThan": 300_000_000,  # $300M minimum
    "priceMoreThan": 5,
    "volumeMoreThan": 200_000,
    "isActivelyTrading": "true"
}

# SEPA Strategy Parameters
SMA_FAST = 50
SMA_MEDIUM = 150
SMA_SLOW = 200
CONSOLIDATION_PERIOD = 20
VOL_SPIKE_THRESHOLD = 1.3

# ML Settings
ML_PRODUCTION_MODEL = 'models/model_m01.json'
ML_CONFIDENCE_THRESHOLD = 0.6
```

### 3. Initial Data Setup

```bash
# Update price cache for all tickers (~1,730 stocks)
python data_curator.py --source fmp_screener --update-prices

# Update fundamental data (optional, quarterly refresh recommended)
python data_curator.py --update-fundamentals
```

This will download and cache:
- Historical price data (5+ years of OHLCV)
- Fundamental data (income statements, balance sheets)
- Company metadata (sector, industry, market cap)

### 4. Daily Workflow

#### Option A: ML-Enhanced Scanner (Recommended)

```bash
# Run daily scanner with ML filtering
python daily_scanner.py --use-ml --scan-date 2026-01-19

# View results in web dashboard
streamlit run dashboard.py
```

The scanner will:
1. Load price data for ~1,730 tickers
2. Calculate lightweight features (12 indicators)
3. Identify SEPA candidates (~5-15 stocks)
4. Calculate heavyweight features (5 alpha factors)
5. Fetch fundamentals for candidates
6. Score with ML model (predict success probability)
7. Filter by threshold (≥ 0.6) and rank candidates
8. Save to database with ML metadata

#### Option B: Traditional Scanner (No ML)

```bash
# Run scanner without ML filtering
python daily_scanner.py --scan-date 2026-01-19
```

#### Dashboard Features

The Streamlit dashboard ([dashboard.py](dashboard.py)) provides:
- Active buy list sorted by ML rank
- Real-time ML score refresh
- Open position monitoring
- Manual override capability
- Historical prediction log

### 5. Model Training (Optional)

If you want to retrain the model with updated data:

```bash
# Complete training pipeline (Dataset B → A → Model)
python model_trainer.py --start 2020-01-01 --end 2025-12-31

# Outputs:
# - data/ml/dataset_b.parquet (trade labels)
# - data/ml/dataset_a.parquet (feature snapshots)
# - data/ml/training_dataset_final.parquet (merged)
# - models/model_m01.json (trained model)
# - evaluation/ (performance reports & plots)
```

Training pipeline steps:
1. **Build Dataset B**: Run historical trade simulator to label all SEPA signals
2. **Build Dataset A**: Extract feature snapshots at entry dates
3. **Merge Datasets**: Point-in-time join with temporal validation
4. **Train Model**: XGBoost with walk-forward validation and Optuna hyperparameter optimization

## System Architecture

### Dual-Stage Feature Engineering

The system uses a two-stage approach for computational efficiency:

#### Stage 1: Lightweight Features (All ~1,730 stocks)
- **Trend Indicators**: SMA(50, 150, 200), price position
- **Volatility**: ATR normalized by price
- **Relative Strength**: Stock vs SPY correlation
- **Volume**: Ratio to 50-day average, dry-up detection
- **VCP Indicators**: Consolidation width, tightness
- **Price Extremes**: Distance from 52-week high/low

**Purpose**: Fast SEPA screening to filter universe to ~5-15 candidates

#### Stage 2: Heavyweight Features (SEPA candidates only)
- **Alpha #001**: Volatility-adjusted close rank
- **Alpha #006**: Open-volume correlation
- **Alpha #012**: Volume-price momentum
- **Alpha #041**: Intraday strength (VWAP deviation)
- **Alpha #101**: Intraday momentum signal

**Purpose**: High-fidelity signals for ML scoring (10x faster than calculating for all stocks)

### Fundamental Integration (Point-in-Time)

Quarterly fundamental data is merged with daily price data using strict temporal alignment:

```
Raw Fundamentals (filing_date)
    ↓
Preprocessing (fundamental_processor.py)
    ├── Growth calculations (YoY revenue, EPS, net income)
    ├── Safety ratios (debt/equity, current ratio)
    └── Operating metrics (gross margin, ROE, ROA)
    ↓
As-of Join (fundamental_merger.py)
    ├── Use filing_date (public release), not fiscal_date
    ├── Forward-fill most recent data
    ├── Flag staleness (>400 days old)
    └── Hybrid features (P/E, P/B, P/S)
    ↓
Enriched Daily DataFrame (Price + Technical + Fundamental)
```

**Key Features**:
- **Temporal Integrity**: Uses `filing_date` to prevent lookahead bias
- **Staleness Detection**: Warns when fundamental data is outdated
- **Missing Value Strategy**: Graceful handling of incomplete data

### ML Training Pipeline (Walk-Forward Validation)

```
Training Dataset (1,694 labeled trades, 2020-2025)
    ↓
Temporal Splitting (model_preparation.py)
    ├── Fold 1: Train 2021-2022 (2y) → Test 2023 (1y)
    ├── Fold 2: Train 2021-2023 (3y) → Test 2024-2025 (1.9y)
    └── Purge gap: 60 days (prevents trade overlap)
    ↓
Feature Selection
    ├── Drop >99% missing (4 features removed)
    ├── Correlation filter at 0.95 (42 features removed)
    └── Optional: Top-N by SHAP importance
    ↓
XGBoost Training (train_model.py)
    ├── Class imbalance: scale_pos_weight=9 (9:1 failure:success ratio)
    ├── Metric: Precision@Top-20% (custom XGBoost objective)
    ├── Optimization: Optuna (50 trials)
    └── Early stopping: 50 rounds
    ↓
Evaluation (evaluate_model.py)
    ├── Precision@k (10%, 20%, 30%)
    ├── ROC-AUC, PR-AUC
    ├── SHAP feature importance
    └── Trading simulation (threshold sweep)
    ↓
Production Model (models/model_m01.json)
```

**Key Innovations**:
- **Precision@Top-k Metric**: Optimized for ranking (focuses on top 20% predictions)
- **Temporal Purge**: 60-day gap prevents train/test contamination
- **Point-in-Time Validation**: Ensures no lookahead bias in fundamentals

### Data Flow Summary

```
┌─────────────────────────────────────────────────────────────┐
│                     DATA ACQUISITION                         │
├─────────────────────────────────────────────────────────────┤
│ Price Data (yfinance/FMP) → data/price/*.parquet           │
│ Fundamentals (FMP API) → data/fundamentals/*.parquet       │
│ Universe (FMP Screener) → ~1,730 tickers                   │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                  FEATURE ENGINEERING                         │
├─────────────────────────────────────────────────────────────┤
│ Stage 1: Lightweight (12 features) → All stocks            │
│ SEPA Screening → Filter to ~5-15 candidates                │
│ Stage 2: Heavyweight (5 alpha factors) → Candidates only   │
│ Fundamental Merger → Point-in-time join                    │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                    ML INFERENCE                              │
├─────────────────────────────────────────────────────────────┤
│ Load Model (models/model_m01.json)                         │
│ Predict Success Probability (0.0-1.0)                      │
│ Filter by Threshold (≥ 0.6)                                │
│ Rank Candidates (1=best)                                   │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                   OUTPUT & STORAGE                           │
├─────────────────────────────────────────────────────────────┤
│ Database (database/trades.db) → buy_list table             │
│ Prediction Log (data/predictions_log.parquet)              │
│ Dashboard Display (Streamlit web app)                      │
└─────────────────────────────────────────────────────────────┘
```

## SEPA Methodology Details

### Stage Analysis

**Stage 1: Accumulation** (Not tradable)
- Price below 150-day and 200-day SMA
- Weak momentum, potential base building

**Stage 2: Advancing** (Target for entry)
- Price above rising 50-day, 150-day, and 200-day SMA
- All SMAs in proper order: SMA(50) > SMA(150) > SMA(200)
- Strong relative strength vs market
- Increasing volume on up days

**Stage 3: Distribution** (Exit or avoid)
- Price topping, SMAs flattening or crossing down

**Stage 4: Decline** (Avoid)
- Price in downtrend, below key moving averages

### Volatility Contraction Pattern (VCP)

VCP indicates institutional accumulation and readiness for breakout:

1. **Consolidation**: Price trades in tightening range (20+ days)
2. **Contraction**: Percentage width decreases over time
3. **Volume Dry-Up**: Volume decreases during consolidation
4. **Breakout**: Price breaks above resistance with volume spike (≥ 1.3x average)

### SEPA Entry Signals

A stock generates a SEPA buy signal when:
- ✓ Stage 2 uptrend confirmed (all SMA criteria met)
- ✓ VCP pattern detected (consolidation + contraction)
- ✓ Breakout triggered (close > consolidation high)
- ✓ Volume confirmation (spike ≥ 1.3x average)
- ✓ Relative strength vs SPY positive

The ML model then scores these signals to identify the highest-probability setups.

## Performance Metrics

### Model Statistics (as of latest training)

- **Training Dataset**: 1,694 labeled trades (2020-2025)
- **Class Distribution**: 1,527 failures (90.1%) : 167 successes (9.9%)
- **Feature Count**: 150+ raw → ~85 after selection
- **Model Type**: XGBoost binary classifier

### Evaluation Metrics

**Precision@Top-k** (Most relevant for trading):
- Precision@10%: ~0.30-0.35 (3-4x baseline)
- Precision@20%: ~0.20-0.25 (2-3x baseline)
- Precision@30%: ~0.15-0.20 (1.5-2x baseline)

**Standard Metrics**:
- ROC-AUC: ~0.65-0.70
- PR-AUC: ~0.20-0.25
- Recall@Threshold(0.6): ~0.40-0.50

**Interpretation**: The model successfully ranks successful trades higher than failures. By trading only the top 20% of predictions, we achieve 2-3x better precision than the baseline success rate.

## Key Features & Innovations

### 1. Temporal Integrity Enforcement
- **Perturbation Testing**: Inject future price spikes to verify no data leakage
- **Point-in-Time Joins**: Use `filing_date` for fundamentals, not `fiscal_date`
- **60-Day Purge Gap**: Prevents overlapping trades in train/test splits

### 2. Dual-Stage Feature Engineering
- Lightweight features run on full universe (fast)
- Heavyweight alphas run only on SEPA candidates (efficient)
- 10x speedup vs calculating alphas for all stocks

### 3. Precision@Top-k Optimization
- Custom XGBoost metric optimized for ranking
- Focuses on top 20% predictions (actionable signals)
- More relevant than accuracy for imbalanced datasets

### 4. Production ML Pipeline
- Automatic feature alignment (handles missing/reordered features)
- Prediction logging for feedback loop
- Database integration with ML metadata

### 5. Comprehensive Testing Suite
- 35+ test scripts for validation
- Data health monitoring ([data_health_analyzer.py](data_health_analyzer.py))
- Temporal validation ([temporal_validator.py](src/temporal_validator.py))

## Common Commands Reference

### Data Management

```bash
# Update price cache (daily/weekly)
python data_curator.py --source fmp_screener --update-prices

# Update fundamentals (quarterly)
python data_curator.py --update-fundamentals

# Check data health
python src/data_health_analyzer.py

# Clear stale cache files
python data_curator.py --clean-cache
```

### Scanning & Trading

```bash
# Daily scanner with ML
python daily_scanner.py --use-ml

# Scanner for specific date
python daily_scanner.py --use-ml --scan-date 2026-01-15

# Scanner without ML filtering
python daily_scanner.py

# Launch dashboard
streamlit run dashboard.py

# Refresh ML scores in dashboard
# (Use refresh button in UI)
```

### Model Development

```bash
# Complete training pipeline
python model_trainer.py --start 2020-01-01 --end 2025-12-31

# Build Dataset B only (trade labels)
python model_trainer.py --start 2020-01-01 --end 2025-12-31 --dataset-b-only

# Prepare training dataset (merge A + B)
python prepare_training_dataset.py

# Train model with Optuna optimization
python train_model.py --n-trials 50

# Evaluate model performance
python evaluate_model.py
```

### Testing & Validation

```bash
# Test trade simulator
python test/test_trade_simulator_fast.py

# Test ML scorer
python test/test_ml_scorer.py

# Test temporal alignment
python src/temporal_validator.py

# Test feature engineering
python test/test_features.py
```

## Data Sources

### Price Data
- **Primary**: yfinance (free, 5+ years history)
- **Fallback**: FMP API (paid, more reliable for recent data)
- **Storage**: Parquet cache (one file per ticker)
- **Update Frequency**: Daily (after market close)

### Fundamental Data
- **Source**: Financial Modeling Prep (FMP) API
- **Data Types**: Income statements, balance sheets, cash flow
- **Storage**: Parquet cache with 90-day TTL
- **Update Frequency**: Quarterly (after earnings releases)

### Universe Definition
- **Default**: FMP Stock Screener (~1,730 tickers)
  - Market cap ≥ $300M
  - Price ≥ $5
  - Volume ≥ 200K shares/day
  - Actively trading
- **Fallback**: SSGA S&P 500 Holdings (~504 tickers)

## Documentation

Comprehensive documentation available in [docs/](docs/):

### Core Concepts
- [SEPA Methodology](docs/sepa_methodology.md)
- [ML Meta-Labeling](docs/ml_metalabeling.md)
- [Trading Rules](docs/rules.md)
- [Risk Management](docs/risk_management.md)

### Technical Documentation
- [Data Pipeline](docs/data_pipeline.md)
- [Feature Engineering](docs/feature_engineering.md)
- [Model Training](docs/model_training.md)
- [Temporal Validation](docs/temporal_validation.md)

### API References
- [Data Engine](docs/api/data_engine.md)
- [Strategy Module](docs/api/strategy.md)
- [ML Scorer](docs/api/ml_scorer.md)
- [Database Schema](docs/api/database.md)

## Development Roadmap

### Current Status (Sprint 1 Complete)
- ✓ Expanded universe (504 → 1,730 tickers)
- ✓ ML-enhanced scanner operational
- ✓ Complete model training pipeline
- ✓ Database integration with ML metadata
- ✓ Streamlit dashboard
- ✓ Comprehensive documentation

### Planned Enhancements
- [ ] Macro indicators (VIX, fund spreads, market regime detection)
- [ ] Cross-sectional rankings (sector-relative strength)
- [ ] Feature normalization EDA and optimization
- [ ] Multi-day scanner optimization
- [ ] Automated feedback loop (update outcomes when trades close)
- [ ] Alerting system (email/SMS notifications for high-rank signals)

## Troubleshooting

### Common Issues

**1. API Rate Limits (FMP)**
```bash
# Use yfinance fallback
# Automatically handled by data_engine.py
# Or reduce universe size in config.py
```

**2. Stale Cache Files**
```bash
# Check data health
python src/data_health_analyzer.py

# Clean stale files
python data_curator.py --clean-cache
```

**3. Missing Fundamental Data**
```bash
# Some stocks may have incomplete fundamentals
# System handles gracefully with NaN strategy
# Check data/fundamentals/*.parquet for coverage
```

**4. Model Prediction Errors**
```bash
# Verify model file exists
ls models/model_m01.json

# Check feature alignment
python test/test_ml_scorer.py

# Retrain if necessary
python model_trainer.py --start 2020-01-01 --end 2025-12-31
```

## Project History

- **2020-2021**: Initial backtesting framework, SEPA strategy implementation
- **2022-2023**: Fundamental data integration, WorldQuant alpha factors
- **2024**: ML meta-labeling framework, XGBoost training pipeline
- **2025**: Production scanner, dashboard, expanded universe
- **Sprint 1 (2026-01)**: Major refactoring, FMP screener integration, comprehensive docs

## License

Private project. All rights reserved.

## Contact & Support

For issues, questions, or enhancements, refer to:
- Internal documentation: [docs/](docs/)
- Project tracker: [tracker.todo](tracker.todo)
- Development notes: [.claude/CLAUDE.md](.claude/CLAUDE.md)

---

**Disclaimer**: This system is for educational and personal use only. Past performance does not guarantee future results. Trading stocks involves risk of loss. Always conduct your own research and consult with a financial advisor before making investment decisions.
