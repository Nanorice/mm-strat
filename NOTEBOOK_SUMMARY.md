# QSS Complete Workflow Notebook

**Created**: 2024-12-02
**Location**: `notebooks/QSS_Complete_Workflow.ipynb`

---

## What Was Created

An all-in-one Jupyter notebook that combines:

1. **Data Curation** - Download & validate price/fundamental data
2. **Feature Engineering** - Calculate technical & fundamental features
3. **Dataset Building** - Generate Dataset A (features) & Dataset B (labels)
4. **Model Training** - Train & evaluate XGBoost models
5. **Scanner** - Run ML-enhanced scanner
6. **EDA** - Comprehensive exploratory data analysis

---

## Key Features

### 🎯 Complete Workflow Integration

**All major QSS components in one place**:
- Data sourcing (price + fundamentals)
- Feature calculation (technical + alphas + fundamentals)
- Trade simulation (Dataset B generation)
- Feature snapshot extraction (Dataset A generation)
- Dataset merging
- Model training with temporal splits
- Model evaluation
- Scanner execution (SEPA + ML)

### 📊 Comprehensive EDA

**10 analysis sections**:

1. **Data Analysis**
   - Price charts & volume
   - Returns distribution
   - Feature distributions
   - Feature correlations

2. **Model Results**
   - Prediction distributions
   - Confusion matrices at multiple thresholds
   - Precision-recall trade-offs
   - Calibration analysis

3. **Simulated Trades**
   - Return distributions
   - Days held analysis
   - Exit reason breakdown
   - Winners vs losers comparison
   - Top performers
   - Monthly performance trends

4. **Feature Importance**
   - XGBoost gain-based importance
   - Top 20 features
   - SHAP values (optional)
   - Feature category breakdown

5. **Prediction Analysis**
   - Prediction log analysis
   - Performance by probability bins
   - Buy list analysis
   - ML score distributions

### ⚙️ Configurable Workflow

**Easy switching between modes**:

```python
# Quick Test Mode (5-10 minutes)
USE_FULL_UNIVERSE = False
DOWNLOAD_FUNDAMENTALS = False
USE_ML = False

# Full Production Mode (2-4 hours)
USE_FULL_UNIVERSE = True
DOWNLOAD_FUNDAMENTALS = True
USE_ML = True

# EDA-Only Mode (10-20 minutes)
GENERATE_DATASET_B = False  # Load existing
CALCULATE_SHAP = True  # Deep analysis
```

### 🔍 Interactive Analysis

**Built-in visualizations**:
- 30+ matplotlib/seaborn plots
- Heatmaps, scatter plots, histograms
- Multi-panel figures
- Time series charts
- Distribution comparisons

---

## Workflow Overview

```
┌─────────────────────────────────────────────────────────────┐
│                  NOTEBOOK WORKFLOW                          │
└─────────────────────────────────────────────────────────────┘

1. Setup
   └── Import modules, configure settings

2. Data Curation
   ├── Update universe (FMP screener or S&P 500)
   ├── Download price data
   ├── Download fundamentals (optional)
   └── Data quality checks

3. Feature Engineering
   ├── Demo: Calculate features for single ticker
   ├── Visualize feature distributions
   └── Analyze correlations

4. Dataset Building
   ├── Generate Dataset B (trade simulation)
   │   ├── Run historical SEPA trades
   │   ├── Calculate metrics (return, MDD, MFE, Sharpe)
   │   └── Label trades (success/failure)
   ├── Generate Dataset A (feature snapshots)
   │   ├── Calculate features for all tickers
   │   ├── Add fundamentals (optional)
   │   └── Extract daily snapshots
   └── Merge Dataset A + B
       └── Temporal join on (ticker, entry_date)

5. Model Training
   ├── Temporal split (walk-forward validation)
   ├── Feature selection (correlation filter)
   ├── Train XGBoost
   │   ├── Default params (fast)
   │   └── Optuna optimization (optional)
   └── Evaluate model
       ├── Classification metrics
       ├── Precision@k
       ├── Trading simulation
       └── ROC/PR curves

6. Scanner
   ├── Load price data
   ├── Calculate features
   ├── Screen for SEPA signals
   ├── ML scoring (optional)
   │   ├── Load model
   │   ├── Score candidates
   │   ├── Filter by threshold
   │   └── Rank signals
   └── Update database (optional)

7-10. EDA (Exploratory Data Analysis)
   ├── Data distributions
   ├── Model performance
   ├── Trade analysis
   ├── Feature importance
   └── Prediction tracking
```

