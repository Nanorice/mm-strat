"""
Script to build the Comprehensive EDA Notebook programmatically.
This is more efficient than adding cells one-by-one via NotebookEdit.
"""

import json
from pathlib import Path

def create_cell(cell_type, source):
    """Helper to create a notebook cell"""
    cell = {
        'cell_type': cell_type,
        'metadata': {},
        'source': source if isinstance(source, list) else [source]
    }

    if cell_type == 'code':
        cell['outputs'] = []
        cell['execution_count'] = None

    return cell

# Define all cells
cells = []

# Header
cells.append(create_cell('markdown', """# Comprehensive Model EDA: M01 & M01_3BAR Deep Dive

**Objective:** Professional analysis of both M01 (Signal Regressor) and M01_3BAR (Ignition Engine) models with industry-standard metrics.

## Structure
1. **Trade Physics** - Dataset DNA analysis (MAE/MFE, Time-to-Peak, Failure Anatomy)
2. **M01 Deep Dive** - Signal regressor evaluation (Feature separation, FOMO/Toxic analysis, Event study)
3. **M01_3BAR Deep Dive** - Ignition engine validation (Calibration, Negative filter, SHAP clustering)
4. **Portfolio Application** - Framework for model deployment (Placeholder)

---

**Author:** Quantamental Trading System
**Date:** 2026-01-23
**Models:** M01 (v1), M01_3BAR_V2"""))

# Setup
cells.append(create_cell('code', """# Imports and Setup
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import xgboost as xgb
import sys
from scipy import stats
from scipy.stats import ks_2samp, wasserstein_distance
from sklearn.calibration import calibration_curve
import warnings
warnings.filterwarnings('ignore')

# Add project root to path
sys.path.append(str(Path.cwd().parent))

# Import custom modules
from src.feature_config import M01_FEATURES, M01_3BAR_FEATURES_V2, get_model_features
from src import eda_utils

# Plotting configuration
%matplotlib inline
plt.style.use('seaborn-v0_8-whitegrid')
sns.set_palette("husl")
pd.set_option('display.max_columns', 50)
pd.set_option('display.precision', 2)

# Figure settings for high-quality output
plt.rcParams['figure.dpi'] = 100
plt.rcParams['savefig.dpi'] = 300
plt.rcParams['figure.figsize'] = (12, 6)

print("✅ Environment setup complete")
print(f"📦 Loaded M01 features: {len(M01_FEATURES)}")
print(f"📦 Loaded M01_3BAR_V2 features: {len(M01_3BAR_FEATURES_V2)}")"""))

# Load datasets
cells.append(create_cell('code', """# Load Datasets
print("Loading datasets...")

# D2 Rehydrated (for Section 1: Trade Physics)
d2_rehydrated_path = Path('../data/ml/d2_rehydrated.parquet')
if d2_rehydrated_path.exists():
    d2_rehydrated = pd.read_parquet(d2_rehydrated_path)
    print(f"✅ D2 Rehydrated: {len(d2_rehydrated)} rows, {d2_rehydrated['trade_id'].nunique()} unique trades")

    # Add trade sequence (day_in_trade, is_exit_day) if missing
    if 'day_in_trade' not in d2_rehydrated.columns:
        print("   Adding day_in_trade and is_exit_day columns...")
        d2_rehydrated = eda_utils.add_trade_sequence(d2_rehydrated, date_col='Date')
        print(f"   ✅ Trade sequence added")
else:
    print(f"⚠️  D2 Rehydrated not found at {d2_rehydrated_path}")
    d2_rehydrated = None

# D2 Features (for Section 2: M01 Analysis)
d2_features_path = Path('../data/ml/d2_features.parquet')
if d2_features_path.exists():
    d2_features = pd.read_parquet(d2_features_path)
    print(f"✅ D2 Features: {len(d2_features)} rows, {len(d2_features.columns)} columns")
else:
    print(f"⚠️  D2 Features not found at {d2_features_path}")
    d2_features = None

# D3 Triple Barrier (for Section 3: M01_3BAR Analysis)
d3_path = Path('../data/ml/d3_triple_barrier_120d.parquet')
if d3_path.exists():
    d3 = pd.read_parquet(d3_path)
    print(f"✅ D3 Triple Barrier: {len(d3)} rows")
    print(f"   Barrier outcomes: {d3['barrier_outcome'].value_counts().to_dict()}")
else:
    print(f"⚠️  D3 Triple Barrier not found at {d3_path}")
    d3 = None

print("\\n📊 Data loading complete")"""))

