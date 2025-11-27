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

2. **Stage 1: Technical Screening (The Wide Net):** A lightweight, vectorized pass that filters the entire universe using strict SEPA trend templates and VCP criteria. This reduces ~500 stocks to ~5-10 daily candidates.

3. **Stage 2: Feature Enrichment (The Deep Dive):** A computationally intensive pass on only the valid candidates. It fetches quarterly fundamentals and calculates complex Alpha Factors.

4. **Stage 3: ML Scoring (The Selector):** The enriched candidates are fed into a Meta-Model (Random Forest/XGBoost/Logistic Regression). The model predicts the probability of the trade becoming a "Superperformer" (hitting profit targets before stops).

5. **Stage 4: Portfolio Allocation (The Executioner):** A Portfolio Manager module ranks trades by their ML score, applies constraints (Max 8 positions, Cash availability), and executes orders.

6. **Validation:** An Event-Driven Backtest Engine validates the entire pipeline, simulating realistic frictions like cash drag and market regime shifts.

---

## 3. Component Specifications

### **Module A: The Data Curator**
**Responsibility:** Acts as the "Source of Truth" for the system, handling data ingestion, cleaning, and persistent storage.

* **Data Sources:** State Street (SSGA) for Universe definitions; Yahoo Finance for Price and Fundamental data.
* **Storage Strategy:**
    * **Time-Series:** Parquet files (columnar storage) for high-speed reading of price history.
    * **Metadata:** SQLite database for tracking the Watchlist, Trade Logs, and System State.
* **Optimization:** Implements a "Smart Update" mechanism that checks the local cache against the current date, downloading only the delta (missing days) to prevent API rate-limiting.

### **Module B: The Feature Engine**
A dual-stage engine designed to optimize computational resources:

