# Quantamental SEPA System (QSS): Project Blueprint

## 1. Executive Summary

**Objective:** To engineer an automated, event-driven quantitative trading system designed to systematically identify and trade "Superperformer" stocks within the S&P 500.

**Core Philosophy:** The system integrates three distinct trading disciplines into a unified **"Funnel"** architecture:

1. **Selection (The Filter):** Automating Mark Minervini's SEPA (Specific Entry Point Analysis) methodology. This strictly filters the universe for high-probability setups based on Trend, Volatility Contraction Patterns (VCP), and Volume Breakouts.

2. **Enrichment (The Quantamental Layer):** Validating technical setups with fundamental growth metrics (Earnings/Sales acceleration) and quantitative Alpha Factors (e.g., WorldQuant formulas).

3. **Ranking & Sizing (The Brain):** Applying Financial Machine Learning (Meta-Labeling). Instead of discretionary sizing, the system uses a classifier to predict the probability of a trade's success over its lifecycle, driving dynamic capital allocation and risk management.

---

## 2. System Architecture

The system is designed as a **multi-stage funnel** that progressively filters and enriches data, reducing a broad universe of stocks down to a concentrated, high-conviction portfolio.

### The "Funnel" Workflow:

1. **Universe Ingestion:** Daily ingestion of the S&P 500 constituents (via SSGA) to ensure a survivorship-bias-free and tradeable universe.

2. **Stage 1: Technical Screening (The Wide Net):** A lightweight, vectorized pass that filters the entire universe using strict SEPA trend templates and VCP criteria. This reduces ~500 stocks to ~5-15 daily candidates.

3. **Stage 2: Feature Enrichment (The Deep Dive):** A computationally intensive pass on only the valid candidates. Calculates all technical indicators and relative strength metrics using the dual-stage FeatureEngineer.

4. **Stage 3: Buy List Management (The Tracker):** Active buy signals are tracked in a persistent database with:
   - Signal price and date (never changes)
   - Current price and P&L tracking (updates daily)
   - Actual indicator values (MA50/150/200, 52w high/low)
   - Smart data handling for market holidays

5. **Stage 4: ML Scoring (The Selector - Future):** Enriched candidates will be fed into a Meta-Model (Random Forest/XGBoost) to predict probability of trade success.

6. **Stage 5: Portfolio Allocation (The Executioner - Future):** Portfolio Manager will rank trades by ML score, apply constraints (Max 8 positions), and execute orders.

7. **Validation:** Event-Driven Backtest Engine validates the pipeline with realistic frictions like cash drag and market regime shifts.

---

## 3. Component Specifications

### **Module A: The Data Curator**
**Responsibility:** Acts as the "Source of Truth" for the system, handling data ingestion, cleaning, and persistent storage.

* **Data Sources:** 
    * State Street (SSGA) for S&P 500 universe
    * Yahoo Finance (primary) for OHLCV data
    * Financial Modeling Prep (FMP) for historical data (with yfinance fallback)
* **Storage Strategy:**
    * **Time-Series:** Parquet files (columnar storage) for high-speed reading of price history
    * **Metadata:** SQLite database for Watchlist, Buy List, and Trade Logs
* **Optimization:** Smart cache update checks local files vs current date, downloads only missing data to prevent API rate-limiting
* **Batch Processing:** Processes up to 500 tickers in ~5-6 seconds

### **Module B: The Feature Engine**
A dual-stage engine designed to optimize computational resources:

* **Lightweight Mode (Universe Scan):** Calculates low-cost vectorized indicators for broad screen:
    * Moving Averages (SMA 50/150/200)
    * ATR (volatility)
    * Relative Strength vs SPY
    * Volume metrics (ratio vs 50-day average)
    * 52-week high/low tracking
    * Breakout detection (20-day high)

