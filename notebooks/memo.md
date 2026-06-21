current status:
1. a bit of dead-end on m01_baseline:
    a. regime failure: expanding the training set back to 2003 did not improve performance in backtest. we tested a few versions, a) model trained using 2023-2025 (last_fold) b) model trained using 2003-2025 (baseline_full) and c) model trained using 2003-2024 (baseline_full_2024), d) old version of this model (baseline), likely similar to (a). Results are logged in @model_results.md -> basically if the training window is long, even leakage does not help with performance. this suggests this is not fully telling regime apart, or the model give little weight to these features, or this model is simply not good enough (it is designed to tell if a set up is good enough to enter, judged by its potential max return before trend breaks)
2. features naming in current pipeline and bugfix:
    a. currently the features with _pct_change and _delta are basically the same, we should confirm and drop the _pct_change ones
    b. we had a feature edit in the pipeline that was not added in the right place in SQL, resulting a shift of all features. Make sure we avoid that
3. new model: m01_prototype
    a. this is supposed to have better OOS performance than baseline
    b. we added a few new features, so need to add them in the pipeline. comparison with m01_baseline below:
    Removed from Prod (33 features):
['alpha002', 'alpha101', 'atr_delta', 'breakout', 'close_above_sma200', 'consolidation_duration', 'days_since_report', 'dist_from_20d_low', 'dist_from_20d_low_delta', 'dist_from_52w_high', 'dist_from_52w_low', 'dist_from_52w_low_delta', 'dry_up_volume', 'eps_accel', 'green_days_ratio_20d', 'is_green_day', 'low_52w_delta', 'lowest_low_20d_delta', 'mom_126d', 'mom_189d', 'mom_63d', 'net_income_growth_yoy', 'price_vs_sma_150', 'price_vs_sma_150_delta', 'price_vs_sma_200', 'price_vs_sma_200_delta', 'price_vs_sma_50', 'price_vs_sma_50_delta', 'ps_ratio', 'rs_line_delta', 'rs_line_uptrend', 'rs_rating', 'rs_velocity']

Newly added (24 features):
['adr_20d', 'alpha008', 'atr_pct_chg', 'dollar_volume_avg_20', 'ema_21_50_ratio', 'ema_50_100_ratio', 'ema_8_21_ratio', 'gap_risk_ratio', 'industry', 'mom_21d_vol_adj', 'mom_slope_21_63', 'mom_slope_63_126', 'net_income', 'peg_adjusted', 'price_vs_sma_50_vol_adj', 'price_vs_spy_ma63', 'return_60d', 'revenue', 'rs_universe_rank', 'sector', 'shares_outstanding', 'sma_ratio_150_200', 'volatility_20d', 'volume_velocity_2d']

    
what we accomplished:
1. m01_prototype
2. backtest pipeline, with sweep and visualisation. Need to add micro analytics, on trade level