# Milestone 6.1: Daily Pipeline Architecture Design (MECE Framework)

## 🎯 Design Principles

1. **Mutually Exclusive, Collectively Exhaustive (MECE)** - Each component has a single, clear responsibility
2. **OOP Best Practices** - Domain logic in classes, orchestration in scripts
3. **Separation of Concerns** - Engines (data I/O), Pipelines (computation), Managers (state)
4. **Reusability** - Components usable from CLI, dashboard, or automated jobs

---

## 🏗️ Existing Architecture Analysis

### Current Components (Already Exist)

| Component | Type | Responsibility | Location |
|-----------|------|----------------|----------|
| `DataRepository` | **Engine** | T1 price data ingestion | `src/data_engine.py` |
| `FundamentalEngine` | **Engine** | T1 fundamental data ingestion | `src/fundamental_engine.py` |
| `SharesEngine` | **Engine** | T1 shares outstanding ingestion | `src/shares_engine.py` |
| `MacroEngine` | **Engine** | T1 macro data ingestion | `src/macro_engine.py` |
| `RegimePipeline` | **Pipeline** | T2 regime score computation | `src/regime_pipeline.py` |
| `FeaturePipeline` | **Pipeline** | T2/daily_features/T3 computation | `src/feature_pipeline.py` |
| `ViewManager` | **Manager** | View/cache lifecycle | `src/view_manager.py` |

### Gaps in Current Architecture

❌ **No orchestration layer** - `data_curator_duckdb.py` is monolithic
❌ **No pipeline state tracking** - Can't detect completed phases
❌ **No error handling abstraction** - HALT/WARN/SKIP logic is ad-hoc
❌ **No monitoring abstraction** - Health checks scattered across scripts

---

## 🧩 Proposed MECE Architecture

### Layer 1: Engines (Data I/O)
**Responsibility**: Fetch data from external APIs, write to DuckDB
**Pattern**: `{Domain}Engine`
**Characteristics**: Stateless, idempotent, single data source

```
✅ DataRepository       → Price data (yfinance)
✅ FundamentalEngine    → Fundamentals (FMP)
✅ SharesEngine         → Shares (yfinance)
✅ MacroEngine          → Macro (yfinance)
```

### Layer 2: Pipelines (Computation)
**Responsibility**: Transform raw data into features, execute multi-step computations
**Pattern**: `{Domain}Pipeline`
**Characteristics**: Stateless, compute-heavy, multi-step

```
✅ FeaturePipeline      → T2 screener, daily_features (A-E), T3 lazy
✅ RegimePipeline       → M03 regime scores
```

### Layer 3: Managers (State & Lifecycle)
**Responsibility**: Manage database objects, track execution state
**Pattern**: `{Resource}Manager`
**Characteristics**: Stateful, CRUD operations, lifecycle management

```
✅ ViewManager          → Views, training cache
⏳ PipelineRunManager   → Pipeline execution tracking (NEW)
```

### Layer 4: Orchestrators (Workflow)
**Responsibility**: Coordinate engines/pipelines/managers, implement business logic
**Pattern**: `{Workflow}Orchestrator`
**Characteristics**: High-level control flow, error handling, monitoring

```
⏳ DailyPipelineOrchestrator → 9-phase daily workflow (NEW)
```

---

## 📦 New Components Design

### 1. `PipelineRunManager` (NEW - `src/pipeline_run_manager.py`)

**Responsibility**: Track pipeline execution state for idempotency and monitoring

