# Mid-Sprint 6 Pipeline Assessment (2026-03-21)

## Entry Point
`scripts/run_daily_pipeline.py` → `DailyPipelineOrchestrator` → 9-phase daily pipeline

## Overall Status: Production-Ready (with caveats)

All 9 phases are fully implemented. No stubs, no unimplemented methods. The pipeline
can be run daily as-is.

---

## Phase-by-Phase Sequence

```
run_daily_pipeline.py
  └── DailyPipelineOrchestrator.run_pipeline(target_date)
        ├── Trading day resolution (SPY lookup via yfinance)
        ├── Phase 1.1  Quarterly Universe Refresh [OPTIONAL, every 90d]
        ├── Phase 1    T1 Ingestion [PARALLEL, 4 threads]
        │     ├── 1.1 Price   — DataRepository → price_data (stale tickers only)
        │     ├── 1.2 Funds   — FundamentalEngine → fundamentals
        │     ├── 1.3 Shares  — SharesEngine → shares_outstanding
        │     └── 1.4 Macro   — MacroEngine → macro_data (FRED + VIX)
        ├── Phase 2    Screener Membership [HALT] → screener_members
        ├── Phase 3    T2 Screener Features [HALT] → t2_screener_features (30 cols)
        ├── Phase 4    T2 Regime Scores [WARN] → t2_regime_scores
        ├── Phase 5    daily_features Rebuild [HALT] → daily_features (149 cols)
        │     ├── Phase A: 79 base features via SQL CTEs     (~10s)
        │     ├── Phase B: 16 WQ101 alphas via multiprocessing (~50s)
        │     ├── Phase C: 7 cross-sectional ranks via SQL    (~2s)
        │     ├── Phase D: M03 regime scores joined in
        │     └── Phase E: M03 derived features (deltas, vol)
        ├── Phase 6    T3 Lazy Materialization [WARN] → t3_sepa_features
        ├── Phase 7    View Refresh [WARN] → 8 views + 2 aliases
        ├── Phase 8    Training Cache Refresh [WARN] → d2_training_cache
        └── Phase 9    Monitoring [ALWAYS] → alerts, health report
```

**Failure modes**: HALT = stops pipeline. WARN = logs warning, continues. SKIP = continues silently.

---

## Parquet Status

Production data path is **fully DuckDB** for:
- `price_data` — DataRepository (yfinance → DuckDB)
- `fundamentals` — FundamentalEngine (yfinance → DuckDB)
- `shares_outstanding` — SharesEngine (DuckDB)
- `macro_data` — MacroEngine (DuckDB)
- `daily_features`, `t3_sepa_features` — FeaturePipeline (DuckDB)

**Remaining parquet caches** (intentional, non-blocking):

| File | Purpose | Migration Priority |
|------|---------|--------------------|
| `src/company_profile_engine.py` | Profiles, industry/sector mapping | Low (lightweight cache) |
| `src/earnings_engine.py` | Earnings calendar per ticker | Low (used for smart scheduling) |
| `src/macro_engine.py` | FRED/VIX series cache | Low (lightweight) |
| `src/fundamental_engine.py` | Legacy FMP path (not production) | None (dead path) |
| `src/data_engine.py` | yfinance write-fail fallback | None (error recovery only) |
| Backtest outputs | Trade logs, equity curve exports | None (output artifacts) |

---

## Issues Found

### 1. Incremental Mode is a No-Op (Medium)
**File**: [src/feature_pipeline.py:265-273](../../../src/feature_pipeline.py)

`_compute_incremental()` logs "EXPERIMENTAL" and immediately calls `_compute_full_rebuild()`.
Every daily run rebuilds all 2.6M rows (~70-90s) instead of just the new day (~10-20s).

**Impact**: Pipeline is slower than necessary daily. No correctness issue.

**Fix estimate**: 6-9 hours (documented in memory as deferred).

---

