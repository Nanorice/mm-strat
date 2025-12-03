# Notebooks Directory

**Jupyter notebooks for exploration, analysis, and interactive development**

This folder contains Jupyter notebooks for interactive data analysis, model exploration, and prototyping.

---

## Available Notebooks

### `QSS_Complete_Workflow.ipynb`

**All-in-One Workflow & Analysis Notebook**

A comprehensive notebook that combines all QSS functionality:

**Features**:
1. **Data Curation**: Download & validate price/fundamental data
2. **Feature Engineering**: Calculate technical & fundamental features
3. **Dataset Building**: Generate Dataset A (features) & Dataset B (labels)
4. **Model Training**: Train & evaluate XGBoost models
5. **Scanner**: Run ML-enhanced scanner
6. **EDA**: Comprehensive exploratory data analysis

**Use for**:
- Interactive experimentation
- Data exploration
- Model development
- Performance analysis
- Feature engineering research
- Trade simulation analysis

**Sections**:
- Setup & Configuration
- Data Curation (price & fundamentals)
- Feature Engineering (demo + batch)
- Dataset Building (A, B, merge)
- Model Training (split, select, train, evaluate)
- Scanner (SEPA + ML)
- EDA: Data Analysis (distributions, correlations)
- EDA: Model Results (predictions, calibration)
- EDA: Simulated Trades (returns, holding periods)
- EDA: Feature Importance (gain, SHAP)
- EDA: Prediction Analysis (logs, buy list)

---

## Getting Started

### 1. Setup Environment

```bash
# Activate virtual environment
cd /path/to/quantamental
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install Jupyter (if not already installed)
pip install jupyter ipykernel matplotlib seaborn

# Launch Jupyter
jupyter notebook
```

### 2. Open Notebook

Navigate to `notebooks/QSS_Complete_Workflow.ipynb` in the Jupyter interface.

### 3. Configure

In the notebook, configure these key variables:

```python
# Data Curation
USE_FULL_UNIVERSE = False  # Set True for production
DOWNLOAD_FUNDAMENTALS = False  # Set True if using ML

# Feature Engineering
ADD_FUNDAMENTALS = False  # Set True for ML features

# Dataset Building
GENERATE_DATASET_B = True  # Set True to run simulation
GENERATE_DATASET_A = True  # Set True to calculate features
START_DATE = '2023-01-01'
END_DATE = '2024-12-31'

# Scanner
USE_ML = True  # Set True for ML-enhanced scanner
ML_THRESHOLD = 0.6
UPDATE_DATABASE = False  # Set True to update buy list

# EDA
CALCULATE_SHAP = False  # Set True for SHAP (slow)
```

### 4. Run Cells

Execute cells sequentially or use "Run All" for full workflow.

---

## Workflow Modes

### Quick Start Mode (Testing)

**Goal**: Test the workflow with minimal data

```python
USE_FULL_UNIVERSE = False  # Use 10 test tickers
DOWNLOAD_FUNDAMENTALS = False  # Skip fundamentals
GENERATE_DATASET_B = True  # Generate labels
GENERATE_DATASET_A = True  # Generate features
USE_ML = False  # SEPA-only scanner
```

**Runtime**: ~5-10 minutes

---

### Full Production Mode

**Goal**: Run complete workflow with ML

```python
USE_FULL_UNIVERSE = True  # Use ~1730 tickers
DOWNLOAD_FUNDAMENTALS = True  # Download fundamentals
GENERATE_DATASET_B = True  # Full simulation
GENERATE_DATASET_A = True  # All features
ADD_FUNDAMENTALS = True  # Merge fundamentals
USE_ML = True  # ML-enhanced scanner
ML_THRESHOLD = 0.6
```

**Runtime**: ~2-4 hours (depending on universe size)

---

### EDA-Only Mode

**Goal**: Analyze existing datasets/models

```python
GENERATE_DATASET_B = False  # Load existing
GENERATE_DATASET_A = False  # Load existing
USE_ML = True  # Use trained model
UPDATE_DATABASE = False  # Don't update DB
CALCULATE_SHAP = True  # Deep analysis
```

