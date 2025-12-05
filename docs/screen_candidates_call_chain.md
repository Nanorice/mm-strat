# Call Chain Analysis: screen_candidates() Usage

## Summary

`screen_candidates()` is ONLY used for **EXIT logic** (checking if SEPA criteria are still met). It's NOT used for entry signal detection in any of the three scenarios.

---

## Complete Call Chains

### 1. Sequential Dataset B Builder (--slow flag)

**File:** `build_dataset_b.py` → `TradeSimulator`

```
build_dataset_b.py (--slow)
  └─ TradeSimulator.run_simulation()
      ├─ ENTRY DETECTION:
      │   └─ _check_for_entries(date, enriched_data)
      │       └─ strategy.batch_scan_universe(enriched_data, scan_date=date)
      │           └─ VectorizedSEPAScreener.batch_screen_universe()  ✅ Uses correct RS > 0
      │
      └─ EXIT DETECTION:
          └─ _check_for_exits(date, enriched_data)
              └─ strategy.screen_candidates(ticker_df, date)  ❌ Uses detect_stage2_uptrend()
                  └─ TechnicalAnalysis.detect_stage2_uptrend()
                      └─ Uses Close > Low_52W * 1.3 (WRONG!)
```

**Lines:**
- Entry: [`trade_simulator.py:L318-L320`](file:///c:/Users/Hang/PycharmProjects/quantamental/src/trade_simulator.py#L318-L320)
- Exit: [`trade_simulator.py:L365`](file:///c:/Users/Hang/PycharmProjects/quantamental/src/trade_simulator.py#L365)

---

### 2. Vectorized Dataset B Builder (default, fast mode)

**File:** `build_dataset_b.py` → `FastTradeSimulator`

```
build_dataset_b.py (default)
  └─ FastTradeSimulator.run_simulation()
      ├─ ENTRY DETECTION:
      │   └─ _detect_signals_using_strategy(enriched_data)
      │       └─ _vectorized_sepa_screen(df)
      │           └─ VectorizedSEPAScreener.screen_single_ticker()  ✅ Uses correct RS > 0
      │
      └─ EXIT DETECTION:
          └─ _find_exit_vectorized(ticker_df, entry_date, entry_price)
              ├─ PRIMARY: Uses precomputed SEPA_Status column  ✅ Correct RS > 0
              │   (from _detect_signals_using_strategy)
              │
              └─ FALLBACK (if SEPA_Status missing):
                  └─ strategy.screen_candidates(ticker_df, date)  ❌ Uses detect_stage2_uptrend()
                      └─ TechnicalAnalysis.detect_stage2_uptrend()
                          └─ Uses Close > Low_52W * 1.3 (WRONG!)
```

**Lines:**
- Entry: [`trade_simulator_fast.py:L166`](file:///c:/Users/Hang/PycharmProjects/quantamental/src/trade_simulator_fast.py#L166)
- Exit (Primary): [`trade_simulator_fast.py:L370-L381`](file:///c:/Users/Hang/PycharmProjects/quantamental/src/trade_simulator_fast.py#L370-L381)
- Exit (Fallback): [`trade_simulator_fast.py:L387`](file:///c:/Users/Hang/PycharmProjects/quantamental/src/trade_simulator_fast.py#L387)

---

### 3. Daily Scanner (optimized_scanner.py)

**File:** `optimized_scanner.py`

```
optimized_scanner.py
  └─ (Does NOT call screen_candidates at all!)
  └─ Uses VectorizedSEPAScreener.batch_screen_universe() directly  ✅ Correct RS > 0
```

**Verification:**
```powershell
# Search confirms NO usage in optimized_scanner.py
grep -n "screen_candidates" optimized_scanner.py
# Returns: (no results)
```

The daily scanner **never uses** `screen_candidates()` - it calls `VectorizedSEPAScreener` directly, so it's already correct!

---

## Impact Summary

| Component | Entry Logic | Exit Logic | Uses screen_candidates? | Impact |
|-----------|-------------|------------|------------------------|--------|
| **Sequential Builder** | ✅ Correct (VectorizedSEPAScreener) | ❌ Wrong (detect_stage2_uptrend) | Yes (exits only) | **High** |
| **Vectorized Builder** | ✅ Correct (VectorizedSEPAScreener) | ⚠️ Mostly correct (uses SEPA_Status), fallback is wrong | Yes (fallback only) | **Low** |
| **Daily Scanner** | ✅ Correct (VectorizedSEPAScreener) | N/A (no exits) | No | **None** |

---

## Key Insight

**The discrepancy is primarily in EXITS, not ENTRIES:**

1. **Sequential simulator** uses wrong exit criteria (`detect_stage2_uptrend` with Low_52W check)
2. **Vectorized simulator** uses correct exit criteria (precomputed `SEPA_Status` with RS > 0)
3. This causes trades to exit at different times, leading to:
   - Different trade counts (some trades exit earlier/later)
   - Different win rates (exit timing affects returns)

---

## Solution

Fixing `screen_candidates()` to use `VectorizedSEPAScreener.screen_at_date()` will:
- ✅ Fix sequential simulator exits
- ✅ Fix vectorized simulator fallback path
- ✅ Ensure all code paths use identical SEPA criteria
- ✅ No impact on daily scanner (already correct)

**Single line change in [`strategy.py:L91`](file:///c:/Users/Hang/PycharmProjects/quantamental/src/strategy.py#L91):**
```python
# OLD:
stage2 = self.ta.detect_stage2_uptrend(df)

# NEW:
return VectorizedSEPAScreener.screen_at_date(df, date)
```
