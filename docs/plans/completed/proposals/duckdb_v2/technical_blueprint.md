# DuckDB V2 Infrastructure: Technical Blueprint

## 1. Core Architecture Principles
1. **Separation of Tiers:** Raw data (Tier 1), Screener indicators (Tier 2), and Heavy ML targets (Tier 3) represent different compute costs and are stored independently.
2. **Eager Base, Lazy ML:** Tier 1 and Tier 2 compute eagerly across the full market history. Tier 3 (the heavy Python/XGBoost ML features) computes lazily *only* on breakout days.
3. **Immutability of Trade History:** Once a trade is materialized into Tier 3 with its ML features, its inputs do not change.
4. **Resilient Session IDs:** Trade IDs are determined strictly by date-gaps on consecutive qualified trading days, rather than boolean toggles.

---

## 2. Table Schemas (Physical Storage)

### 2.1 Tier 1: `t1_price` (Raw OHLCV)
* **Description:** Daily eager ingest of full US market history.
* **Source:** `yfinance`
* **Schema:**
  * `ticker` (VARCHAR, PK)
  * `date` (DATE, PK)
  * `open`, `high`, `low`, `close`, `adj_close` (DOUBLE)
  * `volume` (UBIGINT)

### 2.2 Tier 1: `t1_fundamentals` (Company Fundamentals)
* **Description:** Quarterly fundamental data (P/E, P/S, revenue, etc.) from yfinance.
* **Source:** `yfinance`, FMP (validation)
* **Schema:**
  * `ticker` (VARCHAR, PK)
  * `date` (DATE, PK)
  * `pe_ratio`, `ps_ratio`, `pb_ratio`, `peg_ratio` (DOUBLE)
  * `market_cap`, `revenue`, `net_income` (DOUBLE)
  * `updated_at` (TIMESTAMP)

### 2.3 Tier 1: `t1_shares_outstanding` (Share Count)
* **Description:** Historical shares outstanding for market cap calculations.
* **Source:** `yfinance`
* **Schema:**
  * `ticker` (VARCHAR, PK)
  * `date` (DATE, PK)
  * `shares_outstanding` (BIGINT)

### 2.4 Tier 1: `t1_macro` (Market-Wide Data)
* **Description:** Daily market-level data for M03 regime detection.
* **Source:** `yfinance`
* **Schema:**
  * `date` (DATE, PK)
  * `spy_close`, `spy_volume` (DOUBLE, UBIGINT)
  * `qqq_close`, `qqq_volume` (DOUBLE, UBIGINT)
  * `vix_close` (DOUBLE)
  * `advance_decline_ratio`, `new_high_low_ratio` (DOUBLE)

### 2.5 Tier 2: `t2_screener_features` (Lightweight Indicators)
* **Description:** Eagerly computed technical features required by the SEPA screener. Recomputed daily from `t1_price`.
* **Scope:** Full Universe (~8,000 tickers, all history). Enables historical consistency and captures emerging stocks.
* **Schema:**
  * `ticker`, `date` (PK)
  * `sma_50`, `sma_150`, `sma_200` (DOUBLE)
  * `high_52w`, `low_52w` (DOUBLE)
  * `atr_20d`, `vol_avg_20` (DOUBLE)
  * `rs_rating` (DOUBLE)
  * `distance_from_52w_high`, `distance_from_52w_low` (DOUBLE)
  * `distance_from_20d_high`, `distance_from_20d_low` (DOUBLE)
  * ... [~30 lightweight technical features total]

### 2.6 Tier 2: `t2_regime_scores` (M03 Model Outputs)
* **Description:** Daily market regime classification from M03 model. Replaces `data/regime_scores.parquet`.
* **Source:** Computed from `t1_macro` via M03 model
* **Schema:**
  * `date` (DATE, PK)
  * `m03_score` (DOUBLE)
  * `m03_pillar_trend`, `m03_pillar_liq`, `m03_pillar_risk` (DOUBLE)
  * `model_version` (VARCHAR DEFAULT 'v1.0')