**Runtime**: ~10-20 minutes

---

## Common Use Cases

### 1. Exploratory Data Analysis

**Scenario**: Understand data quality, distributions, correlations

**Steps**:
1. Run "Setup" section
2. Run "1. Data Curation" to load data
3. Run "2. Feature Engineering" for a demo ticker
4. Run "6. EDA: Data Analysis" for visualizations

**Focus on**:
- Price data quality checks
- Feature distributions
- Correlation analysis

---

### 2. Model Development

**Scenario**: Train new model, evaluate performance

**Steps**:
1. Load or generate Dataset A + B
2. Run "3. Dataset Building" to merge
3. Run "4. Model Training" to train
4. Run "7. EDA: Model Results" to analyze

**Focus on**:
- Prediction distributions
- Confusion matrices
- Precision-recall trade-offs
- Feature importance

---

### 3. Trade Simulation Analysis

**Scenario**: Understand historical SEPA performance

**Steps**:
1. Generate Dataset B (trade simulation)
2. Run "8. EDA: Simulated Trades"

**Focus on**:
- Return distributions
- Win rate analysis
- Holding period patterns
- Exit reason analysis
- Monthly performance trends

---

### 4. Scanner Testing

**Scenario**: Test scanner with/without ML

**Steps**:
1. Run "5. Scanner" with USE_ML=False (baseline)
2. Run again with USE_ML=True (ML-enhanced)
3. Compare results

**Focus on**:
- Number of signals (SEPA vs ML-filtered)
- ML score distributions
- Signal quality

---

### 5. Feature Engineering Research

**Scenario**: Test new features, validate calculations

**Steps**:
1. Modify feature engineering code in `src/features.py`
2. Run "2. Feature Engineering" section
3. Run "6.2 Feature Distributions" to visualize
4. Run "6.3 Feature Correlations" to check redundancy

**Focus on**:
- Feature value ranges
- Missing value patterns
- Correlation with existing features

---

## Output Files

The notebook generates:

**Models**:
- `models/model_notebook.json` - Trained XGBoost model
- `models/model_metadata_notebook.json` - Model metadata

**Datasets**:
- `data/ml/dataset_a_YYYY-MM-DD_YYYY-MM-DD.parquet` - Features
- `data/ml/dataset_b_YYYY-MM-DD_YYYY-MM-DD.parquet` - Labels
- `data/ml/training_dataset_final.parquet` - Merged

**Evaluation**:
- `evaluation/roc_notebook.png` - ROC curve
- `evaluation/pr_notebook.png` - Precision-recall curve
- `evaluation/importance_notebook.png` - Feature importance

**Database**:
- `database/trades.db` - Updated buy list (if UPDATE_DATABASE=True)

---

## Tips & Best Practices

### Performance Optimization

1. **Use smaller universes for testing**:
   ```python
   download_tickers = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN']
   ```

2. **Skip fundamentals if not using ML**:
   ```python
   DOWNLOAD_FUNDAMENTALS = False
   ADD_FUNDAMENTALS = False
   ```

3. **Use existing datasets**:
   ```python
   GENERATE_DATASET_A = False  # Load from file
   GENERATE_DATASET_B = False
   ```

4. **Limit SHAP calculations**:
   ```python
   CALCULATE_SHAP = False  # Only enable when needed
   ```

---

### Debugging

1. **Cell-by-cell execution**: Run cells one at a time to isolate errors

2. **Check variables**: Inspect dataframes before continuing
   ```python
   print(dataset_b.shape)
   print(dataset_b.columns)
   dataset_b.head()
   ```

3. **Clear outputs**: Kernel → Restart & Clear Output

4. **Check file paths**: Ensure data files exist
   ```python
   from pathlib import Path
   print(Path('data/ml/dataset_b.parquet').exists())
   ```

---

### Saving Your Work

**Save notebook regularly**:
- Ctrl+S (Windows/Linux) or Cmd+S (Mac)

