# Master Workflow Notebook - Quick Reference Guide

## Overview
The `master_workflow.ipynb` notebook provides an interactive interface for the complete QSS trading system. It replaces command-line scripts with user-friendly widgets and organized workflows.

## Prerequisites

### Installation
```bash
# Install required packages
pip install ipywidgets jupyterlab tqdm matplotlib seaborn

# Enable Jupyter widgets
jupyter labextension install @jupyter-widgets/jupyterlab-manager

# Or for Jupyter Notebook
jupyter nbextension enable --py widgetsnbextension
```

### Launch Notebook
```bash
# From project root
jupyter lab master_workflow.ipynb

# Or
jupyter notebook master_workflow.ipynb
```

---

## Notebook Structure

### SECTION 1: DATA CURATOR (Cells 1-5)

#### Cell 1: Get Tickers
**Purpose:** Load ticker universe
**Options:**
- `price_folder` - All tickers in data/price/*.parquet
- `fmp_screener` - Filtered universe from FMP API (with custom filters)
- `sp500` - S&P 500 constituents

**Outputs:**
- `loaded_tickers` (list) - Available for downstream cells

---

#### Cell 2: Price Cache Update
**Purpose:** Download/update price data
**Parameters:**
- Source: fmp or yfinance
- Min Date: Historical data start (default: 2 years ago)
- Force Update: Re-download all data

**Best Practice:** Set Force Update = False to only fetch missing/outdated data

---

#### Cell 3: Fundamental Data Update
**Purpose:** Download fundamental data (financial statements, ratios)
**Parameters:**
- Parallel Workers: 1-10 (default: 5)
- Rate Limit: 300 req/min (FMP API limit)

**Note:** Uses parallel downloading for speed

---

#### Cell 4: Company Profile Update
**Purpose:** Download company info (sector, industry, market cap)
**Parameters:**
- Parallel Workers: 1-10 (default: 5)

**Output:** Displays sector distribution

---

#### Cell 5: Data Health Check
**Purpose:** Comprehensive data quality analysis
**Checks:**
- 200-bar filter compliance
- Fundamental data coverage
- Company profile coverage
- Dataset B eligibility

**Output:**
- Console report
- `data/data_health_report.json` (if save enabled)

---

### SECTION 2: SEPA MODEL (Cells 6-13)

#### Cell 6: Build Dataset A
**Purpose:** Generate daily feature snapshots
**Parameters:**
- Start/End Date: Training period
- Mode: lightweight (fast) or full (heavyweight alphas)
- Include Fundamentals: Merge with financial data
- Include Cross-Sectional: Sector/industry features
- n_jobs: -1 for all CPUs, 1 for sequential

**Output:**
- `data/ml/dataset_a.parquet`
- `dataset_a` variable (DataFrame)

**Typical Runtime:** 5-20 minutes depending on date range and mode

---

#### Cell 7: Build Dataset B
**Purpose:** Generate trade simulation labels
**Parameters:**
- Entry Period: When to enter trades
- Outcome End: Extended window for exits (default: +90 days)
- Success Threshold: Return % for success label (default: 15%)
- Use Fast Simulator: Vectorized (10-20x faster)
- Custom Label Rule: Optional (e.g., "trade.return_pct >= 20")

**Output:**
- `data/ml/dataset_b.parquet`
- Trade statistics (win rate, avg return, exit reasons)

**Typical Runtime:** 2-10 minutes (fast mode), 30-120 minutes (event-driven mode)

---

#### Cell 8: Merge and Prepare Training Data
**Purpose:** Merge Dataset A + B with validation
**Checks:**
- Date range coverage
- Duplicate rows
- Missing values
- Label distribution balance
- Temporal consistency

**Output:**
- `data/ml/training_dataset_final.parquet`
- `data/ml/preparation_report.txt`

---

#### Cell 9: Feature Engineering Framework
**Purpose:** Template for custom feature engineering
**Modify Code Sections:**
1. Missing value handling
2. Feature scaling/normalization
3. Custom feature creation

**Output:** `data/ml/training_dataset_cleaned.parquet`

---

#### Cell 10: Define Fold and Training Parameters
**Purpose:** Configure temporal splitting and feature selection
**Key Parameters:**
- Purge Gap: Days between train/test (prevents lookahead, default: 60)
- Correlation Threshold: Remove correlated features (default: 0.95)
- Top N Features: Keep best N by SHAP (0 = all)
- Optimize Hyperparameters: Enable Optuna search (slow!)
- n_trials: Optuna iterations (default: 50)

**Output:**
- `train_config` dict with folds, features, splitter
- Fold structure summary

---

#### Cell 11: Train Model
**Purpose:** Train XGBoost for each fold
**Process:**
1. Load fold data
2. Optimize hyperparameters (Fold 1 only, if enabled)
3. Train model
4. Save to models/model_fold_X.json

**Typical Runtime:**
- Without optimization: 2-5 minutes per fold
- With optimization (50 trials): 20-60 minutes for Fold 1

---

#### Cell 12: Review Results and Select Best Model
**Purpose:** Compare fold performance
**Displays:**
- Comparison table (Precision@k, Win Rate, Avg Return, AUC-ROC)
- Best fold recommendations

**Files Generated:**
- `evaluation/evaluation_report.json`
- `evaluation/roc_curve_fold_*.png`
- `evaluation/feature_importance_fold_*.png`

---

#### Cell 13: Retrain Production Model
**Purpose:** Retrain best model on ALL data
**Process:**
1. Load hyperparameters from selected fold
2. Train on entire dataset (no train/test split)
3. Save as `models/model_production.json`

**Use Case:** Deploy this model for daily scanner with ML scoring

---

### SECTION 3: DAILY SCANNER (Cells 14-16)

#### Cell 14: Define Scanner Scope
**Purpose:** Run SEPA scanner
**Modes:**
- **Single Day:** Scan one specific date
- **Date Range:** Vectorized 2D scan (faster for backtesting)

**Parameters:**
- Use ML: Enable ML probability scoring
- Model Path: Production model from Cell 13
- CSV Output: Export buy_list and activity
- Debug Mode: Show detailed metrics for specific tickers

**Output:**
- Console summary (new triggers, buy list updates)
- `data/scanner_output/buy_list_*.csv` (if enabled)

---

#### Cell 15: Review Buy List
**Purpose:** Display current buy list
**Features:**
- Sort by signal_date, ml_rank, rs, price_change_%
- Calculate performance metrics
- Export to CSV

**Output:** Interactive DataFrame with top 50 signals

---

#### Cell 16: Database Management Examples
**Purpose:** Demonstrate database operations
**Examples:**
1. Inspect buy_list table
2. View activity log
3. Clear future signals (temporal cleanup)
4. Export tables to CSV
5. Custom SQL queries

**Use Case:** Data inspection, troubleshooting, manual interventions

---

## Common Workflows

### 1. Initial Setup (First Time)
```
Cell 1 → Cell 2 → Cell 3 → Cell 4 → Cell 5
```
Load tickers → Update price cache → Update fundamentals → Update profiles → Health check

---

### 2. Build Training Dataset
```
Cell 6 → Cell 7 → Cell 8
```
Dataset A → Dataset B → Merge & Validate

---

### 3. Train ML Model
```
Cell 10 → Cell 11 → Cell 12 → Cell 13
```
Configure folds → Train folds → Review results → Retrain production

---

### 4. Daily Scanning (Production)
```
Cell 14 (single_day, use_ml=True) → Cell 15
```
Run scanner with ML → Review buy list

---

### 5. Backtest Date Range
```
Cell 14 (date_range mode)
```
Vectorized 2D scan for historical period

---

## Tips & Best Practices

### Performance
1. **Dataset A:** Use `n_jobs=-1` for parallel processing (4-8x speedup)
2. **Dataset B:** Always use Fast Simulator (10-20x faster)
3. **Scanner:** Use date_range mode for backtesting (processes multiple days in one batch)

### Data Management
1. **Price Cache:** Update weekly or when adding new tickers
2. **Fundamentals:** Update quarterly (after earnings releases)
3. **Profiles:** Update monthly or when universe changes

### Model Training
1. **First Training:** Disable hyperparameter optimization to test pipeline
2. **Production Training:** Enable optimization with 50-100 trials for best results
3. **Feature Selection:** Start with correlation=0.95, adjust if needed

### Debugging
1. **Use Debug Mode** in Cell 14 to see detailed SEPA condition checks for specific tickers
2. **Check Health Report** (Cell 5) if Dataset B has fewer tickers than expected
3. **Review Preparation Report** (Cell 8) for data quality issues

---

## Troubleshooting

### "No tickers loaded" Error
**Solution:** Run Cell 1 first, or uncheck "Use tickers from Cell 1" in other cells

### ML Model Loading Failed
**Solution:**
1. Check model file exists at specified path
2. Verify model was trained with same feature set
3. Check model version compatibility

### API Rate Limit Errors
**Solution:**
1. Reduce parallel workers to 3-5
2. Add delays between batches
3. Check FMP API key is valid

### Out of Memory Errors
**Solution:**
1. Reduce date range for Dataset A/B
2. Use lightweight mode instead of full
3. Process in smaller ticker batches

---

## File Outputs Reference

### Data Files
- `data/price/*.parquet` - Price cache (individual tickers)
- `data/fundamentals/*.parquet` - Fundamental data (individual tickers)
- `data/company_info/*.json` - Company profiles (individual tickers)
- `data/ml/dataset_a.parquet` - Feature snapshots
- `data/ml/dataset_b.parquet` - Trade labels
- `data/ml/training_dataset_final.parquet` - Merged training data

### Model Files
- `models/model_fold_*.json` - Trained fold models
- `models/model_production.json` - Production model (from Cell 13)

### Evaluation Files
- `evaluation/evaluation_report.json` - Fold comparison metrics
- `evaluation/roc_curve_fold_*.png` - ROC curve plots
- `evaluation/feature_importance_fold_*.png` - Feature importance plots

### Scanner Outputs
- `data/scanner_output/buy_list_*.csv` - Daily buy list snapshots
- `data/scanner_output/buy_list_activity_*.csv` - Activity log

### Reports
- `data/ml/preparation_report.txt` - Dataset validation report
- `data/data_health_report.json` - Data coverage analysis

---

## Advanced Usage

### Custom FMP Screener Filters
In Cell 1, modify screener parameters:
```python
market_cap_min.value = 5000000000  # $5B min market cap
price_min.value = 10.0  # $10 min price
volume_min.value = 500000  # 500K min volume
```

### Custom Label Rules
In Cell 7, define custom success criteria:
```python
custom_label_rule_b.value = "trade.return_pct >= 20 and trade.days_held <= 30"
```
This creates labels for "20% return in ≤30 days"

### Feature Engineering
In Cell 9, add custom features:
```python
# Example: Price momentum
df_fe['price_momentum'] = df_fe['Close'] / df_fe['Close'].shift(20) - 1

# Example: Volume spike
df_fe['volume_spike'] = df_fe['Volume'] / df_fe['Volume'].rolling(50).mean()
```

---

## Next Steps

After completing the notebook workflow:

1. **Deploy Scanner:** Use Cell 14 daily for live signals
2. **Monitor Performance:** Review Cell 15 buy list regularly
3. **Retrain Models:** Quarterly or when strategy drifts
4. **Analyze Results:** Use Cell 12 evaluation reports to improve model

---

## Support

For issues or questions:
- Check the detailed plan in the notebook markdown cells
- Review existing Python scripts (build_dataset_a.py, train_sepa_model.py, etc.) for implementation details
- Refer to config.py for system configuration

---

**Last Updated:** 2024-12-05
**Notebook Version:** 1.0
