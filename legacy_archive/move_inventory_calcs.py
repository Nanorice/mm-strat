"""Move inventory calculations from _calculate_growth_metrics to _calculate_advanced_metrics"""

with open('src/fundamental_processor.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find and mark the inventory code in _calculate_growth_metrics for removal
in_calc_growth = False
in_inventory_block = False
new_lines = []

for i, line in enumerate(lines):
    # Check if we're in _calculate_growth_metrics
    if 'def _calculate_growth_metrics' in line:
        in_calc_growth = True
    elif in_calc_growth and line.strip().startswith('def '):
        in_calc_growth = False
    
    # Skip inventory calculations in _calculate_growth_metrics
    if in_calc_growth and 'MINERVINI QUALITY CHECK - Inventory' in line:
        in_inventory_block = True
        new_lines.append("        # NOTE: Inventory calculations moved to _calculate_advanced_metrics()\n")
        new_lines.append("        # because inventory is in balance sheet, not income statement\n")
        new_lines.append("        \n")
        continue
    elif in_inventory_block:
        # Skip until we hit the sort or return
        if 'Sort back to original order' in line or 'return df' in line:
            in_inventory_block = False
       else:
            continue
    
    new_lines.append(line)

# Now add inventory calculations to _calculate_advanced_metrics
# Find the line with "# Add all new columns"
for i, line in enumerate(new_lines):
    if i > 0 and "'efficient_growth' = np.nan" in new_lines[i-1] and "# Add all new columns" in line:
        # Insert inventory calculation before this line
        indent = "        "
        insert_lines = [
            f"\n",
            f"{indent}# MINERVINI QUALITY CHECK - Inventory vs Sales Spread\n",
            f"{indent}# Inventory is in balance sheet, so we calculate it here on merged data\n",
            f"{indent}# Positive value = Red flag (inventory growing faster than sales)\n",
            f"{indent}# Negative value = Healthy (sales outpacing inventory growth)\n",
            f"{indent}if 'inventory' in df.columns and 'revenue_growth_yoy' in df.columns:\n",
            f"{indent}    # Sort by filing_date for time-series calculation\n",
            f"{indent}    df_sorted = df.sort_values('filing_date', ascending=True)\n",
            f"{indent}    \n",
            f"{indent}    # Calculate inventory YoY growth (compare to 4 quarters ago)\n",
            f"{indent}    inventory_growth = df_sorted['inventory'].pct_change(periods=4, fill_method=None) * 100\n",
            f"{indent}    \n",
            f"{indent}    # Calculate spread (inventory growth - revenue growth)\n",
            f"{indent}    inventory_spread = inventory_growth - df_sorted['revenue_growth_yoy']\n",
            f"{indent}    \n",
            f"{indent}    # Add back to new_columns (maintain original df index order)\n",
            f"{indent}    new_columns['inventory_growth_yoy'] = inventory_growth.reindex(df.index)\n",
            f"{indent}    new_columns['inventory_vs_sales_spread'] = inventory_spread.reindex(df.index)\n",
            f"{indent}else:\n",
            f"{indent}    new_columns['inventory_growth_yoy'] = np.nan\n",
            f"{indent}    new_columns['inventory_vs_sales_spread'] = np.nan\n",
            f"{indent}\n",
        ]
        new_lines = new_lines[:i] + insert_lines + new_lines[i:]
        break

with open('src/fundamental_processor.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("✅ Moved inventory calculations to _calculate_advanced_metrics()")
