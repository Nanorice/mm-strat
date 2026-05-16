# Phase 3 — Feature Table Redesign
> Created: 2026-03-23 | Status: ✅ COMPLETE (2026-03-24)

## Goal

Eliminate `daily_features` (fat table, all tickers, 111 cols) and replace with a clean
two-table design that matches the actual pipeline tier logic:

```
t2_screener_features  — full screener universe (~2400 tickers), population-dependent features
t3_sepa_features      — SEPA candidates only (~50-200/day), per-ticker features + carry-forward from t2
```

`daily_features` is dropped. `t3_sepa_features` is rebuilt with a clean schema (no migration
artifacts).

---

## Confirmed Findings from Audit

### Columns EXCLUDED from models by feature_config.py

These are in `EXCLUDE_RAW_COLUMNS` or `EXCLUDE_PRICE_STRUCTURE` — stored today but never
fed to any model:

| Column | Reason excluded |
|---|---|
| `open`, `high`, `low` | Raw price (non-stationary) |
| `sma_20`, `sma_50`, `sma_150`, `sma_200` | Raw price proxy (`EXCLUDE_RAW_COLUMNS`) |
| `high_52w`, `low_52w` | Absolute price (`EXCLUDE_RAW_COLUMNS`) |
| `high_20d`, `highest_high_20d`, `lowest_low_20d` | Absolute price (`EXCLUDE_PRICE_STRUCTURE`) |
| `price_vs_spy*` (5 cols) | Explicitly in `EXCLUDE_BENCHMARK_RS` — see note below |
| `vol_avg_20`, `vol_avg_50` | Raw volume (not in any model feature list) |
| `vol_ratio_50` | Not in M01/M02 feature lists |
| `return_1d`, `return_5d`, `return_20d`, `return_60d` | Not in M01/M02 (momentum via mom_* instead) |
| `atr_14` | `atr_20d` is used; `atr_14` is not in any model list |
| `sma_200_lag20` | Used only to compute `trend_ok`; not a model input |
| `rs_line_uptrend` | In `v_sepa_candidates` view only, not a model feature |
| `*_pct_chg_1` suffix (19 cols) | Migration artifact duplicates — drop |

### Columns kept in t2 (population-dependent, need full universe)

- Cross-sectional: `RS_Universe_Rank`, `RS_Sector_Rank`, `RS_vs_Sector`, `Sector_Momentum`,
  `RS_Industry_Rank`, `RS_vs_Industry`, `Industry_Momentum`
- Alphas (16): `alpha001–alpha101`
- RS base (needed for rank computation): `rs`, `rs_ma`

### SEPA filter columns (t2 only, not needed in t3)

`trend_ok`, `breakout_ok` — used as filter gates, not model features.
Kept in t2 output. t3 rows are by definition `trend_ok=TRUE AND breakout_ok=TRUE`, so
these flags are implicit and do not need to be stored in t3.

---

## New Schema

### t2_screener_features (Phase 3) — ~2400 tickers/day

**Primary key:** `(ticker, date)`

| Group | Columns | Count |
|---|---|---|
| Keys | `ticker`, `date` | 2 |
| SEPA filter flags | `trend_ok`, `breakout_ok` | 2 |
| Trend / SMA | `sma_200_lag20`, `price_vs_sma_50`, `price_vs_sma_150`, `price_vs_sma_200`, `close_above_sma200` | 5 |
| Relative strength | `rs`, `rs_ma`, `rs_rating`, `rs_line_log`, `rs_line_delta`, `rs_line_uptrend` | 6 |
| SPY ratio | `price_vs_spy`, `price_vs_spy_ma63` | 2 |
| Volume | `vol_avg_20`, `vol_avg_50`, `vol_ratio`, `dry_up_volume` | 4 |
| Volatility | `atr_20d`, `natr`, `volatility_20d`, `vcp_ratio`, `consolidation_width` | 5 |
| 52w range | `high_52w`, `low_52w`, `dist_from_52w_high`, `dist_from_52w_low`, `pct_from_high_52w`, `pct_above_low_52w` | 6 |
| 20d range | `high_20d`, `lowest_low_20d`, `highest_high_20d`, `dist_from_20d_high`, `dist_from_20d_low` | 5 |
| Cross-sectional ranks | `RS_Universe_Rank`, `RS_Sector_Rank`, `RS_vs_Sector`, `Sector_Momentum`, `RS_Industry_Rank`, `RS_vs_Industry`, `Industry_Momentum` | 7 |
| Alphas | `alpha001`, `alpha002`, `alpha004`, `alpha006`, `alpha009`, `alpha011`, `alpha012`, `alpha013`, `alpha015`, `alpha041`, `alpha046`, `alpha049`, `alpha051`, `alpha054`, `alpha060`, `alpha101` | 16 |
| Metadata | `updated_at` | 1 |
| **Total** | | **61** |

