import json
import logging
import subprocess
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("data/market_data.duckdb")
ARTIFACTS_BASE = Path("models/artifacts")


class ModelRegistry:
    """Manages model versions, specs, metrics, and feature catalog in DuckDB."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = str(db_path or DEFAULT_DB_PATH)
        ARTIFACTS_BASE.mkdir(parents=True, exist_ok=True)
        self._create_feature_catalog_tables()

    # ------------------------------------------------------------------
    # SCHEMA SETUP
    # ------------------------------------------------------------------

    def _create_feature_catalog_tables(self) -> None:
        con = duckdb.connect(self.db_path)
        try:
            self._migrate_models_table(con)
            con.execute("""
                CREATE TABLE IF NOT EXISTS feature_catalog (
                    feature_name       VARCHAR NOT NULL,
                    display_name       VARCHAR,
                    description        VARCHAR,
                    formula_summary    VARCHAR,
                    source_layer       VARCHAR NOT NULL,
                    source_table       VARCHAR,
                    data_type          VARCHAR DEFAULT 'DOUBLE',
                    is_categorical     BOOLEAN DEFAULT FALSE,
                    version_introduced VARCHAR NOT NULL DEFAULT 'v3.1',
                    version_retired    VARCHAR,
                    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (feature_name, version_introduced)
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS model_feature_sets (
                    feature_set_id  VARCHAR NOT NULL,
                    feature_name    VARCHAR NOT NULL,
                    feature_group   VARCHAR,
                    ordinal         INTEGER,
                    PRIMARY KEY (feature_set_id, feature_name)
                )
            """)
        finally:
            con.close()

    @staticmethod
    def _migrate_models_table(con: duckdb.DuckDBPyConnection) -> None:
        """Idempotently add model_name/model_version columns to `models` and backfill.

        Backfill rule for existing rows: split version_id on the timestamp suffix
        `_YYYYMMDD_HHMMSS`. Anything before that is `model_name`, the timestamp is
        `model_version`. If no timestamp, the whole id becomes `model_name` and
        `model_version` stays NULL. Existing non-NULL values are not overwritten.
        """
        existing_cols = {
            r[0] for r in con.execute("PRAGMA table_info('models')").fetchall()
        }
        if not existing_cols:
            return  # `models` doesn't exist yet — schema_design.sql owns its creation

        if "model_name" not in existing_cols:
            con.execute("ALTER TABLE models ADD COLUMN model_name VARCHAR")
        if "model_version" not in existing_cols:
            con.execute("ALTER TABLE models ADD COLUMN model_version VARCHAR")

        con.execute(r"""
            UPDATE models
            SET model_name = CASE
                    WHEN regexp_matches(version_id, '_\d{8}_\d{6}$')
                        THEN regexp_replace(version_id, '_\d{8}_\d{6}$', '')
                    ELSE version_id
                END,
                model_version = CASE
                    WHEN regexp_matches(version_id, '_\d{8}_\d{6}$')
                        THEN regexp_extract(version_id, '(\d{8}_\d{6})$', 1)
                    ELSE NULL
                END
            WHERE model_name IS NULL
        """)

    # ------------------------------------------------------------------
    # MODEL VERSIONS
    # ------------------------------------------------------------------

    def register_version(
        self,
        version_id: str,
        specs: Dict[str, Any],
        status: str = "test",
        feature_version: str = "v3.1",
        training_date: Optional[date] = None,
        dataset_rows: Optional[int] = None,
        accuracy: Optional[float] = None,
        weighted_f1: Optional[float] = None,
        macro_f1: Optional[float] = None,
        feature_set_id: Optional[str] = None,
        git_sha: Optional[str] = None,
        model_type: str = "classifier",
        artifacts_path: Optional[str] = None,
        model_name: Optional[str] = None,
        model_version: Optional[str] = None,
    ) -> None:
        if status not in ("test", "prod", "archived"):
            raise ValueError(f"Invalid status: {status}. Must be test/prod/archived")

        if artifacts_path is None:
            artifacts_path = str(ARTIFACTS_BASE / version_id)
            Path(artifacts_path).mkdir(parents=True, exist_ok=True)
        else:
            artifacts_path = str(artifacts_path)

        training_date = training_date or date.today()
        specs_json = json.dumps(specs)

        con = duckdb.connect(self.db_path)
        try:
            con.execute(
                """
                INSERT INTO models (
                    version_id, status_flag, specs_json, feature_version,
                    training_date, dataset_rows, artifacts_path,
                    accuracy, weighted_f1, macro_f1,
                    feature_set_id, git_sha, model_type,
                    model_name, model_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    version_id, status, specs_json, feature_version,
                    training_date, dataset_rows, artifacts_path,
                    accuracy, weighted_f1, macro_f1,
                    feature_set_id, git_sha, model_type,
                    model_name, model_version,
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
        accuracy: Optional[float] = None,
        weighted_f1: Optional[float] = None,
        macro_f1: Optional[float] = None,
    ) -> None:
        updates = []
        params = []

        for col, val in [
            ("rmse", rmse), ("mae", mae), ("r2", r2),
            ("spearman_corr", spearman_corr),
            ("accuracy", accuracy), ("weighted_f1", weighted_f1), ("macro_f1", macro_f1),
        ]:
            if val is not None:
                updates.append(f"{col} = ?")
                params.append(val)

        if not updates:
            logger.warning("No metrics provided for update")
            return

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(version_id)

        con = duckdb.connect(self.db_path)
        try:
            con.execute(
                f"UPDATE models SET {', '.join(updates)} WHERE version_id = ?", params
            )
            logger.info(f"[OK] Updated metrics for {version_id}")
            print(f"[OK] Updated metrics for {version_id}")
        finally:
            con.close()

    def set_prod(self, version_id: str) -> None:
        con = duckdb.connect(self.db_path)
        try:
            exists = con.execute(
                "SELECT COUNT(*) FROM models WHERE version_id = ?", [version_id]
            ).fetchone()[0]
            if not exists:
                raise ValueError(f"Model version not found: {version_id}")
            con.execute(
                "UPDATE models SET status_flag = 'archived' WHERE status_flag = 'prod'"
            )
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
        con = duckdb.connect(self.db_path)
        try:
            where = "WHERE status_flag = ?" if status else ""
            params = [status, limit] if status else [limit]
            sql = f"""
                SELECT version_id, status_flag, feature_version, training_date,
                       dataset_rows, accuracy, weighted_f1, macro_f1,
                       feature_set_id, git_sha, model_type,
                       rmse, mae, r2, spearman_corr, created_at
                FROM models
                {where}
                ORDER BY created_at DESC
                LIMIT ?
            """
            return con.execute(sql, params).fetchdf()
        finally:
            con.close()

    def get_prod_version(self) -> Optional[str]:
        con = duckdb.connect(self.db_path)
        try:
            result = con.execute(
                "SELECT version_id FROM models WHERE status_flag = 'prod' LIMIT 1"
            ).fetchone()
            return result[0] if result else None
        finally:
            con.close()

    def get_artifacts_path(self, version_id: str) -> Path:
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

    # ------------------------------------------------------------------
    # FEATURE CATALOG
    # ------------------------------------------------------------------

    def register_feature_set(
        self,
        feature_set_id: str,
        features: List[str],
        feature_groups: Dict[str, List[str]],
    ) -> None:
        """Insert feature set rows into model_feature_sets."""
        group_lookup: Dict[str, str] = {}
        for group, names in feature_groups.items():
            for name in names:
                group_lookup[name] = group

        rows = [
            (feature_set_id, f, group_lookup.get(f), i)
            for i, f in enumerate(features)
        ]

        con = duckdb.connect(self.db_path)
        try:
            con.executemany(
                "INSERT OR IGNORE INTO model_feature_sets "
                "(feature_set_id, feature_name, feature_group, ordinal) VALUES (?, ?, ?, ?)",
                rows,
            )
            print(f"[OK] Registered feature set '{feature_set_id}' ({len(rows)} features)")
        finally:
            con.close()

    def get_reproducibility_info(self, version_id: str) -> pd.DataFrame:
        """Return full feature definitions for a model version.

        Joins models → model_feature_sets → feature_catalog.
        """
        con = duckdb.connect(self.db_path)
        try:
            result = con.execute(
                "SELECT feature_set_id, git_sha, model_type, feature_version "
                "FROM models WHERE version_id = ?",
                [version_id],
            ).fetchone()
            if not result:
                raise ValueError(f"Model version not found: {version_id}")

            feature_set_id, git_sha, model_type, feature_version = result

            df = con.execute(
                """
                SELECT
                    mfs.ordinal,
                    mfs.feature_name,
                    mfs.feature_group,
                    fc.description,
                    fc.formula_summary,
                    fc.source_layer,
                    fc.source_table,
                    fc.is_categorical,
                    fc.version_introduced,
                    fc.version_retired
                FROM model_feature_sets mfs
                LEFT JOIN feature_catalog fc
                    ON mfs.feature_name = fc.feature_name
                    AND fc.version_introduced = ?
                WHERE mfs.feature_set_id = ?
                ORDER BY mfs.ordinal
                """,
                [feature_version, feature_set_id],
            ).fetchdf()

            df.attrs["version_id"] = version_id
            df.attrs["git_sha"] = git_sha
            df.attrs["model_type"] = model_type
            return df
        finally:
            con.close()

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

    @staticmethod
    def get_git_sha() -> str:
        try:
            return subprocess.check_output(
                ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
            ).decode().strip()
        except Exception:
            return "unknown"
