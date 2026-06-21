# Alpha Parity Investigation & Fixes

We identified two critical categories of discrepancies between the Python (`WorldQuant_101.py`) and SQL (`data_curator_duckdb.py`) implementations of alpha factors.

## 1. VWAP Scaling Bug (Python)

The Python implementation of VWAP in `WorldQuant_101.py` contained a scaling error that made the VWAP value ~1/100th of the actual price.

**Previous Python Code:**
```python
self.volume = df_data['S_DQ_VOLUME'] * 100  # Multiplied by 100
self.vwap = (df_data['S_DQ_AMOUNT']*1000)/(df_data['S_DQ_VOLUME']*100 + 1)
```
- **Issue:** The volume was artificially inflated by 100x variance, while the amount was correct (assuming `AMOUNT` is in thousands). This resulted in `VWAP ≈ Price / 100`.
- **Impact:** Alphas dependent on VWAP (e.g., `alpha041 = sqrt(high*low) - vwap`) were calculating `Price - (Price/100)` ≈ `Price`, instead of the intended small deviation `Price - VWAP`. This destroys the alpha's signal.
- **Fix:** Removed the `*100` multiplier and aligned the formula to `(Amount * 1000) / Volume`.

## 2. Slope Logic Inversion (SQL)

Alphas 046, 049, and 051 rely on the change in slope (acceleration/deceleration) of the close price. The SQL implementation was calculating the opposite of the Python logic.

**Python Logic (Acceleration):**
```python
((delay(close, 20) - delay(close, 10)) / 10) - ((delay(close, 10) - close) / 10)
```
- Term 1: `(Close_{t-20} - Close_{t-10})/10` (Old Slope, inverted sign)
- Term 2: `(Close_{t-10} - Close_t)/10` (New Slope, inverted sign)
- Result: `(-Old_Slope) - (-New_Slope)` = `New_Slope - Old_Slope` = **Acceleration**

**Previous SQL Logic (Deceleration):**
```sql
((close_lag10 - close_lag20) / 10.0) - ((close - close_lag10) / 10.0)
```
- Term 1: `(Close_{t-10} - Close_{t-20})/10` (Old Slope)
- Term 2: `(Close_t - Close_{t-10})/10` (New Slope)
- Result: `Old_Slope - New_Slope` = **Deceleration** (Negative Acceleration)

- **Impact:** The alphas were triggering on the exact opposite conditions (e.g., accelerating downside instead of decelerating).
- **Fix:** Inverted the subtraction in all three SQL alphas to match `New_Slope - Old_Slope`.

## Next Steps

1. **Recompute Features:** Run `data_curator_duckdb.py --update-features --recompute` to apply the SQL fixes.
2. **Review Python VWAP:** Verify if `S_DQ_AMOUNT` is indeed in thousands. If not, further adjustment may be needed.
3. **Validate Parity:** Run `validate_alpha_parity.py` again. We expect significantly higher correlations for the affected alphas.
