# Milestone 6.1: Daily Pipeline Orchestration Script

## 📋 Overview

**Goal**: Create production-ready daily pipeline script that orchestrates all data ingestion and feature computation phases with error handling, monitoring, and idempotency.

**Estimated Time**: 4 hours
**Status**: 📝 PLANNING

---

## 🎯 Objectives

1. **Orchestrate 9-phase pipeline** (T1 → T2 → T3 → Views)
2. **Idempotent execution** (safe to rerun without side effects)
3. **Error handling** (fail-safe modes: HALT, WARN, CONTINUE)
4. **Monitoring** (log runtime, alert on anomalies)
5. **CLI interface** (flexible date ranges, dry-run mode)

---

## 🏗️ Architecture

### Current State
- ✅ `data_curator_duckdb.py` handles T1 (price, fundamentals, shares) + daily_features rebuild
- ✅ `scripts/ingest_t1_macro.py` handles T1 macro ingestion
- ✅ `FeaturePipeline.compute_all()` handles Phases A-E (daily_features)
- ✅ `FeaturePipeline.compute_t2_screener_features()` handles T2 screener
- ✅ `FeaturePipeline.compute_t3_features()` handles T3 lazy materialization
- ✅ `ViewManager.create_all()` handles view creation

### Target Architecture
```
┌─────────────────────────────────────────────────────────────────┐
│ scripts/run_daily_pipeline.py (NEW)                             │
│                                                                  │
│ Phase 1: T1 Ingestion (PARALLEL)                                │
│   ├─ T1.1: Price data         (yfinance, 1826 tickers)          │
│   ├─ T1.2: Fundamentals       (FMP earnings calendar, ~25/day)  │
│   ├─ T1.3: Shares outstanding (yfinance, ~50/day)               │
│   └─ T1.4: Macro data         (SPY/QQQ/VIX)                     │
│                                                                  │
│ Phase 2: T2 Screener Membership (SEQUENTIAL)                    │
│   └─ Update screener_members table (depends on T1.1)            │
│                                                                  │
│ Phase 3: T2 Screener Features (SEQUENTIAL)                      │
│   └─ FeaturePipeline.compute_t2_screener_features()             │
│      (depends on T1.1, screener_members)                        │
│                                                                  │
│ Phase 4: T2 Regime Scores (PARALLEL with Phase 3)               │
│   └─ RegimePipeline.update() (depends on T1.4)                  │
│                                                                  │
│ Phase 5: daily_features Rebuild (SEQUENTIAL)                    │
│   └─ FeaturePipeline.compute_all()                              │
│      (Phases A-E, depends on T2 screener + T2 regime)           │
│                                                                  │
│ Phase 6: T3 Lazy Materialization (SEQUENTIAL)                   │
│   └─ FeaturePipeline.compute_t3_features()                      │
│      (depends on Phase 5, t2_screener_features SEPA flags)      │
│                                                                  │
│ Phase 7: View Layer Refresh (SEQUENTIAL)                        │
│   └─ ViewManager.create_all() (depends on T3)                   │
│                                                                  │
│ Phase 8: Training Cache Refresh (SEQUENTIAL)                    │
│   └─ ViewManager.refresh_training_cache() (depends on views)    │
│                                                                  │
│ Phase 9: Pipeline Monitoring (ALWAYS RUN)                       │
│   └─ Log runtime, breakout counts, alert on anomalies           │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📦 Deliverables

### 1. `scripts/run_daily_pipeline.py` (NEW - ~300 lines)

**Main Components**:

```python
class DailyPipelineOrchestrator:
    """Orchestrates the 9-phase daily data pipeline."""

    def __init__(self, db_path: str, dry_run: bool = False):
        """Initialize pipeline with database connection."""
        pass

    def run_phase_1_t1_ingestion(self, target_date: str) -> Dict[str, bool]:
        """
        Phase 1: Ingest T1 data (price, fundamentals, shares, macro) in parallel.

        Returns:
            Dict with success status for each T1 component
        """
        pass

    def run_phase_2_screener_membership(self, target_date: str) -> bool:
        """
        Phase 2: Update screener_members table based on price data.

        Depends on: Phase 1.1 (price data)
        """
        pass

    def run_phase_3_t2_screener_features(self, target_date: str) -> int:
        """
        Phase 3: Compute T2 screener features (lightweight SQL).

        Depends on: Phase 1.1 (price), Phase 2 (screener_members)
        Returns: Number of rows computed
        """
        pass

    def run_phase_4_t2_regime_scores(self, target_date: str) -> int:
        """
        Phase 4: Compute M03 regime scores.

        Depends on: Phase 1.4 (macro data)
        Returns: Number of dates computed
        """
        pass

    def run_phase_5_daily_features(self, target_date: str, incremental: bool = True) -> int:
        """
        Phase 5: Compute daily_features (Phases A-E).

        Depends on: Phase 3 (T2 screener), Phase 4 (T2 regime)
        Returns: Number of rows computed
        """
        pass

    def run_phase_6_t3_lazy_materialization(self, target_date: str) -> int:
        """
        Phase 6: Compute T3 features for new SEPA breakouts only.

        Depends on: Phase 5 (daily_features), Phase 3 (T2 SEPA flags)
        Returns: Number of new breakouts materialized
        """
        pass

    def run_phase_7_view_refresh(self) -> int:
        """
        Phase 7: Refresh all views.

        Depends on: Phase 6 (T3 data)
        Returns: Number of views refreshed
        """
        pass

    def run_phase_8_training_cache_refresh(self) -> int:
        """
        Phase 8: Refresh d2_training_cache table.

        Depends on: Phase 7 (views)
        Returns: Number of rows cached
        """
        pass

    def run_phase_9_monitoring(self, run_stats: Dict) -> None:
        """
        Phase 9: Log metrics and send alerts if needed.

        Always runs (even if earlier phases fail)
        """
        pass

    def run_pipeline(self, target_date: str = None, incremental: bool = True) -> bool:
        """
        Execute full 9-phase pipeline.

        Args:
            target_date: Date to process (None = yesterday)
            incremental: Use incremental mode for daily_features

        Returns:
            True if all critical phases succeeded
        """
        pass
