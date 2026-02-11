"""
M01 Automated Workflow
======================

End-to-end orchestrator for M01 model development:
    Load Data -> Auto-EDA -> Feature Selection -> Train -> Report

This "factory" removes manual friction when testing new features,
enabling rapid iteration without redoing EDA/selection/reporting manually.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from src.feature_config import M01_FEATURES, get_model_features, FEATURE_AUTO_EXCLUDE, M03_FEATURES
from src.evaluation.feature_screener import FeatureScreener
from .data_pipeline import DataPipeline
from .m01_trainer import M01Trainer

logger = logging.getLogger(__name__)


@dataclass
class WorkflowConfig:
    """Configuration for automated M01 workflow."""

    # Data parameters
    start_date: str = '2018-01-01'
    end_date: str = '2023-12-31'
    success_threshold: float = 15.0

    # Feature screening
    candidate_features: List[str] = field(default_factory=list)
    ks_threshold: float = 0.15
    correlation_threshold: float = 0.7
    auto_select: bool = True
    fast_eda: bool = False  # If True, use KS-only pipeline instead of full 4-pillar
    exclude_m03: bool = False  # If True, exclude M03 regime features from selection
    enrich_mfe: bool = False  # If True, add MFE/MAE from D2R to D2 for EDA
    eda_target: str = 'return_pct'  # Target for EDA: 'return_pct' or 'y_max'

    # Training parameters
    target_type: str = 'log_space'
    tune: bool = False
    n_jobs: int = -1

    # Output
    generate_report: bool = True
    output_dir: str = 'models'
    save_model: bool = False  # NEVER auto-save; user must explicitly approve

    def __post_init__(self):
        # Leave candidate_features empty to auto-discover from d2_features
        # FeatureScreener.pre_filter_features() will use all numeric columns
        pass


class M01Workflow:
    """
    End-to-end automated M01 training workflow.

    Orchestrates: Load -> EDA -> Select -> Train -> Report

    Example:
        config = WorkflowConfig(start_date='2020-01-01', tune=True)
        workflow = M01Workflow(config)
        results = workflow.run()
    """

    VALID_STEPS = ['load', 'eda', 'select', 'train', 'report']

    def __init__(self, config: WorkflowConfig):
        self.config = config
        self.pipeline = DataPipeline()
        self.trainer = M01Trainer()

        # State
        self.data: Optional[pd.DataFrame] = None
        self.eda_results: Optional[Dict] = None
        self.selected_features: List[str] = []
        self.model = None
        self.metrics_df: Optional[pd.DataFrame] = None

    def run(self, steps: List[str] = None) -> Dict:
        """
        Execute the workflow.

        Args:
            steps: Steps to run. Default: all steps.
                   Options: 'load', 'eda', 'select', 'train', 'report'

        Returns:
            Dict with results from each step
        """
        steps = steps or self.VALID_STEPS.copy()

        # Validate steps
        invalid = set(steps) - set(self.VALID_STEPS)
        if invalid:
            raise ValueError(f"Invalid steps: {invalid}. Valid: {self.VALID_STEPS}")

        results = {'config': self.config}
        print(self._header())

        # Step 1: Load data
        if 'load' in steps:
            print("\n[1/5] Loading data...")
            self.data = self._load_data()
            results['data_shape'] = self.data.shape
            print(f"      Loaded {len(self.data):,} trades with {self.data.shape[1]} columns")

        # Step 2: Run EDA
        if 'eda' in steps:
            if self.data is None:
                self.data = self.pipeline.load_d2()
            print("\n[2/5] Running Auto-EDA (feature screening)...")
            self.eda_results = self._run_eda()
            results['eda'] = self.eda_results
            n_passed = len(self.eda_results['passed'])
            n_failed = len(self.eda_results['failed'])
            print(f"      Screened {n_passed + n_failed} features: {n_passed} passed, {n_failed} failed")

        # Step 3: Select features
        if 'select' in steps:
            if self.eda_results is None and self.config.auto_select:
                print("\n[3/5] Skipping selection (no EDA results, using all candidates)")
                self.selected_features = self.config.candidate_features.copy()
            else:
                print("\n[3/5] Selecting features...")
                self.selected_features = self._select_features()
            results['selected_features'] = self.selected_features
            print(f"      Selected {len(self.selected_features)} features for training")

        # Step 4: Train model
        if 'train' in steps:
            if self.data is None:
                self.data = self.pipeline.load_d2()
            if not self.selected_features:
                self.selected_features = self.config.candidate_features.copy()
            print(f"\n[4/5] Training M01 model (target={self.config.target_type})...")
            self.model, self.metrics_df = self._train()
            results['metrics'] = self._summarize_metrics()
            print(f"      Training complete. IC: {results['metrics'].get('avg_ic', 0):.3f}")

        # Step 5: Generate report
        if 'report' in steps:
            if self.model is None:
                print("\n[5/5] Skipping report (no model trained)")
            else:
                print("\n[5/5] Generating reports...")
                report_paths = self._generate_reports()
                results['reports'] = report_paths
                for name, path in report_paths.items():
                    print(f"      {name}: {path}")

        print(self._footer(results))
        return results

    def _header(self) -> str:
        """Generate workflow header."""
        eda_mode = "KS-Only (fast)" if self.config.fast_eda else "Quant-Standard (4-pillar)"
        lines = [
            "",
            "=" * 70,
            " M01 AUTOMATED WORKFLOW",
            "=" * 70,
            f"   Date Range: {self.config.start_date} to {self.config.end_date}",
            f"   Target: {self.config.target_type}",
            f"   EDA Mode: {eda_mode}",
            f"   EDA Target: {self.config.eda_target}",
            f"   KS Threshold: {self.config.ks_threshold}",
            f"   Candidates: {len(self.config.candidate_features) if self.config.candidate_features else 'all numeric'} features",
            f"   MFE Enrichment: {'ENABLED (from D2R)' if self.config.enrich_mfe else 'disabled'}",
            f"   Tuning: {'ENABLED' if self.config.tune else 'disabled'}",
            "=" * 70,
        ]
        return '\n'.join(lines)

    def _footer(self, results: Dict) -> str:
        """Generate workflow footer."""
        lines = [
            "",
            "=" * 70,
            " WORKFLOW COMPLETE",
            "=" * 70,
        ]
        if 'metrics' in results:
            m = results['metrics']
            lines.append(f"   IC: {m.get('avg_ic', 0):.3f} | Edge: {m.get('avg_selection_edge', 0):+.2f}%")
        if 'selected_features' in results:
            lines.append(f"   Features: {len(results['selected_features'])} selected")
        if 'reports' in results:
            lines.append(f"   Reports: {len(results['reports'])} generated")

        # Remind user about next steps
        if not self.config.save_model:
            lines.append("")
            lines.append("   [!] Model NOT saved. Review models/eda_report.md for next steps.")
        lines.append("=" * 70)
        return '\n'.join(lines)

    def _load_data(self) -> pd.DataFrame:
        """Load D2 features dataset."""
        try:
            d2 = self.pipeline.load_d2()
            logger.info(f"Loaded existing D2: {len(d2)} rows")
        except FileNotFoundError:
            logger.info("D2 not found, generating from scratch...")
            d1 = self.pipeline.scan(
                self.config.start_date,
                self.config.end_date,
                threshold=self.config.success_threshold
            )
            d2 = self.pipeline.features(d1, n_jobs=self.config.n_jobs)
        
        # Enrich with MFE from D2R if requested
        if self.config.enrich_mfe:
            d2 = self._enrich_with_mfe(d2)
        
        return d2
    
    def _enrich_with_mfe(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Enrich D2 with MFE/MAE from D2R.
        
        Adds columns: y_max (MFE), MAE, regret
        """
        from pathlib import Path
        
        # Find D2R file
        d2r_paths = [
            Path('data/pipeline/d2r_sepa.parquet'),
            Path('data/ml/d2r_sepa.parquet'),
            Path('data/pipeline/d2r_120d.parquet'),
            Path('data/ml/d2r_120d.parquet'),
        ]
        
        d2r_path = None
        for path in d2r_paths:
            if path.exists():
                d2r_path = path
                break
        
        if d2r_path is None:
            logger.warning("D2R not found. Run 'python model_runner.py data --steps hydrate' first.")
            logger.warning("Skipping MFE enrichment.")
            return data
        
        logger.info(f"Enriching D2 with MFE from {d2r_path}...")
        
        # Use M01Trainer's method
        data_enriched = self.trainer.enrich_with_survivor_labels(
            data,
            d2r_path=str(d2r_path),
            stop_multiplier=2.0
        )
        
        # Count how many got MFE
        mfe_count = data_enriched['MFE'].notna().sum()
        logger.info(f"   Added MFE to {mfe_count:,} / {len(data_enriched):,} trades")
        
        if 'MFE' in data_enriched.columns:
            avg_mfe = data_enriched['MFE'].mean()
            avg_mae = data_enriched['MAE'].mean() if 'MAE' in data_enriched.columns else 0
            logger.info(f"   Avg MFE: {avg_mfe:+.1f}%, Avg MAE: {avg_mae:+.1f}%")
        
        return data_enriched

    def _run_eda(self) -> Dict:
        """Run feature discrimination screening (quant-standard by default)."""
        # Pass None if no explicit candidates -> FeatureScreener auto-discovers all numeric cols
        candidates = self.config.candidate_features if self.config.candidate_features else None
        
        # Determine EDA target column
        eda_target = self.config.eda_target
        if eda_target == 'y_max' and 'y_max' not in self.data.columns:
            logger.warning("y_max not in dataset. Did you forget --enrich-mfe? Falling back to return_pct")
            eda_target = 'return_pct'
        
        logger.info(f"Running EDA with target: {eda_target}")

        # Apply automatic exclusions (benchmark RS, stale features)
        exclusions = set(FEATURE_AUTO_EXCLUDE)
        if self.config.exclude_m03:
            exclusions.update(M03_FEATURES)
            logger.info(f"Excluding M03 features: {M03_FEATURES}")

        # Filter candidates if provided, otherwise FeatureScreener will filter during discovery
        if candidates:
            candidates = [c for c in candidates if c not in exclusions]
            logger.info(f"After exclusions: {len(candidates)} candidate features")

        if self.config.fast_eda:
            # Fast mode: KS-only pipeline
            results = FeatureScreener.run_pipeline(
                df=self.data,
                candidate_features=candidates,
                target_col=eda_target,
                ks_threshold=self.config.ks_threshold,
                correlation_threshold=self.config.correlation_threshold
            )
            # Map to common format
            results['failed'] = results.get('failed_ks', [])
        else:
            # Full quant-standard 4-pillar pipeline
            results = FeatureScreener.run_quant_pipeline(
                df=self.data,
                candidate_features=candidates,
                target_col=eda_target,
                date_col='entry_date',
                ks_threshold=self.config.ks_threshold,
                correlation_threshold=self.config.correlation_threshold
            )
            # Map to common format for downstream compatibility
            results['failed'] = results.get('failed_composite', [])

        # Generate EDA outputs (both markdown and JSON for dashboard)
        if self.config.generate_report:
            output_paths = FeatureScreener.generate_all_outputs(
                screening_results=results,
                output_dir=Path(self.config.output_dir),
                target_col=eda_target,
                ks_threshold=self.config.ks_threshold,
                correlation_threshold=self.config.correlation_threshold
            )
            logger.info(f"Generated EDA outputs: {output_paths}")

        return results

    def _select_features(self) -> List[str]:
        """Select features based on EDA or explicit list."""
        if not self.config.auto_select:
            # Use all candidates without filtering
            return self.config.candidate_features.copy()

        if self.eda_results and self.eda_results['passed']:
            # Use features that passed KS screening
            return self.eda_results['passed']

        # Fallback to candidates
        logger.warning("No features passed screening, using all candidates")
        return self.config.candidate_features.copy()

    def _train(self) -> Tuple:
        """Train M01 model with selected features (does NOT save by default)."""
        # Override trainer's feature list
        original_features = self.trainer.get_features()

        # Temporarily patch get_features to use selected
        def patched_get_features():
            return self.selected_features

        self.trainer.get_features = patched_get_features

        try:
            model, metrics = self.trainer.train(
                self.data,
                tune=self.config.tune,
                target=self.config.target_type
            )
            # Only save if explicitly requested (default: False)
            if self.config.save_model:
                self.trainer.save(model, metrics)
                logger.info("Model saved to disk")
            else:
                logger.info("Model NOT saved (save_model=False). Review EDA report first.")
            return model, metrics
        finally:
            # Restore original
            self.trainer.get_features = lambda: original_features

    def _summarize_metrics(self) -> Dict:
        """Extract summary metrics from training results."""
        if self.metrics_df is None or self.metrics_df.empty:
            return {}

        return {
            'avg_ic': self.metrics_df['ic'].mean() if 'ic' in self.metrics_df else 0,
            'avg_selection_edge': self.metrics_df['selection_edge'].mean() if 'selection_edge' in self.metrics_df else 0,
            'ic_std': self.metrics_df['ic'].std() if 'ic' in self.metrics_df else 0,
            'n_folds': len(self.metrics_df)
        }

    def _generate_reports(self) -> Dict[str, str]:
        """Generate training reports."""
        reports = {}

        # Model training report
        if self.model is not None and self.config.generate_report:
            report_path = self.trainer.generate_report(
                self.model,
                self.metrics_df,
                start_date=self.config.start_date,
                end_date=self.config.end_date
            )
            reports['training_report'] = report_path

        # EDA report path (already generated in _run_eda)
        eda_path = Path(self.config.output_dir) / 'eda_report.md'
        if eda_path.exists():
            reports['eda_report'] = str(eda_path)

        return reports
