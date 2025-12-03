# Database Usage Clarification

**Question**: How is `qss_db.sqlite` used? For scanner results, do we cache to `trades.db`?

**Short Answer**:
- `qss_db.sqlite` is **EMPTY/UNUSED** (leftover file, can be deleted)
- `database/qss_scanner.db` is **EMPTY/UNUSED** (created by mistake, can be deleted)
- **`database/trades.db` is the ONLY active database** used by the scanner

---

## Database Files in Project

```
Current State:
├── database/trades.db          ✅ ACTIVE (56 KB, contains data)
├── database/qss_scanner.db     ❌ EMPTY (0 KB, unused)
└── qss_db.sqlite               ❌ EMPTY (0 KB, unused, in root)
```

---

## The Truth: Only `trades.db` is Used

### Configuration (config.py:110)

```python
DB_PATH = DATABASE_DIR / 'trades.db'  # This is the one!
```

### What's Inside `trades.db`

```sql
-- Scanner uses these tables:
├── buy_list              -- Active buy signals with ML scores
├── buy_list_activity     -- Audit trail (adds/removes)
├── watchlist             -- Stocks in setup (not triggered yet)
└── trades                -- Historical trade log (future use)
```

---

## Table Purposes

### 1. `buy_list` - Active Buy Signals

**Purpose**: Stocks that triggered SEPA signals and passed ML filter

**Used by**: `optimized_scanner.py`

**Schema**:
```sql
CREATE TABLE buy_list (
    ticker TEXT PRIMARY KEY,
    signal_date DATE NOT NULL,         -- When signal triggered
    signal_price REAL NOT NULL,        -- Price at signal
    current_price REAL NOT NULL,       -- Latest price (updated daily)
    entry_price REAL,                  -- Planned entry
    stop_price REAL,                   -- Stop loss
    target_price REAL,                 -- Profit target
    atr REAL,                          -- Average True Range
    rs REAL,                           -- Relative Strength
    volume_ratio REAL,                 -- Volume spike
    ma50, ma150, ma200 REAL,          -- Moving averages
    high_52w, low_52w REAL,           -- 52-week range

    -- ML Columns (added in ML integration)
    ml_probability REAL,               -- ML success probability (0.0-1.0)
    ml_rank INTEGER,                   -- ML rank (1=best)
    ml_model_version TEXT,             -- Model version identifier
    ml_score_date DATE,                -- When ML score was calculated

    last_updated DATE,                 -- Last scanner update
    status TEXT DEFAULT 'active',      -- 'active' or 'removed'
    notes TEXT
);
```

**Example Data**:
```
ticker | signal_date | signal_price | ml_probability | ml_rank | status
-------|-------------|--------------|----------------|---------|--------
AAPL   | 2024-11-15  | 150.00       | 0.72           | 1       | active
MSFT   | 2024-11-20  | 380.00       | 0.65           | 2       | active
NVDA   | 2024-11-10  | 490.00       | 0.58           | 5       | removed
```

---

### 2. `buy_list_activity` - Audit Trail

**Purpose**: Log every change to buy_list (who was added when, who was removed why)

**Used by**: `optimized_scanner.py` (logs all changes)

**Schema**:
```sql
CREATE TABLE buy_list_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,              -- 'ADDED' or 'REMOVED'
    action_date DATE NOT NULL,         -- When action happened
    reason TEXT,                       -- 'new_trigger' or 'trend_broken'
    entry_price REAL,
    stop_price REAL,
    target_price REAL,
    rs REAL,
    vol_ratio REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Example Data**:
```
id | ticker | action  | action_date | reason
---|--------|---------|-------------|-------------
1  | AAPL   | ADDED   | 2024-11-15  | new_trigger
2  | MSFT   | ADDED   | 2024-11-20  | new_trigger
3  | NVDA   | REMOVED | 2024-11-25  | trend_broken
4  | NVDA   | ADDED   | 2024-12-01  | new_trigger (re-entry)
```

---

### 3. `watchlist` - Setup Tracking (Pre-Signal)

**Purpose**: Track stocks in Stage 2 uptrend but haven't triggered buy signal yet

**Used by**: Legacy feature (not actively used by current scanner)

**Schema**:
```sql
CREATE TABLE watchlist (
    ticker TEXT PRIMARY KEY,
    first_seen DATE NOT NULL,          -- First time stock met setup criteria
    last_seen DATE NOT NULL,           -- Last time stock still in setup
    days_on_watchlist INTEGER DEFAULT 1,
    avg_rs REAL,
    avg_volume_ratio REAL,
    status TEXT DEFAULT 'active',
    notes TEXT
);
```

**Note**: This table is for "stocks setting up" (Stage 2, but no volume breakout yet). Current scanner focuses on `buy_list` (signals already triggered).

---

### 4. `trades` - Historical Trade Log

**Purpose**: Log actual trades (entry, exit, P&L)

**Used by**: **NOT YET IMPLEMENTED** (placeholder for future trade execution)

**Schema**:
```sql
CREATE TABLE trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    entry_date DATE NOT NULL,
    entry_price REAL NOT NULL,
    exit_date DATE,
    exit_price REAL,
    shares INTEGER NOT NULL,
    pnl_dollars REAL,
    pnl_percent REAL,
    exit_reason TEXT,
    stop_price REAL,
    target_price REAL,
    days_held INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Future Use**: When you integrate with broker API, log actual trades here for performance tracking.

---