```

**Error Handling**:
```python
class PipelineFailureMode(Enum):
    HALT = "halt"       # Stop pipeline immediately
    WARN = "warn"       # Log warning, continue
    CONTINUE = "skip"   # Skip phase, continue to next

FAILURE_DECISION_TREE = {
    # Phase 1: T1 Ingestion
    "t1_price": PipelineFailureMode.HALT,         # CRITICAL - can't proceed without prices
    "t1_fundamentals": PipelineFailureMode.WARN,  # Non-critical - stale data OK
    "t1_shares": PipelineFailureMode.WARN,        # Non-critical - use previous shares
    "t1_macro": PipelineFailureMode.WARN,         # Non-critical - M03 will use previous scores

    # Phase 2-3: T2 Screener
    "t2_membership": PipelineFailureMode.HALT,    # CRITICAL - needed for T2 features
    "t2_screener": PipelineFailureMode.HALT,      # CRITICAL - needed for T3

    # Phase 4: T2 Regime
    "t2_regime": PipelineFailureMode.WARN,        # Non-critical - daily_features will use NULLs

    # Phase 5: daily_features
    "daily_features": PipelineFailureMode.HALT,   # CRITICAL - needed for T3

    # Phase 6-8: T3 + Views
    "t3_materialization": PipelineFailureMode.WARN,  # Non-critical - T3 can lag by 1 day
    "view_refresh": PipelineFailureMode.WARN,        # Non-critical - views are recreatable
    "training_cache": PipelineFailureMode.WARN,      # Non-critical - cache is optional
}
```

**Idempotency Tracking**:
```python
class PipelineRunTracker:
    """Tracks pipeline execution status for idempotency."""

    def __init__(self, db_path: str):
        self._ensure_pipeline_runs_table()

    def _ensure_pipeline_runs_table(self):
        """Create pipeline_runs table if not exists."""
        # CREATE TABLE IF NOT EXISTS pipeline_runs (
        #     run_id INTEGER PRIMARY KEY,
        #     run_date DATE NOT NULL,
        #     target_date DATE NOT NULL,  -- date being processed
        #     phase_name VARCHAR NOT NULL,
        #     status VARCHAR NOT NULL,     -- 'running', 'success', 'failed', 'skipped'
        #     runtime_seconds DOUBLE,
        #     rows_processed INTEGER,
        #     error_message VARCHAR,
        #     started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        #     completed_at TIMESTAMP
        # )
        pass

    def start_phase(self, target_date: str, phase_name: str) -> int:
        """Mark phase as running, return run_id."""
        pass

    def complete_phase(self, run_id: int, status: str, rows_processed: int = None, error: str = None):
        """Mark phase as completed."""
        pass

    def is_phase_completed(self, target_date: str, phase_name: str) -> bool:
        """Check if phase already completed for target_date."""
        pass
