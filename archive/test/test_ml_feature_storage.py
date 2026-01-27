"""
Tests for ML Feature Storage in Buy List Database

Test coverage:
- Feature storage and retrieval
- JSON serialization/deserialization
- None/null handling for non-ML scans
- Feature data types and conversions
"""

import pytest
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.database import DatabaseManager


def test_feature_storage_and_retrieval():
    """Test that ML features can be stored and retrieved correctly."""
    test_db = 'database/test_features.db'
    
    # Clean up
    if os.path.exists(test_db):
        os.remove(test_db)
    
    try:
        db = DatabaseManager(db_path=test_db)
        
        # Add entry with features
        test_features = {
            'RSI_14': 65.5,
            'RS': 0.85,
            'alpha001_rank': 42,
            'revenueGrowth_1y': 0.25,
            'VCP_Ratio': 1.15
        }
        
        db.add_to_buy_list(
            ticker='TSLA',
            signal_date='2025-12-01',
            signal_price=250.0,
            current_price=250.0,
            ml_features=test_features
        )
        
        # Retrieve and verify
        buy_list = db.get_buy_list()
        assert len(buy_list) == 1, 'Expected 1 entry in buy_list'
        
        stored_features = buy_list.iloc[0]['ml_features']
        
        assert isinstance(stored_features, dict), 'Features not parsed back to dict'
        assert stored_features['RSI_14'] ==65.5, 'Feature value mismatch'
        assert stored_features['alpha001_rank'] == 42, 'Rank feature missing'
        assert len(stored_features) == 5, 'Not all features stored'
        
        print("✓ Feature storage and retrieval test passed")
    finally:
        # Clean up
        if os.path.exists(test_db):
            os.remove(test_db)


def test_none_features_handling():
    """Test that None features are handled gracefully (non-ML scan)."""
    test_db = 'database/test_none_features.db'
    
    if os.path.exists(test_db):
        os.remove(test_db)
    
    try:
        db = DatabaseManager(db_path=test_db)
        
        # Add entry without features (non-ML scan)
        db.add_to_buy_list(
            ticker='AAPL',
            signal_date='2025-12-01',
            signal_price=150.0,
            current_price=150.0,
            ml_features=None
        )
        
        buy_list = db.get_buy_list()
        assert len(buy_list) == 1, 'Expected 1 entry'
        
        stored_features = buy_list.iloc[0]['ml_features']
        assert stored_features is None, f'Features should be None, got {type(stored_features)}'
        
        print("✓ None features handling test passed")
    finally:
        if os.path.exists(test_db):
            os.remove(test_db)


def test_empty_features_dict():
    """Test that empty features dict is handled correctly."""
    test_db = 'database/test_empty_features.db'
    
    if os.path.exists(test_db):
        os.remove(test_db)
    
    try:
        db = DatabaseManager(db_path=test_db)
        
        # Add entry with empty features dict
        db.add_to_buy_list(
            ticker='MSFT',
            signal_date='2025-12-01',
            signal_price=350.0,
            current_price=350.0,
            ml_features={}
        )
        
        buy_list = db.get_buy_list()
        stored_features = buy_list.iloc[0]['ml_features']
        # Empty dict may be stored as {} or None depending on JSON handling
        assert stored_features == {} or stored_features is None, f'Expected empty dict or None, got {type(stored_features)}: {stored_features}'
        
        print("✓ Empty features dict test passed")
    finally:
        if os.path.exists(test_db):
            os.remove(test_db)


def test_multiple_entries_with_different_features():
    """Test storing multiple entries with different feature sets."""
    test_db = 'database/test_multiple_features.db'
    
    if os.path.exists(test_db):
        os.remove(test_db)
    
    try:
        db = DatabaseManager(db_path=test_db)
        
        # Add entry 1 with many features
        features1 = {f'feature_{i}': float(i) for i in range(85)}
        db.add_to_buy_list(
            ticker='TICKER1',
            signal_date='2025-12-01',
            signal_price=100.0,
            current_price=100.0,
            ml_features=features1
        )
        
        # Add entry 2 with fewer features
        features2 = {f'feature_{i}': float(i * 2) for i in range(23)}
        db.add_to_buy_list(
            ticker='TICKER2',
            signal_date='2025-12-01',
            signal_price=200.0,
            current_price=200.0,
            ml_features=features2
        )
        
        # Add entry 3 with no features
        db.add_to_buy_list(
            ticker='TICKER3',
            signal_date='2025-12-01',
            signal_price=300.0,
            current_price=300.0,
            ml_features=None
        )
        
        buy_list = db.get_buy_list()
        assert len(buy_list) == 3, 'Expected 3 entries'
        
        # Verify each entry
        ticker1_features = buy_list[buy_list['ticker'] == 'TICKER1'].iloc[0]['ml_features']
        assert len(ticker1_features) == 85, 'TICKER1 should have 85 features'
        
        ticker2_features = buy_list[buy_list['ticker'] == 'TICKER2'].iloc[0]['ml_features']
        assert len(ticker2_features) == 23, 'TICKER2 should have 23 features'
        
        ticker3_features = buy_list[buy_list['ticker'] == 'TICKER3'].iloc[0]['ml_features']
        assert ticker3_features is None, 'TICKER3 should have None features'
        
        print("✓ Multiple entries with different features test passed")
    finally:
        if os.path.exists(test_db):
            os.remove(test_db)


def test_feature_value_types():
    """Test that various Python types are correctly stored and retrieved."""
    test_db = 'database/test_feature_types.db'
    
    if os.path.exists(test_db):
        os.remove(test_db)
    
    try:
        db = DatabaseManager(db_path=test_db)
        
        # Add entry with different value types
        test_features = {
            'int_value': 42,
            'float_value': 3.14159,
            'none_value': None,
            'string_value': 'test',  # Edge case: should work
            'zero_value': 0.0,
            'negative_value': -15.5
        }
        
        db.add_to_buy_list(
            ticker='TYPE_TEST',
            signal_date='2025-12-01',
            signal_price=100.0,
            current_price=100.0,
            ml_features=test_features
        )
        
        buy_list = db.get_buy_list()
        stored_features = buy_list.iloc[0]['ml_features']
        
        assert stored_features['int_value'] == 42
        assert abs(stored_features['float_value'] - 3.14159) < 0.0001
        assert stored_features['none_value'] is None
        assert stored_features['zero_value'] == 0.0
        assert stored_features['negative_value'] == -15.5
        
        print("✓ Feature value types test passed")
    finally:
        if os.path.exists(test_db):
            os.remove(test_db)


if __name__ == "__main__":
    print("Running ML Feature Storage Tests...\n")
    
    test_feature_storage_and_retrieval()
    test_none_features_handling()
    test_empty_features_dict()
    test_multiple_entries_with_different_features()
    test_feature_value_types()
    
    print("\n✅ All tests passed!")
