# M02 Final Verdict

## 1. Idea Generation & Initial Purpose
M02 was initially conceived during Sprint 2 as a "loser detector" (meta-labeling model) designed to act as a secondary filter. The original intent was to identify trades likely to hit a stop-loss, improving the overall win rate of candidates surfaced by the primary model (M01). It was structured as a binary classifier with inverted labels, outputting the probability of a candidate failing (hitting a stop loss) vs surviving.

## 2. Definition of the Problem (Sprint 12 Pivot)
By Sprint 12, the problem definition shifted significantly. "M02" was repurposed (note: this caused a name collision with the older classifier) into a **dense forward-21d quantile regression model**. 
The goal was to directly predict the Maximum Favorable Excursion (MFE) and Maximum Adverse Excursion (MAE) to establish correctly calibrated volatility bands:
- **P90(MFE/natr)**: Take-Profit (TP)
- **P10(MAE/natr)**: Stop-Loss (SL)
- **P50**: Directional rank (median expected outcome)

The objective was to see if M02 could dynamically set TP/SL bounds better than simple ATR multiples and provide directional alpha as a ranker.

## 3. How It Was Built & Trained
The `m02_prototype` was built using XGBoost (`reg:quantileerror`), training one booster per quantile (P10, P50, P90).
- **Data Universe**: Trained on a dense dataset of 16.1 million rows (`m02_prototype_targets`) covering all tickers and all days, without pre-filtering for specific setups.
- **Training Setup**: 6-variant sweep, training on data from 2016+, with testing on 2021-2026 across 5 folds and a 21-day embargo geometry to prevent leakage (`src/evaluation/m02_cv.py`).

## 4. Feature Set
M02 relied on a dense candidate population feature set, encompassing price action velocity, momentum, and (initially) M03 regime features. Because it was applied to all tickers every day, the feature set lacked the specific structural context of a localized breakout pattern.

## 5. How It Was Evaluated
Evaluation was rigorously conducted using:
- `eval_m02_coverage.py` for quantile calibration (verifying if P10/P90 actually bound the realized MAE/MFE at the expected rates).
- `m02_cv.py` for ranking skill, calculating Information Coefficient (IC) and RMSE/MAE across walk-forward folds.

## 6. Why It Failed at Detecting Breakouts
The evaluation yielded two decisive conclusions:
1. **M02 Failed as a Ranker**: It demonstrated **negative edge**. Ranking today's candidates by M02's predicted P50 resulted in worse performance than random selection. It possessed no monotonic agreement with realized forward returns.
2. **No Superiority in TP/SL Estimation**: While M02 successfully outputted statistically calibrated volatility bands (the P10/P90 bounds were geometrically accurate), it did not demonstrate any directional alpha. Its output was essentially equivalent to a correctly calibrated generic volatility-scaled band (like $k \times ATR$). 

**Conclusion:** M02 predicts a "volatility cone" reasonably well but has zero directional edge. Breakout detection requires identifying structural alpha (price memory, supply/demand imbalances), not just predicting that a stock will fluctuate within its normal volatility bounds. 

## 7. Next Steps & Final Decision
**Verdict: M02 is retired.**
- We will NOT ship M02 for daily ranking or candidate selection.
- For TP/SL estimation, we will default to **Option B: Simple ATR multiples ($k \times ATR$ bands)**, which provide the same volatility-scaling benefits without the overhead of a complex ML model.
- **Next Horizon**: We will consider adding **Price Action (PA)** structurally. PA analysis (e.g., VCP characteristics, specific chart pattern recognition) is better suited to identifying the structural supply/demand dynamics that define true breakouts, which generic dense regression models like M02 fail to capture.
