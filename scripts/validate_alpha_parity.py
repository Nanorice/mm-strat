"""
Alpha Parity Validation Script
================================
Compare Python-computed alpha factors vs SQL-computed alpha factors.

Purpose:
- Validate that SQL migration preserved alpha factor logic
- Measure correlation and max absolute difference
- Document VWAP-driven divergence

Usage:
    python scripts/validate_alpha_parity.py --tickers AAPL,NVDA,MSFT,TSLA,GOOGL
    python scripts/validate_alpha_parity.py --sample 10
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
import duckdb
import argparse
from datetime import datetime, timedelta

import config
from src.alpha_factors import AlphaEngine
from src.data_loader_duckdb import DuckDBDataLoader

# Database path
DB_PATH = Path(__file__).parent.parent / "data" / "market_data.duckdb"


def load_sql_alphas(tickers: list, end_date: str = None) -> pd.DataFrame:
    """
    Load SQL-computed alpha factors from daily_features table.

    Args:
        tickers: List of tickers to load
        end_date: End date (YYYY-MM-DD), defaults to latest

    Returns:
        DataFrame with columns: ticker, date, alpha001, alpha002, ...
    """
    con = duckdb.connect(str(DB_PATH))

    if end_date is None:
        end_date = con.execute("SELECT MAX(date) FROM daily_features").fetchone()[0]

    # Get last 252 trading days
    start_date = con.execute("""
        SELECT MIN(date) FROM (
            SELECT DISTINCT date
            FROM daily_features
            WHERE date <= ?
            ORDER BY date DESC
            LIMIT 252
        )
    """, [end_date]).fetchone()[0]

    # Get target alphas from AlphaEngine
    engine = AlphaEngine()
    target_alphas = engine.get_alpha_names()
    alpha_cols = ", ".join(target_alphas)

    ticker_list = "', '".join(tickers)
    query = f"""
        SELECT
            ticker,
            date,
            {alpha_cols}
        FROM daily_features
        WHERE ticker IN ('{ticker_list}')
          AND date >= '{start_date}'
          AND date <= '{end_date}'
        ORDER BY ticker, date
    """

    df = con.execute(query).df()
    con.close()

    return df


def compute_python_alphas(tickers: list, end_date: str = None) -> pd.DataFrame:
    """
    Compute alpha factors using legacy Python AlphaEngine.

    Args:
        tickers: List of tickers to compute
        end_date: End date (YYYY-MM-DD), defaults to latest

    Returns:
        DataFrame with columns: ticker, date, alpha001_py, alpha002_py, ...
    """
    loader = DuckDBDataLoader()
    engine = AlphaEngine()

    # Load price data for all tickers
    price_data = loader.get_price_data_batch(
        tickers,
        end_date=end_date,
        include_features=False  # Don't need pre-computed features
    )

    results = []

    for ticker in tickers:
        ticker_df = price_data.get(ticker)
        if ticker_df is None or len(ticker_df) < 252:
            print(f"[WARN] {ticker}: Insufficient data ({len(ticker_df) if ticker_df is not None else 0} rows)")
            continue

        # Compute alphas using Python
        try:
            # Ensure columns are TitleCase for AlphaEngine
            ticker_df = ticker_df.rename(columns={
                'open': 'Open', 'high': 'High', 'low': 'Low', 
                'close': 'Close', 'volume': 'Volume'
            })
            
            alphas_df = engine.calculate_alphas(ticker_df)
            alphas_df['ticker'] = ticker
            alphas_df['date'] = alphas_df.index
            alphas_df = alphas_df.reset_index(drop=True)

            # Rename columns to alpha001_py, alpha002_py, ...
            alpha_cols = [col for col in alphas_df.columns if col.startswith('alpha')]
            rename_map = {col: f"{col}_py" for col in alpha_cols}
            alphas_df = alphas_df.rename(columns=rename_map)

            results.append(alphas_df)
        except Exception as e:
            print(f"[ERROR] {ticker}: Alpha computation failed: {e}")
            continue

    if not results:
        return pd.DataFrame()

    return pd.concat(results, ignore_index=True)


def compare_alphas(sql_df: pd.DataFrame, python_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compare SQL vs Python alpha factors.

    Args:
        sql_df: SQL-computed alphas (alpha001, alpha002, ...)
        python_df: Python-computed alphas (alpha001_py, alpha002_py, ...)

    Returns:
        DataFrame with comparison metrics per alpha factor
    """
    # Merge on ticker + date
    merged = pd.merge(
        sql_df,
        python_df,
        on=['ticker', 'date'],
        how='inner'
    )

    print(f"\n[INFO] Merged {len(merged)} rows for comparison")

    # Alpha columns
    engine = AlphaEngine()
    alpha_names = engine.get_alpha_names()
    
    results = []

    for alpha_col in alpha_names:
        sql_col = alpha_col
        py_col = f"{alpha_col}_py"

        if sql_col not in merged.columns or py_col not in merged.columns:
            continue

        # Filter to rows with non-null values in both
        valid_mask = merged[sql_col].notna() & merged[py_col].notna()
        valid_data = merged[valid_mask]

        if len(valid_data) == 0:
            print(f"[WARN] {sql_col}: No valid overlap rows")
            continue

        sql_vals = valid_data[sql_col].values
        py_vals = valid_data[py_col].values

        # Compute metrics
        correlation = np.corrcoef(sql_vals, py_vals)[0, 1]
        mae = np.mean(np.abs(sql_vals - py_vals))
        max_diff = np.max(np.abs(sql_vals - py_vals))
        rmse = np.sqrt(np.mean((sql_vals - py_vals) ** 2))

        # Percent of rows with exact match (within 1e-6)
        exact_matches = np.sum(np.abs(sql_vals - py_vals) < 1e-6)
        exact_match_pct = exact_matches / len(valid_data) * 100

        results.append({
            'alpha': sql_col,
            'valid_rows': len(valid_data),
            'correlation': correlation,
            'mae': mae,
            'max_diff': max_diff,
            'rmse': rmse,
            'exact_match_pct': exact_match_pct
        })

    return pd.DataFrame(results)


