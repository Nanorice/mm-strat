# Missing Snapshots Root Cause Analysis

## Problem Summary
951 trades in Dataset B (2.3%) cannot find matching snapshots in Dataset A, causing them to be excluded from the merged training dataset.

## Root Cause: Asymmetric Ticker Filtering

**Dataset A and Dataset B use different ticker universes**, creating a mismatch:

### Dataset A (build_dataset_a.py:324-326)
```python
from src.utils import filter_etfs
tickers = filter_etfs(tickers)
```
- ✅ Filters out ETFs, REITs, and SPACs
- ✅ Only processes "operating companies"

### Dataset B (trade_simulator_fast.py:187)
```python
tickers = self.data_repo.update_universe()
```
- ❌ Uses the FULL universe (no filtering)
- ❌ Includes ETFs, REITs, and SPACs

## Evidence: Missing Tickers Are REITs

All top missing tickers are confirmed REITs in `data/etf_fund_tickers.txt`:

```
UTHR: 44 trades   → Likely ends with 'R', flagged as suspicious, filtered as SPAC/REIT
NTRS: 33 trades   → Northern Trust Corporation (in ETF exclusion list)
ESS:  31 trades   → Essex Property Trust (REIT, in exclusion list)
AKR:  31 trades   → Acadia Realty Trust (REIT, in exclusion list)
FR:   30 trades   → First Industrial Realty Trust (REIT)
FRT:  30 trades   → Federal Realty Investment Trust (REIT, in exclusion list)
DLR:  28 trades   → Digital Realty Trust (REIT, in exclusion list)
LXP:  27 trades   → LXP Industrial Trust (REIT)
CPT:  27 trades   → Camden Property Trust (REIT)
VNO:  26 trades   → Vornado Realty Trust (REIT)
```

## How the Filter Works (src/utils.py:116-192)

The `filter_etfs()` function has TWO stages:

### Stage 1: ETF/Fund Exclusion List
- Removes tickers in `data/etf_fund_tickers.txt`
- Filters: NTRS, ESS, AKR, FRT, DLR (confirmed)

### Stage 2: SPAC/Shell Detection (filter_spacs=True)
```python
# Checks tickers ending with U/W/R as "suspicious"
is_suspicious = (
    (ticker.endswith(('U', 'W', 'R')) and len(ticker) > 2) or
    ('acquisition' in ticker_lower) or
    ...
)
```
- UTHR ends with 'R' → flagged as suspicious
- Then checks company profile for keywords like 'acquisition', 'shell', 'units'
- If profile contains these keywords, ticker is EXCLUDED

## Why This Happens

1. **Dataset A Creation:**
   - Loads universe from FMP screener (~1,730 tickers)
   - Applies `filter_etfs()` → ~1,600 tickers (operating companies only)
   - Builds features for filtered tickers

2. **Dataset B Creation:**
   - Loads universe from FMP screener (~1,730 tickers)
   - **NO FILTERING APPLIED** → all 1,730 tickers
   - Generates trades for all tickers (including REITs)

3. **Merge:**
   - Tries to match Dataset B trades (1,730 tickers) with Dataset A snapshots (1,600 tickers)
   - 951 trades from the ~130 filtered-out tickers → MISSING SNAPSHOTS

## Solutions

### Option 1: Filter Dataset B to Match Dataset A ✅ RECOMMENDED
Apply the same filter during Dataset B creation to ensure alignment.

**Implementation:**
```python
# In build_dataset_b.py or trade_simulator_fast.py
from src.utils import filter_etfs

tickers = self.data_repo.update_universe()
tickers = filter_etfs(tickers)  # Add this line
```

**Pros:**
- Simple, one-line fix
- Maintains consistency between datasets
- REITs/ETFs have different characteristics anyway (may not be suitable for the strategy)

**Cons:**
- Loses 951 trades (but they're from filtered tickers anyway)

### Option 2: Rebuild Dataset A Without Filtering
Remove the filter from Dataset A to include all tickers.

**Implementation:**
```python
# In build_dataset_a.py:324-326
# Comment out or remove:
# from src.utils import filter_etfs
# tickers = filter_etfs(tickers)
```

**Pros:**
- No data loss
- Maximum coverage

**Cons:**
- Adds ~130 tickers (ETFs/REITs) to Dataset A
- Longer build time
- May include tickers unsuitable for the SEPA strategy

### Option 3: Rebuild Dataset A from Dataset B Tickers
Use the `--from-dataset-b` flag to ensure perfect alignment.

**Implementation:**
```bash
python build_dataset_a.py \\
    --start 2020-01-01 \\
    --end 2026-01-11 \\
    --from-dataset-b data/ml/dataset_b.parquet \\
    --include-fundamentals
```

**Pros:**
- Guaranteed zero missing snapshots
- Only builds features for tickers that have trades
- Most efficient approach

**Cons:**
- Requires rebuilding Dataset A

## Recommendation

**Use Option 3: Rebuild Dataset A from Dataset B**

This is the cleanest solution because:
1. Zero missing snapshots guaranteed
2. Only builds features for tickers that actually have trades
3. Saves compute time (fewer tickers to process)
4. Future-proof: any changes to Dataset B will automatically propagate

Then, for future datasets, apply **Option 1** to prevent this from happening again.

## Prevention for Future Datasets

Add this check to `prepare_training_dataset.py`:

```python
def validate_ticker_alignment(self):
    """Ensure Dataset A and B have the same tickers."""
    a_tickers = set(self.dataset_a['ticker'].unique())
    b_tickers = set(self.dataset_b['ticker'].unique())

    missing_in_a = b_tickers - a_tickers
    if missing_in_a:
        logger.warning(f"{len(missing_in_a)} tickers in Dataset B but not in Dataset A")
        logger.warning(f"Sample missing tickers: {sorted(missing_in_a)[:10]}")
        return False
    return True
```

## Impact Assessment

**Current State:**
- Total Dataset B trades: 40,469
- Missing snapshots: 951 (2.3%)
- Match rate: 97.7%

**After Fix:**
- Expected match rate: 100%
- Lost trades if using Option 1: 951 (all from REITs/ETFs)
- Lost trades if using Option 3: 0

The 2.3% missing rate is **low enough to not significantly impact model training**, but fixing it ensures data integrity and eliminates potential sampling bias.