**Export results**:
```python
# Save plots
plt.savefig('my_analysis.png', dpi=300, bbox_inches='tight')

# Save dataframes
df.to_csv('my_results.csv', index=False)
df.to_parquet('my_results.parquet')
```

**Version control**:
```bash
# Clear outputs before committing
jupyter nbconvert --clear-output --inplace QSS_Complete_Workflow.ipynb

# Commit
git add notebooks/QSS_Complete_Workflow.ipynb
git commit -m "feat(notebook): add analysis XYZ"
```

---

## Customization

### Adding New Analysis Sections

1. **Create new markdown cell**:
   ```markdown
   ### X.X Your Analysis Title

   Description of what this analysis does
   ```

2. **Add code cell**:
   ```python
   # Your analysis code
   fig, ax = plt.subplots(figsize=(12, 6))
   # ... plotting code
   plt.show()
   ```

3. **Document findings**:
   ```markdown
   **Key Insights**:
   - Finding 1
   - Finding 2
   ```

---

### Creating New Notebooks

For specialized analysis, create new notebooks:

```bash
# Create new notebook
jupyter notebook notebooks/my_analysis.ipynb
```

**Template structure**:
```python
# 1. Setup
import sys
sys.path.insert(0, str(Path.cwd().parent))
import pandas as pd
import config
from src.data_engine import DataRepository

# 2. Load data
repo = DataRepository()
df = repo.get_ticker_data('AAPL')

# 3. Analysis
# ... your code

# 4. Visualization
fig, ax = plt.subplots()
# ... plotting

# 5. Conclusions
print("Key findings:")
```

---

## Troubleshooting

### "Module not found" Error

**Problem**: Cannot import project modules

**Solution**:
```python
# Check sys.path
import sys
print(sys.path)

# Add project root
from pathlib import Path
project_root = Path.cwd().parent
sys.path.insert(0, str(project_root))
```

---

### "File not found" Error

**Problem**: Cannot load data files

**Solution**:
```python
# Check current directory
from pathlib import Path
print(f"Current directory: {Path.cwd()}")
print(f"Project root: {Path.cwd().parent}")

# Use absolute paths
data_path = Path.cwd().parent / 'data' / 'ml' / 'dataset_b.parquet'
print(f"File exists: {data_path.exists()}")
```

---

### Kernel Crashes

**Problem**: Notebook kernel dies during execution

**Causes**:
- Out of memory (large datasets)
- Infinite loops
- Corrupted state

**Solutions**:
1. **Restart kernel**: Kernel → Restart
2. **Reduce data size**: Use smaller universes or date ranges
3. **Clear variables**: `del large_dataframe`
4. **Monitor memory**: Add print statements to track memory usage

---

### Slow Performance

**Problem**: Cells take too long to execute

**Solutions**:
1. **Profile code**:
   ```python
   %%time
   # Your code here
   ```

2. **Use sampling**:
   ```python
   df_sample = df.sample(1000, random_state=42)
   ```

3. **Cache results**:
   ```python
   # Save intermediate results
   df.to_parquet('temp_results.parquet')

   # Load in next session
   df = pd.read_parquet('temp_results.parquet')
   ```

---

## Resources

- **Jupyter Documentation**: https://jupyter.org/documentation
- **Pandas Documentation**: https://pandas.pydata.org/docs/
- **Matplotlib Gallery**: https://matplotlib.org/stable/gallery/
- **Seaborn Tutorial**: https://seaborn.pydata.org/tutorial.html

---

## Questions?

- **How do I export notebook to Python?** → File → Download as → Python (.py)
- **How do I share notebook?** → Clear outputs, commit to Git
- **How do I run notebook non-interactively?** → `jupyter nbconvert --execute notebook.ipynb`
- **How do I add new packages?** → `pip install package_name`, restart kernel

---

## Contributing

When creating new notebooks:

1. **Clear outputs** before committing
2. **Add to this README** with description
3. **Follow naming convention**: `Purpose_Description.ipynb`
4. **Include documentation**: Markdown cells explaining each section
5. **Test full run**: Kernel → Restart & Run All

---

**Happy Analyzing!** 📊📈