def print_comparison_report(comparison_df: pd.DataFrame):
    """Print human-readable comparison report."""
    print("\n" + "=" * 80)
    print("ALPHA PARITY VALIDATION REPORT")
    print("=" * 80)
    print(f"\nTotal Alphas Compared: {len(comparison_df)}")

    if comparison_df.empty:
        print("\n[WARN] No comparisons generated.")
        print("=" * 80)
        return

    print("\n" + "-" * 80)
    print(f"{'Alpha':<10} {'Valid Rows':<12} {'Correlation':<12} {'MAE':<12} {'Max Diff':<12} {'RMSE':<12}")
    print("-" * 80)

    for _, row in comparison_df.iterrows():
        print(f"{row['alpha']:<10} {row['valid_rows']:<12} "
              f"{row['correlation']:<12.4f} {row['mae']:<12.4f} "
              f"{row['max_diff']:<12.4f} {row['rmse']:<12.4f}")

    print("-" * 80)

    # Summary statistics
    avg_corr = comparison_df['correlation'].mean()
    min_corr = comparison_df['correlation'].min()
    avg_mae = comparison_df['mae'].mean()
    max_diff_overall = comparison_df['max_diff'].max()

    print(f"\nSUMMARY:")
    print(f"  Average Correlation: {avg_corr:.4f}")
    print(f"  Min Correlation:     {min_corr:.4f}")
    print(f"  Average MAE:         {avg_mae:.4f}")
    print(f"  Max Diff Overall:    {max_diff_overall:.4f}")

    # Flag concerning alphas (correlation < 0.95)
    low_corr = comparison_df[comparison_df['correlation'] < 0.95]
    if len(low_corr) > 0:
        print(f"\n[WARN] {len(low_corr)} alpha(s) with correlation < 0.95:")
        for _, row in low_corr.iterrows():
            print(f"  {row['alpha']}: corr={row['correlation']:.4f}, mae={row['mae']:.4f}")
    else:
        print("\n[OK] All alphas have correlation >= 0.95")

    print("\n" + "=" * 80)
    print("\nNOTES:")
    print("- VWAP formula changed: Python used avg_price/100, SQL uses (H+L+C)/3")
    print("- Correlation should be high (>0.95) but not perfect due to VWAP difference")
    print("- Alphas are ranked/normalized, so direction matters more than absolute values")
    print("=" * 80 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Validate alpha factor parity between Python and SQL implementations"
    )
    parser.add_argument(
        '--tickers',
        type=str,
        help="Comma-separated ticker list (e.g., AAPL,NVDA,MSFT)"
    )
    parser.add_argument(
        '--sample',
        type=int,
        help="Randomly sample N tickers from universe"
    )
    parser.add_argument(
        '--end-date',
        type=str,
        help="End date for comparison (YYYY-MM-DD), defaults to latest"
    )
    parser.add_argument(
        '--export-csv',
        action='store_true',
        help="Export detailed comparison to CSV"
    )

    args = parser.parse_args()

    # Determine tickers to test
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(',')]
    elif args.sample:
        # Sample N tickers from universe
        con = duckdb.connect(str(DB_PATH))
        tickers = con.execute(f"""
            SELECT DISTINCT ticker
            FROM daily_features
            WHERE date = (SELECT MAX(date) FROM daily_features)
            ORDER BY RANDOM()
            LIMIT {args.sample}
        """).df()['ticker'].tolist()
        con.close()
        print(f"[INFO] Sampled {len(tickers)} random tickers: {', '.join(tickers[:5])}...")
    else:
        # Default test tickers
        tickers = ['AAPL', 'NVDA', 'MSFT', 'TSLA', 'GOOGL']
        print(f"[INFO] Using default test tickers: {', '.join(tickers)}")

    # Load SQL alphas
    print("\n[1/3] Loading SQL-computed alphas from daily_features...")
    sql_df = load_sql_alphas(tickers, end_date=args.end_date)
    print(f"       Loaded {len(sql_df)} rows for {len(sql_df['ticker'].unique())} tickers")

    # Compute Python alphas
    print("\n[2/3] Computing Python alphas using AlphaEngine...")
    python_df = compute_python_alphas(tickers, end_date=args.end_date)
    
    if python_df.empty:
        print("\n[ERROR] No Python alphas computed (insufficient data for all sampled tickers).")
        return

    print(f"       Computed {len(python_df)} rows for {len(python_df['ticker'].unique())} tickers")

    # Compare
    print("\n[3/3] Comparing SQL vs Python alphas...")
    comparison_df = compare_alphas(sql_df, python_df)

    # Print report
    print_comparison_report(comparison_df)

    # Export CSV if requested
    if args.export_csv:
        output_file = f"alpha_parity_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        comparison_df.to_csv(output_file, index=False)
        print(f"\n[INFO] Detailed comparison exported to: {output_file}")


if __name__ == "__main__":
    main()