```

**CLI Interface**:
```bash
# Daily incremental update (default behavior)
python scripts/run_daily_pipeline.py

# Process specific date
python scripts/run_daily_pipeline.py --date 2024-01-15

# Dry-run mode (validation only)
python scripts/run_daily_pipeline.py --dry-run

# Force full rebuild (ignore idempotency)
python scripts/run_daily_pipeline.py --force

# Skip specific phases
python scripts/run_daily_pipeline.py --skip-fundamentals --skip-t3

# Verbose logging
python scripts/run_daily_pipeline.py --verbose
```

---

### 2. Pipeline Monitoring Queries (Embedded in Phase 9)

```python
def check_pipeline_health(self, target_date: str, run_stats: Dict) -> Dict[str, Any]:
    """
    Check pipeline health and return metrics.

    Alerts triggered when:
    - 0 new SEPA breakouts for 5 consecutive days
    - Phase runtime >2× average
    - Any CRITICAL phase failed
    - T3 data gap >7 days
    """

    queries = {
        "breakout_count": """
            SELECT COUNT(*) as new_breakouts
            FROM t3_sepa_features
            WHERE date = '{target_date}'
        """,

        "data_freshness": """
            SELECT
                MAX(date) as max_price_date,
                MAX(date) as max_t2_date,
                MAX(date) as max_t3_date
            FROM price_data
        """,

        "avg_runtime": """
            SELECT
                phase_name,
                AVG(runtime_seconds) as avg_runtime,
                COUNT(*) as run_count
            FROM pipeline_runs
            WHERE run_date >= CURRENT_DATE - INTERVAL '30 days'
                AND status = 'success'
            GROUP BY phase_name
        """,

        "recent_failures": """
            SELECT
                target_date,
                phase_name,
                error_message
            FROM pipeline_runs
            WHERE status = 'failed'
                AND run_date >= CURRENT_DATE - INTERVAL '7 days'
            ORDER BY started_at DESC
        """,
    }

    # Execute queries and build health report
    health = {
        "new_breakouts": 0,
        "data_freshness_ok": True,
        "runtime_anomalies": [],
        "recent_failures": [],
        "alerts": []
    }

    # Check for 5-day breakout drought
    if health["new_breakouts"] == 0:
        drought_days = self._count_consecutive_zero_breakouts(target_date)
        if drought_days >= 5:
            health["alerts"].append(f"WARN: 0 breakouts for {drought_days} days")

    # Check runtime anomalies (>2× avg)
    for phase, runtime in run_stats.items():
        avg = self._get_avg_runtime(phase)
        if runtime > avg * 2:
            health["alerts"].append(f"WARN: Phase '{phase}' took {runtime:.1f}s (avg: {avg:.1f}s)")

    return health
```

---

## 🔄 Implementation Steps

### Step 1: Create Pipeline Orchestrator Class (1 hour)
- [ ] Create `scripts/run_daily_pipeline.py`
- [ ] Implement `DailyPipelineOrchestrator` class skeleton
- [ ] Implement `PipelineRunTracker` with `pipeline_runs` table
- [ ] Add CLI argument parsing (argparse)

### Step 2: Implement Phase 1-4 (T1 + T2) (1 hour)
- [ ] `run_phase_1_t1_ingestion()` with parallel ThreadPoolExecutor
  - Reuse `data_curator_duckdb.py` methods
  - Reuse `ingest_t1_macro.py` logic
- [ ] `run_phase_2_screener_membership()` (delegated to FeaturePipeline)
- [ ] `run_phase_3_t2_screener_features()` (delegated to FeaturePipeline)
- [ ] `run_phase_4_t2_regime_scores()` (delegated to RegimePipeline)

### Step 3: Implement Phase 5-8 (daily_features + T3 + Views) (1 hour)
- [ ] `run_phase_5_daily_features()` with incremental parameter
- [ ] `run_phase_6_t3_lazy_materialization()` with new breakout detection
- [ ] `run_phase_7_view_refresh()` (delegated to ViewManager)
- [ ] `run_phase_8_training_cache_refresh()` (delegated to ViewManager)

### Step 4: Error Handling + Monitoring (1 hour)
- [ ] Implement `FAILURE_DECISION_TREE` logic
- [ ] `run_phase_9_monitoring()` with health checks
- [ ] Alert system (console logging + optional email/Slack hooks)
- [ ] Dry-run mode implementation
- [ ] Idempotency checks before each phase

---

## ✅ Acceptance Criteria

### Functional Requirements
- [ ] Pipeline executes all 9 phases end-to-end on historical date
- [ ] Idempotent: Can be re-run safely without duplicates
- [ ] Error handling: HALT vs WARN modes work correctly
- [ ] CLI interface: `--date`, `--dry-run`, `--force`, `--skip-*` flags functional

### Performance Requirements
- [ ] Total runtime <180 seconds for daily incremental update (0-50 new rows)
- [ ] Phase 1 (T1 ingestion) runs in parallel (<30s)
- [ ] Phase 5 (daily_features) uses incremental mode (<90s)
- [ ] Phase 6 (T3) completes in <1s for daily updates

### Monitoring Requirements
- [ ] `pipeline_runs` table logs all phase executions
- [ ] Alert triggered if 0 breakouts for 5 days
- [ ] Alert triggered if phase runtime >2× average
- [ ] Health report shows data freshness for T1/T2/T3

### Data Quality Requirements
- [ ] No duplicates in `pipeline_runs` for same (target_date, phase_name)
- [ ] No NULLs in T3 critical columns after Phase 6
- [ ] View refresh completes without errors
- [ ] Training cache row count matches `v_d2_training` row count

---

## 🧪 Validation Plan

### Test 1: Historical Date Execution
```bash
# Run pipeline on historical date
python scripts/run_daily_pipeline.py --date 2024-01-15

