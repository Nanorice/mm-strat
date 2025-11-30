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
   ├── Dataset A (features)     → Daily technical indicators
   ├── Dataset B (labels)       → Trade outcomes
   └── Model (future)           → Meta-labeling classifier

5. APPLICATION LAYER
   ├── scanner_v0.py            → Daily signal scanner
   ├── build_dataset_a.py       → Feature store builder  
   └── build_dataset_b.py       → Trade history builder
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

#### `src/database.py`
**Purpose**: SQLite database for buy list tracking and trade logging

**Key Classes**:
- `DatabaseManager`: Manages database operations and schema

**Database Schema**:

```sql
-- Buy List: Active buy signals with price tracking
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
# Buy List Management
add_to_buy_list(ticker, signal_date, signal_price, current_price, ...)
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
**Purpose**: Batch-optimized daily buy signal scanner with temporal consistency

**What it does**:
1. Fetches S&P 500 universe (~500 tickers)
2. Batch updates price cache (vectorized operations)
3. Batch calculates features for all tickers
4. Scans for SEPA signals (qualifying stocks + new triggers)
5. Manages buy list:
   - **Detects backward scans** (scan_date < earliest_signal_date)
   - **Clears future signals** automatically for temporal consistency
   - **Adds** new triggers not in buy_list
   - **Updates** existing tickers still qualifying
   - **Removes** tickers with broken trends
6. Logs all activity to `buy_list_activity` table
7. Optional CSV export of buy_list and activity

**Scanner Workflow**:
```
[1/4] Fetch Universe → 504 tickers
[2/4] Batch Update Cache → Download OHLCV data
[3/4] Batch Load Data → Load all parquet files
[4/4] Batch Process → Features + SEPA screening
[5/5] Manage Buy List:
    ├── Temporal Check (backward scan detection)
    ├── Load existing buy_list (as of scan_date)
    ├── Determine: ADD, UPDATE, REMOVE
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
```python
# In-script configuration
run_optimized_scanner(
    scan_date='2024-11-15',  # None = today
    csv_output=True           # Export to CSV
)

# Date range mode (backfilling)
start_date = datetime(2024, 11, 1)
end_date = datetime(2024, 11, 30)
for date in date_range(start_date, end_date):
    run_optimized_scanner(scan_date=date.strftime('%Y-%m-%d'))
```

**Performance**:
```
Typical run (500 tickers):
- Cache update: 0.3s
- Data loading: 0.9s  
- Feature calc: 2.7s (185 tickers/sec)
- SEPA screening: 0.4s (1200+ tickers/sec)
Total: ~4.5s
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
│   ├── temporal_validator.py     # Data leakage prevention
│   ├── strategy.py               # SEPA signals
│   ├── trade_simulator.py        # Historical simulation
│   ├── trading_config.py         # Configuration
│   ├── database.py               # SQLite operations
│   └── dataset_merger.py         # Dataset merging
│
├── build_dataset_a.py            # Dataset A builder
├── build_dataset_b.py            # Dataset B builder
├── merge_datasets.py             # Dataset merger CLI
├── inspect_merged.py             # Merged dataset inspector
├── verify_merge.py               # Quick verification script
├── scanner_v0.py                 # Daily scanner
├── inspect_dataset_b.py          # Dataset B inspection
│
├── WorldQuant_101.py             # Alpha factor library
├── config.py                     # Global configuration
│
├── test_temporal_integrity.py   # Temporal validation tests
├── test_qss_phase1.py            # System tests
│
├── data/
│   ├── price/                    # Parquet cache (OHLCV)
│   ├── ml/                       # Datasets for ML training
│   │   ├── dataset_a.parquet    # Feature store
│   │   └── dataset_b.parquet    # Trade history
│   └── fundamentals/             # Future: fundamental data
│
├── database/
│   └── trades.db                 # SQLite database
│
└── docs/
    ├── DATASET_A_GUIDE.md        # Dataset A usage
    ├── DATASET_B_GUIDE.md        # Dataset B usage
    ├── ARCHITECTURE.md           # This file
    ├── sprint_1.md               # Sprint progress
    └── sprint_plan.md            # Project roadmap
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

## Next Steps / Future Development

### Sprint 2: Model Training & Deployment
- [ ] `merge_datasets.py` - Join Dataset A + B
- [ ] `train_model.py` - Train Random Forest classifier
- [ ] `evaluate_model.py` - AUC-ROC, feature importance
- [ ] `scanner_ml.py` - ML-enhanced scanner

### Sprint 3: Advanced Features
- [ ] Fundamental data integration (FMP earnings, sales)
- [ ] Cross-sectional ranking alphas
- [ ] Online learning (update model with new data)
- [ ] Multi-class labeling (0=loss, 1=small, 2=big win)

### Sprint 4: Production
- [ ] Real-time scanner (market hours)
- [ ] Trade execution interface
- [ ] Performance monitoring dashboard
- [ ] Automated daily reports

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

- **Architecture**: `docs/ARCHITECTURE.md` (this file)
- **Dataset A**: `docs/DATASET_A_GUIDE.md`
- **Dataset B**: `docs/DATASET_B_GUIDE.md`
- **Sprint Plan**: `docs/sprint_plan.md`
- **Sprint Progress**: `docs/sprint_1.md`
- **QSS Overview**: `QSS.md`