```python
class PipelineRunStatus(Enum):
    """Execution status enum."""
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"

class PipelineRunManager:
    """
    Manages pipeline execution tracking in the `pipeline_runs` table.

    Responsibilities:
    - Create/update pipeline_runs table
    - Track phase execution (start, complete, fail)
    - Query execution history (for idempotency checks)
    - Generate health metrics (runtime, failure rates)
    """

    def __init__(self, db_path: str):
        """Initialize with database connection."""
        self.db_path = db_path
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create pipeline_runs table if not exists."""
        # CREATE TABLE IF NOT EXISTS pipeline_runs (...)
        pass

    def start_phase(self, target_date: str, phase_name: str, metadata: dict = None) -> int:
        """
        Mark phase as RUNNING, return run_id.

        Args:
            target_date: Date being processed (e.g., '2024-01-15')
            phase_name: Phase identifier (e.g., 'phase_1_t1_price')
            metadata: Optional metadata (e.g., {'tickers_count': 1826})

        Returns:
            run_id: Unique ID for this execution
        """
        pass

    def complete_phase(
        self,
        run_id: int,
        status: PipelineRunStatus,
        rows_processed: int = None,
        error_message: str = None
    ) -> None:
        """Mark phase as completed with status."""
        pass

    def is_phase_completed(self, target_date: str, phase_name: str) -> bool:
        """
        Check if phase already completed successfully for target_date.
        Used for idempotency checks.
        """
        pass

    def get_phase_metrics(self, phase_name: str, lookback_days: int = 30) -> dict:
        """
        Get average runtime and success rate for a phase.

        Returns:
            {
                'avg_runtime_sec': 45.2,
                'success_rate': 0.98,
                'failure_count': 2
            }
        """
        pass

    def get_health_report(self, target_date: str = None) -> dict:
        """
        Generate pipeline health report.

        Checks:
        - Data freshness (T1/T2/T3 max dates)
        - Recent failures (last 7 days)
        - Breakout drought (0 breakouts for N days)
        - Runtime anomalies (phase >2× avg)

        Returns:
            {
                'data_freshness_ok': True,
                'recent_failures': [...],
                'breakout_drought_days': 0,
                'runtime_anomalies': [...]
            }
        """
        pass
```

---

### 2. `DailyPipelineOrchestrator` (NEW - `src/daily_pipeline_orchestrator.py`)

**Responsibility**: Orchestrate 9-phase daily pipeline with error handling and monitoring

