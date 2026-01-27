"""
Identify and save ETF/Fund tickers for filtering.

This script analyzes company profiles to identify ETFs and Closed-End Funds,
then saves them to a text file for easy filtering during data processing.
"""

import pandas as pd
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent))
import config


def identify_etfs_and_funds():
    """Identify ETF and fund tickers from company profiles."""

    print("="*80)
    print(" ETF/FUND IDENTIFIER")
    print("="*80)

    # Load company profiles
    profiles_path = config.COMPANY_INFO_DIR / 'company_profiles.parquet'

    if not profiles_path.exists():
        print(f"ERROR: Company profiles not found: {profiles_path}")
        return

    df = pd.read_parquet(profiles_path)
    print(f"\nLoaded {len(df)} company profiles")

    # Identify funds/trusts by company name patterns
    etf_fund_tickers = []

    fund_keywords = [
        'Trust',      # Closed-End Funds often have "Trust" in name
        'Fund',       # Mutual Funds and CEFs
        'ETF',        # Exchange-Traded Funds
        'Index',      # Index funds
    ]

    print(f"\nScanning for fund indicators: {', '.join(fund_keywords)}")
    print("Checking company names...\n")

    for ticker in df.index:
        company_name = df.loc[ticker, 'companyName']

        # Check if company name contains fund indicators
        for keyword in fund_keywords:
            if keyword in company_name:
                # Additional validation: keyword should be a separate word or at end
                # This avoids false positives like "Truist" (contains "Trust")
                if (company_name.endswith(keyword) or
                    f'{keyword} ' in company_name or
                    f' {keyword}' in company_name):
                    etf_fund_tickers.append(ticker)
                    print(f"  Found: {ticker:6s} - {company_name}")
                    break

    # Also check Asset Management industry (often CEFs)
    print(f"\nChecking Asset Management industry...")
    asset_mgmt = df[df['industry'].str.contains('Asset Management', case=False, na=False)]

    for ticker in asset_mgmt.index:
        if ticker not in etf_fund_tickers:
            company_name = asset_mgmt.loc[ticker, 'companyName']
            # Only add if name suggests it's a fund, not a company
            if any(kw in company_name for kw in fund_keywords):
                etf_fund_tickers.append(ticker)
                print(f"  Found: {ticker:6s} - {company_name}")

    # Sort and deduplicate
    etf_fund_tickers = sorted(set(etf_fund_tickers))

    # Save to file
    output_file = Path('data/etf_fund_tickers.txt')
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w') as f:
        f.write("# ETF and Fund Tickers\n")
        f.write(f"# Auto-generated from company profiles\n")
        f.write(f"# Total: {len(etf_fund_tickers)} tickers\n")
        f.write("#\n")
        f.write("# These tickers are excluded from fundamental screening because:\n")
        f.write("# - ETFs/Funds don't file traditional 10-Q/10-K reports\n")
        f.write("# - They have different financial statement structures\n")
        f.write("# - Growth screening strategies don't apply to fund products\n")
        f.write("#\n")
        for ticker in etf_fund_tickers:
            company_name = df.loc[ticker, 'companyName']
            f.write(f"{ticker}\t# {company_name}\n")

    print(f"\n{'='*80}")
    print(f" SUMMARY")
    print(f"{'='*80}")
    print(f"Total ETF/Fund tickers found: {len(etf_fund_tickers)}")
    print(f"Percentage of universe: {len(etf_fund_tickers)/len(df)*100:.1f}%")
    print(f"\nSaved to: {output_file}")

    # Show breakdown by industry
    etf_fund_df = df.loc[etf_fund_tickers]
    print(f"\nIndustry breakdown:")
    industry_counts = etf_fund_df['industry'].value_counts().head(10)
    for industry, count in industry_counts.items():
        print(f"  {industry:40s}: {count:3d}")

    # Show some examples
    print(f"\nExample tickers (first 20):")
    for ticker in etf_fund_tickers[:20]:
        company_name = df.loc[ticker, 'companyName']
        print(f"  {ticker:6s} - {company_name}")

    if len(etf_fund_tickers) > 20:
        print(f"  ... and {len(etf_fund_tickers) - 20} more")

    print(f"\n{'='*80}\n")

    return etf_fund_tickers


def load_etf_fund_list(filepath: str = 'data/etf_fund_tickers.txt') -> set:
    """
    Load ETF/Fund ticker list from file.

    Args:
        filepath: Path to ETF/fund ticker list

    Returns:
        Set of ticker symbols to exclude
    """
    filepath = Path(filepath)

    if not filepath.exists():
        print(f"WARNING: ETF/Fund list not found: {filepath}")
        print(f"Run 'python identify_etfs.py' to generate it")
        return set()

    etf_fund_tickers = set()

    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if line.startswith('#') or not line:
                continue
            # Extract ticker (before tab or space)
            ticker = line.split()[0]
            etf_fund_tickers.add(ticker)

    return etf_fund_tickers


if __name__ == "__main__":
    identify_etfs_and_funds()
