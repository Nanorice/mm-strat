"""Base Evaluator for Model Evaluation Framework.

Abstract base class providing common interface for all model evaluators.
Supports both regression and classification models with consistent:
- Metrics computation and storage
- Model registry integration
- Report generation
- Artifact management
"""

import json
import logging
import platform
import subprocess
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from ..model_registry import ModelRegistry

logger = logging.getLogger(__name__)


def _safe_git_sha() -> Optional[str]:
    """Return the current HEAD SHA, or None if git is unavailable."""
    try:
        out = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'],
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
        return out.decode('ascii', errors='ignore').strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None


class BaseEvaluator(ABC):
    """Abstract base class for all model evaluators.

    Provides common infrastructure for:
    - Output directory management
    - Model registry integration
    - Metrics serialization
    - Report generation

    Subclasses must implement:
    - evaluate(): Core evaluation logic
    - generate_report(): Model-specific markdown report
    """

    def __init__(
        self,
        model_name: str,
        model_version: str,
        output_dir: Path,
        db_path: Optional[Path] = None
    ):
        """Initialize base evaluator.

        Args:
            model_name: Model identifier (e.g., 'M01', 'M04')
            model_version: Version string (e.g., 'baseline', 'v1.2')
            output_dir: Base directory for outputs (will create subdirs)
            db_path: Path to DuckDB database for model registry
        """
        self.model_name = model_name
        self.model_version = model_version

        # Create versioned output directory
        self.output_dir = Path(output_dir) / model_name / model_version
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Evaluation subdirectory
        self.eval_dir = self.output_dir / "evaluation"
        self.eval_dir.mkdir(exist_ok=True)

        # Model registry connection
        self.registry = ModelRegistry(db_path=db_path)

        # Metrics storage
        self.metrics: Dict[str, Any] = {}
        self.plots: Dict[str, Path] = {}

        # Reproducibility context. Subclasses or callers may set these before
        # invoking save_results(); _save_metrics_json reads them into the
        # evaluator_run metadata block.
        self.label_registry_id: Optional[str] = None
        self.feature_set_id: Optional[str] = None
        self.pipeline_run_id: Optional[int] = None
        self.db_path = db_path

        logger.info(f"✅ Initialized {self.__class__.__name__} for {model_name}/{model_version}")
        logger.info(f"📁 Output directory: {self.output_dir}")

    @abstractmethod
    def evaluate(self, **kwargs) -> Dict[str, Any]:
        """Execute model evaluation.

        Core evaluation logic - must be implemented by subclasses.

        Returns:
            Dictionary with evaluation metrics
        """
        pass

    @abstractmethod
    def generate_report(self, metrics: Dict[str, Any], plots: Dict[str, Path]) -> Path:
        """Generate markdown scorecard report.

        Args:
            metrics: Evaluation metrics dictionary
            plots: Dictionary mapping plot names to file paths

        Returns:
            Path to generated report
        """
        pass

    def save_results(
        self,
        metrics: Dict[str, Any],
        plots: Dict[str, Path],
        update_registry: bool = True
    ) -> Path:
        """Save evaluation results to disk and optionally update model registry.

        Performs:
        1. Save metrics to JSON
        2. Generate markdown report
        3. Update model registry (if enabled)

        Args:
            metrics: Evaluation metrics
            plots: Plot file paths
            update_registry: Whether to update DuckDB registry

        Returns:
            Path to metrics JSON file
        """
        # Save metrics JSON
        metrics_path = self.eval_dir / "results.json"
        self._save_metrics_json(metrics, metrics_path)

        # Generate report
        report_path = self.generate_report(metrics, plots)

        # Update registry
        if update_registry:
            self._update_registry(metrics, report_path)

        logger.info(f"✅ Evaluation complete: {self.eval_dir}")
        return metrics_path

    def _save_metrics_json(self, metrics: Dict[str, Any], path: Path) -> None:
        """Serialize metrics to JSON with type handling."""

        def convert_types(obj):
            """Convert numpy/pandas types to JSON-serializable types."""
            if isinstance(obj, (pd.Series, pd.DataFrame)):
                return obj.to_dict()
            elif isinstance(obj, (pd.Timestamp, datetime)):
                return obj.isoformat()
            elif hasattr(obj, 'tolist'):  # numpy arrays
                return obj.tolist()
            elif hasattr(obj, 'item'):  # numpy scalars
                return obj.item()
            return obj

        # Convert all values
        serializable = {k: convert_types(v) for k, v in metrics.items()}

        # Add metadata
        serializable['_metadata'] = {
            'model_name': self.model_name,
            'model_version': self.model_version,
            'evaluation_timestamp': datetime.now().isoformat(),
            'evaluator_class': self.__class__.__name__,
            'evaluator_run': self._build_evaluator_run_metadata(),
        }

        with open(path, 'w') as f:
            json.dump(serializable, f, indent=2, default=str)

        logger.info(f"💾 Metrics saved: {path}")

    def _update_registry(self, metrics: Dict[str, Any], report_path: Path) -> None:
        """Update model registry with evaluation results.

        Note: Registry expects regression metrics by default.
        Subclasses should override to provide model-specific metrics.
        """
        logger.info(f"📝 Updating model registry for {self.model_version}")
        # Default implementation - subclasses should override
        pass

    def add_plot(self, plot_name: str, plot_path: Path) -> None:
        """Register a plot file for inclusion in report.

        Args:
            plot_name: Identifier for the plot (e.g., 'confusion_matrix')
            plot_path: Path to saved plot file
        """
        self.plots[plot_name] = plot_path
        logger.debug(f"📊 Registered plot: {plot_name} -> {plot_path}")

    def _build_evaluator_run_metadata(self) -> Dict[str, Any]:
        """Build the evaluator_run reproducibility block.

        Captures git SHA, python version, and identifiers needed to reconstruct
        which labels/features/pipeline-run were used. Any field that can't be
        resolved degrades to None rather than failing the evaluation.
        """
        return {
            'git_sha': _safe_git_sha(),
            'python_version': platform.python_version(),
            'platform': platform.platform(),
            'label_registry_id': self.label_registry_id,
            'feature_set_id': self.feature_set_id,
            'pipeline_run_id': self._resolve_pipeline_run_id(),
        }

    def _resolve_pipeline_run_id(self) -> Optional[int]:
        """Return self.pipeline_run_id if set, else latest completed run from DB."""
        if self.pipeline_run_id is not None:
            return self.pipeline_run_id
        if self.db_path is None:
            return None
        try:
            from src import db
            con = db.connect(str(self.db_path), read_only=True)
            try:
                row = con.execute(
                    "SELECT MAX(run_id) FROM pipeline_runs WHERE status = 'COMPLETED'"
                ).fetchone()
                return int(row[0]) if row and row[0] is not None else None
            finally:
                con.close()
        except Exception as e:  # pragma: no cover — best-effort
            logger.debug(f"pipeline_run_id lookup skipped: {e}")
            return None

    def get_output_path(self, filename: str, subdir: Optional[str] = None) -> Path:
        """Get path for output file in evaluation directory.

        Args:
            filename: Name of file to create
            subdir: Optional subdirectory within evaluation dir

        Returns:
            Full path to output file
        """
        if subdir:
            target_dir = self.eval_dir / subdir
            target_dir.mkdir(exist_ok=True)
            return target_dir / filename
        return self.eval_dir / filename
