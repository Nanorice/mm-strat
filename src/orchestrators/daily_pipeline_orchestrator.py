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
from src.managers.pipeline_run_manager import PipelineRunManager, PipelineRunStatus

# Import config
from config import PIPELINE_FAILURE_MODES, PipelineFailureMode, PIPELINE_ALERT_THRESHOLDS

logger = logging.getLogger(__name__)


class DailyPipelineOrchestrator:
    """
    Orchestrates the daily 8-phase pipeline.

    Phase 1: T1 Ingestion (PARALLEL) - price, fundamentals, shares, macro
    Phase 2: Screener Membership - evaluate_and_log to screener_membership event log
    Phase 3: T2 Screener Features - compute full universe features + XS alphas + ranks
    Phase 4: T2 Regime Scores - compute M03 regime scores
    Phase 5: T3 SEPA Features - compute per-ticker features + TS alphas for SEPA candidates
    Phase 6: View Refresh - recreate all views
    Phase 7: Training Cache Refresh - materialize d2_training_cache
    Phase 8: Monitoring - log metrics, send alerts
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

        logger.debug(f"[Orchestrator] Initialized (db={self.db_path}, dry_run={dry_run}, force={force})")

        # Initialize managers (delegate state tracking)
        self.run_manager = PipelineRunManager(self.db_path)
        self.view_manager = ViewManager(self.db_path)
        self.screener_manager = ScreenerManager(self.db_path)

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

        logger.info("=" * 60)
        logger.info(f"DAILY PIPELINE | Trading Day: {actual_trading_day}")
        logger.info("=" * 60)

        # Track overall success (CRITICAL phases only)
        critical_success = True
        run_stats = {}

        # --- Phase-only shortcuts ---
        if phase_3_only:
            logger.info("[Orchestrator] --phase-3-only: running Phase 3 incremental only")
            phase_success, phase_stats = self._execute_phase(
                "phase_3_t2_screener",
                lambda: self._run_phase_3_t2_screener_incremental(actual_trading_day),
                actual_trading_day,
                skip_idempotency_check=True
            )
            return phase_success

        if phase_4_only:
            logger.info("[Orchestrator] --phase-4-only: running Phase 4 incremental only")
            phase_success, phase_stats = self._execute_phase(
                "phase_4_t2_regime",
                lambda: self._run_phase_4_t2_regime(actual_trading_day),
                actual_trading_day,
                skip_idempotency_check=True
            )
            return phase_success

        if phase_5_only:
            logger.info("[Orchestrator] --phase-5-only: running Phase 5 incremental only")
            phase_success, phase_stats = self._execute_phase(
                "phase_5_t3_features",
                lambda: self._run_phase_5_t3_features_incremental(actual_trading_day),
                actual_trading_day,
                skip_idempotency_check=True
            )
            return phase_success

        if phase_2_only:
            logger.info("[Orchestrator] --phase-2-only: skipping Phase 1, running Phase 2 only")
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
                logger.error("[Orchestrator] Phase 1 FAILED - HALTING pipeline")
                return False

            if phase_1_only:
                logger.info("[Orchestrator] --phase-1-only: stopping after Phase 1")
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
            logger.error("[Orchestrator] Phase 2 FAILED - HALTING pipeline")
            return False

        if phase_2_only:
            logger.info("[Orchestrator] --phase-2-only: stopping after Phase 2")
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
            logger.error("[Orchestrator] Phase 3 FAILED - HALTING pipeline")
            return False

        # Phase 4: T2 Regime Scores
        phase_success, phase_stats = self._execute_phase(
            "phase_4_t2_regime",
            lambda: self._run_phase_4_t2_regime(target_date),
            target_date
        )
        run_stats['phase_4'] = phase_stats
        # Non-critical, continue even if failed

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
            logger.error("[Orchestrator] Phase 5 FAILED - HALTING pipeline")
            return False

        # Phase 6: View Refresh
        phase_success, phase_stats = self._execute_phase(
            "phase_6_views",
            lambda: self._run_phase_6_views(target_date),
            target_date
        )
        run_stats['phase_6'] = phase_stats
        # Non-critical, continue even if failed

        # Phase 7: Training Cache Refresh
        phase_success, phase_stats = self._execute_phase(
            "phase_7_cache",
            lambda: self._run_phase_7_cache(target_date),
            target_date
        )
        run_stats['phase_7'] = phase_stats
        # Non-critical, continue even if failed

        # Phase 8: Monitoring (ALWAYS RUN)
        phase_success, phase_stats = self._execute_phase(
            "phase_8_monitoring",
            lambda: self._run_phase_8_monitoring(target_date, run_stats),
            target_date
        )
        run_stats['phase_8'] = phase_stats

        logger.info("=" * 60)
        logger.info(f"PIPELINE {'OK' if critical_success else 'FAILED'}")
        logger.info("=" * 60)

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
        # Check idempotency (skip if already completed and not force)
        if not skip_idempotency_check and not self.force and self.run_manager.is_phase_completed(target_date, phase_name):
            logger.info(f"[{phase_name}] SKIPPED (already completed for {target_date})")
            return True, {'status': 'skipped', 'reason': 'already_completed'}

        # Start phase tracking
        run_id = None
        if not self.dry_run:
            run_id = self.run_manager.start_phase(target_date, phase_name)

        try:
            # Execute phase function (phases log their own details)
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
            logger.error(f"[{phase_name}] FAILED - {error_msg}", exc_info=True)

            # Complete phase tracking with FAILED status
            if not self.dry_run:
                self.run_manager.complete_phase(
                    run_id,
                    PipelineRunStatus.FAILED,
                    error_message=error_msg
                )

            # Handle error per failure mode
            failure_mode = PIPELINE_FAILURE_MODES.get(phase_name, PipelineFailureMode.HALT)

            if failure_mode == PipelineFailureMode.HALT:
                logger.critical(f"[{phase_name}] CRITICAL FAILURE - HALTING PIPELINE")
                return False, {'status': 'failed', 'error': error_msg}
            elif failure_mode == PipelineFailureMode.WARN:
                logger.warning(f"[{phase_name}] NON-CRITICAL FAILURE - CONTINUING")
                return True, {'status': 'warned', 'error': error_msg}
            else:  # SKIP
                logger.info(f"[{phase_name}] OPTIONAL FAILURE - SKIPPING")
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
                logger.debug(f"[Market Calendar] Last trading day: {last_day} (via SPY)")
                return last_day
        except Exception as e:
            logger.warning(f"[Market Calendar] SPY download failed: {e}")

        # Last resort: skip weekends arithmetically
        dt = datetime.strptime(target_date, '%Y-%m-%d')
        while dt.weekday() >= 5:  # Saturday=5, Sunday=6
            dt -= timedelta(days=1)
        last_day = dt.strftime('%Y-%m-%d')
        logger.warning(f"[Market Calendar] Using weekend-adjusted fallback: {last_day}")
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
            logger.info(f"[Earnings Calendar] No refresh this month (since {month_start}) — triggering refresh")
        return not already_refreshed

    def _run_phase_1_1_quarterly_refresh(self, run_stats: Dict) -> None:
        """
        Quarterly Universe Refresh — only runs when run_pipeline(universe_refresh=True).

        Discovers newly-listed tickers, writes profiles, backfills price + shares.
        Non-critical: pipeline continues on failure.
        """
        try:
            logger.info("[Universe Refresh] Running quarterly universe refresh...")
            new_tickers = self.universe_backfill.quarterly_refresh()
            logger.info(f"[Universe Refresh] {'SUCCESS' if new_tickers >= 0 else 'WARN'} - {new_tickers} new tickers added")
            run_stats['universe_refresh'] = {'status': 'success', 'new_tickers': new_tickers}
        except Exception as e:
            logger.warning(f"[Universe Refresh] FAILED (non-critical): {e}")
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

        # 1.1: Price
        if stale_tickers:
            try:
                result = self.data_repo.update_cache(
                    tickers=stale_tickers,
                    source='yfinance',
                    latest_trading_day=latest_trading_day,
                )
                ticker_results = result if isinstance(result, dict) else {}
                total = len(ticker_results)
                failed = sum(1 for ok in ticker_results.values() if not ok)
                failure_rate = failed / total if total > 0 else 0.0
                results['price'] = {'success': True, 'ok': total - failed, 'failed': failed}
                logger.info(f"  [1.1] Price: {total - failed}/{total} OK, {failed} failed ({failure_rate:.1%})")
                if failure_rate > 0.5:
                    logger.warning(
                        f"  [1.1] ⚠️ High failure rate {failure_rate:.1%} "
                        f"({failed}/{total} tickers) — will retry next run"
                    )
            except Exception as e:
                results['price'] = {'success': False, 'error': str(e)}
                logger.error(f"  [1.1] Price FAILED: {e}")
                if PIPELINE_FAILURE_MODES.get("phase_1_t1_price") == PipelineFailureMode.HALT:
                    raise
        else:
            logger.info("  [1.1] Price: all fresh — skipped")
            results['price'] = {'success': True, 'ok': 0, 'failed': 0}

        # 1.2a: Earnings Calendar Refresh (monthly — first run of each month)
        if active_tickers and self._should_refresh_earnings_calendar(latest_trading_day):
            try:
                rows = self.fund_engine.refresh_earnings_calendar(active_tickers)
                results['earnings_calendar'] = {'success': True, 'rows_written': rows}
                logger.info(f"  [1.2a] Earnings calendar: {rows} rows refreshed")
            except Exception as e:
                results['earnings_calendar'] = {'success': False, 'error': str(e)}
                logger.warning(f"  [1.2a] Earnings calendar FAILED (non-critical): {e}")

        # 1.2: Fundamentals
        if active_tickers:
            try:
                result = self.fund_engine.update_fundamentals(
                    tickers=active_tickers,
                    target_date=target_date,
                    force=False,
                )
                fund_results = result if isinstance(result, dict) else {}
                fund_ok = sum(1 for v in fund_results.values() if v)
                results['fundamentals'] = {'success': True, 'ok': fund_ok, 'failed': len(fund_results) - fund_ok}
                logger.info(f"  [1.2] Fundamentals: {fund_ok}/{len(fund_results)} OK")
            except Exception as e:
                results['fundamentals'] = {'success': False, 'error': str(e)}
                logger.error(f"  [1.2] Fundamentals FAILED: {e}")

        # 1.3: Shares
        if active_tickers:
            try:
                result = self.shares_engine.update(
                    tickers=active_tickers, latest_trading_day=latest_trading_day, max_workers=8
                )
                results['shares'] = {'success': True, 'rows_written': result}
                logger.info(f"  [1.3] Shares: {result} rows written")
            except Exception as e:
                results['shares'] = {'success': False, 'error': str(e)}
                logger.error(f"  [1.3] Shares FAILED: {e}")

        # 1.4: Macro
        try:
            result = self.macro_engine.ingest_daily_macro(start_date=latest_trading_day, force=False)
            rows = result.get('rows_written', 0) if isinstance(result, dict) else result
            results['macro'] = {'success': True, 'rows_written': rows}
            logger.info(f"  [1.4] Macro: {rows} rows")
        except Exception as e:
            results['macro'] = {'success': False, 'error': str(e)}
            logger.error(f"  [1.4] Macro FAILED: {e}")

        # Phase 1 Summary
        price_r = results.get('price', {})
        fund_r = results.get('fundamentals', {})
        shares_r = results.get('shares', {})
        macro_r = results.get('macro', {})
        logger.info(
            f"[Phase 1] Done: "
            f"Price={price_r.get('ok', 0)}/{price_r.get('ok', 0) + price_r.get('failed', 0)} | "
            f"Fund={fund_r.get('ok', '?')}/{fund_r.get('ok', 0) + fund_r.get('failed', 0)} | "
            f"Shares={shares_r.get('rows_written', 0)} | "
            f"Macro={macro_r.get('rows_written', 0)}"
        )

        return {
            'rows_processed': len(active_tickers),
            'sub_phases': results
        }

    def _run_phase_2_screener_membership(self, target_date: str) -> Dict:
        """Phase 2: Evaluate and log screener membership event."""

        result = self.screener_manager.evaluate_and_log(target_date)

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
            logger.info(f"[Phase 3] t2_screener_features already up-to-date (last={max_date}, trading_day={last_trading_day})")
            return {'rows_processed': 0}

        logger.info(f"[Phase 3] Incremental T2 compute: {start_date} -> {last_trading_day} (gap from {max_date})")
        rows = self.feature_pipeline.compute_t2_screener_features(
            start_date=start_date,
            end_date=last_trading_day
        )
        return {'rows_processed': rows}

    def _run_phase_4_t2_regime(self, target_date: str) -> Dict:
        """Phase 4: Compute M03 regime scores."""

        rows = self.regime_pipeline.update_incremental()

        return {'rows_processed': rows}

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
            logger.info(f"[Phase 5] t3_sepa_features already up-to-date (last={max_date}, trading_day={last_trading_day})")
            return {'rows_processed': 0}

        logger.info(f"[Phase 5] Incremental T3 compute: {start_date} -> {last_trading_day} (gap from {max_date})")
        rows = self.feature_pipeline.compute_t3_features(
            start_date=start_date,
            end_date=last_trading_day
        )
        return {'rows_processed': rows}

    def _run_phase_6_views(self, target_date: str) -> Dict:
        """Phase 6: Refresh all views."""

        view_count = self.view_manager.create_all()

        return {'rows_processed': view_count}

    def _run_phase_7_cache(self, target_date: str) -> Dict:
        """Phase 7: Refresh training cache."""

        self.view_manager.refresh_cache(verbose=False)
        stats = self.view_manager.get_cache_stats()
        rows = stats.get('row_count', 0)

        return {'rows_processed': rows}

    def _run_phase_8_monitoring(self, target_date: str, run_stats: Dict) -> Dict:
        """Phase 8: Generate health report and alerts. Always runs."""

        # Get health report
        health = self.run_manager.get_health_report(target_date)

        # Check for alerts
        alerts = []

        # Alert 1: Breakout drought
        if health['breakout_drought_days'] >= PIPELINE_ALERT_THRESHOLDS['breakout_drought_days']:
            alerts.append(
                f"[WARN] ALERT: 0 breakouts for {health['breakout_drought_days']} consecutive days"
            )

        # Alert 2: Runtime anomalies
        for anomaly in health['runtime_anomalies']:
            alerts.append(
                f"[WARN] ALERT: Phase '{anomaly['phase_name']}' took {anomaly['runtime_sec']}s "
                f"(avg: {anomaly['avg_runtime_sec']}s, {anomaly['ratio']}x slower)"
            )

        # Alert 3: Recent failures
        if health['recent_failures']:
            alerts.append(
                f"[WARN] ALERT: {len(health['recent_failures'])} phase failures in last 7 days"
            )

        # Log alerts
        if alerts:
            logger.warning("ALERTS TRIGGERED:")
            for alert in alerts:
                logger.warning(f"   {alert}")
        else:
            logger.info("[OK] No alerts - pipeline health OK")

        # Log health summary
        logger.info(f"Data Freshness: {health['max_dates']}")
        logger.info(f"Breakout Drought: {health['breakout_drought_days']} days")

        return {
            'rows_processed': 0,
            'alerts': alerts,
            'health': health
        }
