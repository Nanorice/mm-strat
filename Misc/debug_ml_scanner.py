"""
Debug ML Scanner Integration

This script helps diagnose why ML scores aren't being populated in the database.
It tests each step of the ML scoring pipeline.
"""

import pandas as pd
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

from src.data_engine import DataRepository
from src.strategy import SEPAStrategy
from src.features import FeatureEngineer
from src.fundamental_merger import FundamentalMerger
from src.ml_scorer import MLScorer
import numpy as np

print("=" * 80)
print(" ML SCANNER INTEGRATION DEBUGGER")
print("=" * 80)

# Configuration
scan_date = '2025-11-28'
model_path = 'models/model_fold_1.json'
ml_threshold = 0.6

print(f"\nConfiguration:")
print(f"  Scan date: {scan_date}")
print(f"  Model path: {model_path}")
print(f"  ML threshold: {ml_threshold}")

# Step 1: Check model existence
print(f"\n[1/7] Checking model files...")
model_file = Path(model_path)
# Use correct naming pattern: model_fold_1.json -> model_metadata_fold_1.json
model_stem = model_file.stem
if 'fold' in model_stem:
    metadata_name = model_stem.replace('model_fold_', 'model_metadata_fold_') + '.json'
else:
    metadata_name = model_stem.replace('model', 'model_metadata') + '.json'
metadata_file = model_file.parent / metadata_name

if model_file.exists():
    print(f"  [OK] Model file exists: {model_file}")
else:
    print(f"  [ERROR] Model file NOT found: {model_file}")
    sys.exit(1)

if metadata_file.exists():
    print(f"  [OK] Metadata file exists: {metadata_file}")
else:
    print(f"  [ERROR] Metadata file NOT found: {metadata_file}")
    sys.exit(1)

# Step 2: Load ML model
print(f"\n[2/7] Loading ML model...")
try:
    ml_scorer = MLScorer(model_path=model_path, log_predictions=False)
    print(f"  [OK] Model loaded successfully")
    print(f"     Model version: {ml_scorer.model_version}")
    print(f"     Features required: {len(ml_scorer.feature_names)}")
    print(f"     Sample features: {ml_scorer.feature_names[:5]}")
except Exception as e:
    print(f"  [ERROR] Model loading failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Step 3: Initialize scanner components
print(f"\n[3/7] Initializing scanner components...")
data_repo = DataRepository()
benchmark_data = data_repo.get_benchmark_data()
feature_engine = FeatureEngineer(benchmark_data=benchmark_data)
strategy = SEPAStrategy(benchmark_data=benchmark_data)
fund_merger = FundamentalMerger()
print(f"  [OK] Components initialized")

# Step 4: Get a sample ticker with SEPA signal
print(f"\n[4/7] Finding SEPA signals for {scan_date}...")

# Load universe (just use a small subset for testing)
test_tickers = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'AMD', 'NFLX', 'CRM']
print(f"  Testing with {len(test_tickers)} tickers")

# Update cache
print(f"  Updating cache...")
data_repo.update_cache(test_tickers, force=False, source='yf')

# Load data
ticker_data = data_repo.get_batch_data(test_tickers)
valid_ticker_data = {
    ticker: df for ticker, df in ticker_data.items()
    if df is not None and len(df) >= 200
}
print(f"  Loaded {len(valid_ticker_data)} tickers with sufficient data")

# Calculate features
print(f"  Calculating features...")
enriched_data = feature_engine.process_universe_batch(valid_ticker_data)
print(f"  Features calculated for {len(enriched_data)} tickers")

# Scan for SEPA signals
print(f"  Scanning for SEPA signals...")
scan_date_obj = pd.Timestamp(scan_date)
results = strategy.batch_scan_universe(enriched_data, scan_date=scan_date_obj)

new_triggers = results['new_triggers']
print(f"  Found {len(new_triggers)} new SEPA triggers")

if len(new_triggers) == 0:
    print(f"\n  [WARN]  No SEPA signals found. Cannot test ML scoring.")
    print(f"     Try a different date or tickers with active signals.")
    sys.exit(0)

# Show first trigger
print(f"\n  Sample trigger:")
trigger = new_triggers[0]
for key, value in trigger.items():
    print(f"    {key}: {value}")

# Step 5: Prepare features for ML scoring
print(f"\n[5/7] Preparing features for ML scoring...")
ml_candidates = []

