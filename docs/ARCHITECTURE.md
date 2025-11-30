# Quantamental SEPA System - Architecture Overview

## System Purpose

The Quantamental SEPA System (QSS) is a **meta-labeling ML framework** for ranking and filtering SEPA (Specific Entry Point Analysis) buy signals. It combines technical analysis with machine learning to predict trade quality before entry.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    QSS SYSTEM ARCHITECTURE                      │
└─────────────────────────────────────────────────────────────────┘

1. DATA LAYER
   ├── data_engine.py          → Price data loading & caching
   ├── FMP API / yfinance       → External data sources
   └── Parquet cache            → Local storage

2. FEATURE ENGINEERING LAYER
   ├── features.py              → Technical indicators (SMA, ATR, RS, etc.)
   ├── alpha_factors.py         → WorldQuant alpha factors
   ├── fundamental_merger.py    → Fundamental integration (P/E, Growth)
   └── temporal_validator.py    → Prevents data leakage

3. STRATEGY LAYER
   ├── strategy.py              → SEPA signal generation
   └── trade_simulator.py       → Historical simulation

4. MACHINE LEARNING LAYER
   ├── Dataset A (features)     → Daily technical + fundamental indicators
   ├── Dataset B (labels)       → Trade outcomes from simulation
   ├── Model Training           → XGBoost with walk-forward validation
   │   ├── model_preparation.py → Temporal splitting & feature selection
   │   ├── train_model.py       → XGBoost training with Optuna
   │   └── evaluate_model.py    → Comprehensive evaluation suite
   └── Production Inference     → ML scoring for live signals
       └── ml_scorer.py         → MLScorer class for scoring

5. APPLICATION LAYER
   ├── optimized_scanner.py     → ML-enhanced scanner (--use-ml flag)
   ├── build_dataset_a.py       → Feature store builder
   ├── build_dataset_b.py       → Trade history builder
   └── prepare_training_dataset.py → Dataset A + B merger
```

## Module Breakdown

### 📦 Core Modules

#### `src/data_engine.py`
**Purpose**: Data acquisition, caching, and management

**Key Classes**:
- `DataRepository`: Central hub for all market data operations

**Key Methods**:
```python
# Ticker universe management
update_universe() → List[str]                    # Get S&P 500 tickers
get_ticker_list_from_ssga() → List[str]         # Download from SSGA

# Price data retrieval
get_ticker_data(ticker, source='yfinance') → DataFrame   # Single ticker
get_batch_data(tickers) → Dict[str, DataFrame]           # Multiple tickers
update_cache(tickers, force=False) → Dict[str, bool]     # Batch download

# Benchmark data
get_benchmark_data() → DataFrame                 # SPY for relative strength
```

**Data Flow**:
```
External Sources (FMP/yfinance)
    ↓
update_cache() → Downloads OHLCV
    ↓