**Computation order within Phase 3:**
1. SQL CTE — all non-rank, non-alpha columns (same as current t2 SQL, trimmed)
2. Python multiprocessing — 16 alphas (same as current Phase B, but on t2 population)
3. SQL UPDATE — `PERCENT_RANK()` cross-sectional ranks (same as current Phase C)

**Note:** `sma_200_lag20`, `high_52w`, `low_52w`, `high_20d`, `lowest_low_20d`,
`highest_high_20d` are kept in t2 because they are intermediate inputs to `trend_ok` /
`breakout_ok` computation and to `dist_*` columns used by models. They are NOT fed to
models directly (they are in `EXCLUDE_RAW_COLUMNS`).

---

### t3_sepa_features (Phase 5) — SEPA candidates only

**Primary key:** `(ticker, date, feature_version)`
**Source:** tickers where `t2_screener_features.trend_ok=TRUE AND breakout_ok=TRUE` on that date

| Group | Columns | Count |
|---|---|---|
| Keys | `ticker`, `date`, `feature_version` | 3 |
| OHLCV | `open`, `high`, `low`, `close`, `volume` | 5 |
| From t2 (carry-forward) | all 59 non-metadata t2 cols | 59 |
| Momentum | `mom_21d`, `mom_63d`, `mom_126d`, `mom_189d`, `mom_252d` | 5 |
| RSI + slope | `rsi_14`, `sma_50_slope` | 2 |
| Volume depth | `vol_ma20`, `vol_ma50`, `vol_ratio_50`, `dollar_volume_avg_20`, `turnover`, `turnover_ma20` | 6 |
| ATR | `atr_14` | 1 |
| Returns | `return_1d`, `return_5d`, `return_20d`, `return_60d` | 4 |
| Pattern | `breakout`, `is_green_day`, `green_days_ratio_20d`, `adr_20d` | 4 |
| Velocity | `rs_velocity`, `volume_acceleration`, `breakout_momentum`, `consolidation_duration`, `price_momentum_curve`, `log_volume_velocity`, `price_accel_10d`, `immediate_thrust` | 8 |
| pct_chg deltas (19, no `_1` duplicates) | `price_vs_sma_50_pct_chg`, `price_vs_sma_150_pct_chg`, `price_vs_sma_200_pct_chg`, `rs_pct_chg`, `rs_ma_pct_chg`, `dry_up_volume_pct_chg`, `natr_pct_chg`, `atr_pct_chg`, `vcp_ratio_pct_chg`, `consolidation_width_pct_chg`, `rsi_14_pct_chg`, `dist_from_52w_high_pct_chg`, `dist_from_52w_low_pct_chg`, `low_52w_pct_chg`, `high_52w_pct_chg`, `dist_from_20d_high_pct_chg`, `dist_from_20d_low_pct_chg`, `lowest_low_20d_pct_chg`, `highest_high_20d_pct_chg` | 19 |
| M03 regime | `m03_score`, `m03_pillar_trend`, `m03_pillar_liq`, `m03_pillar_risk`, `m03_delta_5d`, `m03_delta_20d`, `m03_regime_vol` | 7 |
| Metadata | `ingested_at` | 1 |
| **Total** | | **~124** |

**Note on OHLCV in t3:** kept because `v_d2_hydrated` uses `sma_50`, `atr_20d`, and the
backtest runner needs OHLCV. `open/high/low` are excluded from *models* but are needed
for backtest simulation.

**Note on `atr_14`:** currently in `EXCLUDE_RAW_COLUMNS` and not a model input, but
kept in t3 because it is an intermediate used by velocity feature formulas
(`breakout_momentum = (close - high_20d) / atr_14`). Mark as non-model column.