### 2.7 Tier 3: `t3_sepa_features` (Persistent ML Features)
* **Description:** **The single most important table for ML.** Hard-materialized point-in-time snapshot of 100+ heavy Alpha and M03 Regime features *only* for the specific dates a ticker satisfied the SEPA Trend Template.
* **Scope:** Expanding append-only table (INSERT only, never UPDATE/DELETE).
* **Schema:**
  * `ticker` (VARCHAR, PK)
  * `date` (DATE, PK)
  * `feature_version` (VARCHAR DEFAULT 'v3.0', PK) — Enables reproducibility when feature definitions change
  * ... [All 79 Base SQL Features from Phase A: SMAs, RS line, ATR, distances, returns, momentum, RSI, velocity, flags]
  * ... [All 16 Python Alpha Features from Phase B: alpha001, alpha002, ..., alpha101]
  * ... [All 7 Cross-Sectional Rank Features from Phase C: RS_Universe_Rank, RS_Sector_Rank, etc.]
  * `fundamental_pe`, `fundamental_ps`, `fundamental_pb` (Point-in-time fundamental snapshot from `t1_fundamentals`)
  * `ingested_at` (TIMESTAMP DEFAULT CURRENT_TIMESTAMP) — Audit trail for debugging
* **Indexes:**
  * `CREATE INDEX idx_t3_ticker_date ON t3_sepa_features(ticker, date);`
  * `CREATE INDEX idx_t3_feature_version ON t3_sepa_features(feature_version);`
* **Total Columns:** 102 (79 SQL + 16 Python + 7 Ranks)

### 2.8 Supporting Tables (Infrastructure)

#### `models` (Model Registry)
* **Description:** MLOps metadata and versioning for M01/M02/M03 models.
* **Schema:**
  * `version_id` (VARCHAR, PK) — e.g., 'M01_v2.3.1', 'M02_ignition_v1.0'
  * `status_flag` (VARCHAR) — 'prod', 'test', 'archived'
  * `specs_json` (JSON) — Model hyperparameters, feature list
  * `feature_version` (VARCHAR) — Links to `t3_sepa_features.feature_version`
  * `training_date` (DATE)
  * `dataset_rows` (BIGINT)
  * `rmse`, `mae`, `r2`, `spearman_corr` (DOUBLE) — Performance metrics
  * `artifacts_path` (VARCHAR) — Path to saved model file
  * `created_at`, `updated_at` (TIMESTAMP)

#### `buy_list` (Daily Scored Candidates)
* **Description:** Output of M01/M02/M03 scoring pipeline. Candidates ranked by expected return.
* **Schema:**
  * `ticker` (VARCHAR, PK)
  * `signal_date`, `signal_price`, `current_price` (DATE, DOUBLE)
  * `entry_price`, `stop_price`, `target_price` (DOUBLE)
  * `m01_expected_return`, `m01_rank` (DOUBLE, INTEGER)
  * `m02_loser_proba`, `m02_survival` (DOUBLE) — Ignition classifier outputs
  * `m03_regime_score`, `m03_regime_category` (DOUBLE, VARCHAR)
  * `final_score`, `final_score_rank` (DOUBLE, INTEGER)
  * `status` (VARCHAR) — 'active', 'exited', 'stopped'
  * ... [~50 total columns including lagged features for analysis]

#### `buy_list_activity` (Trade Audit Log)
* **Description:** Historical record of adds/removes from buy_list.
* **Schema:**
  * `id` (INTEGER, PK)
  * `ticker`, `action`, `action_date` (VARCHAR, VARCHAR, DATE)
  * `reason` (VARCHAR) — e.g., 'stop_hit', 'manual_exit', 'new_entry'
  * `entry_price`, `stop_price`, `target_price` (DOUBLE)
  * `created_at` (TIMESTAMP)

#### `master_ticker_registry` (Universe Management)
* **Description:** Central registry of all known tickers, IPO dates, delistings.
* **Schema:**
  * `ticker` (VARCHAR, PK)
  * `name`, `exchange`, `ticker_type` (VARCHAR) — e.g., 'common_stock', 'etf'
  * `ipo_date`, `delist_date` (DATE)
  * `is_active` (BOOLEAN)
  * `source` (VARCHAR) — e.g., 'yfinance', 'manual'
  * `discovered_at` (TIMESTAMP)

