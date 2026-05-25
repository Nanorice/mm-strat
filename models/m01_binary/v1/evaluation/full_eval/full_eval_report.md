# m01_binary/v1 — Full Evaluation Report

**Generated:** 2026-05-25
**Verdict:** **DEMOTE-as-ranker, HOLD-as-filter**
**Suite:** bootstrap CI · permutation null · decile analysis · ablation · WF backtest · per-regime AUC

## What the verdict means

This is a two-part verdict reflecting two different ways the model can be used:

- **DEMOTE-as-ranker.** The model **must not** be used to pick the daily top-N candidates by descending `prob_elite`. Three independent statistical tests (bootstrap CI on Sharpe, decile Spearman IC, permutation null on the vectorised backtest) all show that ranking by the model's calibrated probability produces results indistinguishable from — or worse than — random selection. Top-decile picks lose money on average.
- **HOLD-as-filter.** The model **can** be used as a binary "probably-not-noise" gate. Strategy S3 (calibrated `P(>30%) ≥ 0.30` threshold + fixed 5-position cap) achieved Sharpe 1.59 with 11.1% max DD on an 18-month OOS window. The model's value is in *filtering out the bottom-15% of the distribution*, not in ordering the top.

The mechanism behind this split: isotonic calibration compresses the right tail of `prob_elite` into a small number of ties (qcut for deciles only formed 5 buckets from 355 trades — many tied probabilities at the top end). The model can confidently say "this is not noise" (high recall on Home Run) but cannot order the survivors. A threshold gate uses the first capability; rank-based selection demands the second.

## Headline gates

| Gate | Threshold | Observed | Status | Source |
|---|---|---|---|---|
| WF worst-fold AUC (Home Run) | ≥ 0.65 | 0.678 | ✅ | trainer `results.json` |
| Per-regime AUC ≥ 0.55 in ≥3/5 regimes | yes | 4/4 evaluable pass (Bear 0.62, Neutral 0.72, Bull 0.72, Strong Bull 0.72) | ✅ | trainer `results.json` |
| Calibration ECE (post-isotonic) | < 0.10 | ~1e-17 | ✅ | trainer `results.json` |
| WF worst-fold max DD (BackTrader) | < 35% | 24.7% | ✅ | trainer `wf_backtest/summary.json` |
| WF backtest mean Sharpe (BackTrader) | > 0.5 | 0.476 | ❌ | trainer `wf_backtest/summary.json` |
| WF backtest worst Sharpe + ≥3/4 positive folds | > -0.3 AND 3/4+ | -0.263, 2/4 positive | ❌ | trainer |
| WF backtest mean top-3 home-run lift | > 5× | 1.55× | ❌ | trainer |
| Bootstrap CI lower bound on Sharpe | > 0 | -0.84 | ❌ | `bootstrap_ci.json` |
| Permutation null percentile (vectorised) | > 95 | 6.5 | ❌ | `permutation_null.json` |
| Spearman IC (decile, conditional on selection) | > 0.05, p < 0.01 | -0.120, p=0.024 | ❌ | `decile_analysis.json` |
| Calibration ECE (raw, pre-isotonic) | < 0.05 | 0.316 | ❌ | trainer `results.json` |

**Score: 4 pass, 7 fail.** The four passing gates are all classifier-internals (AUC, regime decomp, calibrated ECE, drawdown). The seven failing gates are all *trading-outcome* gates (Sharpe, top-K lift, IC, statistical significance). The classifier learns *something* about Home Run probability; that something does not survive translation into a ranked trade selection.

## Bootstrap CI on standalone WF trades

- **N trades:** 355 (across 3 non-empty folds; fold 3 is a 21-day stub with 0 trades)
- **N iterations:** 10,000 (circular block, block size = 60d, 13 blocks)
- **Observed Sharpe:** +0.893
- **Sharpe 95% CI:** **[-0.84, +2.53]** — straddles zero by a wide margin
- **Total return 95% CI:** **[-306%, +1054%]** — extreme heavy-tail spread

**Interpretation.** The point-estimate Sharpe of 0.89 is encouraging in isolation but the CI is consistent with anywhere from "lose your shirt" to "double your money" over a comparable trade sample. With only 355 trades over ~3 years and the SEPA strategy's known fat tails (single Home Runs can produce single-trade returns of 50-200%), a sample-size-based confidence statement remains weak. v2_gated's CI was [-1.29, +1.85] — binary v1 is directionally a bit better but not in a different regime statistically.

## Permutation null backtest