## Scanner Workflow with Database

```
optimized_scanner.py
    ↓
1. Load Universe (1730 tickers)
    ↓
2. Calculate Features
    ↓
3. Screen for SEPA Signals → 15 candidates
    ↓
4. [Optional] ML Scoring → 8 pass threshold (>0.6)
    ↓
5. Database Operations:
    ├── Load existing buy_list from trades.db
    ├── Compare with new signals
    ├── ADD new triggers → buy_list table
    ├── UPDATE existing signals still qualifying
    ├── REMOVE signals with broken trends
    ├── LOG all changes → buy_list_activity table
    └── Store ML scores (ml_probability, ml_rank, ml_model_version)
```

---

## Scanner Database Methods (src/database.py)

### Adding Signals
```python
db.add_to_buy_list(
    ticker='AAPL',
    signal_date='2024-11-15',
    signal_price=150.00,
    current_price=150.00,
    ml_probability=0.72,      # ML score
    ml_rank=1,                 # ML rank
    ml_model_version='2024-11-30',
    ml_score_date='2024-12-01',
    rs=0.85,
    vol_ratio=1.4
)
```

### Updating Signals
```python
db.update_buy_list_metrics(
    ticker='AAPL',
    scan_date='2024-11-16',
    current_price=152.50,      # Price updated
    rs=0.87,
    ma50=145.20
)
```

### Removing Signals
```python
db.remove_from_buy_list('AAPL', reason='trend_broken')
db.log_buy_list_activity('AAPL', 'REMOVED', '2024-11-20', reason='trend_broken')
```

### Querying Signals
```python
# Get all active signals
buy_list = db.get_buy_list(active_only=True)

# Get historical state (as of specific date)
historical = db.get_buy_list(active_only=True, as_of_date='2024-11-01')
```

---

## Where Does Dataset B Come From?

**Important**: Dataset B (trade labels) is **NOT** stored in database!

```
Dataset B Generation (build_dataset_b.py):
1. Run historical trade simulation (in-memory)
2. Track trades using Trade objects (dataclasses)
3. Calculate metrics (return, MDD, MFE, Sharpe, etc.)
4. Label trades (1=success, 0=failure)
5. Export to Parquet: data/ml/dataset_b.parquet

Scanner Database (optimized_scanner.py):
1. Store active buy signals in database (buy_list table)
2. Track additions/removals (buy_list_activity)
3. NO overlap with Dataset B generation
```

**Why separate?**
- **Dataset B**: Historical simulation for ML training (ephemeral, batch process)
- **Scanner DB**: Real-time signal tracking (persistent state, incremental updates)

---

## Unused Database Files

### `qss_db.sqlite` (Root Directory)
- **Size**: 0 KB (empty)
- **Status**: Created by mistake, never used
- **Action**: **Can be deleted safely**

### `database/qss_scanner.db`
- **Size**: 0 KB (empty)
- **Status**: Created during testing, never populated
- **Action**: **Can be deleted safely**

---

## Cleanup Recommendation

```bash
# Remove unused database files
rm qss_db.sqlite
rm database/qss_scanner.db

# Keep only the active one
ls database/
# Output: trades.db  (this is the one!)
```

---

## Documentation Inconsistencies

Some docs mention `qss_scanner.db` or `qss_db.sqlite` - these are **ERRORS**. Here's the correction:

| Document | Wrong Reference | Correct Reference |
|----------|----------------|-------------------|
| ARCHITECTURE.md:1226 | `qss_scanner.db` | `trades.db` |
| PROJECT_ORGANIZATION.md | `qss_scanner.db` | `trades.db` |
| USER_GUIDE.md | `qss_scanner.db` | `trades.db` |
| WORKFLOW_CHART.md | `qss_db.sqlite` | `trades.db` |

**Why the confusion?**
Early in development, there were plans to use separate databases. The code was consolidated to use `trades.db` only, but some documentation wasn't updated.

---

## Summary

**✅ USE THIS**:
- `database/trades.db` - The ONLY active database
  - `buy_list` table - Active buy signals (scanner output)
  - `buy_list_activity` table - Audit trail
  - `watchlist` table - Setup tracking (legacy)
  - `trades` table - Future trade execution

**❌ DELETE THESE**:
- `qss_db.sqlite` (root) - Empty, unused
- `database/qss_scanner.db` - Empty, unused

**🔍 REMEMBER**:
- Scanner results → `database/trades.db` (buy_list table)
- Dataset B → `data/ml/dataset_b.parquet` (NOT database)
- ML predictions log → `data/predictions_log.parquet` (NOT database)

---

## Viewing Scanner Results

```bash
# Method 1: Use script
python scripts/view_buy_list.py

# Method 2: Direct SQL query
sqlite3 database/trades.db "SELECT ticker, signal_date, ml_probability, ml_rank FROM buy_list WHERE status='active' ORDER BY ml_rank"

# Method 3: Python
import sqlite3
import pandas as pd

conn = sqlite3.connect('database/trades.db')
df = pd.read_sql_query("SELECT * FROM buy_list WHERE status='active'", conn)
print(df)
```

---

## Questions?

- **Where is scanner output?** → `database/trades.db` (buy_list table)
- **Where is Dataset B?** → `data/ml/dataset_b.parquet` (NOT database)
- **Can I delete qss_db.sqlite?** → Yes, it's empty and unused
- **Why multiple database files?** → Historical artifact, consolidate to trades.db

Hope this clears up the confusion!
