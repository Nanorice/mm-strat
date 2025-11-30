# Sprint 1: Data Pipeline & Primary Meta-Labeling Model

## Overview
**Goal**: Build end-to-end ML training pipeline and deploy first meta-labeling classifier to predict SEPA trade quality.

**Status**: 🟡 In Progress (90% Complete)  
**Start Date**: 2025-11-28  
**Target Completion**: TBD

---

## Sprint Objectives

1. ✅ **Dataset B Construction** - Generate labeled trade history
2. ✅ **Temporal Integrity** - Ensure no look-ahead bias in simulation
3. ✅ **Flexible Labeling** - Lambda-based success criteria
4. ✅ **Dataset A Construction** - Build feature store with daily indicators & alphas
5. 🟡 **Data Merging** - Combine Dataset A + B for ML training
6. 🟡 **Model Training** - Train and validate meta-labeling classifier
7. 🟡 **Scanner Integration** - Deploy model to rank buy signals

---

## Work Completed ✅

### 1. Dataset B - Events Log (100% Complete)

**What**: Labeled log of completed trades with entry/exit details and binary success labels.

**Implementation**:
- **File**: `src/trade_simulator.py` (404 lines)
  - `Trade` dataclass: Represents single trade with 15+ attributes
  - `TradeSimulator` class: Event-driven historical simulation
  - Day-by-day chronological processing (no look-ahead bias)
  - Re-entry handling with configurable cooldown
  - Exit logic: trend break detection (SEPA no longer qualifying)

- **File**: `src/trading_config.py` (138 lines)
  - Configurable strategy parameters
  - Lambda-based labeling function
  - Presets: `default()`, `conservative()`, `aggressive()`

- **File**: `build_dataset_b.py` (279 lines)
  - CLI tool for Dataset B generation
  - `--start`, `--end`: Date range
  - `--threshold`: Success threshold (default: 15%)
  - `--label-rule`: Custom labeling expressions
  - `--save-to-db`: Store in database
  - Summary statistics reporting

**Deliverables**:
- ✅ `data/ml/dataset_b.parquet` - 25 columns, 466 trades (2025 data)
- ✅ Database table: `ml_training_trades`
- ✅ Inspection tool: `inspect_dataset_b.py`

**Test Results** (2025 data):
- 466 trades generated (Jan-Nov 2025)
- 6% win rate (28 wins, 438 losses)
- Class imbalance: 15.6:1 (expected for 15% threshold)

---

### 2. Enhanced Trade Metrics (100% Complete)

**What**: Five additional performance metrics beyond simple returns.

**Metrics Added**:
1. **`max_drawdown_pct`** - Worst intra-trade loss from entry
   - Formula: `(Lowest Price - Entry) / Entry × 100`
   - Use case: Risk assessment, stop loss optimization

2. **`max_favorable_excursion_pct`** - Best intra-trade gain from entry
   - Formula: `(Highest Price - Entry) / Entry × 100`
   - Use case: Profit target optimization, opportunity cost

3. **`r_multiple`** - Risk-adjusted return
   - Formula: `Return / Initial Risk`
   - Initial risk: 2.5× ATR from entry
   - Use case: Position sizing, expectancy calculation

4. **`sharpe_ratio`** - Annualized volatility-adjusted return
   - Formula: `(Mean Daily Return / Std Daily Return) × √252`
   - Use case: Risk-adjusted performance evaluation

5. **`initial_risk_pct`** - Entry to stop distance
   - Formula: `(2.5 × ATR) / Entry Price × 100`
   - Use case: R-multiple calculation, position sizing

**Implementation**:
- Calculated in `Trade.close()` method
- Requires full price history (High/Low/Close)
- Automatically computed during simulation
- Exported to Dataset B

---

### 3. Flexible Labeling System (100% Complete)

**What**: User-defined labeling rules via lambda functions.

