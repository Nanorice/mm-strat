"""
Standalone test: SEC EDGAR XBRL → fundamentals_edgar_test table.

Validates that the SEC taxonomy map correctly resolves to our yfinance schema
for a small set of tickers covering tech (AAPL), bank (JPM), SaaS (NOW).

Creates: fundamentals_edgar_test (isolated, does NOT touch fundamentals table)
Run: python tools/test_edgar_fundamentals.py
"""

import time
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import duckdb
import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format='%(levelname)s  %(message)s')
logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / 'data' / 'edgar_test.duckdb'
SEC_HEADERS = {'User-Agent': 'SEPA_Research_Tool research@quantamental.dev'}
SEC_RATE_LIMIT_SLEEP = 0.15  # SEC allows ~10 req/s

# ── Taxonomy map ─────────────────────────────────────────────────────────────
# Each entry is an ordered priority list: first tag found with a non-null value wins.
# Column names match FundamentalEngine's DuckDB schema exactly.
# Unit type is specified to avoid grabbing USD values for share counts.

TAXONOMY: Dict[str, Tuple[str, List[str]]] = {
    # column_name: (unit_type, [tag_priority_list])
    'total_revenue': ('USD', [
        'RevenueFromContractWithCustomerExcludingAssessedTax',
        'RevenueFromContractWithCustomerIncludingAssessedTax',
        'Revenues',
        'SalesRevenueNet',
        'InterestAndDividendIncomeOperating',       # banks
        'RevenueFromContractsWithCustomers',
    ]),
    'gross_profit': ('USD', [
        'GrossProfit',
    ]),
    'operating_income': ('USD', [
        'OperatingIncomeLoss',
    ]),
    'net_income': ('USD', [
        'NetIncomeLoss',
        'NetIncomeLossAvailableToCommonStockholdersBasic',
        'ProfitLoss',
    ]),
    'r_and_d': ('USD', [
        'ResearchAndDevelopmentExpense',
        'ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost',
    ]),
    'sga': ('USD', [
        'SellingGeneralAndAdministrativeExpense',
        'GeneralAndAdministrativeExpense',
    ]),
    'total_assets': ('USD', [
        'Assets',
    ]),
    'current_assets': ('USD', [
        'AssetsCurrent',
    ]),
    'cash_and_equivalents': ('USD', [
        'CashAndCashEquivalentsAtCarryingValue',
        'CashCashEquivalentsAndShortTermInvestments',
        'Cash',
    ]),
    'total_debt': ('USD', [
        'DebtLongtermAndShorttermCombinedAmount',
        'LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities',
        'LongTermDebt',
    ]),
    'long_term_debt': ('USD', [
        'LongTermDebt',
        'LongTermDebtNoncurrent',
        'LongTermDebtAndCapitalLeaseObligations',
    ]),
    'current_liabilities': ('USD', [
        'LiabilitiesCurrent',
    ]),
    'stockholders_equity': ('USD', [
        'StockholdersEquity',
        'StockholdersEquityAttributableToParent',
    ]),
    'operating_cash_flow': ('USD', [
        'NetCashProvidedByUsedInOperatingActivities',
        'NetCashProvidedByUsedInOperatingActivitiesContinuingOperations',
    ]),
    'capex': ('USD', [
        'PaymentsToAcquirePropertyPlantAndEquipment',
        'PaymentsForCapitalImprovements',
    ]),
}

VALID_FORMS = {'10-K', '10-Q'}


# ── SEC helpers ───────────────────────────────────────────────────────────────

def _fetch_cik_map() -> Dict[str, str]:
    """Return {ticker: zero-padded-10-digit-CIK}."""
    logger.info('Fetching SEC ticker→CIK mapping...')
    r = requests.get(
        'https://www.sec.gov/files/company_tickers.json',
        headers=SEC_HEADERS,
        timeout=30,
    )
    r.raise_for_status()
    return {
        v['ticker']: str(v['cik_str']).zfill(10)
        for v in r.json().values()
    }


def _fetch_company_facts(cik: str) -> Optional[Dict]:
    """Fetch raw XBRL company facts for one CIK."""
    url = f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json'
    time.sleep(SEC_RATE_LIMIT_SLEEP)
    r = requests.get(url, headers=SEC_HEADERS, timeout=30)
    if r.status_code != 200:
        logger.warning(f'HTTP {r.status_code} for CIK {cik}')
        return None
    return r.json()


# ── Taxonomy resolver ─────────────────────────────────────────────────────────

def _resolve_tag(
    us_gaap: Dict,
    unit_type: str,
    tags: List[str],
) -> Dict[Tuple[str, str], float]:
    """
    For a priority-ordered tag list, return the first tag that exists and has
    data. Returns {(end_date, form): value} using the most recently filed value
    per (end_date, form) pair to handle amendments.
    """
    for tag in tags:
        entry = us_gaap.get(tag)
        if entry is None:
            continue
        periods = entry.get('units', {}).get(unit_type, [])
        if not periods:
            continue

        result: Dict[Tuple[str, str], float] = {}
        for p in periods:
            if p.get('form') not in VALID_FORMS:
                continue
            key = (p['end'], p['form'])
            # Keep last-filed (handles 10-K/A amendments)
            if key not in result or p['filed'] > result.get(f'{key}_filed', ''):
                result[key] = p['val']
                result[f'{key}_filed'] = p['filed']

        # Strip the internal _filed tracking keys
        clean = {k: v for k, v in result.items() if isinstance(k, tuple)}
        if clean:
            logger.debug(f'  Tag resolved: {tag} ({len(clean)} periods)')
            return clean

    return {}


# ── Per-ticker extraction ─────────────────────────────────────────────────────