---

## What is Dropped

| Table / Columns | Action |
|---|---|
| `daily_features` table | **DROP** after t3 backfill is validated |
| `t3_sepa_features.*_pct_chg_1` (19 cols) | **DROP** — migration artifacts, clean schema only |
| `price_vs_spy_ma20`, `price_vs_spy_ma50`, `price_vs_spy_ma200` | **DROP** from t3 — in `EXCLUDE_BENCHMARK_RS`, unused |
| Phase 5 (daily_features rebuild) in orchestrator | **REPLACE** with t3 direct computation |
| Phase 6 (t3 lazy copy from daily_features) | **MERGE INTO** Phase 5 |

---

## Implementation Steps

### Step 1 — Migrate t2_screener_features ✅ DONE (2026-03-24)

- [x] Add 9 XS alpha cols + 7 rank cols to `t2_screener_features` DDL
- [x] Add `price_vs_spy`, `price_vs_spy_ma63`, `pct_above_low_52w` to DDL + SELECT output
- [x] `close_above_sma200` kept (decision: boolean SEPA C1 flag, semantically distinct)
- [x] `compute_alpha_features()` made table-agnostic via `target_table` + `alpha_cols` params
- [x] `compute_cross_sectional_ranks()` made table-agnostic via `target_table` param
- [x] `compute_t2_screener_features()` calls both after SQL INSERT (XS alphas then ranks)

**Alpha split introduced:**
- `ALPHA_COLS_XS` = [001,002,004,008,011,013,015,019,060] — cross-sectional, run on t2
- `ALPHA_COLS_TS` = [006,009,012,041,046,049,051,054,101] — time-series only, run on t3
- **alpha008** (5d momentum rank) and **alpha019** (250d return rank) added as new XS alphas

**Alpha correctness fixes (7 alphas corrected):**
- 001,002,011,013,015,060: outer `rank()` was per-ticker time-series; fixed to `groupby('date').rank(pct=True)`
- 004: `rank_low` was `groupby('ticker')` ts-rank; fixed to `groupby('date')` cross-sectional
- All `rank_*` intermediates now: `df.groupby('date')[col].rank(pct=True)`

**Vectorisation fixes:**
- alpha006,009,011,013,015: converted from `groupby.apply` to `transform` (vectorised)
- alpha001,004,060: still use `rolling().apply` — inherently O(N×W), unavoidable

**Checkpoint 1:** `DESCRIBE t2_screener_features` should show ~62 cols. Run for one date, verify alpha/rank values are non-null for ~2400 tickers.

---

### Step 2 — Rebuild t3_sepa_features schema ✅ DONE (2026-03-24)

- [x] `_create_t3_table()` — drops old table, creates clean schema (no `_1` artifact cols)
- [x] `compute_t3_features()` fully rewritten — no dependency on `daily_features`:
  - SQL CTEs: `candidates` (price_data × screener universe) → `per_ticker` (window features) → `with_velocity` (joins t2 for pct_chg deltas + velocity) → final SELECT (joins t2 carry-forward + t2_regime_scores M03)
  - Filter `trend_ok=TRUE AND breakout_ok=TRUE` at final join
  - After SQL insert: calls `compute_alpha_features(alpha_cols=ALPHA_COLS_TS)` for 9 TS alphas
- [x] `pct_above_low_52w` added to both t2 + t3 (was computed but not stored)

**Checkpoint 2:** Row count in t3 matches `SELECT COUNT(*) FROM t2_screener_features WHERE trend_ok AND breakout_ok` for a test date. Spot-check 3 tickers for XS alpha/rank carry-forward correctness.

---

### Step 3 — Update FeaturePipeline ✅ DONE (2026-03-24)

- [x] Deleted `compute_base_features()`, `_compute_full_rebuild()`, `_compute_incremental()`, `compute_m03_features()`, `compute_m03_derived()`
- [x] `_load_data_for_alphas` simplified — single path via `INNER JOIN {target_table}` (daily_features branch removed)
- [x] `compute_all()` rewritten: calls `compute_t2_screener_features()` → `compute_t3_features()` → `_refresh_training_cache()`
- [x] `_create_t3_table()` wired into `compute_all(recreate_t3=True)` param
- [x] TS alpha fix: `warmup_table='t2_screener_features'` param added so rolling history is loaded from t2 (continuous), not sparse t3 dates

