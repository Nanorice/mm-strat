"""
DailyPipelineOrchestrator - Orchestrates the 8-phase daily pipeline (workflow layer).

Responsibilities:
- Execute phases 1-8 in dependency order
- Handle errors according to failure mode (HALT/WARN/SKIP)
- Track execution state via PipelineRunManager
- Generate health reports and alerts
- Delegate to engines/pipelines/managers (NO business logic)
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import duckdb
from src import db

try:
    import psutil
except ImportError:  # telemetry is best-effort; never break the pipeline over it
    psutil = None

# Import layers
from src.data_engine import DataRepository
from src.fundamental_engine import FundamentalEngine
from src.shares_engine import SharesEngine
from src.macro_engine import MacroEngine
from src.edgar_engine import EDGAREngine
from src.feature_pipeline import FeaturePipeline
from src.regime_pipeline import RegimePipeline
from src.pipeline.risk_5_factor import RiskFiveFactorCalculator
from src.universe_backfill import UniverseBackfillEngine
from src.managers.view_manager import ViewManager
from src.managers.screener_manager import ScreenerManager
from src.managers.sepa_watchlist_manager import SepaWatchlistManager
from src.managers.pipeline_run_manager import PipelineRunManager, PipelineRunStatus
from src.orchestrators.phase_registry import failure_mode_for, label_for

# Import config
from config import PIPELINE_FAILURE_MODES, PipelineFailureMode, PIPELINE_ALERT_THRESHOLDS

logger = logging.getLogger(__name__)


class _MemorySampler:
    """Background RSS sampler (process + children) for per-phase peak memory.

    Subprocess phases (dashboard build, model card) hold their working set in a
    child process, so children(recursive) are summed in — that is the number that
    actually decides whether the box stays under budget for a parallel agent.
    Degrades to 0.0 GB if psutil is unavailable.
    """

    def __init__(self, interval: float = 0.5):
        self._interval = interval
        self._proc = psutil.Process() if psutil else None
        self._peak = 0          # since last reset() — per phase
        self._global_peak = 0   # since start() — whole run
        self._stop = threading.Event()
        self._thread = None

    def _rss(self) -> int:
        if not self._proc:
            return 0
        try:
            total = self._proc.memory_info().rss
            for child in self._proc.children(recursive=True):
                try:
                    total += child.memory_info().rss
                except psutil.Error:
                    pass
            return total
        except psutil.Error:
            return 0

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            rss = self._rss()
            self._peak = max(self._peak, rss)
            self._global_peak = max(self._global_peak, rss)

    def start(self) -> None:
        if not self._proc or self._thread:
            return
        self._peak = self._global_peak = self._rss()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def reset(self) -> None:
        self._peak = self._rss()

    @property
    def peak_gb(self) -> float:
        return self._peak / 1024 ** 3

    @property
    def global_peak_gb(self) -> float:
        return self._global_peak / 1024 ** 3


class DailyPipelineOrchestrator:
    """Orchestrates the daily pipeline.

    The phase list, execution order, and display labels are owned by
    `src/orchestrators/phase_registry.py` (single source of truth) — not
    duplicated here, so this docstring can't drift out of sync with it.
    """

    def __init__(
        self,
        db_path: str = None,
        dry_run: bool = False,
        force: bool = False
    ):
        """
        Initialize orchestrator.

        Args:
            db_path: Path to DuckDB database (None = default)
            dry_run: If True, validate only (no writes)
            force: If True, ignore idempotency checks
        """
        if db_path is None:
            db_path = str(Path(__file__).parent.parent.parent / "data" / "market_data.duckdb")

        self.db_path = str(db_path)
        self.dry_run = dry_run
        self.force = force

        self._current_run_id = None  # set by _execute_phase, used by sub-phases for error logging

        logger.debug(f"[Orchestrator] Initialized (db={self.db_path}, dry_run={dry_run}, force={force})")

        # Initialize managers (delegate state tracking)
        self.run_manager = PipelineRunManager(self.db_path)
        self.view_manager = ViewManager(self.db_path)
        self.screener_manager = ScreenerManager(self.db_path)
        self.sepa_watchlist_manager = SepaWatchlistManager(self.db_path)

        # Initialize engines (delegate data I/O)
        self.data_repo = DataRepository(db_path=self.db_path)
        self.fund_engine = FundamentalEngine(db_path=self.db_path, source='yfinance')
        self.shares_engine = SharesEngine(self.db_path)
        self.macro_engine = MacroEngine(self.db_path)
        self.edgar_engine = EDGAREngine(db_path=self.db_path)

        # Initialize pipelines (delegate computation)
        self.feature_pipeline = FeaturePipeline(self.db_path)
        self.regime_pipeline = RegimePipeline(self.db_path)
        self.risk_calculator = RiskFiveFactorCalculator(self.db_path)

        # Universe backfill (only used when run_pipeline(universe_refresh=True))
        self.universe_backfill = UniverseBackfillEngine(self.db_path)

        # Per-phase peak-RSS telemetry (started in run_pipeline)
        self._mem_sampler = _MemorySampler()

    def run_pipeline(self, target_date: str = None, phase_1_only: bool = False, phase_2_only: bool = False, phase_3_only: bool = False, phase_4_only: bool = False, phase_5_only: bool = False, universe_refresh: bool = False) -> bool:
        """
        Execute the full daily pipeline (phases owned by phase_registry).

        Args:
            target_date: Date to process (None = yesterday's close)
            phase_1_only: If True, stop after Phase 1 (T1 ingestion only)
            phase_2_only: If True, run Phase 2 (screener membership) only — skips Phase 1
            phase_3_only: If True, run Phase 3 (T2 screener features) only — incremental
            phase_4_only: If True, run Phase 4 (T2 regime scores) only — incremental
            phase_5_only: If True, run Phase 5 (T3 SEPA features) only — incremental
            universe_refresh: If True, run quarterly universe discovery before Phase 1.
                              Default False — never runs automatically.

        Returns:
            True if all CRITICAL phases succeeded
        """
        # Pre-flight: DuckDB is single-writer. Fail fast with a clear, actionable
        # message if a foreign process (typically a notebook with a read-write
        # connection) holds the write lock — otherwise we'd crash mid-phase. The
        # non-zero exit propagates to the flow's Discord failure alert.
        if not self.dry_run:
            try:
                db.check_write_available(self.db_path)
            except db.DuckDBLockedError as e:
                logger.error(f"[Pipeline] ABORT - {e}")
                return False

        # Determine target date (latest completed US trading day if None)
        if target_date is None:
            from src.utils import get_latest_trading_day
            target_date = get_latest_trading_day().strftime('%Y-%m-%d')

        # Get actual trading day (accounts for weekends/holidays)
        actual_trading_day = self._get_last_trading_day(target_date)

        logger.info(f"[Pipeline] START | Trading Day: {actual_trading_day}")
        self._mem_sampler.start()
        pipeline_t0 = time.monotonic()

        # Track overall success (CRITICAL phases only)
        critical_success = True
        run_stats = {}

        # --- Phase-only shortcuts ---
        if phase_3_only:
            logger.info("[Pipeline] Single-phase mode: Phase 3 only")
            phase_success, phase_stats = self._execute_phase(
                "t2_screener",
                lambda: self._run_phase_3_t2_screener_incremental(actual_trading_day),
                actual_trading_day,
                skip_idempotency_check=True
            )
            return phase_success

        if phase_4_only:
            logger.info("[Pipeline] Single-phase mode: Phase 4 only")
            phase_success, phase_stats = self._execute_phase(
                "t2_regime",
                lambda: self._run_phase_4_t2_regime(actual_trading_day),
                actual_trading_day,
                skip_idempotency_check=True
            )
            return phase_success

        if phase_5_only:
            logger.info("[Pipeline] Single-phase mode: Phase 5 only")
            phase_success, phase_stats = self._execute_phase(
                "t3_features",
                lambda: self._run_phase_5_t3_features_incremental(actual_trading_day),
                actual_trading_day,
                skip_idempotency_check=True
            )
            return phase_success

        if phase_2_only:
            logger.info("[Pipeline] Single-phase mode: Phase 2 only")
        else:
            # Universe Refresh (only when explicitly requested)
            if universe_refresh:
                self._run_phase_1_1_quarterly_refresh(run_stats)

            # Phase 1: T1 Ingestion (PARALLEL)
            # Skip logic owned by update_cache: _get_stale_tickers returns [] when all fresh
            phase_success, phase_stats = self._execute_phase(
                "ingestion",
                lambda: self._run_phase_1_t1_ingestion(target_date, actual_trading_day),
                target_date,
                skip_idempotency_check=True
            )
            run_stats['ingestion'] = phase_stats
            # _execute_phase returns success=False only when a HALT phase failed
            # (WARN/SKIP are absorbed as success there), so `not phase_success`
            # already means "a critical phase died" — no failure-mode recheck needed.
            if not phase_success:
                critical_success = False
                return False

            # Price Quality Gate (read + conditional same-run retry). Non-blocking
            # by construction (never raises). Placed BEFORE the phase_1_only
            # early-return so --phase-1-only runs the gate too.
            run_stats['price_quality_gate'] = self._run_phase_1_5_quality_gate(
                target_date, actual_trading_day
            )

            # Plausibility gate (FAIL-level audit ceilings only). Non-halting;
            # the R2 sync withholds the publish while it's red.
            run_stats['plausibility_gate'] = self._run_phase_1_6_plausibility_gate()

            if phase_1_only:
                return critical_success

        # Phase 2: Screener Membership
        phase_success, phase_stats = self._execute_phase(
            "screener_membership",
            lambda: self._run_phase_2_screener_membership(target_date),
            target_date
        )
        run_stats['screener_membership'] = phase_stats
        if not phase_success:
            critical_success = False
            return False

        if phase_2_only:
            return critical_success

        # Phase 3: T2 Screener Features (incremental — auto-fills gaps)
        phase_success, phase_stats = self._execute_phase(
            "t2_screener",
            lambda: self._run_phase_3_t2_screener_incremental(actual_trading_day),
            target_date,
            skip_idempotency_check=True
        )
        run_stats['t2_screener'] = phase_stats
        if not phase_success:
            critical_success = False
            return False
        if phase_stats.get('rows_processed', 0) > 0:
            self.run_manager.record_write('t2_screener_features', phase_stats['rows_processed'], 't2_screener')

        # Phase 4: T2 Regime Scores
        phase_success, phase_stats = self._execute_phase(
            "t2_regime",
            lambda: self._run_phase_4_t2_regime(target_date),
            target_date
        )
        run_stats['t2_regime'] = phase_stats
        if not phase_success:
            critical_success = False
            return False

        # Phase 4b: SEPA Watchlist Update — must run AFTER t2 features are written
        # (update_daily reads t2_screener_features for the target date) and BEFORE
        # T3 (compute_t3_features filters universe via sepa_watchlist).
        phase_success, phase_stats = self._execute_phase(
            "sepa_watchlist",
            lambda: self._run_phase_4b_sepa_watchlist(actual_trading_day),
            target_date
        )
        run_stats['sepa_watchlist'] = phase_stats
        if not phase_success:
            critical_success = False
            return False

        # Phase 5: T3 SEPA Features (incremental — auto-fills gaps)
        phase_success, phase_stats = self._execute_phase(
            "t3_features",
            lambda: self._run_phase_5_t3_features_incremental(actual_trading_day),
            target_date,
            skip_idempotency_check=True
        )
        run_stats['t3_features'] = phase_stats
        if not phase_success:
            critical_success = False
            return False
        if phase_stats.get('rows_processed', 0) > 0:
            self.run_manager.record_write('t3_sepa_features', phase_stats['rows_processed'], 't3_features')

        # Phase 6: View Refresh
        phase_success, phase_stats = self._execute_phase(
            "views",
            lambda: self._run_phase_6_views(target_date),
            target_date
        )
        run_stats['views'] = phase_stats
        # (no record_write here: screener_watchlist is a VIEW since 2026-07-18 —
        # the views phase no longer materialises any table)
        if not phase_success:
            critical_success = False
            return False

        # Phase 7: Training Cache Refresh
        phase_success, phase_stats = self._execute_phase(
            "cache",
            lambda: self._run_phase_7_cache(target_date),
            target_date
        )
        run_stats['cache'] = phase_stats
        if phase_success and phase_stats.get('rows_processed', 0) > 0:
            self.run_manager.record_write('d2_training_cache', phase_stats['rows_processed'], 'cache')
        if not phase_success:
            critical_success = False
            return False

        # Phase 7.4: Prod-model scoring (best-effort). Materializes today's scores
        # into daily_predictions for BOTH cohorts BEFORE the slim DB is built/
        # uploaded, so the dashboard reads fresh, materialized scores (never live).
        phase_success, phase_stats = self._execute_phase(
            "scoring",
            lambda: self._run_phase_7_4_scoring(target_date),
            target_date,
            skip_idempotency_check=True,
        )
        run_stats['scoring'] = phase_stats
        if not phase_success:
            critical_success = False
            return False

        # Phase 7.45: Weather gauge (best-effort). Recompute the deploy-posture
        # state BEFORE the slim DB build (7.5) so weather_gauge ships in it.
        phase_success, phase_stats = self._execute_phase(
            "weather",
            lambda: self._run_phase_7_45_weather(target_date),
            target_date,
        )
        run_stats['weather'] = phase_stats
        if not phase_success:
            critical_success = False
            return False

        # Phase 7.46: Sector-breadth heatmap snapshot (best-effort). Materialize
        # before the slim DB build (7.5) so sector_breadth ships in it.
        phase_success, phase_stats = self._execute_phase(
            "sector_breadth",
            lambda: self._run_phase_7_46_sector_breadth(),
            target_date,
        )
        run_stats['sector_breadth'] = phase_stats
        if not phase_success:
            critical_success = False
            return False

        # Phase 7.47: Portfolio NAV mark (best-effort). Must run AFTER the day's
        # close is ingested and BEFORE the slim DB build (7.5) so the row ships.
        phase_success, phase_stats = self._execute_phase(
            "portfolio_nav",
            lambda: self._run_phase_7_47_portfolio_nav(target_date),
            target_date,
        )
        run_stats['portfolio_nav'] = phase_stats
        if not phase_success:
            critical_success = False
            return False

        # Phase 7.5: Slim dashboard DB rebuild (best-effort; a slow rebuild must
        # never block the daily pipeline). Snapshots the freshly-refreshed cache
        # + latest features into data/dashboard.duckdb for cross-device sync.
        phase_success, phase_stats = self._execute_phase(
            "dashboard_db",
            lambda: self._run_phase_7_5_dashboard_db(),
            target_date
        )
        run_stats['dashboard_db'] = phase_stats
        if not phase_success:
            critical_success = False
            return False

        # R2 Sync: upload slim DB (best-effort; skipped if R2 creds absent).
        # Withheld while the plausibility gate is red — the remote dashboard stays
        # on its last clean snapshot rather than publishing implausible data.
        gate_failures = run_stats.get('plausibility_gate', {}).get('failures')
        if gate_failures:
            logger.warning(
                f"[R2 Sync] Publish withheld: plausibility gate failed "
                f"({gate_failures}). Remote dashboard stays on last clean snapshot."
            )
            run_stats['r2_sync'] = {'rows_processed': 0, 'skipped': 'plausibility_gate'}
        else:
            phase_success, phase_stats = self._execute_phase(
                "r2_sync",
                lambda: self._run_phase_7_6_r2_sync(),
                target_date
            )
            run_stats['r2_sync'] = phase_stats
            if not phase_success:
                critical_success = False
                return False

        # Phase 8: Monitoring (ALWAYS RUN)
        phase_success, phase_stats = self._execute_phase(
            "monitoring",
            lambda: self._run_phase_8_monitoring(target_date, run_stats),
            target_date
        )
        run_stats['monitoring'] = phase_stats
        if not phase_success:
            critical_success = False
            return False

        # Model card: Advisory model-card rebuild for the prod model (WARN-only).
        # Skips when the card is already fresh; a failure here never halts the
        # daily pipeline (the card is informational, not a gate).
        # The "Phase 10" label (with no Phase 9) is a cosmetic display artifact of
        # the old positional scheme — it lives in the phase registry's `label`
        # only. The stable `id` ("model_card") is order-independent, so this
        # historical gap no longer leaks into persisted keys. See
        # docs/session_logs/sprint_12/pipeline_phase_keys.md.
        phase_success, phase_stats = self._execute_phase(
            "model_card",
            lambda: self._run_phase_10_model_card(target_date),
            target_date,
            skip_idempotency_check=True,
        )
        run_stats['model_card'] = phase_stats

        phases_run = len(run_stats)
        logger.info(
            f"[Pipeline] DONE | {phases_run} phases | "
            f"{'OK' if critical_success else 'FAILED'} | "
            f"{time.monotonic() - pipeline_t0:.0f}s wall | "
            f"peak RSS {self._mem_sampler.global_peak_gb:.1f} GB"
        )

        return critical_success

    def _execute_phase(
        self,
        phase_name: str,
        phase_func: callable,
        target_date: str,
        skip_idempotency_check: bool = False
    ) -> Tuple[bool, Dict]:
        """
        Execute a single phase with error handling and tracking.

        Args:
            phase_name: Stable phase id from the phase registry (e.g. 't2_screener')
            phase_func: Function to execute
            target_date: Date being processed
            skip_idempotency_check: If True, bypass pipeline_runs check (used for Phase 1 data freshness)

        Returns:
            (success: bool, stats: dict)
        """
        # Human-readable label from the registry: "t2_screener" -> "Phase 3 · T2 Features"
        label = label_for(phase_name)

        # Title banner so each phase's output is visually delimited in the log.
        logger.info(f"========== {label} ==========")

        # Check idempotency (skip if already completed and not force).
        # INFO (not DEBUG) so every phase leaves a trace — a skipped phase is
        # otherwise indistinguishable from one that never ran in the log.
        if not skip_idempotency_check and not self.force and self.run_manager.is_phase_completed(target_date, phase_name):
            logger.info(f"[{label}] skipped (already completed for {target_date})")
            return True, {'status': 'skipped', 'reason': 'already_completed'}

        # Start phase tracking
        run_id = None
        if not self.dry_run:
            run_id = self.run_manager.start_phase(target_date, phase_name)
        self._current_run_id = run_id

        t0 = time.monotonic()
        self._mem_sampler.reset()

        try:
            stats = phase_func()

            # Complete phase tracking
            if not self.dry_run:
                self.run_manager.complete_phase(
                    run_id,
                    PipelineRunStatus.SUCCESS,
                    rows_processed=stats.get('rows_processed')
                )

            logger.info(
                f"[{label}] done in {time.monotonic() - t0:.1f}s | "
                f"peak RSS {self._mem_sampler.peak_gb:.1f} GB"
            )
            return True, stats

        except Exception as e:
            error_msg = str(e)
            logger.error(
                f"[{label}] FAILED after {time.monotonic() - t0:.1f}s "
                f"(peak RSS {self._mem_sampler.peak_gb:.1f} GB): {error_msg}",
                exc_info=True,
            )

            if not self.dry_run:
                self.run_manager.complete_phase(
                    run_id,
                    PipelineRunStatus.FAILED,
                    error_message=error_msg
                )

            failure_mode = failure_mode_for(phase_name)

            if failure_mode == PipelineFailureMode.HALT:
                return False, {'status': 'failed', 'error': error_msg}
            elif failure_mode == PipelineFailureMode.WARN:
                logger.warning(f"[{label}] Non-critical, continuing")
                return True, {'status': 'warned', 'error': error_msg}
            else:  # SKIP
                logger.info(f"[{label}] Optional, skipping")
                return True, {'status': 'skipped', 'error': error_msg}

    # ========================================================================
    # HELPER METHODS (Data Freshness Checks)
    # ========================================================================

    def _get_last_trading_day(self, target_date: str) -> str:
        """
        Get the last actual trading day on or before target_date.

        Strategy:
          1. SPY download from yfinance (authoritative market calendar, not affected by DB state).
          2. If SPY fails, fall back to weekend arithmetic (no holidays).
          3. DB query (MAX date in price_data) is NOT used — it would return the last
             ingested date, creating a bootstrap deadlock where the pipeline never advances.
        """
        import yfinance as yf
        try:
            end_date = datetime.strptime(target_date, '%Y-%m-%d')
            start_date = end_date - timedelta(days=7)
            spy = yf.download('SPY', start=start_date.strftime('%Y-%m-%d'),
                             end=(end_date + timedelta(days=1)).strftime('%Y-%m-%d'),
                             progress=False, auto_adjust=True)
            if not spy.empty:
                last_day = spy.index[-1].strftime('%Y-%m-%d')
                logger.debug(f"[Pipeline] Trading day resolved: {last_day} (via SPY)")
                return last_day
        except Exception as e:
            logger.warning(f"[Pipeline] SPY calendar lookup failed: {e}")

        # Last resort: skip weekends arithmetically
        dt = datetime.strptime(target_date, '%Y-%m-%d')
        while dt.weekday() >= 5:  # Saturday=5, Sunday=6
            dt -= timedelta(days=1)
        last_day = dt.strftime('%Y-%m-%d')
        logger.warning(f"[Pipeline] Using weekend-adjusted fallback: {last_day}")
        return last_day

    def _should_refresh_earnings_calendar(self, trading_day: str) -> bool:
        """Check if earnings calendar needs a refresh.

        Gates on the last successful run of phase_1_earnings_calendar_refresh
        in pipeline_runs. Triggers when older than EARNINGS_CALENDAR_REFRESH_DAYS
        (default 7).

        The previous heuristic queried earnings_calendar.updated_at, but
        update_fundamentals touches that timestamp via _mark_earnings_confirmed
        almost every day — so the gate never opened.
        """
        from config import EARNINGS_CALENDAR_REFRESH_DAYS

        conn = db.connect(self.db_path, read_only=True)
        try:
            row = conn.execute("""
                SELECT MAX(completed_at)
                FROM pipeline_runs
                WHERE phase_name = 'phase_1_earnings_calendar_refresh'
                  AND status = 'success'
            """).fetchone()
            last_success = row[0] if row else None
        finally:
            conn.close()

        if last_success is None:
            logger.info("[Ingestion] Earnings calendar: no prior successful refresh — triggering")
            return True

        age_days = (datetime.now() - last_success).days
        should = age_days >= EARNINGS_CALENDAR_REFRESH_DAYS
        if should:
            logger.info(
                f"[Ingestion] Earnings calendar: last refresh {age_days}d ago "
                f"(>= {EARNINGS_CALENDAR_REFRESH_DAYS}d) — triggering"
            )
        else:
            logger.debug(
                f"[Ingestion] Earnings calendar: last refresh {age_days}d ago "
                f"(< {EARNINGS_CALENDAR_REFRESH_DAYS}d) — skipping"
            )
        return should

    def _run_phase_1_1_quarterly_refresh(self, run_stats: Dict) -> None:
        """
        Quarterly Universe Refresh — only runs when run_pipeline(universe_refresh=True).

        Discovers newly-listed tickers, writes profiles, backfills price + shares.
        Non-critical: pipeline continues on failure.
        """
        try:
            new_tickers = self.universe_backfill.quarterly_refresh()
            logger.info(f"[Ingestion] Universe refresh: {new_tickers} new tickers added")
            run_stats['universe_refresh'] = {'status': 'success', 'new_tickers': new_tickers}
        except Exception as e:
            logger.warning(f"[Ingestion] Universe refresh FAILED (non-critical): {e}")
            run_stats['universe_refresh'] = {'status': 'failed', 'error': str(e)}

    # ========================================================================
    # PHASE EXECUTION METHODS (Delegate to Engines/Pipelines/Managers)
    # ========================================================================

    def _compute_price_coverage(self, trading_day: str) -> float:
        """
        % of active tickers with a price row EXACTLY ON trading_day.

        Deliberately stricter than audit_t1_data_quality.py's STALE_PRICE_DAYS=5
        business-day window. A same-run gate wants *today's* prices, not "traded
        sometime this week" — a ticker last seen 3 days ago passes the audit's
        staleness check but is exactly what Phase 1.5 must re-ingest. The two
        definitions differ by design; only the THRESHOLD numbers are centralised.
        """
        conn = db.connect(self.db_path, read_only=True)
        try:
            total, covered = conn.execute("""
                SELECT
                    (SELECT COUNT(*) FROM company_profiles WHERE is_active = TRUE),
                    COUNT(DISTINCT p.ticker)
                FROM price_data p
                INNER JOIN company_profiles cp ON p.ticker = cp.ticker
                WHERE cp.is_active = TRUE AND p.date = ?
            """, [trading_day]).fetchone()
        finally:
            conn.close()
        return (covered / total * 100) if total else 100.0

    def _get_missing_price_tickers(self, trading_day: str) -> List[str]:
        """Active tickers with no price row on trading_day."""
        conn = db.connect(self.db_path, read_only=True)
        try:
            rows = conn.execute("""
                SELECT cp.ticker
                FROM company_profiles cp
                LEFT JOIN price_data p
                  ON p.ticker = cp.ticker AND p.date = ?
                WHERE cp.is_active = TRUE AND p.ticker IS NULL
                ORDER BY cp.ticker
            """, [trading_day]).fetchall()
        finally:
            conn.close()
        return [r[0] for r in rows]

    def _run_phase_1_5_quality_gate(
        self,
        target_date: str,
        latest_trading_day: str,
    ) -> Dict:
        """
        Phase 1.5: T1 price coverage gate + same-run retry for partial failures.

        Read-only check + targeted re-ingest. NEVER halts — warns and records.
        The HALT mode on phase_1_t1_price already covers catastrophic failure;
        this handles partial failures that don't raise (e.g. a yfinance batch
        timing out and marking ~150 tickers stale without an exception).
        """
        from config import PIPELINE_ALERT_THRESHOLDS
        retry_threshold = PIPELINE_ALERT_THRESHOLDS['t1_price_coverage_retry_pct']
        warn_threshold = PIPELINE_ALERT_THRESHOLDS['t1_price_coverage_warn_pct']

        coverage_pct = self._compute_price_coverage(latest_trading_day)
        logger.info(f"[Price Quality Gate] Price coverage: {coverage_pct:.1f}%")

        if coverage_pct >= retry_threshold:
            return {'coverage_pct': coverage_pct, 'retry': False, 'status': 'ok'}

        missing = self._get_missing_price_tickers(latest_trading_day)
        logger.warning(
            f"[Price Quality Gate] Coverage {coverage_pct:.1f}% < {retry_threshold}% — "
            f"retrying {len(missing)} tickers"
        )

        if missing:
            self.data_repo.update_cache(
                tickers=missing,
                source='yfinance',
                latest_trading_day=latest_trading_day,
            )

        coverage_pct_after = self._compute_price_coverage(latest_trading_day)
        logger.info(f"[Price Quality Gate] Coverage after retry: {coverage_pct_after:.1f}%")

        if coverage_pct_after < warn_threshold:
            logger.warning(
                f"[Price Quality Gate] Coverage still {coverage_pct_after:.1f}% after retry — "
                f"downstream features will use stale prices for {len(missing)} tickers"
            )

        return {
            'coverage_pct': coverage_pct_after,
            'retry': True,
            'missing_count': len(missing),
            'status': 'warned' if coverage_pct_after < warn_threshold else 'recovered',
        }

    def _run_phase_1_6_plausibility_gate(self) -> Dict:
        """
        Phase 1.6: fast plausibility gate on freshly-ingested T1 data.

        Runs only the FAIL-level plausibility ceilings from the T1 audit (a few
        seconds total) so impossible values are caught BEFORE features, scoring
        and the R2 publish consume them — the full Phase 8 audit is post-hoc.
        Non-halting: records failures in run_stats; Phase 7.6 withholds the R2
        publish while any fire (stale-but-clean beats fresh-but-dirty).
        """
        from config import T1_PLAUSIBILITY_BOUNDS as b
        checks = {
            'absurd_share_count':
                f"SELECT COUNT(*) FROM shares_history WHERE shares_outstanding > {b['shares_max']}",
            'share_scale_dirt': f"""
                WITH med AS (SELECT ticker, MEDIAN(shares_outstanding) med
                             FROM shares_history WHERE shares_outstanding > 0 GROUP BY ticker)
                SELECT COUNT(*) FROM shares_history s JOIN med m USING(ticker)
                WHERE s.shares_outstanding > {b['shares_scale_abs']}
                  AND s.shares_outstanding > {b['shares_scale_ratio']} * m.med""",
            'absurd_close_price':
                f"SELECT COUNT(*) FROM price_data WHERE close > {b['close_max']}",
            'absurd_implied_market_cap': f"""
                SELECT COUNT(*) FROM shares_history s JOIN price_data p USING(ticker, date)
                WHERE s.shares_outstanding * p.close > {b['implied_cap_max']}""",
            'corrupt_ohlc_bars': f"""
                SELECT COUNT(*) FROM price_data
                WHERE (high < close OR low > close OR high < low)
                  AND GREATEST(CASE WHEN high < close THEN close / NULLIF(high, 0) ELSE 1 END,
                               CASE WHEN low > close THEN low / NULLIF(close, 0) ELSE 1 END,
                               CASE WHEN high < low THEN low / NULLIF(high, 0) ELSE 1 END) - 1
                      > {b['ohlc_excess_fail']}""",
        }
        failures: Dict[str, int] = {}
        conn = db.connect(self.db_path, read_only=True)
        try:
            for name, sql in checks.items():
                n = conn.execute(sql).fetchone()[0]
                if n:
                    failures[name] = n
        finally:
            conn.close()

        if failures:
            logger.error(
                f"[Plausibility Gate] Plausibility gate FAILED: {failures} — R2 publish will be "
                f"withheld. Run scripts/clean_dirty_shares_price.py and check engine "
                f"clamp warnings in the Phase 1 log."
            )
        else:
            logger.info("[Plausibility Gate] Plausibility gate: all clean")
        return {'status': 'fail' if failures else 'ok', 'failures': failures}

    def _run_phase_1_t1_ingestion(self, target_date: str, latest_trading_day: str) -> Dict:
        """
        Phase 1: T1 ingestion (SEQUENTIAL).

        Sub-phases run in order:
        1.1: price_data (DataRepository) - Update stale tickers only
        1.2: fundamentals (FundamentalEngine) - all active tickers
        1.3: shares_outstanding (SharesEngine) - all active tickers
        1.4: macro_data (MacroEngine) - Update macro indicators

        Returns:
            {'rows_processed': N, 'sub_phases': {...}}
        """
        # Resolve active tickers (blacklisted tickers already purged from company_profiles)
        # equity_tickers excludes ETF/INDEX/UNKNOWN — used for fundamentals/earnings
        # which yfinance cannot provide for non-equity instruments.
        conn = db.connect(self.db_path, read_only=True)
        try:
            active_tickers = [t[0] for t in conn.execute(
                "SELECT ticker FROM company_profiles WHERE is_active = TRUE ORDER BY ticker"
            ).fetchall()]
            equity_tickers = [t[0] for t in conn.execute(
                "SELECT ticker FROM company_profiles "
                "WHERE is_active = TRUE AND COALESCE(ticker_type, 'EQUITY') = 'EQUITY' "
                "ORDER BY ticker"
            ).fetchall()]
        finally:
            conn.close()

        if latest_trading_day is None:
            latest_trading_day = self._get_last_trading_day(target_date)

        # Pre-compute stale tickers
        stale_tickers = self.data_repo._get_stale_tickers(latest_trading_day)

        logger.info(f"[Ingestion] T1 Ingestion | active={len(active_tickers)}, stale={len(stale_tickers)}")

        results = {}

        # Price
        if stale_tickers:
            try:
                result = self.data_repo.update_cache(
                    tickers=stale_tickers,
                    source='yfinance',
                    latest_trading_day=latest_trading_day,
                )
                ticker_results = result if isinstance(result, dict) else {}
                total = len(ticker_results)
                ok_count = sum(1 for ok in ticker_results.values() if ok)
                failed = total - ok_count
                failure_rate = failed / total if total > 0 else 0.0
                results['price'] = {'success': True, 'ok': ok_count, 'failed': failed}
                logger.info(f"[Ingestion] Price: {ok_count}/{total} OK, {failed} failed ({failure_rate:.1%})")
                if ok_count > 0:
                    self.run_manager.record_write('price_data', ok_count, 'phase_1_t1_price')
                if self._current_run_id and self.data_repo.last_errors:
                    self.run_manager.record_errors(
                        self._current_run_id, 'phase_1_t1_price', self.data_repo.last_errors
                    )
                if failure_rate > 0.5:
                    logger.warning(
                        f"[Ingestion] High failure rate {failure_rate:.1%} "
                        f"({failed}/{total} tickers) — will retry next run"
                    )
            except Exception as e:
                results['price'] = {'success': False, 'error': str(e)}
                logger.error(f"[Ingestion] Price FAILED: {e}", exc_info=True)
                if PIPELINE_FAILURE_MODES.get("phase_1_t1_price") == PipelineFailureMode.HALT:
                    raise
        else:
            logger.info("[Ingestion] Price: all fresh, skipped")
            results['price'] = {'success': True, 'ok': 0, 'failed': 0}

        # Earnings Calendar (weekly) — equities only (ETFs/indices have no earnings).
        # Tracked as its own phase so the gate query in _should_refresh_earnings_calendar
        # has an authoritative signal — independent of any row-touch side effects.
        if equity_tickers and self._should_refresh_earnings_calendar(latest_trading_day):
            ec_run_id = self.run_manager.start_phase(
                target_date=latest_trading_day,
                phase_name='phase_1_earnings_calendar_refresh',
                metadata={'ticker_count': len(equity_tickers)},
            )
            try:
                rows = self.fund_engine.refresh_earnings_calendar(equity_tickers)
                results['earnings_calendar'] = {'success': True, 'rows_written': rows}
                logger.info(f"[Ingestion] Earnings calendar: {rows} rows refreshed")
                self.run_manager.complete_phase(
                    ec_run_id, PipelineRunStatus.SUCCESS, rows_processed=rows
                )
            except Exception as e:
                results['earnings_calendar'] = {'success': False, 'error': str(e)}
                logger.warning(f"[Ingestion] Earnings calendar FAILED (non-critical): {e}")
                self.run_manager.complete_phase(
                    ec_run_id, PipelineRunStatus.FAILED, error_message=str(e)
                )

        # Fundamentals — equities only (ETFs/indices have no IS/BS/CF)
        if equity_tickers:
            try:
                result = self.fund_engine.update_fundamentals(
                    tickers=equity_tickers,
                    target_date=target_date,
                    force=False,
                )
                fund_results = result if isinstance(result, dict) else {}
                fund_ok = sum(1 for v in fund_results.values() if v)
                fund_failed = len(fund_results) - fund_ok
                # DQ: tickers that wrote rows but whose newest quarter has a NULL
                # filing_date (yfinance earnings endpoint failed). Non-fatal — these
                # are OK writes — but the per-run count is otherwise unobservable
                # (no pipeline_error_log entry). Surface it without flipping status.
                null_filing_written = len(self.fund_engine._null_filing_writes)
                results['fundamentals'] = {
                    'success': True, 'ok': fund_ok, 'failed': fund_failed,
                    'null_filing_written': null_filing_written,
                }
                logger.info(
                    f"[Ingestion] Fundamentals: {fund_ok}/{len(fund_results)} OK"
                    + (f" | DQ: {null_filing_written} wrote NULL filing_date "
                       f"(earnings fetch failed; EDGAR backfill will repair)"
                       if null_filing_written else "")
                )
                if fund_ok > 0:
                    self.run_manager.record_write('fundamentals', fund_ok, 'phase_1_t1_fundamentals')
                if self._current_run_id and self.fund_engine.last_errors:
                    self.run_manager.record_errors(
                        self._current_run_id, 'phase_1_t1_fundamentals', self.fund_engine.last_errors
                    )
                if self._current_run_id and not self.dry_run:
                    self.run_manager.update_phase_metadata(
                        self._current_run_id,
                        {'null_filing_date_written': null_filing_written},
                    )
                self._check_filing_date_quality(equity_tickers)
            except Exception as e:
                results['fundamentals'] = {'success': False, 'error': str(e)}
                logger.error(f"[Ingestion] Fundamentals FAILED: {e}", exc_info=True)

        # cik_map refresh (weekly) — keeps ticker→CIK lookups current for the
        # EDGAR filing-date backfill below. Cheap (~1 HTTP call, ~10K rows).
        if self._should_refresh_cik_map():
            try:
                results['cik_map_refresh'] = self._run_phase_1_cik_map_refresh(latest_trading_day)
            except Exception as e:
                results['cik_map_refresh'] = {'success': False, 'error': str(e)}
                logger.warning(f"[Ingestion] cik_map refresh FAILED (non-critical): {e}")

        # Filing-date backfill — fills filing_date for rows where it is currently
        # NULL, using SEC EDGAR as the authoritative source. Runs AFTER fundamentals
        # (any rows just upserted are eligible) and AFTER the cik_map refresh.
        if equity_tickers:
            try:
                fb_result = self._run_phase_1_filing_date_backfill(latest_trading_day)
                results['filing_date_backfill'] = fb_result
            except Exception as e:
                results['filing_date_backfill'] = {'success': False, 'error': str(e)}
                logger.warning(f"[Ingestion] Filing-date backfill FAILED (non-critical): {e}")

        # Shares — equities only (ETFs report AUM, not shares outstanding)
        if equity_tickers:
            try:
                result = self.shares_engine.update(
                    tickers=equity_tickers, latest_trading_day=latest_trading_day, max_workers=8
                )
                results['shares'] = {'success': True, 'rows_written': result}
                logger.info(f"[Ingestion] Shares: {result} rows")
                if result and result > 0:
                    self.run_manager.record_write('shares_outstanding', result, 'phase_1_t1_shares')
            except Exception as e:
                results['shares'] = {'success': False, 'error': str(e)}
                logger.error(f"[Ingestion] Shares FAILED: {e}", exc_info=True)

        # Macro — two writers, two tables:
        #   ingest_daily_macro()  -> t1_macro    (wide: SPY/QQQ/VIX OHLCV)
        #   update_macro_cache()  -> macro_data  (long: FRED series + VIX, consumed
        #                                         by risk_5_factor + m03_regime)
        # Both must run daily. Previously only t1_macro was written; macro_data
        # was orphaned and drifted ~17d stale, silently freezing 5-factor risk
        # scores at their last manual-backfill date.
        try:
            t1_rows = self.macro_engine.ingest_daily_macro(start_date=latest_trading_day, force=False)
            t1_rows = t1_rows.get('rows_written', 0) if isinstance(t1_rows, dict) else (t1_rows or 0)

            # Diff macro_data row count to get true inserted count (update_macro_cache
            # returns per-series total cache size, not inserts).
            conn = db.connect(self.db_path, read_only=True)
            try:
                md_before = conn.execute("SELECT COUNT(*) FROM macro_data").fetchone()[0]
            finally:
                conn.close()
            self.macro_engine.update_macro_cache(force=False, write_db=True)
            conn = db.connect(self.db_path, read_only=True)
            try:
                md_after = conn.execute("SELECT COUNT(*) FROM macro_data").fetchone()[0]
            finally:
                conn.close()
            md_rows = md_after - md_before

            # Interior-gap self-heal. ingest_daily_macro writes ONLY the target
            # date, so any date missed (outage, rate-limited fetch) stays a hole
            # forever — the incremental path starts from MAX(date) and never looks
            # back. Derived from local price_data/macro_data, so unlike
            # backfill_t1_macro.py this cannot rate-limit or silently no-op.
            healed = self._heal_t1_macro_gaps()
            if healed:
                self.run_manager.record_write('t1_macro', healed, 'phase_1_t1_macro_heal')

            results['macro'] = {
                'success': True,
                't1_macro_rows': t1_rows,
                'macro_data_rows': md_rows,
                't1_macro_healed': healed,
            }
            logger.info(f"[Ingestion] Macro: t1_macro +{t1_rows} rows, macro_data +{md_rows} rows")
            if t1_rows and t1_rows > 0:
                self.run_manager.record_write('t1_macro', t1_rows, 'phase_1_t1_macro')
            if md_rows and md_rows > 0:
                self.run_manager.record_write('macro_data', md_rows, 'phase_1_t1_macro')
        except Exception as e:
            results['macro'] = {'success': False, 'error': str(e)}
            logger.error(f"[Ingestion] Macro FAILED: {e}", exc_info=True)

        # CAPE_OURS: self-computed valuation pillar (Shiller's own data is dormant).
        # Monthly series computed over already-ingested price/fundamentals/shares; isolated
        # try so a compute hiccup never fails the macro phase. See cape_engine.py.
        try:
            from src.cape_engine import CapeEngine
            cape_rows = CapeEngine(self.db_path).update()
            results['cape_ours'] = {'success': True, 'rows': cape_rows}
            logger.info(f"[Ingestion] CAPE_OURS: upserted {cape_rows} months")
            if cape_rows:
                self.run_manager.record_write('macro_data', cape_rows, 'phase_1_cape_ours')
        except Exception as e:
            results['cape_ours'] = {'success': False, 'error': str(e)}
            logger.error(f"[Ingestion] CAPE_OURS FAILED: {e}", exc_info=True)

        return {
            'rows_processed': len(active_tickers),
            'sub_phases': results
        }

    # Trailing window (calendar days) scanned for t1_macro interior holes each run.
    # Matches T3_BACKFILL_LOOKBACK_DAYS in spirit: wide enough to span a multi-day
    # outage without rescanning 26 years of history nightly.
    T1_MACRO_HEAL_LOOKBACK_DAYS = 120

    def _heal_t1_macro_gaps(self, lookback_days: int = None) -> int:
        """Fill interior t1_macro holes from already-ingested local tables.

        `ingest_daily_macro(start_date=trading_day)` writes only that one date, and
        the incremental path resumes from MAX(date) — so a date missed during an
        outage is never revisited. `backfill_t1_macro.py` is not a reliable repair:
        it refetches from yfinance and prints "[OK] ... Rows written: 0" on a
        rate-limit, i.e. failure that looks like success.

        Every t1_macro column is derivable from data already in the DB — SPY/QQQ
        OHLCV from `price_data`, VIX from `macro_data` — so this heals offline with
        no network call and no silent-failure path. INSERT ... SELECT with a NOT
        EXISTS guard: never overwrites a populated row.

        Expected trading days come from SPY's own `price_data` rows (the market
        calendar the rest of the pipeline already trusts).
        """
        lookback = lookback_days if lookback_days is not None else self.T1_MACRO_HEAL_LOOKBACK_DAYS
        con = db.connect(self.db_path)
        try:
            healed = con.execute(f"""
                INSERT INTO t1_macro
                    (date, spy_close, spy_volume, spy_high, spy_low,
                     qqq_close, qqq_volume, qqq_high, qqq_low, vix_close)
                SELECT
                    spy.date,
                    spy.close, spy.volume, spy.high, spy.low,
                    qqq.close, qqq.volume, qqq.high, qqq.low,
                    -- macro_data carries market quotes in `close` and FRED series
                    -- in `value`; VIX is a quote, so `close` wins. COALESCE keeps
                    -- this correct if a VIX row ever arrives via the FRED path.
                    COALESCE(vix.close, vix.value)
                FROM price_data spy
                LEFT JOIN price_data qqq
                       ON qqq.ticker = 'QQQ' AND qqq.date = spy.date
                LEFT JOIN macro_data vix
                       ON vix.symbol = 'VIX' AND vix.date = spy.date
                WHERE spy.ticker = 'SPY'
                  AND spy.date >= CURRENT_DATE - INTERVAL {int(lookback)} DAY
                  AND NOT EXISTS (
                      SELECT 1 FROM t1_macro m WHERE m.date = spy.date
                  )
                RETURNING date
            """).fetchall()
        finally:
            con.close()

        if healed:
            dates = sorted(r[0].strftime('%Y-%m-%d') for r in healed)
            logger.warning(
                f"[Ingestion] t1_macro: healed {len(dates)} interior gap date(s) "
                f"from local price_data/macro_data ({dates[0]} .. {dates[-1]})"
            )
        return len(healed)

    def _should_refresh_cik_map(self) -> bool:
        """Check if cik_map needs a refresh.

        Gates on the last successful run of phase_1_cik_map_refresh in
        pipeline_runs. Triggers when older than CIK_MAP_REFRESH_DAYS (default 7).
        SEC adds new tickers slowly; weekly is plenty.
        """
        from config import CIK_MAP_REFRESH_DAYS

        conn = db.connect(self.db_path, read_only=True)
        try:
            row = conn.execute("""
                SELECT MAX(completed_at)
                FROM pipeline_runs
                WHERE phase_name = 'phase_1_cik_map_refresh'
                  AND status = 'success'
            """).fetchone()
            last_success = row[0] if row else None
        finally:
            conn.close()

        if last_success is None:
            logger.info("[Ingestion] cik_map: no prior successful refresh — triggering")
            return True

        age_days = (datetime.now() - last_success).days
        return age_days >= CIK_MAP_REFRESH_DAYS

    def _run_phase_1_cik_map_refresh(self, trading_day: str) -> Dict:
        """Phase 1.x: refresh ticker→CIK map from SEC (weekly cadence)."""
        ck_run_id = self.run_manager.start_phase(
            target_date=trading_day,
            phase_name='phase_1_cik_map_refresh',
            metadata={},
        )
        try:
            n = self.edgar_engine.refresh_cik_map()
            logger.info(f"[Ingestion] cik_map: {n} rows after refresh")
            self.run_manager.complete_phase(
                ck_run_id, PipelineRunStatus.SUCCESS, rows_processed=n
            )
            return {'success': True, 'rows': n}
        except Exception as e:
            self.run_manager.complete_phase(
                ck_run_id, PipelineRunStatus.FAILED, error_message=str(e)
            )
            raise

    def _run_phase_1_filing_date_backfill(self, trading_day: str) -> Dict:
        """Phase 1.x: backfill filing_date for rows where it is currently NULL,
        using SEC EDGAR as the authoritative source.

        Eligible: source='yfinance' AND filing_date IS NULL AND period_end older
        than FILING_BACKFILL_MIN_AGE_DAYS. Recent quarters are excluded because
        the 10-Q filing typically lands ≥30d after period_end — letting them
        roll forward to a later run is correct.

        Bounded by FILING_BACKFILL_MAX_TICKERS per run (priority: most-missing
        first). Tracked as its own phase for heatmap visibility.
        """
        from config import (
            FILING_BACKFILL_MAX_TICKERS,
            FILING_BACKFILL_MIN_AGE_DAYS,
        )

        conn = db.connect(self.db_path, read_only=True)
        try:
            candidates = conn.execute(f"""
                SELECT f.ticker, COUNT(*) AS missing
                FROM fundamentals f
                JOIN cik_map cm ON f.ticker = cm.ticker
                WHERE f.source = 'yfinance'
                  AND f.filing_date IS NULL
                  AND f.period_end < CURRENT_DATE - INTERVAL {int(FILING_BACKFILL_MIN_AGE_DAYS)} DAY
                GROUP BY f.ticker
                ORDER BY missing DESC, f.ticker
                LIMIT {int(FILING_BACKFILL_MAX_TICKERS)}
            """).fetchall()
        finally:
            conn.close()

        if not candidates:
            logger.debug("[Ingestion] Filing-date backfill: no eligible rows")
            return {'success': True, 'tickers': 0, 'rows_updated': 0}

        tickers = [c[0] for c in candidates]
        total_missing = sum(c[1] for c in candidates)

        fb_run_id = self.run_manager.start_phase(
            target_date=trading_day,
            phase_name='phase_1_filing_date_backfill',
            metadata={'ticker_count': len(tickers), 'rows_eligible': total_missing},
        )
        try:
            results = self.edgar_engine.backfill_filing_dates_from_edgar(
                tickers=tickers, only_null=True
            )
            rows_updated = sum(results.values())
            tickers_touched = len(results)
            logger.info(
                f"[Ingestion] Filing-date backfill (EDGAR): {rows_updated} rows updated "
                f"across {tickers_touched}/{len(tickers)} tickers "
                f"(eligible: {total_missing} rows)"
            )
            self.run_manager.complete_phase(
                fb_run_id, PipelineRunStatus.SUCCESS, rows_processed=rows_updated
            )
            return {
                'success': True,
                'tickers': len(tickers),
                'tickers_touched': tickers_touched,
                'rows_updated': rows_updated,
                'rows_eligible': total_missing,
            }
        except Exception as e:
            self.run_manager.complete_phase(
                fb_run_id, PipelineRunStatus.FAILED, error_message=str(e)
            )
            raise

    def _run_phase_2_screener_membership(self, target_date: str) -> Dict:
        """Phase 2: Evaluate and log screener membership event."""

        result = self.screener_manager.evaluate_and_log(target_date)
        logger.info(
            f"[Screener] Screener membership: active={result['active']}, "
            f"entered={result['entered']}, exited={result['exited']}"
        )

        return {
            'rows_processed':   result['entered'] + result['exited'],
            'entered':          result['entered'],
            'exited':           result['exited'],
            'active':           result['active'],
            'criteria_version': result['criteria_version'],
        }

    def _run_phase_3_t2_screener_incremental(self, last_trading_day: str) -> Dict:
        """Phase 3 incremental: detect gap in t2_screener_features, compute missing dates only."""
        import pandas as pd

        con = db.connect(self.db_path, read_only=True)
        try:
            max_date_row = con.execute("SELECT MAX(date) FROM t2_screener_features").fetchone()
            max_date = max_date_row[0] if max_date_row[0] else None
        finally:
            con.close()

        if max_date is None:
            logger.warning("[T2 Features] t2_screener_features is empty — falling back to full compute from 2020-01-01")
            rows = self.feature_pipeline.compute_t2_screener_features(start_date='2020-01-01')
            return {'rows_processed': rows}

        start_date = (pd.to_datetime(max_date) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')

        if start_date > last_trading_day:
            # Date is current, but check for coverage gaps (partial ingestion)
            coverage = self._t2_coverage_deficit(last_trading_day, con_factory=lambda: db.connect(self.db_path, read_only=True))
            if coverage > 0:
                logger.warning(f"[T2 Features] Coverage gap: {coverage} tickers missing for {last_trading_day} — recomputing")
                rows = self.feature_pipeline.compute_t2_screener_features(
                    start_date=last_trading_day,
                    end_date=last_trading_day
                )
                return {'rows_processed': rows}
            logger.info(f"[T2 Features] t2_screener_features already up-to-date (last={max_date}, trading_day={last_trading_day})")
            return {'rows_processed': 0}

        logger.info(f"[T2 Features] Incremental T2 compute: {start_date} -> {last_trading_day} (gap from {max_date})")
        rows = self.feature_pipeline.compute_t2_screener_features(
            start_date=start_date,
            end_date=last_trading_day
        )
        return {'rows_processed': rows}

    def _t2_coverage_deficit(self, target_date: str, con_factory=None) -> int:
        """Return number of tickers missing from t2_screener_features for target_date."""
        con = con_factory() if con_factory else db.connect(self.db_path, read_only=True)
        try:
            expected = con.execute(f"""
                SELECT COUNT(DISTINCT p.ticker)
                FROM price_data p
                INNER JOIN (
                    SELECT ticker, effective_date, is_active,
                           LEAD(effective_date) OVER (PARTITION BY ticker ORDER BY effective_date) AS next_date
                    FROM screener_membership
                ) sm ON p.ticker = sm.ticker
                    AND p.date >= sm.effective_date
                    AND (sm.next_date IS NULL OR p.date < sm.next_date)
                    AND sm.is_active = TRUE
                WHERE p.date = '{target_date}'
            """).fetchone()[0]
            actual = con.execute(f"""
                SELECT COUNT(DISTINCT ticker) FROM t2_screener_features WHERE date = '{target_date}'
            """).fetchone()[0]
            deficit = expected - actual
            if deficit > 0 and (actual / expected * 100) < 99:
                return deficit
            return 0
        finally:
            con.close()

    def _run_phase_4_t2_regime(self, target_date: str) -> Dict:
        """Phase 4: Compute M03 regime scores + 5-factor risk scores.

        M03 and the 5-factor risk calc are independent — a failure in one must NOT
        block the other. (Previously an M03 failure raised before the risk calc
        ran, freezing 5-factor too even though it reads DuckDB directly.)
        """
        try:
            m03_rows = self.regime_pipeline.update_incremental()
            logger.info(f"[T2 Regime] M03 regime: {m03_rows} new rows")
        except Exception as e:
            logger.warning(f"[T2 Regime] M03 regime update FAILED (non-critical): {e}")
            m03_rows = 0

        try:
            risk_rows = self.risk_calculator.update_incremental()
            logger.info(f"[T2 Regime] 5F Risk: {risk_rows} new rows")
        except Exception as e:
            logger.warning(f"[T2 Regime] 5F Risk update FAILED (non-critical): {e}")
            risk_rows = 0

        return {'rows_processed': m03_rows + risk_rows, 'm03_rows': m03_rows, 'risk_rows': risk_rows}

    def _run_phase_4b_sepa_watchlist(self, target_date: str) -> Dict:
        """Phase 4b: Update sepa_watchlist event log for the target date.

        Reads `t2_screener_features` for `target_date` and applies session events
        (open/close) per SepaWatchlistManager.update_daily(). Must run AFTER
        Phase 3 (t2 features written) and BEFORE Phase 5 (T3 filters universe
        via SELECT DISTINCT ticker FROM sepa_watchlist).
        """
        result = self.sepa_watchlist_manager.update_daily(target_date)
        stats = {
            'rows_processed': result['opened'] + result['closed'],
            'opened':         result['opened'],
            'closed':         result['closed'],
            'active':         result['active'],
        }
        stats['stale_status_rows'] = self._check_watchlist_status_vocab()
        return stats

    def _check_watchlist_status_vocab(self) -> int:
        """Warn when `sepa_watchlist.status` holds values outside {ACTIVE, EXITED}.

        Unlike T2/T3 (which have real gap detectors), this phase only ever APPENDS
        today's session events — nothing re-examines history. A box migrated from
        the pre-2026-07-18 schema keeps its stale COOLDOWN rows forever: nothing
        promotes them, and the nightly run never notices. The `screener_watchlist`
        VIEW self-heals on Phase 6, but the source TABLE does not.

        Detection only — the repair (`scripts/backfill_sepa_watchlist.py`) is an
        authoritative full-history DROP+rebuild, far too destructive to trigger
        automatically off a canary.
        """
        conn = db.connect(self.db_path, read_only=True)
        try:
            rows = conn.execute("""
                SELECT status, COUNT(*) AS n
                FROM sepa_watchlist
                WHERE status NOT IN ('ACTIVE', 'EXITED')
                GROUP BY status ORDER BY n DESC
            """).fetchall()
        finally:
            conn.close()

        if not rows:
            return 0
        total = sum(r[1] for r in rows)
        detail = ", ".join(f"{r[0]}={r[1]}" for r in rows)
        logger.warning(
            f"[SEPA Watchlist] {total} row(s) with a retired status ({detail}). "
            f"Nothing promotes these — this box likely predates the 2026-07-18 "
            f"watchlist merge. Repair: python scripts/backfill_sepa_watchlist.py"
        )
        return total

    def _run_phase_5_t3_features_incremental(self, last_trading_day: str) -> Dict:
        """Phase 5 incremental: detect gap in t3_sepa_features, compute missing dates only."""
        import pandas as pd

        con = db.connect(self.db_path, read_only=True)
        try:
            max_date = con.execute("SELECT MAX(date) FROM t3_sepa_features").fetchone()[0]
        finally:
            con.close()

        if max_date is None:
            logger.warning("[T3 Features] t3_sepa_features is empty — falling back to full compute from 2020-01-01")
            rows = self.feature_pipeline.compute_t3_features(start_date='2020-01-01')
            return {'rows_processed': rows}

        start_date = (pd.to_datetime(max_date) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')

        if start_date > last_trading_day:
            # Frontier is current — but the universe (sepa_watchlist) grows over time,
            # and compute_t3_features only ever writes forward from MAX(date). A ticker
            # admitted to sepa_watchlist late never gets its earlier in-window history
            # backfilled, leaving permanent (ticker,date) holes BEHIND the frontier that
            # silently delete trades from v_d1_candidates (entry-row INNER JOIN). Scan a
            # trailing window for any such hole and re-materialize the affected dates.
            holed_dates = self._t3_holed_dates(last_trading_day)
            if holed_dates:
                logger.warning(
                    f"[T3 Features] Backfill: {len(holed_dates)} date(s) have t3 holes "
                    f"({holed_dates[0]} .. {holed_dates[-1]}) — re-materializing full universe"
                )
                rows = self._recompute_t3_dates(holed_dates)
                return {'rows_processed': rows}
            logger.info(f"[T3 Features] t3_sepa_features already up-to-date (last={max_date}, trading_day={last_trading_day})")
            return {'rows_processed': 0}

        logger.info(f"[T3 Features] Incremental T3 compute: {start_date} -> {last_trading_day} (gap from {max_date})")
        rows = self.feature_pipeline.compute_t3_features(
            start_date=start_date,
            end_date=last_trading_day
        )
        return {'rows_processed': rows}

    # Trailing window (calendar days) scanned for t3 holes each daily run. Covers the
    # recent past where late sepa_watchlist admissions create holes, without rescanning
    # all history every night. ~30d comfortably spans a multi-day pipeline outage.
    T3_BACKFILL_LOOKBACK_DAYS = 30

    # `removed` lifecycle window (≈20 trading days ≈ 28 calendar days). Kept in sync
    # with ViewManager.REMOVED_WINDOW_CALENDAR_DAYS so the self-heal force-materializes
    # exactly the EXITED names that v_d3_lifecycle still tags as `removed`.
    LIFECYCLE_REMOVED_WINDOW_DAYS = 28

    def _t3_holed_dates(self, target_date: str, lookback_days: int = None) -> list:
        """Dates within the trailing window where t3 is missing rows it should have.

        Expected universe per date is the union of two sets that must have a t3 row:

          1. **Candidate frontier** — sepa_watchlist tickers with a
             `t2_screener_features` row on that date. This mirrors what
             compute_t3_features materializes (its INSERT inner-joins
             t2_screener_features), so a ticker with a raw price_data bar but no t2
             row is *legitimately* absent — using price_data as the expected set
             would over-report stale-ticker edges as holes and recompute nightly.
          2. **Held / recently-removed names** (lifecycle-scoring requirement, 4e) —
             ACTIVE or recently-EXITED `screener_watchlist` tickers that have a t2
             row on that date. A held name can drift behind the candidate frontier
             (lazy materialization leaves holes), and the lifecycle scorer can only
             score a name with a t3 row that day. Same t2-row gate, so we never
             demand t3 for a date the name has no features for.

        A date is "holed" if any expected (ticker,date) is absent from t3.
        Returns sorted date strings.
        """
        import pandas as pd
        lookback = lookback_days if lookback_days is not None else self.T3_BACKFILL_LOOKBACK_DAYS
        window_start = (
            pd.to_datetime(target_date) - pd.Timedelta(days=lookback)
        ).strftime('%Y-%m-%d')
        removed_cutoff = (
            pd.to_datetime(target_date)
            - pd.Timedelta(days=self.LIFECYCLE_REMOVED_WINDOW_DAYS)
        ).strftime('%Y-%m-%d')
        con = db.connect(self.db_path, read_only=True)
        try:
            rows = con.execute(f"""
                WITH lifecycle_tickers AS (
                    -- ACTIVE held names + names exited within the removed window.
                    -- Latest trade per ticker decides current lifecycle membership.
                    SELECT ticker
                    FROM (
                        SELECT ticker, status, exit_date,
                               ROW_NUMBER() OVER (
                                   PARTITION BY ticker ORDER BY entry_date DESC
                               ) AS rn
                        FROM screener_watchlist
                    )
                    WHERE rn = 1
                      AND (status = 'ACTIVE'
                           OR (status = 'EXITED' AND exit_date >= '{removed_cutoff}'))
                ),
                expected AS (
                    SELECT t2.ticker, t2.date
                    FROM t2_screener_features t2
                    WHERE t2.date BETWEEN '{window_start}' AND '{target_date}'
                      AND (
                          t2.ticker IN (SELECT DISTINCT ticker FROM sepa_watchlist)
                          OR t2.ticker IN (SELECT ticker FROM lifecycle_tickers)
                      )
                )
                SELECT DISTINCT e.date
                FROM expected e
                LEFT JOIN t3_sepa_features t3
                    ON e.ticker = t3.ticker AND e.date = t3.date
                WHERE t3.ticker IS NULL
                ORDER BY e.date
            """).fetchall()
        finally:
            con.close()
        return [r[0].strftime('%Y-%m-%d') for r in rows]

    def _recompute_t3_dates(self, dates: list) -> int:
        """DELETE then re-materialize the given dates (full universe) over their span.

        compute_t3_features uses a plain INSERT and requires an empty target window,
        so we clear the whole [min,max] span first. Recomputing the full span (not just
        the holed dates) is simpler and keeps the empty-window contract; the extra
        already-present dates in between are cheap relative to the per-ticker warmup.
        """
        if not dates:
            return 0
        start_date, end_date = dates[0], dates[-1]
        con = db.connect(self.db_path)
        try:
            con.execute(
                f"DELETE FROM t3_sepa_features WHERE date BETWEEN '{start_date}' AND '{end_date}'"
            )
        finally:
            con.close()
        return self.feature_pipeline.compute_t3_features(start_date=start_date, end_date=end_date)

    def _run_phase_6_views(self, target_date: str) -> Dict:
        """Phase 6: Refresh all views."""

        view_count = self.view_manager.create_all()
        logger.info(f"[Views] Views refreshed: {view_count} views")

        return {'rows_processed': view_count}

    def _run_phase_7_cache(self, target_date: str) -> Dict:
        """Phase 7: Refresh training cache."""

        self.view_manager.refresh_cache(verbose=False)
        stats = self.view_manager.get_cache_stats()
        rows = stats.get('row_count', 0)
        logger.info(f"[Training Cache] Training cache refreshed: {rows:,} rows")

        return {'rows_processed': rows}

    def _run_phase_7_4_scoring(self, target_date: str) -> Dict:
        """Phase 7.4: Score target_date with the prod model → daily_predictions.

        Runs before the dashboard DB build (7.5) so the materialized scores are
        included in the slim DB and the R2 sync. Best-effort: a scoring failure
        never fails the daily run (the dashboard degrades to last good scores).
        """
        n = 0
        try:
            n = self._log_prod_model_predictions(target_date)
        except Exception as e:
            logger.warning(f"[Scoring] Prediction logging skipped: {e}")
        # Shadow pass (Module B): score the shadow model on the same breakout
        # candidates and materialize the ranking-divergence verdict. Fully
        # isolated — a shadow failure never affects prod scoring or the run.
        try:
            self._log_shadow_predictions_and_divergence(target_date)
        except Exception as e:
            logger.warning(f"[Scoring] Shadow comparison skipped: {e}")
        return {'rows_processed': n}

    def _run_phase_7_45_weather(self, target_date: str) -> Dict:
        """Phase 7.45: Recompute the weather_gauge deploy-posture table.

        Runs after scoring and before the dashboard build so the fresh state ships
        in the slim DB. Full recompute (expanding stats need all history; the table
        is one row/day). Best-effort — a failure never fails the daily run.
        """
        from src.weather_engine import WeatherEngine
        n = WeatherEngine(db_path=self.db_path).refresh(end=target_date)
        return {'rows_processed': n}

    def _run_phase_7_46_sector_breadth(self) -> Dict:
        """Phase 7.46: Materialize the sector_breadth heatmap snapshot (Macro page S2).

        Latest-day aggregate of t2_screener_features ⋈ company_profiles. Runs before
        the dashboard build so the snapshot ships in the slim DB. Best-effort.
        """
        from src.sector_breadth_engine import SectorBreadthEngine
        n = SectorBreadthEngine(db_path=self.db_path).refresh()
        return {'rows_processed': n}

    def _run_phase_7_47_portfolio_nav(self, target_date: str) -> Dict:
        """Phase 7.47: Mark the book to close — one nav_history row for target_date.

        Runs after the close is ingested, before the dashboard build so the row
        ships in the slim DB. Idempotent (delete+insert per date). Best-effort.
        A NAV series cannot be honestly backfilled later: TWR needs the day's
        net_flow recorded on the day, so a missed run is a permanent hole.
        """
        from datetime import datetime

        from src.managers.portfolio_manager import PortfolioManager

        as_of = datetime.strptime(target_date, '%Y-%m-%d').date()
        pm = PortfolioManager(db_path=self.db_path)
        nav = pm.snapshot_nav(as_of=as_of)
        return {'rows_processed': 1, 'metadata': {'nav': nav}}

    def _run_phase_7_5_dashboard_db(self) -> Dict:
        """Phase 7.5: Rebuild the slim dashboard.duckdb from the full DB.

        Delegates to scripts/build_dashboard_db.py via subprocess so the build
        runs in its own process against a fresh read-only ATTACH (no connection
        contention with the orchestrator's open handle to the source DB).
        Best-effort: a failure here is logged but never fails the daily run.
        """
        import subprocess
        import sys

        project_root = Path(__file__).resolve().parent.parent.parent
        build_script = project_root / "scripts" / "build_dashboard_db.py"
        if not build_script.exists():
            logger.warning(f"[Dashboard DB] Build script not found: {build_script}")
            return {'rows_processed': 0}

        # 1800s ceiling: the build windows the multi-GB feature tables off an
        # ever-growing source DB (~88 GB and climbing), so the old 600s cap was
        # killing the build mid-manifest. The build now writes atomically (temp
        # + os.replace), so a kill here can only leave the last good slim DB in
        # place — never a truncated one — but a generous timeout lets the rebuild
        # actually finish so the remote dashboard stays fresh, not just valid.
        proc = subprocess.run(
            [sys.executable, str(build_script)],
            capture_output=True, text=True, timeout=1800,
            cwd=str(project_root),
        )
        if proc.returncode != 0:
            logger.warning(
                f"[Dashboard DB] dashboard DB rebuild failed (rc={proc.returncode}): "
                f"{proc.stderr.strip()[:500]}"
            )
            return {'rows_processed': 0}

        out_db = project_root / "data" / "dashboard.duckdb"
        size_mb = out_db.stat().st_size / 1024 ** 2 if out_db.exists() else 0
        logger.info(f"[Dashboard DB] Slim dashboard DB rebuilt: {size_mb:,.0f} MB")
        return {'rows_processed': 1}

    def _run_phase_7_6_r2_sync(self) -> Dict:
        """Phase 7.6: Upload data/dashboard.duckdb to Cloudflare R2.

        Delegates to scripts/sync_dashboard_db.py. Skipped silently when R2
        credentials are absent (so local-only runs are unaffected).
        Best-effort: failure is logged but never halts the daily run.
        """
        import os
        import subprocess
        import sys

        # config.py anchors load_dotenv() to the project root, so creds are
        # present on any run where .env exists and is filled in. A miss here now
        # means a real misconfig (no .env / incomplete keys) — not an expected
        # local run — so warn loudly rather than skipping silently.
        if not os.environ.get("R2_ACCOUNT_ID"):
            logger.warning(
                "[R2 Sync] R2_ACCOUNT_ID not set; skipping upload. Remote "
                "dashboard will go stale. Check .env at project root."
            )
            return {'rows_processed': 0}

        project_root = Path(__file__).resolve().parent.parent.parent
        sync_script = project_root / "scripts" / "sync_dashboard_db.py"
        if not sync_script.exists():
            logger.warning(f"[R2 Sync] Sync script not found: {sync_script}")
            return {'rows_processed': 0}

        # 1200s ceiling: the ~764 MB slim DB is the only large upload (asset dirs
        # now skip unchanged files), and a slow home uplink can legitimately need
        # well over 5 min. Phase is best-effort, so a generous timeout is safe.
        proc = subprocess.run(
            [sys.executable, str(sync_script)],
            capture_output=True, text=True, timeout=1200,
            cwd=str(project_root),
        )
        if proc.returncode != 0:
            logger.warning(
                f"[R2 Sync] R2 upload failed (rc={proc.returncode}): "
                f"{proc.stderr.strip()[:500]}"
            )
            return {'rows_processed': 0}

        logger.info("[R2 Sync] dashboard.duckdb uploaded to R2 (latest/)")
        return {'rows_processed': 1}

    def _run_phase_10_model_card(self, target_date: str) -> Dict:
        """Phase 10: Advisory weekly DRIFT card for the prod model.

        Builds a trailing-window (1-year) card that re-tests the FROZEN prod
        model against recent data, so behavioral drift is not drowned out by
        20+ years of history. This is a monitoring artifact and is registered
        to model_card_drift_path — it does NOT overwrite model_card_path, which
        is the authoritative full-history promotion-gate card.

        Freshness gate: skip if a drift card was built within the last 7 days.
        Best-effort — failures WARN, never halt the pipeline.
        """
        import subprocess
        import sys
        from datetime import datetime as _dt, timedelta as _td

        from src.model_registry import ModelRegistry

        registry = ModelRegistry(db_path=Path(self.db_path))
        prod_version = registry.get_prod_version()
        if not prod_version:
            logger.info("[Model Card] No prod model registered; skipping card build.")
            return {'rows_processed': 0, 'status': 'no_prod_model'}

        info = registry.get_drift_card_info(prod_version)
        if info and info.get("built_at") is not None:
            built_at = info["built_at"]
            if isinstance(built_at, str):
                try:
                    built_at = _dt.fromisoformat(built_at.replace("Z", ""))
                except ValueError:
                    built_at = None
            if built_at is not None and (_dt.utcnow() - built_at) < _td(days=7):
                logger.info(
                    f"[Model Card] Drift card for {prod_version} is fresh "
                    f"(built {built_at}); skipping rebuild."
                )
                return {'rows_processed': 0, 'status': 'fresh'}

        project_root = Path(__file__).resolve().parent.parent.parent
        build_script = project_root / "scripts" / "build_model_card.py"
        if not build_script.exists():
            logger.warning(f"[Model Card] Build script not found: {build_script}")
            return {'rows_processed': 0, 'status': 'no_script'}

        # Resolve the clean '<name>/<version>' slug (maps to models/<name>/<version>/
        # model.json and yields a clean card filename) rather than the timestamped
        # version_id, which build_model_card.py cannot resolve.
        try:
            model_slug = registry.get_model_slug(prod_version)
        except ValueError as e:
            logger.warning(f"[Model Card] {e}")
            return {'rows_processed': 0, 'status': 'no_model_slug'}

        # Trailing 1-year drift window. ~603K SEPA rows over 1y keeps Section G
        # well-powered. FUTURE: recency-weighted bootstrap instead of a hard
        # cutoff (see docs/proposals/model_card_drift_window.md).
        end_dt = _dt.strptime(target_date, "%Y-%m-%d")
        start_date = (end_dt - _td(days=365)).strftime("%Y-%m-%d")
        slug = model_slug.replace("/", "_")
        out_html = project_root / "model_cards" / f"{slug}_drift.html"

        # NOTE: no --register-version (that writes model_card_path, the gate card).
        # Phase 10 registers the drift path itself after a clean exit.
        cmd = [
            sys.executable, str(build_script),
            "--model", model_slug,
            "--db", self.db_path,
            "--output", str(out_html),
            "--start-date", start_date,
            "--end-date", target_date,
            "--skip-sepa-match",
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=1800,
                cwd=str(project_root),
            )
        except subprocess.TimeoutExpired:
            logger.warning("[Model Card] Drift card build timed out after 1800s")
            return {'rows_processed': 0, 'status': 'timeout'}

        if proc.returncode != 0:
            logger.warning(
                f"[Model Card] Drift card build failed (rc={proc.returncode}): "
                f"{proc.stderr.strip()[:500]}"
            )
            return {'rows_processed': 0, 'status': 'build_failed'}

        # build_model_card.py derives the JSON path from --output by suffix swap.
        card_json = out_html.with_suffix(".json")
        registry.register_drift_card(
            version_id=prod_version,
            card_path=str(card_json),
            built_at=_dt.utcnow().isoformat(timespec="seconds") + "Z",
        )
        logger.info(
            f"[Model Card] Rebuilt drift card ({start_date}..{target_date}) "
            f"for {prod_version}"
        )
        return {'rows_processed': 1, 'status': 'rebuilt'}

    def _run_phase_8_monitoring(self, target_date: str, run_stats: Dict) -> Dict:
        """Phase 8: Generate health report, coverage check, and alerts. Always runs."""

        # Get health report
        health = self.run_manager.get_health_report(target_date)

        # Check for alerts
        alerts = []

        # Alert 1: Breakout drought
        if health['breakout_drought_days'] >= PIPELINE_ALERT_THRESHOLDS['breakout_drought_days']:
            alerts.append(
                f"[WARN] ALERT: 0 breakouts for {health['breakout_drought_days']} consecutive days"
            )

        # Alert 2: Recent failures
        if health['recent_failures']:
            alerts.append(
                f"[WARN] ALERT: {len(health['recent_failures'])} phase failures in last 7 days"
            )

        # Alert 4: Coverage check — detect partial ingestion gaps
        coverage = self._check_coverage(target_date)
        if coverage['alerts']:
            alerts.extend(coverage['alerts'])

        # Alert 5: Missing NAV mark on an ACTIVE book. A NAV series can't be
        # backfilled (TWR needs the day's net_flow recorded on the day — see
        # _run_phase_7_47_portfolio_nav), so a silent miss is a permanent hole.
        # Only fires when the book has activity: an empty book has no NAV to mark.
        nav_con = db.connect(self.db_path, read_only=True)
        try:
            book_active = nav_con.execute(
                "SELECT (SELECT COUNT(*) FROM trades) + (SELECT COUNT(*) FROM cash_flows)"
            ).fetchone()[0]
            if book_active:
                has_row = nav_con.execute(
                    "SELECT COUNT(*) FROM nav_history WHERE date = ?", [target_date]
                ).fetchone()[0]
                if not has_row:
                    alerts.append(
                        f"🛑 ALERT: no nav_history row for {target_date} on an active book. "
                        f"NAV is not backfillable (TWR needs same-day net_flow) — "
                        f"investigate the portfolio_nav phase for this date."
                    )
        finally:
            nav_con.close()

        # Alert 6: prod-model identity. Which model is 'prod' is per-box registry
        # state, so a box that never re-promoted keeps scoring an old model and
        # says nothing (Phase 7.4 logs "no prod model" at INFO and returns 0).
        # That produces wrong live output, not merely missing data — the failure
        # mode that left sh019 scoring 4-class while research scored binary.
        alerts.extend(self._check_prod_model_identity())

        # Log alerts
        if alerts:
            logger.warning("[Monitoring] ALERTS TRIGGERED:")
            for alert in alerts:
                logger.warning(f"  {alert}")
        else:
            logger.info("[Monitoring] No alerts - pipeline health OK")

        # Log health summary
        logger.info(f"[Monitoring] Data freshness: {health['max_dates']}")
        logger.info(f"[Monitoring] Breakout drought: {health['breakout_drought_days']} days")

        # Prediction logging lives in the scoring phase (runs before the dashboard
        # DB is built/uploaded so today's scores ride along; see _run_scoring).
        predictions_written = run_stats.get('scoring', {}).get('rows_processed', 0)

        # Quarterly feature-drift report (best-effort; only fires on 1st of Jan/Apr/Jul/Oct).
        drift_report = None
        try:
            drift_report = self._maybe_run_quarterly_drift(target_date)
        except Exception as e:
            logger.warning(f"[Monitoring] Quarterly drift report skipped: {e}")

        # Daily audit report (best-effort; populates Pipeline Health audit history).
        audit_report = None
        try:
            audit_report = self._run_daily_audits(target_date)
        except Exception as e:
            logger.warning(f"[Monitoring] Daily audit run skipped: {e}")

        return {
            'rows_processed': predictions_written,
            'alerts': alerts,
            'health': health,
            'coverage': coverage,
            'predictions_written': predictions_written,
            'drift_report': drift_report,
            'audit_report': audit_report,
        }

    def _check_prod_model_identity(self) -> List[str]:
        """Alerts when the scoring model is absent or changed since the last scored date.

        `daily_predictions.model_version_id` records which model actually scored
        each date, so the previous run's identity is already persisted — no new
        state needed. A promotion legitimately changes it, so this WARNS (once,
        on the first run after the change) rather than gating anything.
        """
        conn = db.connect(self.db_path, read_only=True)
        try:
            prod = conn.execute(
                "SELECT version_id FROM models WHERE status_flag = 'prod'"
            ).fetchall()
            if not prod:
                return ["🛑 ALERT: no prod model registered — Phase 7.4 scored nothing. "
                        "daily_predictions is not advancing; promote a model on this box."]
            if len(prod) > 1:
                ids = ", ".join(r[0] for r in prod)
                return [f"🛑 ALERT: {len(prod)} models flagged 'prod' ({ids}) — "
                        f"scoring picks one arbitrarily. Demote all but one."]

            # Compare against whatever scored the LATEST date. Once the promoted
            # model has scored a day, that date reflects it and this goes quiet —
            # so the alert fires once at the switch, not forever off stale rows.
            previous = conn.execute("""
                SELECT model_version_id
                FROM daily_predictions
                WHERE prediction_date = (SELECT MAX(prediction_date) FROM daily_predictions)
                  AND model_version_id <> ?
                LIMIT 1
            """, [prod[0][0]]).fetchone()
        finally:
            conn.close()

        if previous and previous[0]:
            return [f"⚠️ ALERT: prod model changed to {prod[0][0]} "
                    f"(previously scoring {previous[0]}). Expected after a promotion — "
                    f"investigate if you did not promote."]
        return []

    def _run_daily_audits(self, target_date: str) -> Optional[Dict]:
        """Invoke tools/run_all_audits.py as a subprocess. Best-effort.

        Writes one JSON per run to data/audit_reports/audit_report_YYYYMMDD.json
        (filename = orchestrator run UTC date — same key used by the dashboard).
        """
        import subprocess
        import sys
        import json

        repo_root = Path(__file__).parent.parent.parent
        audit_script = repo_root / "tools" / "run_all_audits.py"
        if not audit_script.exists():
            logger.warning(f"[Monitoring] Audit script not found: {audit_script}")
            return None

        cmd = [sys.executable, str(audit_script), "--date", target_date, "--warn-only"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            logger.warning("[Monitoring] Audit run timed out after 600s")
            return None

        # run_all_audits exits 0 (all OK) or 1 (any WARNING/FAIL); 2+ = crash.
        if proc.returncode not in (0, 1):
            err = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "unknown"
            logger.warning(f"[Monitoring] Audit run crashed (rc={proc.returncode}): {err}")
            return None

        # The script writes audit_report_YYYYMMDD.json keyed by UTC run date.
        from datetime import datetime as _dt
        date_str = _dt.utcnow().strftime("%Y%m%d")
        report_path = repo_root / "data" / "audit_reports" / f"audit_report_{date_str}.json"
        if not report_path.exists():
            logger.warning(f"[Monitoring] Audit report not written at expected path: {report_path}")
            return None

        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            logger.warning(f"[Monitoring] Could not parse audit report: {e}")
            return None

        summary = report.get("summary", {}).get("total", {})
        logger.info(
            f"[Monitoring] Audit report saved ({report_path.name}): "
            f"FAIL={summary.get('FAIL', 0)} WARN={summary.get('WARNING', 0)} "
            f"OK={summary.get('OK', 0)} overall={report.get('overall')}"
        )

        # Standing FAILs are noise; a FAIL that wasn't in the previous report is the
        # actionable signal — escalate those to ERROR so they stand out in the nightly log.
        new_fails = report.get("new_fails", [])
        if new_fails:
            for r in new_fails:
                logger.error(
                    f"[Monitoring] NEW audit FAIL: {r.get('audit')}/{r.get('section')}."
                    f"{r.get('check')} = {r.get('value')} — {r.get('detail', '')[:120]}"
                )

        return {
            'path': str(report_path),
            'overall': report.get('overall'),
            'summary': summary,
            'new_fails': [f"{r.get('section')}.{r.get('check')}" for r in new_fails],
        }

    def _log_prod_model_predictions(self, target_date: str) -> int:
        """Score `target_date`'s lifecycle population with the prod model and log it.

        One MECE pass over the SEPA lifecycle (supersedes the old breakout +
        pre_breakout status-gated split). v_d3_lifecycle carries a derived `cohort`
        tag per row; we split by tag and log each (rank is computed within each tag).

        Tags written: 'pre_breakout' | 'active' | 'removed'. The 'breakout' cohort is
        dropped from the prod path — a name is 'active' from the day it breaks out, so
        breakout surfaced nothing active didn't. (Shadow still scores 'breakout'; see
        _log_shadow_predictions_and_divergence — a separate concern.)

        Skips silently (returns 0) if no prod model is registered or its artifact
        is missing. A failure on one tag never blocks the others.

        Scoring itself lives in the shared ScoreEngine (RAW softprob) so this and
        the backfill util (scripts/backfill_daily_predictions.py) can't drift.
        """
        from src.evaluation.score_engine import ScoreEngine

        try:
            engine = ScoreEngine.from_prod(self.db_path)
        except (ValueError, FileNotFoundError) as e:
            logger.warning(f"[Scoring] Prod model not scorable: {e}")
            return 0
        if engine is None:
            logger.info("[Scoring] No prod model registered — skipping prediction log.")
            return 0

        population = self._fetch_lifecycle_candidates(target_date)
        if population.empty:
            logger.info(f"[Monitoring] No lifecycle candidates on {target_date}.")
            return 0

        total = 0
        # Rank within each tag (per-cohort), so split before scoring.
        for cohort, candidates in population.groupby("cohort", sort=False):
            try:
                n = engine.score_and_log(candidates, target_date, cohort, self.db_path)
                logger.info(f"[Scoring] Logged {n} '{cohort}' predictions on {target_date}")
                total += n
            except Exception as e:
                logger.warning(f"[Scoring] Scoring cohort '{cohort}' failed: {e}")
        return total

    def _log_shadow_predictions_and_divergence(self, target_date: str) -> int:
        """Module B: score the shadow model + write today's divergence verdict.

        Scores only the 'breakout' cohort (the list actually acted on) into
        daily_predictions under the shadow's model_version_id — additive, never
        touches prod rows. Then loads both models' breakout scores for
        target_date and upserts the ranking-divergence row into shadow_divergence.

        Best-effort and self-contained: returns 0 (and logs) if no shadow is
        designated or its artifact is missing.
        """
        from src.evaluation.score_engine import ScoreEngine
        from src.evaluation.shadow_compare import (
            compare_day,
            load_cohort_scores,
            write_day_divergence,
        )
        from src.model_registry import ModelRegistry

        try:
            engine = ScoreEngine.from_shadow(self.db_path)
        except (ValueError, FileNotFoundError) as e:
            logger.warning(f"[Scoring] Shadow model not scorable: {e}")
            return 0
        if engine is None:
            logger.info("[Scoring] No shadow model designated — skipping shadow pass.")
            return 0

        cohort = "breakout"
        candidates = self._fetch_breakout_candidates(target_date)
        n = engine.score_and_log(candidates, target_date, cohort, self.db_path)
        logger.info(f"[Scoring] Logged {n} shadow '{cohort}' predictions on {target_date}")

        prod_id = ModelRegistry(db_path=self.db_path).get_prod_version()
        if not prod_id:
            logger.info("[Scoring] No prod model — skipping divergence verdict.")
            return n

        prod_day = load_cohort_scores(self.db_path, prod_id, cohort, target_date, target_date)
        shadow_day = load_cohort_scores(self.db_path, engine.version_id, cohort, target_date, target_date)
        day = compare_day(prod_day, shadow_day)
        if day is None:
            logger.info("[Scoring] No overlapping prod/shadow scores on %s — no verdict.", target_date)
            return n
        write_day_divergence(
            self.db_path, target_date, prod_id, engine.version_id, cohort, day
        )
        logger.info(
            "[Scoring] Shadow divergence %s: spearman=%.3f jaccard@10=%.3f disagree=%d",
            target_date, day.spearman, day.jaccard_at_10, day.n_disagreements,
        )
        return n

    def _fetch_breakout_candidates(self, target_date: str):
        """SEPA breakout entries for target_date (v_d3_deployment)."""
        con = db.connect(self.db_path, read_only=True)
        try:
            return con.execute(
                "SELECT * FROM v_d3_deployment WHERE date = ?", [target_date]
            ).df()
        except duckdb.Error as e:
            logger.warning(f"[Scoring] Could not query v_d3_deployment: {e}")
            import pandas as pd
            return pd.DataFrame()
        finally:
            con.close()

    def _fetch_lifecycle_candidates(self, target_date: str):
        """MECE lifecycle population for target_date (v_d3_lifecycle).

        Returns the union of pre_breakout / active / removed names with the SAME
        feature contract as v_d3_deployment plus a derived `cohort` column per row.
        The caller splits by cohort and logs each tag (rank within tag).
        """
        con = db.connect(self.db_path, read_only=True)
        try:
            return con.execute(
                "SELECT * FROM v_d3_lifecycle WHERE date = ?", [target_date]
            ).df()
        except duckdb.Error as e:
            logger.warning(f"[Scoring] Could not query v_d3_lifecycle: {e}")
            import pandas as pd
            return pd.DataFrame()
        finally:
            con.close()

    def _maybe_run_quarterly_drift(self, target_date: str) -> Optional[dict]:
        """Quarterly PSI drift report against the prod model's frozen baseline.

        Fires only when `target_date.day == 1` AND `month in (1, 4, 7, 10)`.
        Output → logs/drift/<YYYY>Q<N>.json. Returns None on any silent skip.
        """
        from datetime import date as _date
        from pathlib import Path as _Path

        from src.evaluation.drift import quarterly_drift_report
        from src.model_registry import ModelRegistry

        target_dt = (
            _date.fromisoformat(target_date) if isinstance(target_date, str)
            else target_date
        )
        if target_dt.day != 1 or target_dt.month not in (1, 4, 7, 10):
            return None

        registry = ModelRegistry(db_path=self.db_path)
        prod_version_id = registry.get_prod_version()
        if not prod_version_id:
            logger.info("[Monitoring] No prod model — skipping drift report.")
            return None

        try:
            artifacts_path = registry.get_artifacts_path(prod_version_id)
        except ValueError:
            logger.warning(f"[Monitoring] Prod model {prod_version_id} has no artifacts_path; skipping drift.")
            return None

        snapshot_path = _Path(artifacts_path) / "reference_snapshot.json"
        if not snapshot_path.exists():
            logger.info(
                f"[Monitoring] No reference_snapshot.json under {artifacts_path} "
                f"— skipping drift (model pre-dates §2.2 wiring)."
            )
            return None

        quarter = f"{target_dt.year}Q{(target_dt.month - 1) // 3 + 1}"
        out_dir = _Path("logs") / "drift"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{quarter}.json"

        report = quarterly_drift_report(
            reference_snapshot_path=snapshot_path,
            current_view="v_d3_deployment",
            db_path=_Path(self.db_path),
            quarter=quarter,
        )
        import json as _json
        out_path.write_text(_json.dumps(report, indent=2, default=str))
        gate = report["gates"][0]
        logger.info(
            f"[Monitoring] Drift report {quarter}: {gate['status']} — "
            f"{report['n_features_drifted']} drifted, "
            f"{report['n_features_warned']} warned, "
            f"{report['n_features_skipped']} skipped → {out_path}"
        )
        if report["drifted_features"]:
            sample = report["drifted_features"][:5]
            logger.warning(f"[Monitoring] Drifted features (top {len(sample)}): {sample}")
        return report

    def _check_filing_date_quality(self, tickers: list) -> None:
        """Two-part fundamentals DQ check.

        1. Bogus filing_dates: rows where filing_date sits within 8d of period_end.
           These are yfinance announcement dates (or worse, the period_end itself)
           rather than real 10-Q filings. New ingests are now sanitised at the
           upsert gate, so any remaining hits indicate pre-fix legacy rows.

        2. Stale fundamentals: the NEXT expected quarter is overdue. A healthy
           quarterly filer crosses 100d-since-last-filing for ~45d of every quarter
           (10-Q lands ~45d after period_end, the next quarter ends ~90d later), so
           measuring days-since-last-FILING raises a false alarm every cycle. We
           anchor on last period_end instead: stale ⟺ today > last_period_end +
           EXPECTED_NEXT_FILING_LAG_DAYS (~135d). When period_end is unknown (ticker
           with no fundamentals rows at all), fall back to the flat
           FUNDAMENTAL_STALENESS_DAYS check on last_filing. A genuinely stale name is
           a late filer, delisted, fiscal-calendar restate, or a pipeline miss.

           Known residual (accepted, not fixed here): off-calendar fiscal filers
           (e.g. AZO Aug-FY) have legitimately longer gaps and may still trip — same
           fiscal-calendar floor noted in the EDGAR backfill. The form-type →
           ticker_type reclassification removes the non-10-Q filers (CEFs/BDCs/ADRs).
        """
        if not tickers:
            return
        import pandas as pd
        from config import (
            FUNDAMENTAL_STALENESS_DAYS,
            EXPECTED_NEXT_FILING_LAG_DAYS,
            FILING_MIN_REAL_GAP_DAYS,
        )

        ticker_df = pd.DataFrame({'ticker': tickers})
        con = db.connect(self.db_path, read_only=True)
        try:
            con.register('_dq_tickers', ticker_df)

            bogus = con.execute(f"""
                SELECT ticker, period_end, filing_date,
                       DATE_DIFF('day', period_end, filing_date) AS gap_days
                FROM fundamentals
                WHERE ticker IN (SELECT ticker FROM _dq_tickers)
                  AND filing_date IS NOT NULL
                  AND DATE_DIFF('day', period_end, filing_date) < {int(FILING_MIN_REAL_GAP_DAYS)}
                ORDER BY gap_days
                LIMIT 20
            """).fetchdf()

            # Primary anchor: the most recent period_end we have an ACTUAL FILING for
            # (filing_date IS NOT NULL). yfinance fabricates future quarterly period_end
            # slots with a NULL filing_date (earnings-endpoint failures), so MAX(period_end)
            # alone would trust a quarter we have no proof was ever filed and mask dead
            # tickers. Flag only when the NEXT quarter's filing is overdue
            # (today > last_filed_period_end + EXPECTED_NEXT_FILING_LAG_DAYS). Fall back to
            # the flat days-since-last-filing check only when we have no filed quarter at all.
            stale = con.execute(f"""
                WITH latest AS (
                  SELECT ticker,
                         MAX(filing_date) AS last_filing,
                         MAX(period_end) FILTER (WHERE filing_date IS NOT NULL)
                             AS last_period_end
                  FROM fundamentals
                  WHERE ticker IN (SELECT ticker FROM _dq_tickers)
                  GROUP BY ticker
                )
                SELECT ticker, last_filing, last_period_end,
                       CASE WHEN last_filing IS NULL THEN NULL
                            ELSE DATE_DIFF('day', last_filing, CURRENT_DATE)
                       END AS days_since,
                       CASE WHEN last_period_end IS NULL THEN NULL
                            ELSE DATE_DIFF('day', last_period_end, CURRENT_DATE)
                       END AS days_since_period_end
                FROM latest
                WHERE
                    CASE
                        WHEN last_period_end IS NOT NULL THEN
                            DATE_DIFF('day', last_period_end, CURRENT_DATE)
                                > {int(EXPECTED_NEXT_FILING_LAG_DAYS)}
                        ELSE
                            last_filing IS NULL
                            OR DATE_DIFF('day', last_filing, CURRENT_DATE)
                                > {int(FUNDAMENTAL_STALENESS_DAYS)}
                    END
                ORDER BY days_since_period_end DESC NULLS LAST
            """).fetchdf()
        finally:
            con.close()

        if not bogus.empty:
            sample = ", ".join(f"{r.ticker} ({r.gap_days}d)" for r in bogus.head(5).itertuples())
            logger.warning(
                f"[Ingestion] DQ: {len(bogus)} legacy rows with filing_date < 8d after period_end. "
                f"Sample: {sample}. Run scripts/backfill_filing_dates.py to clean."
            )

        if not stale.empty:
            null_count = int(stale['last_filing'].isna().sum())
            old_count = len(stale) - null_count
            sample_old = stale.dropna(subset=['last_period_end']).head(5)
            sample_str = ", ".join(
                f"{r.ticker} ({int(r.days_since_period_end)}d since period_end)"
                for r in sample_old.itertuples()
            )
            logger.warning(
                f"[Ingestion] DQ: {len(stale)} equities with stale fundamentals "
                f"(next quarter overdue: period_end>{EXPECTED_NEXT_FILING_LAG_DAYS}d ago; "
                f"null_filing={null_count}). Sample: {sample_str or 'n/a'}"
            )

    def _check_coverage(self, target_date: str) -> Dict:
        """Check ticker coverage across pipeline tables for the target date.

        Compares expected tickers (price_data + screener_membership) against
        actual tickers in t2_screener_features and t3_sepa_features. Gaps
        indicate partial ingestion (e.g., API rate limits during Phase 1).
        """
        con = db.connect(self.db_path, read_only=True)
        alerts = []
        details = {}

        try:
            # Expected: tickers with price data AND active screener membership on target_date
            expected = con.execute(f"""
                SELECT COUNT(DISTINCT p.ticker)
                FROM price_data p
                INNER JOIN (
                    SELECT ticker, effective_date, is_active,
                           LEAD(effective_date) OVER (PARTITION BY ticker ORDER BY effective_date) AS next_date
                    FROM screener_membership
                ) sm ON p.ticker = sm.ticker
                    AND p.date >= sm.effective_date
                    AND (sm.next_date IS NULL OR p.date < sm.next_date)
                    AND sm.is_active = TRUE
                WHERE p.date = '{target_date}'
            """).fetchone()[0]

            # Actual: tickers in t2_screener_features
            actual_t2 = con.execute(f"""
                SELECT COUNT(DISTINCT ticker)
                FROM t2_screener_features
                WHERE date = '{target_date}'
            """).fetchone()[0]

            details['expected_tickers'] = expected
            details['t2_tickers'] = actual_t2
            details['t2_deficit'] = expected - actual_t2

            coverage_pct = (actual_t2 / expected * 100) if expected > 0 else 100
            if expected > 0 and coverage_pct < 99:
                pct = round(coverage_pct, 1)
                deficit = expected - actual_t2
                alerts.append(
                    f"⚠️  COVERAGE GAP: t2_screener_features has {actual_t2}/{expected} tickers "
                    f"for {target_date} ({pct}% coverage, {deficit} missing). "
                    f"Likely cause: partial price ingestion (API rate limit). "
                    f"Fix: rerun with --phase-3-only"
                )
                # Log sample missing tickers for debugging
                missing = con.execute(f"""
                    SELECT p.ticker
                    FROM price_data p
                    INNER JOIN (
                        SELECT ticker, effective_date, is_active,
                               LEAD(effective_date) OVER (PARTITION BY ticker ORDER BY effective_date) AS next_date
                        FROM screener_membership
                    ) sm ON p.ticker = sm.ticker
                        AND p.date >= sm.effective_date
                        AND (sm.next_date IS NULL OR p.date < sm.next_date)
                        AND sm.is_active = TRUE
                    LEFT JOIN t2_screener_features t2
                        ON p.ticker = t2.ticker AND t2.date = '{target_date}'
                    WHERE p.date = '{target_date}' AND t2.ticker IS NULL
                    ORDER BY p.ticker
                    LIMIT 10
                """).fetchdf()
                sample = ", ".join(missing['ticker'].tolist())
                logger.debug(f"[Monitoring] Missing tickers sample: {sample}")
                details['sample_missing'] = missing['ticker'].tolist()

            # T3 coverage (only meaningful if t2 has breakouts)
            t2_breakouts = con.execute(f"""
                SELECT COUNT(DISTINCT ticker)
                FROM t2_screener_features
                WHERE date = '{target_date}' AND trend_ok = TRUE AND breakout_ok = TRUE
            """).fetchone()[0]

            actual_t3 = con.execute(f"""
                SELECT COUNT(DISTINCT ticker)
                FROM t3_sepa_features
                WHERE date = '{target_date}'
            """).fetchone()[0]

            details['t2_breakouts'] = t2_breakouts
            details['t3_tickers'] = actual_t3

            if t2_breakouts > 0 and actual_t3 < t2_breakouts:
                deficit = t2_breakouts - actual_t3
                alerts.append(
                    f"⚠️  COVERAGE GAP: t3_sepa_features has {actual_t3}/{t2_breakouts} "
                    f"breakout tickers for {target_date} ({deficit} missing). "
                    f"Fix: rerun with --phase-5-only"
                )

        except Exception as e:
            logger.error(f"[Monitoring] Coverage check failed: {e}", exc_info=True)
            alerts.append(f"Coverage check failed: {e}")
        finally:
            con.close()

        if not alerts:
            logger.info(
                f"[Monitoring] Coverage: t2={details.get('t2_tickers', '?')}/{details.get('expected_tickers', '?')} tickers, "
                f"t3={details.get('t3_tickers', '?')}/{details.get('t2_breakouts', '?')} breakouts"
            )

        return {'alerts': alerts, 'details': details}
