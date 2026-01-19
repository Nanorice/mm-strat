# Database Deduplication - How It Works

## Problem
When re-running the scanner on the same date (e.g., testing, debugging, or refining parameters), we need to ensure:
1. No duplicate ticker entries in `buy_list` table
2. No duplicate activity logs in `buy_list_activity` table

## Solution

### 1. Buy List Table - Already Protected ✅

**Schema:**
```sql
CREATE TABLE buy_list (
    ticker TEXT PRIMARY KEY,  -- ← This prevents duplicates
    signal_date DATE NOT NULL,
    ...
)
```

**Method:** `add_to_buy_list()`
```python
# Uses INSERT OR REPLACE (SQLite UPSERT)
cursor.execute("""
    INSERT OR REPLACE INTO buy_list
    (ticker, signal_date, ...)
    VALUES (?, ?, ...)
""", (ticker, signal_date, ...))
```

**Behavior:**
- **First run**: Inserts new row
- **Second run (same day)**: Replaces existing row with updated values
- **Result**: Always exactly 1 row per ticker ✅

### 2. Activity Log Table - Now Protected ✅

**Schema:**
```sql
CREATE TABLE buy_list_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,  -- Each activity gets unique ID
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,
    action_date DATE NOT NULL,
    ...
)
```

**Updated Method:** `log_buy_list_activity()`
```python
# Before (old):
INSERT INTO buy_list_activity (...) VALUES (...)  # ← Always inserted, causing duplicates

# After (new):
# 1. Check if activity exists
SELECT id FROM buy_list_activity
WHERE ticker = ? AND action = ? AND action_date = ?

# 2a. If exists: Update it
UPDATE buy_list_activity
SET reason = ?, entry_price = ?, ...
WHERE id = ?

# 2b. If not exists: Insert new
INSERT INTO buy_list_activity (...) VALUES (...)
```

**Behavior:**
- **First run on 2024-01-15**: Inserts "AAPL ADDED 2024-01-15"
- **Second run on 2024-01-15**: Updates same record (no duplicate!)
- **Run on 2024-01-16**: Inserts new record (different date)
- **Result**: One activity record per ticker+action+date combination ✅

## Example Scenario

### Running Scanner Twice on Same Day

```bash
# First run
python daily_scanner.py --scan-date 2024-01-15

# Database state:
# buy_list:
#   ticker='AAPL', signal_date='2024-01-15', signal_price=150.00
#
# buy_list_activity:
#   id=1, ticker='AAPL', action='ADDED', action_date='2024-01-15'

# Second run (same day, maybe testing)
python daily_scanner.py --scan-date 2024-01-15

# Database state:
# buy_list:
#   ticker='AAPL', signal_date='2024-01-15', signal_price=150.00  ← REPLACED
#
# buy_list_activity:
#   id=1, ticker='AAPL', action='ADDED', action_date='2024-01-15'  ← UPDATED (not duplicated!)
```

### Running Scanner on Different Days

```bash
# Day 1
python daily_scanner.py --scan-date 2024-01-15

# Day 2 (AAPL still in buy list)
python daily_scanner.py --scan-date 2024-01-16

# Database state:
# buy_list:
#   ticker='AAPL', signal_date='2024-01-15', current_price=151.00  ← UPDATED
#
# buy_list_activity:
#   id=1, ticker='AAPL', action='ADDED', action_date='2024-01-15'  ← Original add
#   (no new entry - AAPL wasn't added on 2024-01-16, just updated)
```

### Removing a Signal

```bash
# Day 3 (AAPL breaks trend)
python daily_scanner.py --scan-date 2024-01-17

# Database state:
# buy_list:
#   ticker='AAPL', status='removed'  ← UPDATED to removed
#
# buy_list_activity:
#   id=1, ticker='AAPL', action='ADDED', action_date='2024-01-15'
#   id=2, ticker='AAPL', action='REMOVED', action_date='2024-01-17'  ← New entry
```

## Key Points

1. **Buy List is always unique by ticker**
   - Uses PRIMARY KEY constraint
   - INSERT OR REPLACE ensures no duplicates

2. **Activity Log is unique by ticker+action+date**
   - Uses CHECK before INSERT to prevent duplicates
   - Updates existing record if re-running same day
   - Allows multiple different actions on different dates

3. **Benefits:**
   - Safe to re-run scanner on same date for testing
   - No need to manually clean database between runs
   - Activity history remains clean and accurate

4. **Edge Cases Handled:**
   - Re-running same day: Updates existing records
   - Running different days: Creates new activity only when needed
   - Backward scans: `clear_future_signals()` removes future data first

## Testing

To verify deduplication works:

```python
# Run twice on same date
python daily_scanner.py --scan-date 2024-01-15
python daily_scanner.py --scan-date 2024-01-15

# Check database
python read_buy_list_features.py

# Expected:
# - Each ticker appears exactly once
# - Each ticker+action+date combination in activity appears exactly once
```
