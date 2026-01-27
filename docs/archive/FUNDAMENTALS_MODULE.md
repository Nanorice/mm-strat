# Fundamental Data Module - User Guide

## Overview

The Fundamental Data Module fetches and manages **income statements** and **balance sheets** from the Financial Modeling Prep (FMP) API. This data is essential for completing Dataset A with fundamental features like revenue growth, profit margins, and debt ratios.

## Quick Start

### 1. Initialize Fundamental Dataset

```bash
# Fetch fundamental data for all tickers in price folder
python build_fundamentals.py

# This will:
# - Discover ~337 tickers from data/price/*.parquet
# - Fetch income statements and balance sheets from FMP
# - Cache data as parquet files in data/fundamentals/
# - Take ~3-4 minutes (674 API calls with rate limiting)
```

### 2. Check Cache Status

```bash
# View cache statistics
python build_fundamentals.py --show-stats
```

### 3. Force Refresh

```bash
# Re-fetch all data (ignores 90-day cache)
python build_fundamentals.py --force
```

### 4. Update Specific Tickers

```bash
# Fetch only specific tickers
python build_fundamentals.py --tickers AAPL MSFT GOOGL NVDA
```

## Data Schema

Each ticker's parquet file (`data/fundamentals/{ticker}.parquet`) contains quarterly and annual financial statements with the following structure:

### Core Metadata Columns

| Column | Type | Description |
|--------|------|-------------|
| `ticker` | str | Stock symbol |
| `fiscal_date` | datetime | Fiscal period end date (e.g., 2024-09-30 for Q3 2024) |
| `filing_date` | datetime | **SEC filing date** (when report became public) |
| `accepted_date` | datetime | SEC acceptance date |
| `fiscal_period` | str | Reporting period (e.g., "Q3", "FY") |
| `fiscal_year` | int | Fiscal year |
| `statement_type` | str | "income" or "balance_sheet" |

### Income Statement Metrics

Key columns from FMP income statement endpoint:

- `revenue` - Total revenue
- `costOfRevenue` - Cost of goods sold
- `grossProfit` - Revenue minus COGS
- `operatingIncome` - Operating profit
- `netIncome` - Bottom line profit
- `eps` - Earnings per share
- `ebitda` - Earnings before interest, taxes, depreciation, amortization
- `operatingExpenses` - Total operating costs
- `researchAndDevelopmentExpenses` - R&D spending
- `sellingGeneralAndAdministrativeExpenses` - SG&A costs
- `interestExpense` - Interest on debt
- `incomeTaxExpense` - Taxes paid
- And many more...

### Balance Sheet Metrics

Key columns from FMP balance sheet endpoint:

- `totalAssets` - Total asset value
- `totalLiabilities` - Total debt and obligations  
- `totalEquity` - Shareholder equity
- `cashAndCashEquivalents` - Liquid cash
- `totalDebt` - Short-term + long-term debt
- `currentAssets` - Assets liquidatable within 1 year
- `currentLiabilities` - Obligations due within 1 year
- `inventory` - Goods held for sale
- `accountsReceivable` - Money owed by customers
- `accountsPayable` - Money owed to suppliers
- `propertyPlantEquipment` - Fixed assets
- And many more...

> [!TIP]
> For a complete list of available fields, load a sample ticker and inspect columns:
> ```python
> import pandas as pd
> df = pd.read_parquet('data/fundamentals/AAPL.parquet')
> print(df.columns.tolist())
> ```

## Point-in-Time Usage

**Critical**: Always use `filing_date` to ensure temporal correctness in backtesting.

### What is `filing_date`?

- **`fiscal_date`**: When the fiscal period ended (e.g., Q3 2024 ends Sep 30, 2024)
- **`filing_date`**: When the company **filed the report with SEC** (e.g., filed Oct 31, 2024)

The `filing_date` is when the data **became publicly available**. Using `fiscal_date` would cause lookahead bias!

### Example: Point-in-Time Join

```python
import pandas as pd

# Load price and fundamental data
price_df = pd.read_parquet('data/price/AAPL.parquet')
fund_df = pd.read_parquet('data/fundamentals/AAPL.parquet')

# For each trading date, get the most recent fundamental data available
# (i.e., last filed report before that date)
merged = pd.merge_asof(
    price_df.sort_values('Date'),
    fund_df[fund_df['statement_type'] == 'income'].sort_values('filing_date'),
    left_on='Date',
    right_on='filing_date',
    direction='backward'  # Use last available report
)

# Now merged contains the correct fundamental data as of each trading date
print(merged[['Date', 'Close', 'filing_date', 'revenue', 'netIncome']].head())
```

### Dataset A Integration (Coming Soon)

Once fundamental data is cached, you can include fundamental features in Dataset A:

```bash
python build_dataset_a.py \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --mode full \
  --include-fundamentals \
  --output data/ml/dataset_a_with_fundamentals.parquet
```

