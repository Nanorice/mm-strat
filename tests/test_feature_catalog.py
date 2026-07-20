"""
Tests for feature catalog and model reproducibility system.
Requires a populated DuckDB — run scripts/populate_feature_catalog.py first.
"""

import json
import tempfile
import unittest
from pathlib import Path

import duckdb

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.model_registry import ModelRegistry

DB_PATH = Path(__file__).parent.parent / "data" / "market_data.duckdb"
METADATA_PATH = Path(__file__).parent.parent / "models" / "m01_baseline" / "v1" / "metadata.json"
FEATURE_SET_ID = "fs_m01_baseline_v0.1"
MODEL_VERSION_ID = "M01_baseline_v0.1"


def _con():
    """Read-only handle on the production DB.

    read_only is mandatory: a write-mode open CREATES the database if it is
    absent (and every manager/engine constructed against it then materialises
    its tables there), so an inspection-only test suite would silently build a
    stub production DB. Read-only also keeps the suite off the single-writer
    lock the nightly pipeline needs.
    """
    if not DB_PATH.exists():
        raise unittest.SkipTest(
            f"{DB_PATH} not present — run scripts/populate_feature_catalog.py"
        )
    return duckdb.connect(str(DB_PATH), read_only=True)


class TestFeatureCatalogPopulated(unittest.TestCase):
    """Verify populate_feature_catalog.py ran successfully."""

    def test_v01_feature_set_registered(self):
        """The v0.1 feature set must be registered and non-trivially sized.

        model_feature_sets is the single source of truth now (train_mfe_classifier
        loads features from it) — the old FEATURE_GROUPS cross-check is obsolete.
        """
        con = _con()
        count = con.execute(
            "SELECT COUNT(*) FROM model_feature_sets WHERE feature_set_id = ?",
            [FEATURE_SET_ID],
        ).fetchone()[0]
        con.close()
        self.assertGreaterEqual(count, 100, f"'{FEATURE_SET_ID}' should have 106 features")

    def test_feature_set_includes_atr_delta(self):
        """atr_delta must be registered (declared in FEATURE_GROUPS, absent from artifact)."""
        con = _con()
        count = con.execute(
            "SELECT COUNT(*) FROM model_feature_sets WHERE feature_set_id = ? AND feature_name = 'atr_delta'",
            [FEATURE_SET_ID],
        ).fetchone()[0]
        con.close()
        self.assertEqual(count, 1, "atr_delta should be in model_feature_sets")

    def test_catalog_completeness(self):
        """Every feature in model_feature_sets must have a catalog entry."""
        con = _con()
        orphans = con.execute(
            """
            SELECT mfs.feature_name
            FROM model_feature_sets mfs
            LEFT JOIN feature_catalog fc
                ON mfs.feature_name = fc.feature_name
            WHERE mfs.feature_set_id = ?
              AND fc.feature_name IS NULL
            """,
            [FEATURE_SET_ID],
        ).fetchall()
        con.close()
        self.assertFalse(
            orphans,
            f"Features in model_feature_sets with no catalog entry: {[r[0] for r in orphans]}",
        )

    def test_baseline_model_registered(self):
        """M01_baseline_v0.1 must be registered with classification metrics.

        Prod status belongs to whichever model the registry currently promotes
        (m01_binary since 2026-07-15) — asserted separately below.
        """
        con = _con()
        row = con.execute(
            "SELECT accuracy, weighted_f1, macro_f1, feature_set_id FROM models WHERE version_id = ?",
            [MODEL_VERSION_ID],
        ).fetchone()
        con.close()

        self.assertIsNotNone(row, f"Model '{MODEL_VERSION_ID}' not found in models table")
        accuracy, weighted_f1, macro_f1, fs_id = row
        self.assertIsNotNone(accuracy)
        self.assertIsNotNone(weighted_f1)
        self.assertIsNotNone(macro_f1)
        self.assertEqual(fs_id, FEATURE_SET_ID)

    def test_exactly_one_prod_model(self):
        """The registry must have exactly one prod model with a feature set."""
        con = _con()
        rows = con.execute(
            "SELECT version_id, feature_set_id FROM models WHERE status_flag = 'prod'"
        ).fetchall()
        con.close()
        self.assertEqual(len(rows), 1, f"Expected exactly one prod model, got {rows}")
        self.assertIsNotNone(rows[0][1], "Prod model must have a feature_set_id")


