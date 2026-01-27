"""
Add Section 2 cells to Comprehensive_Model_EDA.ipynb

This script adds M01 Survivor Model Deep Dive cells programmatically.
"""

import json
from pathlib import Path

# Load the notebook
notebook_path = Path(__file__).parent.parent / 'notebooks' / 'Comprehensive_Model_EDA.ipynb'

with open(notebook_path, 'r', encoding='utf-8') as f:
    nb = json.load(f)

# Define Section 2 cells
section2_cells = [
    # Cell 2.0: Load M01 Model
    {
        "cell_type": "markdown",
        "metadata": {},
        "source": ["## 2.0 Load M01 Survivor Model\n",
                   "\n",
                   "**Goal:** Load the trained M01 model and verify it was trained on survivors.\n",
                   "\n",
                   "**Expected:** Model trained on ~7,352 survivors (50.9% of total trades)"]
    },
    {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": [
            "# Load M01 model\n",
            "if d2_features is not None:\n",
            "    print(\"Loading M01 Survivor Model...\")\n",
            "    \n",
            "    # Find model file\n",
            "    m01_model_path = Path('../models/model_m01.json')\n",
            "    m01_config_path = Path('../models/model_m01_config.json')\n",
            "    \n",
            "    if m01_model_path.exists():\n",
            "        # Load XGBoost model\n",
            "        m01_model = xgb.XGBRegressor()\n",
            "        m01_model.load_model(m01_model_path)\n",
            "        print(f\"\\u2705 Loaded M01 model from {m01_model_path}\")\n",
            "        \n",
            "        # Load config if exists\n",
            "        if m01_config_path.exists():\n",
            "            with open(m01_config_path, 'r') as f:\n",
            "                m01_config = json.load(f)\n",
            "            print(f\"\\n\\ud83d\\udcca Model Configuration:\")\n",
            "            print(f\"   Horizon: {m01_config.get('horizon_days', 'N/A')}d\")\n",
            "            print(f\"   Survivor model: {m01_config.get('survivor_model', False)}\")\n",
            "            print(f\"   Training samples: {m01_config.get('n_train_samples', 'N/A'):,}\")\n",
            "            print(f\"   Features: {m01_config.get('n_features', len(M01_FEATURES))}\")\n",
            "            print(f\"   Mean R\\u00b2: {m01_config.get('mean_r2', 'N/A'):.3f}\")\n",
            "        \n",
            "        # Prepare data for prediction\n",
            "        print(f\"\\nPreparing feature matrix...\")\n",
            "        X_m01 = d2_features[M01_FEATURES].copy()\n",
            "        print(f\"   Features: {len(M01_FEATURES)}\")\n",
            "        print(f\"   Samples: {len(X_m01):,}\")\n",
            "        print(f\"\\n\\u2705 M01 model ready for predictions\")\n",
            "    else:\n",
            "        print(f\"\\u26a0\\ufe0f  M01 model not found at {m01_model_path}\")\n",
            "        print(f\"   Run: python model_trainer.py --steps d2train --survivor-model\")\n",
            "        m01_model = None\n",
            "else:\n",
            "    print(\"\\u26a0\\ufe0f  D2 Features not loaded\")\n",
            "    m01_model = None"
        ]
    },

    # Cell 2.1: Feature Separation Analysis (KS Test)
    {
        "cell_type": "markdown",
        "metadata": {},
        "source": ["## 2.1 Feature Separation Power (KS Test)\n",
                   "\n",
                   "**Goal:** Validate that M01 features discriminate between top/bottom return quartiles.\n",
                   "\n",
                   "**Method:** Kolmogorov-Smirnov test comparing Q1 (losers) vs Q4 (winners) distributions.\n",
                   "\n",
                   "**Industry Standard:** KS statistic > 0.2 indicates good discrimination power."]
    },
    {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": [
            "# Analyze feature separation using KS test\n",
            "if d2_features is not None and 'analysis_df' in locals():\n",
            "    print(\"Running Feature Separation Analysis (KS Test)...\")\n",
            "    \n",
            "    # Merge d2_features with survivor analysis\n",
            "    if 'trade_id' not in d2_features.columns:\n",
            "        d2_features['trade_id'] = d2_features.index + 1\n",
            "    \n",
            "    # Merge with analysis_df to get y_max_survivor\n",
            "    df_merged = d2_features.merge(\n",
            "        analysis_df[['trade_id', 'y_max_survivor', 'is_survivor']], \n",
            "        on='trade_id', how='left'\n",
            "    )\n",
            "    \n",
            "    # Run KS test on survivors only\n",
            "    survivors_df = df_merged[df_merged['is_survivor'] == True].copy()\n",
            "    \n",
            "    separation_df = eda_utils.analyze_feature_separation(\n",
            "        survivors_df, \n",
            "        M01_FEATURES, \n",
            "        target='y_max_survivor'\n",
            "    )\n",
            "    \n",
            "    print(f\"\\n\\ud83d\\udcca Feature Separation Analysis (Survivors Only, n={len(survivors_df):,}):\")\n",
            "    print(f\"\\nTop 10 Features by KS Statistic:\")\n",
            "    display(separation_df.head(10))\n",
            "    \n",
            "    print(f\"\\nFeatures with KS > 0.2 (strong discrimination): {(separation_df['KS_statistic'] > 0.2).sum()}\")\n",
            "    print(f\"Features with KS > 0.1 (moderate discrimination): {(separation_df['KS_statistic'] > 0.1).sum()}\")\n",
            "    \n",
            "else:\n",
            "    print(\"\\u26a0\\ufe0f  Run Section 1.4 first to calculate survivor analysis\")"
        ]
    },

    # Cell 2.2: Violin Plots - Top Features
    {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": [
            "# Visualization: Violin plots for top discriminative features\n",
            "if 'separation_df' in locals() and 'survivors_df' in locals():\n",
            "    # Create return quartiles for survivors\n",
            "    survivors_df['return_quartile'] = pd.qcut(\n",
            "        survivors_df['y_max_survivor'], \n",
            "        q=4, \n",
            "        labels=['Q1_Losers', 'Q2', 'Q3', 'Q4_Winners'],\n",
            "        duplicates='drop'\n",
            "    )\n",
            "    \n",
            "    # Plot top 6 features\n",
            "    top_features = separation_df.head(6)['feature'].tolist()\n",
            "    \n",
            "    fig, axes = plt.subplots(2, 3, figsize=(18, 10))\n",
            "    axes = axes.flatten()\n",
            "    \n",
            "    for idx, feature in enumerate(top_features):\n",
            "        ax = axes[idx]\n",
            "        \n",
            "        # Filter for Q1 and Q4 only\n",
            "        plot_data = survivors_df[survivors_df['return_quartile'].isin(['Q1_Losers', 'Q4_Winners'])]\n",
            "        \n",
            "        sns.violinplot(\n",
            "            data=plot_data, \n",
            "            x='return_quartile', \n",
            "            y=feature, \n",
            "            ax=ax,\n",
            "            palette={'Q1_Losers': 'red', 'Q4_Winners': 'green'}\n",
            "        )\n",
            "        \n",
            "        ks_stat = separation_df[separation_df['feature'] == feature]['KS_statistic'].iloc[0]\n",
            "        ax.set_title(f\"{feature}\\nKS = {ks_stat:.3f}\", fontsize=10)\n",
            "        ax.set_xlabel('')\n",
            "        ax.grid(True, alpha=0.3, axis='y')\n",
            "    \n",
            "    plt.tight_layout()\n",
            "    plt.savefig('../evaluation/section2_feature_separation.png', dpi=300, bbox_inches='tight')\n",
            "    plt.show()\n",
            "    \n",
            "    print(\"\\n\\u2705 Feature separation visualizations complete\")\n",
            "else:\n",
            "    print(\"\\u26a0\\ufe0f  Run previous cell first\")"
        ]
    },

    # Add more cells here for the rest of Section 2...
    # Due to space constraints, I'll create a placeholder for now
]

# Find the index of cell-17 (Section 2 header)
cell_17_idx = None
for idx, cell in enumerate(nb['cells']):
    if cell.get('id') == 'cell-17':
        cell_17_idx = idx
        break

if cell_17_idx is None:
    print("Error: Could not find cell-17 (Section 2 header)")
else:
    # Insert Section 2 cells after cell-17
    insert_idx = cell_17_idx + 1

    for cell_data in section2_cells:
        new_cell = {
            "cell_type": cell_data["cell_type"],
            "metadata": cell_data.get("metadata", {}),
            "source": cell_data["source"]
        }

        if cell_data["cell_type"] == "code":
            new_cell["execution_count"] = cell_data.get("execution_count")
            new_cell["outputs"] = cell_data.get("outputs", [])

        nb['cells'].insert(insert_idx, new_cell)
        insert_idx += 1

    # Save the modified notebook
    with open(notebook_path, 'w', encoding='utf-8') as f:
        json.dump(nb, f, indent=1, ensure_ascii=False)

    print(f"✅ Added {len(section2_cells)} cells to Section 2")
    print(f"   Notebook saved: {notebook_path}")
