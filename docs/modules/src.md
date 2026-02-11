# Module: src

## 1. Overview

**Location:** `C:\Users\Hang\PycharmProjects\quantamental\src`
**Files:** 68

## 2. Visual Architecture

```mermaid
graph TD
    alpha_factors[alpha_factors]
    backtest_feeds[backtest.feeds]
    backtest_position_tracker[backtest.position_tracker]
    backtest_price_feed[backtest.price_feed]
    backtest_regime_feed[backtest.regime_feed]
    backtest_report[backtest.report]
    backtest_runner[backtest.runner]
    backtest_runner --> feeds
    backtest_runner --> sepa_strategy
    backtest_runner --> price_feed
    backtest_score_lookup[backtest.score_lookup]
    backtest_sepa_strategy[backtest.sepa_strategy]
    backtest_sepa_strategy --> score_lookup
    backtest_sepa_strategy --> position_tracker
    backtest_trade_logger[backtest.trade_logger]
    backtest_universe_scorer[backtest.universe_scorer]
    backtester[backtester]
    buy_list_manager[buy_list_manager]
    buy_list_manager --> config
    company_profile_engine[company_profile_engine]
    cross_sectional_features[cross_sectional_features]
    dashboard_reports[dashboard_reports]
    data_engine[data_engine]
    database[database]
    dataset_merger[dataset_merger]
    dataset_rehydrator[dataset_rehydrator]
    earnings_engine[earnings_engine]
    eda_utils[eda_utils]
    evaluate_model[evaluate_model]
    evaluation_errors[evaluation.errors]
    evaluation_feature_analyzer[evaluation.feature_analyzer]
    evaluation_feature_screener[evaluation.feature_screener]
    evaluation_feature_screener --> feature_analyzer
    evaluation_m01_evaluator[evaluation.m01_evaluator]
    evaluation_m01_evaluator --> metrics
    evaluation_m01_evaluator --> ranking
    evaluation_m01_evaluator --> errors
    evaluation_m03_evaluator[evaluation.m03_evaluator]
    evaluation_m03_grid_search[evaluation.m03_grid_search]
    evaluation_m03_ground_truth[evaluation.m03_ground_truth]
    evaluation_metrics[evaluation.metrics]
    evaluation_ranking[evaluation.ranking]
    evaluation_reports[evaluation.reports]
    evaluation_targets[evaluation.targets]
    feature_config[feature_config]
    feature_preprocessor[feature_preprocessor]
    feature_rehydrator[feature_rehydrator]
    features[features]
    features_stub[features_stub]
    fundamental_column_mapping[fundamental_column_mapping]
    fundamental_engine[fundamental_engine]
    fundamental_merger[fundamental_merger]
    fundamental_processor[fundamental_processor]
    indicators[indicators]
    macro_engine[macro_engine]
    ml_scorer[ml_scorer]
    model_preparation[model_preparation]
    pipeline_base_trainer[pipeline.base_trainer]
    pipeline_data_pipeline[pipeline.data_pipeline]
    pipeline_data_pipeline_test[pipeline.data_pipeline_test]
    pipeline_m01_trainer[pipeline.m01_trainer]
    pipeline_m01_trainer --> base_trainer
    pipeline_m01_workflow[pipeline.m01_workflow]
    pipeline_m01_workflow --> data_pipeline
    pipeline_m01_workflow --> m01_trainer
    pipeline_m02_trainer[pipeline.m02_trainer]
    pipeline_m02_trainer --> base_trainer
    pipeline_m03_regime[pipeline.m03_regime]
    pipeline_production_scorer[pipeline.production_scorer]
    reporting[reporting]
    strategy[strategy]
    temporal_validator[temporal_validator]
    ticker_filter[ticker_filter]
    trade_simulator[trade_simulator]
    trade_simulator_fast[trade_simulator_fast]
    trading_config[trading_config]
    train_model[train_model]
    train_model --> model_preparation
    triple_barrier_labeler[triple_barrier_labeler]
    universe_engine[universe_engine]
    utils[utils]
    vectorized_screening[vectorized_screening]
    viz_library[viz_library]
```

## 3. Data Schemas

### SEPAPosition (dataclass)
*Defined in: `backtest.position_tracker`*

| Field | Type |
|-------|------|
| `ticker` | `str` |
| `entry_date` | `datetime` |
| `entry_price` | `float` |
| `entry_atr` | `float` |
| `initial_size` | `int` |
| `score` | `float` |
| `regime` | `int` |
| `initial_stop` | `float` |
| `target1` | `float` |
| `target2` | `float` |
| `tranche1_sold` | `bool` |
| `tranche2_sold` | `bool` |
| `remaining_shares` | `int` |
| `tranche1_pending` | `bool` |
| `tranche2_pending` | `bool` |
| `exit_pending` | `bool` |
| `current_stop` | `float` |
| `exit_date` | `Optional[datetime]` |
| `exit_price` | `Optional[float]` |
| `exit_reason` | `Optional[str]` |
| `max_progression` | `int` |

### DailySnapshot (dataclass)
*Defined in: `backtest.sepa_strategy`*

| Field | Type |
|-------|------|
| `date` | `datetime` |
| `portfolio_value` | `float` |
| `cash` | `float` |
| `position_value` | `float` |
| `position_count` | `int` |
| `regime` | `int` |

### SignalRejection (dataclass)
*Defined in: `backtest.sepa_strategy`*

| Field | Type |
|-------|------|
| `date` | `datetime` |
| `ticker` | `str` |
| `score` | `float` |
| `reason` | `str` |

### TradeLog (dataclass)
*Defined in: `backtest.trade_logger`*

| Field | Type |
|-------|------|
| `ticker` | `str` |
| `entry_date` | `datetime` |
| `entry_price` | `float` |
| `entry_score` | `float` |
| `entry_regime` | `int` |
| `entry_atr` | `float` |
| `initial_size` | `int` |
| `initial_stop` | `float` |
| `target1` | `float` |
| `target2` | `float` |
| `exit_date` | `Optional[datetime]` |
| `exit_price` | `Optional[float]` |
| `exit_reason` | `Optional[str]` |
| `final_size` | `int` |
| `pnl_dollars` | `float` |
| `pnl_percent` | `float` |
| `holding_days` | `int` |
| `tranche1_date` | `Optional[datetime]` |
| `tranche1_price` | `Optional[float]` |
| `tranche2_date` | `Optional[datetime]` |
| `tranche2_price` | `Optional[float]` |

### Position (dataclass)
*Defined in: `backtester`*

| Field | Type |
|-------|------|
| `ticker` | `str` |
| `entry_date` | `pd.Timestamp` |
| `entry_price` | `float` |
| `stop_price` | `float` |
| `target_price` | `float` |
| `shares` | `int` |
| `position_value` | `float` |
| `status` | `str` |
| `exit_date` | `Optional[pd.Timestamp]` |
| `exit_price` | `Optional[float]` |
| `exit_reason` | `Optional[str]` |

### WorkflowConfig (dataclass)
*Defined in: `pipeline.m01_workflow`*

| Field | Type |
|-------|------|
| `start_date` | `str` |
| `end_date` | `str` |
| `success_threshold` | `float` |
| `candidate_features` | `List[str]` |
| `ks_threshold` | `float` |
| `correlation_threshold` | `float` |
| `auto_select` | `bool` |
| `fast_eda` | `bool` |
| `exclude_m03` | `bool` |
| `enrich_mfe` | `bool` |
| `eda_target` | `str` |
| `target_type` | `str` |
| `tune` | `bool` |
| `n_jobs` | `int` |
| `generate_report` | `bool` |
| `output_dir` | `str` |
| `save_model` | `bool` |

### Trade (dataclass)
*Defined in: `trade_simulator`*

| Field | Type |
|-------|------|
| `trade_id` | `int` |
| `ticker` | `str` |
| `entry_date` | `pd.Timestamp` |
| `entry_price` | `float` |
| `exit_date` | `Optional[pd.Timestamp]` |
| `exit_price` | `Optional[float]` |
| `return_pct` | `Optional[float]` |
| `days_held` | `Optional[int]` |
| `exit_reason` | `Optional[str]` |
| `entry_indicators` | `Dict` |
| `max_drawdown_pct` | `Optional[float]` |
| `max_favorable_excursion_pct` | `Optional[float]` |
| `r_multiple` | `Optional[float]` |
| `sharpe_ratio` | `Optional[float]` |
| `initial_risk_pct` | `Optional[float]` |
| `label` | `Optional[int]` |

### TradingConfig (dataclass)
*Defined in: `trading_config`*

| Field | Type |
|-------|------|
| `success_threshold_pct` | `float` |
| `exit_on_trend_break` | `bool` |
| `exit_on_stop_loss` | `bool` |
| `stop_loss_pct` | `float` |
| `max_positions` | `int` |
| `position_size_pct` | `float` |
| `allow_reentry` | `bool` |
| `reentry_cooldown_days` | `int` |
| `labeling_function` | `Optional[Callable[['Trade'], int]]` |

