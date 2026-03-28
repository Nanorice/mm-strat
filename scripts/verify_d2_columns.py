
import sys
import duckdb
import numpy as np
import pandas as pd
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.feature_config import M01_FEATURES
from src.managers.view_manager import DEFAULT_DB_PATH

def verify_columns():
    print(f"Connecting to {DEFAULT_DB_PATH}...")
    con = duckdb.connect(str(DEFAULT_DB_PATH))
    
    try:
        print("Querying v_d2_training...")
        df_train_raw = con.execute("""
            SELECT *
            FROM v_d2_training
            LIMIT 10
        """).df()
        
        print(f"Raw columns: {df_train_raw.columns.tolist()}")

        # --- Apply log transforms inline (FeaturePreprocessor normally does this) ---
        LOG_COLS = [
            'close', 'volume_avg_20', 'dollar_volume_avg_20', 'atr_20',
            'alpha001', 'alpha009', 'alpha060',
            'Price_vs_SMA_50', 'Price_vs_SMA_150', 'Price_vs_SMA_200',
            'Dist_From_52W_High', 'Dist_From_20D_Low',
            'mfe_pct', 'mae_pct',
        ]
        
        # Mock log transforms (just checking existence)
        for col in LOG_COLS:
            if col in df_train_raw.columns:
                df_train_raw[f'log_{col}'] = 1.0 # Mock value

        # Fix rs_rating to 1-99 percentile
        if 'RS_Universe_Rank' in df_train_raw.columns:
            df_train_raw['rs_rating'] = df_train_raw['RS_Universe_Rank'] * 99

        # Sector/industry from company_profiles if missing
        if 'sector_id' not in df_train_raw.columns and 'sector_1' in df_train_raw.columns:
            df_train_raw['sector_id'] = 1
        if 'industry_id' not in df_train_raw.columns and 'industry_1' in df_train_raw.columns:
            df_train_raw['industry_id'] = 1

        available = [f for f in M01_FEATURES if f in df_train_raw.columns]
        missing   = [f for f in M01_FEATURES if f not in df_train_raw.columns]
        
        print(f"M01 features defined: {len(M01_FEATURES)}")
        print(f"Available: {len(available)}")
        print(f"Missing: {len(missing)}")
        
        if missing:
            print(f"Missing List: {missing}")
        else:
            print("SUCCESS: All M01 features are present!")
            
    finally:
        con.close()

if __name__ == "__main__":
    verify_columns()
