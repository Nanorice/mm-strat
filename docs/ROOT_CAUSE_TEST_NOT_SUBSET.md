# Root Cause: Why Test Is NOT a Subset of Production

**Date:** 2026-02-07
**Issue:** Test has 6,256 trades NOT in Production, despite using stricter filters
**Status:** ✅ ROOT CAUSE IDENTIFIED

---

## Current Results

```
D1 Test: 12,112 trades
D1 Prod: 11,674 trades

Comparison (by ticker, date):
  Common trades: 5,856
  Only in Test: 6,256 (51.7%)
  Only in Prod: 5,818 (49.8%)
```

**Expected:** Test ⊆ Production (Test should be subset with stricter filters)
**Actual:** Only 48.3% overlap - they're selecting DIFFERENT trades!

---

## Root Cause: Entry Timing Mismatch

### Key Finding

**97 out of 100 tickers** trade on **DIFFERENT DATES** in Test vs Production.

Same stock, different entry timing!

### Example: ARES

```
Test:  17 trades, includes 2021-08-13, 2024-05-15
Prod:  15 trades, includes 2020-12-15, 2020-04-09

Common: Only 8 trades on same dates
```

### Why This Happens

#### Production C9: `rs_rating > 0`
- Allows entry as soon as RS turns **slightly positive** (rs_rating = 0.01)
- **Earlier, weaker signals** - catches breakouts at lower RS levels
- May enter before stock reaches top 30% RS

#### Test C9: `rs_rating >= P70 AND rs_rating > 0`
- Requires stock to be in **top 30% RS ranking**
- **Later, stronger signals** - waits for confirmed RS strength
- Delays entry until RS threshold is met

### Concrete Example

**Stock XYZ breaks out on 2024-05-10:**

| Date | RS Rating | Prod C9 | Test C9 | Entry? |
|------|-----------|---------|---------|--------|
| 2024-05-08 | 0.05 (40th percentile) | ✅ Pass | ❌ Fail | Prod enters |
| 2024-05-09 | 0.08 (55th percentile) | ✅ Pass | ❌ Fail | - |
| 2024-05-10 | 0.15 (75th percentile) | ✅ Pass | ✅ Pass | Test enters |

**Result:**
- Production enters on **2024-05-08** (rs_rating = 0.05)
- Test enters on **2024-05-10** (rs_rating = 0.15, P70)
- **Same stock, 2-day difference** → Different trade_id, different outcomes

---

## Why They're NOT Subsets

### The Math

```
Test ⊆ Prod requires: (Test C9) ⊆ (Prod C9)

Test C9: rs_rating >= P70 AND rs_rating > 0
Prod C9: rs_rating > 0

Test C9 is STRICTER, so theoretically Test ⊆ Prod...
BUT this only applies to STATIC DATA at a SINGLE POINT IN TIME!
```

### The Timing Problem

Both pipelines scan for **0→1 transitions** (signal goes False → True).

**Same stock can satisfy breakout conditions on DIFFERENT DAYS:**

1. **Production sees transition earlier** (when rs_rating crosses 0)
2. **Test sees transition later** (when rs_rating crosses P70)
3. They detect **different transition dates** for the same stock
4. Result: **Different trades** even though Test has stricter filter

---

## Implications

### Why Test Has MORE Trades (Not Less)

Despite stricter C9, Test can have more trades because:

1. **Test delays entry** until top 30% RS
2. By the time Test enters, Production may have **already exited** (stop-loss or exit signal)
3. Test "misses" some of Production's early entries (good - lower quality)
4. But Test "catches" some breakouts that Production missed (stock wasn't RS positive when it broke out, but later became top 30%)

### Example Scenario

**Stock ABC:**
- **Day 1:** Breaks out with rs_rating = -0.1 (negative)
  - Prod: ❌ Rejects (rs_rating < 0)
  - Test: ❌ Rejects (rs_rating < 0)

- **Day 5:** RS improves to rs_rating = 0.05 (positive, 40th percentile)
  - Prod: ✅ Enters here
  - Test: ❌ Still waiting (not P70 yet)

- **Day 8:** Prod hits stop-loss, exits
  - Prod: Trade closed (loss)

- **Day 12:** RS reaches 0.22 (75th percentile), new breakout signal
  - Prod: ❌ Already traded and closed
  - Test: ✅ Enters here (first time P70 met)

**Result:** Test has this trade, Production doesn't!

---

## The Filter Paradox

**Test's stricter C9 does NOT guarantee Test ⊆ Production** because:

### What We Expected (Static Logic)
```
If Test_C9 ⊂ Prod_C9, then Test_trades ⊆ Prod_trades
```

### What Actually Happens (Dynamic Logic)
```
Entry timing depends on WHEN conditions first become true.
Stricter filter → LATER entry → DIFFERENT trade
```

---

## Solution Options

### Option 1: Accept Different Populations (Current State)
**Keep as-is:** Test and Production have different selection philosophies
- **Prod:** Early entry, lower quality bar (rs_rating > 0)
- **Test:** Late entry, higher quality bar (rs_rating >= P70)
- **Use case:** A/B test different strategies

**Pros:**
- Tests hypothesis: "Does waiting for top 30% RS improve win rate?"
- No code changes needed

**Cons:**
- Hard to directly compare (different entry timing)
- Test is NOT a "faster Production prototype"

---

### Option 2: Align Test to Production Timing (Recommended)

**Make Test a true subset** by using **identical C9 filter**:

**Change Test C9 from:**
```python
c9 = (df_matrix['rs_rating'] >= df_matrix['rs_pct70']) & (df_matrix['rs_rating'] > 0)
```

**To:**
```python
c9 = df_matrix['rs_rating'] > 0  # Match Production exactly
```

**Result:**
- Test ⊆ Production (guaranteed)
- Test is "fast Production" for experimentation
- Can still test other filters (C11, C12, exits) independently

**Cons:**
- Loses cross-sectional RS ranking experiment

---

### Option 3: Make Production Use Cross-Sectional Ranking

**Update Production C9** to match Test's P70 logic.

**Impact:**
- Both pipelines use same entry timing
- Aligns with true Minervini methodology (top 30% RS)
- Major change to production backtests

**Complexity:** HIGH - requires universe-wide data in `trade_simulator_fast.py`

---

## Recommendation

**Option 2: Align Test to Production (rs_rating > 0)**

**Rationale:**
1. The original goal was to make Test a "faster pipeline" for experimentation
2. Entry timing differences make comparison impossible
3. If you want to test "top 30% RS" strategy, do it SEPARATELY as a new strategy variant
4. For pipeline validation, Test should replicate Production logic exactly

**Next Steps:**
1. Remove P70 filter from Test C9
2. Re-run Test scan
3. Verify Test ⊆ Production
4. Use Test for rapid iteration on OTHER features (C11 variations, exit rules, etc.)

---

## Files Referenced

- `src/vectorized_screening.py:502` - Test C9 (add_sepa_status_column)
- `src/vectorized_screening.py:97` - Production C9 (screen_single_ticker_split)
- `src/pipeline/data_pipeline_test.py:126` - Test pipeline entry point

---

## Summary

**Why Test ≠ Subset of Production:**
- Different entry timing due to C9 filter differences
- Stricter filter → Later entry → Different trades
- Not a quality issue - it's a timing issue

**Solution:**
- Use identical C9 filters for both pipelines
- Test other improvements (C11, exits) independently
- Save cross-sectional RS ranking for dedicated strategy research
