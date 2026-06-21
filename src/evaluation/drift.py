"""PSI / feature drift detection.

Population Stability Index (PSI) on a frozen-at-training reference bin set.
Rolling baselines drift with the data and hide the drift we want to detect —
each model carries its own immutable `reference_snapshot.json` (per the
evaluation plan §2.2 / decision #4 in the original whitepaper plan).

Public API:
    - compute_psi(reference, current, bins=10, epsilon=1e-6) -> float
    - reference_snapshot(train_df, feature_cols, output_path, bins=10) -> dict
    - quarterly_drift_report(reference_snapshot_path, current_view, db_path,
        quarter, psi_alert_threshold=0.25, psi_warn_threshold=0.10) -> dict
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .gate import GateResult

logger = logging.getLogger(__name__)


def compute_psi(
    reference: np.ndarray,
    current: np.ndarray,
    bins: int = 10,
    epsilon: float = 1e-6,
) -> float:
    """PSI = sum_i (curr_pct_i - ref_pct_i) * ln(curr_pct_i / ref_pct_i).

    Binning uses reference quantiles so the bin edges are fixed at training
    time. NaNs are dropped from both arrays before binning. If either array
    is empty after NaN drop, raises ValueError.

    Empty current-bins are clamped to `epsilon` to avoid log(0)/inf.
    """
    ref = np.asarray(reference, dtype=float)
    cur = np.asarray(current, dtype=float)
    ref = ref[~np.isnan(ref)]
    cur = cur[~np.isnan(cur)]
    if ref.size == 0:
        raise ValueError("reference is empty after NaN drop")
    if cur.size == 0:
        raise ValueError("current is empty after NaN drop")
    if bins < 2:
        raise ValueError(f"bins must be >= 2, got {bins}")

    edges = _quantile_edges(ref, bins)
    return _psi_from_edges(ref, cur, edges, epsilon)


def _quantile_edges(reference: np.ndarray, bins: int) -> np.ndarray:
    """Bin edges from `bins` evenly-spaced reference quantiles. Deduped so
    constant-ish features don't produce zero-width bins."""
    qs = np.linspace(0.0, 1.0, bins + 1)
    edges = np.quantile(reference, qs)
    edges[0] = -np.inf
    edges[-1] = np.inf
    # Drop duplicate inner edges (happens when many reference values are equal).
    return np.unique(edges)


def _psi_from_edges(
    reference: np.ndarray,
    current: np.ndarray,
    edges: np.ndarray,
    epsilon: float,
) -> float:
    ref_counts, _ = np.histogram(reference, bins=edges)
    cur_counts, _ = np.histogram(current, bins=edges)
    ref_pct = ref_counts / max(ref_counts.sum(), 1)
    cur_pct = cur_counts / max(cur_counts.sum(), 1)
    ref_pct = np.where(ref_pct == 0, epsilon, ref_pct)
    cur_pct = np.where(cur_pct == 0, epsilon, cur_pct)
    return float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))