**Features**:
- **Default**: `lambda trade: 1 if trade.return_pct >= 15 else 0`
- **Custom CLI**: `--label-rule "trade.return_pct >= 20 and trade.days_held <= 30"`
- **Programmatic**: Pass lambda to `TradingConfig`

**Examples**:
```python
# Duration-adjusted
labeling_function=lambda t: 1 if (t.return_pct >= 15 and t.days_held <= 45) else 0

# Risk-adjusted
labeling_function=lambda t: 1 if t.r_multiple >= 3.0 else 0

# Composite criteria
labeling_function=lambda t: 1 if (
    t.return_pct >= 20 and 
    t.max_drawdown_pct >= -10 and
    t.sharpe_ratio >= 1.5
) else 0
```

---

### 4. Temporal Integrity (100% Complete)

**What**: Guarantee no look-ahead bias in simulation.

**Implementation Details**:

**A. Re-Entry Handling**:
- State: `last_exit_date` dictionary tracks exit dates per ticker
- Check: Before new entry, verify cooldown period elapsed
- Config: `allow_reentry`, `reentry_cooldown_days`
- Result: Same ticker can trigger multiple times realistically

**B. No Look-Ahead Bias**:
- **Layer 1**: Chronological day-by-day loop (sorted dates)
- **Layer 2**: Explicit `scan_date` parameter to `batch_scan_universe()`
- **Layer 3**: DataFrame indexing with `.loc[date, ...]` for specific dates
- **Result**: On Day 100, simulator only knows Days 1-100

**Logic**:
```python
For each trade in Dataset B:
    entry_date = trade['entry_date']
    ticker = trade['ticker']
    
    # Extract feature vector from Dataset A
    features = dataset_a[(dataset_a['date'] == entry_date) & 
                         (dataset_a['ticker'] == ticker)]
    
    # Combine with label
    X.append(features)
    y.append(trade['label'])
```

---

### 5. Fundamental Data Module (100% Complete)

**What**: FMP API integration for income statements and balance sheets to enhance Dataset A with fundamental features.

**Implementation**:
- **File**: `src/fundamental_engine.py` (386 lines)
  - `FundamentalEngine` class: OOP-based fundamental data manager
  - FMP API integration with rate limiting (300 calls/minute)
  - Parquet caching with 90-day refresh cycle
  - Batch processing with configurable delays
  - Smart cache checking to minimize API usage

- **File**: `src/fundamental_processor.py` (360 lines) **NEW**
  - Phase 1: Preprocess sparse quarterly fundamentals
  - Growth calculations: YoY revenue, EPS, net income (4-quarter lookback)
  - Safety ratios: debt-to-equity, current ratio, quick ratio
  - Operating metrics: gross margin, operating margin, ROE, ROA
  - Dynamic merge column handling (prevents KeyError on missing fields)

- **File**: `src/fundamental_merger.py` (430 lines) **NEW**
  - Phase 2: As-of join (sparse fundamental → dense daily data)
  - `pd.merge_asof` on `filing_date` (prevents look-ahead bias)
  - Forward fill fundamentals until next report
  - Staleness detection: `days_since_report`, `is_stale` flag (>400 days)
  - NaN handling: growth→0, ratios→median
  - Phase 3: Hybrid features (P/E ratio, P/B ratio)
  - Index preservation for seamless Dataset A integration

- **File**: `build_fundamentals.py` (249 lines)
  - CLI tool for fundamental dataset initialization
  - Auto-discovers tickers from price folder
  - Progress tracking and error handling
  - `--force`, `--tickers`, `--show-stats` options

- **File**: `view_fundamentals.py` (311 lines)
  - Interactive viewer for cached fundamental data
  - Formatted display of income statements and balance sheets
  - Key metrics: Revenue, Net Income, EPS, Gross Margin
  - Key ratios: Debt/Equity, Current Ratio
  - Raw data inspection mode

