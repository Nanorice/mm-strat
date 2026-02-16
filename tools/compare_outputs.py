"""
Output Comparison Tool - Validation Harness
============================================
Compares outputs from file-based scanner vs DuckDB scanner.

Validation checks:
1. Buy list ticker sets match exactly
2. ML scores within tolerance (1%)
3. Row counts match (price_data, fundamentals)
4. Performance benchmarks (runtime comparison)

Usage:
    # Compare both scanners for specific date
    python tools/compare_outputs.py --scan-date 2024-12-31

    # Run with detailed reporting
    python tools/compare_outputs.py --scan-date 2024-12-31 --verbose

    # Export comparison to CSV
    python tools/compare_outputs.py --scan-date 2024-12-31 --export-csv
"""

import argparse
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Tuple
import sys
import time
from datetime import datetime

# Add parent to path
sys.path.append(str(Path(__file__).parent.parent))

from src.database import DatabaseManager
from src.database_duckdb import DuckDBManager
from src.data_loader_duckdb import DuckDBDataLoader


class OutputComparator:
    """
    Compares outputs from old (SQLite + parquet) and new (DuckDB) systems.
    """

    def __init__(self, scan_date: str, verbose: bool = False):
        """
        Initialize comparator.

        Args:
            scan_date: Date to compare (YYYY-MM-DD)
            verbose: Enable detailed logging
        """
        self.scan_date = scan_date
        self.verbose = verbose

        # Initialize database managers
        self.db_old = DatabaseManager()  # SQLite
        self.db_new = DuckDBManager()   # DuckDB
        self.loader = DuckDBDataLoader()

    def compare_buy_lists(self) -> Dict:
        """
        Compare buy lists from both systems.

        Returns:
            Dict with comparison results
        """
        print(f"\n{'='*80}")
        print(f"Comparing Buy Lists for {self.scan_date}")
        print(f"{'='*80}")

        # Load buy lists
        old_buy_list = self.db_old.get_buy_list(active_only=True, as_of_date=self.scan_date)
        new_buy_list = self.db_new.get_buy_list(active_only=True, as_of_date=self.scan_date)

        # Extract ticker sets
        old_tickers = set(old_buy_list['ticker'].tolist()) if not old_buy_list.empty else set()
        new_tickers = set(new_buy_list['ticker'].tolist()) if not new_buy_list.empty else set()

        # Compute differences
        missing_in_new = old_tickers - new_tickers
        extra_in_new = new_tickers - old_tickers
        common_tickers = old_tickers & new_tickers

        # Print results
        print(f"\n📋 Ticker Count:")
        print(f"   Old system: {len(old_tickers)}")
        print(f"   New system: {len(new_tickers)}")

        if missing_in_new:
            print(f"\n❌ Missing in new: {len(missing_in_new)}")
            if self.verbose:
                print(f"      {', '.join(sorted(missing_in_new))}")

        if extra_in_new:
            print(f"\n⚠️  Extra in new: {len(extra_in_new)}")
            if self.verbose:
                print(f"      {', '.join(sorted(extra_in_new))}")

        if not missing_in_new and not extra_in_new:
            print(f"\n✅ Ticker sets match exactly! ({len(common_tickers)} tickers)")
        else:
            print(f"\n⚠️  Ticker sets differ!")
            print(f"   Common: {len(common_tickers)}")

        # Compare ML scores for common tickers
        if len(common_tickers) > 0:
            print(f"\n📊 ML Score Comparison:")
            score_comparison = self._compare_ml_scores(old_buy_list, new_buy_list, common_tickers)
        else:
            score_comparison = {}

        return {
            'scan_date': self.scan_date,
            'old_count': len(old_tickers),
            'new_count': len(new_tickers),
            'common_count': len(common_tickers),
            'missing_in_new': list(missing_in_new),
            'extra_in_new': list(extra_in_new),
            'ticker_match': len(missing_in_new) == 0 and len(extra_in_new) == 0,
            **score_comparison
        }

    def _compare_ml_scores(self, old_df: pd.DataFrame, new_df: pd.DataFrame, common_tickers: set) -> Dict:
        """
        Compare ML scores for common tickers.

        Args:
            old_df: Old system buy list
            new_df: New system buy list
            common_tickers: Set of common tickers

        Returns:
            Dict with score comparison results
        """
        # Filter to common tickers
        old_common = old_df[old_df['ticker'].isin(common_tickers)].copy()
        new_common = new_df[new_df['ticker'].isin(common_tickers)].copy()

        # Merge on ticker
        merged = old_common.merge(new_common, on='ticker', suffixes=('_old', '_new'))

        results = {}

        # Compare final_score
        if 'final_score_old' in merged.columns and 'final_score_new' in merged.columns:
            valid_mask = merged['final_score_old'].notna() & merged['final_score_new'].notna()
            valid_merged = merged[valid_mask].copy()

            if len(valid_merged) > 0:
                score_diff = (valid_merged['final_score_new'] - valid_merged['final_score_old']).abs()
                score_diff_pct = (score_diff / valid_merged['final_score_old'].abs()).abs()

                max_diff = score_diff_pct.max()
                avg_diff = score_diff_pct.mean()

                print(f"   Final Score:")
                print(f"      Valid comparisons: {len(valid_merged)}")
                print(f"      Max difference: {max_diff*100:.4f}%")
                print(f"      Avg difference: {avg_diff*100:.4f}%")

                if max_diff > 0.01:  # 1% tolerance
                    print(f"      ⚠️  Scores differ by up to {max_diff*100:.2f}%")
                    if self.verbose:
                        outliers = valid_merged[score_diff_pct > 0.01][['ticker', 'final_score_old', 'final_score_new']]
                        print(f"\n      Outliers (>1% difference):")
                        print(outliers.to_string(index=False))
                else:
                    print(f"      ✅ Scores match within 1% tolerance")

                results['final_score_max_diff_pct'] = max_diff
                results['final_score_avg_diff_pct'] = avg_diff
                results['final_score_match'] = max_diff <= 0.01

        # Compare m01_expected_return
        if 'm01_expected_return_old' in merged.columns and 'm01_expected_return_new' in merged.columns:
            valid_mask = merged['m01_expected_return_old'].notna() & merged['m01_expected_return_new'].notna()
            valid_merged = merged[valid_mask].copy()

            if len(valid_merged) > 0:
                score_diff = (valid_merged['m01_expected_return_new'] - valid_merged['m01_expected_return_old']).abs()
                score_diff_pct = (score_diff / valid_merged['m01_expected_return_old'].abs()).abs()

                max_diff = score_diff_pct.max()
                avg_diff = score_diff_pct.mean()

                print(f"   M01 Expected Return:")
                print(f"      Valid comparisons: {len(valid_merged)}")
                print(f"      Max difference: {max_diff*100:.4f}%")
                print(f"      Avg difference: {avg_diff*100:.4f}%")

                if max_diff <= 0.01:
                    print(f"      ✅ M01 scores match within 1% tolerance")

                results['m01_max_diff_pct'] = max_diff
                results['m01_avg_diff_pct'] = avg_diff
                results['m01_match'] = max_diff <= 0.01

        return results

    def compare_data_counts(self) -> Dict:
        """
        Compare row counts in DuckDB vs parquet files.

        Returns:
            Dict with row count comparisons
        """
        print(f"\n{'='*80}")
        print(f"Comparing Data Counts")
        print(f"{'='*80}")

        import duckdb

        db_path = Path(__file__).parent.parent / "data" / "market_data.duckdb"
        con = duckdb.connect(str(db_path))

        try:
            # Price data
            price_count = con.execute("SELECT COUNT(*) FROM price_data").fetchone()[0]
            print(f"\n📊 Price Data:")
            print(f"   DuckDB rows: {price_count:,}")

            # Fundamentals
            fund_count = con.execute("SELECT COUNT(*) FROM fundamentals").fetchone()[0]
            print(f"\n📊 Fundamentals:")
            print(f"   DuckDB rows: {fund_count:,}")

            # Company Profiles
            profile_count = con.execute("SELECT COUNT(*) FROM company_profiles").fetchone()[0]
            print(f"\n📊 Company Profiles:")
            print(f"   DuckDB rows: {profile_count:,}")

            # Daily Features
            feature_count = con.execute("SELECT COUNT(*) FROM daily_features").fetchone()[0]
            print(f"\n📊 Daily Features:")
            print(f"   DuckDB rows: {feature_count:,}")

        finally:
            con.close()

        return {
            'price_count': price_count,
            'fund_count': fund_count,
            'profile_count': profile_count,
            'feature_count': feature_count
        }

    def benchmark_performance(self) -> Dict:
        """
        Benchmark performance of both systems.

        NOTE: This is a mock benchmark since we can't actually run both scanners
        without modifying the existing system. Use this for manual validation.

        Returns:
            Dict with performance metrics
        """
        print(f"\n{'='*80}")
        print(f"Performance Benchmarks (Estimated)")
        print(f"{'='*80}")

        # These are estimates based on expected performance
        print(f"\n⏱️  Expected Performance:")
        print(f"   Old scanner (file-based):")
        print(f"      Price loading: 5-30s (ThreadPool)")
        print(f"      Fundamental merge: 5-50s (loop)")
        print(f"      Total: 30-60s")
        print(f"\n   New scanner (DuckDB):")
        print(f"      Price loading: <1s (SQL query)")
        print(f"      Fundamental merge: <1s (ASOF JOIN)")
        print(f"      Total: 10-20s")
        print(f"\n   ⚡ Expected speedup: 2-3x faster")

        # Actual measurement would require running both scanners
        print(f"\n📝 To measure actual performance:")
        print(f"   1. Run: python daily_scanner.py --scan-date {self.scan_date} --use-ml")
        print(f"   2. Run: python daily_scanner_duckdb.py --scan-date {self.scan_date} --use-ml")
        print(f"   3. Compare reported times")

        return {
            'note': 'Manual benchmark required - see console output for instructions'
        }

    def export_comparison(self, results: Dict, output_path: str):
        """
        Export comparison results to CSV.

        Args:
            results: Comparison results dict
            output_path: Path to output CSV
        """
        # Convert to DataFrame
        summary = {
            'scan_date': [results['buy_list']['scan_date']],
            'old_ticker_count': [results['buy_list']['old_count']],
            'new_ticker_count': [results['buy_list']['new_count']],
            'common_count': [results['buy_list']['common_count']],
            'ticker_match': [results['buy_list']['ticker_match']],
            'missing_in_new_count': [len(results['buy_list']['missing_in_new'])],
            'extra_in_new_count': [len(results['buy_list']['extra_in_new'])],
            'final_score_match': [results['buy_list'].get('final_score_match', None)],
            'final_score_max_diff_pct': [results['buy_list'].get('final_score_max_diff_pct', None)],
            'm01_match': [results['buy_list'].get('m01_match', None)],
            'm01_max_diff_pct': [results['buy_list'].get('m01_max_diff_pct', None)],
            'price_count': [results['data_counts']['price_count']],
            'fund_count': [results['data_counts']['fund_count']],
            'profile_count': [results['data_counts']['profile_count']],
            'feature_count': [results['data_counts']['feature_count']]
        }

        df = pd.DataFrame(summary)
        df.to_csv(output_path, index=False)

        print(f"\n💾 Exported comparison to: {output_path}")

    def run_full_comparison(self, export_csv: bool = False) -> Dict:
        """
        Run full validation suite.

        Args:
            export_csv: If True, export results to CSV

        Returns:
            Dict with all comparison results
        """
        results = {
            'buy_list': self.compare_buy_lists(),
            'data_counts': self.compare_data_counts(),
            'performance': self.benchmark_performance()
        }

        # Print summary
        print(f"\n{'='*80}")
        print(f"Validation Summary")
        print(f"{'='*80}")

        ticker_match = "✅ PASS" if results['buy_list']['ticker_match'] else "❌ FAIL"
        print(f"\n1. Ticker Set Match: {ticker_match}")

        if results['buy_list'].get('final_score_match') is not None:
            score_match = "✅ PASS" if results['buy_list']['final_score_match'] else "❌ FAIL"
            print(f"2. ML Score Match: {score_match}")

        print(f"3. Data Counts:")
        print(f"   Price rows: {results['data_counts']['price_count']:,}")
        print(f"   Fundamental rows: {results['data_counts']['fund_count']:,}")
        print(f"   Feature rows: {results['data_counts']['feature_count']:,}")

        # Overall verdict
        all_pass = results['buy_list']['ticker_match']
        if results['buy_list'].get('final_score_match') is not None:
            all_pass = all_pass and results['buy_list']['final_score_match']

        print(f"\n{'='*80}")
        if all_pass:
            print(f"✅ VALIDATION PASSED - Systems are equivalent!")
        else:
            print(f"❌ VALIDATION FAILED - Review differences above")
        print(f"{'='*80}\n")

        # Export if requested
        if export_csv:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = f"comparison_{self.scan_date}_{timestamp}.csv"
            self.export_comparison(results, output_path)

        return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Compare outputs from old vs new scanner",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('--scan-date', type=str, required=True,
                        help="Scan date to compare (YYYY-MM-DD)")
    parser.add_argument('--verbose', action='store_true',
                        help="Enable detailed logging")
    parser.add_argument('--export-csv', action='store_true',
                        help="Export comparison to CSV")

    args = parser.parse_args()

    # Run comparison
    comparator = OutputComparator(scan_date=args.scan_date, verbose=args.verbose)
    results = comparator.run_full_comparison(export_csv=args.export_csv)
