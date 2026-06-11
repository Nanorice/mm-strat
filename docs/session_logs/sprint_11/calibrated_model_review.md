# Review of Calibrated Prototype Model (`m01_prototype_cali/v1`)

**Date:** 2026-05-29
**Model Model:** `m01_prototype_cali/v1` vs `m01_prototype_2003_2026/v1`

## 1. High-Level Summary
The calibrated model achieved an aggregate score of **10 / 21** (WEAK), a slight 1-point improvement over the uncalibrated model (9 / 21). 

However, the "WEAK" verdict is somewhat misleading for your specific operational workflow. The evaluation framework rejects the model largely because of a hardcoded automated trading gate, whereas your actual process involves a human-in-the-loop manual selection after the model screens at 0.6 / 0.7.

## 2. The Hardcoded Gate Issue (Section E)
The framework strictly evaluates trade frequency at the `T*=0.6` threshold. 
- **The Gate:** `E2_trade_frequency` requires ≥ 3.0 trades per month.
- **The Model:** Yields exactly **2.76 trades per month** at `T=0.6` and fails the blocking gate, causing a cascading rejection of use-cases like `threshold_gate` and `composite_gate_plus_rank`.

**Operational Reality vs. Framework:**
Because your current workflow uses the 0.6/0.7 threshold as a *screener* for manual company selection rather than an automated execution trigger, the 3.0 trades/month requirement is unnecessarily strict. 

As a screener, the model is exceptionally good at the top end:
- **At T=0.6:** Precision is **54.1%** (4.68× lift over base prevalence). It surfaces ~3 highly qualified candidates per month.
- **At T=0.7:** Precision shoots up to **81.1%** (7.02× lift), surfacing ~1 extremely qualified candidate every 3 months.

If the model is treated as a top-candidate screener for a human analyst, this performance is actually highly desirable, and the "FAIL" verdict from the framework doesn't reflect the model's true utility.

## 3. Calibration Status (Section C)
Despite being the "calibrated" model, the calibration step did not actually fix the underlying probability distribution.
- **ECE (Expected Calibration Error):** Remained at `0.1250` (identical to the uncalibrated model's `0.1252`). The gate requires `< 0.05`.
- **Threshold Bins:** 5 out of 5 non-empty bins still exceed the ±0.05 tolerance.
- **Conclusion:** The current calibration implementation (e.g., Platt scaling or Isotonic regression parameters) is not successfully compressing the probabilities into a trustworthy absolute scale. 

## 4. Ranking & Discrimination Improvements (Section B)
Interestingly, the calibration process slightly improved the model's discriminative ranking power.
- **PR-AUC Lift:** Increased from `2.978×` to `3.001×`, bumping the Section B score from Good (2) to Strong (3). 
- **AUC:** Marginally increased from `0.7870` to `0.7879`.

## Next Steps / Recommendations
1. **Update the Evaluation Framework:** We should consider making the `E2_trade_frequency` gate configurable or adding a new use-case specifically for "Human-in-the-loop Screener" that relaxes the frequency requirement in favor of pure precision lift.
2. **Review the Calibrator Implementation:** The calibration logic in `src/evaluation/calibrator.py` or the training script did not meaningfully change the ECE. If we want true probabilities (e.g. for position sizing), we need to debug the calibrator. If we only care about ranking/screening, we can safely ignore Section C.
