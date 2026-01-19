"""
Diagnose Missing Snapshots in Dataset Merge
"""
import pandas as pd
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
from src.dataset_merger import DatasetLoader, SnapshotExtractor

def main():
    print("=" * 80)
    print("DIAGNOSING MISSING SNAPSHOTS")
    print("=" * 80)

    # Load datasets
    print("\nLoading Dataset A...")
    dataset_a = DatasetLoader.load_dataset_a('data/ml/dataset_a.parquet')
    print(f"  Rows: {len(dataset_a):,}")
    print(f"  Date range: {dataset_a['date'].min()} to {dataset_a['date'].max()}")
    print(f"  Unique tickers: {dataset_a['ticker'].nunique()}")
    print(f"  Unique dates: {dataset_a['date'].nunique()}")

    print("\nLoading Dataset B...")
    dataset_b = DatasetLoader.load_dataset_b('data/ml/dataset_b.parquet')
    print(f"  Total trades: {len(dataset_b):,}")
    print(f"  Entry date range: {dataset_b['entry_date'].min()} to {dataset_b['entry_date'].max()}")
    print(f"  Unique tickers: {dataset_b['ticker'].nunique()}")

    # Create extractor and analyze missing snapshots
    print("\n" + "=" * 80)
    print("ANALYZING MISSING SNAPSHOTS")
    print("=" * 80)

    extractor = SnapshotExtractor(dataset_a)

    # Check each trade manually to identify patterns
    missing_by_reason = {
        'ticker_not_in_a': [],
        'date_not_in_a': [],
        'ticker_date_not_in_a': []
    }

    a_tickers = set(dataset_a['ticker'].unique())
    a_dates = set(dataset_a['date'].dt.date.unique())

    print("\nChecking all trades...")
    missing_count = 0

    for idx, trade in dataset_b.iterrows():
        ticker = trade['ticker']
        entry_date = trade['entry_date']

        # Try to extract snapshot
        snapshot = extractor.extract_snapshot(ticker, entry_date)

        if snapshot is None:
            missing_count += 1

            # Categorize the reason
            if ticker not in a_tickers:
                missing_by_reason['ticker_not_in_a'].append({
                    'ticker': ticker,
                    'entry_date': entry_date,
                    'trade_id': trade.get('trade_id', idx)
                })
            elif entry_date.date() not in a_dates:
                missing_by_reason['date_not_in_a'].append({
                    'ticker': ticker,
                    'entry_date': entry_date,
                    'trade_id': trade.get('trade_id', idx)
                })
            else:
                missing_by_reason['ticker_date_not_in_a'].append({
                    'ticker': ticker,
                    'entry_date': entry_date,
                    'trade_id': trade.get('trade_id', idx)
                })

    # Report findings
    print(f"\n📊 Missing Snapshot Analysis:")
    print(f"  Total missing: {missing_count} / {len(dataset_b)} ({missing_count/len(dataset_b)*100:.1f}%)")
    print(f"\n  Breakdown by reason:")
    print(f"    Ticker not in Dataset A: {len(missing_by_reason['ticker_not_in_a'])}")
    print(f"    Date not in Dataset A: {len(missing_by_reason['date_not_in_a'])}")
    print(f"    Ticker+Date combo not in Dataset A: {len(missing_by_reason['ticker_date_not_in_a'])}")

    # Show examples of each
    print("\n" + "=" * 80)
    print("EXAMPLES OF MISSING SNAPSHOTS")
    print("=" * 80)

    if missing_by_reason['ticker_not_in_a']:
        print("\n❌ Tickers not in Dataset A (first 10):")
        ticker_counts = {}
        for item in missing_by_reason['ticker_not_in_a']:
            ticker = item['ticker']
            ticker_counts[ticker] = ticker_counts.get(ticker, 0) + 1

        for ticker, count in sorted(ticker_counts.items(), key=lambda x: -x[1])[:10]:
            print(f"    {ticker}: {count} trades")

    if missing_by_reason['date_not_in_a']:
        print("\n❌ Dates not in Dataset A (first 10):")
        date_counts = {}
        for item in missing_by_reason['date_not_in_a']:
            date = item['entry_date'].date()
            date_counts[date] = date_counts.get(date, 0) + 1

        for date, count in sorted(date_counts.items(), key=lambda x: -x[1])[:10]:
            print(f"    {date}: {count} trades")

    if missing_by_reason['ticker_date_not_in_a']:
        print("\n❌ Ticker+Date combos not in Dataset A (first 10):")
        for item in missing_by_reason['ticker_date_not_in_a'][:10]:
            ticker = item['ticker']
            date = item['entry_date']
            print(f"    {ticker} on {date.date()}")

            # Check if ticker exists on other dates
            if ticker in a_tickers:
                ticker_df = dataset_a[dataset_a['ticker'] == ticker]
                print(f"      (Ticker exists in Dataset A from {ticker_df['date'].min().date()} to {ticker_df['date'].max().date()})")

    # Summary and recommendations
    print("\n" + "=" * 80)
    print("RECOMMENDATIONS")
    print("=" * 80)

    if len(missing_by_reason['ticker_not_in_a']) > 0:
        print(f"\n⚠️  {len(missing_by_reason['ticker_not_in_a'])} trades have tickers not in Dataset A")
        print("    → These tickers may have been filtered out during Dataset A creation")
        print("    → Check ticker filtering logic in build_dataset_a.py")

    if len(missing_by_reason['date_not_in_a']) > 0:
        print(f"\n⚠️  {len(missing_by_reason['date_not_in_a'])} trades have dates not in Dataset A")
        print("    → These dates may be missing from the market calendar")
        print("    → Check date range and market holiday handling")

    if len(missing_by_reason['ticker_date_not_in_a']) > 0:
        print(f"\n⚠️  {len(missing_by_reason['ticker_date_not_in_a'])} trades have ticker+date combos not in Dataset A")
        print("    → The ticker exists but not on that specific date")
        print("    → This could indicate:")
        print("        - Trading halt on that date")
        print("        - Delisted ticker")
        print("        - Data quality issue in price cache")
        print("        - IPO date after entry date")

    print("\n" + "=" * 80)

if __name__ == "__main__":
    main()