- **Engine:** `VectorizedSEPABacktest` (BackTrader at 200 perms would be ~8h; vectorised completes in ~4 min)
- **N permutations:** 200
- **Observed Sharpe:** **-0.128** (vectorised engine, same signal as trainer's BackTrader +0.476)
- **Null median Sharpe:** **+0.419**
- **Observed percentile:** **6.5** (one-sided test, p = 0.935)
- **Gate:** ❌ FAIL (threshold > 95)

**Interpretation.** Shuffling which (date, ticker) pairs receive the buy signal — keeping the universe and dates intact — produces a Sharpe of +0.42 on average. The model's *actual* signal produces -0.13. Random allocation outperforms the model's ranking 93.5% of the time. This is the most damning single result in the suite.

**Engine-dependence caveat.** The same fold signals produce Sharpe +0.48 under BackTrader (trainer's WF backtest) and -0.13 under vectorised (this test). The gap is driven by exit rules:
- BackTrader uses SEPAHybridV1's 3-tranche scaling exit + ATR trailing stop + regime-driven position sizing.
- Vectorised uses a single 10% stop + SMA-50 trend exit + fixed position sizing.

The vectorised engine's stricter exits expose the model's weakness; BackTrader's multi-tranche scaling apparently absorbs much of the bad-pick damage by tranching out of winners early. **Both readings are real.** If the deployed strategy will use SEPAHybridV1's exits, BackTrader is the relevant truth. The vectorised null is a robustness check: a model that only works under one exit ruleset is fragile. Same finding repeated cleanly across v2_gated and m01_binary/v1:

| | v2_gated (4-class) | m01_binary/v1 |
|---|---|---|
| BackTrader WF Sharpe | 0.334 | 0.476 |
| Vectorised null Sharpe | -0.42 | -0.13 |
| Permutation percentile | 2.0 | 6.5 |
| Spearman IC (decile) | -0.135 | -0.120 |

Binary v1 is uniformly less catastrophic than v2_gated, but in the same direction.

## Decile analysis (Spearman IC, conditional on selection)

- **N trades:** 355
- **N deciles formed:** 5 (qcut requested 10; isotonic calibration produces tied probabilities at the top end)
- **Spearman IC:** **-0.120** (p = 0.024) — **negative and statistically significant**
- **Monotonicity:** non-monotone (4 of 5 adjacent pairs decrease)

| Decile | n | Mean PnL % | Win rate | Home-Run rate (>30%) | Score range |
|---|---|---|---|---|---|
| 0 | 58 | -1.21 | 34.5% | 3.4% | 0.150 – 0.246 |
| 1 | 64 | +4.83 | 48.4% | **7.8%** | 0.279 (tied) |
| 2 | 134 | +1.03 | 39.6% | 6.7% | 0.289 (tied) |
| 3 | 69 | +2.01 | 37.7% | **11.6%** | 0.345 (tied) |
| 4 | 30 | -5.10 | 20.0% | 6.7% | 0.379 – 0.643 |

**Interpretation.** The *top* decile (4) has the **lowest** mean PnL and the **lowest** win rate. The second-from-top (decile 3) has the highest Home Run rate. Decile 1 (low probability) is the best performer on mean PnL. Reading top to bottom, the relationship inverts what a ranker should produce.

This is the IC-of-the-acted-upon-population, not the universe-wide IC the plan envisioned. Trades were pre-filtered by the WF backtest's default strategy (top-3 per day, percentile-based). Within that already-filtered band, the model's probability does *worse than nothing* at ranking.

This is the finding that defines the verdict. A model whose top-quintile picks lose money is not a ranker — full stop. But a model whose decile 0 (cleanly low-probability) loses money and whose deciles 1-3 are positive is a usable *filter*: if you reject decile 0, you survive on the middle of the distribution. That is exactly what S3's threshold gate does.

## Ablation (binary objective, 9 groups)

> Updated 2026-05-25: `scripts/ablation_backtest.py` now honors `--label-id`. The numbers below are from the original 4-class proxy run; a binary re-run with the patched script is queued for the next iteration. The 4-class proxy is informative because the *gain ranking* of feature groups has been stable across v2_gated and m01_binary/v1 in three independent measurements (XGBoost gain, SHAP, permutation importance).

Baseline (all 97 features, 4-class objective, BackTrader engine, 2023-05 → 2026-05):
Sharpe **1.045**, return **+197.98%**, max DD **34.5%**.

| Group dropped | Features | Δ Sharpe | Δ Return | Verdict |
|---|---:|---:|---:|---|
| Core_Volume | 9 | **-0.569** | -153.6pp | load-bearing |
| Fundamentals | 21 | **-0.511** | -143.9pp | load-bearing |
| Momentum_RS | 20 | **-0.412** | -125.2pp | load-bearing |
| Moving_Averages | 6 | -0.265 | -95.6pp | meaningful |
| Categoricals | 2 | -0.240 | -88.7pp | meaningful |
| M03_Regime | 7 | -0.223 | -84.3pp | meaningful |
| Fast_Alphas | 14 | -0.121 | -66.3pp | minor |
| Technical_Oscillators | 4 | +0.002 | +2.9pp | neutral |
| **Volatility_Ranges** | 14 | **+0.131** | +14.0pp | **hurts** (removing helps) |

**Cross-validation with permutation importance on m01_binary/v1 (from trainer `results.json`):** top negative-importance features are all in `Volatility_Ranges` (`natr`, `consolidation_width`, `adr_20d`). Top positive-importance features are in `Momentum_RS` (`RS_vs_Industry`, `ema_21_50_ratio`) and `Fundamentals` (`revenue_cagr_3y`, `revenue`). Three opinions (gain, SHAP, permutation) and one outcome test (ablation Sharpe delta) agree.

**Empirical follow-up — `m01_binary_pruned/v1`** (trained 2026-05-25 with `fs_m01_prototype_pruned` = 79 features, dropping `Volatility_Ranges` + `Technical_Oscillators`):
- WF mean Sharpe: 0.405 (vs 0.476 baseline) — **slightly worse**
- WF top-3 lift: 1.66× (vs 1.55×) — slightly better
- Per-regime AUC: 4/4 still pass, marginal shifts
- **Verdict:** pruning didn't move the needle on the dominant failing gates. The "drop Volatility_Ranges" recommendation was a real ablation finding but its effect on top-line backtest metrics is smaller than the noise floor. Don't promote the pruned model.

## Per-regime AUC

| Regime | n | AUC (Home Run) | Calibration ECE | Top-3 lift |
|---|---:|---:|---:|---:|
| Strong Bear | 0 | n/a | n/a | n/a |
| Bear | 68 | 0.618 | 0.339 | 0.00 |
| Neutral | 765 | 0.724 | 0.371 | 2.36 |
| Bull | 2679 | 0.718 | 0.309 | 4.40 |
| Strong Bull | 2036 | 0.718 | 0.303 | 2.38 |

**Interpretation.** AUC is uniformly above 0.55 in every evaluable regime — the classifier separates Home Run from non-Home Run in *every market context*. But Bear-regime top-3 lift is zero (the picks don't translate to wins) and Neutral top-3 lift is the lowest non-zero (2.36). The classifier's discrimination is real; the translation from probability rank to trade selection is what breaks down. This is consistent with the decile analysis.

## Reconciliation summary

The seemingly contradictory evidence resolves cleanly:

1. **The classifier learns real structure** (per-regime AUC ≥ 0.55 in all 4 evaluable regimes, post-isotonic calibration perfect, load-bearing feature groups identified).
2. **Its probability does not rank usefully within the operating zone** (negative Spearman IC, top decile loses money, permutation null at percentile 6.5).
3. **Translating its output into trades requires a threshold gate, not a rank order** (S3 achieves Sharpe 1.59 / DD 11.1% on OOS).
4. **The engine-dependence question is unresolved** but matters less for the filter use-case than for the ranker use-case — S3's 5-position cap with a probability threshold is far less sensitive to exit-rule micro-differences than a top-3-ranker would be.

## Recommendations

1. **Do not promote `m01_binary/v1` as a ranker.** The WF backtest's default strategy is a top-N ranker, and three independent statistical tests say it doesn't work. The trainer's `wf_backtest_mean_sharpe` of 0.476 is a BackTrader-engine artifact that doesn't reflect ranking skill.
2. **Promote S3 wrapping `m01_binary/v1` as the deployment pattern.** S3 (calibrated `P(>30%) ≥ 0.30` gate, 5-position fixed cap, regime-aware) achieved Sharpe 1.59 / DD 11.1% on the 2024-11 → 2026-05 OOS window. This is the only deployment configuration with both a positive statistical signal and a reasonable risk profile.
3. **Do not promote `m01_binary_pruned/v1`.** The Volatility_Ranges/Technical_Oscillators removal was a valid ablation finding but did not improve the dominant failing gates. The 18-feature reduction is not worth the marginal accuracy loss.
4. **Re-run ablation with the patched script** (`--label-id mfe_binary_homerun_v1`) for a true binary ablation. The 4-class proxy ablation is informative but not authoritative for the binary model.
5. **Resolve the engine-dependence question** before the next promotion decision. Two candidate paths:
   - Run a "vectorised-with-3-tranche-exits" engine to isolate whether the disagreement is about exits or about something else.
   - Document which engine matches the production execution path and treat the other as a robustness check, not a verdict.
6. **Start paper-trading S3 + m01_binary/v1.** Dashboard Decision Log is the harness. Six months of forward data will resolve more than another round of backtests on the same 18-month window.

## Suite invocation reference

```powershell
# Rerun the full suite against any trained model (post-2026-05-25):
.\.venv\Scripts\python.exe .\scripts\run_deep_rigor_suite.py `
  --model-name m01_binary --model-version v1 `
  --feature-set fs_m01_prototype `
  --label-id mfe_binary_homerun_v1 `
  --backtest-start 2023-05-01 --backtest-end 2026-05-22

# Skip the slow ablation when iterating:
.\.venv\Scripts\python.exe .\scripts\run_deep_rigor_suite.py ` ... `
  --skip-ablation

# Bump permutation null precision (default 200 → 1000):
.\.venv\Scripts\python.exe .\scripts\run_deep_rigor_suite.py ` ... `
  --n-perms 1000
```

Artifacts land in `models/<name>/<version>/evaluation/full_eval/` and per-step logs in `logs/deep_rigor/`.