### StaticBarrierParams (dataclass)
*Defined in: `triple_barrier_labeler`*

| Field | Type |
|-------|------|
| `upper_pct` | `float` |
| `lower_pct` | `float` |
| `time_days` | `int` |

### DynamicBarrierParams (dataclass)
*Defined in: `triple_barrier_labeler`*

| Field | Type |
|-------|------|
| `upper_atr_mult` | `float` |
| `lower_atr_mult` | `float` |
| `time_days` | `int` |

### HybridBarrierParams (dataclass)
*Defined in: `triple_barrier_labeler`*

| Field | Type |
|-------|------|
| `k_sl` | `float` |
| `k_tp` | `float` |
| `min_tp` | `float` |
| `max_time` | `int` |
| `min_time` | `int` |

## 4. Implementation Rules

| Constant | Value | File |
|----------|-------|------|
| `DEFAULT_ALPHAS` | `[1, 6, 9, 12, 41, 101, 2, 4, 11, 13, 15, 54, 60, 4` | `alpha_factors` |
| `BACKTEST_DATA_DIR` | `config.DATA_DIR / 'backtest'` | `backtest.price_feed` |
| `PRICE_OUTPUT_DIR` | `BACKTEST_DATA_DIR / 'prices'` | `backtest.price_feed` |
| `BACKTEST_DATA_DIR` | `config.DATA_DIR / 'backtest'` | `backtest.regime_feed` |
| `BACKTEST_DATA_DIR` | `config.DATA_DIR / 'backtest'` | `backtest.runner` |
| `BACKTEST_DATA_DIR` | `config.DATA_DIR / 'backtest'` | `backtest.universe_scorer` |
| `D2_PATH` | `config.DATA_DIR / 'ml' / 'd2.parquet'` | `backtest.universe_scorer` |
| `X` | `df[self._m01_features].copy()` | `backtest.universe_scorer` |
| `MIN_GROUP_SIZE` | `3` | `cross_sectional_features` |
| `BACKTEST_RUNS_DIR` | `Path('data/backtest/runs')` | `dashboard_reports` |
| `DEFAULT_HISTORICAL_START_DATE` | `'2000-01-01'` | `data_engine` |
| `LIVE` | `'live'` | `data_engine` |
| `HISTORICAL` | `'historical'` | `data_engine` |
| `CACHE_ONLY` | `'cache_only'` | `data_engine` |
| `X` | `X.copy()` | `eda_utils` |
| `MFE` | `(highest - entry_price) / entry_price * 100` | `eda_utils` |
| `MAE` | `(lowest - entry_price) / entry_price * 100` | `eda_utils` |
| `X` | `subset[valid_features]` | `evaluation.feature_analyzer` |
| `EXPLOSIVE_FEATURES` | `['volume_acceleration', 'Dry_Up_Volume', 'Vol_Rati` | `evaluation.feature_screener` |
| `STANDARD_FEATURES` | `['RSI_14', 'earnings_quality_score', 'operating_ma` | `evaluation.feature_screener` |
| `BOUNDED_FEATURES` | `['RSI_14', 'RSI_5', 'RSI_21', 'earnings_quality_sc` | `evaluation.feature_screener` |
| `SEPA_AUDIT_FEATURES` | `['rs_rating', 'RS_Universe_Rank', 'Price_vs_SMA_20` | `evaluation.feature_screener` |
| `SKIP_MONOTONICITY` | `['industry_id_encoded', 'sector_id_encoded']` | `evaluation.feature_screener` |
| `CCR_SCORE_THRESHOLD` | `30` | `evaluation.m03_evaluator` |
| `FAR_SCORE_THRESHOLD` | `40` | `evaluation.m03_evaluator` |
| `LAG_SCORE_THRESHOLD` | `40` | `evaluation.m03_evaluator` |
| `AUC_TARGET` | `0.9` | `evaluation.m03_evaluator` |
| `COHENS_D_TARGET` | `2.0` | `evaluation.m03_evaluator` |
| `CCR_TARGET` | `0.8` | `evaluation.m03_evaluator` |
| `FAR_TARGET` | `0.05` | `evaluation.m03_evaluator` |
| `LAG_TARGET` | `7` | `evaluation.m03_evaluator` |
| `ARCHETYPES` | `{'baseline': {'description': 'Control Group (Curre` | `evaluation.m03_grid_search` |
| `VIX_CURVES` | `{'standard': {'description': 'Normal VIX sensitivi` | `evaluation.m03_grid_search` |
| `CRITICAL_CRASH_PERIODS` | `[{'name': 'COVID Crash', 'start_date': '2020-02-20` | `evaluation.m03_ground_truth` |
| `TECHNICAL_FEATURES` | `['Price_vs_SMA_50', 'Price_vs_SMA_150', 'Price_vs_` | `feature_config` |
| `ALPHA_FEATURES` | `['alpha001', 'alpha002', 'alpha004', 'alpha006', '` | `feature_config` |
| `FUNDAMENTAL_FEATURES` | `['eps_growth_yoy', 'revenue_growth_yoy', 'net_inco` | `feature_config` |
| `COMPANY_FEATURES` | `['sector_id', 'industry_id']` | `feature_config` |
| `CROSS_SECTIONAL_FEATURES` | `['RS_Universe_Rank', 'RS_Sector_Rank', 'RS_vs_Sect` | `feature_config` |
| `FEATURES_TO_LAG` | `['nATR', 'ATR', 'VCP_Ratio', 'Consolidation_Width'` | `feature_config` |
| `DELTA_FEATURES` | `[f'{feature}_Delta' for feature in FEATURES_TO_LAG` | `feature_config` |
| `LEAKAGE_FEATURES` | `['MFE', 'MAE', 'y_max', 'regret', 'return_pct', 'e` | `feature_config` |
| `CATEGORICAL_FEATURES` | `['sector_id', 'industry_id']` | `feature_config` |
| `M03_FEATURES` | `['m03_score', 'm03_regime_cat', 'm03_delta_5d', 'm` | `feature_config` |
| `EXCLUDE_BENCHMARK_RS` | `[]` | `feature_config` |
| `EXCLUDE_STALE_FEATURES` | `['mktCap_log', 'beta', 'RSI_Regime', 'log_beta']` | `feature_config` |
| `FEATURE_AUTO_EXCLUDE` | `EXCLUDE_BENCHMARK_RS + EXCLUDE_STALE_FEATURES` | `feature_config` |
| `M01_FEATURES` | `['log_breakout_momentum', 'log_VCP_Ratio_Delta', '` | `feature_config` |
| `M01_V2_FEATURES` | `['log_Price_vs_SMA_200', 'alpha011', 'log_nATR', '` | `feature_config` |
| `M01_3BAR_FEATURES` | `M01_FEATURES.copy()` | `feature_config` |
| `M01_3BAR_VELOCITY_ONLY` | `['RS', 'alpha011', 'Dist_From_20D_Low', 'Price_vs_` | `feature_config` |
| `M02_FEATURES` | `M01_3BAR_VELOCITY_ONLY.copy()` | `feature_config` |
| `M01_3BAR_FEATURES_V2` | `M02_FEATURES` | `feature_config` |
| `EXCLUDE_METADATA` | `['date', 'ticker', 'label', 'return_pct', 'days_he` | `feature_config` |
| `EXCLUDE_RAW_COLUMNS` | `['Open', 'High', 'Low', 'Close', 'Volume', 'High_5` | `feature_config` |
| `EXCLUDE_PRICE_STRUCTURE` | `['Lowest_Low_20D', 'Highest_High_20D', 'Lowest_Low` | `feature_config` |
| `EXCLUDE_LAG_FEATURES` | `[f'{f}_Lag1' for f in FEATURES_TO_LAG]` | `feature_config` |
| `EXCLUDE_RAW_FUNDAMENTALS` | `['operatingCashFlow', 'freeCashFlow', 'netIncome',` | `feature_config` |
| `FEATURE_EXCLUSION_LIST` | `EXCLUDE_METADATA + EXCLUDE_RAW_COLUMNS + EXCLUDE_P` | `feature_config` |
| `M01_CANDIDATE_FEATURES` | `M01_FEATURES + ['RS_Universe_Rank', 'RS_Sector_Ran` | `feature_config` |
| `EXPLOSIVE_FEATURES` | `['volume_acceleration', 'Dry_Up_Volume', 'Vol_Rati` | `feature_preprocessor` |
| `STANDARD_FEATURES` | `['RSI_14', 'earnings_quality_score', 'operating_ma` | `feature_preprocessor` |
| `BOUNDED_FEATURES` | `['RSI_14', 'RSI_5', 'RSI_21', 'earnings_quality_sc` | `feature_preprocessor` |
| `FEATURES_TO_LAG` | `['nATR', 'ATR', 'VCP_Ratio', 'Consolidation_Width'` | `features` |
| `CASH_FLOW_COLUMN_MAP` | `{'netCashProvidedByOperatingActivities': 'operatin` | `fundamental_column_mapping` |
| `DERIVED_FUNDAMENTAL_COLUMNS` | `['revenue_growth_yoy', 'eps_growth_yoy', 'net_inco` | `fundamental_column_mapping` |
| `RAW_FUNDAMENTAL_COLUMNS` | `['symbol', 'reportedCurrency', 'cik', 'accepted_da` | `fundamental_column_mapping` |
| `FRED_BASE_URL` | `'https://api.stlouisfed.org/fred/series/observatio...` | `macro_engine` |
| `X` | `X.copy()` | `model_preparation` |
| `X` | `self.remove_missing_features(X)` | `model_preparation` |
| `X` | `self.remove_infinite_values(X)` | `model_preparation` |
| `X` | `self.remove_correlated_features(X)` | `model_preparation` |
| `X` | `X.drop(columns=high_missing)` | `model_preparation` |
| `X` | `X.replace([np.inf, -np.inf], np.nan)` | `model_preparation` |
| `X` | `X.drop(columns=list(to_drop))` | `model_preparation` |
| `X` | `self.select_by_importance(X, y)` | `model_preparation` |
| `OPTUNA_AVAILABLE` | `True` | `pipeline.base_trainer` |
| `OPTUNA_AVAILABLE` | `False` | `pipeline.base_trainer` |
| `VALID_STEPS` | `['load', 'eda', 'select', 'train', 'report']` | `pipeline.m01_workflow` |
| `DEFAULT_BARRIER_PARAMS` | `{'k_sl': 1.0, 'k_tp': 4.0, 'min_tp': 0.2, 'max_tim` | `pipeline.m02_trainer` |
| `PUBLICATION_LAGS` | `{'WALCL': 1, 'WTREGEN': 1, 'RRPONTSYD': 1, 'BAMLH0` | `pipeline.m03_regime` |
| `DEFAULT_MACRO_LAG` | `1` | `pipeline.m03_regime` |
| `DEFAULT_CONFIG` | `{'model_name': 'M03', 'model_type': 'factor_calcul` | `pipeline.m03_regime` |
| `M01_FEATURE_COLUMNS` | `['m03_score', 'm03_regime_cat', 'm03_delta_5d', 'm` | `pipeline.m03_regime` |
| `CATEGORY_ORDINAL` | `{'strong_bear': 0, 'bear': 1, 'neutral': 2, 'bull'` | `pipeline.m03_regime` |
| `X` | `X.replace([np.inf, -np.inf], np.nan)` | `train_model` |
| `SEGMENT_YEARS` | `5` | `universe_engine` |
| `UNIVERSE_COLUMNS` | `['open', 'high', 'low', 'close', 'volume', 'turnov` | `universe_engine` |

