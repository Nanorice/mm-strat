# Data Flow — Legend

Maps each node in [`data_flow.mmd`](data_flow.mmd) to the Python module that produces or consumes it.

## Phases

| Node | Implementation |
|------|----------------|
| Phase 1.1 — Price | `src/data_engine.py` · `DataRepository` |
| Phase 1.2 — Fundamentals + Earnings | `src/fundamental_engine.py` · `FundamentalEngine` |
| Phase 1.3 — Shares | `src/shares_engine.py` · `SharesEngine` |
| Phase 1.4 — Macro | `src/macro_engine.py` · `MacroEngine` |
| Phase 2 — Screener Membership | `src/managers/screener_manager.py` · `ScreenerManager` |
| Phase 3 — T2 Features | `src/feature_pipeline.py` · `FeaturePipeline.compute_t2_screener_features()` |
| Phase 4 — Regime + 5F Risk | `src/regime_pipeline.py` · `RegimePipeline`<br>`src/pipeline/risk_5_factor.py` · `RiskFiveFactorCalculator` |
| Phase 4b — SEPA Watchlist | `src/managers/sepa_watchlist_manager.py` · `SepaWatchlistManager` |
| Phase 5 — T3 SEPA Features | `src/feature_pipeline.py` · `FeaturePipeline.compute_t3_features()` |
| Phase 1.5 — Price Quality Gate | `src/orchestrators/daily_pipeline_orchestrator.py` · `_run_phase_1_5_quality_gate()` |
| Phase 6 — Views | `src/managers/view_manager.py` · `ViewManager.create_all()` |
| Phase 7 — Cache Refresh | `src/managers/view_manager.py` · `ViewManager.refresh_cache()` |
| Phase 1.6 — Plausibility Gate | `src/orchestrators/daily_pipeline_orchestrator.py` · `_run_phase_1_6_plausibility_gate()` (red gate withholds the 7.6 publish) |
| Phase 7.4 — Prod-Model Scoring | `src/evaluation/score_engine.py` · `ScoreEngine`<br>`src/evaluation/prediction_logger.py` · `log_daily_predictions()`<br>shadow pass: `src/evaluation/shadow_compare.py` |
| Phase 7.45 — Weather Gauge | `src/weather_engine.py` · `WeatherEngine.refresh()` |
| Phase 7.46 — Sector Breadth | `src/sector_breadth_engine.py` · `SectorBreadthEngine.refresh()` |
| Phase 7.47 — Portfolio NAV | `src/managers/portfolio_manager.py` · `PortfolioManager.snapshot_nav()` |
| Phase 7.5 — Slim DB Build | `scripts/build_dashboard_db.py` |
| Phase 7.6 — R2 Sync | `src/orchestrators/daily_pipeline_orchestrator.py` · `_run_phase_7_6_r2_sync()` |
| Phase 8 — Monitoring | `src/orchestrators/daily_pipeline_orchestrator.py` |
| Phase 10 — Model-Card Rebuild | `src/evaluation/model_card/builder.py` (advisory; WARN-only) |
| Model Training | `scripts/train_mfe_classifier.py`<br>`src/model_registry.py` · `ModelRegistry` |
| Backtest Runner | `src/backtest/runner.py` · `SEPABacktestRunner` |

## Tables

| Table | Phase | Notes |
|-------|-------|-------|
| `price_data` | 1.1 | OHLCV (equity only; SPY/QQQ in `t1_macro`) |
| `fundamentals` | 1.2 | IS / BS / CF quarterly |
| `earnings_calendar` | 1.2 | Past/future earnings dates — gates fundamentals refresh |
| `shares_history` | 1.3 | Historical shares outstanding |
| `macro_data` | 1.4 | FRED indicators + VIX (read by 5F risk) |
| `t1_macro` | 1.4 | SPY/QQQ/VIX OHLCV (read by Phase 3 SPY benchmark + Phase 4 regime) |
| `screener_membership` | 2 | Append-only event log |
| `t2_screener_features` | 3 | ~9.9M rows; full investable universe |
| `t2_regime_scores` | 4 | M03 score + pillars |
| `t2_risk_scores` | 4 | 5-Factor exposure target + z-scores |
| `sepa_watchlist` | 4b | T3 universe gate; one row per SEPA session |
| `t3_sepa_features` | 5 | ~9.4M rows; single ML source of truth |
| `screener_watchlist` | 6 | **VIEW** over `sepa_watchlist` since 2026-07-18 (company info + realized returns); materialised into the slim DB by 7.5 |
| `d2_training_cache` | 7 | Materialised `v_d2_training` |
| `shadow_divergence` | 7.4 | prod-vs-shadow ranking-diff verdicts |
| `weather_gauge` / `sector_breadth` / `nav_history` | 7.45–7.47 | nightly materializers, ship in the slim DB |
| `models` | ML | Registry; written by `ModelRegistry.register()` |
| `daily_predictions` | 7.4 | RAW-softprob prod-model scores per trading day; both cohorts (breakout + pre-breakout) |
| `dashboard.duckdb` | 7.5 | Slim serving DB (subset of tables); copied to R2 for Streamlit Cloud |

## Dashboard pages

> Two-tier nav since 2026-07-18 (sprint-14 switch-over); the "Today" monolith is retired.

| Tier | Page | Script |
|------|------|--------|
| Decide | Macro *(default landing)* | `scripts/pages/2_Macro.py` |
| Decide | Screening | `scripts/pages/3_Screening.py` |
| Decide | Session activity | `scripts/pages/5_Session_Activity.py` |
| Decide | Portfolio | `scripts/pages/4_Portfolio.py` |
| Decide | Supply chain | `scripts/pages/6_Supply_Chain.py` |
| Decide | Equity research | `scripts/pages/7_Equity_Research.py` |
| Workshop | Dataset EDA | `scripts/pages/1_Dataset_EDA.py` |
| Workshop | Model Lab | `scripts/pages/3_Model_Lab.py` |
| Workshop | Backtest Studio | `scripts/pages/4_Backtest_Studio.py` |
| Workshop | Pipeline Health | `scripts/pages/5_Pipeline_Health.py` |
| — | *entrypoint / nav wiring* | `scripts/dashboard.py` |