* **Heavyweight Mode (Future - Candidate Enrichment):** Will calculate expensive features for passing stocks:
    * **Alpha Factors:** WorldQuant Alphas (Alpha#101, Alpha#9)
    * **Fundamentals:** EPS Growth, Sales Acceleration, Earnings Surprises

### **Module C: The Strategy Engine (SEPA Logic)**
* **Trend Template:** Enforces "Stage 2" uptrend criteria:
    * Price > MA50 > MA150 > MA200
    * MA200 trending up (> 20 days ago)
    * Price > 30% above 52-week low
    * Price within 25% of 52-week high

* **Pattern Recognition:** Detects Volatility Contraction Patterns (VCP) by analyzing standard deviation compression

* **Trigger Logic:** Identifies precise entry points:
    * Price breakout above 20-day high
    * Volume spike (>130% of average)
    * Relative strength confirmation

### **Module D: The Database Manager**
**Responsibility:** Persistent storage and retrieval of system state

* **Tables:**
    * **watchlist:** Tracks stocks in Stage 2 setup (not yet triggered)
    * **buy_list:** Active buy signals with detailed tracking:
        * `signal_date`, `signal_price` (never changes)
        * `current_price`, `last_updated` (updates each scan)
        * Actual indicator values (ma50, ma150, ma200, high_52w, low_52w)
        * RS and volume_ratio
    * **buy_list_activity:** Complete audit log of all additions/removals
    * **trades:** Historical trade log (for future portfolio tracking)

* **Smart Features:**
    * Automatic P&L calculation (price_change_$ and price_change_%)
    * Historical date filtering (as_of_date support)
    * Missing data handling (uses last available date)

### **Module E: The Machine Learning Core (Meta-Labeling - Future)**
**Goal:** To classify the quality of a setup before trading it.

* **The Model:** Random Forest or XGBoost Classifier
* **The Input:** Trade state at entry (Market Regime + Stock Fundamentals + Alpha Factors)
* **The Target:** Did trade achieve "Superperformance" (>20% return) before stop?
* **Output:** Probability score (0.0-1.0) for portfolio ranking

### **Module F: The Portfolio Manager (Future)**
**Responsibility:** Manages allocation, risk, and trade lifecycle

* **Constraints:** Max 8 positions, cash drag prevention
* **Ranking:** ML probability score
* **Exit Management:**
    * Stop Loss: Dynamic volatility-based stops (2.5x ATR)
    * Profit Taking: Partial scaling at 3R
    * Trend Defense: Trailing stops at 50-day SMA

### **Module G: The Backtest Engine**
* **Type:** Event-Driven (day-by-day iteration)
* **Function:** Simulates time passage without look-ahead bias
* **Metrics:** Sharpe, Sortino, Max Drawdown, Win/Loss Rate, Profit Factor, Expectancy

---

## 4. Current Implementation Status

### ✅ **Completed:**
* Data Repository with Parquet caching and smart updates
* FeatureEngineer with dual-stage processing
* SEPAStrategy with modular Trend/Structure/Trigger methods
* DatabaseManager with enhanced buy_list schema
* Optimized scanner (500 tickers in ~5-6 seconds)
* Buy list tracking with P&L monitoring
* Activity logging system
* Historical scanning capability
* Smart data handling for market holidays

### 🚧 **In Progress:**
* ML Meta-Labeling model training
* Portfolio Manager implementation
* Advanced position sizing

### 📋 **Planned:**
* Fundamental data integration
* WorldQuant Alpha factors
* Full backtesting engine
* Performance reporting dashboard

---

## 5. Tech Stack & Infrastructure

* **Language:** Python 3.10+
* **Core Libraries:** `pandas`, `numpy` (vectorized math)
* **Data:** `yfinance` (primary), `financialmodelingprep` (FMP with fallback)
* **Storage:** `pyarrow` (Parquet), `sqlite3` (metadata)
* **ML:** `scikit-learn`, `xgboost` (future Meta-Labeling)
* **Visualization:** `matplotlib`, `seaborn`
* **Environment:** Local execution with file-based storage

---

## 6. File Structure

```
quantamental/
│
├── data/                       # [GitIgnore] Local Data Lake
│   ├── price/                  # Parquet files (OHLCV per ticker)
│   └── sp500_constituents/     # Universe snapshots
│
├── database/
│   └── trades.db               # SQLite (watchlist, buy_list, trades, activity)
│
├── src/                        # Core Logic Modules
│   ├── __init__.py
│   ├── data_engine.py          # DataRepository (ingestion & caching)
│   ├── features.py             # FeatureEngineer (indicators & factors)
│   ├── indicators.py           # TechnicalAnalysis (Stage 2, VCP detection)
│   ├── strategy.py             # SEPAStrategy (screening rules)
│   ├── database.py             # DatabaseManager (persistent storage)
│   ├── reporting.py            # PerformanceReporter (metrics & charts)
│   └── [future] ml_engine.py   # Meta-Labeling model
│
├── notebooks/                  # Research & Analysis
│   └── scanner.ipynb
│
├── config.py                   # Global configuration
├── optimized_scanner.py        # Primary scanner (supports date ranges)
├── show_buy_list.py            # Quick buy list viewer
├── view_buy_list_db.py         # Detailed database viewer
├── reset_database.py           # Database recreation utility
├── requirements.txt
├── QSS.md                      # This document
└── README.md
```

---

## 7. Key Design Principles

* **Modularity:** Each module has single, well-defined responsibility
* **Performance:** Dual-stage feature calculation + Parquet storage
* **Scalability:** Vectorized operations enable fast processing
* **Scientific Rigor:** Event-driven backtesting prevents look-ahead bias
* **Cost Efficiency:** 100% open-source stack with local storage
* **Data Integrity:** Smart handling of missing data and market holidays
* **Audit Trail:** Complete activity logging for all buy list changes

---

## 8. Scanner Workflow (Current Implementation)

### Daily Scan Process:
1. **Universe Update:** Fetch S&P 500 tickers from SSGA (~504 stocks)
2. **Cache Update:** Smart update of missing/stale Parquet files
3. **Data Loading:** Batch load all tickers (500 tickers in ~2-3s)
4. **Feature Calculation:** Vectorized indicators (500 tickers in ~1-2s)
5. **SEPA Screening:** Identify qualifying stocks & new triggers (~0.4s)
6. **Buy List Management:**
   - Add new triggers with signal_price tracking
   - Update existing positions with current metrics
   - Remove tickers that break trend
   - Log all activity

### Display Output:
* New triggers with entry metrics
* Active buy list showing:
  * Signal date and price
  * Current price and P/L ($ and %)
  * RS and volume metrics
  * MA50, MA150, MA200 values
  * 52-week high/low
  * Last updated date

---

## 9. Usage Examples

### Single Day Scan:
```python
python optimized_scanner.py  # Scans configured date
```

### Date Range Backfill:
```python
# Edit optimized_scanner.py main block
start_date = datetime(2025, 11, 17)
end_date = datetime(2025, 11, 27)
# Automatically scans all dates in range
```

### View Buy List:
```python
python show_buy_list.py  # Quick view
python view_buy_list_db.py  # Detailed view with activity
```

---

*Last Updated: 2025-11-28*
*Version: 2.0 (Buy List Enhancement)*