```python
class PipelineFailureMode(Enum):
    """How to handle phase failures."""
    HALT = "halt"       # Stop pipeline immediately
    WARN = "warn"       # Log warning, continue
    SKIP = "skip"       # Skip phase, continue

class DailyPipelineOrchestrator:
    """
    Orchestrates the daily 9-phase pipeline.

    Responsibilities:
    - Execute phases in dependency order
    - Handle errors according to failure mode
    - Track execution state via PipelineRunManager
    - Generate health reports and alerts

    Does NOT:
    - Fetch data (delegates to Engines)
    - Compute features (delegates to Pipelines)
    - Manage views (delegates to ViewManager)
    """

    # Class-level configuration
    FAILURE_MODES = {
        "phase_1_t1_price": PipelineFailureMode.HALT,
        "phase_1_t1_fundamentals": PipelineFailureMode.WARN,
        "phase_1_t1_shares": PipelineFailureMode.WARN,
        "phase_1_t1_macro": PipelineFailureMode.WARN,
        "phase_2_screener_membership": PipelineFailureMode.HALT,
        "phase_3_t2_screener": PipelineFailureMode.HALT,
        "phase_4_t2_regime": PipelineFailureMode.WARN,
        "phase_5_daily_features": PipelineFailureMode.HALT,
        "phase_6_t3_lazy": PipelineFailureMode.WARN,
        "phase_7_views": PipelineFailureMode.WARN,
        "phase_8_cache": PipelineFailureMode.WARN,
    }

    def __init__(
        self,
        db_path: str,
        dry_run: bool = False,
        force: bool = False
    ):
        """
        Initialize orchestrator.

        Args:
            db_path: Path to DuckDB database
            dry_run: If True, validate only (no writes)
            force: If True, ignore idempotency checks
        """
        self.db_path = db_path
        self.dry_run = dry_run
        self.force = force

        # Initialize managers (delegate state tracking)
        self.run_manager = PipelineRunManager(db_path)
        self.view_manager = ViewManager(db_path)

        # Initialize engines (delegate data I/O)
        self.data_repo = DataRepository(db_path)
        self.fund_engine = FundamentalEngine(db_path)
        self.shares_engine = SharesEngine(db_path)
        self.macro_engine = MacroEngine(db_path)

        # Initialize pipelines (delegate computation)
        self.feature_pipeline = FeaturePipeline(db_path)
        self.regime_pipeline = RegimePipeline(db_path)

    def run_pipeline(self, target_date: str = None) -> bool:
        """
        Execute full 9-phase pipeline.

        Args:
            target_date: Date to process (None = yesterday)

        Returns:
            True if all CRITICAL phases succeeded
        """
        # 1. Determine target date (yesterday if None)
        # 2. Execute phases 1-9 in sequence
        # 3. Handle errors per FAILURE_MODES
        # 4. Generate health report
        # 5. Return success/failure
        pass

    def _execute_phase(
        self,
        phase_name: str,
        phase_func: callable,
        target_date: str
    ) -> tuple[bool, dict]:
        """
        Execute a single phase with error handling and tracking.

        Args:
            phase_name: Phase identifier (e.g., 'phase_1_t1_price')
            phase_func: Function to execute (e.g., self._run_phase_1_t1_price)
            target_date: Date being processed

        Returns:
            (success: bool, stats: dict)
        """
        # 1. Check idempotency (skip if already completed and not force)
        # 2. Start phase tracking (run_manager.start_phase)
        # 3. Execute phase_func
        # 4. Complete phase tracking (run_manager.complete_phase)
        # 5. Handle errors per FAILURE_MODES[phase_name]
        pass

    # Phase execution methods (delegate to engines/pipelines)

    def _run_phase_1_t1_ingestion(self, target_date: str) -> dict:
        """Phase 1: T1 ingestion (PARALLEL)."""
        # Use ThreadPoolExecutor to fetch in parallel:
        # - self.data_repo.fetch_prices(target_date)
        # - self.fund_engine.update_fundamentals(...)
        # - self.shares_engine.update_shares(...)
        # - self.macro_engine.ingest_daily_macro(...)
        pass

    def _run_phase_2_screener_membership(self, target_date: str) -> dict:
        """Phase 2: Update screener_members table."""
        # Delegate to FeaturePipeline (or create ScreenerManager?)
        pass

    def _run_phase_3_t2_screener(self, target_date: str) -> dict:
        """Phase 3: Compute T2 screener features."""
        # self.feature_pipeline.compute_t2_screener_features(...)
        pass

    def _run_phase_4_t2_regime(self, target_date: str) -> dict:
        """Phase 4: Compute M03 regime scores."""
        # self.regime_pipeline.update(target_date)
        pass

    def _run_phase_5_daily_features(self, target_date: str) -> dict:
        """Phase 5: Compute daily_features (Phases A-E)."""
        # self.feature_pipeline.compute_all(incremental=True)
        pass

    def _run_phase_6_t3_lazy(self, target_date: str) -> dict:
        """Phase 6: T3 lazy materialization."""
        # self.feature_pipeline.compute_t3_features(target_date)
        pass

    def _run_phase_7_views(self, target_date: str) -> dict:
        """Phase 7: Refresh views."""
        # self.view_manager.create_all()
        pass

    def _run_phase_8_cache(self, target_date: str) -> dict:
        """Phase 8: Refresh training cache."""
        # self.view_manager.refresh_training_cache()
        pass

    def _run_phase_9_monitoring(self, run_stats: dict) -> dict:
        """Phase 9: Generate health report and alerts."""
        # self.run_manager.get_health_report(target_date)
        pass
```

---

## 📁 File Structure

```
src/
├── engines/ (Data I/O Layer)
│   ├── data_engine.py           ✅ EXISTS (DataRepository)
│   ├── fundamental_engine.py    ✅ EXISTS (FundamentalEngine)
│   ├── shares_engine.py         ✅ EXISTS (SharesEngine)
│   └── macro_engine.py          ✅ EXISTS (MacroEngine)
│
├── pipelines/ (Computation Layer)
│   ├── feature_pipeline.py      ✅ EXISTS (FeaturePipeline)
│   └── regime_pipeline.py       ✅ EXISTS (RegimePipeline)
│
├── managers/ (State & Lifecycle Layer)
│   ├── view_manager.py          ✅ EXISTS (ViewManager)
│   └── pipeline_run_manager.py  ⏳ NEW (PipelineRunManager)
│
├── orchestrators/ (Workflow Layer)
│   └── daily_pipeline_orchestrator.py  ⏳ NEW (DailyPipelineOrchestrator)
│
scripts/
└── run_daily_pipeline.py        ⏳ NEW (CLI entrypoint, 50-100 lines)
```

---

## 🎭 Separation of Concerns

### What Goes Where?