def extract_ticker(ticker: str, cik: str) -> Optional[pd.DataFrame]:
    facts = _fetch_company_facts(cik)
    if facts is None:
        return None

    us_gaap = facts.get('facts', {}).get('us-gaap', {})
    if not us_gaap:
        logger.warning(f'{ticker}: no us-gaap facts found')
        return None

    # Collect all (end_date, form) pairs across all columns
    all_keys: set = set()
    resolved: Dict[str, Dict] = {}

    for col, (unit_type, tags) in TAXONOMY.items():
        tag_data = _resolve_tag(us_gaap, unit_type, tags)
        resolved[col] = tag_data
        all_keys.update(tag_data.keys())

    if not all_keys:
        logger.warning(f'{ticker}: no data resolved from taxonomy')
        return None

    rows = []
    for (end_date, form) in sorted(all_keys):
        row: Dict = {
            'ticker': ticker,
            'period_end': end_date,
            'form': form,
        }
        for col in TAXONOMY:
            row[col] = resolved[col].get((end_date, form))
        rows.append(row)

    df = pd.DataFrame(rows)
    df['period_end'] = pd.to_datetime(df['period_end']).dt.date
    df['source'] = 'edgar'
    logger.info(f'{ticker}: {len(df)} periods extracted ({df["period_end"].min()} → {df["period_end"].max()})')
    return df


# ── DuckDB persistence ────────────────────────────────────────────────────────

def _ensure_test_table(con: duckdb.DuckDBPyConnection) -> None:
    cols = '\n'.join(
        f'    {col} {"BIGINT" if "shares" in col else "DOUBLE"},'
        for col in TAXONOMY
    )
    con.execute(f"""
        CREATE OR REPLACE TABLE fundamentals_edgar_test (
            ticker      VARCHAR NOT NULL,
            period_end  DATE    NOT NULL,
            form        VARCHAR,
            {cols}
            source      VARCHAR DEFAULT 'edgar',
            PRIMARY KEY (ticker, period_end, form)
        )
    """)
    logger.info('Table fundamentals_edgar_test created/replaced.')


def _upsert(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    col_names = ['ticker', 'period_end', 'form'] + list(TAXONOMY.keys()) + ['source']
    for c in col_names:
        if c not in df.columns:
            df[c] = None
    df = df[col_names]

    con.register('_edgar_batch', df)
    placeholders = ', '.join(f'EXCLUDED.{c}' for c in col_names if c not in ('ticker', 'period_end', 'form'))
    set_clause = ',\n                    '.join(
        f'{c} = EXCLUDED.{c}'
        for c in col_names
        if c not in ('ticker', 'period_end', 'form')
    )
    con.execute(f"""
        INSERT INTO fundamentals_edgar_test
        SELECT * FROM _edgar_batch
        ON CONFLICT (ticker, period_end, form) DO UPDATE SET
            {set_clause}
    """)
    return len(df)


# ── Diagnostic report ─────────────────────────────────────────────────────────

def _print_coverage_report(con: duckdb.DuckDBPyConnection) -> None:
    print('\n' + '=' * 60)
    print('COVERAGE REPORT — fundamentals_edgar_test')
    print('=' * 60)

    tickers = con.execute('SELECT DISTINCT ticker FROM fundamentals_edgar_test ORDER BY ticker').fetchall()
    for (ticker,) in tickers:
        df = con.execute(
            'SELECT * FROM fundamentals_edgar_test WHERE ticker = ? ORDER BY period_end DESC LIMIT 4',
            [ticker]
        ).df()
        print(f'\n{ticker}  ({len(df)} rows shown, most recent 4):')
        null_counts = df[list(TAXONOMY.keys())].isnull().sum()
        missing_cols = null_counts[null_counts == len(df)].index.tolist()
        populated = [c for c in TAXONOMY if c not in missing_cols]
        print(f'  Populated ({len(populated)}): {", ".join(populated)}')
        print(f'  Missing   ({len(missing_cols)}): {", ".join(missing_cols) or "none"}')
        for _, row in df.head(2).iterrows():
            def _fmt_b(val, label: str) -> str:
                return f'{label}=${val/1e9:.1f}B' if pd.notna(val) and val else f'{label}=N/A'
            def _fmt_m(val, label: str) -> str:
                return f'{label}={val/1e6:.0f}M' if pd.notna(val) and val else f'{label}=N/A'
            print(f'  {row["period_end"]} [{row["form"]}]  '
                  f'{_fmt_b(row.get("total_revenue"), "rev")}  '
                  f'{_fmt_b(row.get("net_income"), "ni")}  '
                  f'{_fmt_m(row.get("shares_outstanding"), "shares")}')

    print('\n')


# ── Main ──────────────────────────────────────────────────────────────────────

TEST_TICKERS = ['AAPL', 'JPM', 'NOW']   # tech | bank | SaaS


def main() -> None:
    cik_map = _fetch_cik_map()

    all_frames = []
    for ticker in TEST_TICKERS:
        cik = cik_map.get(ticker)
        if not cik:
            logger.error(f'{ticker}: CIK not found, skipping')
            continue
        logger.info(f'Processing {ticker} (CIK {cik})...')
        df = extract_ticker(ticker, cik)
        if df is not None:
            all_frames.append(df)

    if not all_frames:
        logger.error('No data extracted. Aborting.')
        return

    combined = pd.concat(all_frames, ignore_index=True)
    logger.info(f'Total rows before dedup: {len(combined)}')

    con = duckdb.connect(str(DB_PATH))
    try:
        _ensure_test_table(con)
        written = _upsert(con, combined)
        logger.info(f'Wrote {written} rows to fundamentals_edgar_test')
        _print_coverage_report(con)
    finally:
        con.close()


if __name__ == '__main__':
    main()
