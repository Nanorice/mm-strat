"""
Simple wrapper to run fundamental data quality check without emoji encoding issues.
"""
import sys
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent))

import config
from data_health_analyzer import DataHealthAnalyzer

def main():
    """Run only the fundamental quality analysis."""
    print("=" * 80)
    print(" FUNDAMENTAL DATA QUALITY CHECK")
    print("=" * 80)
    print()

    analyzer = DataHealthAnalyzer()

    # Get price universe
    print("Loading price universe...")
    price_files = list(analyzer.price_dir.glob('*.parquet'))

    # For demo, use tickers that pass 200-bar filter
    import pandas as pd
    passed_tickers = []

    print(f"Checking {len(price_files)} tickers for 200-bar filter...")
    for price_file in price_files:
        try:
            df = pd.read_parquet(price_file)
            if df is not None and len(df) >= 200:
                passed_tickers.append(price_file.stem)
        except:
            pass

    print(f"Found {len(passed_tickers)} tickers passing 200-bar filter\n")

    # Run detailed fundamental quality check
    results = analyzer.analyze_fundamental_data_quality(passed_tickers)

    print("\n" + "=" * 80)
    print(" ANALYSIS COMPLETE")
    print("=" * 80)

    return results

if __name__ == "__main__":
    results = main()