### 2. Phase 5 Transaction Wrapper is Ineffective (Medium)
**File**: [src/orchestrators/daily_pipeline_orchestrator.py:578-599](../../../src/orchestrators/daily_pipeline_orchestrator.py)

The orchestrator opens a DuckDB connection, calls `BEGIN TRANSACTION`, then delegates to
`FeaturePipeline.compute_all()` which opens **its own separate connection**. The transaction
wraps an empty block.

```python
conn.execute("BEGIN TRANSACTION")   # conn A
rows = self.feature_pipeline.compute_all(...)  # uses conn B internally
conn.execute("COMMIT")              # commits nothing on conn A
```

`CREATE OR REPLACE TABLE` in Phase A is atomic by itself, so correctness is preserved.
But partial failures in Phases B-E (alphas, ranks) will not roll back Phase A.

**Fix**: Either pass `conn` into `compute_all()`, or remove the transaction wrapper and
rely on `CREATE OR REPLACE TABLE` atomicity.

---

### 3. No `logs/` Directory Auto-Creation (Low)
**File**: [scripts/run_daily_pipeline.py:28](../../../scripts/run_daily_pipeline.py)

`FileHandler("logs/daily_pipeline.log")` crashes if `logs/` doesn't exist. First-run
blocker on a fresh clone.

**Fix**: Add `Path("logs").mkdir(exist_ok=True)` before `logging.basicConfig()`.

---

### 4. Quarterly Refresh Heuristic is Fragile (Low)
**File**: [src/orchestrators/daily_pipeline_orchestrator.py:398-411](../../../src/orchestrators/daily_pipeline_orchestrator.py)

Uses `MAX(created_at) FROM company_profiles` as a proxy for "last quarterly refresh date".
This will always be recent (profiles updated frequently) → quarterly refresh never fires.

**Fix**: Store last refresh timestamp in a dedicated `pipeline_metadata` table.

---

### 5. No Market-Closed Guard (Low)

Running on a weekend/holiday resolves to the prior Friday via SPY lookup, finds no new
data delta, and skips Phase 5. Correct outcome, but still burns API quota on Phase 1
ingestion needlessly.

---

## Recommended Actions Before Regular Daily Use

Priority order:

1. **Fix `logs/` creation** — one-liner, blocks first run on fresh environment
2. **Fix Phase 5 transaction** — remove dead wrapper or pass connection through
3. **Fix quarterly refresh heuristic** — add `pipeline_metadata` table
4. **Implement true incremental Phase 5** — major effort, defer unless daily runtime is unacceptable

---

## DuckDB Tables (Source of Truth)

| Table | Writer | Consumer |
|-------|--------|----------|
| `company_profiles` | CompanyProfileEngine | All engines (ticker universe) |
| `price_data` | DataRepository | FeaturePipeline |
| `fundamentals` | FundamentalEngine | FeaturePipeline |
| `shares_outstanding` | SharesEngine | FeaturePipeline |
| `macro_data` | MacroEngine | RegimePipeline |
| `screener_members` | ScreenerManager | FeaturePipeline (T2) |
| `t2_screener_features` | FeaturePipeline | FeaturePipeline (T3 gate) |
| `t2_regime_scores` | RegimePipeline | FeaturePipeline (Phase D) |
| `daily_features` | FeaturePipeline | T3 extraction, views |
| `t3_sepa_features` | FeaturePipeline | All 8 production views |
| `d2_training_cache` | ViewManager | Model training (70x speedup) |
| `pipeline_runs` | PipelineRunManager | Phase 9 health report |

## Schematics

