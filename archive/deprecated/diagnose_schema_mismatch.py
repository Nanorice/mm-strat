"""
Diagnose schema mismatches in parallel processing.

Checks why different tickers produce different schemas.
"""

import pandas as pd
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

from build_dataset_a import _process_ticker_for_dataset_a
from src.data_engine import DataRepository
from src.utils import filter_etfs

print("="*80)
print(" SCHEMA MISMATCH DIAGNOSIS")
print("="*80)

# Get sample tickers
data_repo = DataRepository()
all_tickers = data_repo.update_universe()
all_tickers = filter_etfs(all_tickers)

# Load benchmark data
benchmark_data = data_repo.get_benchmark_data()

# Process first 10 tickers and check their schemas
sample_tickers = all_tickers[:10]

print(f"\nProcessing {len(sample_tickers)} sample tickers...")
print(f"Date range: 2025-01-01 to 2025-01-10\n")

schemas = {}
for ticker in sample_tickers:
    # Load ticker data
    df = data_repo.get_ticker_data(ticker, use_cache=True)
    if df is None or df.empty:
        print(f"{ticker}: No data")
        continue

    # Process
    result = _process_ticker_for_dataset_a(
        ticker=ticker,
        df=df,
        mode='lightweight',
        benchmark_data=benchmark_data,
        include_fundamentals=True,
        skip_data_updates=True,
        start_date='2025-01-01',
        end_date='2025-01-10'
    )

    if not result.empty:
        schemas[ticker] = set(result.columns)
        print(f"{ticker}: {len(result.columns)} columns, {len(result)} rows")
    else:
        print(f"{ticker}: Empty result")

print("\n" + "="*80)
print("SCHEMA COMPARISON")
print("="*80)

if len(schemas) > 1:
    # Find common and unique columns
    all_columns = set()
    for cols in schemas.values():
        all_columns.update(cols)

    # Check which columns are missing from which tickers
    print(f"\nTotal unique columns across all tickers: {len(all_columns)}")

    # Find columns that are NOT in all tickers
    tickers_list = list(schemas.keys())
    reference_ticker = tickers_list[0]
    reference_cols = schemas[reference_ticker]

    print(f"\nReference ticker: {reference_ticker} ({len(reference_cols)} columns)")

    for ticker in tickers_list[1:]:
        ticker_cols = schemas[ticker]
        missing = reference_cols - ticker_cols
        extra = ticker_cols - reference_cols

        if missing or extra:
            print(f"\n{ticker}:")
            if missing:
                print(f"  Missing (vs {reference_ticker}): {sorted(missing)[:10]}{'...' if len(missing) > 10 else ''}")
                print(f"  Total missing: {len(missing)} columns")
            if extra:
                print(f"  Extra (vs {reference_ticker}): {sorted(extra)[:10]}{'...' if len(extra) > 10 else ''}")
                print(f"  Total extra: {len(extra)} columns")
        else:
            print(f"{ticker}: Identical schema")

    # Find columns that vary
    varying_columns = []
    for col in all_columns:
        present_in = sum(1 for schema_cols in schemas.values() if col in schema_cols)
        if present_in != len(schemas):
            varying_columns.append((col, present_in))

    if varying_columns:
        print(f"\n" + "="*80)
        print(f"VARYING COLUMNS ({len(varying_columns)} columns not present in all tickers):")
        print("="*80)
        varying_columns.sort(key=lambda x: x[1])

        print(f"\nMost variable columns (present in fewer tickers):")
        for col, count in varying_columns[:20]:
            print(f"  {col}: present in {count}/{len(schemas)} tickers")
else:
    print("\nNot enough tickers with data to compare schemas")

print("\n" + "="*80)
