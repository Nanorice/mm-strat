# Temporary fix file - to be inserted into fundamental_processor.py
# Insert this BEFORE line 575 "# Add all new columns at once using concat"

        # MINERVINI QUALITY CHECK - Inventory vs Sales Spread
        # Inventory is in balance sheet, so we calculate it here on merged data
        # Positive value = Red flag (inventory growing faster than sales)
        # Negative value = Healthy (sales outpacing inventory growth)
        if 'inventory' in df.columns and 'revenue_growth_yoy' in df.columns:
            # Sort by filing_date for time-series calculation
            df_sorted = df.sort_values('filing_date', ascending=True)
            
            # Calculate inventory YoY growth (compare to 4 quarters ago)
            inventory_growth = df_sorted['inventory'].pct_change(periods=4, fill_method=None) * 100
            
            # Calculate spread (inventory growth - revenue growth)
            inventory_spread = inventory_growth - df_sorted['revenue_growth_yoy']
            
            # Add back to new_columns (maintain original df index order)
            new_columns['inventory_growth_yoy'] = inventory_growth.reindex(df.index)
            new_columns['inventory_vs_sales_spread'] = inventory_spread.reindex(df.index)
        else:
            new_columns['inventory_growth_yoy'] = np.nan
            new_columns['inventory_vs_sales_spread'] = np.nan
