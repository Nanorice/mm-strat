"""
Retroactive ML Ranking Script
Rank existing buy_list with ML scores without re-scanning.

This script:
1. Reads the current buy_list from the database
2. Loads cached price/fundamental data for those tickers
3. Calculates features (already available in enriched data)
4. Scores with ML model
5. Updates buy_list with ml_probability and ml_rank

Usage:
    # Rank current buy list
    python rank_buy_list.py

    # Use specific model
    python rank_buy_list.py --model-path models/production_model.json

    # Dry run (show scores without saving)
    python rank_buy_list.py --dry-run
"""

import pandas as pd
import numpy as np
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
import logging

# Add src to path
sys.path.append(str(Path(__file__).parent))

import config
from src.database import DatabaseManager
from src.data_engine import DataRepository
from src.features import FeatureEngineer
from src.ml_scorer import MLScorer
from src.fundamental_merger import FundamentalMerger

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_ml_scorer(model_path: str):
    """Load ML scorer with error handling."""
    try:
        ml_scorer = MLScorer(model_path=model_path, log_predictions=False)
        logger.info(f"Loaded ML model: {model_path}")
        logger.info(f"  Model version: {ml_scorer.model_version}")
        logger.info(f"  Features required: {len(ml_scorer.feature_names)}")
        return ml_scorer
    except FileNotFoundError as e:
        logger.error(f"Model file not found: {e}")
        logger.error("Please ensure the model file exists or train a new model.")
        return None
    except Exception as e:
        logger.error(f"Failed to load ML model: {e}")
        return None


def prepare_buy_list_features(db: DatabaseManager, data_repo: DataRepository):
    """
    Load buy_list tickers and prepare features for ML scoring.

    Returns:
        Tuple of (tickers, enriched_data_dict, fund_merger)
    """
    # Get active buy list
    buy_list_df = db.get_buy_list(active_only=True)

    if buy_list_df.empty:
        logger.warning("Buy list is empty, nothing to rank")
        return [], {}, None

    tickers = buy_list_df['ticker'].tolist()
    logger.info(f"Found {len(tickers)} tickers in buy list")

    # Load price data (from cache)
    logger.info("Loading price data from cache...")
    min_date = (pd.Timestamp.now() - pd.DateOffset(years=2)).strftime('%Y-%m-%d')
    ticker_data = data_repo.get_batch_data(
        tickers,
        min_date=min_date,
        check_min_date=False,
        force_cache_only=True
    )

    if not ticker_data:
        logger.error("No price data available in cache. Run daily_scanner.py first to populate cache.")
        return [], {}, None

    logger.info(f"Loaded {len(ticker_data)} tickers from cache")

    # Load benchmark
    benchmark_data = data_repo.get_benchmark_data(
        check_min_date=False,
        force_cache_only=True
    )

    if benchmark_data is None:
        logger.error("Benchmark data not available. Run daily_scanner.py first.")
        return [], {}, None

    # Calculate features
    logger.info("Calculating technical features...")
    feature_engine = FeatureEngineer(benchmark_data=benchmark_data)
    enriched_data = feature_engine.process_universe_batch(ticker_data)

    # Calculate heavyweight features (inventory, etc.)
    logger.info("Calculating heavyweight features...")
    for ticker in list(enriched_data.keys()):
        try:
            enriched_data[ticker] = feature_engine.calculate_heavyweight_features(
                enriched_data[ticker],
                ticker
            )
        except Exception as e:
            logger.warning(f"Failed to calculate heavyweight features for {ticker}: {e}")

    # Initialize fundamental merger
    fund_merger = FundamentalMerger()

    return tickers, enriched_data, fund_merger


def prepare_ml_candidates(tickers, enriched_data, fund_merger, as_of_date=None):
    """
    Prepare feature DataFrame for ML scoring.

    Args:
        tickers: List of ticker symbols
        enriched_data: Dict of ticker -> DataFrame with features
        fund_merger: FundamentalMerger instance
        as_of_date: Date to use for features (default: latest available)

    Returns:
        DataFrame ready for ML scoring
    """
    if as_of_date is None:
        as_of_date = pd.Timestamp.now()
    else:
        as_of_date = pd.Timestamp(as_of_date)

    ml_candidates = []

    for ticker in tickers:
        ticker_df = enriched_data.get(ticker)
        if ticker_df is None or len(ticker_df) == 0:
            logger.warning(f"No data for {ticker}, skipping")
            continue

        # Get row at as_of_date or latest available
        if as_of_date in ticker_df.index:
            row_date = as_of_date
            row = ticker_df.loc[as_of_date]
        else:
            available_dates = ticker_df.index[ticker_df.index <= as_of_date]
            if len(available_dates) == 0:
                logger.warning(f"No data before {as_of_date} for {ticker}, skipping")
                continue
            row_date = available_dates[-1]
            row = ticker_df.loc[row_date]

        # Get fundamental data
        single_date_df = pd.DataFrame({
            'Date': [row_date],
            'Close': [row.get('Close', np.nan)]
        }).set_index('Date')

        try:
            merged_df = fund_merger.merge_ticker_data(ticker, single_date_df)
            fund_cols = [c for c in merged_df.columns
                        if c not in ['Date', 'Close', 'Open', 'High', 'Low', 'Volume', 'Adj Close']]
            fund_data = merged_df[fund_cols].iloc[0] if len(merged_df) > 0 else None
        except Exception as e:
            logger.debug(f"Failed to load fundamentals for {ticker}: {e}")
            fund_data = None

        # Merge technical + fundamental features
        candidate_features = {
            'ticker': ticker,
            'date': row_date,
            **row.to_dict(),
        }

        if fund_data is not None:
            candidate_features.update(fund_data.to_dict())

        ml_candidates.append(candidate_features)

    return pd.DataFrame(ml_candidates) if ml_candidates else pd.DataFrame()


