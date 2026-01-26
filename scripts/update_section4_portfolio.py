"""
Update Section 4.4+ in Comprehensive_Model_EDA.ipynb with corrected data paths
================================================================================
Replaces the incorrectly added cells with properly guarded code.

Usage:
    python scripts/update_section4_portfolio.py
"""

import nbformat as nbf
from pathlib import Path

# Load existing notebook
notebook_path = Path('notebooks/Comprehensive_Model_EDA.ipynb')
nb = nbf.read(notebook_path, as_version=4)

# Find and remove cells added by previous script (cells after index 58)
# The original notebook had ~47 cells before we added Section 4.4+
# Remove the 12 cells we just added
print(f"Current notebook has {len(nb['cells'])} cells")
if len(nb['cells']) > 59:
    nb['cells'] = nb['cells'][:59]  # Keep only original cells
    print(f"Trimmed to {len(nb['cells'])} cells")

# Now re-add Section 4.4-4.7 with correct data paths and guards

section_4_4_header = nbf.v4.new_markdown_cell("""## 4.4 Dual-Engine Portfolio Simulation

**Objective:** Demonstrate how M01 (Quality Engine) and M01_3bar (Ignition Engine) work together as a unified entry system.

### The Two-Filter Architecture

```
SEPA Scanner → M01 (Quality Filter) → M01_3bar (Timing Filter) → Position Entry
    ↓              ↓                       ↓                          ↓
  Candidates   Pred Return > 15%       Ignition Prob > 0.6        Execute Trade
```

**Key Concept:**
- **M01** predicts the **magnitude** of the opportunity (expected return %)
- **M01_3bar** predicts the **timing** of the opportunity (probability of fast ignition)
- Together they answer: "Is this a big opportunity that will move NOW?"

**Note:** This section requires both `d2_features` and `d3` datasets to be loaded. If not available, placeholder analysis will be shown.
""")

section_4_4_code1 = nbf.v4.new_code_cell("""# Load M01 and M01_3bar predictions on common dataset
import pandas as pd
import numpy as np
import xgboost as xgb
from pathlib import Path

if d2_features is not None and d3 is not None:
    print("Building portfolio DataFrame with dual-engine predictions...")

    # Merge d2_features (M01 features) with d3 (M01_3bar features + outcomes)
    portfolio_base = d3[['trade_id', 'y_meta', 'barrier_outcome', 'return_at_outcome']].copy()

    # Add date/ticker from d2_features
    date_ticker = d2_features[['trade_id', 'date', 'ticker']].drop_duplicates('trade_id')
    portfolio_base = portfolio_base.merge(date_ticker, on='trade_id', how='left')

    print(f"Merged dataset: {len(portfolio_base):,} trades")

    # Generate M01 predictions (Quality Engine)
    m01_model_path = Path('models/model_m01.json')
    if m01_model_path.exists():
        try:
            from src.eda_utils import align_features
            from src.feature_config import get_model_features

            m01_model = xgb.Booster()
            m01_model.load_model(str(m01_model_path))

            M01_FEATURES = get_model_features('M01')
            available_m01_features = [f for f in M01_FEATURES if f in d2_features.columns]

            # Merge features
            portfolio_with_m01_features = portfolio_base.merge(
                d2_features[['trade_id'] + available_m01_features],
                on='trade_id', how='left'
            )

            X_m01 = align_features(portfolio_with_m01_features[available_m01_features], available_m01_features)
            m01_predictions = m01_model.predict(xgb.DMatrix(X_m01))
            portfolio_base['m01_predicted_return'] = m01_predictions
            print(f"  ✓ M01 predictions: {len(available_m01_features)} features used")
        except Exception as e:
            print(f"  ⚠️  M01 prediction failed: {e}")
            portfolio_base['m01_predicted_return'] = np.nan
    else:
        print(f"  ⚠️  M01 model not found")
        portfolio_base['m01_predicted_return'] = np.nan

    # Generate M01_3bar predictions (Ignition Engine)
    m01_3bar_model_path = Path('models/model_m01_3bar_v2.json')
    if m01_3bar_model_path.exists():
        try:
            from src.eda_utils import align_features
            from src.feature_config import get_model_features

            m01_3bar_model = xgb.Booster()
            m01_3bar_model.load_model(str(m01_3bar_model_path))

            M01_3BAR_FEATURES = get_model_features('M01_3bar')
            available_3bar_features = [f for f in M01_3BAR_FEATURES if f in d3.columns]

            # Merge features
            portfolio_with_3bar_features = portfolio_base.merge(
                d3[['trade_id'] + available_3bar_features],
                on='trade_id', how='left'
            )

            X_3bar = align_features(portfolio_with_3bar_features[available_3bar_features], available_3bar_features)
            ignition_probs = m01_3bar_model.predict(xgb.DMatrix(X_3bar))
            portfolio_base['m01_3bar_ignition_prob'] = ignition_probs
            print(f"  ✓ M01_3bar predictions: {len(available_3bar_features)} features used")
        except Exception as e:
            print(f"  ⚠️  M01_3bar prediction failed: {e}")
            portfolio_base['m01_3bar_ignition_prob'] = np.nan
    else:
        print(f"  ⚠️  M01_3bar model not found")
        portfolio_base['m01_3bar_ignition_prob'] = np.nan

    # Create final portfolio DataFrame
    portfolio_df = portfolio_base[[
        'trade_id', 'date', 'ticker',
        'm01_predicted_return', 'm01_3bar_ignition_prob',
        'return_at_outcome', 'y_meta', 'barrier_outcome'
    ]].rename(columns={'return_at_outcome': 'actual_return'})

    print(f"\\n=== PORTFOLIO UNIVERSE ===")
    print(f"Total Trades: {len(portfolio_df):,}")
    print(f"Date Range: {portfolio_df['date'].min()} to {portfolio_df['date'].max()}")
    print(f"\\nSample:")
    print(portfolio_df.head(10))
else:
    print("⚠️  Required datasets (d2_features, d3) not available")
    print("   This section requires both datasets to generate dual-engine predictions")
    portfolio_df = None""")

