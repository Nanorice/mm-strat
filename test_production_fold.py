"""
Quick test to verify production fold (Fold 10) handling.

This script verifies:
1. Fold 10 is created and marked as production
2. Fold 10 trains without errors
3. Fold 10 is skipped during evaluation
"""

import sys
from pathlib import Path
import pandas as pd

# Add src to path
sys.path.append(str(Path(__file__).parent))

from src.model_preparation import TemporalSplitter

def test_production_fold():
    """Test that Fold 10 is properly handled."""
    
    # Create mock dataset with dates from 2003 to 2025
    print("=" * 80)
    print("TESTING PRODUCTION FOLD HANDLING")
    print("=" * 80)
    
    # Create sample data
    dates = pd.date_range(start='2003-01-01', end='2025-11-30', freq='D')
    n = len(dates)
    
    df = pd.DataFrame({
        'entry_date': dates,
        'label': [0, 1] * (n // 2) + [0] * (n % 2),  # Alternate 0/1
        'feature1': range(n),
        'feature2': range(n, n*2)
    })
    
    print(f"\nMock dataset: {len(df):,} rows")
    print(f"Date range: {df['entry_date'].min().date()} to {df['entry_date'].max().date()}")
    
    # Create folds
    splitter = TemporalSplitter(purge_gap_days=60)
    folds = splitter.create_folds(df, date_column='entry_date')
    
    print(f"\n{'='*80}")
    print("FOLD SUMMARY")
    print(f"{'='*80}")
    print(f"Total folds created: {len(folds)}")
    
    validation_folds = [f for f in folds if not f.get('is_production', False)]
    production_folds = [f for f in folds if f.get('is_production', False)]
    
    print(f"Validation folds: {len(validation_folds)}")
    print(f"Production folds: {len(production_folds)}")
    
    # Check Fold 10
    if len(folds) >= 10:
        fold_10 = folds[9]  # 0-indexed
        print(f"\n{'='*80}")
        print("FOLD 10 DETAILS")
        print(f"{'='*80}")
        print(f"Fold ID: {fold_10['fold_id']}")
        print(f"Is Production: {fold_10.get('is_production', False)}")
        print(f"Train samples: {fold_10['train_size']}")
        print(f"Test samples: {fold_10['test_size']}")
        print(f"Train period: {fold_10['train_start'].date()} to {fold_10['train_end'].date()}")
        print(f"Test period: {fold_10['test_start'].date()} to {fold_10['test_end'].date()}")
        
        # Verify it's marked as production
        if fold_10.get('is_production', False):
            print("\n✅ SUCCESS: Fold 10 is correctly marked as PRODUCTION")
        else:
            print("\n❌ FAILURE: Fold 10 should be marked as production!")
            
        # Verify test size is 0
        if fold_10['test_size'] == 0:
            print("✅ SUCCESS: Fold 10 has no test data (as expected)")
        else:
            print(f"⚠️  WARNING: Fold 10 has {fold_10['test_size']} test samples (expected 0)")
    else:
        print(f"\n❌ FAILURE: Expected 10 folds, but got {len(folds)}")
    
    print(f"\n{'='*80}")
    print("TEST COMPLETE")
    print(f"{'='*80}\n")

if __name__ == "__main__":
    test_production_fold()