# Verify T3 rows created
SELECT COUNT(*) FROM t3_sepa_features WHERE date = '2024-01-15';
# Expected: ~50 rows (typical daily breakout count)

# Verify pipeline_runs logs
SELECT phase_name, status, runtime_seconds, rows_processed
FROM pipeline_runs
WHERE target_date = '2024-01-15'
ORDER BY started_at;
# Expected: 9 phases, all 'success', runtimes logged
```

### Test 2: Idempotency Check
```bash
# Run pipeline twice on same date
python scripts/run_daily_pipeline.py --date 2024-01-15
python scripts/run_daily_pipeline.py --date 2024-01-15

# Verify no duplicate T3 rows
SELECT ticker, date, COUNT(*) as cnt
FROM t3_sepa_features
WHERE date = '2024-01-15'
GROUP BY ticker, date
HAVING cnt > 1;
# Expected: 0 rows (no duplicates)

# Verify second run skipped completed phases
SELECT phase_name, status
FROM pipeline_runs
WHERE target_date = '2024-01-15'
ORDER BY started_at DESC
LIMIT 9;
# Expected: 9 phases marked 'skipped' or 'success' (idempotent)
```

### Test 3: Error Handling (Simulate T1 Failure)
```bash
# Simulate yfinance API failure by using invalid date
python scripts/run_daily_pipeline.py --date 2099-01-01

# Verify HALT behavior
SELECT phase_name, status, error_message
FROM pipeline_runs
WHERE target_date = '2099-01-01'
ORDER BY started_at;
# Expected: Phase 1 'failed', subsequent phases 'skipped' due to HALT
```

### Test 4: Dry-Run Mode
```bash
# Run in dry-run mode (no writes)
python scripts/run_daily_pipeline.py --date 2024-01-16 --dry-run

# Verify no new data written
SELECT COUNT(*) FROM t3_sepa_features WHERE date = '2024-01-16';
# Expected: 0 rows (dry-run doesn't write)

# Verify dry-run logged
SELECT phase_name, status FROM pipeline_runs WHERE target_date = '2024-01-16';
# Expected: 0 rows (dry-run doesn't log to DB)
```

---

## 📊 Expected Outcomes

### Phase Runtimes (Daily Incremental)
| Phase | Description | Expected Runtime |
|-------|-------------|------------------|
| 1.1 | T1 Price Ingestion | ~20s (1826 tickers) |
| 1.2 | T1 Fundamentals | ~5s (~25 tickers/day) |
| 1.3 | T1 Shares | ~3s (~50 tickers/day) |
| 1.4 | T1 Macro | ~2s (SPY/QQQ/VIX) |
| 2 | T2 Screener Membership | ~1s (UPDATE query) |
| 3 | T2 Screener Features | ~8s (full rebuild) |
| 4 | T2 Regime Scores | ~2s (M03 compute) |
| 5 | daily_features | ~90s (incremental) |
| 6 | T3 Lazy Materialization | ~1s (0-50 rows) |
| 7 | View Refresh | ~5s (10 views) |
| 8 | Training Cache Refresh | ~8s (materialize) |
| 9 | Monitoring | ~2s (health queries) |
| **TOTAL** | **~147s** | **<3 minutes** |

### Daily Workflow
```bash
# Cron job runs at 6pm EST (after market close)
0 18 * * 1-5 cd /path/to/quantamental && python scripts/run_daily_pipeline.py

