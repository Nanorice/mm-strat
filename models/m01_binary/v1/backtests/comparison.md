# Strategy Array Comparison — m01_binary/v1

**Window:** 2024-11-01 → 2026-05-22
**Strategies evaluated:** 10

## Ranking (by Sharpe, desc)

| Rank | Strategy | Sharpe | Total Return | Max DD | Win Rate | Trades | Avg Hold | SQN |
|---|---|---|---|---|---|---|---|---|
| 1 | **S3_prob_threshold_5pos** | 1.592 | +52.52% | 11.10% | 37.93% | 145 | 14.793 | 2.073 |
| 2 | **S5_hybrid_persistent_raw** | 1.548 | +68.61% | 16.15% | 40.18% | 219 | 15.820 | 1.842 |
| 3 | **S1_baseline_top3_raw** | 1.438 | +74.45% | 21.75% | 41.03% | 273 | 15.432 | 1.667 |
| 4 | **S2_trailing10_top5_raw** | 1.438 | +74.45% | 21.75% | 41.03% | 273 | 15.432 | 1.667 |
| 5 | **S4_trailing20_regime_aware_raw** | 1.438 | +74.45% | 21.75% | 41.03% | 273 | 15.432 | 1.667 |
| 6 | **S3_prob_threshold_5pos_raw** | 1.284 | +41.22% | 14.71% | 39.29% | 140 | 15.370 | 1.389 |
| 7 | **S5_hybrid_persistent** | 1.006 | +38.93% | 19.44% | 36.05% | 233 | 14.947 | 1.367 |
| 8 | **S1_baseline_top3** | 0.783 | +34.63% | 20.14% | 33.57% | 283 | 15.091 | 0.995 |
| 9 | **S2_trailing10_top5** | 0.783 | +34.63% | 20.14% | 33.57% | 283 | 15.091 | 0.995 |
| 10 | **S4_trailing20_regime_aware** | 0.783 | +34.63% | 20.14% | 33.57% | 283 | 15.091 | 0.995 |

## Strategy descriptions

- **S1_baseline_top3**: Baseline: top-3 daily, regime caps, default exits.
- **S2_trailing10_top5**: 10-day trailing percentile, up to 5 entries/day, regime caps.
- **S3_prob_threshold_5pos**: Calibrated P(>30%) >= 0.30 entry gate, fixed 5-position cap.
- **S4_trailing20_regime_aware**: 20-day trailing percentile + min_prob_elite=0.25.
- **S5_hybrid_persistent**: Persistence-gated entry (top-30% trailing rank, 3 of last 5 days), fixed 8-position cap, 10-day min hold.
- **S1_baseline_top3_raw**: Baseline: top-3 daily, regime caps, default exits.
- **S2_trailing10_top5_raw**: 10-day trailing percentile, up to 5 entries/day, regime caps.
- **S3_prob_threshold_5pos_raw**: Calibrated P(>30%) >= 0.30 entry gate, fixed 5-position cap.
- **S4_trailing20_regime_aware_raw**: 20-day trailing percentile + min_prob_elite=0.25.
- **S5_hybrid_persistent_raw**: Persistence-gated entry (top-30% trailing rank, 3 of last 5 days), fixed 8-position cap, 10-day min hold.