---

## Use Cases

### 1. Daily Interactive Analysis

**Workflow**:
```bash
# 1. Launch Jupyter
jupyter notebook

# 2. Open QSS_Complete_Workflow.ipynb

# 3. Run Scanner section only
#    - Skip data building
#    - Run with USE_ML=True
#    - Analyze results in EDA sections

# 4. View buy list
#    - Check ML scores
#    - Analyze distributions
```

**Benefit**: Quick daily scanner + analysis in one place

---

### 2. Model Development Cycle

**Workflow**:
```python
# 1. Generate new datasets
GENERATE_DATASET_B = True  # Latest trades
GENERATE_DATASET_A = True  # Latest features

# 2. Train multiple models
#    - Try different hyperparameters
#    - Test feature combinations
#    - Compare performance

# 3. Analyze results
#    - Run EDA sections
#    - Compare feature importance
#    - Validate predictions

# 4. Select best model
#    - Save to models/
#    - Deploy to scanner
```

**Benefit**: Rapid iteration on model improvements

---

### 3. Feature Engineering Research

**Workflow**:
```python
# 1. Modify src/features.py
#    - Add new feature calculation

# 2. Run Feature Engineering section
#    - Calculate for demo ticker
#    - Visualize distribution

# 3. Check correlations
#    - Run correlation heatmap
#    - Identify redundant features

# 4. Train model with new features
#    - Run Model Training section
#    - Check feature importance

# 5. Evaluate impact
#    - Compare metrics vs baseline
```

**Benefit**: Test new features without rebuilding entire pipeline

---

### 4. Trade Strategy Analysis

**Workflow**:
```python
# 1. Modify TradingConfig
#    - Change success threshold
#    - Adjust stop loss
#    - Modify exit rules

# 2. Run Dataset B generation
#    - New simulation with config

# 3. Analyze trade results
#    - Run "EDA: Simulated Trades" section
#    - Check win rate, returns, holding periods

# 4. Compare strategies
#    - Run multiple simulations
#    - Compare metrics
```

**Benefit**: Understand impact of strategy changes

---

### 5. Production Monitoring

**Workflow**:
```python
# Weekly:
# 1. Load prediction log
# 2. Run "EDA: Prediction Analysis"
# 3. Check calibration
# 4. Identify drift

# Monthly:
# 1. Retrain model with new data
# 2. Compare performance vs previous model
# 3. Deploy if improved
```

**Benefit**: Monitor model performance over time

---

## Quick Start

### Option 1: Test Mode (Fast)

```python
# In notebook, set:
USE_FULL_UNIVERSE = False
download_tickers = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN']
DOWNLOAD_FUNDAMENTALS = False
GENERATE_DATASET_B = True
START_DATE = '2024-01-01'
END_DATE = '2024-06-30'
USE_ML = False

# Run all cells
# Runtime: ~5 minutes
```

### Option 2: Production Mode (Full)

```python
# In notebook, set:
USE_FULL_UNIVERSE = True  # ~1730 tickers
DOWNLOAD_FUNDAMENTALS = True
GENERATE_DATASET_B = True
START_DATE = '2023-01-01'
END_DATE = '2024-12-31'
ADD_FUNDAMENTALS = True
USE_ML = True

# Run all cells
# Runtime: ~2-4 hours
```

### Option 3: Analysis Only

```python
# In notebook, set:
GENERATE_DATASET_B = False  # Load existing
GENERATE_DATASET_A = False  # Load existing
USE_ML = True

# Run Setup + EDA sections only
# Runtime: ~10 minutes
```

---

## Output Examples

### Visualizations Generated

1. **Price Analysis**
   - Price chart with moving averages
   - Volume bars
   - Returns distribution

2. **Feature Analysis**
   - Feature distribution histograms (8 panels)
   - Correlation heatmap
   - Feature vs price scatter plots

3. **Model Performance**
   - Prediction probability distributions
   - Confusion matrices (4 thresholds)
   - ROC curve
   - Precision-recall curve
   - F1 score vs threshold

4. **Trade Analysis**
   - Return distribution
   - Days held distribution
   - Exit reason bar chart
   - Return vs days held scatter
   - Winners vs losers comparison
   - Monthly performance bars

5. **Feature Importance**
   - Top 20 features bar chart
   - SHAP values (optional)

