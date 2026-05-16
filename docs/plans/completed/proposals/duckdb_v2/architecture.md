Updated Complete Architecture

|--------------------------------------------------------------------------|
| TIER 1: t1_price (Eager, ALL tickers, ALL history via yfinance)          |
| TIER 1: t1_company_profile (Eager, ALL tickers)                          |
| TIER 1: t1_fundamentals (Eager, ALL tickers, quarterly)                  |
|--------------------------------------------------------------------------|
| SCREENER: t2_screener_members (retroactive filter)                       |
| -> Tracks historical screener pass/fail status                           |
|--------------------------------------------------------------------------|
| TIER 2: t2_screener_features (Eager, ALL history,                        |
|         lightweight technical features)                                  |
|--------------------------------------------------------------------------|
| TIER 3: t3_sepa_features (SEPA-qualified,                                |
|         heavy ML feature set, persistent, lazy-appended)                 |
|--------------------------------------------------------------------------|
| VIEWS (derived, not stored):                                             |
|                                                                          |
| ┌─ v_d1_trades ———————— trade_id GAP generation & entry/exit summary     |
| ├─ v_d2_hydrated —————— daily detail + MAE/MFE/SL                        |
| ├─ v_d2_training —————— ML training dataset (features @ entry)           |
| ├─ v_d3_deployment ———— current-day ML inference feed                    |
| └─ dashboard_view ————— enriched for visualization                       |
|--------------------------------------------------------------------------|
| MODELS:                                                                  |
| ├─ M01 (entry quality scorer) — trained on v_d2_training                 |
| ├─ M03 (regime classifier) — trained on market-level                     |
| └─ Refresh: daily scoring into buy_list                                  |
|--------------------------------------------------------------------------|
| DAILY PIPELINE:                                                          |
|                                                                          |
| 1. Append today's price data (t1_price) via yfinance                     |
| 2. Run screener -> update t2_screener_members                            |
| 3. Compute base features -> update t2_screener_features                  |
| 4. Filter for NEW SEPA breakouts -> Compute Alphas -> APPEND to Tier 3   |
| 5. Score v_d3_deployment with M01/M03                                    |
| 6. Output to buy_list & Refresh dashboard                                |
|--------------------------------------------------------------------------|