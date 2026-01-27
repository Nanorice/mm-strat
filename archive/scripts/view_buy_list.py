"""
Buy List Viewer - Shows current active buy signals with ML ranking
Supports viewing in terminal and exporting to CSV

Usage:
    python scripts/view_buy_list.py                      # View in terminal
    python scripts/view_buy_list.py --show-features      # View with ML features displayed
    python scripts/view_buy_list.py --csv                # Export to CSV (default: buy_list_export.csv)
    python scripts/view_buy_list.py --export-csv out.csv # Export with features as columns
"""
import sys
from pathlib import Path
import pandas as pd
import argparse

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.database import DatabaseManager
import sqlite3

def get_buy_list_activity(db: DatabaseManager, limit: int = 10) -> pd.DataFrame:
    """
    Query buy_list_activity table directly since there's no dedicated method.
    
    Args:
        db: DatabaseManager instance
        limit: Number of recent events to return
    
    Returns:
        DataFrame of recent activity
    """
    conn = sqlite3.connect(db.db_path)
    # Only select core columns that are guaranteed to exist
    query = """
        SELECT ticker, action, action_date, reason, entry_price
        FROM buy_list_activity
        ORDER BY created_at DESC
        LIMIT ?
    """
    df = pd.read_sql_query(query, conn, params=(limit,))
    conn.close()
    return df


