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


class DataHealthAnalyzer:
    """Analyzes data health across price, fundamental, and profile dimensions."""
    
    def __init__(self):
        self.price_dir = Path(config.PRICE_DATA_DIR)
        self.fundamentals_dir = Path(config.FUNDAMENTALS_DIR)
        self.company_info_dir = Path(config.COMPANY_INFO_DIR)
        
        # Results storage
        self.price_results = {}
        self.fundamental_results = {}
        self.profile_results = {}
        
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
    
    def analyze_fundamental_data(self, price_universe: List[str]) -> Dict:
        """Analyze fundamental data coverage for the price universe."""
        print("\n" + "=" * 80)
        print(" FUNDAMENTAL DATA ANALYSIS")
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
                    
                    # Get most recent data date
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

        # Load company profiles from single parquet file
        profiles_file = self.company_info_dir / 'company_profiles.parquet'

        if not profiles_file.exists():
            print(f"❌ Company profiles file not found: {profiles_file}")
            print(f"   Run Cell 4 (Company Profile Update) to generate profiles")
            return {
                'total_checked': len(price_universe),
                'complete': 0,
                'incomplete': 0,
                'missing': len(price_universe),
                'with_profiles': [],
                'without_profiles': price_universe,
                'field_availability': {}
            }

        try:
            profiles_df = pd.read_parquet(profiles_file)
            print(f"Total profiles in file: {len(profiles_df)}")

            # Get available tickers in profiles
            if 'symbol' in profiles_df.columns:
                profile_tickers = set(profiles_df['symbol'].values)
            elif 'ticker' in profiles_df.columns:
                profile_tickers = set(profiles_df['ticker'].values)
            else:
                # If no symbol/ticker column, assume index contains tickers
                profile_tickers = set(profiles_df.index)

            print(f"Tickers with profiles: {len(profile_tickers)}")

        except Exception as e:
            print(f"❌ Error loading company profiles: {e}")
            return {
                'total_checked': len(price_universe),
                'complete': 0,
                'incomplete': 0,
                'missing': len(price_universe),
                'with_profiles': [],
                'without_profiles': price_universe,
                'field_availability': {}
            }

        # Categorize
        with_profiles = []
        without_profiles = []
        incomplete_profiles = []

        # Key fields to check (use actual column names from parquet)
        key_fields = ['sector', 'industry', 'mktCap', 'exchange', 'country']
        field_availability = defaultdict(int)

        for ticker in price_universe:
            if ticker in profile_tickers:
                try:
                    # Get ticker's profile row
                    if 'symbol' in profiles_df.columns:
                        profile_row = profiles_df[profiles_df['symbol'] == ticker]
                    elif 'ticker' in profiles_df.columns:
                        profile_row = profiles_df[profiles_df['ticker'] == ticker]
                    else:
                        profile_row = profiles_df.loc[[ticker]] if ticker in profiles_df.index else pd.DataFrame()

                    if profile_row.empty:
                        without_profiles.append(ticker)
                        self.profile_results[ticker] = {'status': 'missing'}
                        continue

                    # Get first row if multiple matches
                    profile = profile_row.iloc[0].to_dict()

                    # Check key fields
                    available_fields = []
                    for field in key_fields:
                        if field in profile and pd.notna(profile[field]) and profile[field] not in ['', None]:
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
                        'sector': profile.get('sector'),
                        'industry': profile.get('industry')
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

        # Print results
        total = len(price_universe)
        print(f"\n✅ Complete profiles: {len(with_profiles)} tickers ({len(with_profiles)/total*100:.1f}%)")
        print(f"⚠️  Incomplete profiles: {len(incomplete_profiles)} tickers ({len(incomplete_profiles)/total*100:.1f}%)")
        print(f"❌ No profiles: {len(without_profiles)} tickers ({len(without_profiles)/total*100:.1f}%)")

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
                                profile_summary: Dict, cross_ref: Dict):
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
        
        print("\n" + "=" * 80)
    
    def save_detailed_report(self, output_path: str = "data/data_health_report.json"):
        """Save detailed report to JSON file."""
        report = {
            'generated_at': datetime.now().isoformat(),
            'price_results': self.price_results,
            'fundamental_results': self.fundamental_results,
            'profile_results': self.profile_results
        }
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        print(f"\n📝 Detailed report saved to: {output_file}")
        return output_file
    
    def run_full_analysis(self):
        """Run complete data health analysis."""
        print("\n" + "=" * 80)
        print(" DATA HEALTH ANALYZER - COMPREHENSIVE REPORT")
        print("=" * 80)
        print(f" Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)
        
        # 1. Price data analysis
        price_summary = self.analyze_price_data()
        
        # Use passed tickers for subsequent analysis
        passed_tickers = price_summary['passed_tickers']
        
        # 2. Fundamental data analysis
        fund_summary = self.analyze_fundamental_data(passed_tickers)
        
        # 3. Company profile analysis
        profile_summary = self.analyze_company_profiles(passed_tickers)
        
        # 4. Cross-reference analysis
        cross_ref = self.cross_reference_analysis(price_summary, fund_summary, profile_summary)
        
        # 5. Summary report
        self.generate_summary_report(price_summary, fund_summary, profile_summary, cross_ref)
        
        # 6. Save detailed report
        self.save_detailed_report()
        
        print("\n✅ Analysis complete!\n")
        
        return {
            'price': price_summary,
            'fundamentals': fund_summary,
            'profiles': profile_summary,
            'cross_reference': cross_ref
        }


def main():
    """Main entry point."""
    analyzer = DataHealthAnalyzer()
    results = analyzer.run_full_analysis()


if __name__ == "__main__":
    main()
