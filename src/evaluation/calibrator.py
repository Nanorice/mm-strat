"""Probability calibrator for binary classifiers.

Why this exists:
    XGBoost binary:logistic with `compute_class_weight='balanced'` centers
    its output around the *resampled* prior, not the true base rate. For
    m01_binary/v1 this drove ECE to 0.32 with the model emitting ~50% mean
    probability against a 14.5% true Home-Run base rate. Isotonic regression
    on the validation slice remaps raw probabilities to honest ones without
    retraining.

Design:
    - `IsotonicCalibrator.fit` consumes (y_true, y_prob_raw) on a held-out
      slice and stores an internal `IsotonicRegression(out_of_bounds='clip')`.
    - `transform` is idempotent: a calibrated value put through `transform`
      again returns itself.
    - `save` / `load` round-trip via joblib (more portable across sklearn
      versions than raw pickle).
    - Metadata records `n_fit_samples`, `fit_date`, `model_version_id`,
      plus pre/post ECE so audit-time questions are answerable from the
      artifact alone.

Why isotonic over Platt:
    Platt assumes the miscalibration is sigmoid-shaped (a single (a, b)
    fit). When class weights shift the *mean* of the output without
    distorting its shape, Platt is fine. But the m01_binary/v1 negative-
    permutation features tell us the model's confidence isn't just shifted
    — it's non-monotonic over confidence regions. Isotonic is monotone but
    accepts arbitrary curves between the constraint points; safer default.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class CalibratorMetadata:
    n_fit_samples: int
    fit_date: str
    model_version_id: Optional[str] = None
    pre_ece: Optional[float] = None
    post_ece: Optional[float] = None
    method: str = "isotonic"


class IsotonicCalibrator:
    """Isotonic probability calibrator for binary classifiers.

    Fits once on a held-out (y_true, y_prob_raw) pair; thereafter `transform`
    maps raw probabilities to calibrated probabilities. Stateless across
    invocations once fitted.
    """

    def __init__(self) -> None:
        self._iso = None  # sklearn IsotonicRegression, lazy-imported
        self.metadata: Optional[CalibratorMetadata] = None

    def fit(
        self,
        y_true: np.ndarray,
        y_prob_raw: np.ndarray,
        model_version_id: Optional[str] = None,
    ) -> "IsotonicCalibrator":
        from sklearn.isotonic import IsotonicRegression

        y_true = np.asarray(y_true).ravel()
        y_prob_raw = np.asarray(y_prob_raw, dtype=float).ravel()

        if y_true.shape != y_prob_raw.shape:
            raise ValueError(
                f"y_true and y_prob_raw must have the same shape; "
                f"got {y_true.shape} vs {y_prob_raw.shape}"
            )
        if len(y_true) < 50:
            raise ValueError(
                f"need at least 50 samples to fit calibrator; got {len(y_true)}"
            )
        if set(np.unique(y_true).tolist()) - {0, 1}:
            raise ValueError("y_true must be binary {0, 1}")

        self._iso = IsotonicRegression(out_of_bounds="clip")
        self._iso.fit(y_prob_raw, y_true)

        self.metadata = CalibratorMetadata(
            n_fit_samples=int(len(y_true)),
            fit_date=datetime.now(timezone.utc).isoformat(),
            model_version_id=model_version_id,
        )
        logger.info(
            "Fitted IsotonicCalibrator on %d samples (model=%s)",
            len(y_true),
            model_version_id,
        )
        return self

    def transform(self, y_prob_raw: np.ndarray) -> np.ndarray:
        if self._iso is None:
            raise RuntimeError("Calibrator not fitted; call fit() first")
        return np.asarray(self._iso.predict(np.asarray(y_prob_raw, dtype=float).ravel()))

    def fit_transform(
        self,
        y_true: np.ndarray,
        y_prob_raw: np.ndarray,
        model_version_id: Optional[str] = None,
    ) -> np.ndarray:
        self.fit(y_true, y_prob_raw, model_version_id=model_version_id)
        return self.transform(y_prob_raw)

    def save(self, path: Path) -> None:
        import joblib

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if self._iso is None or self.metadata is None:
            raise RuntimeError("Cannot save an unfitted calibrator")
        joblib.dump({"iso": self._iso, "metadata": self.metadata}, path)
        # Sidecar JSON for human-readable audit.
        meta_path = path.with_suffix(".meta.json")
        meta_path.write_text(
            json.dumps(
                {
                    "n_fit_samples": self.metadata.n_fit_samples,
                    "fit_date": self.metadata.fit_date,
                    "model_version_id": self.metadata.model_version_id,
                    "pre_ece": self.metadata.pre_ece,
                    "post_ece": self.metadata.post_ece,
                    "method": self.metadata.method,
                },
                indent=2,
            )
        )
        logger.info("Saved calibrator to %s (+ %s)", path, meta_path.name)

    @classmethod
    def load(cls, path: Path) -> "IsotonicCalibrator":
        import joblib

        bundle = joblib.load(Path(path))
        cal = cls()
        cal._iso = bundle["iso"]
        cal.metadata = bundle["metadata"]
        return cal


def calibrator_path_for(model_dir: Path) -> Path:
    """Canonical location of a calibrator inside a model artifact directory."""
    return Path(model_dir) / "calibrator.joblib"