## 5. Public Interface

### `alpha_factors`

**class AlphaEngine**
  - `calculate_alphas(df: pd.DataFrame) -> pd.DataFrame`
  - `get_alpha_names() -> List[str]`
  - `validate_alpha_output(df: pd.DataFrame) -> bool`
- `add_alpha_factors(df: pd.DataFrame, alpha_list: Optional[List[int]]) -> pd.DataFrame`

### `backtest.feeds`

**class SEPAStockFeed**
**class M03RegimeFeed**
- `load_stock_feed(ticker: str, prices_dir: str) -> SEPAStockFeed`
- `load_regime_feed(regime_path: str) -> M03RegimeFeed`

### `backtest.position_tracker`

**class PositionTracker**
  - `register_entry_intent(order_ref: int, intent: dict)`
  - `confirm_entry(order_ref: int, executed_price: float, executed_size: int) -> Optional[SEPAPosition]`
  - `record_partial_exit(ticker: str, shares_sold: int, exit_price: float, exit_reason: str, exit_date: Optional[datetime]) -> bool`
  - `is_in_cooldown(ticker: str, current_date: datetime, cooldown_days: int) -> bool`
  - `get_position(ticker: str) -> Optional[SEPAPosition]`
  - `has_position(ticker: str) -> bool`
  - `get_open_count() -> int`
  - `get_all_open() -> List[SEPAPosition]`
  - `get_all_closed() -> List[SEPAPosition]`
  - `update_stops(ticker: str, current_atr: float, current_high: float) -> Optional[float]`
  - `check_stops(ticker: str, current_low: float) -> bool`
  - `check_targets(ticker: str, current_high: float) -> Optional[str]`
  - `get_stats() -> Dict`

### `backtest.price_feed`

- `calculate_atr(df: pd.DataFrame, period: int) -> pd.Series`
- `get_qualifying_tickers(scores_path: Path, min_score: float, min_percentile: float) -> Set[str]`
- `prepare_price_feeds(start_date: str, end_date: str, scores_path: Optional[Path], output_dir: Optional[Path], min_score: float, min_percentile: float, atr_period: int) -> List[str]`
- `list_prepared_tickers(output_dir: Optional[Path]) -> List[str]`

### `backtest.regime_feed`

- `prepare_regime_feed(start_date: str, end_date: str, output_path: Optional[Path], trading_days_only: bool) -> pd.DataFrame`

### `backtest.report`

- `calculate_rolling_sharpe(equity_curve: pd.DataFrame, window_months: int, risk_free_rate: float) -> pd.Series`
- `generate_report(metrics: Dict[str, Any], trade_df: Optional[pd.DataFrame], equity_curve: Optional[pd.DataFrame], output_path: Optional[str], start_date: str, end_date: str, initial_cash: float, strategy_params: Optional[Dict[str, Any]]) -> str`
- `generate_monthly_returns(equity_curve: pd.Series) -> pd.DataFrame`

### `backtest.runner`

**class SEPABacktestRunner**
  - `setup(max_tickers: Optional[int], specific_tickers: List[str])`
  - `run() -> Dict[str, Any]`
  - `get_equity_curve_dataframe() -> Optional[pd.DataFrame]`
  - `get_trade_dataframe() -> Optional[pd.DataFrame]`
  - `save_report(metrics: Dict[str, Any], output_dir: Optional[Path]) -> str`
  - `save_run(metrics: Dict[str, Any], run_note: str) -> Path`
  - `print_results(metrics: Optional[Dict])`
  - `plot(save_path: Optional[str])`
- `run_backtest(start_date: str, end_date: str, initial_cash: float, max_tickers: Optional[int]) -> Dict[str, Any]`

### `backtest.score_lookup`

**class ScoreLookup**
  - `get_candidates(date: datetime, min_score: float, min_percentile: float, rank_by: Literal['trailing', 'daily']) -> List[Tuple[str, float, float]]`
  - `get_score(date: datetime, ticker: str) -> Optional[Tuple[float, float, float]]`
  - `get_available_dates() -> List[datetime]`
  - `get_date_range() -> Tuple[datetime, datetime]`
  - `get_stats() -> Dict`

### `backtest.sepa_strategy`

**class SEPAHybridV1**
  - `notify_order(order)`
  - `next()`
  - `stop()`
  - `get_exposure_stats() -> Dict`
  - `get_signal_rejection_stats() -> Dict`
  - `get_equity_curve() -> List[tuple]`

### `backtest.trade_logger`

**class TradeLogger**
  - `log_entry(ticker: str, entry_date: datetime, entry_price: float, entry_score: float, entry_regime: int, entry_atr: float, initial_size: int, initial_stop: float, target1: float, target2: float)`
  - `log_partial_exit(ticker: str, exit_date: datetime, exit_price: float, shares_sold: int, exit_reason: str)`
  - `get_open_trades() -> List[TradeLog]`
  - `get_closed_trades() -> List[TradeLog]`
  - `to_dataframe() -> pd.DataFrame`
  - `save(path: str)`
  - `load(path: str)`
  - `get_stats() -> Dict[str, Any]`
  - `get_exit_breakdown() -> Dict[str, int]`
  - `get_regime_breakdown() -> Dict[int, Dict[str, float]]`

### `backtest.universe_scorer`

**class UniverseScorer**
  - `load_model()`
  - `score_universe(start_date: str, end_date: str, output_path: Optional[Path]) -> pd.DataFrame`
- `score_universe(start_date: str, end_date: str, output_path: Optional[Path]) -> pd.DataFrame`

### `backtester`

**class PortfolioManager**
  - `get_position_size(price: float) -> int`
  - `can_open_position() -> bool`
  - `open_position(ticker: str, entry_date: pd.Timestamp, entry_price: float, stop_price: float, target_price: float) -> Optional[Position]`
  - `close_position(ticker: str, exit_date: pd.Timestamp, exit_price: float, reason: str) -> Optional[Position]`
  - `update_positions(date: pd.Timestamp, price_data: Dict[str, pd.DataFrame], strategy: SEPAStrategy) -> List[Position]`
  - `get_total_equity(current_prices: Dict[str, float]) -> float`
  - `record_equity(date: pd.Timestamp, equity: float)`
  - `get_equity_series() -> pd.Series`
  - `get_holdings_summary() -> pd.DataFrame`
