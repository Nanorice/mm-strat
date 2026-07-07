# M02 Breakout Prediction Model

## Overview
The M02 Breakout Prediction model is a regression prototype designed to predict the likelihood and proximity of a stock breaking out and being included in the SEPA watchlist. It serves as a structural departure from previous M02 iterations (which focused purely on volatility boundaries), explicitly targeting directional, high-quality breakouts.

## Target Formulation
The model frames breakout prediction as a regression problem using a continuous **Breakout Proximity Score**:
- **Days to Breakout**: The number of calendar days until a ticker's *next* entry into the `sepa_watchlist`.
- **Exponential Decay**: `proximity_score = exp(-k * days_to_breakout)` (where $k=0.1$).
  - If a stock breaks out tomorrow, its score is near `1.0`.
  - If it breaks out in 30 days, its score decays towards `0.0`.
  - If no breakout occurs within the 60-day horizon, the score is strictly `0.0`.

This continuous target allows XGBoost Regressor (`reg:squarederror`) to prioritize candidates that are closest to a breakout event, effectively smoothing out sparse binary events into a trackable gradient.

## Training Pipeline & Data
- **Target Generation**: `scripts/build_breakout_targets.py` computes the dense forward targets by joining `price_data` against the `sepa_watchlist`.
- **Features**: Trained on `fs_m01_prototype` (the dense candidate population features) via `t3_training_cache`.
- **Cross-Validation**: Evaluated using an anchored Walk-Forward embargo harness (`src/evaluation/breakout_cv.py`) to prevent lookahead bias.

## Results & Baseline Comparison
The model was trained and evaluated on ~9.3M rows across 5 years (2021-2026), yielding exceptional results:
- **Rank IC**: Consistently bounded between `+0.32` and `+0.38`.
- **Precision@50**: ~`50.0%`. Out of the model's top 50 ranked candidates on any given day, approximately half successfully broke out within 60 days.
- **Baseline Edge**: The base rate of a random candidate breaking out within 60 days is **13.66%**. The model's 50% Precision@50 represents a massive **~3.6x edge** over blind selection.
- **Recall@50**: Ranged from `6%` to `16%`, effectively surfacing a significant chunk of the market's total breakouts from a tiny, concentrated pool of 50 picks.

## Future Improvements & Analytics
To mature this prototype into a production asset, the following analytics and improvements are recommended:
1. **Target Stratification**: Refine the target by filtering out "low quality" SEPA watchlist entries (e.g., only predicting entries where `breakout_ok = TRUE` and `trend_ok = TRUE`).
2. **Horizon Tuning**: Experiment with the $k$ decay parameter and the 60-day horizon to find the optimal curve that maximizes the model's predictive gradients.
3. **Integration**: Wire the `m02_breakout` model into `daily_scanner.py` and display the predictions in the daily dashboard for live, out-of-sample forward monitoring.
