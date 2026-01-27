"""Fix Section 2 issues in Comprehensive Model EDA notebook."""
import json
from pathlib import Path

def fix_section2_cells():
    """Fix variable names, update n_features display, and add validation notes."""

    nb_path = Path('notebooks/Comprehensive_Model_EDA.ipynb')

    with open(nb_path, 'r', encoding='utf-8') as f:
        nb = json.load(f)

    changes_made = []

    for i, cell in enumerate(nb['cells']):
        if cell['cell_type'] != 'code':
            continue

        source = ''.join(cell['source'])
        original_source = source

        # Fix 1: Fix n_features display to use len(m01_config['feature_columns'])
        if "print(f\"   Features: {m01_config.get('n_features', len(M01_FEATURES))}\")" in source:
            source = source.replace(
                "            print(f\"   Features: {m01_config.get('n_features', len(M01_FEATURES))}\")",
                "            print(f\"   Features: {len(m01_config.get('feature_columns', M01_FEATURES))}\")"
            )
            changes_made.append(f"Cell {i}: Fixed n_features display to use feature_columns")

        # Fix 2: Add warning note about training data in FOMO/Toxic analysis
        if "# FOMO/Toxic error analysis" in source and "survivors_df['error_type'] = 'Normal'" in source:
            # Add a note at the top
            source = source.replace(
                "# FOMO/Toxic error analysis\nif 'survivors_df' in locals() and 'm01_prediction' in survivors_df.columns:\n    print(\"Analyzing FOMO/Toxic errors...\")",
                "# FOMO/Toxic error analysis\nif 'survivors_df' in locals() and 'm01_prediction' in survivors_df.columns:\n    print(\"Analyzing FOMO/Toxic errors...\")\n    print(\"⚠️  NOTE: This includes training data - use for EDA only, not final validation\")"
            )
            changes_made.append(f"Cell {i}: Added training data warning to FOMO/Toxic analysis")

        # Update the cell if changes were made
        if source != original_source:
            cell['source'] = source.split('\n')
            # Preserve newlines except at the end
            cell['source'] = [line + '\n' if idx < len(cell['source']) - 1 else line
                             for idx, line in enumerate(cell['source'])]

    # Save the updated notebook
    with open(nb_path, 'w', encoding='utf-8') as f:
        json.dump(nb, f, indent=1, ensure_ascii=False)

    print("Section 2 fixes applied:")
    for change in changes_made:
        print(f"   {change}")

    print(f"\nSaved to: {nb_path}")

if __name__ == '__main__':
    fix_section2_cells()
