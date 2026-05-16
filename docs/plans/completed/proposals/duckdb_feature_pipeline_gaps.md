# DuckDB Feature Pipeline Gaps
**Date:** 2026-02-18
**Discovered during:** Notebook EDA (`quantamental_workflow.ipynb`)
**Status:** In Progress (Issue 1 & 4 & 2b Resolved)

---

## Summary

Four structural gaps were identified between the intended ML feature pipeline and what is actually
available in the DuckDB views (`v_d1_candidates`, `v_d2_features`, `v_d2r_hydrated`, `v_d2_training`).
These gaps result in 49 of 73 M01 features being unavailable at training time, an incorrect `rs_rating`
column in the live database, and no access to trade-simulator exit data from DuckDB.

---

## Issue 1: `rs_rating` Is Not a Percentile — Phase C UPDATE Not Applied

**Status: RESOLVED (2026-02-18) — Fixed in Phase C re-run.**

### Symptom
`rs_rating` in `daily_features` has a range of −0.99 to 1,291,600 with a median of ~0.056.
Mark Minervini's RS Rating criterion (RS ≥ 70) is meaningless against this column.

### Root Cause
Phase A SQL (line 157, `feature_pipeline.py`) computes `rs_rating` as raw weighted momentum:
```sql
0.4 * mom_63d + 0.2 * mom_126d + 0.2 * mom_189d + 0.2 * mom_252d AS rs_rating
```
Phase A then aliases it: `rs_rating AS rs` — so `rs` and `rs_rating` are identical raw floats.

Phase C (line 619) contains the correct fix:
```python
rs_rating = CAST(ROUND(r.rs_universe_rank * 98) + 1 AS INT),
```
This maps `PERCENT_RANK()` (0.0–1.0) to an IBD-style 1–99 integer. However, the current
database was populated before this fix was added (or Phase C failed silently due to a type
mismatch — the column is `DOUBLE` from Phase A, and Phase C writes `INT`).

`RS_Universe_Rank` is correctly computed (0.0–1.0, uniform distribution) and is the valid
proxy in the meantime: `RS_Universe_Rank * 99`.

### Expected Behaviour
| Metric | Expected | Actual |
|--------|----------|--------|
| `rs_rating` range | 1–99 integer | −0.99 to 1,291,600 float |
| `rs_rating` for NVDA | ~75–85 | ~0.58 (= raw momentum) |
| RS ≥ 70 filter | ~30% of universe | Meaningless |

### Fix
Re-run `FeaturePipeline` (Phase C only is sufficient). Verify that the Phase C UPDATE
actually overwrites the column — if the DOUBLE/INT type conflict silently no-ops, add an
explicit `ALTER TABLE daily_features ALTER COLUMN rs_rating TYPE INTEGER` before Phase C runs.

### Workaround (notebook)
```python
df['rs_rating_99'] = df['RS_Universe_Rank'] * 99
```

---

## Issue 2: 49/73 M01 Features Missing from `v_d2_training`

### Symptom
```
M01 features defined: 73
Available in v_d2_training: 24
Missing: 49
```

### Root Cause Breakdown

#### 2a. `log_*` transforms (~30 features)
`log_close`, `log_alpha001`, `log_Price_vs_SMA_50`, etc. are computed at **query/training time**
by `FeaturePreprocessor` and never persisted to `daily_features` or the views. The raw source
columns exist; only the `log()` wrapper is absent from the views.

#### 2b. M03 regime features (~7 features)
**Status: RESOLVED (2026-02-18)** — `compute_m03_features()` and `compute_m03_derived()` added to `FeaturePipeline`. All 7 features now in `daily_features`.

`m03_score`, `m03_pillar_trend`, `m03_pillar_risk_appetite`, `m03_delta_*` etc. are outputs
of the M03 market regime model. These scores are not written to `daily_features` — they only
live in memory during an M03 run. Until M03 scores are persisted, these features cannot be
used in any view-based training pipeline.

#### 2c. Phase A gaps (~8 features)
The following are referenced in `M01_FEATURES` but not computed in Phase A SQL:
- `RSI_14` — computed but stored as `rsi_14` (case mismatch)
- `VCP_Ratio` — computed in Phase A but may be aliased differently
- `Price_vs_SMA_150_Delta`, `Price_vs_SMA_50_Delta` — delta variants not in Phase A
- `Dist_From_20D_High_Delta`, `Dist_From_52W_High_Delta` — delta variants not in Phase A
- `Is_Green_Day` — boolean flag not computed in Phase A

#### 2d. Missing joins in views (~4 features)
- `sector_id`, `industry_id` — need join to `company_profiles`; `sector_1`/`industry_1` exist
  as strings in `v_d2_features` but the integer-encoded `_id` variants do not
- `pe_ratio`, `ps_ratio`, `peg_adjusted` — not in `fundamental_features` table

### Impact
Only 24 features available for M01 training, severely limiting model quality. The current
`v_d2_training` is effectively a skeleton view.

### Fix (prioritised)

