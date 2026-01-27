"""
Data Health Analyzer - Comprehensive Data Coverage and Quality Check

This script analyzes data health across three key dimensions:
1. Price Data Coverage: Checks the 200-bar filtering criterion
2. Fundamental Data Coverage: Analyzes financial metrics completeness
3. Company Profile Coverage: Verifies company information availability

Helps understand why Dataset B filters certain tickers from the universe.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import json
from collections import defaultdict, Counter
import sys

# Add src to path
sys.path.append(str(Path(__file__).parent))

import config
from src.earnings_engine import EarningsEngine


class DataHealthAnalyzer:
    """Analyzes data health across price, fundamental, and profile dimensions."""
    
    def __init__(self):
        self.price_dir = Path(config.PRICE_DATA_DIR)
        self.fundamentals_dir = Path(config.FUNDAMENTALS_DIR)
        self.company_info_dir = Path(config.COMPANY_INFO_DIR)
        self.earnings_dir = Path(config.EARNINGS_DIR)

        # Initialize earnings engine
        try:
            self.earnings_engine = EarningsEngine()
        except ValueError:
            # API key not available, earnings analysis will be skipped
            self.earnings_engine = None

        # Results storage
        self.price_results = {}
        self.fundamental_results = {}
        self.profile_results = {}
        self.earnings_results = {}
        
    def analyze_price_data(self) -> Dict:
        """Analyze price data coverage and the 200-bar filter."""
        print("=" * 80)
        print(" PRICE DATA ANALYSIS")
        print("=" * 80)
        
        # Get all price files
        price_files = list(self.price_dir.glob('*.parquet'))
        total_tickers = len(price_files)
        
        print(f"\n📁 Total tickers in universe: {total_tickers}")
        print(f"📂 Price data directory: {self.price_dir}\n")
        
        # Analyze each ticker
        passed_200_bar = []
        failed_200_bar = []
        failed_to_load = []
        bar_counts = []
        date_ranges = []
        
        print("Analyzing price data for all tickers...")
        for price_file in price_files:
            ticker = price_file.stem
            
            try:
                # Load price data
                df = pd.read_parquet(price_file)
                
                if df is None or df.empty:
                    failed_to_load.append(ticker)
                    self.price_results[ticker] = {
                        'status': 'failed_to_load',
                        'bar_count': 0,
                        'date_range': None
                    }
                    continue
                
                bar_count = len(df)
                bar_counts.append(bar_count)
                
                # Get date range
                df.index = pd.to_datetime(df.index)
                start_date = df.index.min()
                end_date = df.index.max()
                date_ranges.append((start_date, end_date))
                
                # Check 200-bar filter
                if bar_count >= 200:
                    passed_200_bar.append(ticker)
                    status = 'passed'
                else:
                    failed_200_bar.append((ticker, bar_count))
                    status = 'failed_200_bar'
                
                self.price_results[ticker] = {
                    'status': status,
                    'bar_count': bar_count,
                    'start_date': start_date,
                    'end_date': end_date,
                    'days_span': (end_date - start_date).days
                }
                
            except Exception as e:
                failed_to_load.append(ticker)
                self.price_results[ticker] = {
                    'status': 'error',
                    'bar_count': 0,
                    'error': str(e)
                }
        
        # Calculate statistics
        total_passed = len(passed_200_bar)
        total_failed = len(failed_200_bar)
        total_errors = len(failed_to_load)
        
        print(f"\n✅ PASSED 200-bar filter: {total_passed} tickers ({total_passed/total_tickers*100:.1f}%)")
        print(f"❌ FAILED 200-bar filter: {total_failed} tickers ({total_failed/total_tickers*100:.1f}%)")
        print(f"⚠️  Failed to load: {total_errors} tickers ({total_errors/total_tickers*100:.1f}%)")
        
        # Bar count distribution
        if bar_counts:
            print(f"\n📊 Bar Count Statistics:")
            print(f"   Mean: {np.mean(bar_counts):.0f} bars")
            print(f"   Median: {np.median(bar_counts):.0f} bars")
            print(f"   Min: {np.min(bar_counts):.0f} bars")
            print(f"   Max: {np.max(bar_counts):.0f} bars")
            print(f"   25th percentile: {np.percentile(bar_counts, 25):.0f} bars")
            print(f"   75th percentile: {np.percentile(bar_counts, 75):.0f} bars")
        
        # Show failed tickers with bar counts
        if failed_200_bar and len(failed_200_bar) <= 50:
            print(f"\n📋 Tickers that FAILED 200-bar filter:")
            failed_sorted = sorted(failed_200_bar, key=lambda x: x[1])
            for ticker, count in failed_sorted[:20]:  # Show first 20
                print(f"   {ticker}: {count} bars")
            if len(failed_sorted) > 20:
                print(f"   ... and {len(failed_sorted) - 20} more")
        
        return {
            'total_tickers': total_tickers,
            'passed': total_passed,
            'failed': total_failed,
            'errors': total_errors,
            'passed_tickers': passed_200_bar,
            'failed_tickers': [t for t, _ in failed_200_bar],
            'bar_count_stats': {
                'mean': float(np.mean(bar_counts)) if bar_counts else 0,
                'median': float(np.median(bar_counts)) if bar_counts else 0,
                'min': int(np.min(bar_counts)) if bar_counts else 0,
                'max': int(np.max(bar_counts)) if bar_counts else 0,
            }
        }
    
    def analyze_fundamental_data_quality(self, price_universe: List[str]) -> Dict:
        """
        Analyze fundamental data quality with focus on key screening columns.

        Key columns for Minervini/Growth screening:
        - Growth: revenue, eps, netIncome, revenue_growth_yoy, eps_growth_yoy
        - Acceleration: eps_accel, revenue_accel
        - Profitability: roe, roa, gross_margin, operating_margin
        - Safety: debt_to_equity, current_ratio, cash
        - Meta: filing_date, fiscal_date
        """
        print("\n" + "=" * 80)
        print(" FUNDAMENTAL DATA QUALITY ANALYSIS (DETAILED)")
        print("=" * 80)

        # Define critical columns for screening (RAW API columns only, not derived)
        # These are the actual columns from FMP API stored in parquet files
        critical_columns = {
            'Income Statement': ['revenue', 'eps', 'epsDiluted', 'netIncome', 'grossProfit',
                                'operatingIncome', 'ebitda', 'costOfRevenue'],
            'Balance Sheet': ['totalAssets', 'totalLiabilities', 'totalEquity', 'totalDebt',
                             'cashAndCashEquivalents', 'totalCurrentAssets', 'totalCurrentLiabilities',
                             'inventory', 'netReceivables'],
            'Cash Flow': ['operatingCashFlow', 'freeCashFlow', 'capitalExpenditure',
                         'netCashProvidedByOperatingActivities'],
            'Date Fields': ['date', 'filingDate', 'acceptedDate', 'fiscalYear', 'period'],
            'Meta Fields': ['symbol', 'reportedCurrency']
        }

        print(f"\n📋 Critical Columns for Screening:")
        for category, cols in critical_columns.items():
            print(f"   {category}: {', '.join(cols)}")

        print(f"\n📁 Analyzing {len(price_universe)} tickers from price universe")
        print(f"📂 Fundamentals directory: {self.fundamentals_dir}\n")

        # Results tracking
        quality_scores = {}
        column_availability = {col: 0 for category in critical_columns.values() for col in category}
        column_completeness = {col: [] for category in critical_columns.values() for col in category}
        filing_date_issues = []
        data_freshness = []
        quarterly_coverage = []

        # Process each ticker
        processed_count = 0
        for ticker in price_universe:
            # Check if fundamental file exists
            fund_file = self.fundamentals_dir / f"{ticker}.parquet"

            if not fund_file.exists():
                quality_scores[ticker] = {
                    'overall_score': 0,
                    'status': 'no_file',
                    'issues': ['Fundamental file does not exist']
                }
                continue

            try:
                df = pd.read_parquet(fund_file)

                if df is None or df.empty:
                    quality_scores[ticker] = {
                        'overall_score': 0,
                        'status': 'empty',
                        'issues': ['Fundamental data is empty']
                    }
                    continue

                processed_count += 1
                issues = []
                category_scores = {}

                # Check each category
                for category, cols in critical_columns.items():
                    available = [col for col in cols if col in df.columns]
                    category_score = len(available) / len(cols) if cols else 0
                    category_scores[category] = category_score

                    # Track column availability
                    for col in available:
                        column_availability[col] += 1
                        # Calculate completeness (% non-null)
                        completeness = (df[col].notna().sum() / len(df)) * 100
                        column_completeness[col].append(completeness)

                    # Track missing critical columns
                    missing = [col for col in cols if col not in df.columns]
                    if missing:
                        issues.append(f"Missing {category}: {', '.join(missing)}")

                # Check filing_date quality
                if 'filing_date' in df.columns:
                    df['filing_date'] = pd.to_datetime(df['filing_date'], errors='coerce')
                    null_count = df['filing_date'].isna().sum()
                    if null_count > 0:
                        filing_date_issues.append((ticker, null_count, len(df)))
                        issues.append(f"filing_date: {null_count}/{len(df)} null values")

                    # Check data freshness
                    if df['filing_date'].notna().any():
                        most_recent = df['filing_date'].max()
                        age_days = (datetime.now() - most_recent).days if pd.notna(most_recent) else None
                        if age_days:
                            data_freshness.append((ticker, age_days, most_recent))
                            if age_days > 180:  # 6 months
                                issues.append(f"Stale data: {age_days} days old")
                else:
                    issues.append("No filing_date column")

                # Check quarterly coverage (should have at least 8 quarters for YoY)
                num_quarters = len(df)
                quarterly_coverage.append((ticker, num_quarters))
                if num_quarters < 8:
                    issues.append(f"Insufficient history: only {num_quarters} quarters")

                # Calculate overall quality score
                overall_score = np.mean(list(category_scores.values())) * 100

                quality_scores[ticker] = {
                    'overall_score': overall_score,
                    'category_scores': category_scores,
                    'num_quarters': num_quarters,
                    'issues': issues,
                    'status': 'excellent' if overall_score >= 90 else 'good' if overall_score >= 70 else 'fair' if overall_score >= 50 else 'poor'
                }

            except Exception as e:
                quality_scores[ticker] = {
                    'overall_score': 0,
                    'status': 'error',
                    'issues': [f"Error loading: {str(e)}"]
                }

        # Print results
        print(f"\n✅ Successfully analyzed: {processed_count} tickers\n")

        # Quality distribution
        excellent = sum(1 for s in quality_scores.values() if s['status'] == 'excellent')
        good = sum(1 for s in quality_scores.values() if s['status'] == 'good')
        fair = sum(1 for s in quality_scores.values() if s['status'] == 'fair')
        poor = sum(1 for s in quality_scores.values() if s['status'] == 'poor')
        no_data = sum(1 for s in quality_scores.values() if s['status'] in ['no_file', 'empty', 'error'])

        total = len(price_universe)
        print(f"📊 Quality Distribution:")
        print(f"   🌟 Excellent (90%+): {excellent} tickers ({excellent/total*100:.1f}%)")
        print(f"   ✅ Good (70-90%):   {good} tickers ({good/total*100:.1f}%)")
        print(f"   ⚠️  Fair (50-70%):   {fair} tickers ({fair/total*100:.1f}%)")
        print(f"   ❌ Poor (<50%):      {poor} tickers ({poor/total*100:.1f}%)")
        print(f"   💀 No Data:          {no_data} tickers ({no_data/total*100:.1f}%)")

        # Column availability analysis
        print(f"\n📋 Critical Column Availability (out of {processed_count} tickers):")
        for category, cols in critical_columns.items():
            print(f"\n   {category}:")
            for col in cols:
                count = column_availability[col]
                pct = (count / processed_count * 100) if processed_count > 0 else 0
                avg_completeness = np.mean(column_completeness[col]) if column_completeness[col] else 0

                status = "✅" if pct >= 80 else "⚠️" if pct >= 50 else "❌"
                print(f"      {status} {col:30s}: {count:4d} ({pct:5.1f}%) | Avg {avg_completeness:5.1f}% complete")

        # filing_date issues
        if filing_date_issues:
            print(f"\n⚠️  filing_date Issues ({len(filing_date_issues)} tickers):")
            for ticker, null_count, total_rows in sorted(filing_date_issues, key=lambda x: x[1], reverse=True)[:10]:
                pct = (null_count / total_rows * 100)
                print(f"      {ticker}: {null_count}/{total_rows} null ({pct:.1f}%)")
            if len(filing_date_issues) > 10:
                print(f"      ... and {len(filing_date_issues) - 10} more")

        # Data freshness
        if data_freshness:
            print(f"\n🕒 Data Freshness:")
            avg_age = np.mean([age for _, age, _ in data_freshness])
            print(f"      Average age: {avg_age:.0f} days")

            stale = [(t, a, d) for t, a, d in data_freshness if a > 180]
            if stale:
                print(f"      ⚠️  Stale data (>180 days): {len(stale)} tickers")
                for ticker, age, date in sorted(stale, key=lambda x: x[1], reverse=True)[:5]:
                    print(f"         {ticker}: {age} days old (last: {date.date()})")

        # Quarterly coverage
        if quarterly_coverage:
            quarters = [q for _, q in quarterly_coverage]
            print(f"\n📅 Quarterly Coverage:")
            print(f"      Average: {np.mean(quarters):.1f} quarters")
            print(f"      Median:  {np.median(quarters):.0f} quarters")
            print(f"      Min:     {np.min(quarters):.0f} quarters")
            print(f"      Max:     {np.max(quarters):.0f} quarters")

            insufficient = [(t, q) for t, q in quarterly_coverage if q < 8]
            if insufficient:
                print(f"      ⚠️  < 8 quarters: {len(insufficient)} tickers (can't calculate YoY)")

        # Show examples of excellent and poor quality
        print(f"\n🌟 Example EXCELLENT Tickers:")
        excellent_tickers = [(t, s) for t, s in quality_scores.items() if s['status'] == 'excellent']
        for ticker, score in sorted(excellent_tickers, key=lambda x: x[1]['overall_score'], reverse=True)[:5]:
            print(f"      {ticker}: {score['overall_score']:.1f}% | {score['num_quarters']} quarters")

        if poor > 0:
            print(f"\n❌ Example POOR Quality Tickers:")
            poor_tickers = [(t, s) for t, s in quality_scores.items() if s['status'] == 'poor']
            for ticker, score in sorted(poor_tickers, key=lambda x: x[1]['overall_score'])[:5]:
                print(f"      {ticker}: {score['overall_score']:.1f}% | Issues: {'; '.join(score['issues'][:2])}")

        return {
            'quality_scores': quality_scores,
            'column_availability': column_availability,
            'column_completeness': {k: np.mean(v) if v else 0 for k, v in column_completeness.items()},
            'filing_date_issues': filing_date_issues,
            'data_freshness': data_freshness,
            'quarterly_coverage': quarterly_coverage,
            'summary': {
                'excellent': excellent,
                'good': good,
                'fair': fair,
                'poor': poor,
                'no_data': no_data
            }
        }

    def analyze_fundamental_data(self, price_universe: List[str]) -> Dict:
        """Analyze fundamental data coverage for the price universe (legacy method)."""
        print("\n" + "=" * 80)
        print(" FUNDAMENTAL DATA COVERAGE (BASIC)")
        print("=" * 80)

        print(f"\n📁 Checking fundamentals for {len(price_universe)} tickers")
        print(f"📂 Fundamentals directory: {self.fundamentals_dir}\n")

        # Get all fundamental files
        fundamental_files = list(self.fundamentals_dir.glob('*.parquet'))
        fundamental_tickers = {f.stem for f in fundamental_files}

        print(f"Total fundamental files: {len(fundamental_files)}")
        
        # Categorize tickers
        with_fundamentals = []
        without_fundamentals = []
        partial_fundamentals = []
        
        # Track which metrics are available
        available_metrics = defaultdict(int)
        missing_metrics = Counter()
        
        for ticker in price_universe:
            if ticker in fundamental_tickers:
                # Check data quality
                fund_file = self.fundamentals_dir / f"{ticker}.parquet"
                try:
                    df = pd.read_parquet(fund_file)
                    
                    if df is None or df.empty:
                        without_fundamentals.append(ticker)
                        self.fundamental_results[ticker] = {
                            'status': 'empty',
                            'metrics': []
                        }
                        continue
                    
                    # Count available metrics (columns)
                    metrics = df.columns.tolist()
                    non_null_metrics = [col for col in metrics if df[col].notna().any()]
                    
                    for metric in non_null_metrics:
                        available_metrics[metric] += 1
                    
                    # Check completeness
                    completeness = len(non_null_metrics) / len(metrics) if metrics else 0
                    
                    # Get most recent data date from 'date' column if exists, otherwise use index
                    if 'date' in df.columns:
                        most_recent = pd.to_datetime(df['date']).max() if df['date'].notna().any() else None
                    else:
                        most_recent = df.index.max() if hasattr(df.index, 'max') else None
                    
                    if completeness > 0.8:  # 80% threshold
                        with_fundamentals.append(ticker)
                        status = 'complete'
                    elif completeness > 0:
                        partial_fundamentals.append(ticker)
                        status = 'partial'
                        # Track missing metrics
                        for metric in metrics:
                            if metric not in non_null_metrics:
                                missing_metrics[metric] += 1
                    else:
                        without_fundamentals.append(ticker)
                        status = 'empty'
                    
                    self.fundamental_results[ticker] = {
                        'status': status,
                        'metrics': non_null_metrics,
                        'completeness': completeness,
                        'most_recent': most_recent
                    }
                    
                except Exception as e:
                    without_fundamentals.append(ticker)
                    self.fundamental_results[ticker] = {
                        'status': 'error',
                        'error': str(e)
                    }
            else:
                without_fundamentals.append(ticker)
                self.fundamental_results[ticker] = {
                    'status': 'missing',
                    'metrics': []
                }
        
        # Print results
        total = len(price_universe)
        print(f"\n✅ Complete fundamentals: {len(with_fundamentals)} tickers ({len(with_fundamentals)/total*100:.1f}%)")
        print(f"⚠️  Partial fundamentals: {len(partial_fundamentals)} tickers ({len(partial_fundamentals)/total*100:.1f}%)")
        print(f"❌ No fundamentals: {len(without_fundamentals)} tickers ({len(without_fundamentals)/total*100:.1f}%)")
        
        # Show tickers without fundamentals
        if without_fundamentals and len(without_fundamentals) <= 50:
            print(f"\n📋 Tickers WITHOUT Fundamentals ({len(without_fundamentals)}):")
            for ticker in sorted(without_fundamentals)[:20]:
                print(f"   {ticker}")
            if len(without_fundamentals) > 20:
                print(f"   ... and {len(without_fundamentals) - 20} more")
        
        # Show most commonly missing metrics
        if missing_metrics:
            print(f"\n📊 Most Commonly Missing Metrics:")
            for metric, count in missing_metrics.most_common(10):
                print(f"   {metric}: missing in {count} tickers")
        
        return {
            'total_checked': total,
            'complete': len(with_fundamentals),
            'partial': len(partial_fundamentals),
            'missing': len(without_fundamentals),
            'with_fundamentals': with_fundamentals,
            'without_fundamentals': without_fundamentals,
            'available_metrics': dict(available_metrics)
        }
    
    def analyze_company_profiles(self, price_universe: List[str]) -> Dict:
        """Analyze company profile coverage."""
        print("\n" + "=" * 80)
        print(" COMPANY PROFILE ANALYSIS")
        print("=" * 80)
        
        print(f"\n📁 Checking profiles for {len(price_universe)} tickers")
        print(f"📂 Company info directory: {self.company_info_dir}\n")
        print("ℹ️  NOTE: Company profiles are stored in a single parquet file (company_profiles.parquet)")
        
        # Load the single company profiles parquet file
        profiles_file = self.company_info_dir / 'company_profiles.parquet'
        
        with_profiles = []
        without_profiles = []
        incomplete_profiles = []
        
        # Key fields to check
        key_fields = ['sector', 'industry', 'marketCap', 'exchange', 'country']
        field_availability = defaultdict(int)
        
        try:
            if not profiles_file.exists():
                print(f"⚠️  WARNING: Company profiles file not found: {profiles_file}")
                print(f"    All {len(price_universe)} tickers will be marked as missing profiles.\n")
                for ticker in price_universe:
                    without_profiles.append(ticker)
                    self.profile_results[ticker] = {'status': 'missing_file'}
            else:
                # Load all profiles at once
                profiles_df = pd.read_parquet(profiles_file)
                print(f"Loaded profiles for {len(profiles_df)} companies\n")
                
                # Check each ticker
                for ticker in price_universe:
                    if ticker in profiles_df.index:
                        try:
                            profile = profiles_df.loc[ticker]
                            
                            # Check key fields
                            available_fields = []
                            for field in key_fields:
                                if field in profile.index and pd.notna(profile[field]) and profile[field]:
                                    available_fields.append(field)
                                    field_availability[field] += 1
                            
                            completeness = len(available_fields) / len(key_fields)
                            
                            if completeness >= 0.8:
                                with_profiles.append(ticker)
                                status = 'complete'
                            elif completeness > 0:
                                incomplete_profiles.append(ticker)
                                status = 'incomplete'
                            else:
                                without_profiles.append(ticker)
                                status = 'empty'
                            
                            self.profile_results[ticker] = {
                                'status': status,
                                'available_fields': available_fields,
                                'completeness': completeness,
                                'sector': profile.get('sector') if 'sector' in profile.index else None,
                                'industry': profile.get('industry') if 'industry' in profile.index else None
                            }
                            
                        except Exception as e:
                            without_profiles.append(ticker)
                            self.profile_results[ticker] = {
                                'status': 'error',
                                'error': str(e)
                            }
                    else:
                        without_profiles.append(ticker)
                        self.profile_results[ticker] = {'status': 'missing'}
        
        except Exception as e:
            print(f"❌ ERROR loading profiles file: {e}")
            for ticker in price_universe:
                without_profiles.append(ticker)
                self.profile_results[ticker] = {'status': 'file_error', 'error': str(e)}
        
        # Print results
        total = len(price_universe)
        print(f"\n✅ Complete profiles: {len(with_profiles)} tickers ({len(with_profiles)/total*100:.1f}%)")
        print(f"⚠️  Incomplete profiles: {len(incomplete_profiles)} tickers ({len(incomplete_profiles)/total*100:.1f}%)")
        print(f"❌ No profiles: {len(without_profiles)} tickers ({len(without_profiles)/total*100:.1f}%)")
        
        # Show tickers without profiles
        if without_profiles and len(without_profiles) <= 50:
            print(f"\n📋 Tickers WITHOUT Profiles ({len(without_profiles)}):")
            for ticker in sorted(without_profiles)[:20]:
                print(f"   {ticker}")
            if len(without_profiles) > 20:
                print(f"   ... and {len(without_profiles) - 20} more")
        
        # Show field availability
        print(f"\n📊 Key Field Availability:")
        for field in key_fields:
            count = field_availability[field]
            print(f"   {field}: {count}/{total} ({count/total*100:.1f}%)")
        
        return {
            'total_checked': total,
            'complete': len(with_profiles),
            'incomplete': len(incomplete_profiles),
            'missing': len(without_profiles),
            'with_profiles': with_profiles,
            'without_profiles': without_profiles,
            'field_availability': dict(field_availability)
        }

    def analyze_earnings_health(self, price_universe: List[str]) -> Dict:
        """
        Analyze earnings data health and staleness.

        Checks:
        1. Earnings cache coverage (how many tickers have earnings data)
        2. Staleness detection:
           - If today > future_earnings_date + 1 day AND fundamental_cache_date < latest_earnings_date
           - This indicates FMP has filled in actuals since we last updated fundamentals
        3. Earnings data quality (null actuals, cache age)

        Args:
            price_universe: List of ticker symbols to analyze

        Returns:
            Dictionary with earnings health metrics
        """
        if self.earnings_engine is None:
            print("\n⚠️  Earnings analysis skipped: EarningsEngine not available (API key missing)")
            return {
                'total_checked': len(price_universe),
                'with_earnings': 0,
                'without_earnings': len(price_universe),
                'stale_fundamentals': [],
                'cache_issues': [],
                'skipped': True
            }

        print("\n" + "=" * 80)
        print(" EARNINGS HEALTH ANALYSIS")
        print("=" * 80)

        print(f"\nAnalyzing earnings data for {len(price_universe)} tickers")
        print(f"Earnings directory: {self.earnings_dir}\n")

        # Results tracking
        with_earnings = []
        without_earnings = []
        stale_fundamentals = []  # Tickers with fundamentals older than latest earnings
        cache_issues = []  # Tickers with corrupted/invalid earnings cache
        earnings_quality = {}

        # Get list of all earnings files
        earnings_files = {f.stem for f in self.earnings_dir.glob('*.parquet')}

        print(f"Total earnings cache files: {len(earnings_files)}\n")

        # Analyze each ticker
        for ticker in price_universe:
            if ticker not in earnings_files:
                without_earnings.append(ticker)
                self.earnings_results[ticker] = {
                    'status': 'missing',
                    'has_cache': False
                }
                continue

            try:
                # Load earnings data
                earnings_df = self.earnings_engine.get_ticker_earnings(ticker, use_cache=True)

                if earnings_df is None or earnings_df.empty:
                    without_earnings.append(ticker)
                    cache_issues.append((ticker, 'empty_or_failed'))
                    self.earnings_results[ticker] = {
                        'status': 'error',
                        'has_cache': True,
                        'issue': 'Empty or failed to load'
                    }
                    continue

                with_earnings.append(ticker)

                # Get latest past earnings date
                past_earnings = earnings_df[~earnings_df['is_future']]
                latest_earnings_date = past_earnings['date'].max() if not past_earnings.empty else None

                # Get cache age
                cache_timestamp = earnings_df['cache_timestamp'].iloc[0]
                cache_age_days = (datetime.now() - cache_timestamp).days

                # Check for null actuals in latest 3 earnings
                latest_3 = past_earnings.head(3)
                has_null_actuals = False
                if not latest_3.empty:
                    has_null_actuals = (
                        latest_3['epsActual'].isna().any() or
                        latest_3['revenueActual'].isna().any()
                    )

                # Check fundamental cache staleness
                fund_cache = self.fundamentals_dir / f"{ticker}.parquet"
                is_fund_stale = False
                fund_cache_date = None

                if fund_cache.exists() and latest_earnings_date:
                    fund_cache_date = datetime.fromtimestamp(fund_cache.stat().st_mtime)

                    # Staleness rule: latest_earnings_date > fundamental_cache_date
                    if pd.to_datetime(latest_earnings_date) > fund_cache_date:
                        is_fund_stale = True
                        stale_fundamentals.append({
                            'ticker': ticker,
                            'latest_earnings': latest_earnings_date,
                            'fund_cache_date': fund_cache_date,
                            'days_behind': (pd.to_datetime(latest_earnings_date) - fund_cache_date).days
                        })

                # Get next earnings date
                future_earnings = earnings_df[earnings_df['is_future']].sort_values('date')
                next_earnings_date = future_earnings.iloc[0]['date'] if not future_earnings.empty else None
                days_until_earnings = (next_earnings_date - pd.Timestamp.now()).days if next_earnings_date else None

                # Record earnings quality
                earnings_quality[ticker] = {
                    'latest_earnings_date': latest_earnings_date,
                    'next_earnings_date': next_earnings_date,
                    'days_until_earnings': days_until_earnings,
                    'cache_age_days': cache_age_days,
                    'has_null_actuals': has_null_actuals,
                    'total_earnings': len(earnings_df),
                    'past_earnings': len(past_earnings),
                    'future_earnings': len(future_earnings),
                    'is_fund_stale': is_fund_stale,
                    'fund_cache_date': fund_cache_date
                }

                self.earnings_results[ticker] = {
                    'status': 'complete',
                    'has_cache': True,
                    'quality': earnings_quality[ticker]
                }

            except Exception as e:
                without_earnings.append(ticker)
                cache_issues.append((ticker, str(e)))
                self.earnings_results[ticker] = {
                    'status': 'error',
                    'has_cache': True,
                    'error': str(e)
                }

        # Print results
        total = len(price_universe)
        print(f"\nWith earnings cache: {len(with_earnings)} tickers ({len(with_earnings)/total*100:.1f}%)")
        print(f"Without earnings cache: {len(without_earnings)} tickers ({len(without_earnings)/total*100:.1f}%)")

        if cache_issues:
            print(f"\nCache Issues ({len(cache_issues)} tickers):")
            for ticker, issue in cache_issues[:10]:
                print(f"   {ticker}: {issue}")
            if len(cache_issues) > 10:
                print(f"   ... and {len(cache_issues) - 10} more")

        # Stale fundamentals analysis
        if stale_fundamentals:
            print(f"\nSTALE FUNDAMENTALS DETECTED ({len(stale_fundamentals)} tickers):")
            print(f"   These tickers have earnings AFTER their fundamental cache update:")

            # Sort by days behind (worst first)
            stale_sorted = sorted(stale_fundamentals, key=lambda x: x['days_behind'], reverse=True)

            for item in stale_sorted[:15]:
                print(f"   {item['ticker']:6s}: Latest earnings {item['latest_earnings'].date()}, "
                      f"Fund cache {item['fund_cache_date'].date()} ({item['days_behind']} days behind)")

            if len(stale_sorted) > 15:
                print(f"   ... and {len(stale_sorted) - 15} more")

            print(f"\n   Recommendation: Run 'python data_curator.py --update-fundamentals' to refresh")

        # Earnings quality statistics
        if earnings_quality:
            cache_ages = [q['cache_age_days'] for q in earnings_quality.values()]
            null_actuals_count = sum(1 for q in earnings_quality.values() if q['has_null_actuals'])

            print(f"\nEarnings Cache Quality:")
            print(f"   Average cache age: {np.mean(cache_ages):.1f} days")
            print(f"   Median cache age: {np.median(cache_ages):.0f} days")
            print(f"   Max cache age: {np.max(cache_ages):.0f} days")
            print(f"   Tickers with null actuals: {null_actuals_count} ({null_actuals_count/len(earnings_quality)*100:.1f}%)")

            # Upcoming earnings
            upcoming = [q for q in earnings_quality.values()
                       if q['days_until_earnings'] and 0 <= q['days_until_earnings'] <= 30]

            if upcoming:
                print(f"\nUpcoming Earnings (next 30 days): {len(upcoming)} tickers")
                upcoming_sorted = sorted(upcoming, key=lambda x: x['days_until_earnings'])
                for q in upcoming_sorted[:10]:
                    ticker = [t for t, data in earnings_quality.items() if data == q][0]
                    print(f"   {ticker:6s}: {q['next_earnings_date'].date()} "
                          f"({q['days_until_earnings']} days)")

        return {
            'total_checked': total,
            'with_earnings': len(with_earnings),
            'without_earnings': len(without_earnings),
            'stale_fundamentals': stale_fundamentals,
            'stale_fundamentals_count': len(stale_fundamentals),
            'cache_issues': cache_issues,
            'earnings_quality': earnings_quality,
            'skipped': False
        }

    def cross_reference_analysis(self, price_summary: Dict, fund_summary: Dict, profile_summary: Dict):
        """Analyze cross-references between data types."""
        print("\n" + "=" * 80)
        print(" CROSS-REFERENCE ANALYSIS")
        print("=" * 80)
        
        passed_price = set(price_summary['passed_tickers'])
        with_fundamentals = set(fund_summary['with_fundamentals'])
        with_profiles = set(profile_summary['with_profiles'])
        
        # Combinations
        full_data = passed_price & with_fundamentals & with_profiles
        price_fund_only = passed_price & with_fundamentals - with_profiles
        price_profile_only = passed_price & with_profiles - with_fundamentals
        price_only = passed_price - with_fundamentals - with_profiles
        
        print(f"\n📊 Data Combination Analysis (for tickers passing 200-bar filter):")
        print(f"\n   ✅ Price + ✅ Fundamentals + ✅ Profile: {len(full_data)} tickers")
        print(f"      → These are FULLY eligible for Dataset B")
        
        print(f"\n   ✅ Price + ✅ Fundamentals + ❌ Profile: {len(price_fund_only)} tickers")
        print(f"   ✅ Price + ❌ Fundamentals + ✅ Profile: {len(price_profile_only)} tickers")
        print(f"   ✅ Price + ❌ Fundamentals + ❌ Profile: {len(price_only)} tickers")
        
        total_passed = len(passed_price)
        print(f"\n📈 Dataset B Eligibility:")
        print(f"   Total passed 200-bar filter: {total_passed}")
        print(f"   With complete data stack: {len(full_data)} ({len(full_data)/total_passed*100:.1f}%)")
        
        return {
            'full_data': len(full_data),
            'price_fund_only': len(price_fund_only),
            'price_profile_only': len(price_profile_only),
            'price_only': len(price_only),
            'full_data_tickers': list(full_data)
        }
    
    def generate_summary_report(self, price_summary: Dict, fund_summary: Dict,
                                profile_summary: Dict, cross_ref: Dict,
                                earnings_summary: Dict = None):
        """Generate final summary report."""
        print("\n" + "=" * 80)
        print(" SUMMARY REPORT")
        print("=" * 80)

        print(f"\n🎯 KEY FINDINGS:")
        print(f"\n1. PRICE DATA:")
        print(f"   - Universe size: {price_summary['total_tickers']} tickers")
        print(f"   - Passing 200-bar filter: {price_summary['passed']} ({price_summary['passed']/price_summary['total_tickers']*100:.1f}%)")
        print(f"   - Failing 200-bar filter: {price_summary['failed']} ({price_summary['failed']/price_summary['total_tickers']*100:.1f}%)")
        print(f"   - Load errors: {price_summary['errors']}")

        print(f"\n2. FUNDAMENTAL DATA:")
        print(f"   - Complete coverage: {fund_summary['complete']}/{fund_summary['total_checked']} ({fund_summary['complete']/fund_summary['total_checked']*100:.1f}%)")
        print(f"   - Missing: {fund_summary['missing']} tickers")

        print(f"\n3. COMPANY PROFILES:")
        print(f"   - Complete coverage: {profile_summary['complete']}/{profile_summary['total_checked']} ({profile_summary['complete']/profile_summary['total_checked']*100:.1f}%)")
        print(f"   - Missing: {profile_summary['missing']} tickers")

        if earnings_summary and not earnings_summary.get('skipped', False):
            print(f"\n4. EARNINGS DATA:")
            print(f"   - With earnings cache: {earnings_summary['with_earnings']}/{earnings_summary['total_checked']} ({earnings_summary['with_earnings']/earnings_summary['total_checked']*100:.1f}%)")
            print(f"   - Missing earnings: {earnings_summary['without_earnings']} tickers")
            if earnings_summary['stale_fundamentals_count'] > 0:
                print(f"   - ⚠️  STALE FUNDAMENTALS: {earnings_summary['stale_fundamentals_count']} tickers need update")

            print(f"\n5. DATASET B ELIGIBILITY:")
            print(f"   - Fully eligible (all data): {cross_ref['full_data']} tickers")
            print(f"   - Percentage of passed price filter: {cross_ref['full_data']/price_summary['passed']*100:.1f}%")
        else:
            print(f"\n4. DATASET B ELIGIBILITY:")
            print(f"   - Fully eligible (all data): {cross_ref['full_data']} tickers")
            print(f"   - Percentage of passed price filter: {cross_ref['full_data']/price_summary['passed']*100:.1f}%")

        print(f"\n💡 RECOMMENDATIONS:")

        if price_summary['failed'] > price_summary['passed'] * 0.3:
            print(f"\n   ⚠️  HIGH: {price_summary['failed']} tickers fail the 200-bar filter")
            print(f"      → Consider extending price data history collection")
            print(f"      → Or adjust the 200-bar threshold based on requirements")

        if fund_summary['missing'] > fund_summary['total_checked'] * 0.2:
            print(f"\n   ⚠️  MEDIUM: {fund_summary['missing']} tickers lack fundamental data")
            print(f"      → Prioritize fundamental data collection for passed price tickers")

        if profile_summary['missing'] > profile_summary['total_checked'] * 0.2:
            print(f"\n   ⚠️  MEDIUM: {profile_summary['missing']} tickers lack company profiles")
            print(f"      → Consider batch profile collection")

        if earnings_summary and not earnings_summary.get('skipped', False):
            if earnings_summary['stale_fundamentals_count'] > 0:
                print(f"\n   🔴 CRITICAL: {earnings_summary['stale_fundamentals_count']} tickers have stale fundamental data")
                print(f"      → Run 'python data_curator.py --update-fundamentals' to refresh")
                print(f"      → These tickers have new earnings reports not reflected in fundamental cache")

            if earnings_summary['without_earnings'] > earnings_summary['total_checked'] * 0.3:
                print(f"\n   ⚠️  MEDIUM: {earnings_summary['without_earnings']} tickers lack earnings data")
                print(f"      → Consider updating earnings cache for better fundamental staleness detection")

        print("\n" + "=" * 80)
    
    def save_detailed_report(self, output_path: str = "data/data_health_report.json"):
        """Save detailed report to JSON file."""
        report = {
            'generated_at': datetime.now().isoformat(),
            'price_results': self.price_results,
            'fundamental_results': self.fundamental_results,
            'profile_results': self.profile_results,
            'earnings_results': self.earnings_results
        }
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        print(f"\n📝 Detailed report saved to: {output_file}")
        return output_file
    
    def run_full_analysis(self, detailed_fundamentals=True):
        """
        Run complete data health analysis.

        Args:
            detailed_fundamentals: If True, run detailed quality checks on fundamental data
        """
        print("\n" + "=" * 80)
        print(" DATA HEALTH ANALYZER - COMPREHENSIVE REPORT")
        print("=" * 80)
        print(f" Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)

        # 1. Price data analysis
        price_summary = self.analyze_price_data()

        # Use passed tickers for subsequent analysis
        passed_tickers = price_summary['passed_tickers']

        # 2. Fundamental data analysis (ENHANCED with quality checks)
        if detailed_fundamentals:
            fund_quality = self.analyze_fundamental_data_quality(passed_tickers)
            # For backwards compatibility, create a summary
            fund_summary = {
                'total_checked': len(passed_tickers),
                'complete': fund_quality['summary']['excellent'] + fund_quality['summary']['good'],
                'partial': fund_quality['summary']['fair'],
                'missing': fund_quality['summary']['poor'] + fund_quality['summary']['no_data'],
                'with_fundamentals': [t for t, s in fund_quality['quality_scores'].items()
                                     if s['status'] in ['excellent', 'good', 'fair']],
                'without_fundamentals': [t for t, s in fund_quality['quality_scores'].items()
                                        if s['status'] in ['poor', 'no_file', 'empty', 'error']],
                'quality_details': fund_quality
            }
        else:
            fund_summary = self.analyze_fundamental_data(passed_tickers)
            fund_quality = None

        # 3. Company profile analysis
        profile_summary = self.analyze_company_profiles(passed_tickers)

        # 4. Earnings health analysis
        earnings_summary = self.analyze_earnings_health(passed_tickers)

        # 5. Cross-reference analysis
        cross_ref = self.cross_reference_analysis(price_summary, fund_summary, profile_summary)

        # 6. Summary report
        self.generate_summary_report(price_summary, fund_summary, profile_summary, cross_ref, earnings_summary)

        # 7. Save detailed report
        self.save_detailed_report()

        print("\n✅ Analysis complete!\n")

        return {
            'price': price_summary,
            'fundamentals': fund_summary,
            'fundamental_quality': fund_quality,
            'profiles': profile_summary,
            'earnings': earnings_summary,
            'cross_reference': cross_ref
        }


    def analyze_ipo_validation(self, save_problematic_list: bool = True) -> Dict:
        """
        Validate price cache files against IPO dates to detect anachronistic data.

        Args:
            save_problematic_list: If True, saves list of problematic files to JSON

        Returns:
            Dictionary with validation results and problematic file list
        """
        print("\n" + "=" * 80)
        print(" IPO DATE VALIDATION - CACHE CORRUPTION DETECTION")
        print("=" * 80)

        import requests
        import hashlib
        from collections import defaultdict

        # Known IPO dates (can be expanded or loaded from external source)
        KNOWN_IPO_DATES = {
            'RIVN': '2021-11-10',
            'RKLB': '2021-08-25',
            'RKT': '2020-08-06',
            'RITM': '2015-06-25',
            'LOAR': '2002-07-31',
            'RL': '1997-06-12',
            'SNOW': '2020-09-16',
            'ABNB': '2020-12-10',
            'COIN': '2021-04-14',
            'DDOG': '2019-09-19',
            'ZS': '2018-03-16',
            'CRWD': '2019-06-12',
            'DKNG': '2020-04-24',
            'PLTR': '2020-09-30',
            'U': '2019-04-18',
        }

        problematic_files = []
        duplicate_data_groups = []
        suspicious_prices = []

        # Get all cache files
        cache_files = list(self.price_dir.glob('*.parquet'))
        total_files = len(cache_files)

        print(f"\nScanning {total_files} cache files for IPO violations and corruption...\n")

        # Track data hashes to detect duplicates
        hash_registry = {}

        for cache_file in cache_files:
            ticker = cache_file.stem

            try:
                df = pd.read_parquet(cache_file)

                if df.empty:
                    continue

                data_start = df.index.min()
                data_end = df.index.max()

                issues = []

                # Check 1: IPO date validation
                if ticker in KNOWN_IPO_DATES:
                    ipo_date = pd.to_datetime(KNOWN_IPO_DATES[ticker])

                    if data_start < ipo_date:
                        years_before = (ipo_date - data_start).days / 365.25
                        issues.append({
                            'type': 'anachronistic_data',
                            'severity': 'critical',
                            'message': f'Data starts {years_before:.1f} years before IPO',
                            'data_start': str(data_start.date()),
                            'ipo_date': str(ipo_date.date()),
                            'years_before_ipo': round(years_before, 1)
                        })

                # Check 2: Duplicate data detection
                data_hash = hashlib.md5(pd.util.hash_pandas_object(df).values).hexdigest()

                if data_hash in hash_registry:
                    issues.append({
                        'type': 'duplicate_data',
                        'severity': 'critical',
                        'message': f'Identical data as {hash_registry[data_hash]}',
                        'duplicate_of': hash_registry[data_hash]
                    })

                    # Group duplicates
                    duplicate_data_groups.append({
                        'ticker': ticker,
                        'duplicate_of': hash_registry[data_hash]
                    })
                else:
                    hash_registry[data_hash] = ticker

                # Check 3: Suspicious price ranges
                if df['Close'].min() <= 0:
                    issues.append({
                        'type': 'invalid_prices',
                        'severity': 'critical',
                        'message': 'Zero or negative prices detected',
                        'min_price': float(df['Close'].min())
                    })

                if df['Close'].max() > 100000:
                    issues.append({
                        'type': 'suspicious_prices',
                        'severity': 'warning',
                        'message': 'Unrealistically high prices detected',
                        'max_price': float(df['Close'].max())
                    })
                    suspicious_prices.append(ticker)

                # Note: We don't check "before 1970" here - that's handled in data_engine validation
                # IPO validation focuses only on IPO date mismatches

                # Record problematic file
                if issues:
                    problematic_files.append({
                        'ticker': ticker,
                        'file_path': str(cache_file),
                        'data_start': str(data_start.date()),
                        'data_end': str(data_end.date()),
                        'num_rows': len(df),
                        'issues': issues,
                        'severity': 'critical' if any(i['severity'] == 'critical' for i in issues) else 'warning'
                    })

            except Exception as e:
                problematic_files.append({
                    'ticker': ticker,
                    'file_path': str(cache_file),
                    'issues': [{
                        'type': 'load_error',
                        'severity': 'critical',
                        'message': f'Failed to load file: {str(e)}'
                    }],
                    'severity': 'critical'
                })

        # Print summary
        critical_files = [f for f in problematic_files if f['severity'] == 'critical']
        warning_files = [f for f in problematic_files if f['severity'] == 'warning']

        print(f"📊 Validation Results:")
        print(f"   Total files scanned: {total_files}")
        print(f"   Clean files: {total_files - len(problematic_files)} ({(total_files - len(problematic_files))/total_files*100:.1f}%)")
        print(f"   Problematic files: {len(problematic_files)} ({len(problematic_files)/total_files*100:.1f}%)")
        print(f"     - Critical issues: {len(critical_files)}")
        print(f"     - Warnings: {len(warning_files)}")

        if problematic_files:
            print(f"\n🔴 CRITICAL Issues Found:")

            # Group by issue type
            issue_counts = defaultdict(int)
            for f in problematic_files:
                for issue in f['issues']:
                    issue_counts[issue['type']] += 1

            for issue_type, count in sorted(issue_counts.items(), key=lambda x: -x[1]):
                print(f"   {issue_type}: {count} files")

            print(f"\n📋 Problematic Files ({min(10, len(critical_files))} shown):")
            for f in critical_files[:10]:
                print(f"\n   {f['ticker']}:")
                for issue in f['issues']:
                    print(f"     - [{issue['severity'].upper()}] {issue['message']}")

            if len(critical_files) > 10:
                print(f"\n   ... and {len(critical_files) - 10} more critical issues")

        # Save problematic file list
        if save_problematic_list and problematic_files:
            output_file = Path('data/corrupted_cache_files.json')
            output_file.parent.mkdir(parents=True, exist_ok=True)

            report = {
                'generated_at': datetime.now().isoformat(),
                'total_scanned': total_files,
                'total_problematic': len(problematic_files),
                'critical_count': len(critical_files),
                'warning_count': len(warning_files),
                'problematic_files': problematic_files,
                'duplicate_groups': duplicate_data_groups,
                'suspicious_price_tickers': suspicious_prices
            }

            with open(output_file, 'w') as f:
                json.dump(report, f, indent=2)

            print(f"\n📝 Problematic files list saved to: {output_file}")

        return {
            'total_scanned': total_files,
            'clean_files': total_files - len(problematic_files),
            'problematic_files': problematic_files,
            'critical_count': len(critical_files),
            'warning_count': len(warning_files),
            'duplicate_groups': duplicate_data_groups,
            'suspicious_prices': suspicious_prices
        }


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Data Health Analyzer")
    parser.add_argument('--ipo-validation', action='store_true',
                       help='Run IPO date validation and cache corruption detection')
    parser.add_argument('--full', action='store_true',
                       help='Run full data health analysis (default)')

    args = parser.parse_args()

    analyzer = DataHealthAnalyzer()

    if args.ipo_validation:
        # Run IPO validation only
        results = analyzer.analyze_ipo_validation(save_problematic_list=True)
    else:
        # Run full analysis (default)
        results = analyzer.run_full_analysis()

        # Also run IPO validation at the end
        print("\n")
        ipo_results = analyzer.analyze_ipo_validation(save_problematic_list=True)


if __name__ == "__main__":
    main()