* **Lightweight Mode (Universe Scan):** Calculates low-cost vectorized indicators required for the broad screen (SMA 50/150/200, RSI, ATR, Relative Strength). Applied to the full S&P 500 daily.
* **Heavyweight Mode (Candidate Enrichment):** Calculates computationally expensive features only for stocks that pass the SEPA screen.
    * **Alpha Factors:** WorldQuant Alphas (e.g., Alpha#101 for intraday strength, Alpha#9 for momentum).
    * **Fundamentals:** EPS Growth (QoQ), Sales Acceleration, Earnings Surprises.

### **Module C: The Strategy Engine (SEPA Logic)**
* **Trend Template:** Enforces the "Stage 2" uptrend criteria (Price > SMAs, Rising 200-day SMA, Price near 52-week highs).
* **Pattern Recognition:** Detects Volatility Contraction Patterns (VCP) by analyzing standard deviation compression over multiple timeframes.
* **Trigger Logic:** Identifies precise entry points, specifically looking for price breakouts above a 20-day high accompanied by a volume spike (>130% of average).

### **Module D: The Machine Learning Core (Meta-Labeling)**
**Goal:** To classify the quality of a setup before trading it.

* **The Model:** Random Forest or XGBoost Classifier.
* **The Input:** The "State" of the trade at the moment of entry (Market Regime + Stock Fundamentals + Alpha Factors).
* **The Target (Lifecycle Labeling):** Did the trade achieve "Superperformance" (>20% return) before hitting a Stop Loss or Trend Break?
    * **Label 1 (Win):** Yes.
    * **Label 0 (Loss/Noise):** No.
* **Output:** A probability score (0.0 to 1.0) used by the Portfolio Manager to rank competing signals.

### **Module E: The Portfolio Manager**
**Responsibility:** Manages allocation, risk, and trade lifecycle.

* **Constraints:** Enforces reality checks, such as a maximum of 8 simultaneous positions and preventing trading if cash is insufficient ("Cash Drag").
* **Ranking Logic:** If valid signals exceed available slots, candidates are ranked by their ML Probability Score.
* **Exit Management:**
    * **Stop Loss:** Dynamic volatility-based stops (e.g., 2.5x ATR).
    * **Profit Taking:** Partial scaling out at 3R (3x Risk).
    * **Trend Defense:** Trailing stops along the 50-day SMA to capture extended runs.

### **Module F: The Backtest Engine (The Laboratory)**
* **Type:** Event-Driven (Day-by-Day iteration), distinct from vectorized backtesters.
* **Function:** Simulates the passage of time without look-ahead bias. It steps through history one day at a time, updating the Data, Strategy, and Portfolio states sequentially.
* **Metrics:** Generates a professional "Tearsheet" including Sharpe Ratio, Sortino Ratio, Max Drawdown, Win/Loss Rate, Profit Factor, and Expectancy.

---

## 4. Detailed Implementation Roadmap

### **Phase 1: Foundation & Data Architecture (Days 1-3)**
* [ ] Set up folder structure (`data/`, `src/`, `notebooks/`).
* [ ] Implement `DataRepository` with Parquet caching and Smart Update mechanism.
* [ ] Build the `update_data` routine to handle batch downloads and API rate limits.
* [ ] **Milestone:** A script that downloads/updates 500 tickers in <60 seconds.

### **Phase 2: The OOP Strategy Core (Days 4-6)**
* [ ] Implement `FeatureEngineer` with dual-stage processing (Lightweight + Heavyweight modes).
* [ ] Implement `SEPAStrategy` class with modular methods for "Trend", "Structure", and "Trigger".
* [ ] **Milestone:** A script that takes a Ticker + Date and returns "BUY", "SELL", or "WAIT".

### **Phase 3: Event-Driven Backtester (Days 7-10)**
* [ ] Build the `BacktestEngine` loop (Day-by-Day iteration).
* [ ] Implement `PortfolioManager` to handle the "Max 8 Positions" and "Cash Drag" logic.
* [ ] Integrate Transaction Costs and Slippage simulation.
* [ ] **Milestone:** A realistic Equity Curve that accounts for limited cash.

### **Phase 4: Reporting & Watchlist System (Days 11-12)**
* [ ] Create `PerformanceReporter` to calculate Sharpe, Drawdown, and Win/Loss stats.
* [ ] Build the **Persistent Watchlist** (SQLite) to track how long a stock has been setting up (Days on Watchlist).
* [ ] **Milestone:** A generated PDF/HTML report of the strategy performance.

### **Phase 5: Machine Learning Integration (Meta-Labeling)**
* [ ] **Data Generation:** Generate labeled training data from backtest trade logs.
* [ ] **Model Training:** Train a Random Forest/XGBoost Classifier on historical setups.
* [ ] **Feature Importance:** Identify which factors (Vol, RS, Sector) predict trade success.
* [ ] **Scoring:** Replace binary "Buy" signals with probability scores (0-100%) to rank trades dynamically.
* [ ] **Milestone:** ML-enhanced portfolio allocation with improved risk-adjusted returns.

---

## 5. Tech Stack & Infrastructure (No Cost)

* **Language:** Python 3.10+
* **Core Libraries:** `pandas`, `numpy` (Vectorized math).
* **Data:** `yfinance` (Market Data), `requests` (SSGA/Wiki Scraping).
* **Storage:** `pyarrow` (Parquet support), `sqlite3`.
* **ML:** `scikit-learn`, `xgboost` (Meta-Labeling models).
* **Visuals:** `matplotlib`, `seaborn`.
* **Environment:** Google Colab (Cloud execution) + Google Drive (Persistent Storage).

---

## 6. File Structure

```
quant_sepa/
│
├── data/                       # [GitIgnore] Local Data Lake
│   ├── price/                  # Parquet files (OHLCV data per ticker)
│   ├── fundamentals/           # Quarterly financial statements
│   └── ml_datasets/            # Labeled training data generated by the system
│
├── database/
│   └── system.db               # SQLite database (Watchlist history, Trade Logs)
│
├── src/                        # Core Logic Modules (Source Code)
│   ├── __init__.py
│   ├── data_engine.py          # Class: DataRepository (Ingestion & Caching)
│   ├── features.py             # Class: FeatureEngineer (Indicators & Factors)
│   ├── strategy.py             # Class: SEPAStrategy (Screening Rules)
│   ├── ml_engine.py            # Class: MetaLabelingModel (Training & Inference)
│   ├── portfolio.py            # Class: PortfolioManager (Sizing & Risk)
│   └── backtester.py           # Class: BacktestEngine (Event-Driven Loop)
│
├── notebooks/                  # Research & Prototyping Lab
│   ├── 01_data_validation.ipynb
│   ├── 02_factor_analysis.ipynb
│   └── 03_ml_model_training.ipynb
│
├── config.py                   # Global Configuration (Paths, Risk Parameters, API Keys)
├── main_scanner.py             # Entry Point: Daily Live Scanning Script
├── run_backtest.py             # Entry Point: Historical Simulation Script
├── requirements.txt            # Python Dependencies
└── README.md                   # Project Documentation
```

---

## 7. Key Design Principles

* **Modularity:** Each module has a single, well-defined responsibility.
* **Performance:** Dual-stage feature calculation optimizes computational resources.
* **Scalability:** Parquet storage and vectorized operations enable fast processing of large datasets.
* **Scientific Rigor:** Event-driven backtesting prevents look-ahead bias.
* **Cost Efficiency:** 100% open-source stack with local file-based storage.