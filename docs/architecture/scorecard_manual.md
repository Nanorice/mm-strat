# Model Scorecard Manual

This document provides detailed instructions on how to read, interpret, and action the automated Model Scorecards produced by `build_model_card.py`.

## 1. Glossary of Acronyms & Metrics

*   **AUC (ROC-AUC)**: Area Under the Receiver Operating Characteristic Curve. The probability that if you pick one random winner and one random loser, the model gave a higher score to the winner. (Baseline = 0.5, Target > 0.55).
*   **PR-AUC (Average Precision)**: Area Under the Precision-Recall Curve. It tells us how well the model avoids false positives at the very top of its scored list. We usually look at its **Lift over Prevalence** (e.g., if PR-AUC is 30% and the natural hit rate is 10%, the lift is 3.0x).
*   **Brier Score**: The mean squared difference between predicted probabilities (e.g., 0.60) and actual outcomes (1 or 0). Lower is better.
*   **ECE (Expected Calibration Error)**: Measures whether probabilities are trustworthy. (Lower is better, target < 0.05).
*   **IC (Information Coefficient)**: The Spearman rank correlation between the model's scores and the actual outcomes. 
    *   **Binary IC**: Rank correlation with whether it was a home run (1 or 0).
    *   **Magnitude IC (MFE-IC)**: Rank correlation with the exact Maximum Favorable Excursion percentage.
*   **MFE**: Maximum Favorable Excursion. Peak return percentage achieved before hitting a trailing stop.
*   **Top-K Lift**: Takes the top $K$ highest-scored tickers and measures their average outcome divided by the pool average.
*   **PSI (Population Stability Index)**: A measure of feature/score drift compared to the training snapshot.

---

## 2. Evaluation Pools: Mode A vs. Mode B

*   **Mode A (The Entry-Only Ledger)**: Evaluates the model *only* on the exact days and tickers where a trade setup triggered (e.g., `trend_ok = TRUE`). **Usage:** Determines if the model is a good entry filter (used for Rubric scores).
*   **Mode B (The Stateful Daily Pool)**: Evaluates the model on **every single ticker** in the active SEPA watchlist, on **every single day**. **Usage:** Determines if the model is a good continuous holder/ranker over time.

---

## 3. The 7 Sections (A-G) and Benchmarks

### Section A — Input Data Integrity
Runs hard pass/fail checks before computing any metrics. A single blocking failure here completely **VOIDS** the scorecard.
*   **A1 (Outcome Features)**: Verifies there are no columns leaking future information (like `return_pct`) into the model inputs. Defined in `OUTCOME_COLUMNS` in [`data_loader.py`](file:///c:/Users/Hang/PycharmProjects/quantamental/src/evaluation/model_card/data_loader.py).
*   **A2 (Label Horizon)**: Spot-checks that `exit_date > entry_date` and `mfe_pct >= 0` to ensure labels are logically sound. Defined in [`section_a_integrity.py`](file:///c:/Users/Hang/PycharmProjects/quantamental/src/evaluation/model_card/sections/section_a_integrity.py).
*   **A3 (SEPA Match)**: Compares evaluation rows against the live `v_d3_deployment` view to ensure the backtest data matches production SEPA output.
*   **A4 (Class Balance)**: This is NOT a gate; it is simply a reported metric (prevalence), which is why there is no "A4 pass/fail" badge.
*   **A5 (Bad Tickers)**: Checks that known invalid tickers (e.g., LIF, CUE) are not in the dataset. Defined as `BAD_TICKERS` in [`section_a_integrity.py`](file:///c:/Users/Hang/PycharmProjects/quantamental/src/evaluation/model_card/sections/section_a_integrity.py).
*   **A6 (trend_ok)**: Ensures all evaluated rows have `trend_ok=True`.

### Section B — Discrimination (Classification Quality)
*   **Metrics**: AUC, PR-AUC, Brier, Log Loss.
*   **Baseline (Dummy)**: A naive model that just predicts the overall average hit rate every time. If our ML model can't beat this dummy, it's worse than guessing.
*   **Gates vs Warnings**: B1 (AUC) and B2 (PR-AUC) are *blocking* gates. If they fail, the model is rejected. B3 (Brier beats prior) is a *warning* gate. A warning flags as "FAIL" in red, but because it is non-blocking, the overall Section B can still "Pass".
*   **How to iterate**: If B3 fails, your probabilities are poorly scaled. You need to apply Isotonic Calibration or change the XGBoost loss function.

### Section C — Calibration (Probability Trustworthiness)
*   **What it means**: If the model outputs $P=0.6$, does that cohort historically hit home runs 60% of the time? If `threshold_bins_within_tolerance = 0`, it means exactly *zero* of the probability buckets were within 5% of their true empirical hit rate.
*   **Why it happens**: XGBoost on imbalanced data naturally outputs uncalibrated probabilities. For instance, it might output $0.8$ just to rank a stock #1, even if the true historical hit rate for that setup is only $30\%$. 
*   **How to fix**: Treat the model purely as a ranker (Section D), or apply post-hoc calibration (Platt Scaling).

### Section D — Ranker Performance (Binary & Magnitude)
*   **What it does**: Confirms strict **monotonicity** between model output and performance. A higher score should strictly translate to a higher return. Measured using Spearman IC.
*   **Why twice?**: Run once for the Binary target (did it hit 30%?) and once for Magnitude (exact MFE%). If it fails Magnitude, the model is a filter, not a ranker.

### Section E — Gate Performance (Threshold Sweep)
*   **What it does**: Simulates using the model as a hard filter by sweeping thresholds ($T \in [0.3, 0.4, 0.5, 0.6, 0.7]$).
*   **How to read**: The UI highlights $T=0.6$ as the "headline" metric, but the full comparison of all thresholds is available in the `threshold_sweep` data table below the gates. *(Note: The raw data generates a `threshold_sweep.png` line chart locally in the evaluation folder for easier visualization).*

### Section F — Regime & Temporal Robustness
*   **What it does**: Breaks down performance by market regime (Strong Bull, Bear, etc.), by calendar year, and by sector.
*   **How to read**: `auc_regime_pass_rate_m03 = 1.0` does NOT mean the AUC is 1.0. It means that **100% of the market regimes** successfully passed the AUC > 0.55 threshold. The actual regime-specific AUCs are in the `taxonomy_m03_quintiles` table.
*   **Gates**: F1 (Regime Pass Rate) is blocking. F2 (Temporal Stability / no year worse than random) is a warning.

### Section G — Edge Existence (Statistical Rigor)
*   **Permutation Null**: We randomly shuffle the target labels 1000 times and recalculate the metrics. If our model's AUC is 0.69, and the highest AUC ever achieved by random shuffling was 0.52, our model beat 100% of the random shuffles (`null_percentile = 100.0`, `p-value = 0.0`).
*   **Bootstrap CI**: We sample trades with replacement to create 1000 alternate realities of our backtest. This gives us a 95% Confidence Interval. If the entire interval sits above the random baseline, we are statistically confident the edge isn't just luck.

### Benchmarks (Model vs. SEPA Composite)
*   **What it does**: Creates an equal-weight composite score from simple SEPA rules (no ML). 
*   **Rationale**: If the ML model doesn't beat the simple composite baseline, the ML is unneeded complexity.
