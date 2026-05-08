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
from typing import Dict, Tuple, Optional
import duckdb

# Import layers
from src.data_engine import DataRepository
from src.fundamental_engine import FundamentalEngine
from src.shares_engine import SharesEngine
from src.macro_engine import MacroEngine
from src.feature_pipeline import FeaturePipeline
from src.regime_pipeline import RegimePipeline
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

        # Initialize pipelines (delegate computation)
        self.feature_pipeline = FeaturePipeline(self.db_path)
        self.regime_pipeline = RegimePipeline(self.db_path)

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

        # Phase 8: Monitoring (ALWAYS RUN)
        phase_success, phase_stats = self._execute_phase(
            "phase_8_monitoring",
            lambda: self._run_phase_8_monitoring(target_date, run_stats),
            target_date
        )
        run_stats['phase_8'] = phase_stats

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
        """Check if earnings calendar needs a monthly refresh.

        Triggers on the first trading day of each month by checking whether
        any earnings_calendar row was updated this month already.
        """
        td = datetime.strptime(trading_day, '%Y-%m-%d')
        month_start = td.replace(day=1).strftime('%Y-%m-%d')

        conn = duckdb.connect(self.db_path, read_only=True)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM earnings_calendar WHERE updated_at >= ?",
                [month_start]
            ).fetchone()
            already_refreshed = row[0] > 0
        finally:
            conn.close()

        if not already_refreshed:
            logger.debug(f"[Phase 1] Earnings calendar needs monthly refresh (since {month_start})")
        return not already_refreshed

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
        conn = duckdb.connect(self.db_path, read_only=True)
        try:
            active_tickers = [t[0] for t in conn.execute(
                "SELECT ticker FROM company_profiles WHERE is_active = TRUE ORDER BY ticker"
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

        # Earnings Calendar (monthly)
        if active_tickers and self._should_refresh_earnings_calendar(latest_trading_day):
            try:
                rows = self.fund_engine.refresh_earnings_calendar(active_tickers)
                results['earnings_calendar'] = {'success': True, 'rows_written': rows}
                logger.info(f"[Phase 1] Earnings calendar: {rows} rows refreshed")
            except Exception as e:
                results['earnings_calendar'] = {'success': False, 'error': str(e)}
                logger.warning(f"[Phase 1] Earnings calendar FAILED (non-critical): {e}")

        # Fundamentals
        if active_tickers:
            try:
                result = self.fund_engine.update_fundamentals(
                    tickers=active_tickers,
                    target_date=target_date,
                    force=False,
                )
                fund_results = result if isinstance(result, dict) else {}
                fund_ok = sum(1 for v in fund_results.values() if v)
                fund_failed = len(fund_results) - fund_ok
                results['fundamentals'] = {'success': True, 'ok': fund_ok, 'failed': fund_failed}
                logger.info(f"[Phase 1] Fundamentals: {fund_ok}/{len(fund_results)} OK")
                if fund_ok > 0:
                    self.run_manager.record_write('fundamentals', fund_ok, 'phase_1_t1_fundamentals')
                if self._current_run_id and self.fund_engine.last_errors:
                    self.run_manager.record_errors(
                        self._current_run_id, 'phase_1_t1_fundamentals', self.fund_engine.last_errors
                    )
                self._check_filing_date_quality(active_tickers)
            except Exception as e:
                results['fundamentals'] = {'success': False, 'error': str(e)}
                logger.error(f"[Phase 1] Fundamentals FAILED: {e}", exc_info=True)

        # Shares
        if active_tickers:
            try:
                result = self.shares_engine.update(
                    tickers=active_tickers, latest_trading_day=latest_trading_day, max_workers=8
                )
                results['shares'] = {'success': True, 'rows_written': result}
                logger.info(f"[Phase 1] Shares: {result} rows")
                if result and result > 0:
                    self.run_manager.record_write('shares_outstanding', result, 'phase_1_t1_shares')
            except Exception as e:
                results['shares'] = {'success': False, 'error': str(e)}
                logger.error(f"[Phase 1] Shares FAILED: {e}", exc_info=True)

        # Macro
        try:
            result = self.macro_engine.ingest_daily_macro(start_date=latest_trading_day, force=False)
            rows = result.get('rows_written', 0) if isinstance(result, dict) else result
            results['macro'] = {'success': True, 'rows_written': rows}
            logger.info(f"[Phase 1] Macro: {rows} rows")
            if rows and rows > 0:
                self.run_manager.record_write('macro_data', rows, 'phase_1_t1_macro')
        except Exception as e:
            results['macro'] = {'success': False, 'error': str(e)}
            logger.error(f"[Phase 1] Macro FAILED: {e}", exc_info=True)

        return {
            'rows_processed': len(active_tickers),
            'sub_phases': results
        }

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
        """Phase 4: Compute M03 regime scores."""

        rows = self.regime_pipeline.update_incremental()

        return {'rows_processed': rows}

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

        return {
            'rows_processed': 0,
            'alerts': alerts,
            'health': health,
            'coverage': coverage,
        }

    def _check_filing_date_quality(self, tickers: list) -> None:
        """Warn if any fundamental rows have filing_date <= 7 days after period_end.

        A gap <= 7 days means yfinance mapped an earnings announcement date (which can be
        1-3 days after quarter-end for fast reporters) rather than the actual 10-Q filing date.
        Legitimate 10-Q filings take at least 8 days; accelerated filers average 20-30 days.
        """
        if not tickers:
            return
        ticker_list = ", ".join(f"'{t}'" for t in tickers)
        con = duckdb.connect(self.db_path, read_only=True)
        try:
            rows = con.execute(f"""
                SELECT ticker, period_end, filing_date,
                       DATE_DIFF('day', period_end, filing_date) AS gap_days
                FROM fundamentals
                WHERE ticker IN ({ticker_list})
                  AND filing_date IS NOT NULL
                  AND DATE_DIFF('day', period_end, filing_date) <= 7
                ORDER BY gap_days
                LIMIT 20
            """).fetchdf()
        finally:
            con.close()

        if not rows.empty:
            sample = ", ".join(f"{r.ticker} ({r.gap_days}d)" for r in rows.head(5).itertuples())
            logger.warning(
                f"[Phase 1] DQ: {len(rows)} fundamentals with filing_date <= 7d after period_end. "
                f"Sample: {sample}"
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