| Concern | Layer | Example |
|---------|-------|---------|
| **Fetch price data** | Engine | `DataRepository.fetch_prices()` |
| **Compute T2 features** | Pipeline | `FeaturePipeline.compute_t2_screener_features()` |
| **Track execution state** | Manager | `PipelineRunManager.start_phase()` |
| **Coordinate workflow** | Orchestrator | `DailyPipelineOrchestrator.run_pipeline()` |
| **CLI interface** | Script | `scripts/run_daily_pipeline.py` (argparse) |

### Anti-Patterns to Avoid

❌ **God Class** - Don't put all logic in `DailyPipelineOrchestrator`
❌ **Leaky Abstraction** - Engines shouldn't know about pipelines
❌ **Circular Dependencies** - Orchestrator depends on engines/pipelines, not vice versa
❌ **Business Logic in Scripts** - `run_daily_pipeline.py` should be <100 lines

---

## 🔄 Dependency Graph

```
┌────────────────────────────────────────────────────────────┐
│ scripts/run_daily_pipeline.py (CLI Entrypoint)            │
│   - Parses arguments                                       │
│   - Calls orchestrator.run_pipeline(target_date)          │
│   - Prints results (exit 0/1)                             │
└────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────┐
│ DailyPipelineOrchestrator (Workflow Coordinator)          │
│   - Executes phases 1-9 in dependency order               │
│   - Handles errors (HALT/WARN/SKIP)                       │
│   - Delegates to engines/pipelines/managers               │
└────────────────────────────────────────────────────────────┘
          │              │              │              │
          ▼              ▼              ▼              ▼
    ┌─────────┐    ┌──────────┐   ┌─────────┐   ┌──────────┐
    │ Engines │    │Pipelines │   │Managers │   │ Managers │
    │         │    │          │   │         │   │          │
    │DataRepo │    │Feature   │   │View     │   │Run       │
    │FundEng  │    │Pipeline  │   │Manager  │   │Manager   │
    │SharesEng│    │Regime    │   │         │   │          │
    │MacroEng │    │Pipeline  │   │         │   │          │
    └─────────┘    └──────────┘   └─────────┘   └──────────┘
          │              │              │              │
          └──────────────┴──────────────┴──────────────┘
                            │
                            ▼
                    ┌──────────────┐
                    │   DuckDB     │
                    │ (Data Layer) │
                    └──────────────┘
```

**Key Points**:
- Scripts depend on Orchestrators
- Orchestrators depend on Engines/Pipelines/Managers
- Engines/Pipelines/Managers are INDEPENDENT (no cross-dependencies)
- All layers depend on DuckDB (shared resource)

---

## 🧪 Testability

### Unit Tests (Test Each Layer Independently)

```python
# Test Engine (mocked DuckDB)
def test_data_repository_fetch_prices():
    repo = DataRepository(':memory:')
    df = repo.fetch_prices('2024-01-15', tickers=['AAPL'])
    assert len(df) > 0
    assert 'close' in df.columns

# Test Pipeline (mocked DuckDB with test data)
def test_feature_pipeline_compute_t2():
    pipeline = FeaturePipeline(':memory:')
    # Insert test price_data
    rows = pipeline.compute_t2_screener_features()
    assert rows > 0

# Test Manager (mocked DuckDB)
def test_pipeline_run_manager_tracking():
    manager = PipelineRunManager(':memory:')
    run_id = manager.start_phase('2024-01-15', 'phase_1_t1_price')
    manager.complete_phase(run_id, PipelineRunStatus.SUCCESS, rows_processed=1826)
    assert manager.is_phase_completed('2024-01-15', 'phase_1_t1_price')
```

### Integration Tests (Test Orchestrator End-to-End)

```python
def test_daily_pipeline_orchestrator_full_run():
    orchestrator = DailyPipelineOrchestrator(':memory:', dry_run=False)
    success = orchestrator.run_pipeline('2024-01-15')
    assert success is True
    # Verify T3 rows created
    # Verify views refreshed
```

---

## 🚀 Implementation Steps (MECE-Aligned)

### Step 1: Create PipelineRunManager (1 hour)
- [ ] Create `src/managers/` directory
- [ ] Move `src/view_manager.py` → `src/managers/view_manager.py`
- [ ] Create `src/managers/pipeline_run_manager.py`
- [ ] Implement `PipelineRunStatus` enum
- [ ] Implement `PipelineRunManager` class (6 methods)
- [ ] Create `pipeline_runs` table schema
- [ ] Write unit tests