def reference_snapshot(
    train_df: pd.DataFrame,
    feature_cols: list[str],
    output_path: Path,
    bins: int = 10,
    model_version_id: Optional[str] = None,
) -> dict:
    """Build and persist a per-feature quantile/bin-count snapshot.

    Called once at model training time. The output file becomes the immutable
    PSI baseline for that model version.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    features: dict[str, dict] = {}
    skipped: list[str] = []
    for col in feature_cols:
        if col not in train_df.columns:
            skipped.append(col)
            continue
        series = pd.to_numeric(train_df[col], errors="coerce")
        arr = series.to_numpy(dtype=float, copy=False)
        n_missing = int(np.isnan(arr).sum())
        arr = arr[~np.isnan(arr)]
        if arr.size < bins:
            # Too few non-null values to build a stable baseline — record
            # what we have and flag with empty edges.
            features[col] = {
                "bin_edges": [],
                "ref_counts": [],
                "n_missing": n_missing,
                "n_rows": int(arr.size),
                "status": "insufficient_data",
            }
            continue
        edges = _quantile_edges(arr, bins)
        counts, _ = np.histogram(arr, bins=edges)
        features[col] = {
            "bin_edges": [float(e) for e in edges],
            "ref_counts": [int(c) for c in counts],
            "n_missing": n_missing,
            "n_rows": int(arr.size),
            "status": "ok",
        }

    snapshot = {
        "n_rows": int(len(train_df)),
        "n_features": len(features),
        "bins": int(bins),
        "features": features,
        "skipped_features": skipped,
        "created_at": datetime.now().isoformat(),
        "model_version_id": model_version_id,
    }
    output_path.write_text(json.dumps(snapshot, indent=2, default=str))
    logger.info(f"📸 Reference snapshot saved → {output_path} "
                f"({len(features)} features, {len(skipped)} skipped)")
    return snapshot


def quarterly_drift_report(
    reference_snapshot_path: Path,
    current_view: str,
    db_path: Path,
    quarter: str,
    psi_alert_threshold: float = 0.25,
    psi_warn_threshold: float = 0.10,
    current_df: Optional[pd.DataFrame] = None,
) -> dict:
    """Compute PSI per feature for the current quarter against a frozen ref.

    Args:
        reference_snapshot_path: JSON file written by `reference_snapshot`.
        current_view: DuckDB view/table to read current-period data from.
        db_path: DuckDB path. Ignored when `current_df` is provided.
        quarter: label like "2026Q1" (caller computes — keep this side-effect-free).
        psi_alert_threshold: features above this are 'drifted'.
        psi_warn_threshold: features in (warn, alert] are 'warn'.
        current_df: optional pre-loaded DataFrame; bypasses DuckDB read (useful
            for tests and for re-using a previously loaded slice).

    Returns:
        Dict with summary counts, per-feature PSI/status, and a gate entry.
    """
    snap_path = Path(reference_snapshot_path)
    if not snap_path.exists():
        raise FileNotFoundError(f"reference snapshot not found: {snap_path}")
    snap = json.loads(snap_path.read_text())

    if current_df is None:
        from src import db
        feature_cols = list(snap.get("features", {}).keys())
        if not feature_cols:
            raise ValueError(f"reference snapshot {snap_path} has no features")
        # Quote identifiers — feature names may collide with reserved words
        # or contain mixed case (e.g. RS_Sector_Rank).
        select_cols = ", ".join(f'"{c}"' for c in feature_cols)
        con = db.connect(str(db_path), read_only=True)
        try:
            current_df = con.execute(
                f"SELECT {select_cols} FROM {current_view}"
            ).df()
        finally:
            con.close()

    per_feature: dict[str, dict] = {}
    drifted: list[str] = []
    warned: list[str] = []
    skipped: list[str] = []
    epsilon = 1e-6

    for name, spec in snap.get("features", {}).items():
        if spec.get("status") != "ok":
            per_feature[name] = {"psi": None, "status": "skipped",
                                 "reason": spec.get("status", "unknown")}
            skipped.append(name)
            continue
        if name not in current_df.columns:
            per_feature[name] = {"psi": None, "status": "skipped",
                                 "reason": "missing_in_current"}
            skipped.append(name)
            continue
        edges = np.asarray(spec["bin_edges"], dtype=float)
        ref_counts = np.asarray(spec["ref_counts"], dtype=float)
        # Reconstruct reference distribution from stored counts (we don't keep
        # the raw values). Use ref_pct directly so we don't have to re-sample.
        cur = pd.to_numeric(current_df[name], errors="coerce").to_numpy(dtype=float)
        cur = cur[~np.isnan(cur)]
        if cur.size == 0:
            per_feature[name] = {"psi": None, "status": "skipped",
                                 "reason": "empty_current"}
            skipped.append(name)
            continue
        cur_counts, _ = np.histogram(cur, bins=edges)
        ref_pct = ref_counts / max(ref_counts.sum(), 1)
        cur_pct = cur_counts / max(cur_counts.sum(), 1)
        ref_pct = np.where(ref_pct == 0, epsilon, ref_pct)
        cur_pct = np.where(cur_pct == 0, epsilon, cur_pct)
        psi = float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))

        if psi > psi_alert_threshold:
            status = "drifted"
            drifted.append(name)
        elif psi > psi_warn_threshold:
            status = "warn"
            warned.append(name)
        else:
            status = "ok"
        per_feature[name] = {"psi": psi, "status": status,
                             "n_current": int(cur.size)}

    n_drifted = len(drifted)
    n_checked = sum(1 for v in per_feature.values() if v["psi"] is not None)

    gate = GateResult(
        name="psi_drift",
        status="pass" if n_drifted == 0 else "fail",
        value=float(n_drifted),
        threshold=0.0,
        detail=(
            f"{n_drifted} features with PSI > {psi_alert_threshold} "
            f"(of {n_checked} checked)"
        ),
        blocking=False,
    ).to_dict()

    return {
        "quarter": quarter,
        "model_version_id": snap.get("model_version_id"),
        "reference_snapshot_path": str(snap_path),
        "current_view": current_view,
        "n_features_checked": n_checked,
        "n_features_drifted": n_drifted,
        "n_features_warned": len(warned),
        "n_features_skipped": len(skipped),
        "per_feature": per_feature,
        "drifted_features": drifted,
        "warned_features": warned,
        "skipped_features": skipped,
        "thresholds": {
            "alert": psi_alert_threshold,
            "warn": psi_warn_threshold,
        },
        "gates": [gate],
        "created_at": datetime.now().isoformat(),
    }