#### `universe_snapshots` (Historical Screener Membership)
* **Description:** Monthly snapshots of which tickers passed screener filters.
* **Schema:**
  * `month_date` (DATE)
  * `ticker` (VARCHAR)
  * `close`, `volume_avg_20`, `market_cap_approx` (DOUBLE)
  * `meets_price_filter`, `meets_volume_filter`, `meets_mktcap_filter` (BOOLEAN)
  * `in_universe` (BOOLEAN)

#### `price_data_backfill` & `shares_backfill` (Backfill Staging)
* **Description:** Temporary staging tables for historical data backfills. Used by `v_price_combined` and `v_shares_combined` views.
* **Schema:** Same as `t1_price` and `t1_shares_outstanding`
* **Note:** Can be dropped after backfill completes, or kept for audit trail.

---

## 3. Virtual Views (Derived ML Pipeline)

### 3.1 `v_d1_trades` (Gap Generation)
* **Description:** Generates `trade_id` using LAG based on elapsed valid trading days from `t1_price`. Splits continuous SEPA presence into distinct trades when 2+ day gap occurs (excluding weekends/holidays). Eliminates redundant adjacent rows to capture just entry and exit dates.
* **Source:** `t3_sepa_features`
* **Key Columns:** `ticker`, `trade_id`, `entry_date`, `exit_date`, `entry_price`, `exit_price`
* **Logic:** `trade_id = SUM(CASE WHEN days_since_last > 1 THEN 1 ELSE 0 END) OVER (PARTITION BY ticker ORDER BY date)`

### 3.2 `v_d2_hydrated` (Forward Outcome Logic)
* **Description:** Joins `v_t3_trades` back onto `t1_price` to walk forward over the lifetime of the trade to compute Stop-Loss and Peak conditions.
* **Key Columns:** `trade_id`, `mae`, `mfe`, `running_return_pct`, `sl_hit`, `sl_pct`

### 3.3 `v_d2_training` (ML Model Feeder)
* **Description:** The ultimate training dataset for the M01 Model. Joins the point-in-time ML features stored in `t3_sepa_features` at `entry_date` with the future outcomes from `v_d2_hydrated`.
* **Key Columns:** `trade_id`, `[100+ t3_features]`, `target_return`, `target_class`

### 3.4 `v_d3_deployment` (Daily Screen Feeder)
* **Description:** Pulls the last 252 days of active records from `t3_sepa_features`. Used for daily inference scoring.

---

## 4. Daily Operational Workflow (Cron Job)

1. **Ingest Prices:** `python src/pipelines/ingest_t1.py`
   * Fetch previous day's data from `yfinance` for all tickers. Append to `t1_price`.
2. **First-Pass Screen:** `python src/pipelines/run_screener.py`
   * Evaluate `t1_price` against Minervini baseline rules (Price > 15, Vol > 100k). Update `stock_screener` membership table.
3. **Compute T2:** `python src/pipelines/compute_t2.py`
   * Re-run SQL window functions over `t1_price` to update SMAs and RS Ratings. Store in `t2_screener_features`.
4. **Identify Breakouts & Compute T3:** `python src/pipelines/compute_t3.py`
   * Join `t2_screener_features` against `stock_screener`.
   * Filter for explicit SEPA criteria (`trend_ok = TRUE`).
   * Identify *novel* entries (not present yesterday).
   * **[HEAVY]** For those novel entries, calculate Python M01/M03 Pandas Alphas.
   * Append to `t3_sepa_features`.
5. **Score Candidates:** `python src/models/m01_scorer.py`
   * Read `v_d3_deployment`. Run XGBoost inference. Output to `buy_list`.
6. **Dashboard Refresh:** Update Streamlit/Grafana pointing to `buy_list`.

---

## 6. Historical Backfill Strategy

### 6.1 Initial T3 Population
**Goal:** Populate `t3_sepa_features` with historical SEPA breakout candidates from 2020-01-01 to present.

**Rationale:**
- Maximize M01 training data (5 years of historical trades)
- Estimated ~500,000 rows (avg 50 breakouts/day × 252 days × 5 years)
- One-time compute cost: ~8 hours