# Section 1 Header
cells.append(create_cell('markdown', """# Section 1: Trade Physics (Dataset DNA Analysis)

## Objective
Analyze the fundamental characteristics of trades in the D2 rehydrated dataset to understand the physical constraints of the "Ignition" concept.

### Key Metrics
1. **MAE/MFE Analysis** - E-Ratio validation (Industry benchmark: >3.0)
2. **Time-to-Peak** - Optimal holding period identification
3. **Failure Anatomy** - Understanding how and when trades fail

---"""))

# 1.1 MAE/MFE Analysis
cells.append(create_cell('markdown', """## 1.1 Maximum Adverse/Favorable Excursion (MAE/MFE)

**Goal:** Calculate E-Ratio to validate breakout strategy quality.

**Industry Benchmark:** E-Ratio > 3.0 confirms a valid breakout strategy.

**Research Questions:**
- What % of trades have E-Ratio > 3.0?
- Do igniters (label=1) have higher E-Ratio than drifters?
- What's the typical MAE before runners take off? (Informs stop-loss placement)"""))

cells.append(create_cell('code', """# Calculate MAE/MFE for all trades
if d2_rehydrated is not None:
    print("Calculating MAE/MFE...")
    mae_mfe_df = eda_utils.calculate_mae_mfe(d2_rehydrated)

    print(f"\\n📊 MAE/MFE Analysis ({len(mae_mfe_df)} trades):")
    print(f"   Median E-Ratio: {mae_mfe_df['E_Ratio'].median():.2f}")
    print(f"   Mean E-Ratio: {mae_mfe_df['E_Ratio'].mean():.2f}")
    print(f"   % with E-Ratio > 3.0: {(mae_mfe_df['E_Ratio'] > 3.0).mean():.1%}")
    print(f"   Median MFE: {mae_mfe_df['MFE'].median():.1f}%")
    print(f"   Median MAE: {mae_mfe_df['MAE'].median():.1f}%")
    print(f"   Median Regret: {mae_mfe_df['regret'].median():.1f}%")

    display(mae_mfe_df.describe())
else:
    print("⚠️  D2 Rehydrated not loaded, skipping MAE/MFE analysis")"""))

cells.append(create_cell('code', """# Visualizations: MAE/MFE Analysis
if d2_rehydrated is not None and 'mae_mfe_df' in locals():
    # Create evaluation directory if it doesn't exist
    eval_dir = Path('../evaluation')
    eval_dir.mkdir(exist_ok=True)

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))

    # 1. Scatter: MFE vs MAE
    ax1 = axes[0, 0]
    # Add return quartiles for coloring
    mae_mfe_df['return_quartile'] = pd.qcut(mae_mfe_df['final_return'], q=4, labels=['Q1', 'Q2', 'Q3', 'Q4'])
    scatter = ax1.scatter(mae_mfe_df['MAE'], mae_mfe_df['MFE'],
                         c=mae_mfe_df['final_return'], cmap='RdYlGn', alpha=0.6, s=30)
    ax1.set_xlabel('MAE (Max Adverse Excursion %)')
    ax1.set_ylabel('MFE (Max Favorable Excursion %)')
    ax1.set_title('MFE vs MAE (colored by final return)')
    ax1.axhline(0, color='black', linestyle='--', linewidth=0.5)
    ax1.axvline(0, color='black', linestyle='--', linewidth=0.5)
    plt.colorbar(scatter, ax=ax1, label='Final Return %')
    ax1.grid(True, alpha=0.3)

    # 2. E-Ratio Distribution
    ax2 = axes[0, 1]
    mae_mfe_df['E_Ratio'].hist(bins=50, ax=ax2, color='steelblue', edgecolor='black')
    ax2.axvline(3.0, color='red', linestyle='--', linewidth=2, label='Benchmark (3.0)')
    ax2.axvline(mae_mfe_df['E_Ratio'].median(), color='green', linestyle='--', linewidth=2, label=f'Median ({mae_mfe_df["E_Ratio"].median():.2f})')
    ax2.set_xlabel('E-Ratio (MFE / |MAE|)')
    ax2.set_ylabel('Frequency')
    ax2.set_title('E-Ratio Distribution')
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    # 3. Box plots: E-Ratio by Winners vs Losers
    ax3 = axes[1, 0]
    mae_mfe_df['trade_type'] = mae_mfe_df['final_return'].apply(lambda x: 'Winner' if x > 0 else 'Loser')
    sns.boxplot(data=mae_mfe_df, x='trade_type', y='E_Ratio', ax=ax3, palette={'Winner': 'green', 'Loser': 'red'})
    ax3.set_title('E-Ratio: Winners vs Losers')
    ax3.set_ylabel('E-Ratio')
    ax3.axhline(3.0, color='blue', linestyle='--', label='Benchmark')
    ax3.legend()
    ax3.grid(True, alpha=0.3)

    # 4. Regret Analysis
    ax4 = axes[1, 1]
    mae_mfe_df['regret'].hist(bins=50, ax=ax4, color='coral', edgecolor='black')
    ax4.axvline(mae_mfe_df['regret'].median(), color='darkred', linestyle='--', linewidth=2,
                label=f'Median Regret: {mae_mfe_df["regret"].median():.1f}%')
    ax4.set_xlabel('Regret (MFE - Final Return %)')
    ax4.set_ylabel('Frequency')
    ax4.set_title('Profit Left on Table (Regret Analysis)')
    ax4.legend()
    ax4.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig('../evaluation/section1_mae_mfe_analysis.png', dpi=300, bbox_inches='tight')
    plt.show()

    print("\\n✅ MAE/MFE visualizations complete")"""))