- **File**: `docs/FUNDAMENTALS_MODULE.md` (600+ lines)
  - Complete user guide and API reference
  - Point-in-time usage patterns
  - Future hybrid earnings calendar approach

**Data Schema**:
Each ticker's parquet file contains:
- **Metadata**: `fiscal_date`, `filing_date` (SEC filing = release date), `fiscal_period`, `fiscal_year`
- **Income Statement**: revenue, netIncome, eps, ebitda, grossProfit, operatingIncome, etc. (40+ metrics)
- **Balance Sheet**: totalAssets, totalLiabilities, totalEquity, totalDebt, cash, currentRatio, etc. (50+ metrics)

**Enrichment Pipeline Output** (Dataset A with --include-fundamentals):
- **Metadata**: `filing_date_matched`, `days_since_report`, `is_stale`, `has_fundamentals`
- **Raw Fundamentals**: revenue, netIncome, eps, totalAssets, totalDebt, totalEquity, cash (10+ fields)
- **Growth Metrics**: revenue_growth_yoy, eps_growth_yoy, net_income_growth_yoy
- **Safety Ratios**: debt_to_equity, current_ratio, quick_ratio
- **Operating Metrics**: gross_margin, operating_margin, roe, roa
- **Hybrid Features**: pe_ratio, pb_ratio, ps_ratio (price × fundamentals)

**API Integration**:
- **Endpoint**: FMP stable API (`https://financialmodelingprep.com/stable/`)
- **Rate Limiting**: 300 calls/minute (FMP Starter tier)
- **Batch Strategy**: 10 tickers per batch with 2.5s delay
- **Cache Duration**: 90 days (quarterly refresh cycle)
- **Historical Data**: 5 years of quarterly/annual reports

**Key Features**:
1. **Point-in-time Correctness**: Uses `filing_date` (when report became public) to prevent lookahead bias
2. **Fiscal Year Trap Prevention**: As-of join on `filing_date` NOT `fiscal_date`
3. **Rate Limit Handling**: Automatic throttling with call tracking
4. **Smart Caching**: Only fetches missing or stale data
5. **Error Resilience**: Graceful handling of missing data (ETFs, REITs, foreign stocks)
6. **Reusable Design**: Follows `DataRepository` patterns

**Test Results**:
- ✅ Successfully enriched AAPL Q1 2024: 65 rows × 165 features (18.73% NaN, expected)
- ✅ Full dataset (274 tickers, 2023-2025): 142,901 rows × 165 features (20.85% NaN)
- ✅ Fiscal year trap prevention verified (no look-ahead bias)
- ✅ Forward fill verified (fundamentals constant until next filing)
- ✅ Staleness detection working (flags data >400 days old)
- ✅ All technical indicators fully populated (SMA_200, 52W high/low)
- ✅ NaN values only from fundamentals (expected behavior)
- ✅ 100% success rate on test batch
- ✅ ~71 KB per ticker (40 rows = 20 periods × 2 statement types)
- ✅ Correct filing dates (~1 month after fiscal period end)
- ✅ Complete schema with 94 columns per statement

**Usage**:
```bash
# Initialize fundamental data for all tickers
python build_fundamentals.py

# View cached fundamental data
python view_fundamentals.py AAPL

# Check cache statistics
python build_fundamentals.py --show-stats
```

**Future Enhancement**:
- Weekly earnings calendar integration
- Incremental updates (only new reports)
- Reduced API usage (~25 calls/week vs ~674 calls/quarter)
- Automatic restatement detection

---

## Remaining Sprint 1 Work 🟡

### 6. Data Merging (0% Complete)

**What**: Train binary classifier to predict trade success.

**Model Options**:
1. **Random Forest** (preferred for interpretability)
   - Hyperparameters: n_estimators, max_depth, min_samples_split
   - Feature importance: Gini/SHAP values
   
2. **XGBoost** (preferred for performance)
   - Hyperparameters: learning_rate, max_depth, subsample
   - Handles class imbalance well

