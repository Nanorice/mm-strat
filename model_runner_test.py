"""
Model Runner Test - CLI for Testing Optimized D1/D2 Generation
===============================================================

This is a TEST version of model_runner.py that uses the optimized
DataPipelineTest to generate D1 and D2 from Universe Parquet.

Usage:
    python model_runner_test.py scan --start-date 2024-01-01 --end-date 2024-03-31
    python model_runner_test.py features
    python model_runner_test.py full --start-date 2024-01-01 --end-date 2024-03-31

Output files are named with _test suffix:
    - data/ml/d1_test.parquet
    - data/ml/d2_test.parquet
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.pipeline.data_pipeline_test import DataPipelineTest

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def cmd_scan(args):
    """Run D1 scan using optimized pipeline."""
    print("\n" + "="*60)
    print(" D1 SCAN (TEST) - Optimized with Universe Parquet + C9 Fix")
    print("="*60)
    
    pipeline = DataPipelineTest()
    
    d1 = pipeline.scan(
        start_date=args.start_date,
        end_date=args.end_date,
        threshold=args.threshold,
        save=True
    )
    
    if len(d1) > 0:
        print(f"\n✓ D1 Test generated: {len(d1)} trades")
        print(f"  Win rate: {d1['label'].mean():.1%}")
        print(f"  Saved to: data/ml/d1_test.parquet")
    else:
        print("\n✗ No trades generated!")
    
    return d1


def cmd_features(args):
    """Run D2 feature enrichment using optimized pipeline."""
    print("\n" + "="*60)
    print(" D2 FEATURES (TEST) - Optimized (Universe + Heavyweight Only)")
    print("="*60)
    
    pipeline = DataPipelineTest()
    
    d2 = pipeline.features(
        d1=None,  # Will load d1_test.parquet
        n_jobs=args.n_jobs,
        save=True,
        include_m03=not args.no_m03,
        apply_preprocessing=not args.no_preprocess
    )
    
    if len(d2) > 0:
        print(f"\n✓ D2 Test generated: {len(d2)} rows, {len(d2.columns)} columns")
        
        # Show feature breakdown
        alpha_cols = [c for c in d2.columns if c.startswith('alpha')]
        lw_cols = [c for c in d2.columns if c in ['SMA_50', 'SMA_150', 'RS', 'mom_21d']]
        print(f"  Alpha features: {len(alpha_cols)}")
        print(f"  Lightweight (from Universe): {len(lw_cols)} verified")
        print(f"  Saved to: data/ml/d2_test.parquet")
    else:
        print("\n✗ No features generated!")
    
    return d2


def cmd_full(args):
    """Run full pipeline: scan + features."""
    print("\n" + "="*60)
    print(" FULL PIPELINE (TEST)")
    print("="*60)
    
    d1 = cmd_scan(args)
    
    if len(d1) > 0:
        d2 = cmd_features(args)
        return d2
    
    return None


def cmd_compare(args):
    """Compare test outputs with production outputs."""
    import pandas as pd
    
    print("\n" + "="*60)
    print(" COMPARE TEST vs PRODUCTION")
    print("="*60)
    
    # Load files
    d1_test_path = Path('data/ml/d1_test.parquet')
    d1_prod_path = Path('data/ml/d1.parquet')
    
    if not d1_test_path.exists():
        print("✗ d1_test.parquet not found. Run 'scan' first.")
        return
    
    d1_test = pd.read_parquet(d1_test_path)
    
    print(f"\nD1 Test: {len(d1_test)} trades")
    
    if d1_prod_path.exists():
        d1_prod = pd.read_parquet(d1_prod_path)
        print(f"D1 Prod: {len(d1_prod)} trades")
        
        # Check if test is subset of prod
        test_keys = set(zip(d1_test['ticker'], d1_test['date'].astype(str)))
        prod_keys = set(zip(d1_prod['ticker'], d1_prod['date'].astype(str)))
        
        only_in_test = test_keys - prod_keys
        only_in_prod = prod_keys - test_keys
        common = test_keys & prod_keys
        
        print(f"\nComparison:")
        print(f"  Common trades: {len(common)}")
        print(f"  Only in Test (new with strict C9): {len(only_in_test)}")
        print(f"  Only in Prod (filtered by strict C9): {len(only_in_prod)}")
        
        if len(only_in_prod) > 0:
            print(f"\n  → Strict C9 filtered out {len(only_in_prod)} trades ({len(only_in_prod)/len(d1_prod)*100:.1f}%)")
    else:
        print("D1 Prod: (not found)")


def main():
    parser = argparse.ArgumentParser(
        description="Model Runner Test - Optimized D1/D2 Generation",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Scan command
    scan_parser = subparsers.add_parser('scan', help='Generate D1 (trade candidates)')
    scan_parser.add_argument('--start-date', required=True, help='Start date (YYYY-MM-DD)')
    scan_parser.add_argument('--end-date', required=True, help='End date (YYYY-MM-DD)')
    scan_parser.add_argument('--threshold', type=float, default=15.0, help='Success threshold %%')
    scan_parser.set_defaults(func=cmd_scan)
    
    # Features command
    feat_parser = subparsers.add_parser('features', help='Generate D2 (feature enrichment)')
    feat_parser.add_argument('--n-jobs', type=int, default=-1, help='Parallel workers')
    feat_parser.add_argument('--no-m03', action='store_true', help='Skip M03 features')
    feat_parser.add_argument('--no-preprocess', action='store_true', help='Skip preprocessing')
    feat_parser.set_defaults(func=cmd_features)
    
    # Full command
    full_parser = subparsers.add_parser('full', help='Run full pipeline (scan + features)')
    full_parser.add_argument('--start-date', required=True, help='Start date (YYYY-MM-DD)')
    full_parser.add_argument('--end-date', required=True, help='End date (YYYY-MM-DD)')
    full_parser.add_argument('--threshold', type=float, default=15.0, help='Success threshold %%')
    full_parser.add_argument('--n-jobs', type=int, default=-1, help='Parallel workers')
    full_parser.add_argument('--no-m03', action='store_true', help='Skip M03 features')
    full_parser.add_argument('--no-preprocess', action='store_true', help='Skip preprocessing')
    full_parser.set_defaults(func=cmd_full)
    
    # Compare command
    comp_parser = subparsers.add_parser('compare', help='Compare test vs production outputs')
    comp_parser.set_defaults(func=cmd_compare)
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        return
    
    # Run command
    args.func(args)


if __name__ == '__main__':
    main()
