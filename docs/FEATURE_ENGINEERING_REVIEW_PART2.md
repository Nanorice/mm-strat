# Feature Engineering Review - Part 2: Detailed Challenges

## 🚨 Section 1: The "Must-Drop" List - My Challenges

### 1.1 RSI_14 (Raw) - **PARTIAL AGREEMENT** ⚠️

**Your Argument**: 
> "In strong momentum, RSI stays > 70. A standard model sees 70 as 'Sell'."

**My Challenge**:

**Tree-based models DON'T have this problem!**

Decision trees can learn:
```
If RSI > 70:
    If Price_vs_SMA_50 > 1.1 AND RS > 1.0:
        → BUY (strong momentum, RSI is confirmation)
    Else:
        → SELL (overbought without momentum)
```

**However**, you're right that:
1. Linear models (logistic regression) WOULD see this as a problem
2. Even tree models benefit from **clear signals**
3. Interpretability improves with `RSI_Regime`

**My Recommendation**: ⚠️ **KEEP BOTH**
- ✅ Add `RSI_Regime` (your brilliant insight)  
- ✅ Also keep raw `RSI_14` (let model choose which to use)
- Reason: Feature importance will tell us which is better

**Alternative**: If you want ONLY one, I vote for `RSI_Regime` ✅

---

## 🚀 Section 2: The "Minervini Boosters" - My Challenges

### 2.1 Inventory vs Sales Spread - **100% AGREE** ✅

No challenge. This is gold. Already agreed to implement.

---

### 2.2 EPS_Accel - **100% AGREE** ✅

No challenge. Already agreed to implement.

---

### 2.3 PEG_Adjusted - **MISSING FORMULA!** ⚠️

**Your Statement**:
> "Challenge: If EPS Growth is negative, PEG becomes negative (which looks 'cheap' to a simple sort)."
> "Fix: PEG_Adjusted"

**My Challenge**: **YOU DIDN'T GIVE ME THE FORMULA!** 😊

What exactly is `PEG_Adjusted`? Here are the options:

**Option A**: Cap negative/invalid
```python
if eps_growth_yoy <= 0:
    peg_adjusted = np.nan  # Or some large penalty like 999
elif eps_growth_yoy < 5:
    peg_adjusted = np.nan  # Too small, PEG explodes
else:
    peg_adjusted = pe_ratio / eps_growth_yoy
```

**Option B**: Absolute value (not recommended)
```python
peg_adjusted = pe_ratio / abs(eps_growth_yoy)
# Problem: Negative growth looks same as positive!
```

**Option C**: Separate feature for declining stocks
```python
# Keep PEG for growers only
if eps_growth_yoy > 5:
    peg_ratio = pe_ratio / eps_growth_yoy
else:
    peg_ratio = np.nan

# Add separate boolean
is_declining = 1 if eps_growth_yoy < 0 else 0
```