for trigger in new_triggers:
    ticker = trigger['ticker']
    ticker_df = enriched_data.get(ticker)

    if ticker_df is None or len(ticker_df) == 0:
        print(f"  [WARN]  No enriched data for {ticker}")
        continue

    # Get row at scan_date
    if scan_date_obj in ticker_df.index:
        row_date = scan_date_obj
        row = ticker_df.loc[scan_date_obj]
    else:
        available_dates = ticker_df.index[ticker_df.index <= scan_date_obj]
        if len(available_dates) > 0:
            row_date = available_dates[-1]
            row = ticker_df.loc[row_date]
        else:
            print(f"  [WARN]  No data before scan_date for {ticker}")
            continue

    # Get fundamental data using FundamentalMerger
    single_date_df = pd.DataFrame({
        'Date': [row_date],
        'Close': [row.get('Close', np.nan)]
    }).set_index('Date')

    try:
        merged_df = fund_merger.merge_ticker_data(ticker, single_date_df)
        fund_cols = [c for c in merged_df.columns if c not in ['Date', 'Close', 'Open', 'High', 'Low', 'Volume', 'Adj Close']]
        fund_data = merged_df[fund_cols].iloc[0] if len(merged_df) > 0 else None

        if fund_data is not None:
            print(f"  [OK] Fundamental data found for {ticker}: {len(fund_cols)} columns")
        else:
            print(f"  [WARN]  No fundamental data for {ticker}")
    except Exception as e:
        print(f"  [WARN]  Failed to get fundamentals for {ticker}: {e}")
        fund_data = None

    # Merge features
    candidate_features = {
        'ticker': ticker,
        'date': scan_date_obj,
        **row.to_dict(),
    }

    if fund_data is not None:
        candidate_features.update(fund_data.to_dict())

    ml_candidates.append(candidate_features)

if len(ml_candidates) == 0:
    print(f"\n  [ERROR] No candidates prepared for ML scoring!")
    print(f"     All candidates missing either technical or fundamental data.")
    sys.exit(1)

print(f"\n  [OK] Prepared {len(ml_candidates)} candidates for ML scoring")

candidates_df = pd.DataFrame(ml_candidates)
print(f"\n  Candidates DataFrame:")
print(f"    Shape: {candidates_df.shape}")
print(f"    Columns: {list(candidates_df.columns)[:10]}...")
print(f"    Tickers: {candidates_df['ticker'].tolist()}")

# Step 6: Score with ML model
print(f"\n[6/7] Scoring candidates with ML model...")
try:
    probabilities, ranks = ml_scorer.score_batch(
        candidates_df,
        ticker_column='ticker',
        date_column='date'
    )

    print(f"  [OK] ML scoring successful!")
    print(f"\n  Probabilities: {probabilities}")
    print(f"  Ranks: {ranks}")

    # Show results
    print(f"\n  Results:")
    for i, ticker in enumerate(candidates_df['ticker']):
        print(f"    {ticker}: prob={probabilities[i]:.3f}, rank={ranks[i]}")

except Exception as e:
    print(f"  [ERROR] ML scoring failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Step 7: Filter by threshold
print(f"\n[7/7] Filtering by threshold ({ml_threshold})...")
filtered_df = ml_scorer.filter_by_threshold(
    candidates_df,
    probabilities,
    ranks,
    threshold=ml_threshold
)

print(f"  Threshold filter: {len(candidates_df)} → {len(filtered_df)} candidates")

if len(filtered_df) == 0:
    print(f"\n  [WARN]  WARNING: All candidates filtered out by threshold!")
    print(f"     This means no signals will have ML scores in the database.")
    print(f"\n  Suggestions:")
    print(f"    1. Lower the threshold (current: {ml_threshold})")
    print(f"    2. Check if model is predicting reasonable probabilities")
    print(f"    3. Review model calibration")
else:
    print(f"\n  [OK] {len(filtered_df)} candidates passed threshold filter")
    print(f"\n  Filtered candidates:")
    for _, row in filtered_df.iterrows():
        print(f"    {row['ticker']}: prob={row['ml_probability']:.3f}, rank={row['ml_rank']}")

# Summary
print(f"\n" + "=" * 80)
print(" DIAGNOSIS SUMMARY")
print("=" * 80)

if len(filtered_df) > 0:
    print(f"\n[OK] ML scoring pipeline is working correctly!")
    print(f"   {len(filtered_df)}/{len(new_triggers)} SEPA signals passed ML filter")
    print(f"\n   If scanner database shows NaN values, check:")
    print(f"   1. Are you running scanner with --use-ml flag?")
    print(f"   2. Is the scan_date producing any SEPA signals?")
    print(f"   3. Check scanner logs for ML scoring section")
else:
    print(f"\n[WARN]  ML scoring works, but all signals filtered out!")
    print(f"   Probability range: {probabilities.min():.3f} - {probabilities.max():.3f}")
    print(f"   Threshold: {ml_threshold}")
    print(f"\n   Solutions:")
    print(f"   1. Lower threshold: python optimized_scanner.py --use-ml --ml-threshold 0.5")
    print(f"   2. Review model calibration (may be predicting too conservatively)")

print(f"\n" + "=" * 80)
