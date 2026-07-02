# Goal B: Minervini Stage Classifier Plan

## Objective
Classify the market structure of candidate tickers into Minervini's 4 Stages (Stage 1: Basing, Stage 2: Advancing, Stage 3: Top Area, Stage 4: Declining). 
The primary goal is to act as a **strategy entry filter**: we only want to deploy capital on tickers in early/mid Stage 2, and strictly avoid late Stage 3 or Stage 4 setups, regardless of what the M01/M02 score says.

## Deliverables
1. **Rule-Based Stage Classifier (Python module / SQL view):**
   - A robust classification logic built on existing moving average and price features.
2. **Backtest Integration:**
   - Incorporate the stage classification as a mandatory condition in the Strategy Arena / vectorized backtest engine.
3. **Exploratory Notebook / Report:**
   - A brief analysis showing the distribution of the 4 stages across the SEPA watchlist and their forward return profiles.

## High-Level Implementation Plan

### Phase 1: Feature Re-use & Definition
We will build a rule-based engine using our existing materialized technical features:
- `price_vs_sma_200`
- `sma_ratio_150_200` (SMA 150 vs SMA 200)
- `price_vs_sma_50`
- `dist_from_52w_high` / `dist_from_52w_low`

*Minervini Stage 2 criteria (example baseline):*
- Current Price > 150-day SMA and 200-day SMA.
- 150-day SMA > 200-day SMA.
- 200-day SMA is trending up for at least 1 month.
- Current Price > 50-day SMA.
- Current Price is at least 30% above 52-week low.
- Current Price is within 25% of 52-week high.

### Phase 2: Classification Logic
Create a new function/script `src/features/stage_classifier.py` or directly append to the SQL pipeline if more efficient.
The classifier will output a categorical `market_stage` column: `[1, 2, 3, 4]`.

- **Stage 1 (Consolidation):** Price oscillating around flat SMAs.
- **Stage 2 (Advancing):** Uptrending SMAs, price > 50 SMA > 150 SMA > 200 SMA.
- **Stage 3 (Distribution):** Increased volatility, price crossing below 50 SMA, 200 SMA flattening.
- **Stage 4 (Declining):** Downtrending SMAs, price < 50 SMA < 150 SMA < 200 SMA.

### Phase 3: Validation & Backtest Integration
- Validate the logic against a few known historical ticker charts (sanity check).
- Compute the stage for the `t3_training_cache` universe.
- Run a quick analysis: *What is the Precision@50 of the M02 model if we strictly filter for Stage 2 candidates?*
- Wire this filter into the parameter optimizer (Goal 5) for final strategy evaluation.

*(Note: We will defer complex pattern recognition like Elliott-wave counting unless this simple rule-based approach proves insufficient).*
