"""
Ticker Filter - Utilities to filter out ETFs, Funds, and other non-stock securities.

This module helps identify and filter out:
- Closed-End Funds (CEFs)
- Exchange-Traded Funds (ETFs)
- Mutual Funds
- REITs (optionally)
- Other non-traditional equities

These securities have different fundamental reporting requirements and may not
be suitable for traditional stock screening strategies.
"""

import pandas as pd
from pathlib import Path
from typing import List, Set, Optional
import logging

import sys
sys.path.append(str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


class TickerFilter:
    """Filter out non-stock securities (ETFs, Funds, etc.)"""

    def __init__(self, company_profiles_path: Optional[Path] = None):
        """
        Initialize TickerFilter.

        Args:
            company_profiles_path: Path to company profiles parquet file
        """
        self.profiles_path = company_profiles_path or (config.COMPANY_INFO_DIR / 'company_profiles.parquet')
        self.profiles = None

    def load_profiles(self):
        """Load company profiles from cache."""
        if self.profiles_path.exists():
            self.profiles = pd.read_parquet(self.profiles_path)
            logger.info(f"Loaded {len(self.profiles)} company profiles")
        else:
            logger.warning(f"Company profiles not found: {self.profiles_path}")
            self.profiles = pd.DataFrame()

    def is_fund_or_trust(self, ticker: str) -> bool:
        """
        Check if ticker is a fund or trust based on company name.

        Closed-End Funds (CEFs) typically have names like:
        - "BlackRock Enhanced Equity Dividend Trust"
        - "PIMCO Corporate & Income Strategy Fund"
        - "Abrdn Global Infrastructure Income Fund"

        Real companies don't have these suffixes:
        - "BlackRock, Inc." ✅ (keep)
        - "Apple Inc." ✅ (keep)

        Args:
            ticker: Stock symbol

        Returns:
            True if ticker is a fund/trust, False otherwise
        """
        if self.profiles is None:
            self.load_profiles()

        if self.profiles.empty or ticker not in self.profiles.index:
            return False

        company_name = self.profiles.loc[ticker, 'companyName']

        # Check for fund/trust indicators in name
        fund_indicators = [
            'Trust',
            'Fund',
            'ETF',
            'Index',
        ]

        # Exclude if name ends with these (e.g., "Vanguard Total Stock Market Index Fund")
        # But keep if name just contains "Trust" as part of company name (e.g., "Truist Financial")
        for indicator in fund_indicators:
            if indicator in company_name:
                # Check if it's at the end or followed by common fund suffixes
                if (company_name.endswith(indicator) or
                    f'{indicator} ' in company_name or
                    f' {indicator}' in company_name):
                    return True

        return False

    def is_asset_management_fund(self, ticker: str) -> bool:
        """
        Check if ticker is an Asset Management fund (CEF) vs real company.

        Pattern:
        - Sector: Financial Services
        - Industry: Asset Management (or variants)
        - Company Name: Contains "Trust" or "Fund"

        Args:
            ticker: Stock symbol

        Returns:
            True if it's a fund, False if it's a real asset management company
        """
        if self.profiles is None:
            self.load_profiles()

        if self.profiles.empty or ticker not in self.profiles.index:
            return False

        row = self.profiles.loc[ticker]

        # Check if it's in Asset Management industry
        if 'industry' in row and pd.notna(row['industry']):
            if 'Asset Management' in row['industry']:
                # If yes, check company name for fund indicators
                return self.is_fund_or_trust(ticker)

        return False

    def filter_stocks_only(
        self,
        tickers: List[str],
        exclude_funds: bool = True,
        exclude_reits: bool = False,
        verbose: bool = True
    ) -> List[str]:
        """
        Filter ticker list to stocks only (exclude funds, ETFs, etc.).

        Args:
            tickers: List of ticker symbols
            exclude_funds: If True, exclude funds and trusts (default: True)
            exclude_reits: If True, exclude REITs (default: False)
            verbose: If True, log filtering results

        Returns:
            Filtered list of ticker symbols (stocks only)
        """
        if self.profiles is None:
            self.load_profiles()

        if self.profiles.empty:
            logger.warning("No company profiles loaded, cannot filter")
            return tickers

        original_count = len(tickers)
        filtered = []
        excluded = {
            'funds': [],
            'reits': [],
            'no_profile': []
        }

        for ticker in tickers:
            # Check if profile exists
            if ticker not in self.profiles.index:
                excluded['no_profile'].append(ticker)
                continue

            # Check if fund/trust
            if exclude_funds and self.is_fund_or_trust(ticker):
                excluded['funds'].append(ticker)
                continue

            # Check if REIT
            if exclude_reits:
                row = self.profiles.loc[ticker]
                if 'sector' in row and row['sector'] == 'Real Estate':
                    excluded['reits'].append(ticker)
                    continue

            # Keep this ticker
            filtered.append(ticker)

        if verbose:
            logger.info(f"Ticker filtering results:")
            logger.info(f"  Original: {original_count}")
            logger.info(f"  Kept (stocks): {len(filtered)} ({len(filtered)/original_count*100:.1f}%)")
            if excluded['funds']:
                logger.info(f"  Excluded (funds/trusts): {len(excluded['funds'])}")
            if excluded['reits']:
                logger.info(f"  Excluded (REITs): {len(excluded['reits'])}")
            if excluded['no_profile']:
                logger.info(f"  Excluded (no profile): {len(excluded['no_profile'])}")

        return filtered

    def get_excluded_tickers(
        self,
        tickers: List[str],
        exclude_funds: bool = True,
        exclude_reits: bool = False
    ) -> dict:
        """
        Get detailed breakdown of excluded tickers.

        Returns:
            Dictionary with categories of excluded tickers
        """
        if self.profiles is None:
            self.load_profiles()

        excluded = {
            'funds': [],
            'reits': [],
            'no_profile': [],
            'kept': []
        }

        for ticker in tickers:
            if ticker not in self.profiles.index:
                excluded['no_profile'].append(ticker)
            elif exclude_funds and self.is_fund_or_trust(ticker):
                excluded['funds'].append(ticker)
            elif exclude_reits and self.profiles.loc[ticker, 'sector'] == 'Real Estate':
                excluded['reits'].append(ticker)
            else:
                excluded['kept'].append(ticker)

        return excluded


def filter_stocks_only(tickers: List[str], verbose: bool = True) -> List[str]:
    """
    Convenience function to filter stocks only.

    Args:
        tickers: List of ticker symbols
        verbose: If True, log filtering results

    Returns:
        Filtered list (stocks only, no funds/ETFs)
    """
    filter_obj = TickerFilter()
    return filter_obj.filter_stocks_only(tickers, verbose=verbose)