class TestFeatureCatalogImmutability(unittest.TestCase):
    """Verify the PK constraint prevents duplicate feature definitions."""

    def test_feature_immutability(self):
        """Inserting duplicate (feature_name, version_introduced) must raise.

        Runs against a throwaway DB built by ModelRegistry's own DDL. This asserts
        a schema constraint, so it must not INSERT into production — the previous
        version aimed its INSERT at the real DB and was safe only because the PK
        happened to reject it.

        Seeding the row here also makes the assertion honest: the old
        assertRaises(Exception) passed even when feature_catalog was missing
        entirely, so it never actually proved the constraint existed.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Not pre-created — DuckDB refuses to open an existing zero-byte file.
            db_path = Path(tmpdir) / "registry.duckdb"
            ModelRegistry(db_path=db_path)  # runs the feature_catalog DDL

            row = ["rs", "t2_sql", "v3.1"]
            con = duckdb.connect(str(db_path))
            try:
                con.execute(
                    "INSERT INTO feature_catalog (feature_name, source_layer, version_introduced) VALUES (?, ?, ?)",
                    row,
                )
                with self.assertRaises(duckdb.ConstraintException):
                    con.execute(
                        "INSERT INTO feature_catalog (feature_name, source_layer, version_introduced) VALUES (?, ?, ?)",
                        row,
                    )
            finally:
                con.close()


class TestViewNoLogFeatures(unittest.TestCase):
    """v_d2_training must not contain any log_ columns."""

    def test_no_log_features_in_training_view(self):
        con = _con()
        try:
            columns = [
                r[0]
                for r in con.execute("DESCRIBE v_d2_training").fetchall()
            ]
        except Exception:
            self.skipTest("v_d2_training view does not exist — run ViewManager.create_all() first")
        finally:
            con.close()

        log_cols = [c for c in columns if c.lower().startswith("log_")]
        self.assertFalse(
            log_cols,
            f"v_d2_training still has log_ columns: {log_cols}",
        )


class TestGetModelFeaturesFromDB(unittest.TestCase):
    """get_model_features() must return the prod model's registered features."""

    def setUp(self):
        if not DB_PATH.exists():
            self.skipTest(f"{DB_PATH} not present")

    def test_get_model_features_from_db(self):
        from src.utils import get_model_features

        features = get_model_features('M01', db_path=str(DB_PATH))
        self.assertIsInstance(features, list)
        # Prod M01 feature sets range 90–106 features (binary=97, baseline=106).
        self.assertGreaterEqual(len(features), 90, "Expected at least 90 features for M01")

    def test_get_model_features_raises_on_unknown_model(self):
        from src.utils import get_model_features

        with self.assertRaises(RuntimeError):
            get_model_features('NONEXISTENT_MODEL_XYZ', db_path=str(DB_PATH))


class TestReproducibilityInfo(unittest.TestCase):
    """get_reproducibility_info must return full feature definitions for v0.1.

    KNOWN GAP: ModelRegistry has no read-only mode — its constructor runs DDL and
    all 20 of its connect sites open write mode. So these two tests still take a
    write handle on the production DB when it is present, and the conftest guard
    will (correctly) fail them there. Fixing that means threading read_only
    through ModelRegistry, which is a separate change.
    """

    def setUp(self):
        if not DB_PATH.exists():
            self.skipTest(f"{DB_PATH} not present")

    def test_reproducibility_info_returns_dataframe(self):
        registry = ModelRegistry(db_path=DB_PATH)
        df = registry.get_reproducibility_info(MODEL_VERSION_ID)
        self.assertFalse(df.empty, "Reproducibility info should not be empty")
        self.assertIn("feature_name", df.columns)
        self.assertIn("formula_summary", df.columns)
        self.assertIn("source_layer", df.columns)

    def test_reproducibility_info_row_count(self):
        registry = ModelRegistry(db_path=DB_PATH)
        df = registry.get_reproducibility_info(MODEL_VERSION_ID)
        # Feature set has 106 entries (105 valid + atr_delta)
        self.assertGreaterEqual(len(df), 105)


if __name__ == "__main__":
    unittest.main()