**Implementation:**
```python
# scripts/backfill_t3_sepa_features.py
for date in pd.date_range('2020-01-01', yesterday):
    # Step 1: Identify SEPA candidates on this date
    candidates = identify_sepa_breakouts(date)  # Query t2_screener_features

    if candidates.empty:
        continue

    # Step 2: Compute heavy features (Phase A + B + C)
    features = compute_heavy_features(
        candidates,
        date,
        feature_version='v3.0'
    )

    # Step 3: Insert (skip duplicates)
    con.execute("""
        INSERT OR IGNORE INTO t3_sepa_features
        SELECT * FROM features
    """)

    # Step 4: Checkpoint every 100 dates
    if date.day_of_year % 100 == 0:
        save_checkpoint(date)
        log_progress(f"Processed through {date}: {len(candidates)} candidates")
```

**Idempotency:**
- Use `INSERT OR IGNORE` to skip existing (ticker, date, feature_version) rows
- Checkpoint file stores last processed date → allows resume after failure
- Safe to re-run entire script (will skip already-processed dates)

**Feature Version Handling:**
- All backfilled rows use `feature_version = 'v3.0'`
- If feature logic changes in future (e.g., bug fix in alpha006):
  - Bump version to `v3.1`
  - Re-run backfill with `feature_version='v3.1'` (creates parallel dataset)
  - Old M01 models continue using `v3.0` (reproducibility)
  - New M01 models train on `v3.1`

**Validation:**
```sql
-- Check backfill completeness
SELECT
    COUNT(*) as total_rows,
    COUNT(DISTINCT ticker) as unique_tickers,
    MIN(date) as earliest_date,
    MAX(date) as latest_date,
    feature_version
FROM t3_sepa_features
GROUP BY feature_version;

-- Expected: ~500K rows, ~1500 tickers, 2020-01-01 to yesterday, feature_version='v3.0'
```

### 6.2 Rollback Procedure
**If backfill fails or produces incorrect data:**

1. **Drop bad data:**
   ```sql
   DELETE FROM t3_sepa_features WHERE feature_version = 'v3.0';
   ```

2. **Restore from checkpoint:**
   ```bash
   python scripts/backfill_t3_sepa_features.py --resume-from 2022-06-15
   ```

3. **Full rebuild (nuclear option):**
   ```sql
   DROP TABLE t3_sepa_features;
   CREATE TABLE t3_sepa_features AS SELECT * FROM t3_sepa_features_backup;
   ```

---

## 7. Error Handling & Monitoring

### 7.1 Fail-Safe Mode
**Problem:** If `yfinance` API fails (rate limit, outage), entire pipeline halts.

**Solution:** Graceful degradation with alerts.

**Implementation:**
```python
# scripts/run_daily_pipeline.py
try:
    success = ingest_t1_price()
    if not success:
        logger.error("T1 price ingestion failed")
        send_alert("yfinance API down - using yesterday's data")
        sys.exit(1)  # Halt T2/T3 updates
except Exception as e:
    logger.exception("T1 ingestion crashed")
    send_alert(f"Critical: T1 pipeline crashed: {e}")
    sys.exit(1)

# Continue with T2/T3 only if T1 succeeded
update_t2_screener()
update_t3_sepa()
```

### 7.2 Idempotency Checks
**Problem:** Accidentally running pipeline twice on same date creates duplicates.

**Solution:** Check run status before executing.

**Implementation:**
```python
# Check if already run today
last_run = con.execute("""
    SELECT MAX(run_date) FROM pipeline_runs
    WHERE status = 'success'
""").fetchone()[0]

if last_run == yesterday:
    logger.info("Pipeline already run for {yesterday}. Exiting.")
    sys.exit(0)

# Mark run start
con.execute("""
    INSERT INTO pipeline_runs (run_date, status, started_at)
    VALUES (?, 'running', CURRENT_TIMESTAMP)
""", [yesterday])
```