# 1.2 Time-to-Peak Analysis
cells.append(create_cell('markdown', """## 1.2 Time-to-Peak Analysis

**Goal:** Understand when trades reach maximum profit to inform optimal holding periods.

**Research Questions:**
- What % of winners peak within 10/15/20 days?
- Median days to peak vs total holding period?
- Average fade from peak to exit (capital efficiency loss)?"""))

cells.append(create_cell('code', """# Calculate Time-to-Peak
if d2_rehydrated is not None:
    print("Calculating Time-to-Peak...")
    ttp_df = eda_utils.calculate_time_to_peak(d2_rehydrated)

    print(f"\\n📊 Time-to-Peak Analysis ({len(ttp_df)} trades):")
    print(f"   Median days to peak: {ttp_df['days_to_peak'].median():.0f}")
    print(f"   Mean days to peak: {ttp_df['days_to_peak'].mean():.1f}")
    print(f"   % peaked within 10 days: {(ttp_df['days_to_peak'] <= 10).mean():.1%}")
    print(f"   % peaked within 15 days: {(ttp_df['days_to_peak'] <= 15).mean():.1%}")
    print(f"   % peaked within 20 days: {(ttp_df['days_to_peak'] <= 20).mean():.1%}")
    print(f"   Avg fade from peak to exit: {ttp_df['peak_to_exit_fade'].mean():.1f}%")

    display(ttp_df.describe())
else:
    print("⚠️  D2 Rehydrated not loaded")"""))

cells.append(create_cell('code', """# Visualizations: Time-to-Peak
if d2_rehydrated is not None and 'ttp_df' in locals():
    # Ensure evaluation directory exists
    eval_dir = Path('../evaluation')
    eval_dir.mkdir(exist_ok=True)

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))

    # 1. CDF: % peaked by day N
    ax1 = axes[0, 0]
    sorted_days = np.sort(ttp_df['days_to_peak'])
    cdf = np.arange(1, len(sorted_days) + 1) / len(sorted_days)
    ax1.plot(sorted_days, cdf * 100, linewidth=2, color='navy')
    ax1.set_xlabel('Days to Peak')
    ax1.set_ylabel('% of Trades Peaked')
    ax1.set_title('Cumulative Distribution: Days to Peak')
    ax1.grid(True, alpha=0.3)
    ax1.axhline(80, color='red', linestyle='--', label='80% threshold')
    ax1.legend()

    # 2. Histogram: Days to peak
    ax2 = axes[0, 1]
    ttp_df['days_to_peak'].hist(bins=30, ax=ax2, color='teal', edgecolor='black')
    ax2.axvline(ttp_df['days_to_peak'].median(), color='red', linestyle='--', linewidth=2,
                label=f'Median: {ttp_df["days_to_peak"].median():.0f} days')
    ax2.set_xlabel('Days to Peak')
    ax2.set_ylabel('Frequency')
    ax2.set_title('Days to Peak Distribution')
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    # 3. Scatter: Days to peak vs final return
    ax3 = axes[1, 0]
    ttp_df['return_quartile'] = pd.qcut(ttp_df['peak_return'], q=4, labels=['Q1', 'Q2', 'Q3', 'Q4'], duplicates='drop')
    colors = {'Q1': 'red', 'Q2': 'orange', 'Q3': 'lightgreen', 'Q4': 'darkgreen'}
    for q in ttp_df['return_quartile'].unique():
        subset = ttp_df[ttp_df['return_quartile'] == q]
        ax3.scatter(subset['days_to_peak'], subset['peak_return'], label=q, alpha=0.6, s=30, color=colors.get(q, 'gray'))
    ax3.set_xlabel('Days to Peak')
    ax3.set_ylabel('Peak Return %')
    ax3.set_title('Days to Peak vs Peak Return (by quartile)')
    ax3.legend(title='Return Quartile')
    ax3.grid(True, alpha=0.3)

    # 4. Box plot: Days to peak by return quartile
    ax4 = axes[1, 1]
    sns.boxplot(data=ttp_df, x='return_quartile', y='days_to_peak', ax=ax4, palette='viridis')
    ax4.set_xlabel('Return Quartile')
    ax4.set_ylabel('Days to Peak')
    ax4.set_title('Time to Peak by Return Quartile')
    ax4.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig('../evaluation/section1_time_to_peak.png', dpi=300, bbox_inches='tight')
    plt.show()

    print("\\n✅ Time-to-Peak visualizations complete")"""))