# Expected behavior:
# - Fetches yesterday's price data (T1.1)
# - Fetches ~25 fundamental updates via earnings calendar (T1.2)
# - Fetches ~50 shares outstanding updates (T1.3)
# - Fetches macro data (T1.4)
# - Computes T2 screener features for full universe (T2)
# - Computes M03 regime scores (T2 regime)
# - Rebuilds daily_features incrementally (Phase 5)
# - Materializes T3 for new SEPA breakouts (0-50 rows/day)
# - Refreshes views and training cache
# - Logs health metrics and sends alerts if anomalies
```

---

## 🚨 Alert Conditions

| Alert Level | Condition | Action |
|-------------|-----------|--------|
| **CRITICAL** | Phase 1.1 (Price) failed | HALT pipeline, send email |
| **CRITICAL** | Phase 5 (daily_features) failed | HALT pipeline, send email |
| **WARNING** | 0 breakouts for 5 consecutive days | Log warning, send email |
| **WARNING** | Phase runtime >2× average | Log warning (no email) |
| **WARNING** | T3 data gap >7 days | Log warning, send email |
| **INFO** | Fundamentals fetch failed | Log info (no email) |
| **INFO** | Shares fetch failed | Log info (no email) |

---

## 📝 Code Reuse Strategy

### Components to Reuse (No Changes)
1. ✅ `data_curator_duckdb.py` → Methods for T1 ingestion
2. ✅ `scripts/ingest_t1_macro.py` → Macro ingestion logic
3. ✅ `FeaturePipeline.compute_t2_screener_features()` → T2 screener
4. ✅ `FeaturePipeline.compute_all()` → Phases A-E (daily_features)
5. ✅ `FeaturePipeline.compute_t3_features()` → T3 lazy materialization
6. ✅ `ViewManager.create_all()` → View refresh
7. ✅ `ViewManager.refresh_training_cache()` → Cache refresh

### New Components to Create
1. ⏳ `DailyPipelineOrchestrator` class (orchestration logic)
2. ⏳ `PipelineRunTracker` class (idempotency + monitoring)
3. ⏳ `pipeline_runs` table (execution logs)
4. ⏳ CLI interface with argparse

---

## 🔗 Dependencies

### External Libraries (Already Installed)
- `duckdb` (database operations)
- `pandas` (data manipulation)
- `concurrent.futures` (parallel T1 ingestion)
- `argparse` (CLI interface)
- `logging` (logging)

### Internal Modules (Already Exist)
- `src.data_engine.DataRepository` (price ingestion)
- `src.fundamental_engine.FundamentalEngine` (fundamentals)
- `src.shares_engine.SharesEngine` (shares)
- `src.macro_engine.MacroEngine` (macro)
- `src.feature_pipeline.FeaturePipeline` (T2 + daily_features + T3)
- `src.regime_pipeline.RegimePipeline` (M03 regime scores)
- `src.view_manager.ViewManager` (views + cache)

---

## 🎯 Success Metrics

### Milestone Complete When:
- [x] `scripts/run_daily_pipeline.py` executes all 9 phases end-to-end
- [x] Can be re-run safely (idempotent via `pipeline_runs` table)
- [x] Alerts sent on failures (console logs + optional email)
- [x] Runtime <180s for daily incremental updates
- [x] Validation tests pass (historical date, idempotency, error handling, dry-run)

---

## 📚 Related Documentation

- [Pipeline DAG](pipeline_dag.md) - Full dependency graph and failure modes
- [Technical Blueprint](technical_blueprint.md) - Error handling strategy
- [Reconciliation Plan](reconciliation_plan.md) - Component reuse strategy
- [MEMORY.md](../../../.claude/projects/c--Users-Hang-PycharmProjects-quantamental/memory/MEMORY.md) - Architecture notes

---

## 🚀 Next Milestone After 6.1

**Option A**: 6.2 - Create Pipeline Monitoring Dashboard (2 hours)
**Option B**: 6.5.1 - Implement Backtesting Engine (4 hours)
**Option C**: 4.5.1 - Develop M01 Baseline Model (4 hours)

Recommend: **Option C** (M01 Model Development) to validate T3 data quality before deploying production pipeline.
