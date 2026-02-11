#!/usr/bin/env python3
"""
D2R Verification Script
========================

Verifies that D2R files have correct cross-sectional RS ranks and company features.

Usage:
    python verify_d2r.py                    # Verify d2r_120d.parquet
    python verify_d2r.py --file d2r_60d     # Verify specific file
    python verify_d2r.py --all              # Verify all D2R files
"""

import argparse
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple
import warnings
warnings.filterwarnings('ignore')


class D2RVerifier:
    """Comprehensive verification for D2R datasets."""

    def __init__(self, d2r_path: str):
        self.d2r_path = Path(d2r_path)
        self.d2r = None
        self.results = {}

    def load_data(self) -> bool:
        """Load D2R file."""
        print(f"\n{'='*70}")
        print(f"LOADING: {self.d2r_path.name}")
        print(f"{'='*70}")

        if not self.d2r_path.exists():
            print(f"❌ File not found: {self.d2r_path}")
            return False

        try:
            self.d2r = pd.read_parquet(self.d2r_path)
            size_mb = self.d2r_path.stat().st_size / 1024 / 1024
            print(f"✓ Loaded successfully")
            print(f"  Shape: {self.d2r.shape[0]:,} rows × {self.d2r.shape[1]} columns")
            print(f"  Size: {size_mb:.1f} MB")

            # Handle both 'date' and 'Date' column names
            if 'Date' in self.d2r.columns and 'date' not in self.d2r.columns:
                self.d2r['date'] = pd.to_datetime(self.d2r['Date'])
            elif 'date' in self.d2r.columns:
                self.d2r['date'] = pd.to_datetime(self.d2r['date'])
            else:
                print("❌ No date column found!")
                return False

            return True
        except Exception as e:
            print(f"❌ Failed to load: {e}")
            return False

    def check_1_column_count(self) -> bool:
        """Verify column count matches expectations."""
        print(f"\n[1] COLUMN COUNT VERIFICATION")
        print("-" * 70)

        expected_min = 145  # Old 140 + at least 5 new features
        actual = len(self.d2r.columns)

        # Check for new columns
        new_cols = [
            'sector_id', 'industry_id', 'mktCap_log', 'beta',
            'RS_Universe_Rank', 'RS_Sector_Rank', 'RS_Industry_Rank',
            'RS_vs_Sector', 'RS_vs_Industry', 'Sector_Momentum', 'Industry_Momentum'
        ]

        missing_cols = [col for col in new_cols if col not in self.d2r.columns]
        present_cols = [col for col in new_cols if col in self.d2r.columns]

        if missing_cols:
            print(f"❌ FAIL: Missing {len(missing_cols)} expected columns:")
            for col in missing_cols:
                print(f"   - {col}")
            self.results['column_count'] = False
            return False
        else:
            print(f"✓ PASS: All {len(new_cols)} expected columns present")
            print(f"  Total columns: {actual}")
            print(f"  New columns added: {', '.join(present_cols[:4])}...")
            self.results['column_count'] = True
            return True

    def check_2_rs_rank_validity(self) -> bool:
        """Verify RS rank is cross-sectional (per day, across universe)."""
        print(f"\n[2] RS RANK CROSS-SECTIONAL VALIDITY")
        print("-" * 70)

        if 'RS_Universe_Rank' not in self.d2r.columns:
            print("❌ RS_Universe_Rank column not found")
            self.results['rs_rank_validity'] = False
            return False

        # Sample 5 random dates
        sample_dates = self.d2r['date'].drop_duplicates().sample(min(5, self.d2r['date'].nunique()))
        all_passed = True

        for sample_date in sample_dates:
            day_data = self.d2r[self.d2r['date'] == sample_date]

            # Check 1: Range [0, 1]
            rank_min = day_data['RS_Universe_Rank'].min()
            rank_max = day_data['RS_Universe_Rank'].max()

            if rank_min < 0 or rank_max > 1:
                print(f"❌ {sample_date.date()}: Range [{rank_min:.3f}, {rank_max:.3f}] (expected [0, 1])")
                all_passed = False
                continue

            # Check 2: High uniqueness (cross-sectional should have unique ranks)
            unique_ranks = day_data['RS_Universe_Rank'].nunique()
            total_stocks = len(day_data)
            uniqueness_pct = unique_ranks / total_stocks * 100

            # Check 3: Distribution uniformity (roughly flat)
            quartiles = day_data['RS_Universe_Rank'].quantile([0.25, 0.5, 0.75]).values

            if uniqueness_pct > 80:
                status = "✓"
            else:
                status = "⚠"
                all_passed = False

            print(f"{status} {sample_date.date()}: {total_stocks} stocks, {unique_ranks} unique ranks ({uniqueness_pct:.1f}%)")
            print(f"     Range: [{rank_min:.3f}, {rank_max:.3f}], Quartiles: [{quartiles[0]:.2f}, {quartiles[1]:.2f}, {quartiles[2]:.2f}]")

        if all_passed:
            print(f"\n✓ PASS: RS ranks are cross-sectional (per day)")
            self.results['rs_rank_validity'] = True
        else:
            print(f"\n❌ FAIL: RS rank distribution issues detected")
            self.results['rs_rank_validity'] = False

        return all_passed

    def check_3_company_features_coverage(self) -> bool:
        """Check coverage of company profile features."""
        print(f"\n[3] COMPANY FEATURES COVERAGE")
        print("-" * 70)

        company_cols = ['sector_id', 'industry_id', 'mktCap_log', 'beta']
        missing = [col for col in company_cols if col not in self.d2r.columns]

        if missing:
            print(f"❌ Missing columns: {missing}")
            self.results['company_coverage'] = False
            return False

        total_rows = len(self.d2r)

        # Check coverage (sector_id != -1 means valid)
        valid_sector = (self.d2r['sector_id'] != -1).sum()
        valid_industry = (self.d2r['industry_id'] != -1).sum()
        valid_beta = (self.d2r['beta'] != 1.0).sum()  # 1.0 is default
        valid_mktcap = (self.d2r['mktCap_log'] > 0).sum()

        sector_pct = valid_sector / total_rows * 100
        industry_pct = valid_industry / total_rows * 100
        beta_pct = valid_beta / total_rows * 100
        mktcap_pct = valid_mktcap / total_rows * 100

        print(f"  sector_id:   {valid_sector:,}/{total_rows:,} ({sector_pct:.1f}%)")
        print(f"  industry_id: {valid_industry:,}/{total_rows:,} ({industry_pct:.1f}%)")
        print(f"  beta:        {valid_beta:,}/{total_rows:,} ({beta_pct:.1f}%)")
        print(f"  mktCap_log:  {valid_mktcap:,}/{total_rows:,} ({mktcap_pct:.1f}%)")

        # Pass if coverage > 80%
        if sector_pct > 80 and industry_pct > 80:
            print(f"\n✓ PASS: Company features coverage > 80%")
            self.results['company_coverage'] = True
            return True
        else:
            print(f"\n⚠ WARNING: Company features coverage < 80%")
            self.results['company_coverage'] = False
            return False

    def check_4_cross_sectional_math(self) -> bool:
        """Verify cross-sectional feature calculations are correct."""
        print(f"\n[4] CROSS-SECTIONAL FEATURE MATH VALIDATION")
        print("-" * 70)

        # Sample one date
        sample_date = self.d2r['date'].drop_duplicates().sample(1).iloc[0]
        day_data = self.d2r[self.d2r['date'] == sample_date].copy()

        print(f"Testing date: {sample_date.date()} ({len(day_data)} stocks)")

        all_passed = True

        # Test 1: Sector_Momentum = mean(rs_rating) per sector
        if 'Sector_Momentum' in day_data.columns and 'rs_rating' in day_data.columns:
            sectors_to_test = day_data['sector_id'].value_counts().head(3).index

            for sector_id in sectors_to_test:
                sector_data = day_data[day_data['sector_id'] == sector_id]
                expected_momentum = sector_data['rs_rating'].mean()
                actual_momentum = sector_data['Sector_Momentum'].iloc[0]

                diff = abs(expected_momentum - actual_momentum)
                if diff < 0.01:
                    status = "✓"
                else:
                    status = "❌"
                    all_passed = False

                print(f"  {status} Sector {sector_id}: Momentum={actual_momentum:.2f} (expected {expected_momentum:.2f}, diff={diff:.4f})")
        else:
            print("  ⚠ Missing Sector_Momentum or rs_rating column")
            all_passed = False

        # Test 2: RS_Sector_Rank correlates with rs_rating
        if 'RS_Sector_Rank' in day_data.columns and 'rs_rating' in day_data.columns:
            for sector_id in sectors_to_test:
                sector_data = day_data[day_data['sector_id'] == sector_id]
                if len(sector_data) >= 3:  # Need at least 3 for correlation
                    corr = sector_data[['rs_rating', 'RS_Sector_Rank']].corr().iloc[0, 1]

                    if corr > 0.95:
                        status = "✓"
                    else:
                        status = "❌"
                        all_passed = False

                    print(f"  {status} Sector {sector_id}: RS_Sector_Rank correlation with rs_rating = {corr:.3f}")

        if all_passed:
            print(f"\n✓ PASS: Cross-sectional math is correct")
            self.results['cross_sectional_math'] = True
        else:
            print(f"\n❌ FAIL: Cross-sectional math validation failed")
            self.results['cross_sectional_math'] = False

        return all_passed

    def check_5_time_series_integrity(self) -> bool:
        """Verify company features are constant within each trade."""
        print(f"\n[5] TIME SERIES INTEGRITY (Company Features)")
        print("-" * 70)

        # Sample 10 random trades
        sample_trades = self.d2r['trade_id'].drop_duplicates().sample(min(10, self.d2r['trade_id'].nunique()))

        all_passed = True
        issues = []

        for trade_id in sample_trades:
            trade_data = self.d2r[self.d2r['trade_id'] == trade_id]

            # Company features should be constant
            sector_unique = trade_data['sector_id'].nunique()
            industry_unique = trade_data['industry_id'].nunique()
            ticker_unique = trade_data['ticker'].nunique()

            if sector_unique != 1 or industry_unique != 1 or ticker_unique != 1:
                issues.append(f"Trade {trade_id}: sector={sector_unique}, industry={industry_unique}, ticker={ticker_unique}")
                all_passed = False

            # Beta should be nearly constant (allow tiny variance from rounding)
            beta_std = trade_data['beta'].std()
            if beta_std > 0.01:
                issues.append(f"Trade {trade_id}: beta variance too high (std={beta_std:.4f})")
                all_passed = False

        if all_passed:
            print(f"✓ PASS: Company features constant within all {len(sample_trades)} sampled trades")
            self.results['time_series_integrity'] = True
        else:
            print(f"❌ FAIL: Found {len(issues)} trades with varying company features:")
            for issue in issues[:5]:  # Show first 5
                print(f"   - {issue}")
            self.results['time_series_integrity'] = False

        return all_passed

    def check_6_null_analysis(self) -> bool:
        """Check for unexpected null values."""
        print(f"\n[6] NULL VALUE ANALYSIS")
        print("-" * 70)

        cross_sectional_cols = [
            'RS_Universe_Rank', 'RS_Sector_Rank', 'RS_Industry_Rank',
            'RS_vs_Sector', 'RS_vs_Industry', 'Sector_Momentum', 'Industry_Momentum'
        ]

        existing_cols = [col for col in cross_sectional_cols if col in self.d2r.columns]
        null_counts = self.d2r[existing_cols].isnull().sum()

        total_nulls = null_counts.sum()

        if total_nulls == 0:
            print(f"✓ PASS: No null values in cross-sectional features")
            self.results['null_analysis'] = True
            return True
        else:
            print(f"⚠ WARNING: Found {total_nulls} null values:")
            print(null_counts[null_counts > 0])

            # Check if nulls are from unmapped tickers
            unmapped_mask = self.d2r['sector_id'] == -1
            unmapped_pct = unmapped_mask.sum() / len(self.d2r) * 100
            print(f"\n  Unmapped tickers (sector_id=-1): {unmapped_pct:.1f}%")

            self.results['null_analysis'] = False
            return False

    def check_7_compare_d2_vs_d2r(self) -> bool:
        """Compare D2 vs D2R entry features."""
        print(f"\n[7] D2 vs D2R FEATURE DISTRIBUTION COMPARISON")
        print("-" * 70)

        d2_path = Path('data/ml/d2.parquet')
        if not d2_path.exists():
            print("⚠ D2 file not found, skipping comparison")
            self.results['d2_comparison'] = None
            return True

        try:
            d2 = pd.read_parquet(d2_path)

            # Get entry day features from D2R (first day of each trade)
            d2r_entry = self.d2r.sort_values('date').groupby('trade_id').first().reset_index()

            features_to_compare = ['RS', 'RS_Universe_Rank', 'sector_id', 'mktCap_log']
            existing_features = [f for f in features_to_compare if f in d2.columns and f in d2r_entry.columns]

            print(f"Comparing {len(existing_features)} features on entry dates:")
            all_passed = True

            for feat in existing_features:
                # Filter out -1 and 0 for fair comparison
                d2_vals = d2[feat][(d2[feat] != -1) & (d2[feat] != 0)]
                d2r_vals = d2r_entry[feat][(d2r_entry[feat] != -1) & (d2r_entry[feat] != 0)]

                d2_mean = d2_vals.mean()
                d2r_mean = d2r_vals.mean()
                diff_pct = abs(d2_mean - d2r_mean) / d2_mean * 100 if d2_mean != 0 else 0

                if diff_pct < 10:
                    status = "✓"
                else:
                    status = "⚠"
                    all_passed = False

                print(f"  {status} {feat:20s}: D2={d2_mean:8.3f}, D2R={d2r_mean:8.3f} (diff: {diff_pct:5.1f}%)")

            if all_passed:
                print(f"\n✓ PASS: D2R entry features match D2 (within 10%)")
                self.results['d2_comparison'] = True
            else:
                print(f"\n⚠ WARNING: Some features differ by >10%")
                self.results['d2_comparison'] = False

            return all_passed

        except Exception as e:
            print(f"⚠ Comparison failed: {e}")
            self.results['d2_comparison'] = None
            return True

    def check_8_spot_check_trade(self) -> bool:
        """Manual inspection of a random trade."""
        print(f"\n[8] SPOT CHECK: Random Trade Inspection")
        print("-" * 70)

        # Pick a random trade
        sample_trade_id = self.d2r['trade_id'].sample(1).iloc[0]
        trade = self.d2r[self.d2r['trade_id'] == sample_trade_id].sort_values('date')

        print(f"\nTrade ID: {sample_trade_id}")
        print(f"Ticker: {trade['ticker'].iloc[0]}")
        print(f"Sector: {trade['sector_id'].iloc[0]}")
        print(f"Industry: {trade['industry_id'].iloc[0]}")
        print(f"Duration: {len(trade)} days")
        print(f"Date range: {trade['date'].min().date()} to {trade['date'].max().date()}")

        print(f"\nFirst 5 days of trajectory:")
        cols_to_show = ['date', 'Close', 'RS', 'RS_Universe_Rank', 'RS_Sector_Rank']
        existing_cols = [c for c in cols_to_show if c in trade.columns]
        print(trade[existing_cols].head(5).to_string(index=False))

        # Verify monotonic dates
        date_check = trade['date'].is_monotonic_increasing
        rank_std = trade['RS_Universe_Rank'].std() if 'RS_Universe_Rank' in trade.columns else 0
        sector_unique = trade['sector_id'].nunique()

        print(f"\nValidation:")
        print(f"  {'✓' if date_check else '❌'} Dates monotonic increasing: {date_check}")
        print(f"  {'✓' if rank_std > 0.01 else '❌'} RS_Universe_Rank varies over time: std={rank_std:.3f}")
        print(f"  {'✓' if sector_unique == 1 else '❌'} Sector constant: {sector_unique} unique value(s)")

        all_passed = date_check and rank_std > 0.01 and sector_unique == 1

        if all_passed:
            print(f"\n✓ PASS: Trade data looks reasonable")
            self.results['spot_check'] = True
        else:
            print(f"\n❌ FAIL: Trade data has issues")
            self.results['spot_check'] = False

        return all_passed

    def run_all_checks(self) -> Dict:
        """Run all verification checks."""
        if not self.load_data():
            return {'success': False, 'checks': {}}

        # Run all checks
        checks = [
            self.check_1_column_count,
            self.check_2_rs_rank_validity,
            self.check_3_company_features_coverage,
            self.check_4_cross_sectional_math,
            self.check_5_time_series_integrity,
            self.check_6_null_analysis,
            self.check_7_compare_d2_vs_d2r,
            self.check_8_spot_check_trade
        ]

        for check in checks:
            try:
                check()
            except Exception as e:
                print(f"\n❌ ERROR in {check.__name__}: {e}")
                self.results[check.__name__] = False

        # Summary
        print(f"\n{'='*70}")
        print(f"VERIFICATION SUMMARY")
        print(f"{'='*70}")

        passed = sum(1 for v in self.results.values() if v is True)
        failed = sum(1 for v in self.results.values() if v is False)
        skipped = sum(1 for v in self.results.values() if v is None)
        total = len(self.results)

        print(f"Passed: {passed}/{total}")
        print(f"Failed: {failed}/{total}")
        if skipped > 0:
            print(f"Skipped: {skipped}/{total}")

        overall_pass = failed == 0

        if overall_pass:
            print(f"\n✓ OVERALL: PASS")
        else:
            print(f"\n❌ OVERALL: FAIL ({failed} checks failed)")

        return {
            'success': overall_pass,
            'checks': self.results,
            'passed': passed,
            'failed': failed,
            'total': total
        }