**Supporting Table:**
```sql
CREATE TABLE pipeline_runs (
    run_date DATE PRIMARY KEY,
    status VARCHAR CHECK (status IN ('running', 'success', 'failed')),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT,
    t1_rows_inserted BIGINT,
    t2_rows_updated BIGINT,
    t3_rows_inserted BIGINT
);
```

### 7.3 Alert Conditions
**Trigger alerts when:**

| Condition | Severity | Action |
|-----------|----------|--------|
| T1 ingestion fails | CRITICAL | Email + Slack, halt pipeline |
| 0 SEPA breakouts for 5 consecutive days | WARNING | Slack notification (possible market regime change or bug) |
| T3 row count < 10 on any day | WARNING | Investigate screener logic |
| Fundamental data variance >20% vs FMP | WARNING | Weekly validation failed, audit data source |
| Pipeline runtime >2× avg | WARNING | Performance degradation detected |
| Any step crashes with exception | CRITICAL | Email + Slack with stack trace |

**Alert Implementation:**
```python
def send_alert(message: str, severity: str = 'WARNING'):
    """Send alert via Slack webhook + email."""
    if severity == 'CRITICAL':
        send_email(to=ADMIN_EMAIL, subject=f"[CRITICAL] Pipeline Alert", body=message)

    slack_webhook.post(json={
        'text': f"[{severity}] {message}",
        'channel': '#trading-alerts'
    })
```

### 7.4 Monitoring Dashboard
**Daily health check script:**
```bash
python scripts/check_pipeline_health.py
```

**Outputs:**
- Last 30 days pipeline runs (success/failure rate)
- Data freshness (max date in each table)
- Gap detection (missing trading days)
- Avg runtime per step (detect performance degradation)

**Example Output:**
```
Pipeline Health Report (Last 30 Days)
======================================
Success Rate: 29/30 (96.7%)
Failed Runs: 2024-01-15 (yfinance timeout)

Data Freshness:
  t1_price:             2024-02-16 ✅
  t2_screener_features: 2024-02-16 ✅
  t3_sepa_features:     2024-02-16 ✅

Avg Runtime (last 7 days):
  T1 ingestion:  42s
  T2 compute:    18s
  T3 append:     7s (avg 47 breakouts/day)
  Total:         67s

Alerts:
  ⚠️  2024-02-10: 0 SEPA breakouts (market-wide pullback)
  ⚠️  2024-02-12: T3 compute took 142s (2.6× avg)
```

---

## 8. Evaluation Checklist (Definition of Done)

- [ ] **T1 Performance:** `yfinance` ingestion successfully appends 8k+ tickers daily in under 2 minutes.
- [ ] **T1 Macro Ingestion:** `t1_macro` table populated daily with SPY/QQQ/VIX data, no missing dates.
- [ ] **T2 Validation:** SMA and RS Rating calculations precisely match legacy `daily_features` output.
- [ ] **T2 Regime Scores:** `t2_regime_scores` matches values from `data/regime_scores.parquet` (validate 10 random dates).
- [ ] **Trade ID Integrity:** `v_d1_trades` properly splits a single continuous ticker presence into two distinct `trade_id`s if a 2-day non-weekend gap occurs.
- [ ] **T3 Append Idempotency:** Daily pipeline correctly avoids re-calculating Phase B Python Alphas for days that already exist in `t3_sepa_features`.
- [ ] **T3 Feature Versioning:** All rows have `feature_version = 'v3.0'` after initial backfill.
- [ ] **T3 Backfill Completeness:** ~500K rows from 2020-01-01 to present, ~1500 unique tickers.
- [ ] **Hydration Accuracy:** `v_d2_hydrated` correctly calculates the exact date a 15% stop-loss would be triggered on historical test data.
- [ ] **Training Data Zero-Leakage:** `v_d2_training` has 0.00% lookahead bias (no Phase A variables mistakenly peek ahead of the entry date).
- [ ] **View Naming:** All views follow `v_dN_*` convention (`v_d1_trades`, `v_d2_hydrated`, `v_d2_training`, `v_d3_deployment`).
- [ ] **Error Handling:** Pipeline gracefully handles yfinance API failures without corrupting data.
- [ ] **Monitoring:** `check_pipeline_health.py` runs weekly, alerts sent for failures or anomalies.
