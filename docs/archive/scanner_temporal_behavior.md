# Scanner Temporal Behavior Analysis

## Your Questions Answered

### 1️⃣ Running for the Latest Day (Building on Previous Scans)

**Your understanding is CORRECT!** ✅

When you run for the latest day (e.g., 2025-11-30), here's exactly what happens:

```python
# Line 134: Load buy_list as of scan_date
current_buy_list = db.get_buy_list(active_only=True, as_of_date='2025-11-30')
# This gets: signals where signal_date <= '2025-11-30' AND status='active'

# Line 138: Scan for qualifying stocks on this date
qualifying_tickers = set([s['ticker'] for s in qualifying_stocks])
new_trigger_tickers = set([t['ticker'] for t in new_triggers_today])

# Line 142: ADD - New triggers not already in buy_list
tickers_to_add = [t for t in new_triggers_today if t['ticker'] not in tickers_in_buy_list]

# Line 205: UPDATE - Existing tickers that still qualify (update prices/indicators)
tickers_to_update = tickers_in_buy_list & qualifying_tickers

# Line 145: REMOVE - Tickers in buy_list but no longer qualify (trend broken)
tickers_to_remove = tickers_in_buy_list - qualifying_tickers
```

**Example Scenario (Latest Day)**:

Assume buy_list currently has: `[AAPL, MSFT, GOOGL]` (added on previous days)

On 2025-11-30 scan:
- AAPL: ✅ Still qualifies (trend intact) → **UPDATE** metrics
- MSFT: ❌ No longer qualifies (trend broken) → **REMOVE** from list
- GOOGL: ✅ Still qualifies → **UPDATE** metrics
- NVDA: 🆕 New trigger today → **ADD** to list

Result: `[AAPL, GOOGL, NVDA]`

Activity log:
- `REMOVED: MSFT (2025-11-30, reason: trend_broken)`
- `ADDED: NVDA (2025-11-30, reason: new_trigger)`

---

### 2️⃣ Running for a Date BEFORE the Earliest Day (⚠️ PROBLEM!)

**This reveals a CRITICAL LIMITATION in the current design!**

#### What SHOULD Happen (Ideal):
If earliest signal in buy_list is 2025-11-20, and you run for 2025-11-15:
- buy_list should be EMPTY (no signals existed yet)
- Scanner finds new triggers on 2025-11-15
- Adds them with signal_date='2025-11-15'

#### What ACTUALLY Happens (Current Code):

```python
# Line 134 with scan_date='2025-11-15'
current_buy_list = db.get_buy_list(active_only=True, as_of_date='2025-11-15')
# Query: SELECT * WHERE status='active' AND signal_date <= '2025-11-15'
# Result: EMPTY (because all existing signals have signal_date > 2025-11-15)
```

So far so good! The buy_list will be empty.

**But here's the problem:**

The database has a **single current state**, not historical states:
- The `status` field is CURRENT status (as of now)
- It doesn't track "what was the status on 2025-11-15"

**Concrete Example:**

Current database state (after running 2025-11-20 to 2025-11-28):
```
buy_list table:
ticker  signal_date  status
AAPL    2025-11-20   active
MSFT    2025-11-22   removed  (trend broke on 2025-11-25)
GOOGL   2025-11-23   active
```

Now run for **2025-11-15** (before everything):
1. `current_buy_list` = EMPTY ✅ (signal_date <= 2025-11-15 finds nothing)
2. Scanner finds triggers on 2025-11-15: [TSLA, AMZN]
3. Adds TSLA and AMZN with signal_date='2025-11-15' ✅
4. **Database now has:**
   ```
   ticker  signal_date  status
   TSLA    2025-11-15   active   <- Added by old date scan
   AMZN    2025-11-15   active   <- Added by old date scan
   AAPL    2025-11-20   active   <- Still exists from newer scan!
   MSFT    2025-11-22   removed
   GOOGL   2025-11-23   active   <- Still exists from newer scan!
   ```

**The TEMPORAL INCONSISTENCY:**
- AAPL and GOOGL shouldn't exist when viewing as of 2025-11-15!
- But they're in the database with status='active'

---

## The Root Problem

The buy_list table uses a **stateful design** (single current state) but the scanner tries to use it **temporally** (reconstruct historical states).

### Why This Happens:

| Design Aspect | Current Implementation | Temporal Requirement |
|---------------|----------------------|---------------------|
| Status field | Single value (active/removed) | Needs: removed_date to know WHEN it was removed |
| as_of_date filter | Filters signal_date only | Should filter both signal_date AND removal_date |
| Database model | Mutable state | Needs: Immutable event log |

---

## Solutions (If You Want Proper Temporal Behavior)

### Option 1: Run in Strict Chronological Order (EASIEST)
- Always run dates from earliest → latest
- Never go backwards
- This is what your current date range loop does! ✅

```python
start_date = datetime(2025, 11, 17)  # Start from earliest
end_date = datetime(2025, 11, 28)
# Loop runs in order: 11-17, 11-18, ..., 11-28
```

### Option 2: Add removed_date Column (PROPER FIX)
Modify schema to track WHEN signals were removed:
```sql
ALTER TABLE buy_list ADD COLUMN removed_date DATE;

-- Then modify get_buy_list:
WHERE signal_date <= :as_of_date 
  AND (removed_date IS NULL OR removed_date > :as_of_date)
```

### Option 3: Use buy_list_activity as Source of Truth
Reconstruct buy_list state from activity log:
```python
def get_buy_list_as_of_date(date):
    # Get all ADDED events on or before date
    # Get all REMOVED events on or before date
    # Calculate net: ADDED - REMOVED = active list
```

---

## Recommendation for Your Use Case

**Since you're backfilling historical data:**

✅ **Use Option 1** - Run in strict chronological order
- Your current date range loop already does this
- No code changes needed
- Just ensure you NEVER run an earlier date after a later date

❌ **Don't run dates out of order** - The database will become inconsistent

📝 **Current behavior is correct IF:**
- You run dates sequentially (earliest → latest)
- You never re-run old dates after newer ones
- You treat the database as an append-only log during backfill

---

## Summary

| Scenario | Current Behavior | Correct? |
|----------|------------------|----------|
| Run latest day (builds on previous) | ✅ Adds new, Updates existing, Removes broken | YES ✅ |
| Run old date (before earliest) in CLEAN database | ✅ Empty buy_list, adds triggers from that date | YES ✅ |
| Run old date AFTER running newer dates | ⚠️ Creates temporal inconsistency | NO ❌ |

**Your workflow is safe** as long as you run dates chronologically! 🎯
