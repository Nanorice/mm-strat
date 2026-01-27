# IndexError Fix - Dashboard Deep Dive Panel

## Error

```
IndexError: single positional indexer is out-of-bounds
```

**Location:** Signal Review page → Deep Dive panel when selecting ROST (or any ticker not in active buy_list)

---

## Root Cause

After changing the ticker dropdown to show **all cached tickers** (not just buy_list), users could select tickers that exist in the price cache but are NOT in the active buy_list.

**Problematic code (line 118):**
```python
ticker_row = buy_list_df[buy_list_df['ticker'] == ticker].iloc[0]
```

**What happened:**
1. User selects ROST from dropdown (ROST is in cache)
2. ROST is NOT in active buy_list (removed/rejected earlier)
3. Filter `buy_list_df[buy_list_df['ticker'] == ticker]` returns empty DataFrame
4. `.iloc[0]` on empty DataFrame throws `IndexError`

---

## Solution

Check if ticker exists in buy_list before accessing it:

**Fixed code:**
```python
def render_deep_dive_panel(ticker: str, buy_list_df: pd.DataFrame,
                           db: DatabaseManager, data_repo: DataRepository):
    st.subheader(f"🔍 Deep Dive: {ticker}")

    # Check if ticker is in buy_list (might not be if selected from cache)
    ticker_data = buy_list_df[buy_list_df['ticker'] == ticker]
    is_in_buy_list = not ticker_data.empty

    if is_in_buy_list:
        ticker_row = ticker_data.iloc[0]
    else:
        ticker_row = None  # Ticker in cache but not in buy_list

    # Layout: Chart (left) | Explainability (right)
    col1, col2 = st.columns([2, 1])

    with col1:
        # Chart works for ANY cached ticker
        st.markdown("#### Price Chart (6 Months)")
        chart = create_candlestick_chart(ticker, data_repo)
        if chart:
            st.plotly_chart(chart, use_container_width=True)
        else:
            st.warning(f"Price data not available for {ticker}")

    with col2:
        if is_in_buy_list:
            # Show ML features + action buttons (only for buy_list tickers)
            st.markdown("#### Model Explainability")
            render_ml_features(ticker_row)

            st.markdown("#### Actions")
            render_action_buttons(ticker, db)
        else:
            # Ticker not in buy_list - show helpful message
            st.info(f"**{ticker}** is not in the active buy list.")
            st.markdown("This ticker is cached but has no active signal. You can:")
            st.markdown("- View the price chart on the left")
            st.markdown("- Add manually via 'Manual Override' page")
```

---

## Behavior

### Before Fix
```
1. Select ROST from dropdown
2. ❌ IndexError: single positional indexer is out-of-bounds
3. Dashboard crashes
```

### After Fix
```
1. Select ROST from dropdown
2. ✅ Chart displays on left
3. ✅ Right side shows:
   "ROST is not in the active buy list.
    This ticker is cached but has no active signal. You can:
    - View the price chart on the left
    - Add manually via 'Manual Override' page"
```

---

## Edge Cases Handled

### Case 1: Ticker in buy_list (Normal)
- ✅ Chart displays
- ✅ ML features shown
- ✅ Action buttons (Reject/Archive) available

### Case 2: Ticker in cache but NOT in buy_list (ROST scenario)
- ✅ Chart displays
- ℹ️ Informative message instead of features
- ❌ No action buttons (can't reject/archive what's not in buy_list)

### Case 3: Ticker not in cache at all
- ⚠️ Chart shows "Price data not available"
- ℹ️ Same informative message

### Case 4: Manual entry of arbitrary ticker
- Works same as Case 2 or 3 (depending on cache availability)

---

## Why This Design Makes Sense

**Original intent:** Allow users to view charts for ANY cached ticker, not just active signals

**This fix enables:**
1. ✅ View historical charts for removed/rejected signals
2. ✅ Compare active signals to non-signals
3. ✅ Post-mortem analysis of past decisions
4. ✅ Ad-hoc research on any cached ticker

**Graceful degradation:**
- Tickers in buy_list: Full functionality (chart + features + actions)
- Tickers NOT in buy_list: Chart-only mode with helpful guidance

---

## Files Modified

**dashboard.py** (lines 113-149)
- Added `is_in_buy_list` check
- Conditional rendering of ML features and action buttons
- Helpful message for non-buy_list tickers

---

## Testing

### Test 1: Buy_list Ticker (NVDA)
```
1. Select NVDA (in buy_list)
2. Expected: Chart + ML features + action buttons
3. ✅ Works
```

### Test 2: Cached but Removed Ticker (ROST)
```
1. Select ROST (in cache, not in buy_list)
2. Expected: Chart + info message
3. ✅ Fixed (was IndexError before)
```

### Test 3: Manual Entry
```
1. Type "AAPL" in manual entry box
2. Expected: Same as Test 1 or 2 depending on buy_list status
3. ✅ Works
```

### Test 4: Non-existent Ticker
```
1. Type "FAKEXYZ" in manual entry
2. Expected: No chart + info message
3. ✅ Works
```

---

## Summary

**Error:** `IndexError` when viewing cached tickers not in buy_list

**Fix:** Check if ticker exists in buy_list before accessing row

**Result:**
- ✅ No more crashes
- ✅ Graceful handling of non-buy_list tickers
- ✅ Chart-only view for historical analysis
- ✅ Helpful user guidance
