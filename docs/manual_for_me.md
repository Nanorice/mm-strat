# Conceptual Architecture

> Last updated: 2026-05-08 — T3 universe gate refactor (Option C). New `sepa_watchlist` event log + Phase 4b in the daily pipeline.

> Naming convention: t1 is raw data in phase 1. t2 is filtered data for investible universe, with lightweight and alpha (because it uses crossectional features so need a larger universe). t3 is furthered filter for SEPA entry criterias.

---

## Table of Contents

1. [Daily Pipeline — Flow](#daily-pipeline)
2. [Phase Map](#phase-map)
3. [Key Tables](#key-tables)
4. [Audit System](#audit-system)
5. [Ticker Lifecycle — Deactivate / Rename / Purge](#ticker-lifecycle)
6. [Helper Libraries](#helper-libraries)
7. [Model Registry](#model-registry)
8. [Model Training](#model-training)
9. [Backtesting](#backtesting)
10. [Dashboard](#dashboard)
11. [Evaluation Framework](#evaluation-framework)
12. [Cache & Report Locations](#cache--report-locations)
13. [Open TODOs](#open-todos)
14. [Resolved](#resolved)

---

## Daily Pipeline

```
Phase 1 (price/fund/shares/macro) ──CRITICAL──▶ Phase 2 (screener members)
│ -> price_data                                  │ -> screener_membership
│   fundamentals                                 │   [criteria from screener_criteria_versions]
│   shares_history                               │
│   macro_data                    ┌──────────────┴──────────────┐
│                                 ▼                              ▼
│                         Phase 3 (T2 features)         Phase 4 (regime) [non-crit]
│                         -> t2_screener_features       -> t2_regime_scores
│                         [OHLCV, SMAs, EMAs,            [M03 pillars, deltas]
│                          XS alphas, ranks]
│                                 │
│                         Phase 4b (sepa_watchlist) ──CRITICAL
│                         -> sepa_watchlist
│                         [open/close SEPA sessions; T3 universe gate]
│                                 │
│                         Phase 5 (T3 SEPA features) ──CRITICAL
│                         -> t3_sepa_features
│                         [filtered by sepa_watchlist universe; carry-forward T2 + TS alphas + M03 join]
│                                 │
│                         Phase 6 (views) [non-crit]
│                         -> SQL views
│                         [v_d1 = sessions/trades, v_d2 = hydrate + outcomes]
│                                 │
│                         Phase 7 (training cache) [non-crit]
│                         -> d2_training_cache
│                                 │
│                         Phase 8 (monitoring) [always]
│                         -> logs / alerts only
```

### Detailed Data Flow & Dependency Chart

> **Source of truth:** [`docs/architecture/data_flow.mmd`](architecture/data_flow.mmd) — single Mermaid file shared with the dashboard's Pipeline Health page. Render locally with `mmdc -i docs/architecture/data_flow.mmd -o data_flow.svg`, view inline in any Mermaid-aware viewer, or open the dashboard.

**CLI (daily runner):**
```bash
python scripts/run_daily_pipeline.py                    # Full pipeline (yesterday)
python scripts/run_daily_pipeline.py --date 2024-01-15  # Specific date
python scripts/run_daily_pipeline.py --phase-1-only     # T1 ingestion only
python scripts/run_daily_pipeline.py --phase-2-only     # Screener membership only
python scripts/run_daily_pipeline.py --phase-3-only     # T2 features incremental
python scripts/run_daily_pipeline.py --phase-4-only     # Regime scores incremental
python scripts/run_daily_pipeline.py --phase-5-only     # T3 SEPA features incremental
python scripts/run_daily_pipeline.py --force            # Ignore idempotency
python scripts/run_daily_pipeline.py --dry-run          # Validate only
```

---

## Phase Map

### Phase 1 — T1 Ingestion & Maintenance *(CRITICAL)*

**Purpose**: Fetch raw data from external sources into DuckDB.

**Input**: Active tickers from `company_profiles`, external APIs (yfinance, FMP, FRED).

**Process**:
| Step | Updates | Source |
|------|---------|--------|
| 1.1 Price | `price_data` | yfinance (stale tickers only) |
| 1.2 Fundamentals | `fundamentals`, `earnings_calendar` | yfinance (due tickers only) |
| 1.3 Shares | `shares_history` (column: `shares_outstanding`) | yfinance (7-day staleness check) |
| 1.4 Macro | `macro_data`, `t1_macro` | FRED + VIX + SPY/QQQ OHLCV |

**Output**: Raw OHLCV, fundamentals, shares, macro data in DuckDB.

**Toolkit:**
| File | Purpose |
|------|---------|
| `src/data_engine.py` | Price ingestion (`DataRepository`) |
| `src/fundamental_engine.py` | Fundamentals + earnings calendar |
| `src/shares_engine.py` | Shares outstanding |
| `src/macro_engine.py` | Macro indicators + SPY/QQQ |
| `src/universe_backfill.py` | Historical backfill + FMP discovery |
| `scripts/run_universe_backfill.py` | CLI for backfill + universe management |
| `scripts/backfill_fundamentals.py` | FMP fundamentals backfill |
| `scripts/backfill_fundamental_ratios.py` | Compute missing PE/PS/PB/PEG ratios from raw data |
| `scripts/backfill_shares_from_fundamentals.py` | Backfill shares_history from `fundamentals.basic_avg_shares` |
| `scripts/backfill_t1_macro.py` | Backfill SPY/QQQ/VIX daily OHLCV via yfinance |
| `scripts/ingest_t1_macro.py` | One-shot ingest of t1_macro for a date range |
| `tools/run_all_audits.py` | **Run all audits in one go** (orchestrator) |
| `tools/audit_t1_data_quality.py` | T1 data quality audit |
| `tools/purge_t1_price_negatives.py` | Remove bad price rows |
| `tools/purge_t1_fundamentals.py` | Remove fundamentals for specific ticker |
| `tools/deactivate_tickers.py` | Retire delisted tickers |
| `tools/purge_junk_tickers.py` | Remove warrants/SPACs/units |
| `tools/rename_tickers.py` | Cross-table ticker rename |
| `tools/patch_fundamentals.py` | Fix `filing_date` anomalies (zero / stale-historical modes) |

**Backfill:**
```bash
python scripts/run_universe_backfill.py --discover-fmp
python scripts/run_universe_backfill.py --backfill-prices --start-date 2000-01-01
python scripts/run_universe_backfill.py --backfill-shares
python scripts/backfill_fundamentals.py --source fmp --overwrite
python scripts/backfill_fundamental_ratios.py
python scripts/backfill_t1_macro.py --start 2000-01-01
```

**Audit:**
```bash
python tools/audit_t1_data_quality.py          # T1 only
python tools/run_all_audits.py                 # All phases in one go
python tools/run_all_audits.py --warn-only     # Exit 1 if any FAIL/WARN
python tools/run_all_audits.py --date 2024-06-01  # Spot-check a date (T2/T3)
python tools/run_all_audits.py --skip t1 t3   # Skip specific audits
```

---

### Phase 2 — Screener Membership *(CRITICAL)*

**Purpose**: Determine which tickers qualify for the investable universe (point-in-time correct).

**Input**: `price_data`, `shares_outstanding`, `screener_criteria_versions`.

**Criteria (v2)**: `close >= $5`, `avg_volume_20d >= 100K`, `market_cap >= $150M`. Log entry/exit events with **126-day grace period** before exit.

**Output**: `screener_membership` — append-only event log (one row per status change per ticker).

**Toolkit:**
| File | Purpose |
|------|---------|
| `src/managers/screener_manager.py` | `ScreenerManager.evaluate_and_log()` |
| `scripts/backfill_screener_membership.py` | Full history backfill (~10s) |
| `tools/audit_t2_membership.py` | Membership audit |

**Backfill:** `python scripts/backfill_screener_membership.py [--reset]`

**Audit:** `python tools/audit_t2_membership.py`

---

### Phase 3 — T2 Screener Features *(CRITICAL)*

**Purpose**: Compute features for the full investable universe. Every active screener ticker gets a row per trading day.

**Input**: `price_data`, `screener_membership` (point-in-time join), `t1_macro` (SPY benchmark).

**Process** (4 sub-phases):
| Sub-phase | Method | What |
|-----------|--------|------|
| A — SQL | CTE chain in `compute_t2_screener_features()` | OHLCV carry-through, SMAs (20/50/150/200), RS line + rating, 52w/20d ranges, volume ratios, ATR, NATR, VCP, volatility, SEPA flags (`trend_ok`, `breakout_ok`) |
| B — Python (alphas) | `compute_alpha_features()` | 9 XS alphas (alpha001–alpha060) via multiprocessing. Must run on full ~2400-ticker population for valid cross-sectional ranks. |
| B-EMA — Python | `compute_ema_features()` | 5 EMAs (8, 21, 50, 100, 200) via `pandas.ewm()`. Recursive — cannot be computed in SQL. |
| C — SQL | `compute_cross_sectional_ranks()` | 7 rank columns: RS_Universe_Rank, RS_Sector_Rank, RS_vs_Sector, Sector_Momentum, RS_Industry_Rank, RS_vs_Industry, Industry_Momentum |

**Output**: `t2_screener_features` (~2400 tickers/day, ~70 columns including OHLCV + EMAs + alphas + ranks).

**Toolkit:**
| File | Purpose |
|------|---------|
| `src/feature_pipeline.py` | `FeaturePipeline.compute_t2_screener_features()` |
| `scripts/backfill_t2_screener_features.py` | Backfill Phase 3 for full price_data history |
| `tools/audit_t2_screener_features.py` | T2 feature audit |

**Incremental:** `python scripts/run_daily_pipeline.py --phase-3-only` (detects gap from `MAX(date)` to last trading day, plus coverage-aware recompute if <99% tickers present)

**Audit:** `python tools/audit_t2_screener_features.py`

---

### Phase 4 — T2 Regime Scores *(non-critical)*

**Purpose**: Compute M03 market regime scores (macro/breadth context, one row per date).

**Input**: `macro_data`, `price_data`.

**Process**: `M03RegimeCalculator.calculate_history_vectorized()` — computes trend/liquidity/risk pillars, 5d/20d deltas, regime volatility.

**Output**: `t2_regime_scores` — columns: `date, m03_score, m03_pillar_trend, m03_pillar_liq, m03_pillar_risk, m03_delta_5d, m03_delta_20d, m03_regime_vol`.

**Toolkit:**
| File | Purpose |
|------|---------|
| `src/regime_pipeline.py` | `RegimePipeline` (CLI + programmatic) |
| `src/pipeline/m03_regime.py` | `M03RegimeCalculator` |

**Incremental:** `python scripts/run_daily_pipeline.py --phase-4-only` (auto-detects gap)

**Backfill:** `python src/regime_pipeline.py --backfill [--start 2020-01-01]`

---

### Phase 4b — SEPA Watchlist Update *(CRITICAL)*

**Purpose**: Maintain the `sepa_watchlist` event log — the universe gate for T3. Each ticker that ever entered a SEPA session has at least one row; T3 then carries that ticker's full price history (Option C design, 2026-05-08).

**Input**: `t2_screener_features` for `target_date` (reads `trend_ok`, `breakout_ok`, `close`, `sma_50/150/200`).

**Process** (one SQL pass, three operations, in order):
1. **Close** open sessions whose trend boundary breaks today (`close < sma_50 OR sma_150 OR sma_200`) → `exit_date = today`, `cooldown_end = today + 14 days`, `status = 'COOLDOWN'`.
2. **Open** new sessions for tickers with `trend_ok AND breakout_ok` today AND no open session AND past prior `cooldown_end` → INSERT `status = 'ACTIVE'`, `session_id = max(prior) + 1`.
3. **Promote** any `COOLDOWN` row whose `cooldown_end < today` → `status = 'EXITED'`. Refresh `trend_ok`/`breakout_ok` on remaining ACTIVE rows.

**Output**: `sepa_watchlist` — event log keyed by `(ticker, entry_date)`. Columns: `ticker, entry_date, exit_date, cooldown_end, session_id, trend_ok, breakout_ok, status, updated_at`.

**Session model**:
- **Entry trigger**: `trend_ok AND breakout_ok` (full SEPA setup).
- **Exit trigger**: C1+C2+C6 break (close drops below sma_50/150/200). Uses C1+C2+C6 only — *not* full `trend_ok` — to avoid C9 RS-line flicker fragmenting one long session into many short ones.
- **Cooldown**: 14 calendar days after `exit_date` before a new session can open for the same ticker.
- **Re-entry**: new `session_id`, new row. Prior session's `exit_date`/`cooldown_end` are preserved.

**Key design notes**:
- Cooldown is a **session-opening gate**, not a row-inclusion gate. T3 carries full history for every ticker that has ever appeared in `sepa_watchlist`, regardless of cooldown state.
- `update_daily(date)` is **not idempotent** — re-running it for the same date would attempt to open duplicate sessions on tickers that already entered today. Use the `pipeline_runs` idempotency guard (set by orchestrator) or manually clean up (see Backfill notes below) before re-running.
- Distinct from `screener_watchlist` (the dashboard trade log). Both coexist.

**Toolkit:**
| File | Purpose |
|------|---------|
| `src/managers/sepa_watchlist_manager.py` | `SepaWatchlistManager.backfill()`, `update_daily()`, `get_universe()`, `get_stats()` |
| `scripts/backfill_sepa_watchlist.py` | One-time full backfill from t2 history (~7s) |

**Incremental:** Runs automatically as Phase 4b in the daily pipeline.

**Backfill (one-time, authoritative — wipes existing rows):**
```bash
python scripts/backfill_sepa_watchlist.py                                # full t2 history
python scripts/backfill_sepa_watchlist.py --start 2010-01-01 --end 2024-12-31  # custom range
```
Always run *before* T3 backfill — T3 reads `SELECT DISTINCT ticker FROM sepa_watchlist`.

**Manual rerun of a date** (rare — for fixing a bad daily run):
```sql
DELETE FROM sepa_watchlist WHERE entry_date = '<DATE>';
UPDATE sepa_watchlist
SET exit_date = NULL, cooldown_end = NULL, status = 'ACTIVE'
WHERE exit_date = '<DATE>';
```
Then call `update_daily('<DATE>')` again.

---

### Phase 5 — T3 SEPA Features *(CRITICAL)*

**Purpose**: Materialize the full feature set for the SEPA universe. Single source of truth for all downstream ML and views.

**Input**: `t2_screener_features` (SEPA filter + carry-forward), `price_data` (per-ticker rolling windows), `t2_regime_scores` (M03 join), **`sepa_watchlist` (universe gate)**.

**Process** (2 sub-phases):
| Sub-phase | What |
|-----------|------|
| A — SQL INSERT | Filters tickers via `WHERE ticker IN (SELECT DISTINCT ticker FROM sepa_watchlist)`. Carries forward all T2 columns (OHLCV, SMAs, EMAs, RS, XS alphas, ranks, `trend_ok`, `breakout_ok`). Computes per-ticker window features: momentum (21/63/126/189/252d), RSI-14, ATR-14, volume depth, velocity features, pattern flags, pct_chg deltas, sma_50_slope, rs_line_lag_delta. Joins M03 regime scores by date. |
| B — Python UPDATE | 9 TS alphas (alpha006–alpha101) + 2 vol-adjusted features via multiprocessing. Warmup loaded from `t2_screener_features` (broader population) for continuous rolling windows. |

**Output**: `t3_sepa_features` (~9.4M rows total over 2,697 SEPA-eligible tickers, **144 columns**). Keyed by `(ticker, date, feature_version)`.

**Key design notes** (Option C, 2026-05-08):
- **Universe = sepa_watchlist tickers, full history.** A ticker is in T3 iff it has ever opened a SEPA session. T3 carries that ticker's complete history regardless of current SEPA state. The previous design (Option B) gated by `screener_membership.is_active` and produced ~70% non-SEPA noise rows — replaced.
- Both `trend_ok` and `breakout_ok` are explicit columns. Filter on `trend_ok=TRUE AND breakout_ok=TRUE` for entry candidates; filter on neither for the full SEPA-universe history.
- T3 is dense over `sepa_watchlist_tickers ∩ has_t2_row`.
- T3 rows are append-only — once written, permanent.
- **Fundamentals removed from T3 schema** (2026-05-08): `net_income`, `revenue`, `shares_outstanding`, `peg_adjusted` are no longer stored in T3. They are joined at query time by `v_d2_features` (LEFT JOIN to `fundamental_features` and `shares_history`). Saves ~300MB and eliminates ASOF JOIN cost at insert time.
- `dist_from_52w_high_pct_chg` / `dist_from_20d_high_pct_chg`: uses `CASE WHEN cur = prev THEN 0` to handle zero-denominator (breakout stocks at highs).
- `EXPECTED_T3_COLUMN_COUNT = 144` is a tripwire in `feature_pipeline.py`. Update alongside any DDL change.

**Toolkit:**
| File | Purpose |
|------|---------|
| `src/feature_pipeline.py` | `FeaturePipeline.compute_t3_features()`, `_create_t3_table()` |
| `scripts/backfill_t3_sepa_features.py` | Chunked-resumable T3 backfill |
| `tools/audit_t3_sepa_features.py` | T3 feature audit |

**Incremental:** `python scripts/run_daily_pipeline.py --phase-5-only` (detects gap from `MAX(date)` to last trading day, plus coverage-aware recompute if breakout tickers missing)

**Backfill (one-time, after sepa_watchlist is populated):**
```bash
python scripts/backfill_t3_sepa_features.py --restart --from 2001-Q1
```
Expected: ~9.4M rows, 1.5-2.5h wall time. Tail progress: `tail -f logs/t3_backfill_progress.log` (see "Tailing logs" at bottom of doc for the bash equivalent of PowerShell `Get-Content -Wait`).

After completion: `python scripts/create_duckdb_views.py && python scripts/refresh_training_cache.py`.

**Audit:** `python tools/audit_t3_sepa_features.py`

---

### Phase 6 — View Refresh *(non-critical)*

**Purpose**: Recreate SQL views that transform T3 features into trade-level training data.

**Input**: `t3_sepa_features`, `price_data`, `fundamentals`, `company_profiles`.

**Observed timing (2026-05-13, 38K trades):**
- Phase 6 (DDL only — `CREATE OR REPLACE VIEW`): ~16 min
- Phase 7 (materialise `d2_training_cache`): **~592s (~10 min)** — STALE, see note below
- Combined Phase 6+7: ~26 min out of ~38 min total pipeline

**Performance bottleneck (RESOLVED in code, timing not re-measured)**: The `sl_exits` CTE in `v_d2_training` previously ran a correlated subquery — `SELECT p.date FROM price_data WHERE p.ticker = s.ticker AND p.date > s.sl_date ORDER BY p.date LIMIT 1` — once per SL-triggered trade. This has been rewritten using the `price_with_next` CTE with `LEAD(date) OVER (PARTITION BY ticker ORDER BY date)` (see `src/managers/view_manager.py:580-597`). The 592s timing above predates this fix. **Action: re-time Phase 7 to determine current bottleneck (if any).**

**Process**: The view chain progressively transforms daily SEPA observations into trade-level rows with outcomes:

| View | Row represents | Status | Downstream consumers |
|------|---------------|--------|----------------------|
| `v_sepa_candidates` | 1 day per ticker (while in trend) | **Active** | Diagnostic queries, notebooks |
| `v_d1_candidates` | **1 trade** (session) | **Active** | `v_d2_features`, `v_d2_hydrated`, `v_screener_dashboard` |
| `v_d1_trades` | Alias for `v_d1_candidates` | Alias (low use) | Notebooks only — prefer `v_d1_candidates` |
| `v_d2_features` | 1 trade + fundamentals | **Active** | `v_d2_training`, `v_d3_deployment`, `v_d2_hydrated` |
| `v_d2_hydrated` | **N days per trade** (entry→exit daily rows) | **Active — ML only** | `v_d2_training` only. Backtest no longer uses this — backtest reads `t3_sepa_features` + `price_data` directly via `DuckDBCandidateFeed`. |
| `v_d2r_hydrated` | Alias for `v_d2_hydrated` | **Backward-compat alias** | Old scripts/notebooks. Migrate to `v_d2_hydrated`. |
| `v_d2_training` | **1 trade + outcomes** | **Active — ML hub** | `train_mfe_classifier.py`, `d2_training_cache`, ablation, validation scripts |
| `v_d3_deployment` | Last 252 days of SEPA candidates | **Active** | `dashboard.py` (live M01 scoring) |
| `v_screener_dashboard` | **1 trade** (session) | **Active — duplicates session logic** | Source for `screener_watchlist`. Re-implements `v_d1_candidates` session detection on T2 — same full LAG/window pass. |

**Output**: 9 production views + 2 backward-compat aliases + 2 materialised tables.

**Materialised tables:**
| Table | Source | Rows (2026-05-13) | Refresh wall time |
|-------|--------|-------------------|-------------------|
| `screener_watchlist` | `v_screener_dashboard` | ~38K (all trades ever) | ~7s (DDL only — view is cheap to materialise) |
| `d2_training_cache` | `v_d2_training` | ~38K | ~592s (pre-2026-05-14; correlated subquery resolved — re-time needed) |

**Known tech debt in Phase 6+7:**
- `v_screener_dashboard` duplicates the full session-detection CTE block (`trend_c8_base` → `trend_sessions` → `sessions` → `entries` → `session_bounds`) that `v_d1_candidates` already computes. These could share a materialised intermediate, halving T2 scan work.
- `v_d2_hydrated` exists solely to feed `v_d2_training`. If `v_d2_training` were rewritten to compute MAE/MFE/SL directly against `price_data` (pre-joined), `v_d2_hydrated` could be dropped.
- ~~The `sl_exits` correlated subquery is the primary Phase 7 bottleneck.~~ RESOLVED 2026-05-14: rewritten using a `price_with_next` CTE with `LEAD(date/close) OVER (PARTITION BY ticker ORDER BY date)` (see session log). Re-time Phase 7 to find the new bottleneck (if any).

**Toolkit:**
| File | Purpose |
|------|---------|
| `src/managers/view_manager.py` | `ViewManager.create_all()` (views + screener_watchlist) |
| `src/screener_diagnostics.py` | `ScreenerDiagnostics` — reusable library for per-ticker SEPA criteria diagnosis |
| `scripts/create_duckdb_views.py` | Standalone CLI for view recreation |
| `scripts/show_screener.py` | CLI table of active SEPA trades (reads `screener_watchlist`) |
| `scripts/diagnose_ticker.py` | CLI wrapper for `ScreenerDiagnostics` |
| `notebooks/screener_dashboard_snippet.py` | Notebook snippet (3 cells: active trades, watchlist, recent exits) |

**Manual recreation:** `python scripts/create_duckdb_views.py`

**Screener dashboard:**
```bash
python scripts/show_screener.py                    # Active trades (default: sort by entry_date)
python scripts/show_screener.py --sort pct_return  # Sort by return
python scripts/show_screener.py --sort ticker      # Alphabetical
```

**Ticker diagnostic:**
```bash
python scripts/diagnose_ticker.py ROST              # Last 15 days (default)
python scripts/diagnose_ticker.py LUNR --days 20    # Custom lookback
python scripts/diagnose_ticker.py AAPL --start 2026-01-01 --end 2026-03-28
```

```python
# Programmatic (notebooks / REPL)
from src.screener_diagnostics import ScreenerDiagnostics
diag = ScreenerDiagnostics()
result = diag.diagnose('ROST', days=15)   # Returns dict: ticker, freshness, trades, criteria, transitions
diag.print_report(result)                 # Formatted console output
```
Shows: data freshness, recent trades, per-day C1-C9 trend + B1-B2 breakout pass/fail matrix, state transitions with failing criteria.

**Notebook (DataWrangler):** Open `notebooks/screener_dashboard_snippet.py` and run cells:
- Cell 1: Active trades — breakout triggered, session still open
- Cell 2: Watchlist — tickers in SEPA trend template, no breakout yet (candidates to watch)
- Cell 3: Recent exits — trades that exited in last 30 days, with return since entry

---

### Phase 7 — Training Cache Refresh *(non-critical)*

**Purpose**: Materialize `v_d2_training` into `d2_training_cache` for fast ML training loads (70x speedup: 8.8s → 0.126s).

**Input**: `v_d2_training`.

**Output**: `d2_training_cache` table.

**Toolkit:**
| File | Purpose |
|------|---------|
| `src/managers/view_manager.py` | `ViewManager.refresh_cache()` |
| `scripts/refresh_training_cache.py` | CLI (`--stats` for age/rows) |
| `scripts/benchmark_training_cache.py` | Validate 70x speedup |

---

### Phase 8 — Monitoring *(always runs)*

**Purpose**: Log health metrics, check coverage, and fire alerts on anomalies.

**Input**: `run_stats` from phases 1–7, `pipeline_runs` table, `price_data`, `screener_membership`, `t2_screener_features`, `t3_sepa_features`.

**Output**: Log entries + alert messages only (no DB writes).

**Alerts:**
| Alert | Trigger | Fix |
|-------|---------|-----|
| Breakout drought | 0 breakouts for N consecutive days | Investigate market conditions |
| Runtime anomaly | Phase took >3x average runtime | Check API rate limits |
| Recent failures | Phase failures in last 7 days | Check logs |
| T2 coverage gap | <99% ticker coverage on target date | `--phase-3-only` |
| T3 coverage gap | Missing breakout tickers in T3 | `--phase-5-only` |

**Toolkit:**
| File | Purpose |
|------|---------|
| `src/managers/pipeline_run_manager.py` | `PipelineRunManager` (tracking + health reports) |
| `src/orchestrators/daily_pipeline_orchestrator.py` | `_check_coverage()`, `_t2_coverage_deficit()`, `_t3_coverage_deficit()` |
| `config.py` | `PIPELINE_FAILURE_MODES`, `PIPELINE_ALERT_THRESHOLDS` |

---

## Key Tables

| Table | Phase | Rows | Purpose |
|-------|-------|------|---------|
| `price_data` | 1.1 | ~12M | OHLCV history (equity only; SPY/QQQ in `t1_macro`) |
| `fundamentals` | 1.2 | ~300K | IS/BS/CF quarterly, keyed `(ticker, period_end)` |
| `earnings_calendar` | 1.2 | ~20K | Upcoming/past earnings dates |
| `shares_history` | 1.3 | ~2M | Historical shares |
| `macro_data` | 1.4 | ~40K | FRED + VIX indicators |
| `t1_macro` | 1.4 | ~7K | SPY/QQQ OHLCV + VIX (benchmark source) |
| `company_profiles` | seed | ~3K | Universe seed: ticker, name, sector, industry, is_active, delisting_date |
| `ticker_blacklist` | maintenance | ~200 | Permanent record of purged non-tradeable tickers |
| `screener_criteria_versions` | 2 | ~5 | Historical criteria parameter sets (v1, v2, ...) |
| `screener_membership` | 2 | ~20K | Event log — one row per entry/exit per ticker |
| `t2_screener_features` | 3 | ~9.6M | Full universe: OHLCV, SMAs, EMAs, RS, alphas, ranks, SEPA flags |
| `t2_regime_scores` | 4 | ~1.5K | One row per date: M03 score + pillars + deltas |
| `sepa_watchlist` | 4b | ~35K | Event log — one row per SEPA session per ticker. T3 universe gate. |
| `t3_sepa_features` | 5 | ~9.4M | sepa_watchlist universe, full history per ticker: 144 cols, single ML source of truth |
| `screener_watchlist` | 6 | ~38K | Materialized `v_screener_dashboard` (all trades, ACTIVE/EXITED, with returns) |
| `d2_training_cache` | 7 | ~38K | Materialized `v_d2_training` (trade-level with outcomes, ~592s to refresh) |
| `pipeline_runs` | 8 | varies | Phase execution tracking + idempotency |
| `models` | ML | varies | Model registry — versions, metrics, artifact paths |

---

## Audit System

All audits are in `tools/`. Run individually or all-at-once:

```bash
python tools/run_all_audits.py                     # All phases
python tools/run_all_audits.py --warn-only          # Exit 1 if any FAIL/WARN
python tools/run_all_audits.py --date 2024-06-01    # Spot-check T2/T3 at a specific date
python tools/run_all_audits.py --skip t1 t3         # Skip specific audits
python tools/run_all_audits.py --json               # Machine-readable output
```

**Audit reports** are written to `data/audit_reports/audit_report_YYYYMMDD.json`.

---

### audit_t1_data_quality.py

Sections and checks:

**1. Coverage**
- `company_profiles_tickers` — total tickers in universe seed (INFO)
- `{table}_coverage_pct` — % of CP tickers present in price_data / shares_history / fundamentals (WARN if <80% / <60% / <60%)
- `{table}_missing_from_cp` — active CP tickers with NO rows in downstream tables (WARN if >0)
- `{table}_orphan_tickers` — tickers in downstream table NOT in CP; warrants/preferred/rights reported as INFO, regular equities as WARNING

**2. Freshness**
- `price_data_max_date` — days since latest price row (WARN if >5 calendar days)
- `price_data_stale_tickers` — active tickers with no data in last 5 days (WARN if >5% of universe)
- `shares_history_max_date` — days since latest shares row (WARN if >30 days)
- `fundamentals_max_period_end` — latest period_end (WARN if older than 120 days ago)
- `fundamentals_future_period_end` — rows with period_end > today (WARN if >0)

**3. Fundamentals Completeness**
- `null_pct_{col}` for 13 key columns: total_revenue, net_income, gross_profit, operating_income, ebit, ebitda, total_assets, stockholders_equity, operating_cash_flow, free_cash_flow, basic_eps, diluted_eps, filing_date (WARN >15%, FAIL >50%)
- `source_{source}` — row/ticker counts per data source (INFO)
- `sparse_tickers_lt4_periods` — tickers with <4 quarterly periods (WARN if >10%)
- `avg_periods_per_ticker` — average periods per ticker (INFO)

**4. Price Data Integrity**
- `duplicate_ticker_date` — duplicate (ticker, date) keys (FAIL if >0)
- `null_or_zero_close` — NULL or non-positive close (FAIL if >0)
- `zero_volume_rows` — volume=0 rows (WARN if >1%)
- `extreme_price_moves_gt200pct` — single-day >200% moves (WARN if >100 rows)
- `extreme_movers_top20` — top 20 tickers by extreme move count (INFO)
- `tickers_with_gaps` — active tickers with >20% fewer rows than SPY in their date range (FAIL if >0)
- `gap_tickers_top20` — top gap tickers vs SPY (INFO)

**4b. Filing Date Integrity**
- `null_filing_date` — % rows missing filing_date (WARN if >30%)
- `filing_before_period_end` — filing_date < period_end, physically impossible (FAIL if >0)
- `filing_lt_30d_after_period` — filed <30 days after period_end, suspiciously fast (WARN if >0)
- `filing_gt_90d_after_period` — filed >90 days after period_end, outside SEC window (WARN if >0)

**5. Macro Data (t1_macro) Integrity**
- `table_exists` — t1_macro table present (FAIL if missing)
- `max_date` — days since latest t1_macro row (WARN if >5 days)
- `null_{spy_close|qqq_close|vix_close}` — NULL critical columns (FAIL if >0)
- `date_gaps_vs_price_data` — trading days in price_data missing from t1_macro (FAIL if unexpected; INFO if only known market closures like 9/11)

**6. Shares History Integrity**
- `duplicate_ticker_date` — duplicate (ticker, date) keys (FAIL if >0)
- `null_or_zero_shares` — NULL or non-positive shares_outstanding (WARN if >1%)

**Thresholds:**
```python
STALE_PRICE_DAYS = 5
STALE_SHARES_DAYS = 30
FUNDAMENTAL_NULL_WARN_PCT = 15.0
FUNDAMENTAL_NULL_FAIL_PCT = 50.0
MIN_PRICE_COVERAGE_PCT = 80.0
MIN_SHARES_COVERAGE_PCT = 60.0
MIN_FUND_COVERAGE_PCT = 60.0
```

---

### audit_t2_membership.py

**1. Event Log Health**
- `total_events` — row count (INFO)
- `entry_events` / `exit_events` — counts (INFO)
- `exits_exceed_entries` — tickers where exit events > entry events per ticker (FAIL if >0; state machine bug)
- `date_range` — min/max effective_date (INFO)
- `distinct_tickers` — unique tickers ever in event log (INFO)

**2. Market Cap Integrity**
- `zero_or_null_market_cap_pct` — entry events with market_cap=0 or NULL (FAIL >20%, WARN >5%)
- `zero_mcap_tickers_top20` — top tickers with zero market_cap on entry (INFO)
- `price_eligible_never_entered_no_shares` — tickers passing price>=5 but never entered universe due to missing shares_history (WARN if >50)

**3. Grace Period Logic**
- `exits_with_wrong_consec_fail_days` — exit events where consec_fail_days != 126 (FAIL if >0)
- `entries_with_nonzero_consec_fail_days` — entry events where consec_fail_days != 0 (FAIL if >0)

**4. State Consistency**
- `duplicate_entry_events` — consecutive TRUE events for same ticker (missing exit between them) (FAIL if >0)
- `duplicate_exit_events` — consecutive FALSE events for same ticker (FAIL if >0)

**5. Current Universe Size**
- `active_ticker_count` — active universe at as_of_date (WARN if <200 or >5000)

**6. Criteria Version Coverage**
- All events use a known version (FAIL if unknown version found)

---

### audit_t2_screener_features.py

**1. Coverage**
- Row counts, date range vs screener_membership
- Ticker coverage vs screener_membership active tickers (WARN if <80%)
- `active_tickers_no_recent_price` — active CP tickers with no recent data (excludes is_active=FALSE)

**2. SEPA Flags**
- `trend_ok` / `breakout_ok` null rates (FAIL >20%, WARN >5%)
- SEPA candidate yield = rows where `trend_ok AND breakout_ok` / total rows (WARN if <0.5% or >30%)

**3. Key Column Nulls**
Critical columns that must be non-null for SEPA filtering:
`price_vs_sma_50/150/200`, `close_above_sma200`, `dist_from_52w_high/low`, `rs`, `rs_ma`, `rs_rating`, `atr_20d`, `natr`, `vcp_ratio`, `vol_avg_20`, `dry_up_volume`, `trend_ok`, `breakout_ok`
(FAIL >20%, WARN >5%)

**4. Cross-sectional Ranks / Alphas**
Rank columns: `RS_Universe_Rank`, `RS_Sector_Rank`, `RS_vs_Sector`, `Sector_Momentum`
Alpha columns: `alpha001`, `alpha002`, `alpha004`, `alpha011`
- Null checks downgrade to INFO when nulls are within warmup window (first 270 rows/ticker); separate check for post-warmup nulls

**5. Staleness**
- Latest date vs today (WARN if >5 calendar days)

**6. Referential**
- Orphan tickers in t2 not in screener_membership (WARN if >0)

---

### audit_t3_sepa_features.py

**1. Coverage**
- Row counts, date range, ticker count
- T3 vs T2 SEPA candidates — missing breakout tickers (WARN if coverage <80%)

**2. Feature Version**
- Distribution of `feature_version` values (INFO)
- All rows should be `'v3.1'`

**3. Key Column Nulls (Phase A SQL)**
`close`, `volume`, `sma_50/150/200`, `price_vs_sma_50/150/200`, `close_above_sma200`, `dist_from_52w_high/low`, `rs`, `rs_ma`, `rs_rating`, `atr_20d`, `natr`, `vcp_ratio`, `vol_avg_20`, `dry_up_volume`, `rsi_14`, `mom_63d`, `mom_252d`

**4. Pct Change Deltas (v3.1)**
19 `*_pct_chg` columns — null check (first row per ticker expected NULL)

**5. TS Alphas (Phase B Python)**
`alpha006`, `alpha009`, `alpha012`, `alpha041`, `alpha046`, `alpha049`, `alpha051`, `alpha054`, `alpha101`

**6. EMAs (from T2)**
`ema_8`, `ema_21`, `ema_50`, `ema_100`, `ema_200`

**7. XS Alphas + Ranks (from T2)**
`alpha001`, `alpha002`, `alpha004`, `alpha008`, `alpha011`, `alpha013`, `alpha015`, `alpha019`, `alpha060`
Ranks: `RS_Universe_Rank`, `RS_Sector_Rank`

**8. M03 Regime**
`m03_score`, `m03_pillar_trend`, `m03_pillar_liq`, `m03_pillar_risk`, `m03_delta_5d`, `m03_delta_20d`, `m03_regime_vol`
(WARN if >5% null — signals regime join failure)

**9. Staleness**
- Latest date vs today (WARN if >5 calendar days)

**10. Referential**
- Orphan tickers in T3 not in screener_membership
- Missing SEPA candidates: tickers in T2 with `trend_ok AND breakout_ok` but absent from T3

---

## Ticker Lifecycle — Deactivate / Rename / Purge

### When to deactivate

Use when a ticker is delisted, acquired, or merged but you want to preserve historical data.

**Effect**: Sets `is_active = FALSE`, `delisting_date = CURRENT_DATE` in `company_profiles`. Pipeline stops ingesting new data. All historical rows preserved.

```bash
python tools/deactivate_tickers.py FPAY IMAB ZYXI           # dry-run
python tools/deactivate_tickers.py FPAY IMAB ZYXI --execute  # apply
```

**Trigger conditions**:
- Ticker no longer trading (exchange delisting)
- Acquisition/merger completed
- Audit shows `audit_t1_data_quality` `price_data_stale_tickers` warning for a known-dead ticker
- `screener_membership` shows active rows for `company_profiles.is_active = FALSE` tickers (run `deactivate_tickers.py` + inject exit events)

---

### When to rename

Use when a ticker changes symbol (same company, new symbol) or two tickers need merging (split history).

**Two cases handled**:
1. **Simple rename** — old ticker exists, new doesn't → `UPDATE ticker` across all tables
2. **Merge** — both old and new exist → `INSERT OR IGNORE` old history into new, delete old

**Tables updated**:
`price_data`, `fundamentals`, `shares_history`, `earnings_calendar`, `t2_screener_features`, `t3_sepa_features`, `screener_membership`, `company_profiles`

```bash
python tools/rename_tickers.py POAI:AGPU LPTX:CYPH KAR:OPLN   # dry-run
python tools/rename_tickers.py POAI:AGPU --execute              # apply
```

**Trigger conditions**:
- Ticker symbol change announced by the company
- yfinance/FMP returns data under new symbol but DB still has old
- Data split across two symbols after a spin-off

---

### When to purge

Use when a ticker should never have been in the database — non-tradeable securities.

**Purge candidates** (identified automatically):
- Warrants: `*-WT`, `*-WT*`
- Units: `*-UN`, `*-UN*`
- Rights: `*-RI`, `*-RI*`
- Preferred: `*-P_`, `*-P__`
- Wildcards: `*` suffix
- SPACs/blank-check companies: name contains "acquisition", "spac", "blank check", "merger"
- Tickers > 5 characters

**Effect**: Added to `ticker_blacklist` (permanent, never re-ingested). Deleted from `company_profiles` and `price_data`. Warrants/preferred/rights data in `shares_history` / `fundamentals` is **kept** as historical data.

**Also removes**: All `price_data` rows with `date < 2000-01-01` (pre-2000 junk cleanup).

```bash
python tools/purge_junk_tickers.py           # dry-run (shows candidates)
python tools/purge_junk_tickers.py --execute  # apply
```

**Note**: Run `run_all_audits.py` after purge — `orphan_tickers` checks will confirm warrants/preferred/rights are correctly excluded from WARNING count.

---

### Patch fundamentals

For `filing_date` anomalies that don't require deactivation:

```bash
python tools/patch_fundamentals.py --fix filing_date_zero --dry-run   # preview ~55K rows
python tools/patch_fundamentals.py --fix filing_date_zero              # EDGAR lookup + +45d fallback
python tools/patch_fundamentals.py --fix filing_date_stale_historical  # NULL >365d / EDGAR for 91-365d
```

---

## Helper Libraries

These are importable from notebooks/scripts — not just CLI tools.

| Module | Class / Function | Purpose |
|--------|-----------------|---------|
| `src/screener_diagnostics.py` | `ScreenerDiagnostics` | Per-ticker SEPA criteria diagnosis. `diagnose(ticker, days)` returns dict with freshness, trades, per-day C1-C9 / B1-B2 matrix, transitions. `print_report()` for console output. |
| `src/utils.py` | `get_latest_trading_day()` | Returns most recent completed NYSE trading day (calendar-aware). Used everywhere to determine target date. |
| `src/utils.py` | `load_etf_exclusion_list()`, `filter_etfs()` | ETF/fund ticker exclusion. |
| `src/data_loader_duckdb.py` | `load_training_data_from_db(use_cache=True)` | Load `d2_training_cache` (or `v_d2_training` fallback) into DataFrame. Applies `COLUMN_CASE_MAP` rename automatically. |
| `src/model_registry.py` | `ModelRegistry` | CRUD for `models` table — list, register, promote, archive model versions. |
| `src/evaluation/classification_evaluator.py` | `ClassificationEvaluator` | Confusion matrix, ROC/PR curves, SHAP, feature importance. Auto-registers via `ModelRegistry`. |
| `src/evaluation/leakage_guard.py` | `LeakageGuard` | Temporal leakage validation — checks no future data bleeds into training. |
| `src/managers/view_manager.py` | `ViewManager` | `create_all()` recreates all views + `screener_watchlist`. `refresh_cache()` materializes `d2_training_cache`. Constructor: `ViewManager(feature_version='v3.1')`. |
| `src/managers/screener_manager.py` | `ScreenerManager` | `evaluate_and_log(date)` — evaluates screener criteria for one date and logs entry/exit events. |
| `src/managers/sepa_watchlist_manager.py` | `SepaWatchlistManager` | `backfill()` — full rebuild from t2 history. `update_daily(date)` — open/close sessions for one trading day. `get_universe()` — `SELECT DISTINCT ticker FROM sepa_watchlist` (T3 universe gate). `get_stats()` — quick monitoring summary. |
| `src/managers/pipeline_run_manager.py` | `PipelineRunManager` | Phase execution tracking, idempotency checks, health reports. |
| `src/regime_pipeline.py` | `RegimePipeline` | `compute_history()` or `compute_incremental()` — M03 regime scores. |
| `src/feature_pipeline.py` | `FeaturePipeline` | `compute_t2_screener_features()`, `compute_t3_features()`, `compute_all()`. |

---

## Model Registry

**Table**: `models` in DuckDB. Tracks model versions, specs, metrics, and artifact paths.

| Column | Type | Purpose |
|--------|------|---------|
| `version_id` | VARCHAR PK | Unique ID (e.g., `m01_prototype_2003_2026_20260506_160054`) |
| `status_flag` | VARCHAR | `test` / `prod` / `archived` |
| `specs_json` | JSON | Features list, hyperparameters, training config (see below) |
| `feature_version` | VARCHAR | Feature schema (e.g., `v3.1`) |
| `training_date` | DATE | When the model was trained |
| `dataset_rows` | INTEGER | Training set size |
| `artifacts_path` | VARCHAR | Actual path to model files on disk |
| `model_name` | VARCHAR | Base model name (e.g., `m01_prototype_2003_2026`) |
| `model_version` | VARCHAR | Timestamp suffix (e.g., `20260506_160054`) |
| `accuracy`, `weighted_f1`, `macro_f1` | FLOAT | Test/val evaluation metrics |
| `rmse`, `mae`, `r2`, `spearman_corr` | FLOAT | Regression metrics (unused for classifiers) |

**`specs_json` structure** (populated by `train_mfe_classifier.py`):
```json
{
  "features": ["feature1", "feature2", ...],
  "hyperparameters": {
    "objective": "multi:softprob",
    "num_class": 4,
    "max_depth": 4,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8
  },
  "training_config": {
    "train_samples": 31364,
    "val_samples": 5551,
    "test_samples": 0,
    "feature_version": "v3.1",
    "min_date": "2003-01-01",
    "split_mode": "no_holdout_85_15_0",
    "num_boost_round": 100,
    "early_stopping_rounds": 20,
    "best_iteration": 99,
    "label_thresholds": [0, 2, 10, 30],
    "class_weighting": "balanced",
    "class_weights": {"0": 1.2, "1": 0.9, "2": 1.4, "3": 4.1}
  }
}
```

**Current prod model**: `M01_baseline_v0.1` (status=`prod`). Latest prototype: `m01_prototype_2003_2026_20260506_160054`.

**Artifact layout** (written by `train_mfe_classifier.py`):
```
models/<model_name>/<model_version>/     ← artifacts_path in registry
    model.json                           # XGBoost booster
    metadata.json                        # Training config, feature list, leakage audit
    categorical_mapping.json             # category dtype mappings
    evaluation/
        results.json                     # Accuracy, F1, per-class, feature importance, SHAP
        confusion_matrix.png
        feature_importance.png
        roc_curves.png / pr_curves.png
        calibration_curves.png
        class_distribution.png
        report_*.md
        diffs/                           # model_diff.py output (when --save used)
            vs_<other_version>.json
            vs_<other_version>.txt
```

**CLI:**
```python
from src.model_registry import ModelRegistry
reg = ModelRegistry()
reg.list_versions()                      # All registered models
reg.set_prod('version_id')               # Promote to production
reg.get_model_specs('version_id')        # Load specs_json
reg.get_artifacts_path('version_id')     # Returns Path to artifacts dir
```

**All model artifacts** are under `models/`:
```
models/
    m01_prototype_2003_2026/v1/   # Prototype trained 2003-2026 (first run)
    m01_prototype_2003_2026/v2/   # Prototype trained 2003-2026 (second run, current best)
    m01_baseline/v1/              # Baseline (registered as M01_baseline_v0.1 in prod)
    artifacts/                    # Legacy registered artifacts (mostly empty dirs — pre-P1 fix)
    m03_configs/                  # M03 regime config files
    ablation_study/               # M01 ablation results
    feature_importance_*.csv
    model_report_*.md
```

> **Note on `artifacts_path`**: Before 2026-05-07, the registry auto-generated `models/artifacts/<version_id>/` as `artifacts_path`, creating an empty dir that nothing wrote to. This was fixed (P1) — the trainer now passes `artifacts_path=model_dir` explicitly. Existing pre-fix registrations still point to empty dirs; use filesystem paths directly with `model_diff.py` for those models.

---

## Model Training

**Purpose**: Train M01 MFE classifier on `v_d2_training` data. Not part of the daily pipeline — run periodically or after significant feature changes.

**Current model**: M01 — 4-class XGBoost MFE (Maximum Favorable Excursion) classifier.
- Classes: 0=Noise (0-2%), 1=Moderate (2-10%), 2=Strong (10-30%), 3=Home Run (>30%)
- Features: 105 (8 groups: Moving Averages, Momentum/RS, Volume, Volatility, Oscillators, Fundamentals, Alphas, M03 Regime)
- Baseline metrics: accuracy=67%, weighted_F1=0.58, macro_F1=0.25 (class imbalance)

**Data flow**:
```
v_d2_training (or d2_training_cache)
    → temporal split (train / val / test, chronological)
    → XGBoost multi:softprob, balanced class weights
    → ClassificationEvaluator (artifacts + plots)
    → ModelRegistry.register_version()
    → models/artifacts/<version_id>/
```

**Toolkit:**
| File | Purpose |
|------|---------|
| `scripts/train_mfe_classifier.py` | Main training script. Reads `v_d2_training`, trains, evaluates, registers. |
| `scripts/model_diff.py` | Side-by-side diff of two model versions (see below). |
| `scripts/run_m01_ablation_study.py` | M01 ablation study (target definitions) |
| `scripts/run_m01_phase3_integration.py` | Phase 3: M01+M02 integration & crisis simulation |
| `scripts/run_m01_phase4_deployment.py` | Phase 4: Production deployment |
| `scripts/run_m01_production_calibration.py` | M01 production calibration pipeline |
| `src/evaluation/classification_evaluator.py` | Reusable evaluator (confusion matrix, ROC/PR, SHAP, feature importance) |
| `src/evaluation/leakage_guard.py` | Temporal leakage validation |
| `src/pipeline/m01_trainer.py` | M01 trainer class (used by training scripts) |
| `src/pipeline/m03_regime.py` | M03 regime model computation |

**Training CLI:**
```bash
# Train with standard 60/20/20 split, auto-registers in models table
python scripts/train_mfe_classifier.py

# Train no-holdout (85/15 val only — more data for final model)
python scripts/train_mfe_classifier.py --no-holdout

# Custom feature set, model name, date range
python scripts/train_mfe_classifier.py \
    --feature-set fs_m01_prototype \
    --model-name m01_prototype_2003_2026 \
    --model-version v3 \
    --min-date 2003-01-01
```

**`train_mfe_classifier.py` output** (per run):
- `models/<model_name>/<model_version>/model.json` — trained XGBoost booster
- `models/<model_name>/<model_version>/metadata.json` — split config, features, leakage audit
- `models/<model_name>/<model_version>/evaluation/results.json` — all metrics
- Registry row in `models` table with correct `artifacts_path`

### Model Diff Tool

Compare two model versions side-by-side. Resolves identifiers via DuckDB first, then filesystem path as fallback.

**Sections rendered:**
1. Training Config — split mode, date range, sample sizes, label thresholds, boost rounds
2. Hyperparameters — param-by-param delta table
3. Feature Set Diff — added / removed / shared feature counts
4. Aggregate Metrics — accuracy, F1, brier score deltas
5. Per-Class Metrics — precision / recall / F1 / ROC-AUC per class
6. Feature Importance Rank Shift — top-N features by XGBoost gain rank movement
6b. SHAP Top-5 — top SHAP features per class side-by-side (if available)

```bash
# Compare two filesystem paths (works even for unregistered models)
python scripts/model_diff.py \
    --model-a models/m01_prototype_2003_2026/v1 \
    --model-b models/m01_prototype_2003_2026/v2

# Compare two registered version_ids (DuckDB lookup)
python scripts/model_diff.py \
    --model-a M01_baseline_v0.1 \
    --model-b m01_prototype_2003_2026_20260506_160054

# Save machine-readable JSON + plain-text tables alongside model B's artifacts
python scripts/model_diff.py \
    --model-a models/m01_prototype_2003_2026/v1 \
    --model-b models/m01_prototype_2003_2026/v2 \
    --save --save-text

# Limit rank shift table to top 20 features (default 15)
python scripts/model_diff.py --model-a ... --model-b ... --top-n 20
```

**Save output**: `models/<model_b_path>/diffs/vs_<model_a>.json` (+ `.txt` with `--save-text`)

**Status**: ⚠️ Functional but needs work
- [ ] **Class imbalance** — macro_F1=0.25. Needs SMOTE / threshold tuning / cost-sensitive learning.
- [ ] **Promote to prod** — prototype trained 2026-05-06 is status=test. Run `reg.set_prod(version_id)` after validation.

---

## Evaluation Framework

> Built out 2026-05-23 → 2026-05-24 to deliver the rigour spec in `docs/plans/whitepaper_path_forward_2026_05_23.md` §5. The framework is **operational**: every gate has a script, every script writes a JSON artifact, the trainer can wire them all into one run.

**Philosophy.** A trained model is not "done" until it has passed the gate battery. Each library module returns a JSON-serialisable `dict` containing a `gates` list — every gate has `name`, `status` (`pass`/`fail`/`skipped`), `value`, `threshold`, and `blocking` (bool). Blocking failures block prod promotion via `ModelRegistry.set_prod()`.

**Two layers:**

1. **Built into the trainer** (single command, all gates merged into `results.json`):
   ```powershell
   .\.venv\Scripts\python.exe .\scripts\train_mfe_classifier.py `
     --feature-set fs_m01_prototype `
     --model-name m01_binary --model-version v1 `
     --label-id mfe_binary_homerun_v1 `
     --no-holdout --walk-forward `
     --with-wf-backtest --with-regime-decomp `
     --with-perm-importance --with-calibration
   ```
2. **Deep-rigor scripts** (run post-hoc against an already-trained model, write to `evaluation/full_eval/`):
   - `scripts/run_bootstrap_ci.py` — circular-block bootstrap CI on WF trades (10K iter, ~30 min)
   - `scripts/run_permutation_null.py` — per-date signal shuffle null test (200-1000 perms, ~3 min vectorised)
   - `scripts/run_decile_analysis.py` — Spearman IC + decile bucketing on `prob_elite` vs realised PnL
   - `scripts/ablation_backtest.py` — per-feature-group dropout backtest (~70 min for 9 groups)

### Library modules (`src/evaluation/`)

| Module | Purpose | Tests |
|--------|---------|-------|
| `base_evaluator.py` | `BaseEvaluator` ABC + `_metadata` block (git SHA, label_registry_id, feature_set_id) | `tests/test_base_evaluator_metadata.py` |
| `classification_evaluator.py` | `ClassificationEvaluator` — confusion matrix, ROC/PR, SHAP, permutation importance, top-K lift, calibration ECE, regime decomp, walk-forward integration. Auto-handles binary via `_one_hot()` helper + `_BinaryProbaShim`. | — |
| `label_registry.py` | Pluggable label definitions in `label_registry/*.json` — bins, class names, MFE column. `mfe_binary_homerun_v1` and `mfe_4class_v1` are the active ones. | `tests/test_label_registry.py` |
| `calibrator.py` | `IsotonicCalibrator` — fit on val slice, persist to `calibrator.joblib` + sidecar `.meta.json`, monotone + out-of-bounds clip. Wired via `--with-calibration` trainer flag. | `tests/test_calibrator.py` |
| `calibration.py` | ECE / reliability-diagram primitives (pre-calibrator infra). | `tests/test_calibration.py` |
| `walk_forward.py` | `WalkForwardSplitter` — anchored expanding folds (1Y default), `walk_forward_evaluate()`. Used by `--walk-forward`. | — |
| `walk_forward_backtest.py` | `run_walk_forward_backtest()` + `aggregate_walk_forward_backtest()`. `default_signals_to_scores()` applies calibrator + populates `trailing_pct` from rolling daily ranks. | `tests/test_walk_forward_backtest.py` |
| `bootstrap.py` | `circular_block_bootstrap()` (default block=60d) + helpers (`sharpe_from_trades`, `total_return_from_trades`). | `tests/test_bootstrap.py` |
| `permutation_null.py` | `permutation_null_backtest()` — shuffle signal within each date, recompute metric, return percentile of observed in null. | `tests/test_permutation_null.py` |
| `ablation.py` | Feature-group dropout backtest helpers — drives `scripts/ablation_backtest.py`. | — |
| `regime_decomposition.py` | Per-regime AUC/F1/lift split using `m03_score`-derived regime band. | — |
| `drift.py` | `compute_psi()`, `reference_snapshot()`, `quarterly_drift_report()`. Snapshot written next to each model (`reference_snapshot.json`) at training time; quarterly reports go to `logs/drift/<quarter>.json`. **Library shipped; quarterly wiring deferred.** | `tests/test_drift.py` |
| `pretrain_report.py` | Driver for `scripts/run_pretrain_audit.py` (5+ MB self-contained Plotly HTML embedded in Model Lab). | — |
| `prediction_logger.py` | Logs daily M01 scores to `daily_predictions` table (consumed by dashboard Decision Log). | — |
| `feature_signal.py` | Per-feature signal strength / decay diagnostics. | — |
| `data_quality.py` | Pre-train data audit — fundamentals coverage, null rates, outliers. | — |
| `gate.py` | Shared `Gate` dataclass — every evaluator emits these. | — |
| `html_report.py`, `plotting.py`, `thresholding.py`, `training_data_loader.py`, `leakage_guard.py`, `m03_evaluator.py`, `m03_ground_truth.py`, `classification_report.py` | Supporting infra (plot, report, IO helpers). | — |

### Gate catalogue

Active gates emitted into `results.json` (blocking = blocks prod promotion):

| Gate | Threshold | Source | Blocking |
|------|-----------|--------|----------|
| `calibration_ece` | < 0.05 on production class | `classification_evaluator.py` | yes |
| `calibration_ece_post` | < 0.10 after isotonic | `--with-calibration` | yes |
| `regime_decomposition` | ≥ 3/5 regimes with AUC ≥ 0.55, no catastrophic regime (< 0.50) | `--with-regime-decomp` | yes |
| `walk_forward_worst_auc` | ≥ 0.65 on production class | `--walk-forward` | yes |
| `wf_backtest_mean_sharpe` | > 0.5 | `--with-wf-backtest` | yes |
| `wf_backtest_worst_sharpe` | > -0.3 AND ≥ ceil(N·7/9) positive folds | `--with-wf-backtest` | yes |
| `wf_backtest_worst_max_drawdown` | < 35% | `--with-wf-backtest` | yes |
| `wf_backtest_mean_top_3_home_run_lift` | > 5× | `--with-wf-backtest` | yes |

Non-blocking diagnostics also in `results.json`: `permutation_importance` (top features by mean importance delta), `shap_summary` (top-10 by mean |SHAP|), `temporal_stability` (per-quarter accuracy/F1), `topk_precision` (precision@K and lift for K∈{10,50,100,250,500,1000}), `threshold_sweep` (precision/recall at thresholds 0.3-0.7).

### Label registry

JSON files in `label_registry/` define class binning. Trainer reads via `--label-id`.

```json
// label_registry/mfe_binary_homerun_v1.json
{
  "label_id": "mfe_binary_homerun_v1",
  "mfe_column": "mfe_pct",
  "bins": [30.0],                    // single boundary → binary
  "class_names": ["Not Home Run (<=30%)", "Home Run (>30%)"],
  "production_class": "Home Run (>30%)",
  "horizon_days": null,              // measured over SEPA holding period, not fixed horizon
  "objective": "binary:logistic"
}
```

The trainer derives `num_class`, XGBoost `objective`, class names, and label thresholds from `label_def.bins` — no hardcoded constants. `_BinaryProbaShim` adapts the 1-D binary `predict()` output to the 2-D shape sklearn/SHAP/the evaluator expect.

Active labels:
- `mfe_4class_v1` — Noise (0-2%), Moderate (2-10%), Strong (10-30%), Home Run (>30%). Originally `mfe_4class_30d_v1` — `_30d` suffix dropped because MFE is measured over the SEPA holding period (capped at 120 days for trades still open at EOD), not a fixed 30-day horizon.
- `mfe_binary_homerun_v1` — single boundary at 30% MFE. Used by `m01_binary/v1`.

### Strategy array — head-to-head backtester

`scripts/run_strategy_array.py` runs five `SEPAHybridV1` variants on a single window with one shared scored-universe:

| ID | Description |
|----|-------------|
| S1 | Baseline: top-3 daily, regime caps, default exits |
| S2 | 10-day trailing percentile, up to 5 entries/day, regime caps |
| S3 | Calibrated P(>30%) ≥ 0.30 entry gate, fixed 5-position cap |
| S4 | 20-day trailing percentile + `min_prob_elite=0.25` |
| S5 | Persistence-gated entry (top-30% trailing rank, 3 of last 5 days), fixed 8-position cap, 10-day min hold |

```powershell
.\.venv\Scripts\python.exe .\scripts\run_strategy_array.py `
  --model-name m01_binary --model-version v1 `
  --start 2024-11-01 --end 2026-05-22 `
  --strategies S1,S2,S3,S4,S5 --include-uncalibrated
```

Output per strategy: `models/<m>/<v>/backtests/<S>/{trades.parquet,equity.parquet,metrics.json,config.json}`. Top-level: `comparison.md` (ranked by Sharpe) + `summary.json`. `--include-uncalibrated` runs each strategy twice (with `_raw` suffix), so calibration effect is read directly off the comparison table.

### Deep-rigor scripts (post-hoc, per-model)

These read an already-trained model's WF artifacts. Each writes one JSON next to `model.json` under `evaluation/full_eval/`. Edit the `MODEL_DIR` constant at the top of each script (or pass via env var); they were originally hard-coded to `m01_prototype_may/v2_gated`.

```powershell
# Bootstrap CI on WF trades (10K iter, circular block, default block=60d)
.\.venv\Scripts\python.exe .\scripts\run_bootstrap_ci.py
# → evaluation/full_eval/bootstrap_ci.json: {observed, median, ci_lo_95, ci_hi_95}

# Permutation null on signal (200-1000 perms; vectorised, ~3 min for 200)
.\.venv\Scripts\python.exe .\scripts\run_permutation_null.py
# → evaluation/full_eval/permutation_null.json: {observed_metric, null_median, percentile}
# Gate passes if observed percentile > 95

# Spearman IC + decile bucketing on prob_elite vs realised PnL
.\.venv\Scripts\python.exe .\scripts\run_decile_analysis.py
# → evaluation/full_eval/decile_analysis.json: {decile_stats[], spearman_ic, p_value}

# Per-feature-group ablation (drop one group, retrain, backtest, compare)
.\.venv\Scripts\python.exe .\scripts\ablation_backtest.py `
  --model-name <name> --model-version <ver> `
  --feature-set fs_m01_prototype `
  --feature-groups "Core_Volume,Fundamentals,Momentum_RS,Moving_Averages,Categoricals,M03_Regime,Fast_Alphas,Technical_Oscillators,Volatility_Ranges" `
  --output models\<name>\<ver>\evaluation\full_eval\ablation\
# → evaluation/full_eval/ablation/<group>/{model.json,metadata.json,categorical_mapping.json,metrics.json}
```

**Permutation null performance note.** Initial implementation hung at 18GB memory because `v_d2_training` is a JOIN bomb on `t3_sepa_features` (~9M rows). Rewritten to use `d2_training_cache` (materialised, ~38K rows): runtime dropped from "hangs at 25 min" to ~3 min for 200 perms.

**DuckDB lock surprise.** A running `streamlit run scripts/dashboard.py` holds a write-mode connection and blocks these scripts. Kill it before running:
```powershell
Get-Process python | Where-Object { $_.CommandLine -like "*streamlit*" } | Stop-Process
```

### Feature catalog & pruned sets

The `model_feature_sets` table in DuckDB is keyed by `feature_set_id` and tags each feature with a `feature_group`. Trainer reads dynamically via `--feature-set`.

Current sets (registered by `scripts/populate_feature_catalog.py`):
- `fs_m01_baseline` — original 106 features (used by `M01_baseline_v0.1`)
- `fs_m01_prototype` — 97 features (baseline minus REMOVED, plus PROTOTYPE_ADDED)

To register a pruned set (e.g., for the §1.4(c) drop-Volatility/Oscillators experiment), insert rows directly:

```python
# scripts/register_pruned_feature_set.py (write this when needed)
import duckdb
con = duckdb.connect("data/market_data.duckdb")
con.execute("DELETE FROM model_feature_sets WHERE feature_set_id = 'fs_m01_prototype_pruned'")
rows = con.execute("""
  SELECT feature_name, feature_group FROM model_feature_sets
  WHERE feature_set_id = 'fs_m01_prototype'
    AND feature_group NOT IN ('Volatility_Ranges', 'Technical_Oscillators')
  ORDER BY ordinal
""").fetchall()
con.executemany(
  "INSERT INTO model_feature_sets (feature_set_id, feature_name, feature_group, ordinal) VALUES (?, ?, ?, ?)",
  [("fs_m01_prototype_pruned", n, g, i) for i, (n, g) in enumerate(rows)],
)
```

Then train with `--feature-set fs_m01_prototype_pruned --model-version v2`.

### Where output lands

Every trained-model directory now contains:
```
models/<name>/<version>/
    model.json                       # XGBoost booster
    metadata.json                    # Features, split config, leakage audit
    categorical_mapping.json         # sector/industry → category code
    label_definition.json            # Snapshot of label_registry entry used
    calibrator.joblib                # Isotonic calibrator (if --with-calibration)
    calibrator.meta.json             # Calibrator metadata (pre/post ECE, fit samples)
    reference_snapshot.json          # PSI baseline bin edges + counts (frozen at promotion)
    pretrain_audit.html              # Self-contained Plotly audit (if --with-pretrain-audit)
    folds/fold_<idx>/                # WF fold artifacts (model.json, metrics.json, spec.json)
    wf_backtest/fold_<idx>/          # WF backtest per-fold trades/equity/metrics
    wf_backtest/summary.json         # Aggregated WF backtest gates
    backtests/<S>/                   # Strategy array runs (if run_strategy_array.py invoked)
    backtests/comparison.md          # Strategy array ranking
    evaluation/
        results.json                 # All gates + metrics + SHAP + permutation
        report_<timestamp>.md        # Human-readable summary per training run
        walk_forward_summary.json    # Per-fold WF metrics aggregate
        confusion_matrix.png, roc_curves.png, etc.
        full_eval/                   # Deep-rigor (post-hoc) outputs — populated manually
            bootstrap_ci.json
            permutation_null.json
            decile_analysis.json
            ablation/<group>/...
            full_eval_report.md      # One-pager DEMOTE/HOLD/PROMOTE verdict
```

### Production class definition

Each label registry entry declares `production_class`. The evaluator's blocking gates (calibration, regime AUC, top-3 lift) are computed *for that class only*. Binary `production_class = "Home Run (>30%)"` → `_default_actionable_classes()` returns `[1]` (binary); multi-class `production_class = "Home Run (>30%)"` → returns `[3]` (the last bin in 4-class).

### Outstanding operational items

- [ ] **Quarterly drift report wiring.** `drift.py` library shipped + tested; the Phase-9 hook in `daily_pipeline_orchestrator.py` that fires on the 1st of Jan/Apr/Jul/Oct is not yet built. See `docs/plans/evaluation_remaining_implementation_plan_2026_05_24.md` §2.2 step 3.
- [ ] **Backfill historical `daily_predictions`.** Phase 8 prediction logger was silently broken until 2026-05-24; the `daily_predictions` table is empty for the historical period of the prod model. `scripts/backfill_daily_predictions.py` not yet written. See plan §3.2.
- [ ] **Deep-rigor scripts hard-code `MODEL_DIR`.** Add `--model-dir` argument to `run_bootstrap_ci.py`, `run_permutation_null.py`, `run_decile_analysis.py` so they don't need an edit-per-model. Trivial change.
- [ ] **Lazy `src/evaluation/__init__.py`.** Eager re-exports trigger `m03_evaluator → macro_engine → yfinance` import chain → ~25 min pytest cold start on Windows + Defender. See plan §3.1.

---

## Backtesting

**Purpose**: Simulate the SEPA strategy historically using BackTrader. Not part of the daily pipeline — run on-demand.

**Strategy**: `SEPAHybridV1` — M01 score-based selection + M03 regime gating + 3-tranche exit with trailing stops.

**Data flow (DuckDB — default)**:
```
d2_training_cache                   → UniverseScorer.score_from_duckdb() → M01 scoring (vectorized)
t2_regime_scores                    → regime feed (regime_cat 0-4 from m03_score thresholds: <20 strong_bear, <40 bear, <60 neutral, <80 bull, >=80 strong_bull — defaults in src/pipeline/m03_regime.py)
price_data                          → OHLCV feeds + inline ATR-14
    → SEPABacktestRunner.setup_from_duckdb() + run()
    → report + equity curve + trade log
```

**Data flow (legacy parquet — `--full` / `--run`)**:
```
prepare_regime_feed()     → data/backtest/m03_feed.parquet
UniverseScorer.score()    → data/backtest/universe_scores.parquet    ← reads data/ml/d2.parquet
prepare_price_feeds()     → data/backtest/prices/*.parquet
    → SEPABacktestRunner.setup() + run()
    → report + equity curve + trade log
```

**Toolkit:**
| File | Purpose |
|------|---------|
| `scripts/run_backtest.py` | CLI entrypoint (`--duckdb` default, `--full`/`--run` legacy) |
| `scripts/backtest_optimization.py` | Hyperparameter optimization for backtest |
| `src/backtest/runner.py` | `SEPABacktestRunner` |
| `src/backtest/sepa_strategy.py` | `SEPAHybridV1` BackTrader strategy |
| `src/backtest/universe_scorer.py` | `UniverseScorer` — `score_from_duckdb()` or `score_universe()` |
| `src/backtest/score_lookup.py` | `ScoreLookup` — in-memory O(1) daily candidate filtering |
| `src/backtest/position_tracker.py` | `PositionTracker` — 3-tranche exits |
| `src/backtest/report.py` | Post-backtest markdown report generation |
| `src/backtest/analyzers.py` | Custom BackTrader analyzers (CalmarRatio) |
| `src/backtest/feeds.py` | `SEPAStockFeed`, `M03RegimeFeed` |
| `src/backtest/price_feed.py` | Legacy parquet-based price feed |
| `src/backtest/duckdb_feed.py` | `DuckDBCandidateFeed` — **do NOT delete** (imported by `backtest_optimization.py`) |

**CLI:**
```bash
python scripts/run_backtest.py                                 # DuckDB mode (default)
python scripts/run_backtest.py --duckdb --model m01_baseline/v1
python scripts/run_backtest.py --duckdb --max-tickers 50       # Quick test
python scripts/run_backtest.py --duckdb --start 2021-01-01 --end 2023-12-31
python scripts/run_backtest.py --full                          # Legacy: prepare parquet + run
```

**Output**: `data/backtest/` — reports, equity curves, trade logs.

---

## Dashboard

**Purpose**: Multi-page Streamlit UI to expose pipeline output. Localhost-only, single-user, no auth. Never bind to `0.0.0.0`.

**Run:** `streamlit run scripts/dashboard.py`  → opens at http://localhost:8501

**Plan / spec:** `docs/plans/dashboard_implementation_plan_2026_05_23.md`. The dashboard's philosophy is *expose existing work, do not recompute*: DuckDB tables + registered models + pre-generated HTML reports are the canonical artifacts; pages render them.

### Page map (MVP — 2026-05-23)

| # | Page | File | Purpose |
|---|------|------|---------|
| 1 | Today | `scripts/dashboard.py` (`page_today`) | Default landing — M03 + 5F regime cards, screener watchlist with M01 probabilities, pre-breakout cohort, sector heat, analytics |
| — | Feature Time Series | `scripts/pages/1_Feature_Time_Series.py` | Pre-existing per-ticker chart page (kept; rename pending Page 2 build) |
| 3 | Model Lab | `scripts/pages/3_Model_Lab.py` | Registry browser — read-only; embeds pretrain HTML, PNG plots, report MD, specs JSON, diff |
| 4 | Backtest Studio | `scripts/pages/4_Backtest_Studio.py` | Browse v1 backtest runs — equity / DD / per-year / per-regime / trade table / 2-run compare |
| 5 | Pipeline Health | `scripts/pages/5_Pipeline_Health.py` | Ops view — runs heatmap, freshness, universe trend, audit history, storage |

Page 2 (Ticker Deep Dive) is specified in the plan §Page 2 but not yet built.

### Page 1 — Today

Sections, in order:

1. **Pipeline status bar** — `pipeline_runs` latest row (icon + phase + timestamp).
2. **Regime cards (side-by-side)** —
   - **M03** (left): composite score, label band (Strong Bull / Bull / Neutral / Bear / Strong Bear), 3 pillar metrics with formula tooltips. Source: `t2_regime_scores`.
   - **5F** (right): `target_exposure` mapped to band label (Full / Reduced / Cautious / Defensive / Heavy Defensive / Veto), worst factor with σ, weighted z, expander for all 5 z-scores. Source: `t2_risk_scores`.
3. **Screener Watchlist** — filterable (status / sector / date range / ticker) inside an `st.form` so typing doesn't retrigger the page. Default sort: Entry Date desc. Other sorts: P(HR), P(Strong+HR), Return %, Days Held. Columns: ticker / company / sector / entry date / entry $ / price $ / return % / days / M01 class / all 4 P(class) / status.
4. **Pre-Breakout Watch** — `trend_ok=TRUE AND breakout_ok=FALSE` cohort joined to t3 features and **live-scored by prod M01**. Sort: P(HR) desc. Shows close, dist-from-20d-high, vol ratio, VCP, days_in_setup, class + probs.
5. **Sector Heat** — bar chart of `trend_ok` + `breakout_ok` counts per sector, with window selector (Today / 5d avg / 20d avg). ETF pseudo-sectors filtered. Y-axis floored at 150, `cliponaxis=False`.
6. **Analytics** —
   - Quick stats: active count, avg return active, win rate exited, avg holding period.
   - **Days Held × Return scatter** with 4 quadrants (Hot / Mature / Young / Aging) split at 60d × 5%. Tickers labeled on points. Expander below lets you filter by quadrant and see the ticker list.
   - Active sector concentration: single-color bar chart.
   - Exited-trade return distribution (symlog histogram).

**M01 class taxonomy** (used everywhere): 4-class XGBoost MFE classifier (`multi:softprob`).
- 0 Noise (0–2%), 1 Moderate (2–10%), 2 Strong (10–30%), 3 Home Run (>30%).

**Data flow for the screener table:** `screener_watchlist` (active rows) → joined to latest `v_d3_deployment` by ticker → `score_features_df` → 4-class probabilities + class label.

### Page 3 — Model Lab

Registry list (`models` table) with status / feature-version filters. Selecting a row opens 6 tabs:

| Tab | Source | Notes |
|---|---|---|
| Overview | `models` row | Metric cards + artifact path diagnostic |
| Pretrain Report (HTML) | most recent `docs/reports/pretrain_audit_*.html` | Iframed via `st.components.v1.html`. Self-contained (Plotly inlined). **Not version-pinned to the selected model yet** — see plan Open Q #5. |
| Plots | `<artifacts_path>/evaluation/*.png` | `st.image` per PNG. Only the prod model (`m01_prototype_2003_2026/v2/`) has populated artifacts today; older rows render a "no artifacts" warning. |
| Report (MD) | `<artifacts_path>/evaluation/report_*.md` | Newest first |
| Specs | `specs_json` from registry row | Pretty-printed JSON viewer |
| Diff | `<artifacts_path>/diffs/*.txt` if present | Otherwise: placeholder with CLI hint (`python scripts/model_diff.py <A> <B>`). Subprocess wiring deferred. |

**Read-only.** No "Promote to prod" / "Archive" buttons in v1 — promotion remains `ModelRegistry().set_prod(version_id)` from a shell.

### Page 4 — Backtest Studio

Scans `data/backtest/*/manifest.json` and **shows only runs with `manifest_version == "v1"`**. Stale runs (pre-2026-05-23 schema, or hand-named experimental dirs) remain on disk but are silently hidden.

Per run:
- 4 metric cards (total return, Sharpe, max DD, trades) + model version + window.
- Equity curve (NAV from start=1.0).
- Drawdown chart with max-DD annotation.
- Per-year breakdown (trades, avg/median PnL, win rate).
- Per-regime breakdown (trades, avg PnL, win rate) using `entry_regime`.
- Trade table with outcome / sector / exit_reason filters.
- 2-run compare: overlay equity curves (absolute date OR days-from-start axis) + side-by-side summary.

Manifest schema (v1), written by `src/backtest/runner.py:_build_manifest`:
```json
{
  "manifest_version": "v1",
  "run_id": "...",
  "created_at": "...",
  "model": {"name": "...", "version_id": "...", "path": "models/.../model.json"},
  "params": {"start_date": "...", "end_date": "...", "initial_cash": 100000, ...},
  "summary_metrics": {"total_return": ..., "sharpe_ratio": ..., ...}
}
```

`model.version_id` is resolved from `models.artifacts_path` when the on-disk model dir is registered; otherwise it falls back to `<name>/<version-dir>` (e.g. `m01_prototype_2003_2026/v1`).

### Page 5 — Pipeline Health

- **Runs heatmap (last 30d)** — `pipeline_runs` pivoted to phase × date. Cells colored success (green) / running (yellow) / failed (red); hover shows runtime + error message. Failed runs in window are expanded in a drill-down panel.
- **Data freshness** — `MAX(date)` per key table + lag-day status badge (🟢 fresh / 🟡 stale / 🔴 very stale). Per-table tolerances configured in `FRESHNESS_TOLERANCE_DAYS`.
- **Universe & breakout trend (60d)** — daily counts of `trend_ok` and `breakout_ok` from `t2_screener_features`.
- **Audit history** — scans `data/audit_reports/audit_report_*.json` and plots pass/warn/fail counts. **Currently single point** (only 2026-03-28 on disk); a "history accumulating" banner shows when there's ≤ 1 file.
- **Storage** — file sizes for the DuckDB DB, `models/`, `data/backtest/`, `docs/reports/`, `logs/`.

### Toolkit

| File | Purpose |
|------|---------|
| `scripts/dashboard.py` | Page 1 entrypoint + `st.navigation` wiring |
| `scripts/dashboard_utils.py` | Shared loaders (`load_regime`, `load_risk_5f`, `load_watchlist`, `load_pre_breakout`, `load_sector_heat(window_days)`, `load_data_freshness`, `load_pipeline_runs_window`, `load_universe_trend`, `load_models_table`, `load_prod_model`), constants (`CLASS_LABELS`, `EXPOSURE_BANDS`, `PILLAR_FORMULAS`), helpers (`classify_regime`, `exposure_band_label`, `score_features_df`) |
| `scripts/pages/3_Model_Lab.py` | Model registry browser |
| `scripts/pages/4_Backtest_Studio.py` | v1-manifest backtest viewer |
| `scripts/pages/5_Pipeline_Health.py` | Ops dashboard |
| `models/m01_prototype_2003_2026/v2/model.json` | Current prod XGBoost classifier (auto-discovered via `status_flag='prod'`) |
| `docs/reports/pretrain_audit_*.html` | Pre-generated pretrain HTML reports — Model Lab iframes the newest |

### Generating a fresh pretrain HTML report

```bash
python scripts/run_pretrain_audit.py --mode trades
# writes docs/reports/pretrain_audit_trades_<timestamp>.html (5+ MB, Plotly inlined)
```

Model Lab's "Pretrain Report (HTML)" tab picks up the newest file by mtime.

### Streamlit gotchas (learned 2026-05-23)
- **Page rerun is whole-page, not component-local.** Filter controls above an
  expensive widget should be wrapped in `st.form(...)` so the rerun only fires
  on submit. Was making Page 1's search box feel laggy (each keystroke re-ran
  M01 `predict_proba` on the pre-breakout cohort).
- **`@st.cache_data(ttl=300)`** on every read-path loader in `dashboard_utils.py`.
  `@st.cache_resource` for the XGBoost model.
- **Page-1 pre-breakout cohort scoring is live**, not cached to a snapshot
  table. ~50 tickers, acceptable for MVP. If load gets painful, the plan's
  `dashboard_snapshot` table (deferred) is the lever.
- **Lookback windows: use `LIMIT N` on DISTINCT dates**, not `INTERVAL N DAY`.
  The latter counts calendar days incl. weekends, so 1-day windows after a
  Monday return Friday+Monday. See `load_sector_heat`.
- **5F `EXPOSURE_BANDS` mirrored.** Duplicated between
  `src/pipeline/risk_5_factor.py` and `scripts/dashboard_utils.py` rather than
  imported, to avoid a `src.*` import chain inside Streamlit's hot reload. Keep
  both in sync if bands change.

---

## Cache & Report Locations

```
data/market_data.duckdb        Primary DuckDB database (all tables + views)
data/audit_reports/            Audit JSON reports — audit_report_YYYYMMDD.json
data/backtest/                 Backtest results, equity curves, trade logs
data/ml/                       ML artifacts (d2.parquet, predictions, scores)
data/evaluation/               Model evaluation results
data/fundamentals/             Historical fundamentals cache (parquet, legacy)
data/earnings/                 Earnings calendar cache
data/macro/                    Macro data (FRED series)
data/company_info/             Company profiles metadata
data/delisted_tickers.json     Inactive ticker list (legacy)
data/data_health_report.json   Data quality health metrics snapshot

logs/daily_pipeline.log        Daily pipeline execution log
logs/data_quality/YYYY-MM.log  Post-retry data quality failures (monthly)
logs/screener_membership_backfill_checkpoint.json  Backfill resume state

models/artifacts/              Registered model artifacts (timestamped)
models/m01_baseline/           Working model copy (used by backtest --model flag)
models/model_report_*.md       Timestamped evaluation reports
models/feature_importance_*.csv
```

**Where the daily pipeline logs**:
- Execution: `logs/daily_pipeline.log`
- Data quality failures: `logs/data_quality/YYYY-MM.log`
- Phase tracking: `pipeline_runs` table in DuckDB

### Tailing logs (live)

The PowerShell idiom `Get-Content <file> -Wait -Tail 5` follows a file as it grows. Equivalents:

| Shell | Command |
|-------|---------|
| Git Bash / WSL / Linux | `tail -f -n 5 logs/t3_backfill_progress.log` |
| PowerShell | `Get-Content logs\t3_backfill_progress.log -Wait -Tail 5` |
| cmd.exe | (no built-in equivalent — use Git Bash or PowerShell) |

Common log files worth tailing:
```bash
tail -f -n 5 logs/daily_pipeline.log              # daily pipeline run
tail -f -n 5 logs/t3_backfill_progress.log        # T3 backfill progress
tail -f -n 5 logs/data_quality/$(date +%Y-%m).log # this month's data-quality failures
```

To stop following: Ctrl+C.

---

## Open TODOs

### Model Development (blocking backtests from being meaningful)
- [ done ] **Retrain M01 on updated T3 data** — current model trained on 2026-03-15. T3 was rebuilt 2026-03-27 with 0% NULL alphas/EMAs. Retrain + compare metrics. [m01_prototype_may]
- [ ] **Class imbalance** — macro_F1=0.25. Try SMOTE, cost-sensitive learning, or threshold tuning.
- [ ] **Promote to prod** — currently `status=test`. Run `reg.set_prod(version_id)` after validation backtest.
- [ ] **Full backtest** — run `--duckdb` on full date range (2020-2026) with all tickers to establish baseline.

### Data Quality (non-blocking but should fix)
- [ done ] **`filing_date` anomalies** — run the two patch modes to clean up remaining ~55K zero-day rows and ~6.4K stale-historical rows:
  ```bash
  python tools/patch_fundamentals.py --fix filing_date_zero --dry-run   # preview
  python tools/patch_fundamentals.py --fix filing_date_zero              # ~55K rows
  python tools/patch_fundamentals.py --fix filing_date_stale_historical  # ~6.4K rows
  ```
- [ ] **GE price_data + fundamentals** — GE restored to `company_profiles` (2026-03-28) but has no price_data or fundamentals yet. Will auto-fetch on next daily pipeline run.
- [ ] **Monthly earnings calendar refresh trigger** — where to persist last-refresh timestamp (defer until pipeline automated)

### Evaluation Framework (operational follow-ups)
- [ ] **Wire quarterly drift reports into Phase 8** — `src/evaluation/drift.py` shipped 2026-05-24 with tests, but no cron-style trigger yet. See plan §2.2 step 3.
- [ ] **Backfill `daily_predictions`** for prod-model historical period — Phase-8 prediction logger was silently broken pre-2026-05-24. Empty table → dashboard "Past Decisions" view is empty.
- [ ] **Parameterise deep-rigor scripts** — `run_bootstrap_ci.py` / `run_permutation_null.py` / `run_decile_analysis.py` hard-code `MODEL_DIR`; add a `--model-dir` arg.
- [ ] **Run full §1.4 deep-rigor on `m01_binary/v1`** — verdict not yet recorded. Trainer gates ran, but bootstrap CI / permutation null / decile analysis still to do. See plan §1.4 and the §1.4(c) parallel-session instructions for the template.

### Critical Next Stage:
- [ ] **Run one-time T3 backfill on Option C universe** — `sepa_watchlist` is populated (35,560 sessions / 2,697 tickers, done 2026-05-08). T3 schema rebuilt empty. Run:
  ```bash
  python scripts/backfill_t3_sepa_features.py --restart --from 2001-Q1
  # then:
  python scripts/create_duckdb_views.py
  python scripts/refresh_training_cache.py
  ```
  Expected: ~9.4M rows, 1.5-2.5h. Tail: `tail -f -n 5 logs/t3_backfill_progress.log`. See `docs/session_logs/2026-05-08_wrapup.md` for full guidance.
- [ ] **Re-train M01 sanity check** after T3 backfill completes — feature *values* unchanged (fundamentals still reach model via `v_d2_features` JOIN), but verify metrics match `M01_baseline_v0.1` (acc=0.6705, wF1=0.582, macroF1=0.248) within ±0.005. Drift = bug.
- [ ] Finalise notebook to prototype model. This should include EDA, Feature Engineering, model training (with class imbalance), Model evaluation. Then replicate to prod code and create a new model for registry.
- [ ] Dashboard Phase 2: data audit, model eval, backtest results, feature time-series pages. See `docs/dashboard_design.md`.

---

## Resolved

- ~~Backtest parquet dependency~~ → DuckDB-native (2026-03-27)
- ~~Universe discovery~~ → `--discover-fmp` via `UniverseBackfillEngine`
- ~~Historical fundamentals backfill~~ → FMP backfill complete (297K rows)
- ~~Blacklist / SPAC contamination~~ → `ticker_blacklist` table
- ~~`daily_features` table~~ → **DROPPED** (2026-03-24). T2 + T3 replace it.
- ~~T2 missing OHLCV~~ → Added 2026-03-26. OHLCV now stored directly + backfilled.
- ~~T2 missing EMAs~~ → Added 2026-03-26. EMA 8/21/50/100/200 via pandas ewm.
- ~~No T3 audit~~ → `tools/audit_t3_sepa_features.py` created 2026-03-26.
- ~~No Phase 3/4 incremental CLI~~ → `--phase-3-only`, `--phase-4-only` added 2026-03-26.
- ~~T3 full rebuild needed~~ → Rebuilt from T2 (2026-03-27). 41K rows, 0% NULL on XS alphas/EMAs.
- ~~T3 views referencing `trend_ok`~~ → Views now use T2 for session detection, T3 for features (2026-03-27).
- ~~No Phase 5 incremental CLI~~ → `--phase-5-only` added 2026-03-27.
- ~~`dist_from_52w_high_pct_chg` 41% NULL~~ → Zero-denominator fix (2026-03-27).
- ~~Model registry stale entries~~ → Cleaned up (2026-03-27). Canonical: `M01_baseline_20260315_133129`.
- ~~`screener_watchlist` materialisation~~ → Added (2026-03-27). ~42K rows, refreshed in Phase 6.
- ~~Partial ingestion silently drops tickers~~ → Coverage health check added (2026-03-28). Fixed 938 missing tickers on 3/27.
- ~~No per-ticker SEPA diagnostic~~ → `scripts/diagnose_ticker.py` added (2026-03-28).
- ~~Audit warnings inflated by expected data patterns~~ → 19→11 warnings (2026-03-28 session 2):
  - T1 `missing_from_cp` now counts active tickers only; `orphan_tickers` excludes warrants/preferred/rights
  - T2 `active_tickers_no_recent_price` now excludes `cp.is_active=FALSE` tickers
  - T2 screener RS/rank null checks downgrade to INFO when all nulls are within warmup window
  - `patch_fundamentals.py` extended with `filing_date_zero` and `filing_date_stale_historical` modes
  - GE Aerospace ($298B) restored to `company_profiles` as active
  - 167 orphan regular equity tickers purged from T1 tables
  - 27 screener_membership exit events injected for cp.is_active=FALSE tickers
- ~~`screener_members` view~~ → Dropped; `screener_membership` is the source of truth (2026-03-28).
- ~~`rename_tickers.py` referencing dropped tables~~ → Updated to use `screener_membership` (2026-03-28).
- ~~Dashboard Phase 1~~ → `scripts/dashboard.py` — screener watchlist + M01 4-class scoring + M03 regime header + analytics (2026-03-29).
- ~~No model comparison tool~~ → `scripts/model_diff.py` — 7-section CLI diff (training config, hyperparams, feature diff, aggregate metrics, per-class, FI rank shift, SHAP) with `--save`/`--save-text` flags (2026-05-07).
- ~~Registry `artifacts_path` pointed to empty dirs~~ → P1 fix: `register_version()` now accepts `artifacts_path` param; trainer passes `model_dir` explicitly (2026-05-07).
- ~~`specs_json` missing training config fields~~ → P2: added `num_boost_round`, `early_stopping_rounds`, `best_iteration`, `label_thresholds`, `class_weighting`, `class_weights` (2026-05-07).
- ~~No `model_name`/`model_version` columns in `models` table~~ → P4: idempotent migration added + backfilled existing rows by parsing `version_id` timestamp suffix (2026-05-07).
- ~~T3 ≈ T2 (Option B universe gate produced ~70% non-SEPA noise)~~ → **Option C: `sepa_watchlist` event log + Phase 4b** (2026-05-08). T3 universe = tickers that ever entered a SEPA session, full history. New `SepaWatchlistManager` (backfill + daily incremental). Fundamentals (4 cols) removed from T3 schema — joined at query time in `v_d2_features` instead. `EXPECTED_T3_COLUMN_COUNT`: 148 → 144. Backfill `sepa_watchlist`: 35,560 sessions / 2,697 tickers in 6.8s. T3 backfill on new design pending (see Open TODOs). Wrap-up: `docs/session_logs/2026-05-08_wrapup.md`.
- ~~T3 per-quarter wall-time grew O(cumulative history)~~ → Date-bound `candidates` CTE (`AND p.date <= '{end_date}'`) + scoped `with_velocity` t2 join (`AND t2.date BETWEEN '{fetch_start}' AND '{end_date}'`) (2026-05-08, morning session). Per-quarter wall time now flat.
- ~~Evaluation framework was a wishlist~~ → **§5 of whitepaper now operational** (2026-05-23 → 2026-05-24). Library modules in `src/evaluation/`: `bootstrap`, `permutation_null`, `walk_forward_backtest`, `regime_decomposition`, `calibrator` (isotonic), `drift` (PSI), `ablation`. Wired into trainer via `--with-wf-backtest`, `--with-regime-decomp`, `--with-perm-importance`, `--with-calibration`. 8 blocking gates in `results.json` per model. Deep-rigor scripts (`run_bootstrap_ci.py`, `run_permutation_null.py`, `run_decile_analysis.py`, `ablation_backtest.py`) populate `evaluation/full_eval/`. See `## Evaluation Framework` above.
- ~~`v_d2_features` fan-out bug~~ → Fixed 2026-05-24 (`QUALIFY ROW_NUMBER()` dedup on `fundamental_features` + `shares_history`). Trainer now passes `feature_parity_check` without `--skip-parity`. Commit `cca85e9`.
- ~~Label thresholds hardcoded in trainer~~ → Replaced 2026-05-24 with `label_registry/*.json` pluggable definitions. Trainer derives `num_class`, XGBoost `objective`, class names, label boundaries from `label_def.bins`. `mfe_4class_v1` and `mfe_binary_homerun_v1` are the active labels. Binary objective handled via `_BinaryProbaShim` + `_one_hot()` evaluator helpers.
- ~~`SEPAHybridV1` had no min-hold / persistence params, latent bugs in `_check_rank_exits`~~ → Added `min_hold_days`, `persistence_window_days`, `persistence_min_count`, `persistence_threshold` (2026-05-24). Fixed two latent bugs: `.get('trailing_10d_pct')` on a tuple + swapped args to `get_score`. `ScoreLookup.check_persistence()` added with 6 unit tests. `SEPABacktestRunner.setup()` now accepts `strategy_kwargs`. Used by S5 in the strategy array.
- ~~`UniverseScorer` crashed on binary objective~~ → Binary detection added 2026-05-24 (`'binary' in objective`), 1-D proba handling, binary-appropriate MFE midpoints `[3, 70]`. Auto-loads `calibrator.joblib` adjacent to `model.json` if present.
- ~~`default_signals_to_scores` left `trailing_pct` as NaN~~ → Populated 2026-05-24 from rolling daily ranks. Was breaking `rank_by='trailing'` in WF backtest and Strategy Array S2/S4.