# 1.3 Failure Anatomy
cells.append(create_cell('markdown', """## 1.3 Failure Anatomy

**Goal:** Understand how and when trades fail.

**Research Questions:**
- Do failures happen instantly (Day 1-2 rejection) or drift slowly (Day 20)?
- What % break -5% stop within first 3 days?
- Average drawdown of losers vs winners?"""))

cells.append(create_cell('code', """# Analyze Failures
if d2_rehydrated is not None:
    print("Analyzing failures...")
    failures_df = eda_utils.analyze_failures(d2_rehydrated, loss_threshold=-3.0)

    print(f"\\n📊 Failure Analysis ({len(failures_df)} losing trades):")
    print(f"   Avg final return: {failures_df['final_return'].mean():.1f}%")
    print(f"   Avg max drawdown: {failures_df['max_drawdown'].mean():.1f}%")
    print(f"   Avg days to -5% stop: {failures_df['days_to_stop'].mean():.1f}")
    print(f"   % hit -5% within 3 days: {(failures_df['days_to_stop'] <= 3).mean():.1%}")
    print(f"\\nExit reasons breakdown:")
    print(failures_df['exit_reason'].value_counts())

    display(failures_df.describe())
else:
    print("⚠️  D2 Rehydrated not loaded")"""))

cells.append(create_cell('code', """# Visualizations: Failure Anatomy
if d2_rehydrated is not None and 'failures_df' in locals():
    # Ensure evaluation directory exists
    eval_dir = Path('../evaluation')
    eval_dir.mkdir(exist_ok=True)

    fig, axes = plt.subplots(1, 3, figsize=(18, 5))

    # 1. Histogram: Days to -5% stop
    ax1 = axes[0]
    failures_df['days_to_stop'].dropna().hist(bins=20, ax=ax1, color='darkred', edgecolor='black')
    ax1.axvline(failures_df['days_to_stop'].median(), color='yellow', linestyle='--', linewidth=2,
                label=f'Median: {failures_df["days_to_stop"].median():.0f} days')
    ax1.set_xlabel('Days to -5% Stop')
    ax1.set_ylabel('Frequency')
    ax1.set_title('Speed of Failure (Days to -5% Drawdown)')
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # 2. Exit reason breakdown
    ax2 = axes[1]
    exit_counts = failures_df['exit_reason'].value_counts()
    ax2.bar(range(len(exit_counts)), exit_counts.values, color='salmon', edgecolor='black')
    ax2.set_xticks(range(len(exit_counts)))
    ax2.set_xticklabels(exit_counts.index, rotation=45, ha='right')
    ax2.set_ylabel('Count')
    ax2.set_title('Failure Exit Reasons')
    ax2.grid(True, alpha=0.3, axis='y')

    # 3. Max Drawdown distribution
    ax3 = axes[2]
    failures_df['max_drawdown'].hist(bins=30, ax=ax3, color='crimson', edgecolor='black')
    ax3.axvline(failures_df['max_drawdown'].median(), color='yellow', linestyle='--', linewidth=2,
                label=f'Median: {failures_df["max_drawdown"].median():.1f}%')
    ax3.set_xlabel('Max Drawdown %')
    ax3.set_ylabel('Frequency')
    ax3.set_title('Max Drawdown Distribution (Losers)')
    ax3.legend()
    ax3.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig('../evaluation/section1_failure_anatomy.png', dpi=300, bbox_inches='tight')
    plt.show()

    print("\\n✅ Failure anatomy visualizations complete")"""))

# Save the notebook
notebook = {
    'cells': cells,
    'metadata': {
        'kernelspec': {
            'display_name': 'Python 3',
            'language': 'python',
            'name': 'python3'
        },
        'language_info': {
            'name': 'python',
            'version': '3.11.0',
            'codemirror_mode': {
                'name': 'ipython',
                'version': 3
            },
            'file_extension': '.py',
            'mimetype': 'text/x-python',
            'nbconvert_exporter': 'python',
            'pygments_lexer': 'ipython3'
        }
    },
    'nbformat': 4,
    'nbformat_minor': 4
}

output_path = Path(__file__).parent.parent / 'notebooks' / 'Comprehensive_Model_EDA.ipynb'
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(notebook, f, indent=2, ensure_ascii=False)

print(f"[OK] Notebook created at: {output_path}")
print(f"Total cells: {len(cells)}")
print("Note: This is Section 1 only. Run the full notebook builder to add Sections 2-4.")
