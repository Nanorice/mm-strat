import json
import logging
import subprocess
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import duckdb
from src import db
import pandas as pd

logger = logging.getLogger(__name__)

# Anchor artifact resolution to the project tree, not the CWD or the box a model
# was trained on. All model artifacts live under <project>/models/, so paths are
# stored project-relative and re-rooted on the 'models/' segment at read time —
# this keeps the registry portable across machines.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "market_data.duckdb"
ARTIFACTS_BASE = PROJECT_ROOT / "models" / "artifacts"


def _models_relative(path) -> Optional[str]:
    """Return the 'models/...'-anchored portion of a path (POSIX), or None.

    Handles absolute paths from any machine and either separator style.
    """
    parts = Path(str(path)).parts
    for i in range(len(parts) - 1, -1, -1):
        if parts[i].lower() == "models":
            return Path(*parts[i:]).as_posix()
    return None


def _resolve_artifacts_path(stored: str) -> Path:
    """Resolve a stored artifacts_path to this machine's project tree.

    Stored paths may be project-relative (current) or absolute paths from another
    dev box (legacy). Re-root on the 'models/' segment so scoring works regardless
    of where the model was trained.
    """
    p = Path(stored)
    if p.is_absolute() and p.exists():
        return p
    rel = _models_relative(stored)
    if rel:
        return PROJECT_ROOT / rel
    return p if p.is_absolute() else PROJECT_ROOT / p


class PromotionError(RuntimeError):
    """Raised when ModelRegistry.set_prod refuses to promote a version."""


class ReadOnlyRegistryError(RuntimeError):
    """Raised when a write method is called on a read-only ModelRegistry."""


