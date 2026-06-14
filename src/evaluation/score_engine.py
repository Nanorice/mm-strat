"""Shared RAW-softprob scorer for materializing daily_predictions.

Single code path for both the daily orchestrator (Phase 7.4) and the backfill
util, so the two can never drift. Produces RAW class probabilities only — no
calibration (that stays a read-time / backtest-only concern; see the sprint-12
design sign-off). Calibration belongs to UniverseScorer, not here.

Load the model once (`ScoreEngine.from_prod` / `from_version`), then call
`score(candidates_df)` per date/cohort. `predict_frame` returns the columns
prediction_logger.log_daily_predictions expects (ticker, prob_class_*,
predicted_class).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class ScoreEngine:
    """Holds one loaded prod booster + its feature set; scores candidate frames.

    Construct via `from_prod(db_path)` or `from_version(db_path, version_id)`
    so the registry lookup + artifact resolution live in one place.
    """

    def __init__(self, version_id: str, model_path: Path, feature_names: list[str]):
        self.version_id = version_id
        self.model_path = Path(model_path)
        self.feature_names = feature_names
        self._booster = None  # lazy: loaded on first score

    # ── constructors ─────────────────────────────────────────────────────────

    @classmethod
    def from_version(cls, db_path: str, version_id: str) -> "ScoreEngine":
        """Build for a specific model version. Raises if its artifact is absent."""
        from src.model_registry import ModelRegistry

        registry = ModelRegistry(db_path=db_path)
        artifacts_path = registry.get_artifacts_path(version_id)  # raises ValueError if unset
        model_path = Path(artifacts_path) / "model.json"
        if not model_path.exists():
            raise FileNotFoundError(f"model artifact missing: {model_path}")

        specs = registry.get_model_specs(version_id) or {}
        feature_names = specs.get("features") or []
        if not feature_names:
            raise ValueError(f"model {version_id} has no recorded feature set")
        return cls(version_id, model_path, feature_names)

    @classmethod
    def from_prod(cls, db_path: str) -> Optional["ScoreEngine"]:
        """Build for the currently-promoted prod model, or None if none registered."""
        from src.model_registry import ModelRegistry

        registry = ModelRegistry(db_path=db_path)
        version_id = registry.get_prod_version()
        if not version_id:
            return None
        return cls.from_version(db_path, version_id)

    # ── scoring ────────────────────────────────────────────────────────────────

    def _load(self):
        if self._booster is None:
            import xgboost as xgb

            self._booster = xgb.Booster()
            self._booster.load_model(str(self.model_path))
        return self._booster

    def _resolve_cols(self, candidates: pd.DataFrame) -> list[str]:
        """Intersect the model's feature set with columns present (case-insensitive)."""
        cols_lower = {c.lower(): c for c in candidates.columns}
        return [cols_lower[f.lower()] for f in self.feature_names if f.lower() in cols_lower]

    def predict_frame(self, candidates: pd.DataFrame) -> pd.DataFrame:
        """Score a candidate frame → RAW per-class probabilities.

        Returns a frame with `ticker`, `prob_class_0..K-1`, `predicted_class`.
        Empty in → empty out. Raises if feature columns can't be resolved (the
        caller decides whether that's fatal).
        """
        if candidates.empty:
            return pd.DataFrame()

        import xgboost as xgb

        feature_cols = self._resolve_cols(candidates)
        if not feature_cols:
            raise ValueError(
                f"no feature columns of model {self.version_id} present in candidates"
            )

        X = candidates[feature_cols].replace([np.inf, -np.inf], None)
        for col in X.select_dtypes(include="object").columns:
            X[col] = X[col].astype("category")

        proba = np.asarray(self._load().predict(xgb.DMatrix(X, enable_categorical=True)))
        if proba.ndim == 1:  # binary:logistic → P(class=1); expand to 2-col
            proba = np.column_stack([1 - proba, proba])

        out = candidates[["ticker"]].copy()
        for i in range(proba.shape[1]):
            out[f"prob_class_{i}"] = proba[:, i]
        out["predicted_class"] = proba.argmax(axis=1)
        return out

    def log_predictions(
        self,
        scored: pd.DataFrame,
        target_date,
        cohort: str,
        db_path: str,
    ) -> int:
        """Write an already-scored frame (output of predict_frame) to daily_predictions.

        Split from score_and_log so a backfill can predict a whole window in one
        vectorized pass, then log per date (the logger ranks within each date).
        """
        from src.evaluation.prediction_logger import log_daily_predictions

        if scored.empty:
            return 0
        n_classes = sum(c.startswith("prob_class_") for c in scored.columns)
        target_dt = (
            pd.to_datetime(target_date).date() if isinstance(target_date, str) else target_date
        )
        return log_daily_predictions(
            db_path=Path(db_path),
            prediction_date=target_dt,
            model_version_id=self.version_id,
            predictions=scored,
            production_class_idx=n_classes - 1,
            cohort=cohort,
        )

    def score_and_log(
        self,
        candidates: pd.DataFrame,
        target_date,
        cohort: str,
        db_path: str,
    ) -> int:
        """Score one cohort frame and write it to daily_predictions. Returns rows written."""
        if candidates.empty:
            logger.info("[ScoreEngine] no '%s' candidates on %s", cohort, target_date)
            return 0
        return self.log_predictions(
            self.predict_frame(candidates), target_date, cohort, db_path
        )
