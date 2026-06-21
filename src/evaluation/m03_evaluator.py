"""
M03 Evaluator - Validates M03 Regime Scores Against Ground Truth
=================================================================

Calculates three core metrics:
1. Crash Capture Rate (CCR): % of STRONG_BEAR days correctly flagged
2. False Alarm Rate (FAR): % of STRONG_BULL days incorrectly flagged as bearish
3. Reaction Lag: Days between crash start and first bear signal

Usage:
    evaluator = M03Evaluator()
    results = evaluator.evaluate(start_date='2007-01-01', end_date='2024-12-31')
    evaluator.generate_report()
"""

import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from src.pipeline.m03_regime import M03RegimeCalculator
from src.evaluation.m03_ground_truth import (
    load_ground_truth_df,
    get_strong_bear_periods,
    get_strong_bull_periods,
    CRITICAL_CRASH_PERIODS,
)

logger = logging.getLogger("M03Evaluator")


class M03Evaluator:
    """
    Comprehensive evaluation framework for M03 regime calculator.
    
    Evaluates regime scores using a two-phase approach:
    
    Phase 1: DISCRIMINATION (Threshold-Independent)
    - Can the model separate Bull from Bear?
    - Metrics: ROC-AUC, Cohen's D
    - These must pass BEFORE calibration matters
    
    Phase 2: CALIBRATION (Threshold-Dependent)
    - Where do we draw the threshold lines?
    - Metrics: CCR, FAR, Lag
    - Only meaningful after discrimination is validated
    """
    
    # Thresholds for calibration metrics (Phase 2)
    CCR_SCORE_THRESHOLD = 30  # Score below this = "flagged as crash"
    FAR_SCORE_THRESHOLD = 40  # Score below this during STRONG_BULL = false alarm
    LAG_SCORE_THRESHOLD = 40  # Score below this = "bear signal"
    
    # Target thresholds for passing
    # Phase 1: Discrimination targets
    AUC_TARGET = 0.90       # > 90% AUC for regime separation
    COHENS_D_TARGET = 2.0   # > 2.0 standard deviations apart
    
    # Phase 2: Calibration targets (only matter if Phase 1 passes)
    CCR_TARGET = 0.80  # > 80% crash capture
    FAR_TARGET = 0.05  # < 5% false alarm
    LAG_TARGET = 7     # < 7 days average reaction
    
    def __init__(self, config_path: str = None, output_dir: Path = None):
        """
        Initialize M03 Evaluator.
        
        Args:
            config_path: Path to M03 config file (for testing different configs)
            output_dir: Directory for saving reports
        """
        self.config_path = config_path
        self.calculator = M03RegimeCalculator(config_path)
        self.output_dir = output_dir or Path('models')
        
        # Cached results
        self._scores_df: Optional[pd.DataFrame] = None
        self._ground_truth_df: Optional[pd.DataFrame] = None
        self._merged_df: Optional[pd.DataFrame] = None
        self._results: Optional[Dict] = None
    
    def evaluate(
        self,
        start_date: str = '2003-01-01',
        end_date: str = None,
    ) -> Dict:
        """
        Run full evaluation against ground truth.
        
        Args:
            start_date: Evaluation start date (default: 2003 for macro data availability)
            end_date: Evaluation end date (default: today)
        
        Returns:
            Dict with all evaluation metrics and details
        """
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')
        
        logger.info(f"Evaluating M03 from {start_date} to {end_date}")
        
        # 1. Generate M03 scores for full date range
        self._scores_df = self.calculator.calculate_history_vectorized(
            start_date=start_date,
            end_date=end_date,
            freq='D'
        )
        
        # 2. Load ground truth
        self._ground_truth_df = load_ground_truth_df(
            start_date=start_date,
            end_date=end_date
        )
        
        # 3. Merge scores with ground truth
        self._merged_df = self._merge_scores_with_truth()
        
        # ============================================
        # PHASE 1: DISCRIMINATION (Threshold-Independent)
        # ============================================
        discrimination = self._calculate_discrimination_metrics()
        
        # Phase 1 pass/fail
        passed_auc_bear = discrimination['auc_bear'] >= self.AUC_TARGET
        passed_auc_bull = discrimination['auc_bull'] >= self.AUC_TARGET
        passed_cohens_d = discrimination['cohens_d'] >= self.COHENS_D_TARGET
        phase1_pass = passed_auc_bear and passed_cohens_d
        
        # ============================================
        # PHASE 2: CALIBRATION (Threshold-Dependent)
        # ============================================
        ccr_result = self._calculate_crash_capture_rate()
        far_result = self._calculate_false_alarm_rate()
        lag_result = self._calculate_reaction_lag()
        
        # Phase 2 pass/fail
        passed_ccr = ccr_result['rate'] >= self.CCR_TARGET
        passed_far = far_result['rate'] <= self.FAR_TARGET
        passed_lag = lag_result['avg_lag'] <= self.LAG_TARGET
        phase2_pass = passed_ccr and passed_far and passed_lag
        
        # Overall: Phase 1 must pass, Phase 2 is for calibration guidance
        overall_pass = phase1_pass  # Discrimination is the primary gate
        
        self._results = {
            'config_path': self.config_path,
            'date_range': {'start': start_date, 'end': end_date},
            'n_observations': len(self._merged_df),
            
            # Phase 1: Discrimination metrics (PRIMARY)
            'discrimination': discrimination,
            
            # Phase 2: Calibration metrics (SECONDARY)
            'calibration': {
                'crash_capture_rate': ccr_result,
                'false_alarm_rate': far_result,
                'reaction_lag': lag_result,
            },
            
            # Pass/fail summary
            'passed': {
                # Phase 1
                'auc_bear': passed_auc_bear,
                'auc_bull': passed_auc_bull,
                'cohens_d': passed_cohens_d,
                'phase1_discrimination': phase1_pass,
                # Phase 2
                'ccr': passed_ccr,
                'far': passed_far,
                'lag': passed_lag,
                'phase2_calibration': phase2_pass,
                # Overall
                'overall': overall_pass,
            },
            
            # Regime distribution
            'regime_distribution': self._calculate_regime_distribution(),
            
            # Fitness score for grid search
            'fitness': self._calculate_fitness(discrimination, lag_result),
        }
        
        phase1_status = 'PASS' if phase1_pass else 'FAIL'
        logger.info(f"Evaluation complete. Discrimination: {phase1_status} (AUC={discrimination['auc_bear']:.3f}, d={discrimination['cohens_d']:.2f})")
        return self._results
    
    def _calculate_discrimination_metrics(self) -> Dict:
        """
        Calculate threshold-independent discrimination metrics.
        
        Measures how well the score separates regimes WITHOUT 
        relying on any specific threshold value.
        
        Returns:
            Dict with:
            - auc_bear: ROC-AUC for STRONG_BEAR vs REST
            - auc_bull: ROC-AUC for STRONG_BULL vs REST  
            - cohens_d: Effect size between STRONG_BULL and STRONG_BEAR
            - ks_statistic: Kolmogorov-Smirnov separation
        """
        from sklearn.metrics import roc_auc_score
        
        df = self._merged_df
        scores = df['m03_score'].values
        regimes = df['ground_truth_regime'].values
        
        # === ROC-AUC: STRONG_BEAR vs REST ===
        # For bear detection, LOWER scores are better, so we invert
        is_strong_bear = (regimes == 'STRONG_BEAR').astype(int)
        if is_strong_bear.sum() > 0 and is_strong_bear.sum() < len(is_strong_bear):
            # Invert scores since low score = bear (we want AUC where positive class has HIGHER values)
            auc_bear = roc_auc_score(is_strong_bear, -scores)
        else:
            auc_bear = 0.5  # No samples or all same class
        
        # === ROC-AUC: STRONG_BULL vs REST ===
        # For bull detection, HIGHER scores are better (natural direction)
        is_strong_bull = (regimes == 'STRONG_BULL').astype(int)
        if is_strong_bull.sum() > 0 and is_strong_bull.sum() < len(is_strong_bull):
            auc_bull = roc_auc_score(is_strong_bull, scores)
        else:
            auc_bull = 0.5
        
        # === Cohen's D: STRONG_BULL mean vs STRONG_BEAR mean ===
        bear_scores = df[df['ground_truth_regime'] == 'STRONG_BEAR']['m03_score']
        bull_scores = df[df['ground_truth_regime'] == 'STRONG_BULL']['m03_score']
        
        if len(bear_scores) > 1 and len(bull_scores) > 1:
            mean_bear = bear_scores.mean()
            mean_bull = bull_scores.mean()
            
            # Pooled standard deviation
            n_bear, n_bull = len(bear_scores), len(bull_scores)
            var_bear = bear_scores.var()
            var_bull = bull_scores.var()
            pooled_std = np.sqrt(
                ((n_bear - 1) * var_bear + (n_bull - 1) * var_bull) / 
                (n_bear + n_bull - 2)
            )
            
            if pooled_std > 0:
                cohens_d = (mean_bull - mean_bear) / pooled_std
            else:
                cohens_d = 0.0
        else:
            cohens_d = 0.0
            mean_bear = bear_scores.mean() if len(bear_scores) > 0 else 0
            mean_bull = bull_scores.mean() if len(bull_scores) > 0 else 0
        
        # === Kolmogorov-Smirnov Statistic ===
        from scipy import stats
        if len(bear_scores) > 0 and len(bull_scores) > 0:
            ks_stat, ks_pvalue = stats.ks_2samp(bear_scores, bull_scores)
        else:
            ks_stat, ks_pvalue = 0.0, 1.0
        
        return {
            'auc_bear': round(auc_bear, 4),
            'auc_bull': round(auc_bull, 4),
            'cohens_d': round(cohens_d, 2),
            'ks_statistic': round(ks_stat, 4),
            'ks_pvalue': ks_pvalue,
            'mean_strong_bear': round(mean_bear, 1),
            'mean_strong_bull': round(mean_bull, 1),
            'separation_points': round(mean_bull - mean_bear, 1),
            'target_auc': self.AUC_TARGET,
            'target_cohens_d': self.COHENS_D_TARGET,
        }
    
    def _calculate_fitness(self, discrimination: Dict, lag_result: Dict) -> float:
        """
        Calculate fitness score for grid search optimization.
        
        Fitness = (AUC_Bear × 0.6) + (AUC_Bull × 0.4) - Lag_Penalty
        
        Args:
            discrimination: Dict with AUC values
            lag_result: Dict with lag metrics
            
        Returns:
            Fitness score (higher is better)
        """
        auc_bear = discrimination['auc_bear']
        auc_bull = discrimination['auc_bull']
        
        # Lag penalty: penalize slow detection
        avg_lag = lag_result['avg_lag']
        if avg_lag <= self.LAG_TARGET:
            lag_penalty = 0
        else:
            # Penalty grows with lag beyond target
            lag_penalty = 0.01 * (avg_lag - self.LAG_TARGET)
        
        fitness = (auc_bear * 0.6) + (auc_bull * 0.4) - lag_penalty
        return round(fitness, 4)
    
    def _merge_scores_with_truth(self) -> pd.DataFrame:
        """Merge M03 scores with ground truth on date index."""
        scores = self._scores_df[['score', 'category', 'trend_score', 
                                   'liquidity_score', 'risk_appetite_score']].copy()
        scores.columns = ['m03_score', 'm03_category', 'trend_score',
                          'liquidity_score', 'risk_appetite_score']
        
        truth = self._ground_truth_df[['ground_truth_regime']].copy()
        
        # Join on date index
        merged = scores.join(truth, how='inner')
        
        logger.info(f"Merged {len(merged)} observations with ground truth")
        return merged
    
    def _calculate_crash_capture_rate(self) -> Dict:
        """
        Calculate Crash Capture Rate (CCR).
        
        CCR = Days(Score < 30 AND Truth = STRONG_BEAR) / Total Days(STRONG_BEAR)
        
        Target: > 80%
        """
        df = self._merged_df
        
        # Filter to STRONG_BEAR days only
        strong_bear_mask = df['ground_truth_regime'] == 'STRONG_BEAR'
        strong_bear_days = df[strong_bear_mask]
        
        if len(strong_bear_days) == 0:
            return {'rate': 0.0, 'captured_days': 0, 'total_days': 0, 'missed_days': []}
        
        # Count correctly flagged days (score < threshold)
        captured_mask = strong_bear_days['m03_score'] < self.CCR_SCORE_THRESHOLD
        captured_days = captured_mask.sum()
        total_days = len(strong_bear_days)
        
        # Identify missed days for debugging
        missed_days = strong_bear_days[~captured_mask].head(10).to_dict('records')
        
        rate = captured_days / total_days
        
        return {
            'rate': round(rate, 4),
            'captured_days': int(captured_days),
            'total_days': int(total_days),
            'threshold': self.CCR_SCORE_THRESHOLD,
            'target': self.CCR_TARGET,
            'missed_days_sample': missed_days,
        }
    
    def _calculate_false_alarm_rate(self) -> Dict:
        """
        Calculate False Alarm Rate (FAR).
        
        FAR = Days(Score < 40 AND Truth = STRONG_BULL) / Total Days(STRONG_BULL)
        
        Target: < 5%
        """
        df = self._merged_df
        
        # Filter to STRONG_BULL days only
        strong_bull_mask = df['ground_truth_regime'] == 'STRONG_BULL'
        strong_bull_days = df[strong_bull_mask]
        
        if len(strong_bull_days) == 0:
            return {'rate': 0.0, 'false_alarm_days': 0, 'total_days': 0}
        
        # Count false alarm days (score below threshold during bull)
        false_alarm_mask = strong_bull_days['m03_score'] < self.FAR_SCORE_THRESHOLD
        false_alarm_days = false_alarm_mask.sum()
        total_days = len(strong_bull_days)
        
        # Identify false alarm days for debugging
        fa_days = strong_bull_days[false_alarm_mask].head(10).to_dict('records')
        
        rate = false_alarm_days / total_days
        
        return {
            'rate': round(rate, 4),
            'false_alarm_days': int(false_alarm_days),
            'total_days': int(total_days),
            'threshold': self.FAR_SCORE_THRESHOLD,
            'target': self.FAR_TARGET,
            'false_alarm_sample': fa_days,
        }
    
    def _calculate_reaction_lag(self) -> Dict:
        """
        Calculate Reaction Lag for each crash period.
        
        Lag = Days between crash start date and first day with Score < 40
        
        Target: < 7 days average
        """
        df = self._merged_df
        bear_periods = get_strong_bear_periods()
        
        lag_details = []
        
        for period in bear_periods:
            start = pd.to_datetime(period['start_date'])
            end = pd.to_datetime(period['end_date'])
            
            # Get scores during this crash period
            period_scores = df[(df.index >= start) & (df.index <= end)]
            
            if len(period_scores) == 0:
                continue
            
            # Find first day with score below threshold
            bear_signal_mask = period_scores['m03_score'] < self.LAG_SCORE_THRESHOLD
            
            if bear_signal_mask.any():
                first_signal_date = period_scores[bear_signal_mask].index[0]
                lag_days = (first_signal_date - start).days
            else:
                # Never detected - worst case
                lag_days = (end - start).days
                first_signal_date = None
            
            # Check if this is a critical crash
            is_critical = any(
                c['start_date'] == period['start_date'] 
                for c in CRITICAL_CRASH_PERIODS
            )
            
            lag_details.append({
                'period_name': period.get('rationale', '')[:50],
                'start_date': period['start_date'],
                'end_date': period['end_date'],
                'lag_days': lag_days,
                'first_signal_date': str(first_signal_date) if first_signal_date else None,
                'is_critical': is_critical,
            })
        
        # Calculate average lag
        lags = [d['lag_days'] for d in lag_details]
        avg_lag = np.mean(lags) if lags else float('inf')
        max_lag = max(lags) if lags else float('inf')
        
        # Critical crash performance
        critical_lags = [d for d in lag_details if d['is_critical']]
        
        return {
            'avg_lag': round(avg_lag, 1),
            'max_lag': int(max_lag),
            'threshold': self.LAG_SCORE_THRESHOLD,
            'target': self.LAG_TARGET,
            'n_periods': len(lag_details),
            'period_details': lag_details,
            'critical_crash_lags': critical_lags,
        }
    
    def _calculate_regime_distribution(self) -> Dict:
        """Calculate distribution of M03 categories vs ground truth."""
        df = self._merged_df
        
        # M03 category distribution
        m03_dist = df['m03_category'].value_counts().to_dict()
        
        # Ground truth distribution
        gt_dist = df['ground_truth_regime'].value_counts().to_dict()
        
        # Score statistics per ground truth regime
        score_by_regime = df.groupby('ground_truth_regime')['m03_score'].agg(
            ['mean', 'std', 'min', 'max']
        ).round(1).to_dict('index')
        
        return {
            'm03_category_counts': m03_dist,
            'ground_truth_counts': gt_dist,
            'score_by_ground_truth': score_by_regime,
        }
    
    def generate_report(self, save: bool = True) -> str:
        """
        Generate markdown evaluation report.
        
        Args:
            save: Whether to save to file
            
        Returns:
            Markdown report string
        """
        if self._results is None:
            raise ValueError("Must call evaluate() before generating report")
        
        r = self._results
        disc = r['discrimination']
        cal = r['calibration']
        ccr = cal['crash_capture_rate']
        far = cal['false_alarm_rate']
        lag = cal['reaction_lag']
        passed = r['passed']
        
        # Header
        lines = [
            "# M03 Regime Evaluation Report",
            "",
            f"**Date Range:** {r['date_range']['start']} to {r['date_range']['end']}",
            f"**Config:** {self.config_path or 'Default'}",
            f"**Observations:** {r['n_observations']:,}",
            f"**Fitness Score:** {r['fitness']:.4f}",
            "",
        ]
        
        # ============================================
        # PHASE 1: DISCRIMINATION (PRIMARY)
        # ============================================
        phase1_verdict = "PASS" if passed['phase1_discrimination'] else "FAIL"
        lines.extend([
            f"## Phase 1: Discrimination [{phase1_verdict}]",
            "",
            "> **Key Question:** Can the model separate Bull from Bear regimes?",
            "> These metrics are threshold-independent.",
            "",
            "| Metric | Value | Target | Status |",
            "|--------|-------|--------|--------|",
            f"| ROC-AUC (Bear vs Rest) | {disc['auc_bear']:.3f} | >= {self.AUC_TARGET:.2f} | {'PASS' if passed['auc_bear'] else 'FAIL'} |",
            f"| ROC-AUC (Bull vs Rest) | {disc['auc_bull']:.3f} | >= {self.AUC_TARGET:.2f} | {'PASS' if passed['auc_bull'] else 'FAIL'} |",
            f"| Cohen's D | {disc['cohens_d']:.2f} | >= {self.COHENS_D_TARGET:.1f} | {'PASS' if passed['cohens_d'] else 'FAIL'} |",
            f"| KS Statistic | {disc['ks_statistic']:.3f} | (informational) | - |",
            "",
            "### Score Separation",
            "",
            f"- **STRONG_BEAR Mean:** {disc['mean_strong_bear']:.1f}",
            f"- **STRONG_BULL Mean:** {disc['mean_strong_bull']:.1f}",
            f"- **Separation:** {disc['separation_points']:.1f} points",
            "",
        ])
        
        # Interpretation
        if passed['phase1_discrimination']:
            lines.extend([
                "> [!TIP]",
                "> **Discrimination PASSED.** The model can separate regimes. Proceed to calibration.",
                "",
            ])
        else:
            lines.extend([
                "> [!WARNING]",
                "> **Discrimination FAILED.** The model cannot reliably separate regimes.",
                "> Calibration thresholds won't help - the signal itself is too weak.",
                "> Consider: adjusting pillar weights, adding features, or changing the scoring formula.",
                "",
            ])
        
        # ============================================
        # PHASE 2: CALIBRATION (SECONDARY)
        # ============================================
        phase2_verdict = "PASS" if passed['phase2_calibration'] else "NEEDS TUNING"
        lines.extend([
            f"## Phase 2: Calibration [{phase2_verdict}]",
            "",
            "> **Key Question:** Where should we set the threshold lines?",
            "> These metrics depend on threshold configuration.",
            "",
            "| Metric | Value | Target | Status |",
            "|--------|-------|--------|--------|",
            f"| Crash Capture Rate | {ccr['rate']:.1%} | >= {self.CCR_TARGET:.0%} | {'PASS' if passed['ccr'] else 'FAIL'} |",
            f"| False Alarm Rate | {far['rate']:.1%} | <= {self.FAR_TARGET:.0%} | {'PASS' if passed['far'] else 'FAIL'} |",
            f"| Avg Reaction Lag | {lag['avg_lag']:.1f} days | <= {self.LAG_TARGET} days | {'PASS' if passed['lag'] else 'FAIL'} |",
            "",
        ])
        
        if not passed['phase2_calibration'] and passed['phase1_discrimination']:
            lines.extend([
                "> [!NOTE]",
                "> **Calibration thresholds need adjustment.** Since discrimination passed,",
                f"> try adjusting CCR_SCORE_THRESHOLD (currently {self.CCR_SCORE_THRESHOLD}) based on the score distribution.",
                "",
            ])
        
        # Reaction Lag details
        lines.extend([
            "### Reaction Lag Details",
            "",
            "| Crash | Start Date | Lag (Days) | Status |",
            "|-------|------------|------------|--------|",
        ])
        
        for crash in lag['critical_crash_lags']:
            status = "PASS" if crash['lag_days'] <= self.LAG_TARGET else "FAIL"
            lines.append(
                f"| {crash['period_name'][:30]} | {crash['start_date']} | {crash['lag_days']} | {status} |"
            )
        
        lines.extend([
            "",
            "### All STRONG_BEAR Periods",
            "",
            "| Period | Start | Lag (Days) |",
            "|--------|-------|------------|",
        ])
        
        for period in lag['period_details']:
            lines.append(
                f"| {period['period_name'][:40]} | {period['start_date']} | {period['lag_days']} |"
            )
        
        # Score distribution
        lines.extend([
            "",
            "## Score Distribution by Ground Truth Regime",
            "",
            "| Regime | Mean Score | Std Dev | Min | Max |",
            "|--------|------------|---------|-----|-----|",
        ])
        
        dist = r['regime_distribution']['score_by_ground_truth']
        for regime in ['STRONG_BEAR', 'BEAR', 'NEUTRAL', 'BULL', 'STRONG_BULL']:
            if regime in dist:
                stats = dist[regime]
                lines.append(
                    f"| {regime} | {stats['mean']:.1f} | {stats['std']:.1f} | {stats['min']:.0f} | {stats['max']:.0f} |"
                )
        
        lines.append("")
        
        report = "\n".join(lines)
        
        if save:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            report_path = self.output_dir / f"m03_evaluation_{timestamp}.md"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report, encoding='utf-8')
            logger.info(f"Saved evaluation report to {report_path}")
        
        return report
    
    def get_merged_df(self) -> pd.DataFrame:
        """Return merged scores + ground truth DataFrame for analysis."""
        if self._merged_df is None:
            raise ValueError("Must call evaluate() first")
        return self._merged_df.copy()
    
    def calibrate_thresholds(
        self,
        ccr_target: float = 0.80,
        far_target: float = 0.05,
        save_config: bool = False,
    ) -> Dict:
        """
        Calculate optimal thresholds from actual score distributions.
        
        Uses percentile-based approach:
        - CCR threshold: Set at (1 - ccr_target) percentile of STRONG_BEAR scores
          e.g., 80% CCR → 20th percentile of bear scores → captures 80% of bear days
        - FAR threshold: Set at far_target percentile of STRONG_BULL scores
          e.g., 5% FAR → 5th percentile of bull scores → only 5% false alarms
        
        Args:
            ccr_target: Target crash capture rate (default: 0.80)
            far_target: Target false alarm rate (default: 0.05)
            save_config: If True, update m03_config.json with new thresholds
            
        Returns:
            Dict with calibration results and recommendations
        """
        if self._merged_df is None:
            raise ValueError("Must call evaluate() first")
        
        df = self._merged_df
        
        # Get score distributions by regime
        bear_scores = df[df['ground_truth_regime'] == 'STRONG_BEAR']['m03_score']
        bull_scores = df[df['ground_truth_regime'] == 'STRONG_BULL']['m03_score']
        
        if len(bear_scores) == 0 or len(bull_scores) == 0:
            logger.warning("Insufficient data for calibration")
            return {'error': 'Insufficient regime data'}
        
        # ============================================
        # Calculate CCR Threshold
        # ============================================
        # To achieve 80% CCR, we need 80% of STRONG_BEAR scores to be BELOW threshold
        # So threshold = 80th percentile of bear scores
        ccr_percentile = ccr_target * 100  # e.g., 80
        optimal_ccr_threshold = np.percentile(bear_scores, ccr_percentile)
        
        # Verify: what CCR would we get with this threshold?
        expected_ccr = (bear_scores < optimal_ccr_threshold).mean()
        
        # ============================================
        # Calculate FAR Threshold  
        # ============================================
        # To achieve 5% FAR, we need only 5% of STRONG_BULL scores to be BELOW threshold
        # So threshold = 5th percentile of bull scores
        far_percentile = far_target * 100  # e.g., 5
        optimal_far_threshold = np.percentile(bull_scores, far_percentile)
        
        # Verify: what FAR would we get with this threshold?
        expected_far = (bull_scores < optimal_far_threshold).mean()
        
        # ============================================
        # Reconcile the two thresholds
        # ============================================
        # The CCR threshold should be HIGHER (more permissive for bear detection)
        # The FAR threshold should be LOWER (stricter to avoid false alarms)
        # 
        # For the LAG threshold (reaction speed), we use the CCR threshold
        # since fast detection is critical during crashes
        
        # Use FAR threshold for False Alarm Rate checks
        # Use CCR threshold for Crash Capture Rate checks
        # For LAG (reaction time), use the FAR threshold as it's typically lower
        
        # Simple approach: report both, let config use appropriate ones
        recommended_ccr_threshold = round(optimal_ccr_threshold, 0)
        recommended_far_threshold = round(optimal_far_threshold, 0)
        recommended_lag_threshold = round(optimal_far_threshold, 0)  # Use FAR for speed
        
        # What happens if we use a single unified threshold?
        # Test mid-point
        unified_threshold = round((optimal_ccr_threshold + optimal_far_threshold) / 2, 0)
        unified_ccr = (bear_scores < unified_threshold).mean()
        unified_far = (bull_scores < unified_threshold).mean()
        
        calibration_result = {
            'targets': {
                'ccr_target': ccr_target,
                'far_target': far_target,
            },
            'current_thresholds': {
                'ccr': self.CCR_SCORE_THRESHOLD,
                'far': self.FAR_SCORE_THRESHOLD,
                'lag': self.LAG_SCORE_THRESHOLD,
            },
            'optimal_thresholds': {
                'ccr': int(recommended_ccr_threshold),
                'far': int(recommended_far_threshold),
                'lag': int(recommended_lag_threshold),
            },
            'expected_metrics': {
                'ccr_with_optimal': round(expected_ccr, 4),
                'far_with_optimal': round(expected_far, 4),
            },
            'unified_threshold_analysis': {
                'threshold': int(unified_threshold),
                'ccr': round(unified_ccr, 4),
                'far': round(unified_far, 4),
            },
            'distributions': {
                'bear': {
                    'count': len(bear_scores),
                    'mean': round(bear_scores.mean(), 1),
                    'std': round(bear_scores.std(), 1),
                    'min': int(bear_scores.min()),
                    'max': int(bear_scores.max()),
                    'p20': round(np.percentile(bear_scores, 20), 1),
                    'p50': round(np.percentile(bear_scores, 50), 1),
                    'p80': round(np.percentile(bear_scores, 80), 1),
                },
                'bull': {
                    'count': len(bull_scores),
                    'mean': round(bull_scores.mean(), 1),
                    'std': round(bull_scores.std(), 1),
                    'min': int(bull_scores.min()),
                    'max': int(bull_scores.max()),
                    'p5': round(np.percentile(bull_scores, 5), 1),
                    'p20': round(np.percentile(bull_scores, 20), 1),
                    'p50': round(np.percentile(bull_scores, 50), 1),
                },
            },
        }
        
        # Optionally save to config
        if save_config:
            config_path = Path('models/m03_config.json')
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config = json.load(f)
                
                config['thresholds']['calibration'] = {
                    'ccr_score_threshold': int(recommended_ccr_threshold),
                    'far_score_threshold': int(recommended_far_threshold),
                    'lag_score_threshold': int(recommended_lag_threshold),
                    'calibrated_on': datetime.now().strftime('%Y-%m-%d'),
                    'ccr_target': ccr_target,
                    'far_target': far_target,
                }
                
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=2)
                
                logger.info(f"Saved calibrated thresholds to {config_path}")
                calibration_result['config_updated'] = str(config_path)
        
        return calibration_result
    
    def generate_calibration_report(self, calibration: Dict = None) -> str:
        """
        Generate markdown report for threshold calibration.
        
        Args:
            calibration: Result from calibrate_thresholds() (optional, will run if needed)
            
        Returns:
            Markdown report string
        """
        if calibration is None:
            calibration = self.calibrate_thresholds()
        
        c = calibration
        current = c['current_thresholds']
        optimal = c['optimal_thresholds']
        expected = c['expected_metrics']
        unified = c['unified_threshold_analysis']
        bear = c['distributions']['bear']
        bull = c['distributions']['bull']
        
        lines = [
            "# M03 Threshold Calibration Report",
            "",
            f"**Target CCR:** {c['targets']['ccr_target']:.0%}",
            f"**Target FAR:** {c['targets']['far_target']:.0%}",
            "",
            "## Recommended Thresholds",
            "",
            "| Threshold | Current | Optimal | Delta |",
            "|-----------|---------|---------|-------|",
            f"| CCR (Crash Capture) | {current['ccr']} | **{optimal['ccr']}** | {optimal['ccr'] - current['ccr']:+d} |",
            f"| FAR (False Alarm) | {current['far']} | **{optimal['far']}** | {optimal['far'] - current['far']:+d} |",
            f"| LAG (Reaction Speed) | {current['lag']} | **{optimal['lag']}** | {optimal['lag'] - current['lag']:+d} |",
            "",
            "## Expected Metrics with Optimal Thresholds",
            "",
            f"- **CCR:** {expected['ccr_with_optimal']:.1%} (target: ≥{c['targets']['ccr_target']:.0%})",
            f"- **FAR:** {expected['far_with_optimal']:.1%} (target: ≤{c['targets']['far_target']:.0%})",
            "",
            "## Score Distributions",
            "",
            "### STRONG_BEAR Scores",
            f"- **N:** {bear['count']} days",
            f"- **Mean:** {bear['mean']} | **Std:** {bear['std']}",
            f"- **Range:** [{bear['min']}, {bear['max']}]",
            f"- **Percentiles:** P20={bear['p20']}, P50={bear['p50']}, P80={bear['p80']}",
            "",
            "### STRONG_BULL Scores",
            f"- **N:** {bull['count']} days",
            f"- **Mean:** {bull['mean']} | **Std:** {bull['std']}",
            f"- **Range:** [{bull['min']}, {bull['max']}]",
            f"- **Percentiles:** P5={bull['p5']}, P20={bull['p20']}, P50={bull['p50']}",
            "",
            "## Unified Threshold Analysis",
            "",
            f"If using a single threshold of **{unified['threshold']}**:",
            f"- CCR: {unified['ccr']:.1%}",
            f"- FAR: {unified['far']:.1%}",
            "",
        ]
        
        return "\n".join(lines)
    
    def reset(self):
        """Reset evaluator state."""
        self._scores_df = None
        self._ground_truth_df = None
        self._merged_df = None
        self._results = None