class ModelRegistry:
    """Manages model versions, specs, metrics, and feature catalog in DuckDB.

    `read_only=True` opens every connection read-only and skips the constructor
    DDL, so readers (tests, dashboards, notebooks) can query the registry without
    taking the single writer handle on market_data.duckdb. Write methods raise
    ReadOnlyRegistryError rather than failing deep inside DuckDB.
    """

    def __init__(self, db_path: Optional[Path] = None, read_only: bool = False):
        self.db_path = str(db_path or DEFAULT_DB_PATH)
        self.read_only = read_only
        if read_only:
            return
        ARTIFACTS_BASE.mkdir(parents=True, exist_ok=True)
        self._create_feature_catalog_tables()
        self._create_forced_promotions_table()

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return db.connect(self.db_path, read_only=self.read_only)

    def _require_writable(self, method: str) -> None:
        if self.read_only:
            raise ReadOnlyRegistryError(
                f"ModelRegistry.{method}() requires a writable registry, but this "
                f"instance was constructed with read_only=True "
                f"(db_path={self.db_path}). Re-construct with read_only=False."
            )

    def _create_forced_promotions_table(self) -> None:
        con = self._connect()
        try:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS forced_promotions (
                    version_id   VARCHAR PRIMARY KEY,
                    reason       VARCHAR NOT NULL,
                    failed_gates JSON    NOT NULL,
                    promoted_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    promoted_by  VARCHAR
                )
                """
            )
        finally:
            con.close()

    # ------------------------------------------------------------------
    # SCHEMA SETUP
    # ------------------------------------------------------------------

    def _create_feature_catalog_tables(self) -> None:
        con = self._connect()
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
        # Existence must be probed via information_schema: PRAGMA table_info()
        # RAISES CatalogException on a missing table rather than returning an
        # empty result, so checking the column set could never detect absence.
        table_exists = con.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = 'models'"
        ).fetchone()
        if not table_exists:
            return  # `models` doesn't exist yet — schema_design.sql owns its creation

        existing_cols = {
            r[1] for r in con.execute("PRAGMA table_info('models')").fetchall()
        }

        if "model_name" not in existing_cols:
            con.execute("ALTER TABLE models ADD COLUMN model_name VARCHAR")
        if "model_version" not in existing_cols:
            con.execute("ALTER TABLE models ADD COLUMN model_version VARCHAR")
        if "model_card_path" not in existing_cols:
            con.execute("ALTER TABLE models ADD COLUMN model_card_path VARCHAR")
        if "model_card_built_at" not in existing_cols:
            con.execute("ALTER TABLE models ADD COLUMN model_card_built_at TIMESTAMP")

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
        self._require_writable("register_version")
        if status not in ("test", "prod", "shadow", "archived"):
            raise ValueError(
                f"Invalid status: {status}. Must be test/prod/shadow/archived"
            )

        if artifacts_path is None:
            full = ARTIFACTS_BASE / version_id
            full.mkdir(parents=True, exist_ok=True)
            artifacts_path = _models_relative(full) or str(full)
        else:
            # Store project-relative so the registry stays portable across machines.
            artifacts_path = _models_relative(artifacts_path) or str(artifacts_path)

        training_date = training_date or date.today()
        specs_json = json.dumps(specs)

        con = self._connect()
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
        con = self._connect()
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
        self._require_writable("update_metrics")
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

        con = self._connect()
        try:
            con.execute(
                f"UPDATE models SET {', '.join(updates)} WHERE version_id = ?", params
            )
            logger.info(f"[OK] Updated metrics for {version_id}")
            print(f"[OK] Updated metrics for {version_id}")
        finally:
            con.close()

    def set_prod(
        self,
        version_id: str,
        force: bool = False,
        force_reason: str = "",
        promoted_by: Optional[str] = None,
    ) -> None:
        """Promote a version to prod, enforcing blocking evaluation gates.

        Reads `evaluation/results.json` from the version's artifacts dir and
        refuses to promote if any gate with `blocking=True` has `status='fail'`,
        unless `force=True` and `force_reason` is non-empty. Forced promotions
        are logged to the `forced_promotions` table.
        """
        self._require_writable("set_prod")
        # 1. Existence check first — fail fast on typos.
        con = self._connect()
        try:
            exists = con.execute(
                "SELECT COUNT(*) FROM models WHERE version_id = ?", [version_id]
            ).fetchone()[0]
            if not exists:
                raise ValueError(f"Model version not found: {version_id}")
        finally:
            con.close()

        # 2. Locate results.json. Two layouts exist in the wild:
        #    - artifacts_path/evaluation/results.json (ClassificationEvaluator default)
        #    - artifacts_path/results.json (legacy)
        artifacts_path = self.get_artifacts_path(version_id)
        candidate_paths = [
            artifacts_path / "evaluation" / "results.json",
            artifacts_path / "results.json",
        ]
        results_path = next((p for p in candidate_paths if p.exists()), None)

        blocking_failures: List[Dict[str, Any]] = []
        if results_path is None:
            if not force:
                raise PromotionError(
                    f"No evaluation results.json found for {version_id} under "
                    f"{artifacts_path}. Promote with force=True if this is "
                    f"intentional (e.g., legacy model from before the gate "
                    f"framework)."
                )
            logger.warning(
                f"[Promote] No results.json for {version_id}; force=True — proceeding."
            )
        else:
            try:
                results = json.loads(results_path.read_text())
            except Exception as e:
                raise PromotionError(
                    f"Could not parse {results_path}: {e}"
                ) from e
            gates = results.get("gates", []) or []
            blocking_failures = [
                g for g in gates
                if bool(g.get("blocking")) and g.get("status") == "fail"
            ]

        # 3. Enforce.
        if blocking_failures and not force:
            lines = [
                f"Promotion blocked for {version_id} — failing blocking gates:"
            ]
            for g in blocking_failures:
                lines.append(
                    f"  - {g.get('name')}: observed={g.get('value')} "
                    f"threshold={g.get('threshold')} — {g.get('detail', '')}"
                )
            lines.append(
                "Override with set_prod(..., force=True, force_reason='...')."
            )
            raise PromotionError("\n".join(lines))

        if blocking_failures and force:
            if not force_reason.strip():
                raise PromotionError(
                    "force=True requires a non-empty force_reason. The reason is "
                    "permanently logged to the forced_promotions table."
                )
            self._log_forced_promotion(
                version_id=version_id,
                reason=force_reason,
                failed_gates=blocking_failures,
                promoted_by=promoted_by,
            )

        # 3b. Advisory model-card check — INFORMATIONAL ONLY, never blocks.
        # The card's verdict thresholds are hand-set and unvalidated; the hard
        # quality gate is the results.json blocking-gate logic above. We surface
        # an adverse card verdict so a human notices, then promote regardless.
        self._warn_on_adverse_card(version_id)

        # 4. Proceed with original promotion logic.
        con = self._connect()
        try:
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

    def _warn_on_adverse_card(
        self, version_id: str, use_case: str = "composite_gate_plus_rank"
    ) -> None:
        """Log a warning if the registered model card is stale or its use-case
        verdict is REJECT/PENDING. Advisory only — does NOT block promotion.

        Silent (info-level) when no card is registered: a card is not a
        promotion prerequisite.
        """
        info = self.get_model_card_info(version_id)
        if info is None:
            logger.info(
                f"[Promote] No model card registered for {version_id} "
                f"(advisory only; not required)."
            )
            return

        card_path = Path(info["path"])
        if not card_path.exists():
            logger.warning(
                f"[Promote] Model card path on record for {version_id} is "
                f"missing on disk: {card_path} (advisory only)."
            )
            return

        try:
            card = json.loads(card_path.read_text())
        except Exception as e:
            logger.warning(
                f"[Promote] Could not read model card {card_path}: {e} "
                f"(advisory only)."
            )
            return

        verdict = (card.get("use_case_verdicts") or {}).get(use_case)
        band = (card.get("aggregate") or {}).get("band")
        if verdict in ("REJECT", "PENDING") or card.get("card_void"):
            logger.warning(
                f"[Promote] ADVISORY: model card for {version_id} reports "
                f"{use_case}={verdict}, band={band}, void={card.get('card_void')}. "
                f"This does NOT block promotion - proceeding. Review {card_path}."
            )
        else:
            logger.info(
                f"[Promote] Model card OK for {version_id}: "
                f"{use_case}={verdict}, band={band}."
            )

    def _log_forced_promotion(
        self,
        version_id: str,
        reason: str,
        failed_gates: List[Dict[str, Any]],
        promoted_by: Optional[str],
    ) -> None:
        self._require_writable("_log_forced_promotion")
        con = self._connect()
        try:
            con.execute(
                """
                INSERT OR REPLACE INTO forced_promotions
                    (version_id, reason, failed_gates, promoted_by)
                VALUES (?, ?, ?, ?)
                """,
                [version_id, reason, json.dumps(failed_gates), promoted_by],
            )
            logger.warning(
                f"[Promote] FORCED promotion of {version_id} logged "
                f"(reason: {reason!r}, {len(failed_gates)} failing gates)"
            )
        finally:
            con.close()

    def list_versions(
        self, status: Optional[str] = None, limit: int = 20
    ) -> pd.DataFrame:
        con = self._connect()
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
        con = self._connect()
        try:
            result = con.execute(
                "SELECT version_id FROM models WHERE status_flag = 'prod' LIMIT 1"
            ).fetchone()
            return result[0] if result else None
        finally:
            con.close()

    def get_shadow_version(self) -> Optional[str]:
        """version_id of the single shadow model, or None if none designated."""
        con = self._connect()
        try:
            result = con.execute(
                "SELECT version_id FROM models WHERE status_flag = 'shadow' LIMIT 1"
            ).fetchone()
            return result[0] if result else None
        finally:
            con.close()

    def set_shadow(self, version_id: str) -> None:
        """Designate a version as the single shadow model for parallel scoring.

        Unlike set_prod(), no evaluation gates are enforced — a shadow exists to
        be evaluated, not trusted. Demotes any existing shadow to 'test', then
        flags this version 'shadow'. At most one shadow at a time. Refuses to
        shadow the current prod version (a model cannot be its own shadow).
        """
        self._require_writable("set_shadow")
        con = self._connect()
        try:
            row = con.execute(
                "SELECT status_flag FROM models WHERE version_id = ?", [version_id]
            ).fetchone()
            if not row:
                raise ValueError(f"Model version not found: {version_id}")
            if row[0] == "prod":
                raise ValueError(
                    f"{version_id} is the prod model and cannot also be shadow."
                )
            # Demote prior shadow, promote this one — single-shadow invariant.
            con.execute(
                "UPDATE models SET status_flag = 'test', updated_at = CURRENT_TIMESTAMP "
                "WHERE status_flag = 'shadow'"
            )
            con.execute(
                "UPDATE models SET status_flag = 'shadow', updated_at = CURRENT_TIMESTAMP "
                "WHERE version_id = ?",
                [version_id],
            )
            logger.info(f"[OK] Designated {version_id} as SHADOW")
            print(f"[OK] {version_id} is now SHADOW")
        finally:
            con.close()

    def register_model_card(
        self, version_id: str, card_path: str, built_at: Optional[str] = None
    ) -> None:
        """Write the model-card path + build timestamp back to the models row.

        Advisory metadata only — does not gate promotion. `built_at` defaults to
        CURRENT_TIMESTAMP if not supplied (pass the card's own built_at to keep
        them aligned).
        """
        self._require_writable("register_model_card")
        con = self._connect()
        try:
            if built_at is None:
                con.execute(
                    "UPDATE models SET model_card_path = ?, "
                    "model_card_built_at = CURRENT_TIMESTAMP, "
                    "updated_at = CURRENT_TIMESTAMP WHERE version_id = ?",
                    [card_path, version_id],
                )
            else:
                con.execute(
                    "UPDATE models SET model_card_path = ?, "
                    "model_card_built_at = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE version_id = ?",
                    [card_path, built_at, version_id],
                )
            logger.info(f"[OK] Registered model card for {version_id}: {card_path}")
        finally:
            con.close()

    def register_drift_card(
        self, version_id: str, card_path: str, built_at: Optional[str] = None
    ) -> None:
        """Write the trailing-window drift card path + build time on the models row.

        Separate from register_model_card(): the drift card is a recency-focused
        monitoring artifact and must NOT overwrite model_card_path, which is the
        full-history promotion-gate card.
        """
        self._require_writable("register_drift_card")
        con = self._connect()
        try:
            if built_at is None:
                con.execute(
                    "UPDATE models SET model_card_drift_path = ?, "
                    "model_card_drift_built_at = CURRENT_TIMESTAMP, "
                    "updated_at = CURRENT_TIMESTAMP WHERE version_id = ?",
                    [card_path, version_id],
                )
            else:
                con.execute(
                    "UPDATE models SET model_card_drift_path = ?, "
                    "model_card_drift_built_at = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE version_id = ?",
                    [card_path, built_at, version_id],
                )
            logger.info(f"[OK] Registered drift card for {version_id}: {card_path}")
        finally:
            con.close()

    def get_drift_card_info(self, version_id: str) -> Optional[Dict[str, Any]]:
        """Return {'path', 'built_at'} for the version's drift card, or None."""
        con = self._connect()
        try:
            row = con.execute(
                "SELECT model_card_drift_path, model_card_drift_built_at FROM models "
                "WHERE version_id = ?",
                [version_id],
            ).fetchone()
            if not row or row[0] is None:
                return None
            return {"path": row[0], "built_at": row[1]}
        finally:
            con.close()

    def get_model_card_info(self, version_id: str) -> Optional[Dict[str, Any]]:
        """Return {'path', 'built_at'} for the version's card, or None if unset."""
        con = self._connect()
        try:
            row = con.execute(
                "SELECT model_card_path, model_card_built_at FROM models "
                "WHERE version_id = ?",
                [version_id],
            ).fetchone()
            if not row or row[0] is None:
                return None
            return {"path": row[0], "built_at": row[1]}
        finally:
            con.close()

    def get_artifacts_path(self, version_id: str) -> Path:
        con = self._connect()
        try:
            result = con.execute(
                "SELECT artifacts_path FROM models WHERE version_id = ?", [version_id]
            ).fetchone()
            if not result:
                raise ValueError(f"Model version not found: {version_id}")
            return _resolve_artifacts_path(result[0])
        finally:
            con.close()

    def get_model_slug(self, version_id: str) -> str:
        """Return the '<model_name>/<model_version>' slug for a version_id.

        This is the resolvable model id consumed by build_model_card.py
        (maps to models/<name>/<version>/model.json) and yields a clean card
        filename — unlike a raw file path or the timestamped version_id.
        """
        con = self._connect()
        try:
            row = con.execute(
                "SELECT model_name, model_version FROM models WHERE version_id = ?",
                [version_id],
            ).fetchone()
            if not row or row[0] is None or row[1] is None:
                raise ValueError(
                    f"Model name/version unset for version_id={version_id}"
                )
            return f"{row[0]}/{row[1]}"
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
        self._require_writable("register_feature_set")
        group_lookup: Dict[str, str] = {}
        for group, names in feature_groups.items():
            for name in names:
                group_lookup[name] = group

        rows = [
            (feature_set_id, f, group_lookup.get(f), i)
            for i, f in enumerate(features)
        ]

        con = self._connect()
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
        con = self._connect()
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
