# Goal 5: Vectorized Parameter Optimizer

We will build an Optuna-based parameter optimizer over the fast `VectorizedSEPABacktest` engine to perform rapid hyperparameter sweeps for the trading strategy (e.g. stop-loss, SMA exit, entry thresholds).

## Open Questions

> [!WARNING]
> **Walk-Forward Validation**: You mentioned the optimizer should be "walk-forward-gated to avoid overfit". 
> Should the script automatically perform a rolling walk-forward optimization (e.g. optimize on Year 1, test on Year 2, optimize on Year 2, test on Year 3...), or simply accept separate `--is-start`/`--is-end` (In-Sample) and `--oos-start`/`--oos-end` (Out-Of-Sample) arguments to do a single Train/Test split?
> 
> **Objective Metric**: What is the primary metric we should maximize? (e.g., Sharpe Ratio, SQN, or Total Return). I propose Sharpe Ratio.

## Proposed Changes

### [NEW] `scripts/run_strategy_optimizer.py`

A new CLI script to run the parameter optimizer.

- **Data Preloading**: Pre-score the universe via `UniverseScorer` and pre-load all relevant prices. Inject these into `VectorizedSEPABacktest(precomputed_scores=..., precomputed_prices=...)` so each trial runs in milliseconds.
- **Optuna Objective Function**: 
  - Define parameter search spaces for `VectorizedSEPABacktest`:
    - `min_prob_elite`: Float (e.g., 0.15 to 0.35)
    - `max_positions_per_day`: Int (1 to 5)
    - `stop_loss_pct`: Float (0.05 to 0.15)
    - `sma_exit_period`: Categorical (20, 50, 100)
    - `ranking_lookback_days`: Categorical (5, 10, 20)
  - Run the backtest.
  - Calculate the objective metric (e.g. Annualized Sharpe Ratio) from the equity curve.
- **Reporting**:
  - Save `optimization_results.json` containing the best parameters and metric.
  - If a walk-forward / OOS period is defined, run the best parameters on the OOS period and output a comparison Markdown report.

## Verification Plan

### Automated Tests
- Run the optimizer on a small universe with `--n-trials 5` to ensure it completes successfully and outputs valid metrics.

### Manual Verification
- Review the `optimization_results.json` to verify the chosen parameters make logical sense and the script completes quickly due to vectorization.
