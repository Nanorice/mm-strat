# Sprint 13 — Research Log

This is the linear train-of-thought for the sprint, tracking questions and their resolution.

## Thread A: Score Attribution & Validity
1. **Is the M01 score an artifact of Healthcare/sector bias?** → No. The growth tilt is expected; Healthcare dominance in the top 20 is just a base rate effect. [check_healthcare_bias.py]
2. **Which model performs best in a direct bake-off?** → `m01_binary` and `m01_prototype` tied at the top (Sharpe ~2.0). The 4-class `m01_no_macro` was decisively the worst. [run_model_arena.py]
3. **Can `m02_breakout` function as a short-hold or earlier-entry signal?** → Earlier entry confirmed as a pre-breakout signal, but the return claim was falsified (no forward return edge). [m02_signal_quality_report.md](verdicts/m02_signal_quality_report.md)

## Thread B: SEPA Staging / Entry Timing
4. **Does a hard SEPA stage gate improve returns?** → No. Stage gate falsified. Mean reversion > momentum within the pre-selected watchlist. [falsify_stage_gate.py]

## Thread C: Regime / Bearish-Event Notebook
5. **Are there better leading signals than VIX (e.g. absorption ratio, valuation)?** → No leading signal found besides VIX; regime model will not be overcomplicated. [notebooks/regime_model.ipynb]

---

## Open meta-questions
- Does the VIX-sizing uplift hold strictly out-of-sample in a Walk-Forward Optimization (WFO)?
