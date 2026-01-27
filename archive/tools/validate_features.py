"""
Quick validation script to check alpha factor variance and raw Volume issues.
Run this to validate the commentary review findings.
"""

import pandas as pd
import numpy as np
from pathlib import Path

def main():
    print("=" * 80)
    print(" FEATURE VALIDATION - Alpha Factors & Volume Analysis")
    print("=" * 80)
    
    # Load Dataset B
    dataset_path = Path('data/ml/dataset_b.parquet')
    
    if not dataset_path.exists():
        print(f"\n❌ ERROR: Dataset not found at {dataset_path}")
        print("   Run: python build_dataset_b.py --start 2015-01-01 --end 2024-01-01")
        return
    
    print(f"\n📂 Loading dataset from: {dataset_path}")
    df = pd.read_parquet(dataset_path)
    
    print(f"   ✅ Loaded {len(df)} rows, {len(df.columns)} columns")
    print(f"   📅 Date range: {df['entry_date'].min()} to {df['entry_date'].max()}")
    
    # =========================================================================
    # 1. Alpha Factor Analysis
    # =========================================================================
    print("\n" + "=" * 80)
    print(" ALPHA FACTOR ANALYSIS")
    print("=" * 80)
    
    alpha_cols = [c for c in df.columns if c.startswith('alpha')]
    
    if not alpha_cols:
        print("⚠️  No alpha columns found in dataset!")
    else:
        print(f"\n📊 Found {len(alpha_cols)} alpha factors: {alpha_cols}")
        
        # Statistical summary
        print("\n" + "-" * 80)
        print("Statistical Summary:")
        print("-" * 80)
        print(df[alpha_cols].describe())
        
        # Check for zero variance
        print("\n" + "-" * 80)
        print("Variance Analysis:")
        print("-" * 80)
        
        zero_variance_alphas = []
        low_variance_alphas = []
        
        for col in alpha_cols:
            std = df[col].std()
            mean = df[col].mean()
            unique_vals = df[col].nunique()
            pct_zero = (df[col] == 0).sum() / len(df) * 100
            
            print(f"\n{col}:")
            print(f"  Mean: {mean:.6f}, Std: {std:.6f}")
            print(f"  Unique values: {unique_vals}")
            print(f"  % zeros: {pct_zero:.2f}%")
            
            if std == 0:
                print(f"  ⚠️  ZERO VARIANCE - column is constant!")
                zero_variance_alphas.append(col)
            elif std < 0.001:
                print(f"  ⚠️  Very low variance - may not be predictive")
                low_variance_alphas.append(col)
            elif pct_zero > 95:
                print(f"  ⚠️  95%+ zeros - likely calculation error")
        
        # Summary
        print("\n" + "=" * 80)
        print(" ALPHA SUMMARY")
        print("=" * 80)
        
        if zero_variance_alphas:
            print(f"\n❌ {len(zero_variance_alphas)} alphas with ZERO variance:")
            for alpha in zero_variance_alphas:
                print(f"   - {alpha}")
            print("\n   Root cause: Alpha calculation returns all NaN → filled with 0")
            print("   Action: Check WorldQuant_101 implementation or input data quality")
        else:
            print("\n✅ All alphas have non-zero variance")
        
        if low_variance_alphas:
            print(f"\n⚠️  {len(low_variance_alphas)} alphas with low variance (<0.001):")
            for alpha in low_variance_alphas:
                print(f"   - {alpha}")
    
    # =========================================================================
    # 2. Volume Analysis
    # =========================================================================
    print("\n" + "=" * 80)
    print(" VOLUME FEATURE ANALYSIS")
    print("=" * 80)
    
    volume_features = ['Volume', 'Vol_Ratio', 'Vol_MA', 'Dry_Up_Volume']
    available_vol_features = [f for f in volume_features if f in df.columns]
    
    if not available_vol_features:
        print("⚠️  No volume features found in dataset!")
    else:
        print(f"\n📊 Found {len(available_vol_features)} volume features: {available_vol_features}")
        
        print("\n" + "-" * 80)
        print("Volume Feature Statistics:")
        print("-" * 80)
        print(df[available_vol_features].describe())
        
        # Check correlation
        if len(available_vol_features) > 1:
            print("\n" + "-" * 80)
            print("Volume Feature Correlation Matrix:")
            print("-" * 80)
            corr_matrix = df[available_vol_features].corr()
            print(corr_matrix)
            
            # Check for redundancy
            print("\n" + "-" * 80)
            print("Redundancy Analysis:")
            print("-" * 80)
            
            if 'Volume' in available_vol_features and 'Vol_Ratio' in available_vol_features:
                corr = df['Volume'].corr(df['Vol_Ratio'])
                print(f"\nVolume vs Vol_Ratio correlation: {corr:.4f}")
                
                if abs(corr) > 0.5:
                    print("⚠️  High correlation - Volume is redundant with Vol_Ratio")
                    print("   This explains why Volume importance = 0.0")
                else:
                    print("✅ Low correlation - both features provide unique information")
    
    # =========================================================================
    # 3. Feature Importance Simulation
    # =========================================================================
    print("\n" + "=" * 80)
    print(" QUICK FEATURE IMPORTANCE CHECK")
    print("=" * 80)
    
    # Get all numeric features
    numeric_features = df.select_dtypes(include=[np.number]).columns.tolist()
    
    # Remove target and metadata
    feature_cols = [c for c in numeric_features 
                    if c not in ['label', 'return_pct', 'days_held', 'max_drawdown_pct', 
                                'exit_price', 'entry_price']]
    
    print(f"\n📊 Dataset has {len(feature_cols)} numeric features")
    
    # Check for features with zero variance (will be ignored by XGB)
    zero_var_features = []
    for col in feature_cols:
        if df[col].std() == 0:
            zero_var_features.append(col)
    
    if zero_var_features:
        print(f"\n⚠️  {len(zero_var_features)} features with zero variance (XGBoost will ignore):")
        for feat in zero_var_features[:10]:  # Show first 10
            print(f"   - {feat}")
        if len(zero_var_features) > 10:
            print(f"   ... and {len(zero_var_features) - 10} more")
    else:
        print("\n✅ All features have non-zero variance")
    
    # =========================================================================
    # 4. Export sample for manual inspection
    # =========================================================================
    print("\n" + "=" * 80)
    print(" EXPORTING SAMPLE DATA")
    print("=" * 80)
    
    sample_cols = alpha_cols + available_vol_features + ['label', 'ticker', 'entry_date']
    sample_cols = [c for c in sample_cols if c in df.columns]
    
    sample_path = Path('data/ml/feature_validation_sample.csv')
    df[sample_cols].head(100).to_csv(sample_path, index=False)
    print(f"\n✅ Exported 100-row sample to: {sample_path}")
    print(f"   Columns: {', '.join(sample_cols)}")
    
    print("\n" + "=" * 80)
    print(" VALIDATION COMPLETE")
    print("=" * 80)
    print("\nNext steps:")
    print("1. Review the variance analysis above")
    print("2. If alphas have zero variance, check WorldQuant_101 implementation")
    print("3. If Volume has zero importance, check correlation with Vol_Ratio")
    print(f"4. Inspect sample data: {sample_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