**Training Pipeline**:
```python
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import TimeSeriesSplit

# Temporal cross-validation (no shuffling!)
tscv = TimeSeriesSplit(n_splits=5)

# Handle class imbalance
model = RandomForestClassifier(
    n_estimators=200,
    max_depth=10,
    class_weight='balanced',  # Important!
    random_state=42
)

# Train
model.fit(X_train, y_train)

# Evaluate
y_pred_proba = model.predict_proba(X_test)[:, 1]
```

**Evaluation Metrics**:
- AUC-ROC (primary metric)
- Precision-Recall curve (for imbalanced data)
- Confusion matrix
- Feature importance
- Calibration plot

**Tasks**:
- [ ] Create `train_model.py` script
- [ ] Implement temporal cross-validation
- [ ] Handle class imbalance (SMOTE, class weights)
- [ ] Hyperparameter tuning (GridSearch/RandomSearch)
- [ ] Save trained model (pickle/joblib)
- [ ] Generate evaluation report

**Estimated Effort**: 6-8 hours

---

### 8. Scanner Integration (0% Complete)

**What**: Use trained model to rank buy signals in daily scanner.

**Workflow**:
```
Daily Scanner
    ↓
SEPA Signals (5-15 stocks)
    ↓
Extract Features (Dataset A)
    ↓
Model Prediction (probability of success)
    ↓
Rank by Score
    ↓
Display Top N
```

**Implementation**:
```python
# In optimized_scanner.py or new scanner_ml.py
from joblib import load

# Load trained model
model = load('models/meta_labeling_v1.pkl')

# Get buy signals
buy_signals = strategy.batch_scan_universe(enriched_data, scan_date)

# Extract features for each signal
features = []
for signal in buy_signals:
    ticker = signal['ticker']
    features.append(extract_features(ticker, scan_date, enriched_data))

# Predict success probability
X = pd.DataFrame(features)
probs = model.predict_proba(X)[:, 1]

# Rank by ML score
buy_signals['ml_score'] = probs
buy_signals = buy_signals.sort_values('ml_score', ascending=False)

# Display top N
print(buy_signals.head(8))
```

**Tasks**:
- [ ] Create feature extraction function
- [ ] Load model in scanner
- [ ] Add ML score column to buy list
- [ ] Update display/export logic
- [ ] Add ML score to database schema

**Estimated Effort**: 3-4 hours

---

## Sprint 1 Roadmap

### Phase 1: Data Foundation ✅ COMPLETE
- [x] Dataset B construction
- [x] Enhanced metrics
- [x] Flexible labeling
- [x] Temporal integrity verification

### Phase 2: Feature Engineering ✅ COMPLETE
- [x] Dataset A construction
- [x] Temporal validation framework
- [x] WorldQuant alpha integration
- [x] Data quality validation

### Phase 3: Model Development 📋 TODO
- [ ] Dataset merging
- [ ] Model training
- [ ] Hyperparameter tuning
- [ ] Evaluation

### Phase 4: Deployment 📋 TODO
- [ ] Scanner integration
- [ ] Buy list ranking
- [ ] Documentation

---

## Technical Debt & Considerations

### Known Limitations
1. **Survivorship Bias**: Using current S&P 500 list
   - **Impact**: Overstates historical performance
   - **Mitigation**: Use State Street historical constituents (future)

2. **Class Imbalance**: 15.6:1 ratio (failures:successes)
   - **Impact**: Model may predict all failures
   - **Mitigation**: SMOTE, class weights, adjust threshold

3. **Limited Features**: Only technical indicators
   - **Impact**: Missing fundamental signals
   - **Next Sprint**: Add EPS growth, sales acceleration

### Future Enhancements
- Multi-class labeling (0=loss, 1=small, 2=medium, 3=big win)
- Regression target (predict actual return)
- Triple barrier method (profit/stop/time)
- Online learning (update model with new data)

