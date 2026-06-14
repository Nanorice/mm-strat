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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import duckdb

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

# Import config
from config import PIPELINE_FAILURE_MODES, PipelineFailureMode, PIPELINE_ALERT_THRESHOLDS

logger = logging.getLogger(__name__)


class DailyPipelineOrchestrator:
    """
    Orchestrates the daily 8-phase pipeline.

    Phase 1:  T1 Ingestion (PARALLEL) - price, fundamentals, shares, macro
    Phase 2:  Screener Membership - evaluate_and_log to screener_membership event log
    Phase 3:  T2 Screener Features - compute full universe features + XS alphas + ranks
    Phase 4:  T2 Regime Scores - compute M03 regime scores
    Phase 4b: SEPA Watchlist Update - open/close sessions in sepa_watchlist (T3 universe gate)
    Phase 5:  T3 SEPA Features - compute per-ticker features + TS alphas for sepa_watchlist universe
    Phase 6:  View Refresh - recreate all views
    Phase 7:  Training Cache Refresh - materialize d2_training_cache
    Phase 8:  Monitoring - log metrics, send alerts
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

    def run_pipeline(self, target_date: str = None, phase_1_only: bool = False, phase_2_only: bool = False, phase_3_only: bool = False, phase_4_only: bool = False, phase_5_only: bool = False, universe_refresh: bool = False) -> bool:
        """
        Execute full 8-phase pipeline.

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
        # Determine target date (latest completed US trading day if None)
        if target_date is None:
            from src.utils import get_latest_trading_day
            target_date = get_latest_trading_day().strftime('%Y-%m-%d')

        # Get actual trading day (accounts for weekends/holidays)
        actual_trading_day = self._get_last_trading_day(target_date)

        logger.info(f"[Pipeline] START | Trading Day: {actual_trading_day}")

        # Track overall success (CRITICAL phases only)
        critical_success = True
        run_stats = {}

        # --- Phase-only shortcuts ---
        if phase_3_only:
            logger.info("[Pipeline] Single-phase mode: Phase 3 only")
            phase_success, phase_stats = self._execute_phase(
                "phase_3_t2_screener",
                lambda: self._run_phase_3_t2_screener_incremental(actual_trading_day),
                actual_trading_day,
                skip_idempotency_check=True
            )
            return phase_success

        if phase_4_only:
            logger.info("[Pipeline] Single-phase mode: Phase 4 only")
            phase_success, phase_stats = self._execute_phase(
                "phase_4_t2_regime",
                lambda: self._run_phase_4_t2_regime(actual_trading_day),
                actual_trading_day,
                skip_idempotency_check=True
            )
            return phase_success

        if phase_5_only:
            logger.info("[Pipeline] Single-phase mode: Phase 5 only")
            phase_success, phase_stats = self._execute_phase(
                "phase_5_t3_features",
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
                "phase_1_t1_ingestion",
                lambda: self._run_phase_1_t1_ingestion(target_date, actual_trading_day),
                target_date,
                skip_idempotency_check=True
            )
            run_stats['phase_1'] = phase_stats
            if not phase_success and PIPELINE_FAILURE_MODES.get("phase_1_t1_price") == PipelineFailureMode.HALT:
                critical_success = False
                return False

            # Phase 1.5: T1 Price Quality Gate (read + conditional same-run retry).
            # Non-blocking by construction (never raises). Placed BEFORE the
            # phase_1_only early-return so --phase-1-only runs the gate too.
            stats_1_5 = self._run_phase_1_5_quality_gate(target_date, actual_trading_day)
            run_stats['phase_1_5'] = stats_1_5

            if phase_1_only:
                return critical_success

        # Phase 2: Screener Membership
        phase_success, phase_stats = self._execute_phase(
            "phase_2_screener_membership",
            lambda: self._run_phase_2_screener_membership(target_date),
            target_date
        )
        run_stats['phase_2'] = phase_stats
        if not phase_success:
            critical_success = False
            return False

        if phase_2_only:
            return critical_success

        # Phase 3: T2 Screener Features (incremental — auto-fills gaps)
        phase_success, phase_stats = self._execute_phase(
            "phase_3_t2_screener",
            lambda: self._run_phase_3_t2_screener_incremental(actual_trading_day),
            target_date,
            skip_idempotency_check=True
        )
        run_stats['phase_3'] = phase_stats
        if not phase_success:
            critical_success = False
            return False
        if phase_stats.get('rows_processed', 0) > 0:
            self.run_manager.record_write('t2_screener_features', phase_stats['rows_processed'], 'phase_3_t2_screener')

        # Phase 4: T2 Regime Scores
        phase_success, phase_stats = self._execute_phase(
            "phase_4_t2_regime",
            lambda: self._run_phase_4_t2_regime(target_date),
            target_date
        )
        run_stats['phase_4'] = phase_stats
        # Non-critical, continue even if failed

        # Phase 4b: SEPA Watchlist Update — must run AFTER t2 features are written
        # (update_daily reads t2_screener_features for the target date) and BEFORE
        # T3 (compute_t3_features filters universe via sepa_watchlist).
        phase_success, phase_stats = self._execute_phase(
            "phase_4b_sepa_watchlist",
            lambda: self._run_phase_4b_sepa_watchlist(actual_trading_day),
            target_date
        )
        run_stats['phase_4b'] = phase_stats
        if not phase_success:
            critical_success = False
            return False

        # Phase 5: T3 SEPA Features (incremental — auto-fills gaps)
        phase_success, phase_stats = self._execute_phase(
            "phase_5_t3_features",
            lambda: self._run_phase_5_t3_features_incremental(actual_trading_day),
            target_date,
            skip_idempotency_check=True
        )
        run_stats['phase_5'] = phase_stats
        if not phase_success:
            critical_success = False
            return False
        if phase_stats.get('rows_processed', 0) > 0:
            self.run_manager.record_write('t3_sepa_features', phase_stats['rows_processed'], 'phase_5_t3_features')

        # Phase 6: View Refresh
        phase_success, phase_stats = self._execute_phase(
            "phase_6_views",
            lambda: self._run_phase_6_views(target_date),
            target_date
        )
        run_stats['phase_6'] = phase_stats
        if phase_success and phase_stats.get('rows_processed', 0) > 0:
            self.run_manager.record_write('screener_watchlist', phase_stats['rows_processed'], 'phase_6_views')
        # Non-critical, continue even if failed

        # Phase 7: Training Cache Refresh
        phase_success, phase_stats = self._execute_phase(
            "phase_7_cache",
            lambda: self._run_phase_7_cache(target_date),
            target_date
        )
        run_stats['phase_7'] = phase_stats
        if phase_success and phase_stats.get('rows_processed', 0) > 0:
            self.run_manager.record_write('d2_training_cache', phase_stats['rows_processed'], 'phase_7_cache')
        # Non-critical, continue even if failed

        # Phase 7.4: Prod-model scoring (best-effort). Materializes today's scores
        # into daily_predictions for BOTH cohorts BEFORE the slim DB is built/
        # uploaded, so the dashboard reads fresh, materialized scores (never live).
        phase_success, phase_stats = self._execute_phase(
            "phase_7_4_scoring",
            lambda: self._run_phase_7_4_scoring(target_date),
            target_date,
            skip_idempotency_check=True,
        )
        run_stats['phase_7_4'] = phase_stats
        # Non-critical, continue even if failed

        # Phase 7.5: Slim dashboard DB rebuild (best-effort; a slow rebuild must
        # never block the daily pipeline). Snapshots the freshly-refreshed cache
        # + latest features into data/dashboard.duckdb for cross-device sync.
        phase_success, phase_stats = self._execute_phase(
            "phase_7_5_dashboard_db",
            lambda: self._run_phase_7_5_dashboard_db(),
            target_date
        )
        run_stats['phase_7_5'] = phase_stats
        # Non-critical, continue even if failed

        # Phase 7.6: Upload slim DB to R2 (best-effort; skipped if R2 creds absent)
        phase_success, phase_stats = self._execute_phase(
            "phase_7_6_r2_sync",
            lambda: self._run_phase_7_6_r2_sync(),
            target_date
        )
        run_stats['phase_7_6'] = phase_stats
        # Non-critical, continue even if failed

        # Phase 8: Monitoring (ALWAYS RUN)
        phase_success, phase_stats = self._execute_phase(
            "phase_8_monitoring",
            lambda: self._run_phase_8_monitoring(target_date, run_stats),
            target_date
        )
        run_stats['phase_8'] = phase_stats

        # Phase 10: Advisory model-card rebuild for the prod model (WARN-only).
        # Skips when the card is already fresh; a failure here never halts the
        # daily pipeline (the card is informational, not a gate).
        phase_success, phase_stats = self._execute_phase(
            "phase_10_model_card",
            lambda: self._run_phase_10_model_card(target_date),
            target_date,
            skip_idempotency_check=True,
        )
        run_stats['phase_10'] = phase_stats

        phases_run = len(run_stats)
        logger.info(f"[Pipeline] DONE | {phases_run} phases | {'OK' if critical_success else 'FAILED'}")

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
            phase_name: Phase identifier (e.g., 'phase_1_t1_price')
            phase_func: Function to execute
            target_date: Date being processed
            skip_idempotency_check: If True, bypass pipeline_runs check (used for Phase 1 data freshness)

        Returns:
            (success: bool, stats: dict)
        """
        # Human-readable label: "phase_3_t2_screener" -> "Phase 3"
        phase_num = phase_name.split('_')[1] if '_' in phase_name else phase_name
        label = f"Phase {phase_num}"

        # Check idempotency (skip if already completed and not force)
        if not skip_idempotency_check and not self.force and self.run_manager.is_phase_completed(target_date, phase_name):
            logger.debug(f"[{label}] SKIPPED (already completed for {target_date})")
            return True, {'status': 'skipped', 'reason': 'already_completed'}

        # Start phase tracking
        run_id = None
        if not self.dry_run:
            run_id = self.run_manager.start_phase(target_date, phase_name)
        self._current_run_id = run_id

        try:
            stats = phase_func()

            # Complete phase tracking
            if not self.dry_run:
                self.run_manager.complete_phase(
                    run_id,
                    PipelineRunStatus.SUCCESS,
                    rows_processed=stats.get('rows_processed')
                )

            return True, stats

        except Exception as e:
            error_msg = str(e)
            logger.error(f"[{label}] FAILED: {error_msg}", exc_info=True)

            if not self.dry_run:
                self.run_manager.complete_phase(
                    run_id,
                    PipelineRunStatus.FAILED,
                    error_message=error_msg
                )

            failure_mode = PIPELINE_FAILURE_MODES.get(phase_name, PipelineFailureMode.HALT)

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

        conn = duckdb.connect(self.db_path, read_only=True)
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
            logger.info("[Phase 1] Earnings calendar: no prior successful refresh — triggering")
            return True

        age_days = (datetime.now() - last_success).days
        should = age_days >= EARNINGS_CALENDAR_REFRESH_DAYS
        if should:
            logger.info(
                f"[Phase 1] Earnings calendar: last refresh {age_days}d ago "
                f"(>= {EARNINGS_CALENDAR_REFRESH_DAYS}d) — triggering"
            )
        else:
            logger.debug(
                f"[Phase 1] Earnings calendar: last refresh {age_days}d ago "
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
            logger.info(f"[Phase 1] Universe refresh: {new_tickers} new tickers added")
            run_stats['universe_refresh'] = {'status': 'success', 'new_tickers': new_tickers}
        except Exception as e:
            logger.warning(f"[Phase 1] Universe refresh FAILED (non-critical): {e}")
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
        conn = duckdb.connect(self.db_path, read_only=True)
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
        conn = duckdb.connect(self.db_path, read_only=True)
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
        logger.info(f"[Phase 1.5] Price coverage: {coverage_pct:.1f}%")

        if coverage_pct >= retry_threshold:
            return {'coverage_pct': coverage_pct, 'retry': False, 'status': 'ok'}

        missing = self._get_missing_price_tickers(latest_trading_day)
        logger.warning(
            f"[Phase 1.5] Coverage {coverage_pct:.1f}% < {retry_threshold}% — "
            f"retrying {len(missing)} tickers"
        )

        if missing:
            self.data_repo.update_cache(
                tickers=missing,
                source='yfinance',
                latest_trading_day=latest_trading_day,
            )

        coverage_pct_after = self._compute_price_coverage(latest_trading_day)
        logger.info(f"[Phase 1.5] Coverage after retry: {coverage_pct_after:.1f}%")

        if coverage_pct_after < warn_threshold:
            logger.warning(
                f"[Phase 1.5] Coverage still {coverage_pct_after:.1f}% after retry — "
                f"downstream features will use stale prices for {len(missing)} tickers"
            )

        return {
            'coverage_pct': coverage_pct_after,
            'retry': True,
            'missing_count': len(missing),
            'status': 'warned' if coverage_pct_after < warn_threshold else 'recovered',
        }

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
        conn = duckdb.connect(self.db_path, read_only=True)
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

        logger.info(f"[Phase 1] T1 Ingestion | active={len(active_tickers)}, stale={len(stale_tickers)}")

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
                logger.info(f"[Phase 1] Price: {ok_count}/{total} OK, {failed} failed ({failure_rate:.1%})")
                if ok_count > 0:
                    self.run_manager.record_write('price_data', ok_count, 'phase_1_t1_price')
                if self._current_run_id and self.data_repo.last_errors:
                    self.run_manager.record_errors(
                        self._current_run_id, 'phase_1_t1_price', self.data_repo.last_errors
                    )
                if failure_rate > 0.5:
                    logger.warning(
                        f"[Phase 1] High failure rate {failure_rate:.1%} "
                        f"({failed}/{total} tickers) — will retry next run"
                    )
            except Exception as e:
                results['price'] = {'success': False, 'error': str(e)}
                logger.error(f"[Phase 1] Price FAILED: {e}", exc_info=True)
                if PIPELINE_FAILURE_MODES.get("phase_1_t1_price") == PipelineFailureMode.HALT:
                    raise
        else:
            logger.info("[Phase 1] Price: all fresh, skipped")
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
                logger.info(f"[Phase 1] Earnings calendar: {rows} rows refreshed")
                self.run_manager.complete_phase(
                    ec_run_id, PipelineRunStatus.SUCCESS, rows_processed=rows
                )
            except Exception as e:
                results['earnings_calendar'] = {'success': False, 'error': str(e)}
                logger.warning(f"[Phase 1] Earnings calendar FAILED (non-critical): {e}")
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
                    f"[Phase 1] Fundamentals: {fund_ok}/{len(fund_results)} OK"
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
                logger.error(f"[Phase 1] Fundamentals FAILED: {e}", exc_info=True)

        # cik_map refresh (weekly) — keeps ticker→CIK lookups current for the
        # EDGAR filing-date backfill below. Cheap (~1 HTTP call, ~10K rows).
        if self._should_refresh_cik_map():
            try:
                results['cik_map_refresh'] = self._run_phase_1_cik_map_refresh(latest_trading_day)
            except Exception as e:
                results['cik_map_refresh'] = {'success': False, 'error': str(e)}
                logger.warning(f"[Phase 1] cik_map refresh FAILED (non-critical): {e}")

        # Filing-date backfill — fills filing_date for rows where it is currently
        # NULL, using SEC EDGAR as the authoritative source. Runs AFTER fundamentals
        # (any rows just upserted are eligible) and AFTER the cik_map refresh.
        if equity_tickers:
            try:
                fb_result = self._run_phase_1_filing_date_backfill(latest_trading_day)
                results['filing_date_backfill'] = fb_result
            except Exception as e:
                results['filing_date_backfill'] = {'success': False, 'error': str(e)}
                logger.warning(f"[Phase 1] Filing-date backfill FAILED (non-critical): {e}")

        # Shares — equities only (ETFs report AUM, not shares outstanding)
        if equity_tickers:
            try:
                result = self.shares_engine.update(
                    tickers=equity_tickers, latest_trading_day=latest_trading_day, max_workers=8
                )
                results['shares'] = {'success': True, 'rows_written': result}
                logger.info(f"[Phase 1] Shares: {result} rows")
                if result and result > 0:
                    self.run_manager.record_write('shares_outstanding', result, 'phase_1_t1_shares')
            except Exception as e:
                results['shares'] = {'success': False, 'error': str(e)}
                logger.error(f"[Phase 1] Shares FAILED: {e}", exc_info=True)

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
            conn = duckdb.connect(self.db_path, read_only=True)
            try:
                md_before = conn.execute("SELECT COUNT(*) FROM macro_data").fetchone()[0]
            finally:
                conn.close()
            self.macro_engine.update_macro_cache(force=False, write_db=True)
            conn = duckdb.connect(self.db_path, read_only=True)
            try:
                md_after = conn.execute("SELECT COUNT(*) FROM macro_data").fetchone()[0]
            finally:
                conn.close()
            md_rows = md_after - md_before

            results['macro'] = {
                'success': True,
                't1_macro_rows': t1_rows,
                'macro_data_rows': md_rows,
            }
            logger.info(f"[Phase 1] Macro: t1_macro +{t1_rows} rows, macro_data +{md_rows} rows")
            if t1_rows and t1_rows > 0:
                self.run_manager.record_write('t1_macro', t1_rows, 'phase_1_t1_macro')
            if md_rows and md_rows > 0:
                self.run_manager.record_write('macro_data', md_rows, 'phase_1_t1_macro')
        except Exception as e:
            results['macro'] = {'success': False, 'error': str(e)}
            logger.error(f"[Phase 1] Macro FAILED: {e}", exc_info=True)

        return {
            'rows_processed': len(active_tickers),
            'sub_phases': results
        }

    def _should_refresh_cik_map(self) -> bool:
        """Check if cik_map needs a refresh.

        Gates on the last successful run of phase_1_cik_map_refresh in
        pipeline_runs. Triggers when older than CIK_MAP_REFRESH_DAYS (default 7).
        SEC adds new tickers slowly; weekly is plenty.
        """
        from config import CIK_MAP_REFRESH_DAYS

        conn = duckdb.connect(self.db_path, read_only=True)
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
            logger.info("[Phase 1] cik_map: no prior successful refresh — triggering")
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
            logger.info(f"[Phase 1] cik_map: {n} rows after refresh")
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

        conn = duckdb.connect(self.db_path, read_only=True)
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
            logger.debug("[Phase 1] Filing-date backfill: no eligible rows")
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
                f"[Phase 1] Filing-date backfill (EDGAR): {rows_updated} rows updated "
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
            f"[Phase 2] Screener membership: active={result['active']}, "
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

        con = duckdb.connect(self.db_path, read_only=True)
        try:
            max_date_row = con.execute("SELECT MAX(date) FROM t2_screener_features").fetchone()
            max_date = max_date_row[0] if max_date_row[0] else None
        finally:
            con.close()

        if max_date is None:
            logger.warning("[Phase 3] t2_screener_features is empty — falling back to full compute from 2020-01-01")
            rows = self.feature_pipeline.compute_t2_screener_features(start_date='2020-01-01')
            return {'rows_processed': rows}

        start_date = (pd.to_datetime(max_date) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')

        if start_date > last_trading_day:
            # Date is current, but check for coverage gaps (partial ingestion)
            coverage = self._t2_coverage_deficit(last_trading_day, con_factory=lambda: duckdb.connect(self.db_path, read_only=True))
            if coverage > 0:
                logger.warning(f"[Phase 3] Coverage gap: {coverage} tickers missing for {last_trading_day} — recomputing")
                rows = self.feature_pipeline.compute_t2_screener_features(
                    start_date=last_trading_day,
                    end_date=last_trading_day
                )
                return {'rows_processed': rows}
            logger.info(f"[Phase 3] t2_screener_features already up-to-date (last={max_date}, trading_day={last_trading_day})")
            return {'rows_processed': 0}

        logger.info(f"[Phase 3] Incremental T2 compute: {start_date} -> {last_trading_day} (gap from {max_date})")
        rows = self.feature_pipeline.compute_t2_screener_features(
            start_date=start_date,
            end_date=last_trading_day
        )
        return {'rows_processed': rows}

    def _t2_coverage_deficit(self, target_date: str, con_factory=None) -> int:
        """Return number of tickers missing from t2_screener_features for target_date."""
        con = con_factory() if con_factory else duckdb.connect(self.db_path, read_only=True)
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
        """Phase 4: Compute M03 regime scores + 5-factor risk scores."""
        m03_rows = self.regime_pipeline.update_incremental()

        try:
            risk_rows = self.risk_calculator.update_incremental()
            logger.info(f"[Phase 4] 5F Risk: {risk_rows} new rows")
        except Exception as e:
            logger.warning(f"[Phase 4] 5F Risk update FAILED (non-critical): {e}")
            risk_rows = 0

        return {'rows_processed': m03_rows + risk_rows, 'm03_rows': m03_rows, 'risk_rows': risk_rows}

    def _run_phase_4b_sepa_watchlist(self, target_date: str) -> Dict:
        """Phase 4b: Update sepa_watchlist event log for the target date.

        Reads `t2_screener_features` for `target_date` and applies session events
        (open/close/cooldown→exited) per SepaWatchlistManager.update_daily(). Must
        run AFTER Phase 3 (t2 features written) and BEFORE Phase 5 (T3 filters
        universe via SELECT DISTINCT ticker FROM sepa_watchlist).
        """
        result = self.sepa_watchlist_manager.update_daily(target_date)
        return {
            'rows_processed': result['opened'] + result['closed'],
            'opened':         result['opened'],
            'closed':         result['closed'],
            'cooldown_to_exited': result['cooldown_to_exited'],
            'active':         result['active'],
        }

    def _run_phase_5_t3_features_incremental(self, last_trading_day: str) -> Dict:
        """Phase 5 incremental: detect gap in t3_sepa_features, compute missing dates only."""
        import pandas as pd

        con = duckdb.connect(self.db_path, read_only=True)
        try:
            max_date = con.execute("SELECT MAX(date) FROM t3_sepa_features").fetchone()[0]
        finally:
            con.close()

        if max_date is None:
            logger.warning("[Phase 5] t3_sepa_features is empty — falling back to full compute from 2020-01-01")
            rows = self.feature_pipeline.compute_t3_features(start_date='2020-01-01')
            return {'rows_processed': rows}

        start_date = (pd.to_datetime(max_date) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')

        if start_date > last_trading_day:
            # Date is current, but check for coverage gaps
            deficit = self._t3_coverage_deficit(last_trading_day)
            if deficit > 0:
                logger.warning(f"[Phase 5] Coverage gap: {deficit} breakout tickers missing for {last_trading_day} — recomputing")
                rows = self.feature_pipeline.compute_t3_features(
                    start_date=last_trading_day,
                    end_date=last_trading_day
                )
                return {'rows_processed': rows}
            logger.info(f"[Phase 5] t3_sepa_features already up-to-date (last={max_date}, trading_day={last_trading_day})")
            return {'rows_processed': 0}

        logger.info(f"[Phase 5] Incremental T3 compute: {start_date} -> {last_trading_day} (gap from {max_date})")
        rows = self.feature_pipeline.compute_t3_features(
            start_date=start_date,
            end_date=last_trading_day
        )
        return {'rows_processed': rows}

    def _t3_coverage_deficit(self, target_date: str) -> int:
        """Return number of breakout tickers missing from t3_sepa_features for target_date."""
        con = duckdb.connect(self.db_path, read_only=True)
        try:
            expected = con.execute(f"""
                SELECT COUNT(DISTINCT ticker)
                FROM t2_screener_features
                WHERE date = '{target_date}' AND trend_ok = TRUE AND breakout_ok = TRUE
            """).fetchone()[0]
            actual = con.execute(f"""
                SELECT COUNT(DISTINCT ticker)
                FROM t3_sepa_features
                WHERE date = '{target_date}'
            """).fetchone()[0]
            return max(0, expected - actual)
        finally:
            con.close()

    def _run_phase_6_views(self, target_date: str) -> Dict:
        """Phase 6: Refresh all views."""

        view_count = self.view_manager.create_all()
        logger.info(f"[Phase 6] Views refreshed: {view_count} views")

        return {'rows_processed': view_count}

    def _run_phase_7_cache(self, target_date: str) -> Dict:
        """Phase 7: Refresh training cache."""

        self.view_manager.refresh_cache(verbose=False)
        stats = self.view_manager.get_cache_stats()
        rows = stats.get('row_count', 0)
        logger.info(f"[Phase 7] Training cache refreshed: {rows:,} rows")

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
            logger.warning(f"[Phase 7.4] Prediction logging skipped: {e}")
        return {'rows_processed': n}

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
            logger.warning(f"[Phase 7.5] Build script not found: {build_script}")
            return {'rows_processed': 0}

        proc = subprocess.run(
            [sys.executable, str(build_script)],
            capture_output=True, text=True, timeout=600,
            cwd=str(project_root),
        )
        if proc.returncode != 0:
            logger.warning(
                f"[Phase 7.5] dashboard DB rebuild failed (rc={proc.returncode}): "
                f"{proc.stderr.strip()[:500]}"
            )
            return {'rows_processed': 0}

        out_db = project_root / "data" / "dashboard.duckdb"
        size_mb = out_db.stat().st_size / 1024 ** 2 if out_db.exists() else 0
        logger.info(f"[Phase 7.5] Slim dashboard DB rebuilt: {size_mb:,.0f} MB")
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

        if not os.environ.get("R2_ACCOUNT_ID"):
            logger.info("[Phase 7.6] R2 credentials absent; skipping upload")
            return {'rows_processed': 0}

        project_root = Path(__file__).resolve().parent.parent.parent
        sync_script = project_root / "scripts" / "sync_dashboard_db.py"
        if not sync_script.exists():
            logger.warning(f"[Phase 7.6] Sync script not found: {sync_script}")
            return {'rows_processed': 0}

        proc = subprocess.run(
            [sys.executable, str(sync_script)],
            capture_output=True, text=True, timeout=300,
            cwd=str(project_root),
        )
        if proc.returncode != 0:
            logger.warning(
                f"[Phase 7.6] R2 upload failed (rc={proc.returncode}): "
                f"{proc.stderr.strip()[:500]}"
            )
            return {'rows_processed': 0}

        logger.info("[Phase 7.6] dashboard.duckdb uploaded to R2 (latest/)")
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
            logger.info("[Phase 10] No prod model registered; skipping card build.")
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
                    f"[Phase 10] Drift card for {prod_version} is fresh "
                    f"(built {built_at}); skipping rebuild."
                )
                return {'rows_processed': 0, 'status': 'fresh'}

        project_root = Path(__file__).resolve().parent.parent.parent
        build_script = project_root / "scripts" / "build_model_card.py"
        if not build_script.exists():
            logger.warning(f"[Phase 10] Build script not found: {build_script}")
            return {'rows_processed': 0, 'status': 'no_script'}

        # Resolve the clean '<name>/<version>' slug (maps to models/<name>/<version>/
        # model.json and yields a clean card filename) rather than the timestamped
        # version_id, which build_model_card.py cannot resolve.
        try:
            model_slug = registry.get_model_slug(prod_version)
        except ValueError as e:
            logger.warning(f"[Phase 10] {e}")
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
            logger.warning("[Phase 10] Drift card build timed out after 1800s")
            return {'rows_processed': 0, 'status': 'timeout'}

        if proc.returncode != 0:
            logger.warning(
                f"[Phase 10] Drift card build failed (rc={proc.returncode}): "
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
            f"[Phase 10] Rebuilt drift card ({start_date}..{target_date}) "
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

        # Log alerts
        if alerts:
            logger.warning("[Phase 8] ALERTS TRIGGERED:")
            for alert in alerts:
                logger.warning(f"  {alert}")
        else:
            logger.info("[Phase 8] No alerts - pipeline health OK")

        # Log health summary
        logger.info(f"[Phase 8] Data freshness: {health['max_dates']}")
        logger.info(f"[Phase 8] Breakout drought: {health['breakout_drought_days']} days")

        # Prediction logging moved to Phase 7.4 (runs before the dashboard DB is
        # built/uploaded so today's scores ride along; see _run_phase_7_4_scoring).
        predictions_written = run_stats.get('phase_7_4', {}).get('rows_processed', 0)

        # Quarterly feature-drift report (best-effort; only fires on 1st of Jan/Apr/Jul/Oct).
        drift_report = None
        try:
            drift_report = self._maybe_run_quarterly_drift(target_date)
        except Exception as e:
            logger.warning(f"[Phase 8] Quarterly drift report skipped: {e}")

        # Daily audit report (best-effort; populates Pipeline Health audit history).
        audit_report = None
        try:
            audit_report = self._run_daily_audits(target_date)
        except Exception as e:
            logger.warning(f"[Phase 8] Daily audit run skipped: {e}")

        return {
            'rows_processed': predictions_written,
            'alerts': alerts,
            'health': health,
            'coverage': coverage,
            'predictions_written': predictions_written,
            'drift_report': drift_report,
            'audit_report': audit_report,
        }

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
            logger.warning(f"[Phase 8] Audit script not found: {audit_script}")
            return None

        cmd = [sys.executable, str(audit_script), "--date", target_date, "--warn-only"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            logger.warning("[Phase 8] Audit run timed out after 600s")
            return None

        # run_all_audits exits 0 (all OK) or 1 (any WARNING/FAIL); 2+ = crash.
        if proc.returncode not in (0, 1):
            err = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "unknown"
            logger.warning(f"[Phase 8] Audit run crashed (rc={proc.returncode}): {err}")
            return None

        # The script writes audit_report_YYYYMMDD.json keyed by UTC run date.
        from datetime import datetime as _dt
        date_str = _dt.utcnow().strftime("%Y%m%d")
        report_path = repo_root / "data" / "audit_reports" / f"audit_report_{date_str}.json"
        if not report_path.exists():
            logger.warning(f"[Phase 8] Audit report not written at expected path: {report_path}")
            return None

        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            logger.warning(f"[Phase 8] Could not parse audit report: {e}")
            return None

        summary = report.get("summary", {}).get("total", {})
        logger.info(
            f"[Phase 8] Audit report saved ({report_path.name}): "
            f"FAIL={summary.get('FAIL', 0)} WARN={summary.get('WARNING', 0)} "
            f"OK={summary.get('OK', 0)} overall={report.get('overall')}"
        )
        return {
            'path': str(report_path),
            'overall': report.get('overall'),
            'summary': summary,
        }

    def _log_prod_model_predictions(self, target_date: str) -> int:
        """Score `target_date` candidates with the prod model and log predictions.

        Scores TWO cohorts so the dashboard never has to score live:
        - 'breakout'      — SEPA entries from v_d3_deployment (breakout_ok=TRUE)
        - 'pre_breakout'  — in-setup names (trend_ok=TRUE AND breakout_ok=FALSE)

        Skips silently (returns 0) if no prod model is registered or its artifact
        is missing. A failure on one cohort never blocks the other.
        """
        from pathlib import Path as _Path
        from src.model_registry import ModelRegistry

        registry = ModelRegistry(db_path=self.db_path)
        prod_version_id = registry.get_prod_version()
        if not prod_version_id:
            logger.info("[Phase 8] No prod model registered — skipping prediction log.")
            return 0

        try:
            artifacts_path = registry.get_artifacts_path(prod_version_id)
        except ValueError:
            logger.warning(f"[Phase 8] Prod model {prod_version_id} has no artifacts_path.")
            return 0

        model_path = _Path(artifacts_path) / "model.json"
        if not model_path.exists():
            logger.warning(f"[Phase 8] Model artifact missing: {model_path}")
            return 0

        total = 0
        for cohort, candidates in (
            ("breakout", self._fetch_breakout_candidates(target_date)),
            ("pre_breakout", self._fetch_pre_breakout_candidates(target_date)),
        ):
            try:
                total += self._score_and_log_cohort(
                    cohort, candidates, target_date, registry, prod_version_id, model_path
                )
            except Exception as e:
                logger.warning(f"[Phase 8] Scoring cohort '{cohort}' failed: {e}")
        return total

    def _fetch_breakout_candidates(self, target_date: str):
        """SEPA breakout entries for target_date (v_d3_deployment)."""
        con = duckdb.connect(self.db_path, read_only=True)
        try:
            return con.execute(
                "SELECT * FROM v_d3_deployment WHERE date = ?", [target_date]
            ).df()
        except duckdb.Error as e:
            logger.warning(f"[Phase 8] Could not query v_d3_deployment: {e}")
            import pandas as pd
            return pd.DataFrame()
        finally:
            con.close()

    def _fetch_pre_breakout_candidates(self, target_date: str):
        """In-setup names (trend_ok AND NOT breakout_ok) for target_date.

        Reads v_d3_prebreakout, which hydrates the pre-breakout cohort with the
        SAME feature contract as v_d3_deployment (deltas + fundamentals), so the
        prod model scores both cohorts with one feature list.
        """
        con = duckdb.connect(self.db_path, read_only=True)
        try:
            return con.execute(
                "SELECT * FROM v_d3_prebreakout WHERE date = ?", [target_date]
            ).df()
        except duckdb.Error as e:
            logger.warning(f"[Phase 8] Could not query v_d3_prebreakout: {e}")
            import pandas as pd
            return pd.DataFrame()
        finally:
            con.close()

    def _score_and_log_cohort(
        self, cohort, candidates, target_date, registry, prod_version_id, model_path
    ) -> int:
        """Score one cohort's candidate frame with the prod model and log it."""
        from src.evaluation.prediction_logger import log_daily_predictions

        if candidates.empty:
            logger.info(f"[Phase 8] No '{cohort}' candidates on {target_date}.")
            return 0

        import numpy as np
        import pandas as pd
        import xgboost as xgb

        booster = xgb.Booster()
        booster.load_model(str(model_path))
        feature_cols = self._resolve_prod_feature_cols(registry, prod_version_id, candidates)
        if not feature_cols:
            logger.warning(f"[Phase 8] Could not resolve prod feature columns for '{cohort}'.")
            return 0

        X = candidates[feature_cols].replace([float('inf'), float('-inf')], None)
        for col in X.select_dtypes(include='object').columns:
            X[col] = X[col].astype('category')
        dmatrix = xgb.DMatrix(X, enable_categorical=True)
        proba = np.asarray(booster.predict(dmatrix))
        if proba.ndim == 1:
            proba = np.column_stack([1 - proba, proba])

        n_classes = proba.shape[1]
        pred_df = candidates[["ticker"]].copy()
        for i in range(n_classes):
            pred_df[f"prob_class_{i}"] = proba[:, i]
        pred_df["predicted_class"] = proba.argmax(axis=1)

        target_dt = pd.to_datetime(target_date).date() if isinstance(target_date, str) else target_date
        n = log_daily_predictions(
            db_path=Path(self.db_path),
            prediction_date=target_dt,
            model_version_id=prod_version_id,
            predictions=pred_df,
            production_class_idx=n_classes - 1,
            cohort=cohort,
        )
        logger.info(f"[Phase 8] Logged {n} '{cohort}' predictions for {prod_version_id} on {target_date}")
        return n

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
            logger.info("[Phase 8] No prod model — skipping drift report.")
            return None

        try:
            artifacts_path = registry.get_artifacts_path(prod_version_id)
        except ValueError:
            logger.warning(f"[Phase 8] Prod model {prod_version_id} has no artifacts_path; skipping drift.")
            return None

        snapshot_path = _Path(artifacts_path) / "reference_snapshot.json"
        if not snapshot_path.exists():
            logger.info(
                f"[Phase 8] No reference_snapshot.json under {artifacts_path} "
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
            f"[Phase 8] Drift report {quarter}: {gate['status']} — "
            f"{report['n_features_drifted']} drifted, "
            f"{report['n_features_warned']} warned, "
            f"{report['n_features_skipped']} skipped → {out_path}"
        )
        if report["drifted_features"]:
            sample = report["drifted_features"][:5]
            logger.warning(f"[Phase 8] Drifted features (top {len(sample)}): {sample}")
        return report

    def _resolve_prod_feature_cols(self, registry, version_id: str, candidates_df) -> list[str]:
        """Find which v_d3_deployment columns to feed the prod model.

        Prefer the model's recorded feature_set_id from the models table;
        intersect with columns actually present in candidates_df. Falls back to
        an empty list (caller logs and skips).
        """
        try:
            specs = registry.get_model_specs(version_id) or {}
        except Exception:
            specs = {}
        feature_names = specs.get("features") or []
        if not feature_names:
            return []
        # case-insensitive match
        cols_lower = {c.lower(): c for c in candidates_df.columns}
        resolved = []
        for f in feature_names:
            actual = cols_lower.get(f.lower())
            if actual is not None:
                resolved.append(actual)
        return resolved

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
        from config import FUNDAMENTAL_STALENESS_DAYS, EXPECTED_NEXT_FILING_LAG_DAYS

        ticker_df = pd.DataFrame({'ticker': tickers})
        con = duckdb.connect(self.db_path, read_only=True)
        try:
            con.register('_dq_tickers', ticker_df)

            bogus = con.execute("""
                SELECT ticker, period_end, filing_date,
                       DATE_DIFF('day', period_end, filing_date) AS gap_days
                FROM fundamentals
                WHERE ticker IN (SELECT ticker FROM _dq_tickers)
                  AND filing_date IS NOT NULL
                  AND DATE_DIFF('day', period_end, filing_date) < 8
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
                f"[Phase 1] DQ: {len(bogus)} legacy rows with filing_date < 8d after period_end. "
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
                f"[Phase 1] DQ: {len(stale)} equities with stale fundamentals "
                f"(next quarter overdue: period_end>{EXPECTED_NEXT_FILING_LAG_DAYS}d ago; "
                f"null_filing={null_count}). Sample: {sample_str or 'n/a'}"
            )

    def _check_coverage(self, target_date: str) -> Dict:
        """Check ticker coverage across pipeline tables for the target date.

        Compares expected tickers (price_data + screener_membership) against
        actual tickers in t2_screener_features and t3_sepa_features. Gaps
        indicate partial ingestion (e.g., API rate limits during Phase 1).
        """
        con = duckdb.connect(self.db_path, read_only=True)
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
                logger.debug(f"[Phase 8] Missing tickers sample: {sample}")
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
            logger.error(f"[Phase 8] Coverage check failed: {e}", exc_info=True)
            alerts.append(f"Coverage check failed: {e}")
        finally:
            con.close()

        if not alerts:
            logger.info(
                f"[Phase 8] Coverage: t2={details.get('t2_tickers', '?')}/{details.get('expected_tickers', '?')} tickers, "
                f"t3={details.get('t3_tickers', '?')}/{details.get('t2_breakouts', '?')} breakouts"
            )

        return {'alerts': alerts, 'details': details}