**class BacktestEngine**
  - `run(price_data: Dict[str, pd.DataFrame], start_date: str, end_date: str) -> Tuple[pd.DataFrame, pd.DataFrame]`

### `buy_list_manager`

**class BuyListManager**
  - `update_buy_list(current_signals: pd.DataFrame, current_date: datetime)`
  - `get_summary() -> Dict`
  - `backfill(start_date: str, end_date: str, data_repo, strategy)`
  - `get_buy_list() -> pd.DataFrame`
  - `get_history() -> pd.DataFrame`

### `company_profile_engine`

**class CompanyProfileEngine**
  - `get_industry_mapping(use_cache: bool) -> Optional[pd.DataFrame]`
  - `get_sector_mapping(use_cache: bool) -> Optional[pd.DataFrame]`
  - `fetch_all_profiles(tickers: List[str], show_progress: bool, max_workers: int) -> pd.DataFrame`
  - `get_company_profiles(use_cache: bool, tickers: List[str]) -> pd.DataFrame`
  - `update_profiles_cache(tickers: List[str], force: bool, max_workers: int) -> Dict[str, bool]`
  - `get_ticker_profile(ticker: str) -> Optional[pd.Series]`
  - `get_cache_info() -> Dict`

### `cross_sectional_features`

- `add_cross_sectional_features(dataset: pd.DataFrame, company_profile_path: str, rs_column: str) -> pd.DataFrame`
- `get_cross_sectional_summary(dataset: pd.DataFrame) -> dict`

### `dashboard_reports`

- `load_model_config(model_name: str)`
- `load_feature_importance(model_name: str)`
- `load_latest_report(model_name: str)`
- `load_d1_report()`
- `load_d3_summary()`
- `load_eda_dashboard()`
- `discover_model_versions(model_prefix: str) -> list`
- `render_eda_summary()`
- `render_d1_analysis()`
- `render_m01_report()`
- `render_m02_report()`
- `render_dual_model()`
- `discover_backtest_runs() -> list`
- `load_backtest_manifest(run_id: str) -> dict`
- `load_backtest_metrics(run_id: str) -> dict`
- `load_backtest_equity(run_id: str)`
- `load_backtest_trades(run_id: str)`
- `format_run_label(run_id: str) -> str`
- `render_backtest()`
- `render_eda_feature_screening()`

### `data_engine`

**class CacheMode**
**class DataRepository**
  - `get_screener_universe() -> List[str]`
  - `update_universe(source: str) -> List[str]`
  - `get_ticker_data(ticker: str, use_cache: bool, source: str, mode: CacheMode, date_range: Optional[Tuple[str, str]], min_date: str, check_min_date: bool, max_retries: int, update_cache: bool, required_end_date: Optional[pd.Timestamp], force_cache_only: bool) -> Optional[pd.DataFrame]`
  - `update_cache(tickers: List[str], force: bool, source: str, max_workers: int, from_date: str) -> Dict[str, bool]`
  - `get_benchmark_data(mode: CacheMode, date_range: Optional[Tuple[str, str]], min_date: str, check_min_date: bool, required_end_date: Optional[pd.Timestamp], force_cache_only: bool) -> Optional[pd.Series]`
  - `get_batch_data(tickers: List[str], max_workers: int, show_progress: bool, mode: CacheMode, date_range: Optional[Tuple[str, str]], min_date: str, check_min_date: bool, required_end_date: Optional[pd.Timestamp], force_cache_only: bool) -> Dict[str, pd.DataFrame]`
  - `get_cached_tickers() -> List[str]`

### `database`

**class DatabaseManager**
  - `add_to_watchlist(ticker: str, current_date: str, rs: Optional[float], vol_ratio: Optional[float])`
  - `remove_from_watchlist(ticker: str, reason: str)`
  - `get_watchlist(active_only: bool) -> pd.DataFrame`
  - `clean_stale_watchlist(days_threshold: int)`
  - `add_to_buy_list(ticker: str, signal_date: str, signal_price: float, current_price: float, entry_price: Optional[float], stop_price: Optional[float], target_price: Optional[float], atr: Optional[float], rs: Optional[float], vol_ratio: Optional[float], ma50: Optional[float], ma150: Optional[float], ma200: Optional[float], high_52w: Optional[float], low_52w: Optional[float], nATR_lag1: Optional[float], atr_lag1: Optional[float], vcp_ratio_lag1: Optional[float], consolidation_width_lag1: Optional[float], price_vs_sma50_lag1: Optional[float], price_vs_sma150_lag1: Optional[float], price_vs_sma200_lag1: Optional[float], rs_lag1: Optional[float], rs_ma_lag1: Optional[float], dry_up_volume_lag1: Optional[float], high_52w_lag1: Optional[float], low_52w_lag1: Optional[float], rsi14_lag1: Optional[float], dist_from_52w_high_lag1: Optional[float], ml_probability: Optional[float], ml_expected_return: Optional[float], ml_model_type: Optional[str], ml_rank: Optional[int], ml_model_version: Optional[str], ml_score_date: Optional[str], ml_features: Optional[Dict], m01_expected_return: Optional[float], m01_rank: Optional[int], m01_3bar_prob: Optional[float], m01_3bar_rank: Optional[int], m01_3bar_sl_price: Optional[float], m01_3bar_tp_price: Optional[float])`
  - `remove_from_buy_list(ticker: str, reason: str)`
  - `update_buy_list_metrics(ticker: str, scan_date: str, current_price: float, rs: Optional[float], vol_ratio: Optional[float], ma50: Optional[float], ma150: Optional[float], ma200: Optional[float], high_52w: Optional[float], low_52w: Optional[float], ml_probability: Optional[float], ml_expected_return: Optional[float], ml_model_type: Optional[str], ml_rank: Optional[int], ml_model_version: Optional[str], ml_score_date: Optional[str], ml_features: Optional[str])`
  - `update_buy_list_ml_rank(ticker: str, ml_rank: int)`
  - `update_buy_list_column(ticker: str, column: str, value)`
  - `batch_update_ml_scores(updates: List[Dict])`
  - `get_buy_list(active_only: bool, as_of_date: Optional[str]) -> pd.DataFrame`
  - `log_buy_list_activity(ticker: str, action: str, action_date: str, reason: Optional[str], entry_price: Optional[float], stop_price: Optional[float], target_price: Optional[float], rs: Optional[float], vol_ratio: Optional[float])`
  - `clear_future_signals(cutoff_date: str) -> dict`
  - `clean_old_buy_signals(days_threshold: int)`
  - `log_trade(ticker: str, entry_date: str, entry_price: float, shares: int, stop_price: float, target_price: float)`
  - `close_trade(ticker: str, exit_date: str, exit_price: float, exit_reason: str)`
  - `get_trade_history(ticker: Optional[str], closed_only: bool) -> pd.DataFrame`
  - `get_performance_summary() -> Dict`
  - `export_to_csv(table_name: str, output_path: str)`

### `dataset_merger`

**class DatasetLoader**
  - `load_dataset_a(path: str) -> pd.DataFrame`
  - `load_dataset_b(path: str) -> pd.DataFrame`
  - `validate_schema(df: pd.DataFrame, dataset_type: str) -> bool`
**class SnapshotExtractor**
  - `extract_snapshot(ticker: str, date: pd.Timestamp) -> Optional[pd.Series]`
  - `batch_extract(trades: pd.DataFrame) -> pd.DataFrame`
**class DatasetMerger**
  - `load_datasets() -> Tuple[pd.DataFrame, pd.DataFrame]`
  - `validate_compatibility() -> bool`
  - `merge(merge_strategy: str) -> pd.DataFrame`
  - `get_merge_statistics() -> Dict`
  - `export(output_path: str, format: str)`

### `dataset_rehydrator`

**class DatasetRehydrator**
  - `rehydrate_trades(d1_trades: pd.DataFrame, n_jobs: int) -> pd.DataFrame`

### `earnings_engine`

**class EarningsEngine**
  - `get_ticker_earnings(ticker: str, use_cache: bool) -> Optional[pd.DataFrame]`
  - `get_latest_earnings_date(ticker: str) -> Optional[datetime]`
  - `has_new_earnings_since(ticker: str, since_date: datetime) -> bool`
  - `update_earnings_cache(tickers: List[str], force: bool, max_workers: int, show_progress: bool) -> Dict[str, bool]`
  - `get_tickers_needing_fundamental_update(tickers: List[str], fundamentals_dir: Path) -> List[str]`
  - `get_cache_stats() -> Dict`
  - `get_available_tickers() -> List[str]`

### `eda_utils`