**Option D**: Penalty score (Peter Lynch wouldn't do this)
```python
if eps_growth_yoy <= 0:
    peg_adjusted = 100  # Huge penalty
else:
    peg_adjusted = pe_ratio / eps_growth_yoy
```

**Which one do you mean?**

**My Recommendation**: ✅ **Option C**
- PEG only for stocks with growth > 5%
- Separate boolean `Is_Declining_Earnings`
- Reason: Clear signal, no confusion

**Please clarify your intent!**

---

## 🔧 Section 3: Technical Upgrades - STRONG CHALLENGES

### 3.1 RSI_Regime - **BRILLIANT, BUT...** ⚠️

**Your Formula**:
```
RSI_Regime = 1 if (RSI_14 > 40 AND SMA_200_Slope > 0) else 0
```

**My Challenges**:

#### Challenge 3.1.1: SMA_200_Slope Calculation

You haven't defined `SMA_200_Slope` yet!

**Options**:
```python
# Option A: Percentage change (my recommendation)
SMA_200_Slope = (SMA_200 - SMA_200.shift(20)) / SMA_200.shift(20) * 100

# Option B: Simple boolean (simpler)
SMA_200_Slope = 1 if SMA_200 > SMA_200.shift(20) else 0

# Option C: Angle (degrees) - overkill
SMA_200_Slope = np.arctan((SMA_200 - SMA_200.shift(20)) / 20) * 180 / np.pi
```

**Which one?**

For `RSI_Regime`, you only need **positive/negative**, so:
```python
# Simplified
is_bull_market = (SMA_200 > SMA_200.shift(20))  # Rising 200-day MA
RSI_Regime = 1 if (RSI_14 > 40 and is_bull_market) else 0
```

**My Recommendation**: ✅ Use boolean check on SMA_200

---

#### Challenge 3.1.2: Threshold Sensitivity

**Your threshold**: RSI > 40 in bull, otherwise sell

**Andrew Cardwell's actual ranges**:
- **Bull market**: RSI oscillates 40-80 (dips to 40 are buying opportunities)
- **Bear market**: RSI oscillates 20-60 (rallies to 60 are selling opportunities)

**This means**:
- In bull: RSI 45 = "Buy the dip" ✅
- In bull: RSI 75 = "Strong, but still ok" ✅
- In bear: RSI 55 = "Overbought rally, sell" ✅
- In bear: RSI 35 = "Weak, avoid" ✅

**But your formula is binary** (0 or 1). This loses information!

**Alternative 1**: Three regimes
```python
if is_bull_market:
    if RSI_14 > 80:
        RSI_Regime = 2  # Extreme bull (caution)
    elif RSI_14 > 40:
        RSI_Regime = 1  # Healthy bull (buy)
    else:
        RSI_Regime = 0  # Weak (caution)
else:  # Bear market
    if RSI_14 > 60:
        RSI_Regime = -1  # Bear rally (sell)
    elif RSI_14 > 20:
        RSI_Regime = -2  # Bear decline (avoid)
    else:
        RSI_Regime = -3  # Extreme bear (maybe bottom)
```

**Alternative 2**: Continuous score (my preference)
```python
# Normalize RSI based on regime
if is_bull_market:
    RSI_Normalized = (RSI_14 - 40) / 40  # 0 to 1 scale (40 = 0, 80 = 1)
else:
    RSI_Normalized = (RSI_14 - 20) / 40  # 0 to 1 scale (20 = 0, 60 = 1)
```

**Alternative 3**: Keep it simple (your way)
```python
RSI_Regime = 1 if (RSI_14 > 40 and is_bull_market) else 0
```

**My Recommendation**: ⚠️ **Alternative 2 (continuous)** OR **Alternative 3 (simple)**
- Continuous preserves information (better for gradient boosting)
- Simple is more interpretable (better for trees)
- **Your call!** I lean toward continuous.

---

### 3.2 Sector_RS_Rank - **DATA CHALLENGE!** 🚨

**Your Formula**:
```python
df['Sector_RS_Rank'] = df.groupby(['date', 'sector'])['RS'].rank(pct=True)
```

**My MAJOR Challenges**:

#### Challenge 3.2.1: We Don't Have Sector Data!

**Current system**:
- ❌ No sector/industry classification stored
- ❌ FMP **does provide** sector data (`v3/profile/{ticker}` has `sector` field)
- ❌ But we'd need to:
  1. Fetch sector for all 1,730 tickers
  2. Cache it
  3. Add to Dataset A

**Infrastructure needed**:
```python
# New file: src/sector_engine.py
class SectorEngine:
    def get_ticker_sector(ticker: str) -> str:
        # Call FMP API
        # Return "Technology", "Healthcare", etc.
        pass
    
    def get_batch_sectors(tickers: List[str]) -> Dict[str, str]:
        # Batch fetch
        pass
```

**Estimated effort**: 2-3 hours

**My Recommendation**: ⚠️ **DO THIS, but as separate task**
- High value for cross-sectional alpha
- But significant infrastructure work
- **Phase 4** in roadmap, not Phase 1

---

#### Challenge 3.2.2: Cross-Sectional Calculation is EXPENSIVE

**Your formula requires**:
```python
df.groupby(['date', 'sector'])['RS'].rank(pct=True)
```

This means for EACH date (e.g., 5,800 trading days):
1. Load ALL tickers' data for that date (~1,730 rows)
2. Group by sector (~11 GICS sectors)
3. Rank within each sector
4. Store result

**Current approach**: Process tickers **independently** (parallelizable)
**Your approach**: Need **full universe** at each date (not parallelizable)

**Performance impact**:
- Current: ~3-5 minutes for Dataset A (parallel)
- With cross-sectional: ~15-30 minutes (sequential)

**Architecture change needed**:
```python
# Current (ticker-by-ticker):
for ticker in tickers:
    process_ticker(ticker)  # Independent

# New (date-by-date):
for date in trading_dates:
    all_tickers_df = load_all_tickers(date)  # Load 1730 rows
    all_tickers_df['Sector_RS_Rank'] = all_tickers_df.groupby('sector')['RS'].rank(pct=True)
    save_date_snapshot(all_tickers_df)
```

**My Recommendation**: ⚠️ **Defer to Phase 4**
- This is a **major refactoring**
- High value, but significant complexity
- **Alternative for Phase 1**: Universe-wide RS rank (ignore sectors)

---

#### Challenge 3.2.3: Simpler Alternative - Universe RS Rank

**Instead of sector-relative, use universe-relative**:
```python
# Much simpler - no sector needed
df['RS_Percentile'] = df.groupby('date')['RS'].rank(pct=True)
```

**Interpretation**:
- `RS_Percentile = 0.95` → Top 5% strongest stock in entire universe
- `RS_Percentile = 0.20` → Bottom 20% (weak)

**Pros**:
- ✅ No sector data needed
- ✅ Simpler to implement
- ✅ Still captures "relative strength in context"

**Cons**:
- ⚠️ Less precise than sector (Tech stocks naturally have higher RS than Utilities)
- ⚠️ Still requires cross-sectional calculation (date-by-date)

**My Recommendation**: ✅ **Start with this, add sector later**

---

## 📝 My Counter-Proposal for Section 3

### What I Recommend Implementing NOW (Phase 1):

**RSI Features**:
```python
# Option 1: Both raw and regime
RSI_14 = calculate_rsi(df, 14)
is_bull = SMA_200 > SMA_200.shift(20)
RSI_Regime = 1 if (RSI_14 > 40 and is_bull) else 0

# Option 2: Just regime (your preference)
RSI_Regime = 1 if (RSI_14 > 40 and is_bull) else 0
```

**PEG Adjusted** (need your formula!):
```python
# My proposed version until you clarify:
if eps_growth_yoy > 5:
    PEG_Ratio = pe_ratio / eps_growth_yoy
    PEG_Ratio = np.clip(PEG_Ratio, 0, 10)  # Cap extremes
else:
    PEG_Ratio = np.nan

Is_Declining_Earnings = 1 if eps_growth_yoy < 0 else 0
```

**Cross-Sectional Ranking** - PHASE 2, not now:
```python
# Simpler version for Phase 1 (no sectors):
# df['RS_Percentile'] = df.groupby('date')['RS'].rank(pct=True)

# Full version for Phase 2 (with sectors):
# df['Sector_RS_Rank'] = df.groupby(['date', 'sector'])['RS'].rank(pct=True)
```

---

## 🎯 Final Checklist with My Challenges

| Your Recommendation | My Response | Priority |
|---------------------|-------------|----------|
| Drop SMA_50, SMA_200 (raw) | ✅ AGREE | P0 |
| Drop revenue, inventory (raw) | ✅ AGREE | P0 |
| Drop fiscal_date, filing_date | ✅ AGREE | P0 |
| Drop RSI_14 (raw) | ⚠️ PARTIAL - Keep both RSI_14 and RSI_Regime | P1 |
| Add Inventory_vs_Sales_Spread | ✅ AGREE | P0 |
| Add EPS_Accel | ✅ AGREE | P0 |
| Add PEG_Adjusted | ⚠️ NEED FORMULA - Using my Option C for now | P1 |
| Add RSI_Regime | ✅ AGREE (with continuous alternative) | P1 |
| Add Sector_RS_Rank | 🚨 CHALLENGE - Defer to Phase 2, need sector data | P2 |

**P0** = Implement immediately (Phase 1)  
**P1** = Implement after P0 (Phase 1)  
**P2** = Requires infrastructure (Phase 2+)

---

## ❓ Questions for You

1. **PEG_Adjusted formula**: Which option do you prefer?
   - A) Set to NaN if growth <= 5%
   - B) Set to 999 (penalty) if growth <= 0
   - C) Separate boolean `Is_Declining_Earnings`
   - D) Something else?

2. **RSI_Regime**: Binary (0/1) or continuous normalized score?

3. **Sector_RS_Rank**: 
   - Defer to Phase 2? (need to fetch sector data from FMP)
   - OR use universe-wide RS_Percentile in Phase 1?

4. **SMA_200_Slope**: Percentage change or just boolean (rising/falling)?

Please clarify these 4 points and I'll implement!
