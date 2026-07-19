# Module: Market Regime (M03) — `src/regime_pipeline.py` + `src/pipeline/m03_regime.py`

> Verified against code 2026-07-18. Produces the daily market-regime score consumed
> as T3 features and by backtest regime gating. The model-level research history
> (why M03 looks like this, what was falsified) lives in
> [docs/model_doc/regime_model.md](../model_doc/regime_model.md) — this doc is the
> code reference.

## Components

| File | Class | Role |
|---|---|---|
| `src/pipeline/m03_regime.py` | `M03RegimeCalculator` | The scoring logic (0–100 score + category) |
| `src/regime_pipeline.py` | `RegimePipeline` | Pipeline wrapper: history compute, incremental update, DB write, parity check |
| `src/pipeline/risk_5_factor.py` | `RiskFiveFactorCalculator` | Separate 5-factor risk model → `t2_risk_scores` (exposure band + veto) |

## M03 scoring (`M03RegimeCalculator`)

Three pillars, weighted:

1. **Trend (40%)** — SPY price vs SMA_200.
2. **Liquidity (30%)** — Fed Net Liquidity 20-day slope (WALCL/WTREGEN, with
   publication-lag handling: FRED data is shifted to its release date, not its
   observation date, to stay point-in-time correct).
3. **Risk Appetite (30%)** — VIX level + HY credit spread.

Categories from `DEFAULT_CONFIG['thresholds']`: `strong_bull` ≥80, `bull` ≥60,
`neutral` ≥40, `bear` ≥20, `strong_bear` <20. Gating params: `long_allow_min=30`,
`long_reduced_min=50`. Config is overridable from `models/m03_config.json`
(none committed — defaults apply).

**Output table** `t2_regime_scores` (one row/date): `m03_score`,
`m03_pillar_trend`, `m03_pillar_liq`, `m03_pillar_risk`, `m03_delta_5d`,
`m03_delta_20d`, `m03_regime_vol`. Joined into T3 by date (Phase 5A) and exposed
as ML features.

## RegimePipeline API

```python
RegimePipeline(db_path)
    .compute_m03_history(...)    # full-history recompute
    .update_incremental()        # daily pipeline path (orchestrator Phase 4)
    .backfill(...)               # historical backfill
    .write_to_db(...)
    .validate_parity(parquet_path='models/m03_history.parquet')
```

## 5-factor risk model (`risk_5_factor.py`)

Distinct from M03 (do not conflate). Factors (all oriented positive = more risk):
`f_vix` 0.25, `f_hy` 0.25, `f_term` 0.15, `f_trend` 0.15, `f_slope` 0.20.
10-year rolling z-score per factor → weighted sum → 5-year rolling percentile →
exposure band; any single z ≥ 2.0 vetoes to `target_exposure = 0.15`.
Writes `t2_risk_scores`.

## What M03 is and is not (falsification record — don't re-litigate)

- **M03 does not flag entry timing.** The validated timing/deploy signals are
  SPY>200d and `stress_ew_vix` (MacroSizer), not the M03 score. The macro-sizing
  backtest showed VIX-based sizing works while M03 sizing is a no-op.
- **SPY-200d remains the whole go/no-go regime tool** — multivariate macro
  composites did not beat it (coincident trade-gauge study).
- 15 candidate regime indicators all failed to break the ~0.65 AUC wall
  (5th falsification); the "better regime indicator" lever is retired.
- The dashboard's 6-pillar macro board (`load_macro_pillars`) is a **different
  object** from M03's 3 pillars — verify table citations against the DB before
  quoting either.

## Related

- Backtest-side regime use: [backtest.md](backtest.md) (`MacroSizer`, regime feed)
- Deploy posture surfaced to the dashboard: `weather_gauge` ([engines.md](engines.md))
