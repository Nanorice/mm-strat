# DuckDB Schema Design

## Design Principles
1. **Sort by date first, ticker second** (optimizes for scanning/backtesting)
2. **Hybrid schema for fundamentals** (typed core columns + JSON blob)
3. **Historical logs for buy_list** (never overwrite, always append)
4. **Views for features** (compute once, query many times)

---

## Core Tables

### 1. `price_data` (Raw OHLCV)
```sql
CREATE TABLE price_data (
    ticker VARCHAR NOT NULL,
    date DATE NOT NULL,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    volume UBIGINT,
    adj_close DOUBLE,
    adj_factor DOUBLE,
    vwap DOUBLE,
    -- Metadata
    source VARCHAR,  -- 'yfinance', 'alpha_vantage', etc.
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, date)
);

-- Critical: Data should be sorted by (date, ticker) on insert
-- This enables DuckDB's min/max zone maps for fast filtering
```

**Insert Pattern**:
```python
# ALWAYS sort before inserting
df = df.sort_values(['date', 'ticker'])
conn.execute("INSERT INTO price_data SELECT * FROM df")
```

---

### 2. `daily_features` (Pre-computed Technical Indicators)
```sql
CREATE TABLE daily_features (
    ticker VARCHAR NOT NULL,
    date DATE NOT NULL,
    -- Moving Averages
    sma_50 DOUBLE,
    sma_200 DOUBLE,
    ema_21 DOUBLE,
    -- Volatility
    atr_14 DOUBLE,
    vol_avg_50 DOUBLE,
    -- Relative Strength
    rs_rating DOUBLE,
    rs_vs_spy DOUBLE,
    -- 52-week metrics
    high_52w DOUBLE,
    low_52w DOUBLE,
    pct_from_high_52w DOUBLE,  -- (close - high_52w) / high_52w
    -- Volume
    vol_ratio_50 DOUBLE,  -- volume / vol_avg_50
    -- Metadata
    feature_version VARCHAR,  -- 'v1.0', for tracking config changes
    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, date)
);
```

**Note**: This replaces the need to compute SMAs on-the-fly for SEPA filtering.

---

### 3. `fundamentals` (Hybrid: Core + JSON)
```sql
CREATE TABLE fundamentals (
    ticker VARCHAR NOT NULL,
    report_date DATE NOT NULL,  -- Quarter end date (e.g., 2023-12-31)
    filing_date DATE,            -- Actual filing date (for point-in-time)
    period_type VARCHAR,         -- 'Q1', 'Q2', 'Q3', 'Q4', 'FY'
    fiscal_year INTEGER,
    -- First-class citizens (frequently filtered/sorted)
    revenue DOUBLE,
    net_income DOUBLE,
    eps_diluted DOUBLE,
    total_assets DOUBLE,
    total_equity DOUBLE,
    operating_cash_flow DOUBLE,
    -- Second-class citizens (everything else)
    raw_data JSON,  -- Full earnings report as JSON blob
    -- Metadata
    source VARCHAR,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, report_date, period_type)
);

-- Example JSON query:
-- SELECT raw_data->>'operating_margin' FROM fundamentals WHERE ticker = 'AAPL'
```

---

### 4. `company_profiles` (Universe Management)
```sql
CREATE TABLE company_profiles (
    ticker VARCHAR PRIMARY KEY,
    name VARCHAR,
    sector VARCHAR,
    industry VARCHAR,
    market_cap DOUBLE,
    country VARCHAR,
    exchange VARCHAR,
    is_active BOOLEAN DEFAULT TRUE,  -- For handling delistings
    listing_date DATE,
    delisting_date DATE,
    -- Metadata
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Upsert pattern for updates:
-- INSERT INTO company_profiles VALUES (...)
-- ON CONFLICT (ticker) DO UPDATE SET ...
```

---

### 5. `buy_list_history` (Scanner Output Log)
```sql
CREATE TABLE buy_list_history (
    scan_date DATE NOT NULL,
    ticker VARCHAR NOT NULL,
    rank INTEGER,  -- Position in buy list (1 = top)
    score DOUBLE,  -- Composite score from scanner
    reason VARCHAR,  -- 'SEPA_breakout', 'earnings_surprise', etc.
    metadata JSON,  -- Additional context (e.g., which filters passed)
    PRIMARY KEY (scan_date, ticker)
);

-- Never overwrite. Always INSERT new scan results.
-- Query: "What was my buy list on 2023-10-27?"
-- SELECT * FROM buy_list_history WHERE scan_date = '2023-10-27' ORDER BY rank
```

---