Parquet Cache (data/price/*.parquet)
    ↓
get_ticker_data() → Returns DataFrame
```

**Usage**:
```python
repo = DataRepository()
tickers = repo.update_universe()        # ~500 S&P 500 tickers
repo.update_cache(tickers, force=False) # Cache price data
price_data = repo.get_ticker_data('AAPL')  # Get AAPL OHLCV
```

---

#### `src/features.py`
**Purpose**: Technical indicator calculation and feature engineering

**Key Classes**:
- `TechnicalAnalysis`: Low-level indicator calculations (SMA, ATR, etc.)
- `FeatureEngineer`: High-level feature orchestration (dual-stage architecture)

**Key Methods**:
```python
# FeatureEngineer
calculate_lightweight_features(df) → DataFrame   # Fast indicators (12 features)
calculate_heavyweight_features(df, ticker) → DataFrame  # Slow alphas (5 features)
process_universe_batch(ticker_data) → Dict[str, DataFrame]  # Batch processing

# TechnicalAnalysis
add_sma(df, periods=[50, 150, 200]) → DataFrame
add_atr(df, period=14) → DataFrame
add_relative_strength(df, benchmark) → DataFrame
add_volume_metrics(df) → DataFrame
```

**Dual-Stage Architecture**:
```
Stage 1: LIGHTWEIGHT (runs on 500+ stocks daily)
  ├── SMA_50, SMA_150, SMA_200
  ├── ATR, nATR (normalized)
  ├── VCP_Ratio (volatility contraction)
  ├── Consolidation_Width (base tightness)
  ├── RS, Vol_Ratio, Dry_Up_Volume
  └── 52-week high/low, breakout signals
  → 16 features total

Stage 2: HEAVYWEIGHT (runs only on 5-15 SEPA candidates)
  ├── Alpha #001: Volatility-adjusted close
  ├── Alpha #006: Open-volume correlation
  ├── Alpha #009: Trend sustainability (NEW)
  ├── Alpha #012: Volume-price momentum
  ├── Alpha #041: Intraday strength
  └── Alpha #101: Intraday momentum
  → 6 alphas total
```

**Usage**:
```python
fe = FeatureEngineer(benchmark_data=spy_data)

# Calculate lightweight features
df_light = fe.calculate_lightweight_features(price_data)

# Add heavyweight features for qualified stocks
df_full = fe.calculate_heavyweight_features(df_light, 'NVDA')

# Batch process entire universe
ticker_data = {'AAPL': df1, 'MSFT': df2, ...}
enriched = fe.process_universe_batch(ticker_data)
```

---

#### `src/alpha_factors.py`
**Purpose**: WorldQuant alpha factor computation with temporal integrity

**Key Classes**:
- `AlphaEngine`: Wrapper around WorldQuant_101 with data leakage prevention

**Key Methods**:
```python
__init__(alpha_list=[1, 6, 12, 41, 101])  # Select alphas
calculate_alphas(df) → DataFrame           # Add alpha columns
get_alpha_names() → List[str]              # List alpha column names
validate_alpha_output(df) → bool           # Verify all alphas present
```

**Alpha Selection (Sprint 1)**:
```python
DEFAULT_ALPHAS = [1, 6, 12, 41, 101]  # Time-series only, no rank()

# Alpha #001: sign(delta(close)) × (-1 × delta(close))^2 / volume
# Alpha #006: -1 × correlation(open, volume, 10)
# Alpha #012: sign(delta(volume)) × (-1 × delta(close))
# Alpha #041: √(high × low) - vwap
# Alpha #101: (close - open) / (high - low + 0.001)
```

**Usage**:
```python
engine = AlphaEngine(alpha_list=[1, 6, 101])
df_with_alphas = engine.calculate_alphas(price_data)
print(df_with_alphas[['Close', 'alpha001', 'alpha006', 'alpha101']].tail())
```

---

#### `src/fundamental_processor.py`
**Purpose**: Preprocessing and standardization of sparse quarterly fundamental data

**Key Classes**:
- `FundamentalProcessor`: Handles growth, ratios, and metric calculations

**Key Methods**:
```python
process_ticker_fundamentals(ticker, df) → DataFrame  # Main pipeline
_calculate_growth_metrics(df) → DataFrame            # YoY Revenue, EPS, Net Income
_calculate_safety_ratios(df) → DataFrame             # Debt/Equity, Current Ratio
_calculate_operating_metrics(df) → DataFrame         # Margins, ROE, ROA
```

**Features**:
- **Date Standardization**: Aligns fiscal vs filing dates
- **Growth Calculation**: 4-quarter lookback for YoY changes
- **Metric Derivation**: Calculates 15+ derived ratios from raw data

---

#### `src/fundamental_merger.py`
**Purpose**: Merging sparse fundamentals with dense daily price data (Point-in-Time)

**Key Classes**:
- `FundamentalMerger`: Performs as-of joins and hybrid feature calculation

**Key Methods**:
```python
merge_ticker_data(ticker, price_df) → DataFrame      # Main merge logic
_as_of_join(price_df, fund_df) → DataFrame           # Temporal join on filing_date
calculate_hybrid_features(df) → DataFrame            # P/E, P/B, P/S calculation
_handle_missing_fundamentals(df) → DataFrame         # NaN handling strategy
```

**Key Concepts**:
- **Fiscal Year Trap Prevention**: Joins on `filing_date` (public release) NOT `fiscal_date`
- **Staleness Detection**: Flags data older than 400 days
- **Hybrid Features**: Combines daily Price with quarterly EPS/Book Value

---

#### `src/temporal_validator.py`
**Purpose**: Ensure no data leakage in feature engineering

**Key Classes**:
- `TemporalValidator`: Validation and testing for temporal alignment

**Key Methods**:
```python
validate_no_future_leakage(df, entry_date) → bool
get_feature_data_for_entry(df, entry_date) → DataFrame

# Gold standard test for data leakage
perturbation_test(calculate_features_fn, ticker, entry_date, 
                  feature_name, spike_magnitude=100.0) → bool

# Manual verification against TradingView
manual_audit(df, ticker, entry_date, feature_values,
             expected_values, tolerance=0.5) → bool
```

**Perturbation Test Concept**:
```
1. Calculate features with original data     → Feature_A
2. Inject massive spike in FUTURE data       → Feature_B
3. If Feature_A ≠ Feature_B → DATA LEAKAGE!
4. If Feature_A == Feature_B → No leakage ✅
```

**Usage**:
```python
validator = TemporalValidator()

def calc_features(df):
    fe = FeatureEngineer()
    return fe.calculate_lightweight_features(df)

# Test for leakage
passed = validator.perturbation_test(
    calculate_features_fn=calc_features,
    ticker='AAPL',
    entry_date=pd.Timestamp('2024-11-05'),
    feature_name='SMA_50',
    spike_magnitude=100.0
)
```

---

#### `src/strategy.py`
**Purpose**: SEPA signal generation and stock screening

**Key Classes**:
- `SEPAStrategy`: Implements Specific Entry Point Analysis rules

**Key Methods**:
```python
# Modular SEPA components
check_trend_template(df, date) → dict       # Stage 2 uptrend check
check_vcp_structure(df, date) → dict        # Volatility contraction
check_trigger_conditions(df, date) → dict   # Volume breakout

# Main orchestration
generate_signals(df) → List[dict]           # All historical signals
batch_scan_universe(enriched_data, scan_date) → dict  # Scan multiple stocks

# Helpers
screen_candidates(df, date) → bool          # Quick pass/fail filter
```

**SEPA Logic**:
```
1. TREND TEMPLATE (Stage 2 Detection)
   └── Price > SMA_50 > SMA_150 > SMA_200
   
2. VCP STRUCTURE (Volatility Contraction)
   └── Consolidation near 52-week high
   
3. TRIGGER CONDITIONS (Buy Signal)
   └── Price breaks above 20-day high
   └── Volume > 130% of 50-day average
```

**Usage**:
```python
strategy = SEPAStrategy(benchmark_data=spy_data)

# Scan single stock
enriched_df = fe.calculate_lightweight_features(price_data)
signals = strategy.generate_signals(enriched_df)

# Scan entire universe for specific date
scan_results = strategy.batch_scan_universe(
    enriched_data={'AAPL': df1, 'MSFT': df2, ...},
    scan_date=pd.Timestamp('2024-11-15')
)
```

---

#### `src/trade_simulator.py`
**Purpose**: Historical trade simulation for Dataset B generation

**Key Classes**:
- `Trade`: Dataclass representing a single trade
- `TradeSimulator`: Event-driven simulation engine

**Key Methods**:
```python
# TradeSimulator
run_simulation() → DataFrame                # Main simulation loop
get_dataset_b() → DataFrame                 # Export to Dataset B format
get_summary_statistics() → dict             # Performance metrics

# Trade
close(exit_date, exit_price, exit_reason)  # Close trade and calculate metrics
to_dict() → dict                            # Export to dictionary
```

**Simulation Flow**:
```
Initialize
    ↓
Load universe price data
    ↓
Calculate features for all tickers
    ↓
For each trading day (chronological):
    ├── Check for exits (trend break, stop loss)
    └── Check for new entries (SEPA signals)
    ↓
Close remaining positions
    ↓
Export Dataset B
```

**Trade Metrics Calculated**:
```python
# Basic
return_pct, days_held, exit_reason, label

# Enhanced (NEW in Sprint 1)
max_drawdown_pct              # Worst intra-trade loss
max_favorable_excursion_pct   # Best intra-trade gain
r_multiple                     # Risk-adjusted return
sharpe_ratio                  # Annualized Sharpe
initial_risk_pct              # Entry to stop distance
```

**Usage**:
```python
simulator = TradeSimulator(
    data_repo=DataRepository(),
    strategy=SEPAStrategy(),
    feature_engine=FeatureEngineer(),
    start_date='2024-01-01',
    end_date='2024-12-31',
    config=TradingConfig.default()
)

dataset_b = simulator.run_simulation()
stats = simulator.get_summary_statistics()
```

---

#### `src/trading_config.py`
**Purpose**: Configuration and labeling for trade simulation

**Key Classes**:
- `TradingConfig`: Simulation parameters and labeling function

**Key Attributes**:
```python
success_threshold_pct: float = 15.0          # Label threshold
exit_on_trend_break: bool = True             # Exit when SEPA fails
exit_on_stop_loss: bool = False              # ATR-based stop loss
stop_loss_pct: float = 8.0                   # Stop distance
allow_reentry: bool = True                   # Re-enter same stock
reentry_cooldown_days: int = 5               # Days before re-entry
labeling_function: callable                  # Custom labeling logic
```

**Presets**:
```python
TradingConfig.default()       # Standard SEPA (15% threshold)
TradingConfig.conservative()  # 10% threshold, less selective
TradingConfig.aggressive()    # 20% threshold, big winners only
```

**Custom Labeling**:
```python
# Duration-adjusted
config = TradingConfig(
    labeling_function=lambda t: 1 if (t.return_pct >= 15 and t.days_held <= 45) else 0
)

# Risk-adjusted
config = TradingConfig(
    labeling_function=lambda t: 1 if t.r_multiple >= 3.0 else 0
)

# Composite
config = TradingConfig(
    labeling_function=lambda t: 1 if (
        t.return_pct >= 20 and
        t.max_drawdown_pct >= -10 and
        t.sharpe_ratio >= 1.5
    ) else 0
)
```

---

#### `src/dataset_merger.py`
**Purpose**: OOP-based module for merging Dataset A (features) and Dataset B (labels)

**Key Classes**:
- `DatasetLoader`: Handles loading and validation of datasets
- `SnapshotExtractor`: Performs fast (ticker, date) feature extraction
- `DatasetMerger`: Orchestrates the merge process

**Key Methods**:
```python
# DatasetLoader
load_dataset_a(path) → DataFrame
load_dataset_b(path) → DataFrame

# SnapshotExtractor
extract_snapshot(ticker, date) → Series
batch_extract(trades_df) → DataFrame

# DatasetMerger
merge(strategy='left') → DataFrame
get_merge_statistics() → dict
export(path, format='parquet')
```

**Merge Logic**:
- **Snapshot Join**: Extracts features from Dataset A exactly on the trade entry date
- **MultiIndex**: Uses `(ticker, date)` index for O(1) lookups
- **Validation**: Checks for date/ticker overlap and missing snapshots

---

#### `src/ml_scorer.py`
**Purpose**: Production ML inference for SEPA signal ranking and filtering

**Key Classes**:
- `MLScorer`: XGBoost model loader and batch scorer

**Key Methods**:
```python
# MLScorer
__init__(model_path, metadata_path=None, log_predictions=True)
score_batch(X, ticker_column='ticker', date_column=None) → (probabilities, ranks)
filter_by_threshold(X, probabilities, ranks, threshold=0.6, top_n=None) → DataFrame
get_model_info() → dict

# Utility functions
update_prediction_log_with_outcome(ticker, prediction_date, actual_return_pct, actual_label)
analyze_prediction_accuracy(log_path) → dict
```

**Key Features**:
- **Strict Feature Alignment**: Automatically reorders features to match training
- **Missing Feature Handling**: Fills missing features with NaN
- **Infinite Value Handling**: Replaces inf with NaN (XGBoost compatible)
- **Metadata Validation**: Ensures model version and feature compatibility
- **Prediction Logging**: Automatic logging to `data/predictions_log.parquet`
- **Batch Processing**: Efficient vectorized scoring
- **Ranking**: Calculates ranks (1=best) for prioritization

**Usage**:
```python
from src.ml_scorer import MLScorer

# Initialize
scorer = MLScorer(model_path='models/model_fold_1.json')

# Score batch
probabilities, ranks = scorer.score_batch(candidates_df, ticker_column='ticker')

# Filter by threshold
filtered = scorer.filter_by_threshold(
    candidates_df,
    probabilities,
    ranks,
    threshold=0.6
)

# Get model info
info = scorer.get_model_info()
print(f"Model version: {info['model_version']}")
print(f"Features: {len(info['feature_names'])}")
```

**Prediction Logging Schema**:
```python
# Logged to data/predictions_log.parquet
{
    'ticker': str,
    'prediction_date': datetime,
    'ml_probability': float,       # 0.0-1.0
    'ml_rank': int,                 # 1=best
    'model_version': str,           # Training date
    'model_path': str,              # Model filename
    'actual_return_pct': float,     # Filled when trade closes
    'actual_label': int,            # Filled when trade closes
    'logged_at': datetime
}
```

**Feedback Loop**:
```python
# When trade closes, update outcomes
from src.ml_scorer import update_prediction_log_with_outcome

update_prediction_log_with_outcome(
    ticker='AAPL',
    prediction_date='2025-11-20',
    actual_return_pct=5.2,
    actual_label=1  # 1=success, 0=failure
)

# Analyze model performance
from src.ml_scorer import analyze_prediction_accuracy

results = analyze_prediction_accuracy()
print(f"Overall accuracy: {results['overall_accuracy']:.2%}")
print(f"Top-10 precision: {results['top_10_precision']:.2%}")
print(f"Calibration: {results['calibration']}")
```

---

#### `src/model_preparation.py`
**Purpose**: Temporal train/test splitting and feature selection for ML training

**Key Classes**:
- `TemporalSplitter`: Walk-forward validation with purge gap
- `FeatureSelector`: Correlation filter + SHAP importance

**Key Methods**:
```python
# TemporalSplitter
__init__(purge_gap_days=60)
create_folds(df, date_column='entry_date') → List[dict]
get_fold_data(df, fold_idx) → (X_train, X_val, y_train, y_val)

# FeatureSelector
__init__(correlation_threshold=0.95, top_n=None)
fit_transform(X, y) → DataFrame
transform(X) → DataFrame
get_selected_features() → List[str]
calculate_feature_importance_shap(model, X) → DataFrame
```

**Temporal Splitting Logic**:
```
Fold 1: Train 2021-01-01 to 2022-12-31 (2 years)
        → [60-day purge gap] →
        Test 2023-03-01 to 2023-12-31 (10 months)

Fold 2: Train 2021-01-01 to 2023-12-31 (3 years)
        → [60-day purge gap] →
        Test 2024-02-29 to 2025-12-31 (22 months)
```

**Feature Selection Pipeline**:
```
130 numeric features
  ↓
Remove 100% missing features (3 features: current_ratio, quick_ratio, ps_ratio)
  ↓
Correlation filter at 0.95 threshold (~42 features removed)
  ↓
Optional: Top-N by SHAP importance
  ↓
Final: ~85 features (or top-N if specified)
```

**Usage**:
```python
from src.model_preparation import TemporalSplitter, FeatureSelector

# Create temporal folds
splitter = TemporalSplitter(purge_gap_days=60)
folds = splitter.create_folds(df, date_column='entry_date')

# Get fold data
X_train, X_val, y_train, y_val = splitter.get_fold_data(df, fold_idx=0)

# Feature selection
selector = FeatureSelector(correlation_threshold=0.95)
X_train_selected = selector.fit_transform(X_train, y_train)
X_val_selected = selector.transform(X_val)

print(f"Selected {len(selector.get_selected_features())} features")
```

---

#### `src/train_model.py`
**Purpose**: XGBoost model training with custom Precision@k metric and Optuna optimization

**Key Classes**:
- `SEPAModelTrainer`: XGBoost trainer with meta-labeling focus
- `PrecisionAtK`: Custom metric for top-k% prediction quality

**Key Methods**:
```python
# SEPAModelTrainer
__init__(scale_pos_weight='auto', max_depth=3, learning_rate=0.01)
train_baseline(X_train, y_train, X_val=None, y_val=None) → None
optimize_hyperparameters(X_train, y_train, X_val, y_val, n_trials=50) → dict
predict_proba(X) → np.ndarray
save_model(path, metadata=None)
load_model(path) → None

# PrecisionAtK
__init__(k_pct=0.2)  # Top 20%
xgb_metric(preds, dtrain) → (name, value)
calculate(y_true, y_pred_proba) → float
```

**Training Features**:
- **Class Imbalance Handling**: `scale_pos_weight` calculated from data (9:1 ratio)
- **Custom Metric**: Precision@Top-20% instead of AUC-ROC
- **Bayesian Optimization**: Optuna for hyperparameter tuning
- **Infinite Value Handling**: Automatic inf→NaN replacement
- **Early Stopping**: Prevents overfitting
- **Metadata Saving**: Stores feature names, model version, hyperparameters

**Usage**:
```python
from src.train_model import SEPAModelTrainer

# Initialize
trainer = SEPAModelTrainer(max_depth=3)

# Quick training (default params)
trainer.train_baseline(X_train, y_train, X_val, y_val)

# Optimized training (Optuna)
best_params = trainer.optimize_hyperparameters(
    X_train, y_train, X_val, y_val,
    n_trials=50
)

# Save model
trainer.save_model(
    'models/model_fold_1.json',
    metadata={'fold': 1, 'features': feature_names}
)

# Predict
probabilities = trainer.predict_proba(X_test)
```

---

#### `src/evaluate_model.py`
**Purpose**: Comprehensive model evaluation and performance analysis

**Key Classes**:
- `ModelEvaluator`: Evaluation suite with multiple metrics

**Key Methods**:
```python
__init__(model, X_test, y_test, fold_name='fold_1')
evaluate_all() → dict
calculate_precision_at_k(k_values=[10, 20, 30]) → dict
calculate_classification_metrics() → dict
trading_simulation(threshold=0.6) → dict
plot_roc_curve(save_path=None)
plot_precision_recall_curve(save_path=None)
plot_feature_importance(save_path=None)
compare_to_baseline(baseline_win_rate=0.097) → dict
```

**Evaluation Metrics**:
- **Precision@k**: Top 10%, 20%, 30% prediction quality
- **Classification**: Accuracy, Precision, Recall, F1, AUC-ROC
- **Trading Simulation**: Win rate, avg return at various thresholds
- **Baseline Comparison**: Improvement over SEPA-only (9.7% baseline)
- **Feature Importance**: SHAP values and gain-based

**Usage**:
```python
from src.evaluate_model import ModelEvaluator

# Initialize
evaluator = ModelEvaluator(
    model=trainer.model,
    X_test=X_test,
    y_test=y_test,
    fold_name='fold_1'
)

# Comprehensive evaluation
results = evaluator.evaluate_all()

# Generate plots
evaluator.plot_roc_curve('evaluation/roc_fold_1.png')
evaluator.plot_precision_recall_curve('evaluation/pr_fold_1.png')
evaluator.plot_feature_importance('evaluation/importance_fold_1.png')

# Compare to baseline
improvement = evaluator.compare_to_baseline(baseline_win_rate=0.097)
print(f"Precision@20% improvement: {improvement['precision_improvement']:.1%}")
```

---

#### `src/database.py`
**Purpose**: SQLite database for buy list tracking and trade logging (ML-enhanced)

**Key Classes**:
- `DatabaseManager`: Manages database operations and schema

**Database Schema**:

```sql
-- Buy List: Active buy signals with price tracking and ML scores
CREATE TABLE buy_list (
    ticker TEXT PRIMARY KEY,
    signal_date DATE NOT NULL,
    signal_price REAL NOT NULL,      -- Price when signal triggered
    current_price REAL NOT NULL,     -- Latest price (updated daily)
    entry_price REAL,                -- Planned entry price
    stop_price REAL,                 -- Stop loss price
    target_price REAL,               -- Profit target
    atr REAL,
    rs REAL,                         -- Relative strength
    volume_ratio REAL,
    ma50 REAL,                       -- Moving averages (for monitoring)
    ma150 REAL,
    ma200 REAL,
    high_52w REAL,                   -- 52-week high/low
    low_52w REAL,
    -- ML scoring columns (NEW)
    ml_probability REAL,             -- ML success probability (0.0-1.0)
    ml_rank INTEGER,                 -- ML rank (1=best)
    ml_model_version TEXT,           -- Model version identifier
    ml_score_date DATE,              -- Date ML score was generated
    last_updated DATE,               -- Last metrics update
    status TEXT DEFAULT 'active',    -- 'active' or 'removed'
    notes TEXT
);

-- Buy List Activity: Audit trail of all changes
CREATE TABLE buy_list_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,            -- 'ADDED' or 'REMOVED'
    action_date DATE NOT NULL,
    reason TEXT,                     -- 'new_trigger' or 'trend_broken'
    entry_price REAL,
    stop_price REAL,
    target_price REAL,
    rs REAL,
    volume_ratio REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Trades: Historical trade log (for future use)
CREATE TABLE trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    entry_date DATE NOT NULL,
    entry_price REAL NOT NULL,
    exit_date DATE,
    exit_price REAL,
    shares INTEGER NOT NULL,
    pnl_dollars REAL,
    pnl_percent REAL,
    exit_reason TEXT,
    stop_price REAL,
    target_price REAL,
    days_held INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Key Methods**:
```python
# Buy List Management (ML-enhanced)
add_to_buy_list(ticker, signal_date, signal_price, current_price,
                ml_probability=None, ml_rank=None,
                ml_model_version=None, ml_score_date=None, ...)
update_buy_list_metrics(ticker, scan_date, current_price, rs, vol_ratio, ...)
remove_from_buy_list(ticker, reason='trend_broken')
get_buy_list(active_only=True, as_of_date=None) → DataFrame

# Activity Logging
log_buy_list_activity(ticker, action, action_date, reason, ...)

# Temporal Consistency
clear_future_signals(cutoff_date) → dict  # For backward scans

# Export
export_to_csv(table_name, output_path)
```

**Temporal Consistency Feature**:

The scanner supports historical backtesting with automatic temporal consistency:

```python
# When scanning a date BEFORE the earliest signal in database
if scan_date < earliest_signal_date:
    # Automatically clears "future" signals
    deleted = db.clear_future_signals(scan_date)
    # Prevents temporal inconsistency
```

**Scanner vs Dataset B Separation**:

| System | Purpose | Storage | Lifecycle |
|--------|---------|---------|-----------|
| **Scanner** | Track active buy signals | Database (`buy_list` tables) | Persistent state |
| **Dataset B** | Generate ML training data | In-memory → CSV export | Ephemeral simulation |

**No overlap** - Scanner uses database for state management, Dataset B uses in-memory Trade objects.

**Usage**:
```python
db = DatabaseManager()

# Add signal
db.add_to_buy_list(
    ticker='AAPL',
    signal_date='2024-11-15',
    signal_price=150.00,
    current_price=150.00,
    rs=0.85,
    vol_ratio=1.4,
    ma50=145.00
)

# Update daily
db.update_buy_list_metrics(
    ticker='AAPL',
    scan_date='2024-11-16',
    current_price=152.50,
    rs=0.87,
    ma50=145.20
)

# Get active signals
buy_list = db.get_buy_list(active_only=True)

# Historical query
historical = db.get_buy_list(active_only=True, as_of_date='2024-11-01')

# Remove when trend breaks
db.remove_from_buy_list('AAPL', reason='trend_broken')
db.log_buy_list_activity('AAPL', 'REMOVED', '2024-11-20', reason='trend_broken')
```

---

### 🛠️ Application Scripts

#### `optimized_scanner.py`
**Purpose**: Batch-optimized daily buy signal scanner with ML integration

**What it does**:
1. Fetches S&P 500 universe (~500 tickers)
2. Batch updates price cache (vectorized operations)
3. Batch calculates features for all tickers
4. Scans for SEPA signals (qualifying stocks + new triggers)
5. **ML Scoring** (if --use-ml enabled):
   - Loads fundamental data for SEPA candidates
   - Scores candidates with XGBoost model
   - Filters by ML probability threshold (default: 0.6)
   - Calculates ranks (1=best)
   - Logs predictions to `data/predictions_log.parquet`
6. Manages buy list:
   - **Detects backward scans** (scan_date < earliest_signal_date)
   - **Clears future signals** automatically for temporal consistency
   - **Adds** new triggers (ML-filtered if enabled)
   - **Updates** existing tickers still qualifying
   - **Removes** tickers with broken trends
   - **Stores ML metadata** (probability, rank, model version)
7. Logs all activity to `buy_list_activity` table
8. Optional CSV export of buy_list and activity

**Scanner Workflow**:
```
[1/4] Fetch Universe → 504 tickers
[2/4] Batch Update Cache → Download OHLCV data
[3/4] Batch Load Data → Load all parquet files
[4/4] Batch Process → Features + SEPA screening
[ML]  ML Scoring (if --use-ml):
    ├── Load fundamental data for candidates
    ├── Score with XGBoost model
    ├── Filter by threshold (default: 0.6)
    ├── Calculate ranks
    └── Log predictions to parquet
[5/5] Manage Buy List:
    ├── Temporal Check (backward scan detection)
    ├── Load existing buy_list (as of scan_date)
    ├── Determine: ADD (ML-filtered), UPDATE, REMOVE
    ├── Store ML metadata (prob, rank, version, date)
    ├── Execute changes
    └── Log activity
```

**Temporal Consistency**:
```python
# Automatic backward scan detection
all_signals = db.get_buy_list(active_only=False)
earliest_signal_date = all_signals['signal_date'].min()

if scan_date < earliest_signal_date:
    print("⚠️  BACKWARD SCAN DETECTED")
    print("Clearing future signals...")
    deleted = db.clear_future_signals(scan_date)
    # Now database only has signals <= scan_date
```

**CLI**:
```bash
# Basic scanner (SEPA only)
python optimized_scanner.py

# ML-enhanced scanner
python optimized_scanner.py --use-ml

# Custom ML configuration
python optimized_scanner.py \
    --use-ml \
    --model-path models/model_fold_1.json \
    --ml-threshold 0.65 \
    --scan-date 2025-11-28 \
    --csv-output

# Date range backtesting with ML
python optimized_scanner.py \
    --use-ml \
    --ml-threshold 0.6 \
    --date-range 2025-11-01 2025-11-28
```

**Performance**:
```
Typical run (500 tickers):
- Cache update: 0.3s
- Data loading: 0.9s
- Feature calc: 2.7s (185 tickers/sec)
- SEPA screening: 0.4s (1200+ tickers/sec)
- ML scoring (5 candidates): ~2-3s (if --use-ml)
  ├── Fundamental data loading: 1-2s
  └── XGBoost inference: 0.5-1s
Total: ~4.5s (SEPA-only) or ~7-8s (ML-enhanced)
```

**Output**:
```
Database:
  - buy_list table (43 active signals)
  - buy_list_activity table (audit trail)

CSV (if csv_output=True):
  - data/scanner_output/buy_list_YYYY-MM-DD.csv
  - data/scanner_output/buy_list_activity_YYYY-MM-DD.csv
```

**Inspection**:
```bash
# View current buy list
python view_buy_list.py

# Query database directly
sqlite3 database/trades.db "SELECT * FROM buy_list WHERE status='active'"
```

---

#### `view_buy_list.py`
**Purpose**: Quick inspection of current buy list from database

**What it shows**:
- All active signals with ticker, dates, prices
- Price changes since signal
- Days on list
- Summary statistics (total, average days, win rate)

**CLI**:
```bash
python view_buy_list.py

#### `build_dataset_a.py`
**Purpose**: Generate daily feature snapshots (Dataset A)

**What it does**:
1. Loads tickers from Dataset B (or universe)
2. Downloads/caches price data
3. Calculates lightweight + heavyweight features
4. Extracts daily snapshots for each ticker
5. Exports to Parquet

**CLI**:
```bash
python build_dataset_a.py \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --mode full \
  --output data/ml/dataset_a_2024.parquet
```

---

#### `build_dataset_b.py`
**Purpose**: Generate labeled trade history (Dataset B)

**What it does**:
1. Runs historical trade simulation
2. Tracks entries, exits, and outcomes
3. Calculates enhanced metrics
4. Labels trades based on success criteria
5. Exports to Parquet and/or database

**CLI**:
```bash
python build_dataset_b.py \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --threshold 15.0 \
  --output data/ml/dataset_b_2024.parquet \
  --save-to-db
```

---

#### `scanner_v0.py`
**Purpose**: Daily buy signal scanner

**What it does**:
1. Downloads latest price data
2. Calculates features for universe
3. Scans for SEPA signals
4. Updates buy list and database
5. Logs changes to buy_list_history.csv

**CLI**:
```bash
python scanner_v0.py --date 2024-11-15
```

---

#### `merge_datasets.py`
**Purpose**: CLI tool for merging Dataset A and Dataset B

**What it does**:
1. Loads both datasets
2. Validates temporal compatibility
3. Performs snapshot merge
4. Exports merged dataset and statistics report

**CLI**:
```bash
python merge_datasets.py \
  --dataset-a data/ml/dataset_a.parquet \
  --dataset-b data/ml/dataset_b.parquet \
  --output data/ml/merged_dataset.parquet
```

---

#### `inspect_merged.py`
**Purpose**: Quality validation tool for merged datasets

**What it does**:
1. Analyzes label distribution
2. Checks feature completeness
3. Reports missing values
4. Validates merge quality (match rate)

**CLI**:
```bash
python inspect_merged.py data/ml/merged_dataset.parquet
```

---

## Data Flow Diagrams

### Dataset A Generation Flow

```
1. Load Tickers
   ├── From Dataset B (default)
   ├── From --tickers argument
   └── From universe (--use-universe)
       ↓
2. Update Cache
   └── DataRepository.update_cache()
       ↓
3. Calculate Features (per ticker)
   ├── FeatureEngineer.calculate_lightweight_features()
   └── FeatureEngineer.calculate_heavyweight_features()
       ↓
4. Extract Daily Snapshots
   └── For each date: row = (date, ticker, features)
       ↓
5. Export
   └── DataFrame.to_parquet()
```

### Dataset B Generation Flow

```
1. Load Universe
   └── DataRepository.update_universe()
       ↓
2. Simulate Trading Day-by-Day
   ├── Check for exits (active trades)
   └── Check for entries (new signals)
       ↓
3. Close Trades
   └── Calculate metrics (return, MDD, MFE, R-multiple, Sharpe)
       ↓
4. Label Trades
   └── Apply labeling_function (default: return >= 15%)

```
quantamental/
├── src/                          # Core modules
│   ├── data_engine.py            # Data acquisition
│   ├── features.py               # Feature engineering
│   ├── alpha_factors.py          # WorldQuant alphas
│   ├── fundamental_engine.py     # Fundamental data acquisition
│   ├── fundamental_processor.py  # Fundamental preprocessing
│   ├── fundamental_merger.py     # Fundamental-Price merging
│   ├── fundamental_data.py       # Fundamental data manager
│   ├── temporal_validator.py     # Data leakage prevention
│   ├── strategy.py               # SEPA signals
│   ├── trade_simulator.py        # Historical simulation
│   ├── trading_config.py         # Configuration
│   ├── database.py               # SQLite operations (ML-enhanced)
│   ├── dataset_merger.py         # Dataset merging
│   ├── model_preparation.py      # Temporal splitting & feature selection
│   ├── train_model.py            # XGBoost training
│   ├── evaluate_model.py         # Model evaluation
│   └── ml_scorer.py              # Production ML inference
│
├── build_dataset_a.py            # Dataset A builder
├── build_dataset_b.py            # Dataset B builder
├── prepare_training_dataset.py   # Dataset A + B merger
├── train_sepa_model.py           # Master training orchestrator
├── test_training_setup.py        # Pre-flight validation
├── diagnose_inf_values.py        # Diagnostic tool
├── migrate_database_ml.py        # Database migration for ML
│
├── optimized_scanner.py          # ML-enhanced scanner (--use-ml)
├── view_buy_list.py              # Buy list inspector
│
├── WorldQuant_101.py             # Alpha factor library
├── config.py                     # Global configuration
│
├── test_temporal_integrity.py   # Temporal validation tests
├── test_qss_phase1.py            # System tests
│
├── data/
│   ├── price/                    # Parquet cache (OHLCV)
│   ├── fundamental_cache/        # FMP fundamental data
│   ├── ml/                       # ML datasets
│   │   ├── dataset_a.parquet    # Feature store
│   │   ├── dataset_b.parquet    # Trade history
│   │   └── training_dataset_final.parquet  # Merged dataset
│   ├── predictions_log.parquet   # ML prediction tracking
│   └── scanner_output/           # Scanner CSV exports
│
├── models/                       # Trained ML models
│   ├── model_fold_1.json         # XGBoost model (Fold 1)
│   ├── model_metadata_fold_1.json # Model metadata
│   ├── model_fold_2.json         # XGBoost model (Fold 2)
│   └── model_metadata_fold_2.json
│
├── evaluation/                   # Model evaluation outputs
│   ├── evaluation_report.json    # Comprehensive metrics
│   ├── roc_curve_fold_*.png      # ROC curves
│   ├── pr_curve_fold_*.png       # Precision-recall curves
│   └── feature_importance_fold_*.png
│
├── database/
│   └── qss_scanner.db            # SQLite database (ML columns)
│
└── docs/
    ├── ARCHITECTURE.md           # This file (system architecture)
    ├── DATASET_A_GUIDE.md        # Dataset A usage
    ├── DATASET_B_GUIDE.md        # Dataset B usage
    ├── MODEL_TRAINING_GUIDE.md   # ML training guide
    ├── ML_SCANNER_INTEGRATION.md # Scanner integration guide
    └── IMPLEMENTATION_SUMMARY.md # Training implementation summary
```

---

## Key Design Patterns

### 1. Dual-Stage Feature Engineering
- **Lightweight features**: Run on all 500 stocks (SMA, ATR, RS)
- **Heavyweight features**: Run only on 5-15 SEPA candidates (alphas)
- **Benefit**: 10x faster than calculating alphas for entire universe

### 2. Temporal Integrity
- **Rule**: Features for entry on Day T+1 use data only up to Day T
- **Validation**: Perturbation test detects future data leakage
- **Implementation**: Explicit date subsetting in all calculations

### 3. Event-Driven Simulation
- **Day-by-day**: Chronological loop (no random access)
- **Exit before entry**: Check exits first, then new entries
- **Re-entry tracking**: Cooldown period prevents immediate re-entry

### 4. Flexible Labeling
- **Lambda functions**: User-defined success criteria
- **Multiple metrics**: Return, duration, risk-adjusted, composite
- **Runtime override**: CLI `--label-rule` argument

---

## Common Workflows

### Workflow 1: Build Full ML Dataset

```bash
# 1. Generate Dataset B (trade history)
python build_dataset_b.py \
  --start 2023-01-01 --end 2024-12-31 \
  --threshold 15.0 \
  --output data/ml/dataset_b_2023_2024.parquet \
  --save-to-db

# 2. Generate Dataset A (features)
python build_dataset_a.py \
  --start 2023-01-01 --end 2024-12-31 \
  --mode full \
  --output data/ml/dataset_a_2023_2024.parquet

# 3. Merge Datasets
python merge_datasets.py \
  --dataset-a data/ml/dataset_a_2023_2024.parquet \
  --dataset-b data/ml/dataset_b_2023_2024.parquet \
  --output data/ml/merged_dataset.parquet

# 4. Train Model (Python script)
# See docs/ML_TRAINING_GUIDE.md (future)
```

### Workflow 2: Daily Scanner

```bash
# Run scanner for today
python scanner_v0.py

# Check buy list
cat output/buy_list.csv

# View history
cat output/buy_list_history.csv
```

### Workflow 3: Backtest New Labeling Rule

```bash
python build_dataset_b.py \
  --start 2024-01-01 --end 2024-12-31 \
  --label-rule "trade.return_pct >= 20 and trade.days_held <= 30" \
  --output data/ml/dataset_b_custom.parquet
```

---

## Dependencies

**Core**:
- `pandas`, `numpy`: Data manipulation
- `yfinance`: Price data fallback
- `requests`: FMP API calls
- `scipy`: Statistical functions

**Optional**:
- `pytest`: Unit testing
- `tqdm`: Progress bars

**External APIs**:
- **Financial Modeling Prep (FMP)**: Historical price data (optional, requires API key)
- **yfinance**: Free historical data (default)
- **SSGA (State Street)**: S&P 500 constituent list

---

## Configuration

### `config.py` - Key Settings

```python
# Data sources
BENCHMARK_TICKER = 'SPY'
UNIVERSE_SOURCE = 'SSGA'  # S&P 500 list
FMP_API_KEY = os.getenv('FMP_API_KEY')

# Feature parameters
SMA_FAST = 50
SMA_MEDIUM = 150
SMA_SLOW = 200
ATR_PERIOD = 14
RS_LOOKBACK = 63

# SEPA strategy
CONSOLIDATION_PERIOD = 20
VOL_SPIKE_THRESHOLD = 1.3
WEEKS_52_HIGH_THRESHOLD = 0.75

# Caching
DATA_CACHE_DAYS = 1       # Re-download if older
LOOKBACK_PERIOD = '2y'    # History needed for 200-day MA
```

---

## ML Integration Status

### ✅ Completed (Sprint 2)
- [x] Dataset merging (Dataset A + B)
- [x] Fundamental data integration (FMP financial statements)
- [x] Model training pipeline (XGBoost with walk-forward validation)
- [x] Feature selection (correlation filter + SHAP)
- [x] Model evaluation suite (Precision@k, ROC, PR curves)
- [x] Production inference module (MLScorer)
- [x] ML-enhanced scanner (--use-ml flag)
- [x] Database schema updates (ML columns)
- [x] Prediction logging and feedback loop
- [x] Comprehensive documentation

### 🚀 Next Steps / Future Development

### Sprint 3: Production Hardening
- [ ] Automated model retraining pipeline (monthly)
- [ ] Model performance monitoring dashboard
- [ ] A/B testing framework (compare model versions)
- [ ] Alerting system for model drift
- [ ] Automated outcome updates from broker API

### Sprint 4: Advanced Features
- [ ] Multi-class labeling (0=loss, 1=small win, 2=big win, 3=home run)
- [ ] Ensemble models (XGBoost + LightGBM + CatBoost)
- [ ] Cross-sectional ranking alphas (requires full universe data)
- [ ] Online learning (incremental updates)
- [ ] Alternative feature sets (sentiment, news, options flow)

### Sprint 5: Production Deployment
- [ ] Real-time scanner (market hours with live data)
- [ ] Trade execution interface (Interactive Brokers API)
- [ ] Portfolio management dashboard
- [ ] Automated daily reports (email/Slack)
- [ ] Risk management module

---

## Testing

```bash
# Run all tests
pytest

# Run temporal integrity tests only
pytest test_temporal_integrity.py -v

# Skip integration tests (faster)
pytest -m "not integration"

# Run specific test
pytest test_temporal_integrity.py::TestTemporalValidator::test_perturbation_test -v
```

---

## Support & Documentation

### Core Documentation
- **Architecture**: `docs/ARCHITECTURE.md` (this file)
- **Dataset A Guide**: `docs/DATASET_A_GUIDE.md` - Feature store documentation
- **Dataset B Guide**: `docs/DATASET_B_GUIDE.md` - Trade labels documentation
- **QSS Overview**: `QSS.md` - System overview

### ML Documentation
- **Model Training Guide**: `docs/MODEL_TRAINING_GUIDE.md` - Complete training documentation
- **ML Scanner Integration**: `ML_SCANNER_INTEGRATION.md` - Scanner integration guide
- **Implementation Summary**: `IMPLEMENTATION_SUMMARY.md` - Training setup summary
- **Training Quick Start**: `TRAINING_QUICK_START.md` - Quick reference
- **ML Integration Summary**: `ML_INTEGRATION_SUMMARY.md` - Scanner integration summary

### Project Planning
- **Sprint Plan**: `docs/sprint_plan.md` - Project roadmap
- **Sprint Progress**: `docs/sprint_1.md` - Sprint 1 progress