### Step 2: Create DailyPipelineOrchestrator (1.5 hours)
- [ ] Create `src/orchestrators/` directory
- [ ] Create `src/orchestrators/daily_pipeline_orchestrator.py`
- [ ] Implement `PipelineFailureMode` enum
- [ ] Implement `DailyPipelineOrchestrator.__init__()`
- [ ] Implement `_execute_phase()` wrapper (error handling + tracking)
- [ ] Implement phase methods 1-9 (delegate to engines/pipelines/managers)
- [ ] Implement `run_pipeline()` main loop

### Step 3: Create CLI Entrypoint (0.5 hours)
- [ ] Create `scripts/run_daily_pipeline.py` (50-100 lines)
- [ ] Add argparse (--date, --dry-run, --force, --skip-*)
- [ ] Instantiate `DailyPipelineOrchestrator`
- [ ] Call `orchestrator.run_pipeline(target_date)`
- [ ] Print results and exit with status code

### Step 4: Testing & Validation (1 hour)
- [ ] Write unit tests for `PipelineRunManager`
- [ ] Write unit tests for `DailyPipelineOrchestrator` (mock engines/pipelines)
- [ ] Write integration test (full pipeline on historical date)
- [ ] Run validation tests (idempotency, error handling, dry-run)

---

## ✅ MECE Validation Checklist

### Mutually Exclusive (No Overlaps)
- [ ] Each component has ONE clear responsibility
- [ ] No duplicate logic across layers
- [ ] Orchestrator doesn't do data I/O or computation
- [ ] Engines don't do computation
- [ ] Pipelines don't manage state

### Collectively Exhaustive (No Gaps)
- [ ] All 9 phases have execution logic
- [ ] All error modes handled (HALT/WARN/SKIP)
- [ ] All state tracked (pipeline_runs table)
- [ ] All monitoring queries implemented

---

## 📊 Benefits of This Architecture

1. **Maintainability** - Each class has single responsibility (easy to debug)
2. **Testability** - Layers can be unit tested independently
3. **Reusability** - Orchestrator can be used from CLI, dashboard, or cron
4. **Extensibility** - New phases easy to add (just add phase method)
5. **Monitoring** - Centralized tracking in `PipelineRunManager`
6. **Error Handling** - Consistent failure modes across all phases

---

## 🤔 Open Questions for Discussion

1. **ScreenerManager?** - Should screener_members updates be in a separate manager?
   - Current: `FeaturePipeline` handles T2 screener (computation)
   - Proposal: Create `ScreenerManager` for membership updates (state management)
   - Decision: ?

2. **AlertManager?** - Should alerts be a separate component?
   - Current: Alerts embedded in `DailyPipelineOrchestrator._run_phase_9_monitoring()`
   - Proposal: Create `AlertManager` with pluggable backends (console, email, Slack)
   - Decision: ?

3. **Config Management?** - Where to store FAILURE_MODES configuration?
   - Current: Class-level dict in `DailyPipelineOrchestrator`
   - Proposal: Move to `config.py` or YAML file for easier tweaking
   - Decision: ?

4. **Transaction Management?** - Should each phase run in a DuckDB transaction?
   - Current: No explicit transactions (auto-commit)
   - Proposal: Wrap each phase in BEGIN/COMMIT (rollback on failure)
   - Decision: ?

---

## 🎯 Summary

### Proposed Structure (MECE-Compliant)

```
Layer 1: Engines (Data I/O)          → 4 classes ✅ EXISTS
Layer 2: Pipelines (Computation)     → 2 classes ✅ EXISTS
Layer 3: Managers (State/Lifecycle)  → 2 classes (1 exists, 1 NEW)
Layer 4: Orchestrators (Workflow)    → 1 class ⏳ NEW
Layer 5: Scripts (CLI)               → 1 script ⏳ NEW
```

### Implementation Effort

- **PipelineRunManager**: 1 hour (150 lines)
- **DailyPipelineOrchestrator**: 1.5 hours (300 lines)
- **CLI Script**: 0.5 hours (50-100 lines)
- **Testing**: 1 hour (unit + integration tests)
- **Total**: 4 hours ✅ (matches estimate)

---

**Ready to discuss and refine before implementation?**