- `calculate_mae_mfe(d2_df: pd.DataFrame) -> pd.DataFrame`
- `calculate_time_to_peak(d2_df: pd.DataFrame) -> pd.DataFrame`
- `analyze_failures(d2_df: pd.DataFrame, loss_threshold: float) -> pd.DataFrame`
- `analyze_feature_separation(df: pd.DataFrame, features: List[str], target: str) -> pd.DataFrame`
- `analyze_prediction_errors(df: pd.DataFrame, predictions: np.ndarray, features: List[str], toxic_threshold: float, fomo_threshold: float, fomo_return_threshold: float, accuracy_tolerance: float) -> pd.DataFrame`
- `event_study_analysis(d2_rehydrated: pd.DataFrame, predictions_df: pd.DataFrame) -> Tuple[pd.Series, pd.Series]`
- `analyze_calibration(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int) -> Tuple[np.ndarray, np.ndarray, float]`
- `validate_negative_filter(df: pd.DataFrame, probabilities: np.ndarray, threshold: float) -> Tuple[Dict, pd.DataFrame, pd.DataFrame]`
- `analyze_high_scores_shap(model, X: pd.DataFrame, y_prob: np.ndarray, threshold: float, sample_size: Optional[int]) -> Tuple[np.ndarray, pd.DataFrame, pd.DataFrame]`
- `find_latest_model(model_name: str) -> Path`
- `align_features(X: pd.DataFrame, model_feature_names: List[str]) -> pd.DataFrame`
- `add_prediction_deciles(df: pd.DataFrame, predictions: np.ndarray, col_name: str) -> pd.DataFrame`
- `add_trade_sequence(df: pd.DataFrame, date_col: str) -> pd.DataFrame`

### `evaluate_model`

**class ModelEvaluator**
  - `calculate_precision_at_k(y_true: np.ndarray, y_pred_proba: np.ndarray, k_values: List[float]) -> Dict[str, float]`
  - `calculate_classification_metrics(y_true: np.ndarray, y_pred: np.ndarray, y_pred_proba: np.ndarray) -> Dict`
  - `simulate_trading_returns(df: pd.DataFrame, y_pred_proba: np.ndarray, k_pct: float, return_col: str) -> Dict`
  - `compare_to_baseline(y_true: np.ndarray, df: pd.DataFrame, y_pred_proba: np.ndarray, k_pct: float, return_col: str) -> Dict`
  - `calculate_feature_importance_shap(model: object, X: pd.DataFrame, top_n: int, sample_size: int) -> pd.DataFrame`
  - `plot_roc_curve(y_true: np.ndarray, y_pred_proba: np.ndarray, fold_id: Optional[int], save: bool)`
  - `plot_precision_recall_curve(y_true: np.ndarray, y_pred_proba: np.ndarray, fold_id: Optional[int], save: bool)`
  - `plot_feature_importance(importance_df: pd.DataFrame, top_n: int, fold_id: Optional[int], save: bool)`
  - `evaluate_fold(model: object, X_test: pd.DataFrame, y_test: pd.Series, df_test: pd.DataFrame, fold_id: int, k_values: List[float]) -> Dict`
  - `generate_report(all_fold_results: List[Dict], output_path: str)`

### `evaluation.errors`

- `analyze_prediction_errors(predictions_df: pd.DataFrame, pred_col: str, actual_col: str, high_threshold: float, low_threshold: float) -> Dict`
- `classify_by_percentile(values: pd.Series, high_threshold: float, low_threshold: float) -> pd.Series`
- `calculate_error_cost(error_analysis: Dict) -> float`

### `evaluation.feature_analyzer`

**class FeatureAnalyzer**
  - `check_stationarity(df: pd.DataFrame, features: List[str], significance: float) -> pd.DataFrame`
  - `compute_kurtosis(df: pd.DataFrame, features: List[str], extreme_threshold: float) -> pd.DataFrame`
  - `analyze_missingness(df: pd.DataFrame, features: List[str], target: str) -> pd.DataFrame`
  - `compute_ic(df: pd.DataFrame, features: List[str], target: str) -> pd.DataFrame`
  - `compute_mutual_information(df: pd.DataFrame, features: List[str], target: str, n_neighbors: int) -> pd.DataFrame`
  - `analyze_decile_monotonicity(df: pd.DataFrame, features: List[str], target: str, n_bins: int) -> pd.DataFrame`
  - `compute_ic_stability(df: pd.DataFrame, features: List[str], target: str, date_col: str) -> pd.DataFrame`
  - `compute_psi(df: pd.DataFrame, features: List[str], date_col: str, baseline_years: int, n_bins: int) -> pd.DataFrame`
  - `cluster_features(df: pd.DataFrame, features: List[str], threshold: float) -> Dict[str, List[str]]`
  - `get_cluster_recommendations(clusters: Dict[str, List[str]], ic_stability_df: pd.DataFrame, ic_df: pd.DataFrame) -> List[Dict]`
  - `run_full_analysis(cls, df: pd.DataFrame, features: List[str], target: str, date_col: str) -> Dict`

### `evaluation.feature_screener`

- `target_encode_categorical(df: pd.DataFrame, categorical_col: str, target_col: str, smoothing: float, min_samples: int) -> pd.Series`
**class FeatureScreener**
  - `pre_filter_features(df: pd.DataFrame, candidate_features: Optional[List[str]], exclusion_list: Optional[List[str]]) -> Tuple[List[str], List[str]]`
  - `encode_categorical_features(df: pd.DataFrame, categorical_features: Optional[List[str]], target_col: str, smoothing: float) -> Tuple[pd.DataFrame, Dict[str, Dict]]`
  - `signed_log(x: np.ndarray) -> np.ndarray`
  - `compute_tail_alpha_ratio(df: pd.DataFrame, feature: str, target: str, core_range: Tuple[float, float], tail_range: Tuple[float, float]) -> float`
  - `transform_fat_tails(cls, df: pd.DataFrame, features: List[str], target: str, kurtosis_threshold: float, tail_alpha_threshold: float, lower_percentile: float, upper_percentile: float) -> Tuple[pd.DataFrame, Dict[str, List[str]]]`
  - `winsorize_features(cls, df: pd.DataFrame, features: List[str], lower_percentile: float, upper_percentile: float, kurtosis_threshold: float, auto_detect: bool) -> Tuple[pd.DataFrame, List[str]]`
  - `remove_correlated_features(df: pd.DataFrame, features: List[str], ks_scores: Optional[pd.DataFrame], correlation_threshold: float) -> Tuple[List[str], List[Dict]]`
  - `screen_features(df: pd.DataFrame, candidate_features: List[str], target_col: str, ks_threshold: float, p_value_threshold: float) -> Dict`
  - `run_pipeline(cls, df: pd.DataFrame, candidate_features: Optional[List[str]], target_col: str, ks_threshold: float, correlation_threshold: float, p_value_threshold: float) -> Dict`
  - `run_quant_pipeline(cls, df: pd.DataFrame, candidate_features: Optional[List[str]], target_col: str, date_col: str, ks_threshold: float, correlation_threshold: float, p_value_threshold: float, winsorize: bool, encode_categoricals: bool) -> Dict`
  - `generate_eda_report(screening_results: Dict, output_path: Path, target_col: str, ks_threshold: float, correlation_threshold: float) -> str`
  - `export_dashboard_json(screening_results: Dict, output_path: Path, target_col: str) -> str`
  - `generate_all_outputs(screening_results: Dict, output_dir: Path, target_col: str, ks_threshold: float, correlation_threshold: float) -> Dict[str, str]`

### `evaluation.m01_evaluator`

**class M01Evaluator**
  - `add_predictions(fold_predictions: pd.DataFrame)`
  - `evaluate_fold(y_true: pd.Series, y_pred: np.ndarray, test_year: int, n_train: int, n_test: int) -> Dict`
  - `evaluate_full() -> Dict`
  - `generate_scorecard(model, feature_cols: List[str], model_name: str) -> str`
  - `export_viz_data() -> Dict`
  - `get_fold_metrics_df() -> pd.DataFrame`
  - `reset()`

### `evaluation.m03_evaluator`

**class M03Evaluator**
  - `evaluate(start_date: str, end_date: str) -> Dict`
  - `generate_report(save: bool) -> str`
  - `get_merged_df() -> pd.DataFrame`
  - `calibrate_thresholds(ccr_target: float, far_target: float, save_config: bool) -> Dict`
  - `generate_calibration_report(calibration: Dict) -> str`
  - `reset()`

### `evaluation.m03_grid_search`

**class M03GridSearch**
  - `generate_configs() -> Dict[str, Path]`
  - `run_grid_search(start_date: str, end_date: str) -> pd.DataFrame`
  - `generate_comparison_report(df: pd.DataFrame) -> str`
  - `get_best_config_path(df: pd.DataFrame) -> Optional[Path]`
- `run_m03_grid_search(start_date: str, end_date: str, verbose: bool) -> pd.DataFrame`

### `evaluation.m03_ground_truth`

- `load_ground_truth_df(start_date: str, end_date: str, freq: str) -> pd.DataFrame`
- `get_strong_bear_periods() -> List[Dict]`
- `get_strong_bull_periods() -> List[Dict]`
- `get_regime_ordinal(regime: str) -> int`
- `get_critical_crash_info(crash_name: str) -> Dict`

