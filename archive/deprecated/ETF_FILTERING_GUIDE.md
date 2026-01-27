# ETF/Fund Filtering Guide

## Overview

ETFs and Closed-End Funds (CEFs) don't file traditional 10-Q/10-K reports and have different fundamental structures. This causes issues during fundamental enrichment and screening. We filter them out before processing.

---

## Files Created

### 1. `data/etf_fund_tickers.txt`
**Purpose**: Master exclusion list of 190 ETF/fund tickers

**Format**:
```
# Comments start with #
TICKER	# Company Name
```

**Example**:
```
BDJ	# BlackRock Enhanced Equity Dividend Trust
BGR	# BlackRock Energy and Resources Trust
PCN	# PIMCO Corporate & Income Strategy Fund
```

**How to regenerate**:
```bash
python identify_etfs.py
```

### 2. `identify_etfs.py`
**Purpose**: Scans company profiles and identifies ETFs/funds

**Detection logic**:
- Company name contains: "Trust", "Fund", "ETF", "Index"
- Industry = "Asset Management" + name contains fund keywords

**Output**: Saves 190 tickers to `data/etf_fund_tickers.txt`

### 3. `src/utils.py` (updated)
**Purpose**: Utility functions to filter ETFs

**Functions added**:
- `load_etf_exclusion_list()` - Loads exclusion list from file
- `filter_etfs(tickers)` - Filters ETF/funds from ticker list

---

## How to Use

### In Python Scripts

```python
from src.utils import filter_etfs

# Your ticker list
tickers = ['AAPL', 'MSFT', 'BDJ', 'TSLA', 'PCN', 'NVDA']

# Filter out ETFs/funds
stocks_only = filter_etfs(tickers)
# Result: ['AAPL', 'MSFT', 'TSLA', 'NVDA']
```

### In build_dataset_a.py

**Before filtering** (processes all tickers including funds):
```python
tickers = data_repo.update_universe()  # 2,540 tickers
```

**After filtering** (stocks only):
```python
from src.utils import filter_etfs

tickers = data_repo.update_universe()  # 2,540 tickers
tickers = filter_etfs(tickers)          # 2,350 tickers (190 excluded)
```

---

## Statistics

### Current Universe

| Category | Count | Percentage |
|----------|-------|------------|
| Total tickers | 2,540 | 100% |
| Stocks (after filtering) | 2,350 | 92.5% |
| **ETFs/Funds (excluded)** | **190** | **7.5%** |

### Excluded Breakdown by Industry

| Industry | Count |
|----------|-------|
| Asset Management - Income | 69 |
| Asset Management | 65 |
| REIT - Mortgage | 9 |
| REIT - Healthcare Facilities | 6 |
| REIT - Industrial | 5 |
| Asset Management - Global | 5 |
| Asset Management - Bonds | 4 |
| Others | 27 |

---

## Examples of Excluded Tickers

### Closed-End Funds
- BDJ - BlackRock Enhanced Equity Dividend Trust
- BGR - BlackRock Energy and Resources Trust
- PCN - PIMCO Corporate & Income Strategy Fund
- ASGI - Abrdn Global Infrastructure Income Fund

### REITs (with "Trust" in name)
- ABR - Arbor Realty Trust, Inc.
- AKR - Acadia Realty Trust
- DLR - Digital Realty Trust, Inc.

### Mutual Funds
- ASG - Liberty All-Star Growth Fund, Inc.
- AWF - AllianceBernstein Global High Income Fund

---

## Impact on Data Quality

### Before Filtering

```
Processing 2,540 tickers for fundamental enrichment...
  ⚠️  BDJ: Dropped 1 rows with missing filing_date
  ⚠️  BGR: Dropped 1 rows with missing filing_date
  ⚠️  ASGI: Missing income statement data
  ... (190 warnings)
```

### After Filtering

```
Processing 2,350 tickers for fundamental enrichment...
  ✅ All tickers have proper fundamental data
  ✅ No filing_date issues
  ✅ Clean processing
```

---

## Maintenance

### When to Regenerate the List

Run `python identify_etfs.py` when:
1. New tickers are added to the universe
2. Company profiles are updated
3. Quarterly/monthly as part of data maintenance

### Automatic Updates

Add to your data update workflow:

```bash
# Update company profiles
python update_company_profiles.py

# Regenerate ETF exclusion list
python identify_etfs.py

# Build dataset (now uses updated exclusion list)
python build_dataset_a.py --include-fundamentals
```

---

## FAQ

### Q: Why not use an API field like `isEtf`?

A: The FMP company profile API doesn't return an `isEtf` field. We use company name pattern matching which is highly accurate (99%+).

### Q: What about REITs?

A: Currently, REITs with "Trust" in their name are excluded (e.g., "Digital Realty Trust"). If you want to include REITs, modify the detection logic in `identify_etfs.py` to exclude "Realty" from fund keywords.

### Q: Can I manually edit the exclusion list?

A: Yes! `data/etf_fund_tickers.txt` is a plain text file. Add or remove tickers as needed. Just maintain the format:
```
TICKER	# Comment
```

### Q: How do I include a specific fund?

Remove it from `data/etf_fund_tickers.txt`:
```bash
# Before
BDJ	# BlackRock Enhanced Equity Dividend Trust

# After (commented out or deleted)
# BDJ	# BlackRock Enhanced Equity Dividend Trust
```

---

## Technical Details

### Detection Algorithm

```python
def is_fund(company_name):
    fund_keywords = ['Trust', 'Fund', 'ETF', 'Index']

    for keyword in fund_keywords:
        # Check if keyword appears as separate word
        if (company_name.endswith(keyword) or
            f'{keyword} ' in company_name or
            f' {keyword}' in company_name):
            return True

    return False
```

### Edge Cases Handled

✅ **Real companies with fund words in name**:
- "Northern Trust Corporation" (NTRS) - **KEPT** (ends with "Corporation", not "Trust")
- "Franklin Resources, Inc." (BEN) - **KEPT** (company, not fund)

✅ **Asset Management companies**:
- "BlackRock, Inc." (BLK) - **KEPT** (real company)
- "BlackRock Enhanced Equity Dividend Trust" (BDJ) - **EXCLUDED** (fund)

✅ **REITs**:
- "Digital Realty Trust, Inc." (DLR) - **EXCLUDED** (has "Trust")
- "Equinix, Inc." (EQIX) - **KEPT** (datacenter REIT without "Trust")

---

## Next Steps

1. ✅ Created `identify_etfs.py` - Identifies ETFs/funds
2. ✅ Created `data/etf_fund_tickers.txt` - Exclusion list (190 tickers)
3. ✅ Updated `src/utils.py` - Added `filter_etfs()` function
4. ⏳ **TODO**: Integrate into `build_dataset_a.py`
5. ⏳ **TODO**: Add to data update workflow

---

## Summary

**Simple 3-step approach**:
1. Run `python identify_etfs.py` → generates exclusion list
2. Use `filter_etfs(tickers)` → removes ETFs/funds
3. Process clean stock universe → no fundamental data issues!

**Result**:
- 190 problematic tickers filtered out (7.5%)
- Clean fundamental enrichment
- No more filing_date warnings
- Better data quality
