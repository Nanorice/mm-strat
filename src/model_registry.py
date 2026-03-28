"""Model Registry for MLOps metadata and versioning.

Provides CRUD operations for the `models` table in DuckDB:
- Register new model versions with specs and metrics
- Update evaluation metrics
- Promote models to production
- Query model history and artifacts
"""

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("data/market_data.duckdb")
ARTIFACTS_BASE = Path("models/artifacts")


class ModelRegistry:
    """Manages model versions, specs, and evaluation artifacts in DuckDB."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = str(db_path or DEFAULT_DB_PATH)
        ARTIFACTS_BASE.mkdir(parents=True, exist_ok=True)

    def register_version(
        self,
        version_id: str,
        specs: Dict[str, Any],
        status: str = "test",
        feature_version: str = "v3.0",
        training_date: Optional[date] = None,
        dataset_rows: Optional[int] = None,
    ) -> None:
        """Register a new model version.

        Args:
            version_id: Unique identifier (e.g., 'M01_v4')
            specs: Dictionary containing:
                - features: List[str] - Feature names
                - hyperparameters: Dict - XGBoost params, etc.
                - training_config: Dict - Train/test split, cv folds, etc.
            status: 'test' | 'prod' | 'archived'
            feature_version: Feature schema version (e.g., 'v3.0')
            training_date: Date of training (defaults to today)
            dataset_rows: Number of rows in training set
        """
        if status not in ("test", "prod", "archived"):
            raise ValueError(f"Invalid status: {status}. Must be test/prod/archived")

        artifacts_path = str(ARTIFACTS_BASE / version_id)
        Path(artifacts_path).mkdir(parents=True, exist_ok=True)

        training_date = training_date or date.today()
        specs_json = json.dumps(specs)

        con = duckdb.connect(self.db_path)
        try:
            con.execute(
                """
                INSERT INTO models (
                    version_id, status_flag, specs_json, feature_version,
                    training_date, dataset_rows, artifacts_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    version_id,
                    status,
                    specs_json,
                    feature_version,
                    training_date,
                    dataset_rows,
                    artifacts_path,
                ],
            )
            logger.info(f"[OK] Registered {version_id} (status={status})")
            print(f"[OK] Registered {version_id} -> {artifacts_path}")
        except Exception as e:
            logger.error(f"Failed to register {version_id}: {e}")
            raise
        finally:
            con.close()

    def get_model_specs(self, version_id: str) -> Dict[str, Any]:
        """Load model specs for a given version.

        Returns:
            Dictionary with keys: features, hyperparameters, training_config
        """
        con = duckdb.connect(self.db_path)
        try:
            result = con.execute(
                "SELECT specs_json FROM models WHERE version_id = ?", [version_id]
            ).fetchone()
            if not result:
                raise ValueError(f"Model version not found: {version_id}")
            return json.loads(result[0])
        finally:
            con.close()

    def update_metrics(
        self,
        version_id: str,
        rmse: Optional[float] = None,
        mae: Optional[float] = None,
        r2: Optional[float] = None,
        spearman_corr: Optional[float] = None,
    ) -> None:
        """Update evaluation metrics for a model version."""
        updates = []
        params = []

        if rmse is not None:
            updates.append("rmse = ?")
            params.append(rmse)
        if mae is not None:
            updates.append("mae = ?")
            params.append(mae)
        if r2 is not None:
            updates.append("r2 = ?")
            params.append(r2)
        if spearman_corr is not None:
            updates.append("spearman_corr = ?")
            params.append(spearman_corr)

        if not updates:
            logger.warning("No metrics provided for update")
            return

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(version_id)

        sql = f"UPDATE models SET {', '.join(updates)} WHERE version_id = ?"

        con = duckdb.connect(self.db_path)
        try:
            con.execute(sql, params)
            logger.info(f"[OK] Updated metrics for {version_id}")
            print(f"[OK] Updated metrics for {version_id}")
        finally:
            con.close()

    def set_prod(self, version_id: str) -> None:
        """Promote a model to production status.

        Sets status_flag='prod' for the specified version and
        demotes all other versions to 'archived'.
        """
        con = duckdb.connect(self.db_path)
        try:
            # Verify version exists
            exists = con.execute(
                "SELECT COUNT(*) FROM models WHERE version_id = ?", [version_id]
            ).fetchone()[0]
            if not exists:
                raise ValueError(f"Model version not found: {version_id}")

            # Demote all current prod models to archived
            con.execute(
                "UPDATE models SET status_flag = 'archived' WHERE status_flag = 'prod'"
            )

            # Promote target version to prod
            con.execute(
                "UPDATE models SET status_flag = 'prod', updated_at = CURRENT_TIMESTAMP WHERE version_id = ?",
                [version_id],
            )
            logger.info(f"[OK] Promoted {version_id} to production")
            print(f"[OK] {version_id} is now PRODUCTION")
        finally:
            con.close()

    def list_versions(
        self, status: Optional[str] = None, limit: int = 20
    ) -> pd.DataFrame:
        """List registered model versions.

        Args:
            status: Filter by 'prod' | 'test' | 'archived' (None = all)
            limit: Maximum number of rows to return

        Returns:
            DataFrame with columns: version_id, status_flag, training_date,
                                    rmse, mae, r2, spearman_corr, created_at
        """
        con = duckdb.connect(self.db_path)
        try:
            if status:
                sql = """
                    SELECT version_id, status_flag, feature_version, training_date,
                           dataset_rows, rmse, mae, r2, spearman_corr, created_at
                    FROM models
                    WHERE status_flag = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """
                df = con.execute(sql, [status, limit]).fetchdf()
            else:
                sql = """
                    SELECT version_id, status_flag, feature_version, training_date,
                           dataset_rows, rmse, mae, r2, spearman_corr, created_at
                    FROM models
                    ORDER BY created_at DESC
                    LIMIT ?
                """
                df = con.execute(sql, [limit]).fetchdf()
            return df
        finally:
            con.close()

    def get_prod_version(self) -> Optional[str]:
        """Get the current production model version ID."""
        con = duckdb.connect(self.db_path)
        try:
            result = con.execute(
                "SELECT version_id FROM models WHERE status_flag = 'prod' LIMIT 1"
            ).fetchone()
            return result[0] if result else None
        finally:
            con.close()

    def get_artifacts_path(self, version_id: str) -> Path:
        """Get the filesystem path for a version's artifacts."""
        con = duckdb.connect(self.db_path)
        try:
            result = con.execute(
                "SELECT artifacts_path FROM models WHERE version_id = ?", [version_id]
            ).fetchone()
            if not result:
                raise ValueError(f"Model version not found: {version_id}")
            return Path(result[0])
        finally:
            con.close()