### `evaluation.metrics`

- `calculate_ic(y_true: np.ndarray, y_pred: np.ndarray) -> Tuple[float, float]`
- `calculate_precision_at_k(y_true: np.ndarray, y_pred: np.ndarray, k: float, winner_threshold: float) -> float`
- `calculate_recall_at_k(y_true: np.ndarray, y_pred: np.ndarray, k: float, top_class_pct: float) -> float`
- `calculate_decile_lift(y_true: np.ndarray, y_pred: np.ndarray, top_pct: float) -> float`
- `calculate_volatility_correlation(predictions_df: pd.DataFrame, pred_col: str, vol_cols: Optional[List[str]]) -> Dict`

### `evaluation.ranking`

- `analyze_deciles(y_true: np.ndarray, y_pred: np.ndarray, n_deciles: int) -> Dict`
- `calculate_quantile_stats(y_true: np.ndarray, y_pred: np.ndarray, quantiles: List[float]) -> pd.DataFrame`
- `calculate_monotonicity_score(decile_means: List[float]) -> float`

### `evaluation.reports`

**class ReportGenerator**
  - `generate_scorecard(model_name: str, target_type: str, metrics_summary: Dict, fold_metrics: pd.DataFrame, feature_importance: pd.DataFrame, error_analysis: Dict, vol_correlation: Dict) -> str`

### `evaluation.targets`

**class TargetEngineer**
  - `calculate_survivor_mfe(d2_df: pd.DataFrame, d2r_df: pd.DataFrame, stop_multiplier: float) -> Tuple[pd.DataFrame, Dict]`
  - `calculate_hybrid_floor(d2_df: pd.DataFrame, d2r_df: pd.DataFrame, stop_multiplier: float, max_penalty: float) -> Tuple[pd.DataFrame, Dict]`
  - `calculate_risk_adjusted(d2_df: pd.DataFrame, d2r_df: pd.DataFrame, stop_multiplier: float) -> Tuple[pd.DataFrame, Dict]`
  - `calculate_log_space(d2_df: pd.DataFrame, d2r_df: pd.DataFrame, stop_multiplier: float) -> Tuple[pd.DataFrame, Dict]`
  - `calculate_log_hybrid(d2_df: pd.DataFrame, d2r_df: pd.DataFrame, stop_multiplier: float, hard_stop_pct: float, ma_column: str) -> Tuple[pd.DataFrame, Dict]`
  - `prepare_target(d2_df: pd.DataFrame, d2r_df: pd.DataFrame, target_type: str, stop_multiplier: float) -> Tuple[pd.DataFrame, Dict]`

### `feature_config`

- `get_model_features(model_name: str) -> List[str]`

### `feature_preprocessor`

**class FeaturePreprocessor**
  - `signed_log(x: np.ndarray) -> np.ndarray`
  - `compute_tail_alpha_ratio(df: pd.DataFrame, feature: str, target: str) -> float`
  - `fit(df: pd.DataFrame, features: List[str], target: str) -> 'FeaturePreprocessor'`
  - `transform(df: pd.DataFrame, inplace: bool) -> pd.DataFrame`
  - `get_transformed_feature_names(original_features: List[str]) -> List[str]`
  - `save(path: str) -> None`
  - `load(cls, path: str) -> 'FeaturePreprocessor'`
  - `summary() -> pd.DataFrame`

### `feature_rehydrator`

**class FeatureRehydrator**
  - `rehydrate_batch(candidates_df: pd.DataFrame, lookback_days: int) -> pd.DataFrame`

### `features`

**class FeatureEngineer**
  - `calculate_lightweight_features(df: pd.DataFrame) -> pd.DataFrame`
  - `add_lagged_features(df: pd.DataFrame, lag_periods: int) -> pd.DataFrame`
  - `calculate_heavyweight_features(df: pd.DataFrame, ticker: str) -> pd.DataFrame`
  - `process_universe_batch(ticker_data_dict: Dict[str, pd.DataFrame], show_progress: bool) -> Dict[str, pd.DataFrame]`
  - `validate_features(df: pd.DataFrame, mode: str) -> bool`
  - `get_feature_summary(df: pd.DataFrame) -> Dict`
  - `add_company_features(df: pd.DataFrame, ticker: str) -> pd.DataFrame`

### `features_stub`

**class FeatureEngineer**
  - `calculate_lightweight_features(df: pd.DataFrame) -> pd.DataFrame`
  - `get_fundamental_snapshot(ticker: str, date: pd.Timestamp) -> Dict[str, float]`

### `fundamental_column_mapping`

- `standardize_cash_flow_columns(df)`
- `get_columns_to_merge(include_raw: bool)`

### `fundamental_engine`

**class FundamentalEngine**
  - `fetch_income_statement(ticker: str) -> Optional[pd.DataFrame]`
  - `fetch_balance_sheet(ticker: str) -> Optional[pd.DataFrame]`
  - `fetch_cash_flow_statement(ticker: str) -> Optional[pd.DataFrame]`
  - `fetch_all_fundamentals(ticker: str) -> Optional[pd.DataFrame]`
  - `get_ticker_fundamentals(ticker: str, use_cache: bool) -> Optional[pd.DataFrame]`
  - `update_fundamentals_cache(tickers: List[str], force: bool, show_progress: bool, max_workers: int, use_earnings_calendar: bool) -> Dict[str, bool]`
  - `get_available_tickers() -> List[str]`
  - `get_cache_stats() -> Dict`

### `fundamental_merger`

**class FundamentalMerger**
  - `merge_ticker_data(ticker: str, price_df: pd.DataFrame) -> pd.DataFrame`
  - `calculate_hybrid_features(df: pd.DataFrame) -> pd.DataFrame`
  - `get_merge_statistics(df: pd.DataFrame) -> Dict`

### `fundamental_processor`

**class FundamentalProcessor**
  - `process_ticker_fundamentals(ticker: str, df: pd.DataFrame) -> pd.DataFrame`
  - `get_processed_fundamentals_summary(df: pd.DataFrame) -> Dict`

### `indicators`

**class TechnicalAnalysis**
  - `add_sma(df: pd.DataFrame, periods: list) -> pd.DataFrame`
  - `add_atr(df: pd.DataFrame, period: int) -> pd.DataFrame`
  - `add_52_week_highs_lows(df: pd.DataFrame) -> pd.DataFrame`
  - `add_relative_strength(df: pd.DataFrame, benchmark: pd.Series, lookback: int) -> pd.DataFrame`
  - `add_volume_metrics(df: pd.DataFrame, lookback: int) -> pd.DataFrame`
  - `add_breakout_signals(df: pd.DataFrame, period: int) -> pd.DataFrame`
  - `calculate_rsi(df: pd.DataFrame, period: int, column: str) -> pd.Series`
  - `add_normalized_atr(df: pd.DataFrame, period: int) -> pd.DataFrame`
  - `add_vcp_ratio(df: pd.DataFrame, short: int, long: int) -> pd.DataFrame`
  - `add_consolidation_width(df: pd.DataFrame, period: int) -> pd.DataFrame`
  - `add_dry_up_volume(df: pd.DataFrame, short: int, long: int) -> pd.DataFrame`
  - `calculate_all_indicators(df: pd.DataFrame, benchmark: Optional[pd.Series]) -> pd.DataFrame`
  - `detect_stage2_uptrend(df: pd.DataFrame) -> pd.Series`
  - `detect_vcp_setup(df: pd.DataFrame) -> pd.Series`
  - `detect_relative_strength(df: pd.DataFrame) -> pd.Series`

### `macro_engine`

**class MacroEngine**
  - `fetch_fred_series(series_id: str, start_date: str, end_date: str) -> pd.DataFrame`
  - `fetch_vix(start_date: str) -> pd.DataFrame`
  - `update_series(series_id: str, force: bool) -> pd.DataFrame`
  - `update_macro_cache(force: bool) -> Dict[str, int]`
  - `get_series(series_id: str, use_cache: bool) -> pd.DataFrame`
  - `get_net_liquidity(as_of_date: str) -> pd.DataFrame`
  - `get_all_macro_data(as_of_date: str) -> pd.DataFrame`

### `ml_scorer`

**class MLScorer**
  - `score_batch(X: pd.DataFrame, ticker_column: str, date_column: Optional[str]) -> Tuple[np.ndarray, np.ndarray]`
  - `filter_by_threshold(X: pd.DataFrame, probabilities: np.ndarray, ranks: np.ndarray, threshold: float, top_n: Optional[int]) -> pd.DataFrame`
  - `get_model_info() -> Dict`
- `update_prediction_log_with_outcome(ticker: str, prediction_date: str, actual_return_pct: float, actual_label: int, log_path: str)`
- `analyze_prediction_accuracy(log_path: str) -> Dict`

### `model_preparation`