6. **Prediction Tracking**
   - ML score distributions
   - Performance by probability bins
   - Buy list analysis

---

## Integration with QSS

### Notebook vs Scripts

| Task | Notebook | Scripts | When to Use |
|------|----------|---------|-------------|
| **Daily scanning** | ✅ Interactive | ✅ Automated | Notebook: exploration<br>Scripts: production |
| **Model training** | ✅ Iterative | ✅ Batch | Notebook: development<br>Scripts: retraining |
| **Data exploration** | ✅ Visual | ❌ Limited | Notebook: always |
| **Feature testing** | ✅ Quick | ⚠️ Slow | Notebook: prototyping |
| **Production deployment** | ❌ Manual | ✅ Automated | Scripts: always |

### Workflow

```
Development Cycle:
1. Notebook: Prototype features
2. Notebook: Train/evaluate models
3. Notebook: Analyze results
4. Scripts: Deploy to production
   └── optimized_scanner.py --use-ml

Production Monitoring:
1. Scripts: Daily scanner
2. Notebook: Weekly analysis
3. Notebook: Monthly model review
```

---

## Advanced Features

### Custom Analysis Sections

Add your own analysis:

```python
# Create new markdown cell
### X.X My Custom Analysis

# Create code cell
# Your analysis code
fig, ax = plt.subplots(figsize=(12, 6))
# ... plotting
plt.show()
```

### Save Results

```python
# Save plots
plt.savefig('my_analysis.png', dpi=300, bbox_inches='tight')

# Save dataframes
results_df.to_csv('results.csv')
results_df.to_parquet('results.parquet')

# Save models
trainer.save_model('models/my_model.json')
```

### Batch Analysis

```python
# Analyze multiple tickers
for ticker in ['AAPL', 'MSFT', 'NVDA']:
    df = repo.get_ticker_data(ticker)
    # ... analysis
    plt.savefig(f'analysis_{ticker}.png')
```

---

## Best Practices

### 1. Cell Organization

**DO**:
- Keep cells focused (one task per cell)
- Add markdown headers between sections
- Document findings in markdown cells

**DON'T**:
- Put entire workflow in one cell
- Mix data loading and analysis
- Skip documentation

### 2. Memory Management

**DO**:
- Delete large dataframes when done: `del dataset_b`
- Use sampling for EDA: `df.sample(1000)`
- Clear outputs: Kernel → Restart & Clear Output

**DON'T**:
- Keep all data in memory
- Load full universe without need
- Run SHAP on full dataset

### 3. Version Control

**DO**:
- Clear outputs before committing
- Save important results externally
- Document experiment parameters

**DON'T**:
- Commit with outputs
- Rely on notebook for critical data
- Forget to document changes

---

## Troubleshooting

### Common Issues

1. **"Module not found"**
   - Check `sys.path.insert(0, str(project_root))`
   - Restart kernel

2. **"File not found"**
   - Check paths are absolute
   - Verify files exist with `.exists()`

3. **Kernel crashes**
   - Reduce universe size
   - Sample large datasets
   - Restart kernel

4. **Slow execution**
   - Use `%%time` to profile
   - Cache intermediate results
   - Skip expensive computations (SHAP)

---

## Next Steps

### Immediate

1. **Launch notebook**:
   ```bash
   jupyter notebook notebooks/QSS_Complete_Workflow.ipynb
   ```

2. **Run test mode**: Execute with small universe to verify

3. **Explore EDA sections**: Understand available analysis

### Short-term

1. **Add custom analysis**: Create sections for your specific needs
2. **Integrate findings**: Update production scripts based on insights
3. **Document experiments**: Track what works and what doesn't

### Long-term

1. **Create specialized notebooks**: Specific analyses deserve dedicated notebooks
2. **Automate reports**: Convert notebook to automated reporting
3. **Share insights**: Export key findings to documentation

---

## Summary

**Created**: All-in-one QSS workflow notebook with comprehensive EDA

**Benefits**:
- ✅ Interactive experimentation
- ✅ Rapid prototyping
- ✅ Visual analysis
- ✅ Quick iteration
- ✅ Learning tool

**Use for**:
- Daily analysis
- Model development
- Feature engineering
- Strategy research
- Performance monitoring

**Complements**:
- Production scripts for automation
- Documentation for understanding
- Tests for validation

**Result**: Complete interactive interface for the entire QSS workflow!