---

### Step 4 — Update orchestrator phases ✅ DONE (2026-03-24)

- [x] Phase 5 (`_run_phase_5_t3_features`): calls `feature_pipeline.compute_t3_features(target_date)` directly
- [x] Phase 6 (old T3 lazy from daily_features): deleted
- [x] Old Phases 7/8/9 renumbered to 6/7/8
- [x] Orchestrator docstring updated to 8-phase

---

### Step 5 — Update ViewManager ✅ DONE (2026-03-24)

- [x] Stale `daily_features` reference in `MAX(date)` query fixed → `t3_sepa_features`
- [x] All views verified against new t3 schema (column names match)
- [x] `log_alpha008`, `log_alpha019` deferred — add to `v_d2_training` + `M01_FEATURES` before next retrain

---

### Step 6 — Drop daily_features ✅ DONE (2026-03-24)

- [x] XS alphas (alpha008, alpha019) added to t3; all XS alphas + ranks bulk-copied from t2 via UPDATE
- [x] Backfilled missing dates 2026-02-19 to 2026-03-23 (518 new rows)
- [x] Dropped 22 artifact/unused cols: 19 `*_pct_chg_1` duplicates + `price_vs_spy_ma20/50/200` (via CTAS rename — DuckDB ALTER dependency bug workaround)
- [x] `v_d2_training` verified: 1,733 rows, all views returning data
- [x] `DROP TABLE daily_features` executed
- [x] Deleted `scripts/migrate_to_v3_1.py`, `scripts/backfill_t3_sepa_features.py`

**Checkpoint 6 PASSED:** `daily_features` absent, t3=34,080 rows (130 cols), all views healthy.

---

## Files Changed

| File | Change |
|---|---|
| `src/feature_pipeline.py` | Major rewrite: t2 gains alphas+ranks, t3 computed directly, full rebuild deleted |
| `src/managers/view_manager.py` | Remove `*_pct_chg_1` references, verify column names |
| `src/orchestrators/daily_pipeline_orchestrator.py` | Delete Phase 6, update Phase 5 |
| `scripts/backfill_screener_membership.py` | No change |
| `scripts/backfill_t3_sepa_features.py` | Delete after Step 6 |
| `scripts/migrate_to_v3_1.py` | Delete after Step 6 |

---

## Resolved Decisions

| Question | Decision | Evidence |
|---|---|---|
| `rs_velocity` restore to M01? | **Yes — restore.** Comment in `TECHNICAL_FEATURES` is stale. Column is `(rs_rating - LAG(rs_rating, 5)) / 5.0` — momentum-based, not benchmark. `log_rs_velocity` already in `v_d2_training` (view_manager.py:619). Add `rs_velocity` to `TECHNICAL_FEATURES` and `M01_FEATURES`. | feature_pipeline.py:447, view_manager.py:619 |
| `pct_from_high_52w` — drop? | **Keep.** Used as SEPA C8 proximity filter in `data_loader_duckdb.py` (`>= -0.25`) and displayed in `v_sepa_candidates`. | data_loader_duckdb.py:163, view_manager.py:199 |
| `pct_above_low_52w` — drop? | **Keep.** Symmetric to above. Present in current t3 pipeline, negligible cost. | feature_pipeline.py:797 |
| `close_above_sma200` — drop from t2? | **Keep.** Boolean SEPA C1 flag — explicit and semantically distinct from `price_vs_sma_200 > 0`. Dropping would silently change filter readability. | feature_pipeline.py:444,702 |
| `price_vs_spy_ma20/50/200` (3 cols) | **Drop from t3.** In `EXCLUDE_BENCHMARK_RS`. Only `price_vs_spy_ma63` needed (for `trend_ok` and `rs_line_uptrend`). `price_vs_spy` kept for v_sepa_candidates. | feature_config.py:244-250 |
| `log_volume_velocity` — store or compute in view? | **Store in t3.** Referenced directly in M01_FEATURES (not as a view-layer log transform). | feature_config.py:380 |
| `atr_14` — keep? | **Keep in t3.** Denominator in `breakout_momentum = (close - high_20d) / atr_14`. Negligible storage. | feature_pipeline.py:447 |