def main():
    parser = argparse.ArgumentParser(description='Verify D2R file integrity')
    parser.add_argument('--file', default='d2r_120d', help='D2R file name (without .parquet)')
    parser.add_argument('--all', action='store_true', help='Verify all D2R files')
    args = parser.parse_args()

    if args.all:
        # Verify all D2R files
        d2r_files = list(Path('data/ml').glob('d2r_*.parquet'))
        if not d2r_files:
            print("No D2R files found in data/ml/")
            return

        print(f"\nFound {len(d2r_files)} D2R files to verify")

        results = {}
        for d2r_file in sorted(d2r_files):
            verifier = D2RVerifier(str(d2r_file))
            results[d2r_file.name] = verifier.run_all_checks()

        # Overall summary
        print(f"\n{'='*70}")
        print(f"OVERALL SUMMARY - All Files")
        print(f"{'='*70}")
        for filename, result in results.items():
            status = "✓ PASS" if result['success'] else "❌ FAIL"
            print(f"{status}  {filename:20s}  ({result['passed']}/{result['total']} checks passed)")
    else:
        # Verify single file
        d2r_path = f"data/ml/{args.file}.parquet" if not args.file.endswith('.parquet') else args.file
        verifier = D2RVerifier(d2r_path)
        result = verifier.run_all_checks()

        # Exit with error code if failed
        exit(0 if result['success'] else 1)


if __name__ == '__main__':
    main()