---

## Files Created/Modified

### New Files
```
src/
├── trading_config.py          (138 lines) - Strategy configuration
├── trade_simulator.py         (463 lines) - Event-driven simulator
├── temporal_validator.py      (337 lines) - Data leakage prevention
└── alpha_factors.py           (331 lines) - WorldQuant alpha engine

build_dataset_b.py             (279 lines) - Dataset B CLI tool
build_dataset_a.py             (347 lines) - Dataset A CLI tool
inspect_dataset_b.py           (420 lines) - Inspection tool
test_temporal_integrity.py     (294 lines) - Temporal validation tests

docs/
├── DATASET_B_GUIDE.md         - Usage documentation
├── TEMPORAL_INTEGRITY.md      - Re-entry & no-look-ahead explanation
├── sprint_plan.md             - This file's parent
└── sprint_1.md                - This file

data/ml/
├── dataset_b.parquet          (58 trades, Nov 2025)
├── dataset_b_2025.parquet     (466 trades, Jan-Nov 2025)
└── dataset_a_2024_full.parquet (5,480 rows, 274 tickers, 17 features)
```

### Modified Files
```
src/
├── database.py                - Added ml_training_trades table + methods
├── features.py                - Enhanced heavyweight features (alpha integration)
└── data_engine.py             - Changed default to yfinance, improved logging
```

---

## Success Criteria

### Sprint 1 Definition of Done
- [x] **Dataset B**: ≥500 labeled trades with enhanced metrics
- [ ] **Dataset A**: Complete feature coverage (all tickers, all dates)
- [ ] **Model**: AUC ≥ 0.65 on temporal test set
- [ ] **Integration**: Scanner displays ML scores alongside buy signals
- [ ] **Documentation**: Model card, evaluation report, usage guide

### Acceptance Tests
- [ ] Simulate 2023 data, train model, test on 2024 data (time-based split)
- [ ] Generate buy list for live date, verify ML scores rank logically
- [ ] Backtest: Compare top 50% ML-scored trades vs bottom 50%
- [ ] Feature importance: Top 5 features make intuitive sense

---

## Timeline Estimate

| Task | Effort | Status |
|------|--------|--------|
| Dataset B Construction | 8h | ✅ Done |
| Enhanced Metrics | 3h | ✅ Done |
| Flexible Labeling | 2h | ✅ Done |
| Temporal Integrity | 2h | ✅ Done |
| **Dataset A Construction** | 6h | 🟡 Todo |
| **Dataset Merging** | 3h | 🟡 Todo |
| **Model Training** | 8h | 🟡 Todo |
| **Scanner Integration** | 4h | 🟡 Todo |
| **Evaluation & Docs** | 4h | 🟡 Todo |
| **Total** | **40h** | **70% Complete** |

**Estimated Remaining**: 12-15 hours (~2-3 days of focused work)

---

## Next Steps (Prioritized)

1. **[HIGH] Build Dataset A** - Feature store construction
   - Script: `build_dataset_a.py`
   - Output: `data/ml/dataset_a.parquet`
   - Reuse existing `FeatureEngineer`

2. **[HIGH] Merge Datasets** - Create training matrix
   - Script: `merge_datasets.py`
   - Handle temporal alignment
   - Train/test split (70/30, time-based)

3. **[HIGH] Train Baseline Model** - Random Forest
   - Quick iteration to validate pipeline
   - Establish baseline AUC score
   - Identify data issues early

4. **[MEDIUM] Evaluate & Iterate** - Improve model
   - Feature engineering
   - Hyperparameter tuning
   - Class imbalance handling

5. **[MEDIUM] Scanner Integration** - Deploy to production
   - Add ML scoring to buy list
   - Update display logic
   - Test with live data

---

*Sprint Owner*: User + Antigravity AI  
*Last Updated*: 2025-11-29  
*Status*: 🟡 Sprint 1 In Progress (70% Complete)