**class TemporalSplitter**
  - `create_folds(df: pd.DataFrame, date_column: str, fold_specs: Optional[List[Tuple[str, str, str]]]) -> List[Dict]`
  - `get_fold_data(df: pd.DataFrame, fold_idx: int, feature_columns: Optional[List[str]]) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]`
**class FeatureSelector**
  - `remove_missing_features(X: pd.DataFrame) -> pd.DataFrame`
  - `remove_infinite_values(X: pd.DataFrame) -> pd.DataFrame`
  - `remove_correlated_features(X: pd.DataFrame, method: str) -> pd.DataFrame`
  - `select_by_importance(X: pd.DataFrame, y: pd.Series, model: Optional[object], method: str) -> pd.DataFrame`
  - `fit_transform(X: pd.DataFrame, y: Optional[pd.Series]) -> pd.DataFrame`
  - `transform(X: pd.DataFrame) -> pd.DataFrame`
- `prepare_training_data(dataset_path: str, purge_gap_days: int, correlation_threshold: float, keep_top_n: Optional[int], fold_specs: Optional[List[Tuple[str, str, str]]]) -> Dict`

### `pipeline.base_trainer`

**class BaseTrainer**
  - `get_features() -> List[str]`
  - `get_target_col() -> str`
  - `get_model_params(tuned_params: Optional[Dict]) -> Dict`
  - `create_model(params: Dict)`
  - `model_type() -> str`
  - `model_name() -> str`
  - `clean_data(data: pd.DataFrame, feature_cols: List[str]) -> pd.DataFrame`
  - `analyze_deciles(y_true: pd.Series, y_pred: np.ndarray, n_deciles: int) -> Dict`
  - `tune_hyperparameters(X: pd.DataFrame, y: pd.Series, n_trials: int, n_splits: int) -> Dict`
  - `train(data: pd.DataFrame, tune: bool, tune_trials: int, train_years: int, test_years: int) -> Tuple`
  - `save(model, metrics_df: pd.DataFrame, config: Optional[Dict])`

### `pipeline.data_pipeline`

**class DataPipeline**
  - `scan(start_date: str, end_date: str, threshold: float, save: bool) -> pd.DataFrame`
  - `features(d1: pd.DataFrame, n_jobs: int, save: bool, include_m03: bool, apply_preprocessing: bool) -> pd.DataFrame`
  - `hydrate(d1: pd.DataFrame, horizon_days: Optional[int], n_jobs: int, save: bool) -> pd.DataFrame`
  - `label(d2r: pd.DataFrame, k_sl: float, k_tp: float, min_tp: float, max_time: int, n_jobs: int, save: bool, horizon_days: Optional[int], include_m03: bool, apply_preprocessing: bool) -> pd.DataFrame`
  - `rehydrate_d3(d1: pd.DataFrame, d3: pd.DataFrame, n_jobs: int, save: bool, horizon_days: int) -> pd.DataFrame`
  - `load_d1() -> pd.DataFrame`
  - `load_d2() -> pd.DataFrame`
  - `load_d2r(horizon_days: Optional[int]) -> pd.DataFrame`
  - `load_d3(horizon_days: Optional[int]) -> pd.DataFrame`

### `pipeline.data_pipeline_test`

**class DataPipelineTest**
  - `scan(start_date: str, end_date: str, threshold: float, save: bool) -> pd.DataFrame`
  - `features(d1: pd.DataFrame, n_jobs: int, save: bool, include_m03: bool, apply_preprocessing: bool) -> pd.DataFrame`
  - `load_d1() -> pd.DataFrame`
  - `load_d2() -> pd.DataFrame`

### `pipeline.m01_trainer`

**class M01Trainer**
  - `model_type() -> str`
  - `model_name() -> str`
  - `get_features() -> List[str]`
  - `get_target_col() -> str`
  - `get_model_params(tuned_params: Optional[Dict]) -> Dict`
  - `create_model(params: Dict)`
  - `enrich_with_survivor_labels(data: pd.DataFrame, d2r_path: str, stop_multiplier: float) -> pd.DataFrame`
  - `calculate_y_max(data: pd.DataFrame, d2r_path: str) -> pd.DataFrame`
  - `train(data: pd.DataFrame, tune: bool, tune_trials: int, train_years: int, test_years: int, target: str, survivor_model: bool, stop_multiplier: float) -> Tuple`
  - `save_feature_importance(model, feature_cols: List[str]) -> pd.DataFrame`
  - `generate_report(model, metrics_df: pd.DataFrame, start_date: str, end_date: str) -> str`
  - `calibrate(predictions: Optional[pd.DataFrame], n_bins: int) -> Dict`
  - `save_calibrator(path: Optional[str]) -> str`
  - `load_calibrator(path: Optional[str])`
  - `predict_calibrated(X: pd.DataFrame, model) -> np.ndarray`
  - `run_volatility_detector_test(predictions: Optional[pd.DataFrame], atr_column: str) -> Dict`
  - `compute_volatility_adjusted_score(predictions: pd.DataFrame, atr_column: str, penalty_weight: float) -> pd.DataFrame`
  - `compute_combined_score(m01_predictions: pd.DataFrame, m02_model, m02_features: pd.DataFrame, use_volatility_adjustment: bool, atr_column: str, penalty_weight: float) -> pd.DataFrame`
  - `run_crisis_simulation(data: pd.DataFrame, model, crisis_period: tuple, m02_model, use_volatility_adjustment: bool) -> Dict`

### `pipeline.m01_workflow`

**class M01Workflow**
  - `run(steps: List[str]) -> Dict`

### `pipeline.m02_trainer`

**class M02Trainer**
  - `model_type() -> str`
  - `model_name() -> str`
  - `get_features() -> List[str]`
  - `get_target_col() -> str`
  - `get_model_params(tuned_params: Optional[Dict]) -> Dict`
  - `create_model(params: Dict)`
  - `prepare_data(data: pd.DataFrame) -> pd.DataFrame`
  - `train(data: pd.DataFrame, tune: bool, tune_trials: int, train_years: int, test_years: int)`
  - `get_model_params(tuned_params: Optional[Dict]) -> Dict`
  - `save_feature_importance(model, feature_cols: List[str]) -> pd.DataFrame`
  - `generate_report(model, metrics_df: pd.DataFrame, start_date: str, end_date: str) -> str`
  - `save(model, metrics_df: pd.DataFrame, config: Optional[Dict])`

### `pipeline.m03_regime`

**class M03RegimeCalculator**
  - `save_config(path: str) -> None`
  - `get_regime_category(score: float) -> str`
  - `calculate(as_of_date: str) -> Dict`
  - `should_gate_signal(score: float, as_of_date: str) -> Dict`
  - `calculate_history_vectorized(start_date: str, end_date: str, freq: str) -> pd.DataFrame`
  - `calculate_history(start_date: str, end_date: str, freq: str) -> pd.DataFrame`
  - `save_history(df: pd.DataFrame, path: str, format: str) -> str`
  - `load(config_path: str) -> 'M03RegimeCalculator'`
  - `generate_m01_features(start_date: str, end_date: str, freq: str) -> pd.DataFrame`
- `verify_m03_features(df: pd.DataFrame, raise_on_error: bool, feature_columns: list) -> dict`

### `pipeline.production_scorer`

**class ProductionScorer**
  - `load_models()`
  - `score(candidates: pd.DataFrame, use_volatility_adjustment: bool, use_m02: bool, atr_column: str, penalty_weight: float) -> pd.DataFrame`
  - `get_position_sizes(scores: pd.DataFrame, portfolio_value: float, max_positions: int, score_threshold: float, score_column: str, sizing_method: str) -> pd.DataFrame`
  - `score_and_size(candidates: pd.DataFrame, portfolio_value: float, use_volatility_adjustment: bool, use_m02: bool, sizing_method: str) -> pd.DataFrame`
  - `generate_trade_report(positions: pd.DataFrame, output_path: Optional[str]) -> str`

### `reporting`

**class PerformanceReporter**
  - `calculate_metrics() -> Dict`
  - `print_summary()`
  - `plot_performance(save_path: Optional[str])`
  - `get_top_trades(n: int) -> Tuple[pd.DataFrame, pd.DataFrame]`
  - `export_trades(file_path: str)`
  - `generate_html_report(output_path: str)`

### `strategy`

**class AlphaModel**
  - `generate_signals(df: pd.DataFrame, date: pd.Timestamp) -> Dict`
**class SEPAStrategy**
  - `prepare_data(df: pd.DataFrame) -> pd.DataFrame`
  - `screen_candidates(df: pd.DataFrame, date: pd.Timestamp) -> bool`
  - `check_trigger(df: pd.DataFrame, date: pd.Timestamp) -> bool`
  - `check_relative_strength(df: pd.DataFrame, date: pd.Timestamp) -> bool`
  - `check_exit_signal(df: pd.DataFrame, date: pd.Timestamp, entry_price: float, stop_price: float) -> Tuple[bool, str]`
  - `extract_sepa_criteria(df: pd.DataFrame, date: pd.Timestamp) -> Dict[str, int]`
  - `generate_signals(df: pd.DataFrame, date: pd.Timestamp) -> Dict`
  - `calculate_trade_plan(df: pd.DataFrame, date: pd.Timestamp) -> Optional[Dict]`
  - `batch_scan_universe(enriched_data_dict: Dict[str, pd.DataFrame], scan_date: Optional[pd.Timestamp]) -> Dict`
  - `score_signal_ml(df: pd.DataFrame, date: pd.Timestamp) -> float`