┌─────────────────────────────────────────────────────────────────┐
│  CLI ENTRYPOINT (run_daily_pipeline.py)                         │
│  → Parses args (--date, --dry-run, --force, --phase-1-only)     │
│  → Creates DailyPipelineOrchestrator                            │
│  → Calls orchestrator.run_pipeline(target_date)                 │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  TRADING DAY RESOLUTION                                         │
│  Downloads SPY last 7 days via yfinance to find actual trading  │
│  day (skips weekends/holidays)                                  │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 1.1: Quarterly Universe Refresh (OPTIONAL, every 90d)   │
│  → Checks company_profiles.created_at age                       │
│  → If >90 days: yfinance screener → new tickers → backfill     │
│  → Non-critical: continues on failure                           │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 1: T1 Ingestion (PARALLEL — 4 threads)                  │
│  ┌──────────────────┐  ┌──────────────────┐                     │
│  │ 1.1 Price Data   │  │ 1.2 Fundamentals │                     │
│  │ DataRepository   │  │ FundamentalEngine│                     │
│  │ yfinance → DuckDB│  │ yfinance → DuckDB│                     │
│  │ (stale only)     │  │ (all active)     │                     │
│  └──────────────────┘  └──────────────────┘                     │
│  ┌──────────────────┐  ┌──────────────────┐                     │
│  │ 1.3 Shares       │  │ 1.4 Macro        │                     │
│  │ SharesEngine     │  │ MacroEngine      │                     │
│  │ yfinance → DuckDB│  │ FRED/VIX → DuckDB│                     │
│  └──────────────────┘  └──────────────────┘                     │
│  → Checks failure rate (<10% threshold)                         │
│  → HALT on price failure | WARN on others                       │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 2: Screener Membership (HALT on failure)                 │
│  → ScreenerManager.update_membership()                          │
│  → Criteria: Price >= $15, 20d avg vol >= 500K                  │
│  → INSERT new eligible → UPDATE ineligible to is_active=FALSE   │
│  → Writes to: screener_members table                            │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 3: T2 Screener Features (HALT on failure)                │
│  → FeaturePipeline.compute_t2_screener_features()               │
│  → 30 lightweight SQL features (SMAs, RS, VCP, SEPA flags)      │
│  → Writes to: t2_screener_features table                        │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 4: T2 Regime Scores (WARN on failure)                    │
│  → RegimePipeline.update_incremental()                          │
│  → M03 regime scores (macro pillars, vol, net liquidity)        │
│  → Writes to: t2_regime_scores table                            │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 5: daily_features Rebuild (HALT on failure)              │
│  → FeaturePipeline.compute_all(incremental=True, skip_t3=True)  │
│  ⚠️  Incremental mode FALLS BACK to full rebuild currently      │
│  → Phase A: 79 base features via SQL CTEs (~10s)                │
│  → Phase B: 16 WQ101 alphas via Python multiprocessing (~50s)   │
│  → Phase C: 7 cross-sectional ranks via SQL (~2s)               │
│  → Phase D: M03 regime features from t2_regime_scores           │
│  → Phase E: M03 derived features (deltas, vol)                  │
│  → Writes to: daily_features table (CREATE OR REPLACE)          │
│  ⚠️  Transaction wrapper in orchestrator is INEFFECTIVE         │
│     (FeaturePipeline opens its own connection internally)        │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 6: T3 Lazy Materialization (WARN on failure)             │
│  → FeaturePipeline.compute_t3_features(target_date)             │
│  → Extracts SEPA breakout candidates from daily_features        │
│  → INSERT OR IGNORE into t3_sepa_features (idempotent)          │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 7: View Refresh (WARN on failure)                        │
│  → ViewManager.create_all() — 8 views + 2 aliases               │
│  → v_sepa_candidates, v_d1_candidates, v_d2_training, etc.      │
│  → All query t3_sepa_features WHERE feature_version='v3.1'      │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 8: Training Cache Refresh (WARN on failure)              │
│  → ViewManager.refresh_cache() → materializes v_d2_training     │
│  → d2_training_cache table (70x faster model training loads)    │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 9: Monitoring (ALWAYS runs)                              │
│  → PipelineRunManager.get_health_report()                       │
│  → Checks: breakout drought, runtime anomalies, recent failures │
│  → Logs data freshness per table                                │
└─────────────────────────────────────────────────────────────────┘