def score_and_rank_buy_list(db: DatabaseManager, ml_scorer: MLScorer,
                            candidates_df: pd.DataFrame, dry_run: bool = False):
    """
    Score candidates with ML and update database.

    Args:
        db: DatabaseManager instance
        ml_scorer: MLScorer instance
        candidates_df: DataFrame with features
        dry_run: If True, show results without saving to DB

    Returns:
        DataFrame with scores
    """
    if len(candidates_df) == 0:
        logger.error("No candidates to score")
        return pd.DataFrame()

    logger.info(f"Scoring {len(candidates_df)} candidates with ML model...")

    # Score with ML
    try:
        probabilities, ranks = ml_scorer.score_batch(
            candidates_df,
            ticker_column='ticker',
            date_column='date'
        )
    except Exception as e:
        logger.error(f"ML scoring failed: {e}")
        return pd.DataFrame()

    # Add scores to dataframe
    candidates_df['ml_probability'] = probabilities
    candidates_df['ml_rank'] = ranks

    # Sort by rank
    scored_df = candidates_df[['ticker', 'date', 'ml_probability', 'ml_rank']].sort_values('ml_rank')

    # Display results
    print("\n" + "="*80)
    print("ML RANKING RESULTS")
    print("="*80)
    print(scored_df.to_string(index=False))
    print("="*80)

    # Statistics
    print(f"\nStatistics:")
    print(f"  Total candidates: {len(scored_df)}")
    print(f"  Probability range: [{probabilities.min():.3f}, {probabilities.max():.3f}]")
    print(f"  Mean probability: {probabilities.mean():.3f}")
    print(f"  Median probability: {np.median(probabilities):.3f}")

    if dry_run:
        print("\n[DRY RUN] Scores calculated but not saved to database.")
        return scored_df

    # Update database using BATCH UPDATE (solves database locking)
    logger.info("Preparing batch update for database...")

    # Prepare all updates as a list of dicts
    updates = []
    for _, row in scored_df.iterrows():
        ticker = row['ticker']
        ml_prob = float(row['ml_probability'])
        ml_rank_val = int(row['ml_rank'])

        # Get features dict for storage
        candidate_row = candidates_df[candidates_df['ticker'] == ticker].iloc[0]
        features_dict = {}
        for feature_name in ml_scorer.feature_names:
            if feature_name in candidate_row.index:
                value = candidate_row[feature_name]
                if pd.isna(value):
                    features_dict[feature_name] = None
                elif isinstance(value, (np.integer, np.floating)):
                    features_dict[feature_name] = float(value)
                else:
                    features_dict[feature_name] = value

        updates.append({
            'ticker': ticker,
            'ml_probability': ml_prob,
            'ml_rank': ml_rank_val,
            'ml_model_version': ml_scorer.model_version,
            'ml_score_date': datetime.now().strftime('%Y-%m-%d'),
            'ml_features': json.dumps(features_dict)
        })

    # Execute batch update in a single transaction
    logger.info(f"Executing batch update for {len(updates)} tickers...")
    try:
        update_count = db.batch_update_ml_scores(updates)
        logger.info(f"Successfully updated {update_count}/{len(scored_df)} tickers")
        print(f"\n✅ Updated {update_count} tickers with ML scores")
    except Exception as e:
        logger.error(f"Batch update failed: {e}")
        print(f"\n❌ Update failed: {e}")

    return scored_df


def main():
    parser = argparse.ArgumentParser(description="Rank buy_list with ML scores")
    parser.add_argument(
        '--model-path',
        type=str,
        default='models/production_model.json',
        help='Path to ML model (default: models/production_model.json)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show scores without saving to database'
    )
    parser.add_argument(
        '--as-of-date',
        type=str,
        help='Date to use for features (YYYY-MM-DD), default: latest available'
    )

    args = parser.parse_args()

    print("="*80)
    print("BUY LIST ML RANKING")
    print("="*80)
    print(f"Model: {args.model_path}")
    print(f"Dry run: {args.dry_run}")
    print(f"As of date: {args.as_of_date or 'latest available'}")
    print("="*80)

    # Initialize components
    db = DatabaseManager()
    data_repo = DataRepository()

    # Load ML model
    ml_scorer = load_ml_scorer(args.model_path)
    if ml_scorer is None:
        logger.error("Cannot proceed without ML model")
        return

    # Prepare features
    tickers, enriched_data, fund_merger = prepare_buy_list_features(db, data_repo)

    if not tickers:
        logger.error("No tickers to process")
        return

    # Prepare ML candidates
    candidates_df = prepare_ml_candidates(
        tickers,
        enriched_data,
        fund_merger,
        as_of_date=args.as_of_date
    )

    if candidates_df.empty:
        logger.error("No candidates prepared for ML scoring")
        return

    # Score and rank
    scored_df = score_and_rank_buy_list(db, ml_scorer, candidates_df, dry_run=args.dry_run)

    if not args.dry_run and not scored_df.empty:
        print("\n✅ Buy list has been ranked with ML scores!")
        print("   Refresh your dashboard to see updated rankings.")


if __name__ == "__main__":
    main()