### `temporal_validator`

**class TemporalValidator**
  - `validate_no_future_leakage(df: pd.DataFrame, entry_date: pd.Timestamp) -> bool`
  - `get_feature_data_for_entry(df: pd.DataFrame, entry_date: pd.Timestamp) -> pd.DataFrame`
  - `perturbation_test(calculate_features_fn, ticker: str, entry_date: pd.Timestamp, feature_name: str, spike_magnitude: float, price_data: Optional[pd.DataFrame]) -> bool`
  - `manual_audit(df: pd.DataFrame, ticker: str, entry_date: pd.Timestamp, feature_values: Dict[str, float], expected_values: Dict[str, float], tolerance: float) -> bool`
  - `get_validation_summary() -> str`

### `ticker_filter`

**class TickerFilter**
  - `load_profiles()`
  - `is_fund_or_trust(ticker: str) -> bool`
  - `is_asset_management_fund(ticker: str) -> bool`
  - `filter_stocks_only(tickers: List[str], exclude_funds: bool, exclude_reits: bool, verbose: bool) -> List[str]`
  - `get_excluded_tickers(tickers: List[str], exclude_funds: bool, exclude_reits: bool) -> dict`
- `filter_stocks_only(tickers: List[str], verbose: bool) -> List[str]`

### `trade_simulator`

**class TradeSimulator**
  - `run_simulation(show_progress) -> pd.DataFrame`
  - `get_dataset_b() -> pd.DataFrame`
  - `get_summary_statistics() -> dict`

### `trade_simulator_fast`

**class FastTradeSimulator**
  - `run_simulation(show_progress, n_jobs) -> pd.DataFrame`

### `train_model`

**class PrecisionAtK**
  - `xgb_metric(y_pred: np.ndarray, dtrain: xgb.DMatrix) -> Tuple[str, float]`
**class SEPAModelTrainer**
  - `calculate_pos_weight(y: pd.Series) -> float`
  - `train_baseline(X_train: pd.DataFrame, y_train: pd.Series, X_val: Optional[pd.DataFrame], y_val: Optional[pd.Series], params: Optional[Dict]) -> xgb.Booster`
  - `optimize_hyperparameters(X_train: pd.DataFrame, y_train: pd.Series, X_val: pd.DataFrame, y_val: pd.Series, n_trials: int, timeout: Optional[int]) -> Dict`
  - `train_with_best_params(X_train: pd.DataFrame, y_train: pd.Series, X_val: Optional[pd.DataFrame], y_val: Optional[pd.Series]) -> xgb.Booster`
  - `predict_proba(X: pd.DataFrame) -> np.ndarray`
  - `predict(X: pd.DataFrame, threshold: float) -> np.ndarray`
  - `save_model(output_dir: str, fold_id: Optional[int])`
  - `load_model(model_path: str, meta_path: Optional[str])`
- `train_walk_forward_models(folds: List[Dict], df: pd.DataFrame, splitter: object, selector: object, optimize_hyperparams: bool, n_trials: int, output_dir: str) -> Dict`

### `triple_barrier_labeler`

**class TripleBarrierLabeler**
  - `apply_static_barriers(trade_df: pd.DataFrame, params: StaticBarrierParams) -> Tuple[OutcomeType, int, float]`
  - `apply_dynamic_barriers(trade_df: pd.DataFrame, params: DynamicBarrierParams) -> Tuple[OutcomeType, int, float]`
  - `apply_hybrid_barriers(trade_df: pd.DataFrame, params: HybridBarrierParams) -> Tuple[OutcomeType, int, float, dict]`
  - `apply_hybrid_barriers_vectorized(trade_df: pd.DataFrame, params: HybridBarrierParams) -> Tuple[OutcomeType, int, float, dict]`
  - `label_dataset(d2_rehydrated: pd.DataFrame, params: BarrierParams, binary_labels: bool, n_jobs: int, use_vectorized: bool) -> pd.DataFrame`
- `compute_expectancy(outcomes: pd.DataFrame) -> dict`

### `universe_engine`

**class UniverseEngine**
  - `universe() -> pd.DataFrame`
  - `profiles() -> pd.DataFrame`
  - `build_universe(start_date: str, end_date: str, max_workers: int, batch_size: int) -> Dict[str, int]`
  - `append_daily(new_data: Dict[str, pd.DataFrame]) -> None`
  - `get_snapshot(query_date: date) -> pd.DataFrame`
  - `get_cross_sectional_features(query_date: date, tickers: List[str]) -> pd.DataFrame`
  - `get_date_range(ticker: str, start: date, end: date) -> pd.DataFrame`
  - `get_universe_stats() -> Dict`

### `utils`

- `get_latest_trading_day() -> pd.Timestamp`
- `load_etf_exclusion_list(filepath: str) -> Set[str]`
- `filter_etfs(tickers: List[str], etf_list_path: str, filter_spacs: bool) -> List[str]`

### `vectorized_screening`

**class VectorizedSEPAScreener**
  - `screen_single_ticker_split(df: pd.DataFrame) -> Tuple[pd.Series, pd.Series]`
  - `screen_single_ticker_trend_only(df: pd.DataFrame) -> pd.Series`
  - `screen_single_ticker(df: pd.DataFrame) -> pd.Series`
  - `screen_at_date(df: pd.DataFrame, date: pd.Timestamp) -> bool`
  - `batch_screen_universe(enriched_data: Dict[str, pd.DataFrame], scan_date: pd.Timestamp) -> Tuple[List[str], List[str], List[str]]`
  - `find_entry_signals(df: pd.DataFrame, start_date: Optional[pd.Timestamp], end_date: Optional[pd.Timestamp]) -> pd.DatetimeIndex`
  - `find_exit_signals(df: pd.DataFrame, entry_date: pd.Timestamp, end_date: Optional[pd.Timestamp]) -> Optional[pd.Timestamp]`
  - `build_2d_matrix(ticker_data: Dict[str, pd.DataFrame], start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame`
  - `add_sepa_status_column(df_matrix: pd.DataFrame) -> pd.DataFrame`
  - `find_signal_transitions(df_matrix: pd.DataFrame, date_range_start: pd.Timestamp, date_range_end: pd.Timestamp) -> Tuple[pd.DataFrame, pd.DataFrame]`

### `viz_library`

- `create_mae_mfe_scatter(data: List[Dict]) -> go.Figure`
- `create_e_ratio_histogram(data: List[float], benchmark: float) -> go.Figure`
- `create_time_to_peak_histogram(data: List[int]) -> go.Figure`
- `create_decile_bar_chart(decile_data: List[Dict]) -> go.Figure`
- `create_actual_vs_predicted_scatter(predictions: List[Dict], max_points: int) -> go.Figure`
- `create_feature_importance_waterfall(importance_df: pd.DataFrame, top_n: int) -> go.Figure`
- `create_residual_plot(predictions: List[Dict]) -> go.Figure`
- `create_confusion_matrix(cm_data: Dict) -> go.Figure`
- `create_roc_curve(roc_data: List[Dict], auc: float) -> go.Figure`
- `create_precision_recall_curve(pr_data: List[Dict]) -> go.Figure`
- `create_calibration_plot(calibration_data: List[Dict]) -> go.Figure`
- `create_barrier_outcome_by_decile(outcome_data: List[Dict]) -> go.Figure`
- `create_complementarity_scatter(dual_data: List[Dict], max_points: int) -> go.Figure`
- `create_equity_curve(equity_data: List[Dict]) -> go.Figure`
- `create_monthly_returns_heatmap(monthly_data: List[Dict]) -> go.Figure`
- `create_trade_distribution_histogram(trade_returns: List[float]) -> go.Figure`
- `create_backtest_equity_curve(equity_df: pd.DataFrame) -> go.Figure`
- `create_backtest_drawdown(equity_df: pd.DataFrame) -> go.Figure`
- `create_backtest_monthly_heatmap(monthly_data: List[Dict]) -> go.Figure`
- `create_backtest_trade_histogram(trade_returns: List[float]) -> go.Figure`
- `create_backtest_regime_bars(regime_data: List[Dict]) -> go.Figure`
- `create_backtest_exit_pie(exit_reasons: Dict[str, int]) -> go.Figure`
- `create_backtest_holding_days_histogram(holding_days: List[int]) -> go.Figure`
- `create_backtest_cash_overlay(equity_df: pd.DataFrame) -> go.Figure`

## 6. Maintenance Log

**Last Updated:** 2026-02-09
