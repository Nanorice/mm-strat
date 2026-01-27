"""
Unit Tests for Fundamental Processor

Tests Phase 1: Fundamental preprocessing including:
- Date standardization
- YoY growth calculations
- Safety ratios
- Operating metrics
"""

import pandas as pd
import numpy as np
import pytest
from datetime import datetime, timedelta

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from src.fundamental_processor import FundamentalProcessor


class TestFundamentalProcessor:
    """Test suite for FundamentalProcessor class."""
    
    @pytest.fixture
    def processor(self):
        """Create a processor instance."""
        return FundamentalProcessor()
    
    @pytest.fixture
    def sample_fundamental_data(self):
        """Create sample fundamental data for testing."""
        # Simulate 5 quarters of data
        dates = pd.date_range('2023-03-31', periods=5, freq='Q')
        filing_dates = [d + timedelta(days=30) for d in dates]  # Filed 1 month after quarter end
        
        data = {
            'ticker': ['TEST'] * 5,
            'fiscal_date': dates,
            'filing_date': filing_dates,
            'fiscal_period': ['Q1', 'Q2', 'Q3', 'Q4', 'Q1'],
            'fiscal_year': [2023, 2023, 2023, 2023, 2024],
            'statement_type': ['income'] * 5,
            'revenue': [1000, 1100, 1200, 1300, 1200],  # Q1 2024 shows 20% YoY growth
            'netIncome': [100, 110, 120, 130, 120],
            'eps': [1.0, 1.1, 1.2, 1.3, 1.2],  # Q1 2024: 1.2 vs Q1 2023: 1.0 = 20%
            'grossProfit': [400, 440, 480, 520, 480],
            'operatingIncome': [200, 220, 240, 260, 240],
            'totalAssets': [5000, 5100, 5200, 5300, 5400],
            'totalEquity': [2000, 2100, 2200, 2300, 2400],
            'totalDebt': [1000, 1000, 1000, 1000, 1000],
            'currentAssets': [2000, 2100, 2200, 2300, 2400],
            'currentLiabilities': [1000, 1050, 1100, 1150, 1200],
            'inventory': [500, 525, 550, 575, 600]
        }
        
        return pd.DataFrame(data)
    
    def test_date_standardization(self, processor, sample_fundamental_data):
        """Test that filing_date is used as primary and data is sorted correctly."""
        df = sample_fundamental_data.copy()
        
        result = processor._standardize_dates(df, 'TEST')
        
        # Should have filing_date
        assert 'filing_date' in result.columns
        
        # Should be sorted by filing_date (newest first)
        assert result['filing_date'].is_monotonic_decreasing
        
        # Should have all rows
        assert len(result) == len(df)
    
    def test_yoy_growth_calculation(self, processor, sample_fundamental_data):
        """Test YoY growth calculation (compare to 4 quarters back)."""
        df = sample_fundamental_data.copy()
        df = df[df['statement_type'] == 'income'].copy()
        
        result = processor._calculate_growth_metrics(df)
        
        # Check that growth columns exist
        assert 'revenue_growth_yoy' in result.columns
        assert 'eps_growth_yoy' in result.columns
        
        # Q1 2024 (index 4 after sorting by fiscal_date ascending) should have YoY growth
        # Sort by fiscal_date for easier indexing
        result_sorted = result.sort_values('fiscal_date')
        
        # Q1 2024 revenue: 1200, Q1 2023 revenue: 1000
        # Expected growth: (1200 / 1000 - 1) * 100 = 20%
        q1_2024_growth = result_sorted.iloc[-1]['revenue_growth_yoy']
        
        # Allow small floating point error
        assert abs(q1_2024_growth - 20.0) < 0.1, f"Expected 20% growth, got {q1_2024_growth}%"
        
        # Q1 2024 EPS: 1.2, Q1 2023 EPS: 1.0
        # Expected growth: (1.2 / 1.0 - 1) * 100 = 20%
        q1_2024_eps_growth = result_sorted.iloc[-1]['eps_growth_yoy']
        assert abs(q1_2024_eps_growth - 20.0) < 0.1
    
    def test_safety_ratios(self, processor):
        """Test debt-to-equity, current ratio, quick ratio calculations."""
        data = {
            'totalDebt': [1000],
            'totalEquity': [2000],
            'currentAssets': [3000],
            'currentLiabilities': [1500],
            'inventory': [500]
        }
        df = pd.DataFrame(data)
        
        result = processor._calculate_safety_ratios(df)
        
        # Debt to Equity: 1000 / 2000 = 0.5
        assert abs(result['debt_to_equity'].iloc[0] - 0.5) < 0.001
        
        # Current Ratio: 3000 / 1500 = 2.0
        assert abs(result['current_ratio'].iloc[0] - 2.0) < 0.001
        
        # Quick Ratio: (3000 - 500) / 1500 = 1.667
        assert abs(result['quick_ratio'].iloc[0] - 1.667) < 0.01
    
    def test_operating_metrics(self, processor):
        """Test gross margin, operating margin, ROE, ROA calculations."""
        data = {
            'revenue': [1000],
            'grossProfit': [400],  # Gross margin: 40%
            'operatingIncome': [200],  # Operating margin: 20%
            'netIncome': [100],
            'totalEquity': [2000],  # ROE: 100/2000 = 5%
            'totalAssets': [5000]   # ROA: 100/5000 = 2%
        }
        df = pd.DataFrame(data)
        
        result = processor._calculate_operating_metrics(df)
        
        # Gross Margin: (400 / 1000) * 100 = 40%
        assert abs(result['gross_margin'].iloc[0] - 40.0) < 0.1
        
        # Operating Margin: (200 / 1000) * 100 = 20%
        assert abs(result['operating_margin'].iloc[0] - 20.0) < 0.1
        
        # ROE: (100 / 2000) * 100 = 5%
        assert abs(result['roe'].iloc[0] - 5.0) < 0.1
        
        # ROA: (100 / 5000) * 100 = 2%
        assert abs(result['roa'].iloc[0] - 2.0) < 0.1
    
    def test_division_by_zero_handling(self, processor):
        """Test that division by zero is handled gracefully."""
        data = {
            'totalDebt': [1000],
            'totalEquity': [0],  # Zero equity
            'currentAssets': [1000],
            'currentLiabilities': [0],  # Zero liabilities
            'revenue': [0],  # Zero revenue
            'grossProfit': [100]
        }
        df = pd.DataFrame(data)
        
        result = processor._calculate_safety_ratios(df)
        result = processor._calculate_operating_metrics(result)
        
        # Should have NaN where division by zero
        assert pd.isna(result['debt_to_equity'].iloc[0])
        assert pd.isna(result['current_ratio'].iloc[0])
        assert pd.isna(result['gross_margin'].iloc[0])
    
    def test_missing_columns_handling(self, processor):
        """Test processor handles missing columns gracefully."""
        # Minimal data with some columns missing
        data = {
            'ticker': ['TEST'],
            'fiscal_date': [pd.Timestamp('2023-03-31')],
            'filing_date': [pd.Timestamp('2023-04-30')],
            'fiscal_period': ['Q1'],
            'fiscal_year': [2023],
            'statement_type': ['income'],
            'revenue': [1000]
            # Missing most other columns
        }
        df = pd.DataFrame(data)
        
        # Should not crash
        result = processor.process_ticker_fundamentals('TEST', df)
        
        # Should have some columns filled with NaN
        assert 'debt_to_equity' in result.columns
        assert pd.isna(result['debt_to_equity'].iloc[0])


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