This will add features like:
- `revenue_growth_yoy` - Year-over-year revenue growth %
- `earnings_growth_yoy` - YoY EPS growth %
- `gross_margin` - Gross profit / revenue
- `operating_margin` - Operating income / revenue
- `debt_to_equity` - Total debt / total equity
- `current_ratio` - Current assets / current liabilities
- `roa` - Return on assets
- `roe` - Return on equity

## API Reference - `FundamentalEngine` Class

### Initialization

```python
from src.fundamental_engine import FundamentalEngine

# Initialize with defaults from config
engine = FundamentalEngine()

# Or specify custom parameters
engine = FundamentalEngine(
    api_key='your_fmp_api_key',
    fundamentals_dir=Path('custom/path')
)
```

### Methods

#### `fetch_income_statement(ticker: str) -> Optional[pd.DataFrame]`

Fetch income statement for a single ticker.

```python
income_df = engine.fetch_income_statement('AAPL')
print(income_df[['fiscal_date', 'revenue', 'netIncome']].head())
```

#### `fetch_balance_sheet(ticker: str) -> Optional[pd.DataFrame]`

Fetch balance sheet for a single ticker.

```python
balance_df = engine.fetch_balance_sheet('AAPL')
print(balance_df[['fiscal_date', 'totalAssets', 'totalDebt']].head())
```

#### `fetch_all_fundamentals(ticker: str) -> Optional[pd.DataFrame]`

Fetch both statements and combine into single DataFrame.

```python
fund_df = engine.fetch_all_fundamentals('AAPL')
print(f"Total rows: {len(fund_df)}")  # ~40 rows (5 years × 4 quarters × 2 statements)
```

#### `get_ticker_fundamentals(ticker: str, use_cache: bool = True) -> Optional[pd.DataFrame]`

Get fundamental data from cache or fetch if missing.

```python
# Uses cache if available and not stale
df = engine.get_ticker_fundamentals('AAPL')

# Force fresh fetch from API
df = engine.get_ticker_fundamentals('AAPL', use_cache=False)
```

#### `update_fundamentals_cache(tickers: List[str], force: bool = False) -> Dict[str, bool]`

Batch update fundamental cache for multiple tickers.

```python
tickers = ['AAPL', 'MSFT', 'GOOGL', 'NVDA']
results = engine.update_fundamentals_cache(tickers, force=False)

# Check results
for ticker, success in results.items():
    print(f"{ticker}: {'✓' if success else '✗'}")
```

#### `get_available_tickers() -> List[str]`

Get list of tickers with cached data.

```python
cached_tickers = engine.get_available_tickers()
print(f"Cached: {len(cached_tickers)} tickers")
```

#### `get_cache_stats() -> Dict`

Get cache statistics.

```python
stats = engine.get_cache_stats()
print(f"Total tickers: {stats['total_tickers']}")
print(f"Total size: {stats['total_size_mb']:.2f} MB")
print(f"Oldest cache: {stats['oldest_cache']}")
```

## Programmatic Usage Examples

### Example 1: Load and Analyze Single Ticker

```python
from src.fundamental_engine import FundamentalEngine
import pandas as pd

engine = FundamentalEngine()
df = engine.get_ticker_fundamentals('AAPL')

# Filter to income statements only
income = df[df['statement_type'] == 'income'].sort_values('fiscal_date')

# Calculate revenue growth
income['revenue_growth'] = income['revenue'].pct_change() * 100

# Display recent quarters
print(income[['fiscal_date', 'fiscal_period', 'revenue', 'revenue_growth']].tail(8))
```

### Example 2: Batch Update Multiple Tickers

```python
from src.fundamental_engine import FundamentalEngine
from pathlib import Path

engine = FundamentalEngine()

# Get tickers from price folder
price_files = list(Path('data/price').glob('*.parquet'))
tickers = [f.stem for f in price_files]

# Update in batches
results = engine.update_fundamentals_cache(tickers[:50], force=False)

# Summary
success_count = sum(results.values())
print(f"Success rate: {success_count}/{len(results)} ({success_count/len(results)*100:.1f}%)")
```

### Example 3: Calculate Fundamental Ratios

```python
import pandas as pd

# Load fundamental data
df = pd.read_parquet('data/fundamentals/AAPL.parquet')

# Separate income and balance sheet
income = df[df['statement_type'] == 'income'].set_index('fiscal_date')
balance = df[df['statement_type'] == 'balance_sheet'].set_index('fiscal_date')

# Merge on fiscal date
merged = income.join(balance, rsuffix='_bs', how='outer')

# Calculate ratios
merged['gross_margin'] = merged['grossProfit'] / merged['revenue']
merged['debt_to_equity'] = merged['totalDebt'] / merged['totalEquity']
merged['current_ratio'] = merged['currentAssets'] / merged['currentLiabilities']
merged['roa'] = merged['netIncome'] / merged['totalAssets']
merged['roe'] = merged['netIncome'] / merged['totalEquity']

print(merged[['gross_margin', 'debt_to_equity', 'current_ratio', 'roa', 'roe']].tail())
```

## Configuration

All settings are in `config.py`:

```python
# Fundamental Data Settings
FUNDAMENTAL_CACHE_DAYS = 90  # Cache refresh interval (quarterly)
FUNDAMENTAL_LOOKBACK_YEARS = 5  # Historical data to fetch
FMP_FUNDAMENTAL_RATE_LIMIT = 300  # FMP Starter tier limit
FMP_FUNDAMENTAL_BATCH_SIZE = 10  # Tickers per batch
FMP_FUNDAMENTAL_BATCH_DELAY = 2.5  # Delay between batches (seconds)
```

## Rate Limiting

### FMP Starter Tier Limits

- **Rate limit**: 300 calls per minute
- **Each ticker requires**: 2 API calls (income + balance sheet)
- **Total for 337 tickers**: ~674 API calls
- **Estimated time**: ~3-4 minutes with batching

### How Rate Limiting Works

The `FundamentalEngine` automatically handles rate limiting:

1. Tracks API call timestamps
2. Monitors calls per minute
3. Pauses execution if approaching limit (295 calls/minute)
4. Adds delays between batches for safety

You can adjust batch settings in `config.py`:

```python
FMP_FUNDAMENTAL_BATCH_SIZE = 10  # Smaller = slower but safer
FMP_FUNDAMENTAL_BATCH_DELAY = 2.5  # Larger = slower but more buffer
```

## Troubleshooting

### Issue: "FMP_API_KEY is required"

**Solution**: Set your API key in `.env` file:

```bash
FMP_API_KEY=your_actual_api_key_here
```

### Issue: "Rate limit exceeded"

**Solution**: 
- Wait 60 seconds and try again
- Reduce `FMP_FUNDAMENTAL_BATCH_SIZE` in config
- Increase `FMP_FUNDAMENTAL_BATCH_DELAY` in config

### Issue: "No fundamental data available for {ticker}"

**Cause**: Some tickers don't have fundamental data (ETFs, REITs, foreign companies)

**Solution**: This is normal - the engine will log a warning and continue. Failed tickers appear in the summary.

### Issue: Parquet file is empty or has few rows

**Cause**: Company may be newly listed or FMP has limited historical data

**Solution**: Verify on FMP website that data exists. Some companies only have recent data.

### Issue: "Connection timeout"

**Cause**: Network issues or FMP API downtime

**Solution**:
- Check internet connection
- Verify FMP API status at https://site.financialmodelingprep.com/developer/docs/status
- Retry with `--force` flag

## Future: Hybrid Earnings Calendar Approach

The current implementation is for **initial dataset construction**. In the future, we'll enhance this with a more efficient hybrid approach:

### Phase 2 Design (Planned)

#### 1. Weekly Earnings Calendar Scan

Instead of manually refreshing quarterly, automatically detect new earnings:

```python
# Future enhancement - earnings calendar integration
def update_from_earnings_calendar():
    """
    Query FMP earnings calendar for next 7 days.
    Only fetch fundamental data for companies reporting earnings.
    """
    calendar_url = f"{FMP_BASE_URL}/earnings-calendar"
    # Get companies reporting this week
    # Update only those tickers
    # Significantly reduces API usage
```

#### 2. Incremental Updates

Append new quarterly data without re-fetching entire history:

```python
# Current: Fetches all 5 years of data every 90 days
# Future: Only fetch new quarter when company reports
```

#### 3. Production Architecture

- **Scheduled Job**: Add to `daily_scanner.py` or separate cron job
- **API Efficiency**: From ~500 calls/quarter → ~25 calls/week
- **Automated**: No manual refresh needed
- **Fresh Data**: Updated within hours of earnings release

### Benefits of Hybrid Approach

- ✅ **Lower API usage** - Stay within free tier limits
- ✅ **Fresher data** - Weekly updates vs 90-day cache
- ✅ **Automatic detection** - No manual tracking needed
- ✅ **Detects restatements** - Catches when companies revise past reports
- ✅ **Production-ready** - Scalable architecture

### Timeline

Implement after initial Dataset A v1.0 with fundamentals is validated and tested.

## Example Workflow

### Full Pipeline: Price + Fundamentals → Dataset A

```bash
# Step 1: Ensure price data is current
python -c "from src.data_engine import DataRepository; repo = DataRepository(); repo.update_cache(repo.update_universe())"

# Step 2: Initialize fundamental data
python build_fundamentals.py

# Step 3: Build Dataset A with fundamentals
python build_dataset_a.py \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --mode full \
  --include-fundamentals \
  --output data/ml/dataset_a_2024_full.parquet

# Step 4: Verify output
python -c "
import pandas as pd
df = pd.read_parquet('data/ml/dataset_a_2024_full.parquet')
print(f'Rows: {len(df)}')
print(f'Columns: {len(df.columns)}')
print(df.head())
"
```

## Support

For issues or questions:
1. Check this documentation
2. Review FMP API docs: https://site.financialmodelingprep.com/developer/docs
3. Check logs in console output
4. Verify `.env` file has correct `FMP_API_KEY`