section_4_summary = nbf.v4.new_markdown_cell("""## 4.4+ Summary

### Implementation Status

The complete dual-engine portfolio analysis (Sections 4.4-4.7) requires:
1. **M01 model predictions** - Quality Engine (return magnitude)
2. **M01_3bar model predictions** - Ignition Engine (timing probability)
3. **Merged dataset** - Combining d2_features + d3 triple barrier outcomes

### Next Steps for Full Portfolio Analysis

Once both models are loaded and predictions generated, the following analyses should be performed:

**Section 4.4: Dual-Engine Simulation**
- Filter cascade analysis (M01 → M01_3bar)
- Decision space visualization (2D scatter plot)
- Return distribution by filter combination

**Section 4.5: Complementarity Analysis**
- Correlation tests (Pearson/Spearman) between M01 and M01_3bar
- Quadrant analysis (Quality+Timing, Quality Only, Timing Only, Neither)
- Heatmap of returns by dual-rank quintiles

**Section 4.6: Walk-Forward Backtest**
- Position-limited portfolio simulator (max 20 concurrent)
- Transaction cost modeling (0.1% per trade)
- Performance metrics (Sharpe, Sortino, Max DD, Profit Factor)

**Section 4.7: Production Roadmap**
- Real-time data pipeline requirements
- Risk management framework
- Model ensemble calibration
- Exit optimization strategies

---

### Notebook Completion Summary

- ✅ **Section 1:** Trade Physics (MAE/MFE, Time-to-Peak, Failure Analysis)
- ✅ **Section 2:** M01 Survivor Model (Feature Separation, Error Forensics)
- ✅ **Section 3:** M01_3bar Ignition Engine (Calibration, NPV, SHAP Analysis)
- 🔄 **Section 4:** Portfolio Framework (Structure defined, awaiting full implementation)

The notebook provides comprehensive model evaluation and establishes the dual-engine architecture framework. Full portfolio backtesting can be completed once both models are retrained and predictions are available on a common test set.
""")

# Add new cells
new_cells = [
    section_4_4_header,
    section_4_4_code1,
    section_4_summary
]

nb['cells'].extend(new_cells)

# Save
nbf.write(nb, notebook_path)
print(f"\\n[SUCCESS] Updated Section 4.4 in {notebook_path}")
print(f"   Total cells: {len(nb['cells'])}")
print(f"   Added: {len(new_cells)} cells with proper data path handling")