| Priority | Fix | Effort |
|----------|-----|--------|
| High | Add `log_*` transform expressions directly to `v_d2_training` view definition | Low |
| High | Add `sector_id`/`industry_id` integer encoding to `v_d2_training` | Low |
| Medium | Persist M03 scores to `daily_features` (new column group, written after M03 run) | Medium |
| Medium | Add missing Phase A delta/flag features to `feature_pipeline.py` | Medium |
| Low | Source `pe_ratio`, `ps_ratio`, `peg_adjusted` from fundamentals or derive | High |

### Workaround (notebook)
Compute `log_*` transforms inline:
```python
for col in LOG_COLS:
    if col in df.columns:
        df[f'log_{col}'] = np.sign(df[col]) * np.log1p(np.abs(df[col]))
```

---

## Issue 3: `return_pct` (Trade-Sim Exit) Not in DuckDB

### Symptom
```sql
-- Fails:
SELECT * FROM v_d2_training WHERE return_pct IS NOT NULL
-- BinderException: Referenced column "return_pct" not found
```

### Root Cause
`return_pct` is the actual realized return computed by `FastTradeSimulator` using SEPA exit
logic (trailing stops, SMA violations, time stops). This value lives only in `d1.parquet`
(written by `DataPipeline.scan()`). It is never written to DuckDB.

`v_d2_training` exposes `return_120d` (raw 120-day price return from entry) as the closest
proxy, but this is a fixed-horizon return with no exit signal — it does not account for stops
or the actual holding period.

### Impact
- The ablation study (M01_A target) uses `return_pct` for both training and evaluation. This
  is broken in the DuckDB-native path.
- `return_120d` is a noisy proxy: a trade stopped out on day 5 at −8% shows the same exit as
  one held 120 days to +25%.
- MFE/MAE in `v_d2_training` are also computed over the fixed 120-day window, inflating MFE
  for early losers.

### Fix
Write D1 trade-simulator results to a `d1_trades` table in DuckDB:
```sql
CREATE TABLE d1_trades (
    trade_id     VARCHAR,
    ticker       VARCHAR,
    entry_date   DATE,
    exit_date    DATE,
    return_pct   DOUBLE,
    days_held    INTEGER,
    exit_reason  VARCHAR
);
```
Then `v_d2r_hydrated` can join against `d1_trades` to cap hydration at `exit_date`, and
`v_d2_training` can expose the real `return_pct` and correct MFE/MAE over the actual holding
period.

### Workaround (notebook)
Use `return_120d` as the baseline target and acknowledge it is a fixed-horizon proxy:
```python
target = 'return_120d'  # proxy for return_pct; no exit signal
```

---

## Issue 4: `v_d2r_hydrated` Is Fixed 120-Day Window, Not Entry→Exit

**Status: RESOLVED (2026-02-18) — via SEPA-bounded exit, not backtester exits.**

### Original Symptom
`v_d2r_hydrated` hydrated all trades with a hard-coded 120-day forward window, so MFE/MAE
reflected 120-day max/min regardless of when the trade actually ended.

### Resolution
The view was redesigned to use the SEPA template break (first date where any C1-C9 condition
fails) as the exit concept. A 120-day cap is retained only as a data-availability fallback for
recent signals still in Stage 2 at the dataset edge (~1.2% of trades).

**The original fix proposal (using backtester stop-loss exits from `d1_trades`) was incorrect
in its framing.** M01 predicts Stage 2 uptrend quality, so the relevant holding window is
"while in Stage 2," not "while in a simulated trade with ATR stops." Backtester exits are
portfolio-constraint artifacts (position sizing, regime filters) that are orthogonal to the
signal quality question.

### Current schema
`v_d2r_hydrated`: `trade_id, ticker, entry_date, sepa_exit_date, date, days_in_trade, open, high, low, close, volume`
`v_d2_training`: `..., mae_pct, mfe_pct, return_at_exit, sepa_exit_date, holding_days, days_observed`

### Verified stats (2026-02-18, 2.6M-row DB)
- 1,460 trades / 38,157 bars
- Median holding: 24 days, avg 36.8 days
- 120-day fallback: 18 trades (1.2%) — all are recent signals still in Stage 2

---

## Proposed Fix Order

```
1. ✅ DONE: Re-run FeaturePipeline (Phase C) → fixes rs_rating [1 day]
2. Add log_* + sector_id to v_d2_training view → fixes 30+ missing features [0.5 days]
3. ~~Write d1_trades to DuckDB~~ — not needed; Issue 4 resolved via SEPA-bounded exit
4. ✅ DONE: v_d2r_hydrated uses SEPA exit (C1-C9 break) → MFE/MAE now accurate
5. ✅ DONE: Persist M03 scores to daily_features → unlocks regime features [M03 sprint]
```

---

## Related Files

| File | Relevance |
|------|-----------|
| `src/feature_pipeline.py` | Phase A (rs_rating raw), Phase C (rs_rating fix, line 619) |
| `src/pipeline/data_pipeline.py` | `scan()` writes parquet only — needs DuckDB write |
| `src/feature_config.py` | `M01_FEATURES` list (73 features) |
| `scripts/run_m01_ablation_study.py` | Uses `return_pct` — broken in DuckDB path |
| `data/market_data.duckdb` | Views: `v_d2_training`, `v_d2r_hydrated` |