### 6. `macro_data` (Index & Economic Data)
```sql
CREATE TABLE macro_data (
    date DATE NOT NULL,
    symbol VARCHAR NOT NULL,  -- 'SPY', 'VIX', 'TNX', etc.
    close DOUBLE,
    volume UBIGINT,
    -- For economic indicators (e.g., Fed rates, GDP)
    value DOUBLE,
    unit VARCHAR,  -- 'percent', 'billions', etc.
    PRIMARY KEY (date, symbol)
);
```

---

## Views (Computed Features)

### `v_sepa_candidates` (Live SEPA Filter)
```sql
CREATE VIEW v_sepa_candidates AS
SELECT
    f.date,
    f.ticker,
    p.close,
    f.sma_50,
    f.sma_200,
    f.rs_rating,
    f.vol_avg_50,
    f.high_52w,
    f.pct_from_high_52w,
    c.sector,
    c.industry
FROM daily_features f
INNER JOIN price_data p
    ON f.ticker = p.ticker AND f.date = p.date
INNER JOIN company_profiles c
    ON f.ticker = c.ticker
WHERE
    -- Hard Rules (SEPA criteria)
    p.close > f.sma_200                    -- Price > 200 SMA
    AND f.sma_50 > f.sma_200                -- 50 SMA > 200 SMA
    AND f.pct_from_high_52w > -0.25        -- Within 25% of 52w high
    AND c.is_active = TRUE                 -- Active tickers only
    AND f.vol_avg_50 > 500000;             -- Liquidity filter
```

**Usage**:
```python
# Replace your current SEPA filter logic with:
sepa_df = conn.execute("""
    SELECT * FROM v_sepa_candidates
    WHERE date = ?
    ORDER BY rs_rating DESC
    LIMIT 50
""", [target_date]).fetchdf()
```

---

### `v_master_dataset` (Equivalent to D2R)
```sql
CREATE VIEW v_master_dataset AS
SELECT
    p.ticker,
    p.date,
    p.close,
    p.volume,
    p.adj_close,
    -- Technical features
    f.sma_50,
    f.sma_200,
    f.rs_rating,
    f.vol_avg_50,
    -- Company info
    c.sector,
    c.industry,
    c.market_cap,
    -- Fundamentals (latest quarterly data as of date)
    fund.revenue,
    fund.eps_diluted,
    fund.operating_cash_flow,
    -- Macro context
    spy.close as spy_close,
    vix.close as vix_close
FROM price_data p
LEFT JOIN daily_features f
    ON p.ticker = f.ticker AND p.date = f.date
LEFT JOIN company_profiles c
    ON p.ticker = c.ticker
LEFT JOIN LATERAL (
    SELECT revenue, eps_diluted, operating_cash_flow
    FROM fundamentals
    WHERE ticker = p.ticker
      AND report_date <= p.date
    ORDER BY report_date DESC
    LIMIT 1
) fund ON TRUE
LEFT JOIN macro_data spy
    ON p.date = spy.date AND spy.symbol = 'SPY'
LEFT JOIN macro_data vix
    ON p.date = vix.date AND vix.symbol = 'VIX'
WHERE c.is_active = TRUE;
```

---

## Performance Optimization

### Indexes
DuckDB automatically creates indexes on PRIMARY KEY columns. Additional indexes are rarely needed due to columnar storage and zone maps.

### Sorting Strategy
**Critical**: Always sort DataFrames before inserting:
```python
# Correct
df = df.sort_values(['date', 'ticker'])
conn.execute("INSERT INTO price_data SELECT * FROM df")

# Wrong (random row order degrades query performance)
conn.execute("INSERT INTO price_data SELECT * FROM df")
```

### Partitioning
For datasets < 50GB, **do not use Hive-style partitioning**. DuckDB's columnar format + sorting is sufficient.

---

## Migration Strategy

### Phase 1: Parallel Operation
1. **Files remain source of truth**
2. **Daily workflow**:
   - `data_curator.py` updates files (existing logic)
   - `sync_to_duckdb.py` reads files → writes to DB
   - `validate_migration.py` checks file vs. DB consistency

### Phase 2: Feature Migration
1. Migrate SEPA filter to `v_sepa_candidates` view
2. Migrate model training to query `v_master_dataset`
3. Deprecate file-based workflows

---

## Backup & Recovery

### Daily Backup
```bash
# Simple: DuckDB is a single file
cp market_data.duckdb backups/market_data_$(date +%Y%m%d).duckdb
```

### Point-in-Time Recovery
- Keep weekly snapshots for 3 months
- Daily snapshots for last 30 days

---

## Excluded from Phase 1
- Logging tables (use text files)
- Backtest results (store as JSON/parquet for now)
- Model configs (YAML files are fine)

These can be added in Phase 2 if needed.