def view_buy_list(export_csv: bool = False, csv_path: str = None, show_features: bool = False, export_csv_with_features: bool = False):
    """Main function to view or export buy list.
    
    Args:
        export_csv: Quick CSV export (legacy --csv flag)
        csv_path: Path for CSV export
        show_features: Display key ML features in terminal
        export_csv_with_features: Export with features expanded to columns
    """
    db = DatabaseManager()
    
    # Get active buy list
    active = db.get_buy_list(active_only=True)
    
    if active.empty:
        print("\nNo active buy signals in database.\n")
        return
    
    # Calculate days on list
    active['days_on_list'] = (pd.Timestamp.now() - pd.to_datetime(active['signal_date'])).dt.days
    
    # Calculate price change
    if 'signal_price' in active.columns and 'current_price' in active.columns:
        active['price_change_%'] = ((active['current_price'] - active['signal_price']) / 
                                    active['signal_price'] * 100)
    
    # Sort by ML rank (1=best)
    if 'ml_rank' in active.columns:
        active = active.sort_values('ml_rank', na_position='last')
    
    # CSV export mode
    if export_csv or export_csv_with_features:
        output_path = csv_path or 'buy_list_export.csv'
        
        if export_csv_with_features and 'ml_features' in active.columns:
            # Expand features to separate columns
            features_expanded = []
            for idx, row in active.iterrows():
                row_dict = row.to_dict()
                features = row.get('ml_features')
                if features and isinstance(features, dict):
                    # Add feature values as separate columns with 'feat_' prefix
                    for feat_name, feat_value in features.items():
                        row_dict[f'feat_{feat_name}'] = feat_value
                # Remove the ml_features JSON column from export (redundant now)
                row_dict.pop('ml_features', None)
                features_expanded.append(row_dict)
            
            export_df = pd.DataFrame(features_expanded)
            export_df.to_csv(output_path, index=False)
            
            feature_cols = [c for c in export_df.columns if c.startswith('feat_')]
            print(f"\n✅ Exported {len(active)} buy signals to: {output_path}")
            print(f"   Features expanded: {len(feature_cols)} feature columns")
            print(f"   Total columns: {len(export_df.columns)}\n")
        else:
            # Standard CSV export
            active.to_csv(output_path, index=False)
            print(f"\n✅ Exported {len(active)} buy signals to: {output_path}\n")
        return
    
    # Terminal display mode
    print("\n" + "=" * 100)
    print(f" ACTIVE BUY LIST | {len(active)} signals".center(100))
    print("=" * 100 + "\n")
    
    # Display columns optimized for ML scanner output
    display_cols = [
        'ml_rank', 'ticker', 'signal_date', 'days_on_list',
        'ml_probability', 'signal_price', 'current_price', 'price_change_%',
        'rs', 'volume_ratio', 'last_updated'
    ]
    available_cols = [col for col in display_cols if col in active.columns]
    
    # Format for display
    display_df = active[available_cols].copy()
    
    # Round numeric columns for display
    numeric_formats = {
        'signal_price': 2,
        'current_price': 2,
        'price_change_%': 1,
        'ml_probability': 3,
        'rs': 3,
        'volume_ratio': 2
    }
    
    for col, decimals in numeric_formats.items():
        if col in display_df.columns:
            display_df[col] = pd.to_numeric(display_df[col], errors='coerce').round(decimals)
    
    print(display_df.to_string(index=False))
    
    # Summary stats
    print("\n" + "=" * 100)
    print("SUMMARY STATISTICS")
    print("=" * 100)
    print(f"Total signals: {len(active)}")
    print(f"Average days on list: {active['days_on_list'].mean():.1f}")
    
    if 'ml_probability' in active.columns:
        ml_prob = active['ml_probability'].dropna()
        if len(ml_prob) > 0:
            print(f"Average ML probability: {ml_prob.mean():.3f}")
            print(f"ML probability range: {ml_prob.min():.3f} - {ml_prob.max():.3f}")
    
    if 'price_change_%' in active.columns:
        price_changes = active['price_change_%'].dropna()
        if len(price_changes) > 0:
            avg_change = price_changes.mean()
            print(f"Average price change: {avg_change:+.2f}%")
            winners = len(price_changes[price_changes > 0])
            print(f"Winners: {winners}/{len(active)} ({winners/len(active)*100:.1f}%)")
    
    # Recent activity
    print("\n" + "=" * 100)
    print("RECENT ACTIVITY (Last 10 Events)")
    print("=" * 100)
    
    activity = get_buy_list_activity(db, limit=10)
    if not activity.empty:
        # Format activity display
        activity_cols = ['ticker', 'action', 'action_date', 'reason', 'entry_price']
        available_activity_cols = [col for col in activity_cols if col in activity.columns]
        print(activity[available_activity_cols].to_string(index=False))
    else:
        print("No activity recorded")
    
    print("\n" + "=" * 100)
    print(f"Database: {db.db_path}")
    print("=" * 100 + "\n")
    
    # Show ML features if requested
    if show_features and 'ml_features' in active.columns:
        print("\n" + "=" * 100)
        print("ML FEATURES (Top Features)")
        print("=" * 100)
        
        # Define key features to display
        key_features = [
            'RSI_14', 'RS', 'VCP_Ratio', 'SMA_50_Slope', 'Dist_From_52W_High',
            'revenueGrowth_1y', 'epsGrowth_1y', 'roic',
            'alpha001_rank', 'alpha006_rank'
        ]
        
        # Display features for each ticker
        for idx, row in active.iterrows():
            features = row.get('ml_features')
            if features and isinstance(features, dict):
                print(f"\n{row['ticker']}:")
                displayed = 0
                for feature_name in key_features:
                    if feature_name in features:
                        value = features[feature_name]
                        if value is not None:
                            print(f"  {feature_name}: {value:.3f}" if isinstance(value, (int, float)) else f"  {feature_name}: {value}")
                            displayed += 1
                
                # Show total feature count
                print(f"  (Total features: {len(features)})")
        
        print("\n" + "=" * 100 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description='View or export buy list from database',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/view_buy_list.py                        # View in terminal
  python scripts/view_buy_list.py --show-features        # View with ML features
  python scripts/view_buy_list.py --csv                  # Quick CSV export
  python scripts/view_buy_list.py --export-csv out.csv   # Export with features as columns
        """
    )
    parser.add_argument('--csv', nargs='?', const='buy_list_export.csv', 
                       help='Quick export to CSV (optional: specify filename)')
    parser.add_argument('--show-features', action='store_true',
                       help='Display ML features for each ticker in terminal')
    parser.add_argument('--export-csv', type=str, metavar='FILENAME',
                       help='Export to CSV with ML features expanded to columns')
    
    args = parser.parse_args()
    
    if args.export_csv:
        view_buy_list(export_csv_with_features=True, csv_path=args.export_csv)
    elif args.csv:
        view_buy_list(export_csv=True, csv_path=args.csv)
    else:
        view_buy_list(export_csv=False, show_features=args.show_features)


if __name__ == "__main__":
    main()
