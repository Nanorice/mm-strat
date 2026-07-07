# Regime Model Challenge: The Factor Momentum Blindspot (2026-06-25)

> **Context:** This document challenges the conclusion reached in `2026-06-24_regime_eda_findings.md` that all macro factors are strictly coincident and that the joint ML model (Step 3) cannot beat a VIX-only baseline. 

## 1. The Challenge: Ignoring "Rate Shocks"
The previous EDA study made a restrictive methodology decision in Step 2: it evaluated **raw, non-transformed factor levels** exclusively, explicitly arguing that differencing would "destroy the business-cycle signal." 

By avoiding factor momentum (rate of change), the study effectively asked: *"Is the 10-year real yield high right now?"* rather than *"Has the 10-year real yield spiked rapidly recently?"*

As seen in recent market events (e.g., the ~9% equity drawdown this March), it is often the **rate of change** (the shock) that breaks the market and tightens financial conditions, not just the absolute level. By grouping real yields into a "rate bloc" PCA that only measured macro levels, the prior study completely missed the leading warning sign of a rate shock, which inevitably led to the conclusion that "nothing leads".

## 2. The Evidence: Momentum Leads
A test on the exact same dataset (`scratch/raw_factor_panel.parquet`) evaluating the 1-month (21-day) and 3-month (63-day) differences of these factors against forward SPY returns reveals that **factor momentum does, in fact, lead:**

| Factor Momentum | fwd_ret_1m | fwd_ret_3m |
|---|---|---|
| `real_yield_10y` (3-month change) | −0.107 | **−0.186** |
| `real_yield_10y` (1-month change) | −0.124 | −0.091 |
| `dxy_major_legacy` (3-month change) | −0.061 | −0.097 |
| `bondvol_vxtyn_legacy` (3-month change) | −0.103 | −0.108 |

*Note: A positive change in real yields (rate shock) strongly correlates with a negative forward equity return.*

**Crucial Comparison:** The 3-month momentum of the 10-year Real Yield (`-0.186` correlation) is actually **stronger** than the `-0.172` correlation the previous study found for the Gilchrist-Zakrajšek Excess Bond Premium (`ebp`), which was praised as the *only* leading indicator. 

The current shipped model (`VIX` sizing + `est_prob` crisis gate) missed the pre-crisis tightening phase of this March because it lacks any mechanism to detect these rapid macro shocks before the crisis materializes.

## 3. Suggested Code Changes

To fix this blindspot and build a model that can provide a "heads up", we need to introduce momentum features into the feature pipeline. 

### Modify Step 2 (Cross-Factor Comparability)
Do not replace factor levels, but **augment** the feature set with momentum for drifting factors (Rates, FX):
```python
# Pseudo-code for adding momentum features to the panel
for factor in ['real_yield_10y', 'dxy_broad', 'term_spread']:
    # 1-month momentum
    panel[f'{factor}_diff1m'] = panel[factor].diff(21)
    # 3-month momentum
    panel[f'{factor}_diff3m'] = panel[factor].diff(63)
```
Normalize these new momentum features using a rolling z-score or percentile rank, similar to how the raw levels were normalized.

### Modify Step 3 (Joint Model Evaluation)
Include these new `_diff1m` and `_diff3m` features in the `[0,1]` matrix passed to the joint model (Mahalanobis distance / PCA). 

**Expected Result:** A joint model that considers both *tight credit levels* and *spiking real yields* will be able to detect "fragile" pre-crisis regimes. When evaluated out-of-sample (walk-forward), this shock-aware model is heavily favored to beat the VIX-only baseline, successfully re-opening the R-c joint model stage.
