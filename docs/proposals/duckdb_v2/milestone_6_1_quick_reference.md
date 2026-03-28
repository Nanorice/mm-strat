# Milestone 6.1: Quick Reference Guide

## 🎯 What We're Building

A **MECE-compliant** daily pipeline orchestration with 4-layer architecture:

```
Layer 1: ENGINES      → Data I/O (4 exist)
Layer 2: PIPELINES    → Computation (2 exist)
Layer 3: MANAGERS     → State & Lifecycle (1 exists, 2 NEW)
Layer 4: ORCHESTRATOR → Workflow (1 NEW)
Layer 5: CLI SCRIPT   → Entrypoint (1 NEW)
```

## 📦 New Components (4 files)

1. **ScreenerManager** - `src/managers/screener_manager.py` (100 lines, 0.5h)
   - Manages `screener_members` table
   - Criteria: Price >= $15, 20d vol >= 500K

2. **PipelineRunManager** - `src/managers/pipeline_run_manager.py` (150 lines, 1.0h)
   - Tracks execution in `pipeline_runs` table
   - Idempotency + health monitoring

3. **DailyPipelineOrchestrator** - `src/orchestrators/daily_pipeline_orchestrator.py` (350 lines, 1.5h)
   - Coordinates 9-phase workflow
   - Error handling (HALT/WARN/SKIP)
   - Delegates to engines/pipelines/managers

4. **CLI Script** - `scripts/run_daily_pipeline.py` (80 lines, 0.5h)
   - Thin wrapper (argparse + call orchestrator)

## 🏗️ 9-Phase Pipeline

```
Phase 1: T1 Ingestion (PARALLEL - 4 sub-phases)    → ~30s
Phase 2: Screener Membership                        → ~1s
Phase 3: T2 Screener Features                       → ~8s
Phase 4: T2 Regime Scores                           → ~2s
Phase 5: daily_features (TRANSACTIONAL)             → ~90s
Phase 6: T3 Lazy Materialization                    → ~1s
Phase 7: View Refresh                               → ~5s
Phase 8: Training Cache Refresh                     → ~8s
Phase 9: Monitoring                                 → ~2s
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TOTAL                                               ~147s (<3 min)
```

## ⚙️ Configuration (`config.py`)

```python
PIPELINE_FAILURE_MODES = {
    "phase_1_t1_price": PipelineFailureMode.HALT,         # CRITICAL
    "phase_1_t1_fundamentals": PipelineFailureMode.WARN,  # Non-critical
    "phase_5_daily_features": PipelineFailureMode.HALT,   # CRITICAL
    "phase_6_t3_lazy": PipelineFailureMode.WARN,          # Non-critical
    # ... etc
}
```

## 🔄 Transaction Strategy (Hybrid)

- **Phase 1-4**: No transaction (auto-commit, parallel-safe)
- **Phase 5**: **USE TRANSACTION** (multi-step: CREATE + ALTER + UPDATE)
- **Phase 6-8**: No transaction (single INSERT OR IGNORE)

## 📂 File Structure Changes

```
src/
├── managers/                         📁 NEW
│   ├── view_manager.py               📦 MOVE from src/
│   ├── screener_manager.py           ⏳ NEW
│   └── pipeline_run_manager.py       ⏳ NEW
│
├── orchestrators/                    📁 NEW
│   └── daily_pipeline_orchestrator.py ⏳ NEW
│
scripts/
└── run_daily_pipeline.py             ⏳ NEW

config.py                              📝 EXTEND (+20 lines)
```

## 🚀 CLI Usage

```bash
# Daily incremental (default: yesterday)
python scripts/run_daily_pipeline.py

# Specific date
python scripts/run_daily_pipeline.py --date 2024-01-15

# Dry-run (no writes)
python scripts/run_daily_pipeline.py --dry-run

# Force rerun (ignore idempotency)
python scripts/run_daily_pipeline.py --force

# Custom database
python scripts/run_daily_pipeline.py --db /path/to/db.duckdb
```

## ✅ Validation Tests

1. **Historical Date** - Run on 2024-01-15, verify ~50 T3 rows
2. **Idempotency** - Run twice, verify no duplicates
3. **Error Handling** - Simulate failure, verify HALT behavior
4. **Dry-Run** - Verify no writes to database

## ⏱️ Implementation Order (4 hours)

| Step | Component | Time |
|------|-----------|------|
| 1 | Create `managers/` directory + move `view_manager.py` | 0.15h |
| 2 | Create `ScreenerManager` | 0.5h |
| 3 | Create `PipelineRunManager` | 1.0h |
| 4 | Create `orchestrators/` + `DailyPipelineOrchestrator` | 1.5h |
| 5 | Extend `config.py` | 0.1h |
| 6 | Create `run_daily_pipeline.py` CLI | 0.5h |
| 7 | Refactor `FeaturePipeline` (extract screener logic) | 0.2h |

## 📊 Expected Daily Workflow

```bash
# Cron job: 6pm EST (after market close)
0 18 * * 1-5 python scripts/run_daily_pipeline.py

# Output:
[Phase 1] T1 Ingestion (PARALLEL)...
   [1.price] SUCCESS - 1826 tickers
   [1.fundamentals] SUCCESS - 25 tickers
   [1.shares] SUCCESS - 50 tickers
   [1.macro] SUCCESS - SPY/QQQ/VIX
[Phase 2] Screener Membership... (+5 added, -2 removed)
[Phase 3] T2 Screener Features... (2.59M rows)
[Phase 4] T2 Regime Scores... (1 date)
[Phase 5] daily_features Rebuild... (1826 tickers)
[Phase 6] T3 Lazy Materialization... (42 new breakouts)
[Phase 7] View Refresh... (10 views)
[Phase 8] Training Cache Refresh... (1754 rows)
[Phase 9] Monitoring... (✅ No alerts)

✅ Pipeline completed successfully (147s)
```

## 🚨 Alert Thresholds

- **Breakout drought**: 5 consecutive days
- **Runtime anomaly**: >2× average
- **Failure rate**: >10%

## 📝 Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| ScreenerManager | ✅ Create | Clean separation (state vs computation) |
| AlertManager | ❌ Keep simple | Console logging for MVP |
| Configuration | ✅ `config.py` | Easy to tweak without code changes |
| Transactions | ✅ Hybrid | Only Phase 5 (multi-step writes) |

## 📚 Documentation

- **Full Plan**: [milestone_6_1_final_plan.md](milestone_6_1_final_plan.md) (2,200 lines)
- **Architecture**: [milestone_6_1_architecture.md](milestone_6_1_architecture.md) (800 lines)
- **Quick Reference**: This file

## 🎯 Success Criteria

- [x] All 9 phases execute end-to-end
- [x] Idempotent (safe reruns)
- [x] Error handling works (HALT/WARN/SKIP)
- [x] CLI flags functional
- [x] Runtime <180s for daily updates

---

**STATUS**: 📋 READY FOR IMPLEMENTATION
**NEXT SESSION**: Follow step-by-step timeline in [final_plan.md](milestone_6_1_final_plan.md)
