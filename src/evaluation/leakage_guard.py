"""Temporal Leakage Detection and Prevention.

Validates train/test splits to ensure no future data leaks into training.
Critical for time-series data where temporal ordering must be preserved.

Key validations:
- No test data appears before train data
- No overlap in date ranges
- Proper chronological ordering
- Label horizon respected (audit_label)
- Train-vs-deploy feature parity (feature_parity_check)
"""

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .gate import GateResult
from .label_registry import LabelDefinition

logger = logging.getLogger(__name__)


class LeakageGuard:
    """Prevent temporal data leakage in train/test splits."""

    @staticmethod
    def validate_temporal_split(
        df: pd.DataFrame,
        date_col: str,
        train_indices: np.ndarray,
        test_indices: np.ndarray,
        strict: bool = True
    ) -> Dict:
        """Validate that test data doesn't leak into training period.

        Args:
            df: Full dataframe with date column
            date_col: Name of date column
            train_indices: Array of training row indices
            test_indices: Array of test row indices
            strict: If True, raise error on leakage; if False, just warn

        Returns:
            Dictionary with validation results:
            {
                'is_valid': bool,
                'train_date_range': (min, max),
                'test_date_range': (min, max),
                'overlap': bool,
                'leakage_rows': int,
                'message': str
            }

        Raises:
            ValueError: If strict=True and leakage detected
        """
        # Extract dates for each split
        train_dates = df.iloc[train_indices][date_col]
        test_dates = df.iloc[test_indices][date_col]

        # Compute date ranges
        train_min, train_max = train_dates.min(), train_dates.max()
        test_min, test_max = test_dates.min(), test_dates.max()

        # Check for temporal leakage
        # Leakage = any test date before the latest train date
        leakage_mask = test_dates < train_max
        leakage_count = int(leakage_mask.sum())

        # Check for overlap
        overlap = test_min < train_max

        # Determine validity
        is_valid = (leakage_count == 0)

        # Build message
        if is_valid:
            message = (
                f"✅ No temporal leakage detected. "
                f"Train: {train_min} → {train_max}, "
                f"Test: {test_min} → {test_max}"
            )
            logger.info(message)
        else:
            message = (
                f"❌ TEMPORAL LEAKAGE DETECTED! "
                f"{leakage_count:,} test rows ({leakage_count / len(test_dates) * 100:.1f}%) "
                f"occur before train_max ({train_max}). "
                f"Train: {train_min} → {train_max}, "
                f"Test: {test_min} → {test_max}"
            )
            if strict:
                logger.error(message)
                raise ValueError(message)
            else:
                logger.warning(message)

        result = {
            'is_valid': is_valid,
            'train_date_range': (str(train_min), str(train_max)),
            'test_date_range': (str(test_min), str(test_max)),
            'overlap': overlap,
            'leakage_rows': leakage_count,
            'leakage_percentage': float(leakage_count / len(test_dates) * 100) if len(test_dates) > 0 else 0.0,
            'message': message
        }

        return result

    @staticmethod
    def validate_split_ordering(
        df: pd.DataFrame,
        date_col: str,
        train_indices: np.ndarray,
        val_indices: np.ndarray,
        test_indices: np.ndarray
    ) -> Dict:
        """Validate chronological ordering of train/val/test splits.

        Args:
            df: Full dataframe
            date_col: Name of date column
            train_indices: Training indices
            val_indices: Validation indices
            test_indices: Test indices

        Returns:
            Dictionary with validation results for each split boundary
        """
        # Validate train → val
        train_val_result = LeakageGuard.validate_temporal_split(
            df, date_col, train_indices, val_indices, strict=False
        )

        # Validate val → test
        val_test_result = LeakageGuard.validate_temporal_split(
            df, date_col, val_indices, test_indices, strict=False
        )

        # Validate train → test (overall check)
        train_test_result = LeakageGuard.validate_temporal_split(
            df, date_col, train_indices, test_indices, strict=False
        )

        all_valid = (
            train_val_result['is_valid'] and
            val_test_result['is_valid'] and
            train_test_result['is_valid']
        )

        result = {
            'all_valid': all_valid,
            'train_val': train_val_result,
            'val_test': val_test_result,
            'train_test': train_test_result
        }

        if all_valid:
            logger.info("✅ All splits pass temporal validation")
        else:
            logger.warning("⚠️  Some splits failed temporal validation")

        return result

    @staticmethod
    def check_feature_leakage(
        feature_names: list,
        forbidden_patterns: list = None
    ) -> Dict:
        """Check for features that might contain future information.

        Args:
            feature_names: List of feature names
            forbidden_patterns: List of substrings that indicate leakage
                               (default: ['mfe', 'mae', 'return_at_exit', 'final_'])

        Returns:
            Dictionary with:
            {
                'is_clean': bool,
                'suspicious_features': List[str],
                'message': str
            }
        """
        if forbidden_patterns is None:
            forbidden_patterns = [
                'mfe',  # Maximum Favorable Excursion
                'mae',  # Maximum Adverse Excursion
                'return_at_exit',  # Future return
                'final_',  # Final outcome
                'outcome_',  # Outcome variable
                'exit_',  # Exit metrics
                'result_'  # Result variable
            ]

        # Case-insensitive search
        feature_names_lower = [f.lower() for f in feature_names]

        suspicious = []
        for feat, feat_lower in zip(feature_names, feature_names_lower):
            for pattern in forbidden_patterns:
                if pattern.lower() in feat_lower:
                    suspicious.append(feat)
                    break

        is_clean = len(suspicious) == 0

        if is_clean:
            message = f"✅ No suspicious features detected ({len(feature_names)} features checked)"
            logger.info(message)
        else:
            message = (
                f"⚠️  Found {len(suspicious)} suspicious features that may contain future data: "
                f"{', '.join(suspicious[:5])}"
                + (f" ... and {len(suspicious) - 5} more" if len(suspicious) > 5 else "")
            )
            logger.warning(message)

        return {
            'is_clean': is_clean,
            'suspicious_features': suspicious,
            'num_suspicious': len(suspicious),
            'num_features': len(feature_names),
            'message': message
        }

    @staticmethod
    def create_temporal_split(
        df: pd.DataFrame,
        date_col: str,
        train_frac: float = 0.6,
        val_frac: float = 0.2,
        test_frac: float = 0.2
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Create chronologically ordered train/val/test split.

        Args:
            df: Dataframe to split
            date_col: Name of date column
            train_frac: Fraction for training (default 0.6)
            val_frac: Fraction for validation (default 0.2)
            test_frac: Fraction for testing (default 0.2)

        Returns:
            Tuple of (train_indices, val_indices, test_indices)

        Raises:
            ValueError: If fractions don't sum to 1.0
        """
        if not np.isclose(train_frac + val_frac + test_frac, 1.0):
            raise ValueError(
                f"Fractions must sum to 1.0. Got: {train_frac} + {val_frac} + {test_frac} = "
                f"{train_frac + val_frac + test_frac}"
            )

        # Sort by date
        df_sorted = df.sort_values(date_col).reset_index(drop=True)

        # Calculate split points
        n = len(df_sorted)
        train_end = int(n * train_frac)
        val_end = int(n * (train_frac + val_frac))

        # Create index arrays
        train_indices = np.arange(0, train_end)
        val_indices = np.arange(train_end, val_end)
        test_indices = np.arange(val_end, n)

        logger.info(
            f"📊 Created temporal split: "
            f"Train={len(train_indices):,} ({train_frac:.0%}), "
            f"Val={len(val_indices):,} ({val_frac:.0%}), "
            f"Test={len(test_indices):,} ({test_frac:.0%})"
        )

        # Validate the split
        validation_result = LeakageGuard.validate_split_ordering(
            df_sorted,
            date_col,
            train_indices,
            val_indices,
            test_indices
        )

        if not validation_result['all_valid']:
            logger.error("❌ Created split failed validation - this should never happen!")

        return train_indices, val_indices, test_indices

    # ------------------------------------------------------------------
    # §2.1.2 — Label-side leakage audit
    # ------------------------------------------------------------------
    @staticmethod
    def audit_label(
        labels_df: pd.DataFrame,
        price_data_view: str,
        label_def: LabelDefinition,
        db_path: Path,
        max_horizon_days: Optional[int] = None,
        recompute_fn: Optional[Callable[[pd.DataFrame, "LabelDefinition"], Any]] = None,
        price_table: str = "price_data",
    ) -> Dict[str, Any]:
        """Verify every (ticker, date) label uses only price_data within horizon.

        Parameters
        ----------
        labels_df
            Must contain `ticker`, `date`, and `label_def.target_col`.
        price_data_view
            Name of view/table to read prices from (kept for parity with the
            plan; the audit currently joins against `price_table` directly to
            avoid needing a deployment-style view).
        label_def
            The `LabelDefinition` describing the label semantics.
        db_path
            DuckDB path.
        max_horizon_days
            Overrides `label_def.horizon_days` if provided.
        recompute_fn
            Optional reference implementation; called as
            `recompute_fn(window_prices_df, label_def)` and expected to return
            the recomputed label value. When supplied, value-mismatches are
            recorded as `horizon_violations` entries with `kind='value_mismatch'`.
        price_table
            Where to fetch prices from. Defaults to `price_data`.
        """
        from src import db

        required = {"ticker", "date", label_def.target_col}
        missing_cols = required - set(labels_df.columns)
        if missing_cols:
            raise ValueError(f"labels_df missing required columns: {sorted(missing_cols)}")

        horizon = int(max_horizon_days if max_horizon_days is not None else label_def.horizon_days)
        if horizon <= 0:
            raise ValueError(f"horizon must be positive, got {horizon}")

        horizon_violations: List[Dict[str, Any]] = []
        missing_price_rows: List[Dict[str, Any]] = []
        max_observed_horizon = 0

        con = db.connect(str(db_path), read_only=True)
        try:
            for row in labels_df.itertuples(index=False):
                ticker = getattr(row, "ticker")
                label_date = pd.Timestamp(getattr(row, "date"))
                stored_label = getattr(row, label_def.target_col)

                # Pull the horizon window from price_table. We deliberately
                # query *more* than the horizon (horizon + 5 trading days) so
                # we can detect labels that secretly used bars beyond the
                # declared horizon.
                window_end = label_date + pd.Timedelta(days=int(horizon * 1.5) + 5)
                window = con.execute(
                    f"""
                    SELECT *
                    FROM {price_table}
                    WHERE ticker = ?
                      AND date > ?
                      AND date <= ?
                    ORDER BY date
                    """,
                    [ticker, str(label_date.date()), str(window_end.date())],
                ).df()

                if window.empty:
                    missing_price_rows.append(
                        {"ticker": ticker, "date": str(label_date.date())}
                    )
                    continue

                window_dates = pd.to_datetime(window["date"])
                # Calendar-day horizon: a bar is "in horizon" if its date is
                # within `horizon_days` calendar days of label_date. The label
                # itself can reference at most that bar.
                horizon_cutoff = label_date + pd.Timedelta(days=horizon)
                in_horizon = window_dates <= horizon_cutoff
                if in_horizon.any():
                    observed = (window_dates[in_horizon].max() - label_date).days
                    max_observed_horizon = max(max_observed_horizon, int(observed))

                if recompute_fn is None:
                    # Structural-only check: at minimum, *some* prices must
                    # exist within the declared horizon, otherwise the label
                    # is unbacked.
                    if not in_horizon.any():
                        horizon_violations.append(
                            {
                                "ticker": ticker,
                                "date": str(label_date.date()),
                                "kind": "no_in_horizon_prices",
                                "stored_label": _to_py(stored_label),
                            }
                        )
                    continue

                # Reference-recompute check: drive the label off the
                # in-horizon window, compare to stored label.
                window_in = window.loc[in_horizon].reset_index(drop=True)
                try:
                    recomputed = recompute_fn(window_in, label_def)
                except Exception as exc:  # pragma: no cover — fixture errors
                    horizon_violations.append(
                        {
                            "ticker": ticker,
                            "date": str(label_date.date()),
                            "kind": "recompute_error",
                            "error": str(exc),
                        }
                    )
                    continue

                if not _labels_equal(recomputed, stored_label):
                    horizon_violations.append(
                        {
                            "ticker": ticker,
                            "date": str(label_date.date()),
                            "kind": "value_mismatch",
                            "stored_label": _to_py(stored_label),
                            "recomputed_label": _to_py(recomputed),
                        }
                    )

                # Also check whether the stored label could only be reproduced
                # using bars beyond the horizon — i.e. if recompute on the
                # in-horizon window disagrees but recompute on the wider window
                # agrees. That's strong evidence of a horizon overrun.
                if recompute_fn is not None and horizon_violations and horizon_violations[-1].get("kind") == "value_mismatch":
                    try:
                        recomputed_wide = recompute_fn(window, label_def)
                        if _labels_equal(recomputed_wide, stored_label):
                            horizon_violations[-1]["kind"] = "horizon_overrun"
                    except Exception:  # pragma: no cover
                        pass
        finally:
            con.close()

        n_violations = len(horizon_violations) + len(missing_price_rows)
        passed = n_violations == 0
        gate = GateResult(
            name="label_horizon",
            status="pass" if passed else "fail",
            value=float(n_violations),
            threshold=0.0,
            detail=(
                f"checked={len(labels_df)} violations={len(horizon_violations)} "
                f"missing_price={len(missing_price_rows)} "
                f"max_observed_horizon_days={max_observed_horizon}"
            ),
            blocking=True,
        )

        return {
            "checked_n": int(len(labels_df)),
            "horizon_violations": horizon_violations,
            "missing_price_rows": missing_price_rows,
            "max_observed_horizon_days": max_observed_horizon,
            "passed": passed,
            "gate": gate.to_dict(),
        }

    # ------------------------------------------------------------------
    # §2.1.3 — Training vs deployment feature parity
    # ------------------------------------------------------------------
    @staticmethod
    def feature_parity_check(
        train_view: str,
        deploy_view: str,
        feature_set_id: str,
        db_path: Path,
        sample_n: int = 100,
        rtol: float = 1e-6,
        seed: int = 42,
    ) -> Dict[str, Any]:
        """Sample (ticker, date) pairs present in both views and assert that
        their feature vectors are numerically equal.

        Catches the m01_rank class of bug where deployment encodes categoricals
        differently from training.
        """
        from src import db
        import time

        t0 = time.perf_counter()
        logger.info(
            "feature_parity_check: starting (train_view=%s deploy_view=%s "
            "feature_set=%s sample_n=%d)",
            train_view, deploy_view, feature_set_id, sample_n,
        )

        con = db.connect(str(db_path), read_only=True)
        try:
            feature_rows = con.execute(
                """
                SELECT feature_name
                FROM model_feature_sets
                WHERE feature_set_id = ?
                ORDER BY ordinal
                """,
                [feature_set_id],
            ).fetchall()
            if not feature_rows:
                raise ValueError(
                    f"feature_set_id '{feature_set_id}' empty or unknown — "
                    f"populate model_feature_sets first."
                )
            feature_cols = [r[0] for r in feature_rows]
            logger.info("feature_parity_check: loaded %d features in %.1fs",
                        len(feature_cols), time.perf_counter() - t0)

            # If a caller passes v_d2_training, swap to the materialized
            # d2_training_cache when available — same data, ~100x faster scan.
            # The cache is refreshed by FeaturePipeline.compute_all() after every
            # Phase E run, so it tracks the view content.
            effective_train_view = train_view
            if train_view == "v_d2_training":
                cache_exists = con.execute(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_name = 'd2_training_cache'"
                ).fetchone()[0] > 0
                if cache_exists:
                    effective_train_view = "d2_training_cache"
                    logger.info(
                        "feature_parity_check: using materialized "
                        "d2_training_cache for train side (was v_d2_training)"
                    )

            # Pull DISTINCT (ticker, date) keys that exist in both views.
            # The DISTINCT wrappers are load-bearing: v_d2_training and
            # v_d3_deployment can have multiple rows per (ticker, date) when
            # joined against historical filings (multiple fundamental rows per
            # period). Without DISTINCT, the inner join is a Cartesian product
            # and the sample draws duplicate keys.
            sample_sql = f"""
                WITH common AS (
                    SELECT DISTINCT t.ticker AS ticker, t.date AS date
                    FROM (SELECT DISTINCT ticker, date FROM {effective_train_view}) t
                    INNER JOIN (SELECT DISTINCT ticker, date FROM {deploy_view}) d
                      ON t.ticker = d.ticker AND t.date = d.date
                )
                SELECT ticker, date
                FROM common
                USING SAMPLE {int(sample_n)} ROWS (RESERVOIR, {int(seed)})
            """
            t_sample = time.perf_counter()
            logger.info("feature_parity_check: sampling %d common keys "
                        "(may take 1-3 min on large views — DISTINCT scan)...",
                        sample_n)
            keys_df = con.execute(sample_sql).df()
            logger.info("feature_parity_check: sampled %d keys in %.1fs",
                        len(keys_df), time.perf_counter() - t_sample)
            if keys_df.empty:
                return {
                    "sampled_pairs": 0,
                    "matched": 0,
                    "mismatches": [],
                    "dtype_mismatches": [],
                    "passed": True,
                    "gate": GateResult(
                        name="feature_parity",
                        status="n/a",
                        value=0.0,
                        threshold=0.0,
                        detail="no overlapping (ticker, date) rows to sample",
                        blocking=True,
                    ).to_dict(),
                }

            # Wide-load both sides for the sampled keys, picking a single
            # representative row per (ticker, date) via ROW_NUMBER() = 1.
            # We register `keys_df` as a temp relation and INNER JOIN against
            # it — this lets DuckDB push the filter down through the view's
            # CTEs, vs the `IN (...tuple list)` form which forced a full
            # view materialization (~12min per side on v_d2_training).
            keys_for_join = pd.DataFrame({
                "ticker": keys_df["ticker"].astype(str),
                "date": pd.to_datetime(keys_df["date"]).dt.strftime("%Y-%m-%d"),
            })
            con.register("parity_keys", keys_for_join)

            def _resolve_columns(view: str) -> tuple[list[str], list[str]]:
                """Match catalog names to actual view columns (case-insensitive).

                Mirrors what train_mfe_classifier.validate_features does — views
                materialize columns as TitleCase (e.g. RS_Sector_Rank) from
                UPDATE statements while the catalog stores them lowercase.

                Returns (missing_names, select_terms) where select_terms is
                'actual_col AS catalog_name' so the output DF keys match the
                catalog ordering used downstream.
                """
                actual_cols = con.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = ?",
                    [view],
                ).fetchall()
                lookup = {c[0].lower(): c[0] for c in actual_cols}
                missing = []
                select_terms = []
                for name in feature_cols:
                    real = lookup.get(name.lower())
                    if real is None:
                        missing.append(name)
                    else:
                        select_terms.append(
                            f"{_quote_ident(real)} AS {_quote_ident(name)}"
                        )
                return missing, select_terms

            def _load_one_side(view: str) -> tuple[pd.DataFrame, int, list[str]]:
                """Return (deduped df, n_keys_with_multiple_rows, missing_cols) for view."""
                missing, select_terms = _resolve_columns(view)
                quoted_cols = ", ".join(select_terms)
                # Count multi-row keys (cheap — scoped by the JOIN).
                multi = con.execute(
                    f"""
                    SELECT COUNT(*) FROM (
                        SELECT v.ticker, v.date, COUNT(*) AS c
                        FROM {view} v
                        INNER JOIN parity_keys k
                          ON v.ticker = k.ticker
                         AND CAST(v.date AS VARCHAR) = k.date
                        GROUP BY v.ticker, v.date
                        HAVING COUNT(*) > 1
                    )
                    """
                ).fetchone()[0]
                # Pull one representative row per key.
                deduped = con.execute(
                    f"""
                    WITH ranked AS (
                        SELECT v.ticker, v.date, {quoted_cols},
                               ROW_NUMBER() OVER (PARTITION BY v.ticker, v.date ORDER BY v.ticker) AS rn
                        FROM {view} v
                        INNER JOIN parity_keys k
                          ON v.ticker = k.ticker
                         AND CAST(v.date AS VARCHAR) = k.date
                    )
                    SELECT ticker, date, {quoted_cols}
                    FROM ranked
                    WHERE rn = 1
                    """
                ).df()
                return deduped, int(multi), missing

            t_load = time.perf_counter()
            logger.info("feature_parity_check: loading train_view rows (%s)...",
                        effective_train_view)
            train_df, train_multi, train_missing = _load_one_side(effective_train_view)
            logger.info(
                "feature_parity_check: loaded train_view %d rows in %.1fs "
                "(multi_row_keys=%d missing_cols=%d)",
                len(train_df), time.perf_counter() - t_load, train_multi,
                len(train_missing),
            )
            t_load2 = time.perf_counter()
            logger.info("feature_parity_check: loading deploy_view rows...")
            deploy_df, deploy_multi, deploy_missing = _load_one_side(deploy_view)
            logger.info(
                "feature_parity_check: loaded deploy_view %d rows in %.1fs "
                "(multi_row_keys=%d missing_cols=%d)",
                len(deploy_df), time.perf_counter() - t_load2, deploy_multi,
                len(deploy_missing),
            )
        finally:
            con.close()

        logger.info("feature_parity_check: comparing %d features across %d keys...",
                    len(feature_cols), len(train_df))

        # Join on (ticker, date) to align rows. Use a string-date join key to
        # avoid timezone/dtype confusion.
        for df in (train_df, deploy_df):
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

        merged = train_df.merge(
            deploy_df, on=["ticker", "date"], suffixes=("__train", "__deploy"), how="inner"
        )

        mismatches: List[Dict[str, Any]] = []
        dtype_mismatches: List[Dict[str, Any]] = []

        train_missing_set = set(train_missing)
        deploy_missing_set = set(deploy_missing)

        for col in feature_cols:
            # A feature missing on either side is a real catalog-vs-view drift —
            # surface which side and skip further comparison.
            if col in train_missing_set or col in deploy_missing_set:
                dtype_mismatches.append({
                    "feature": col,
                    "kind": "missing_column",
                    "missing_in_train": col in train_missing_set,
                    "missing_in_deploy": col in deploy_missing_set,
                })
                continue

            tcol = f"{col}__train"
            dcol = f"{col}__deploy"
            if tcol not in merged.columns or dcol not in merged.columns:
                # Both sides resolved but merge dropped them — should not happen,
                # but record defensively.
                dtype_mismatches.append(
                    {"feature": col, "kind": "missing_column"}
                )
                continue

            t_series = merged[tcol]
            d_series = merged[dcol]

            if str(t_series.dtype) != str(d_series.dtype):
                dtype_mismatches.append(
                    {"feature": col, "train_dtype": str(t_series.dtype),
                     "deploy_dtype": str(d_series.dtype)}
                )

            # Numerical comparison — NaN considered equal to NaN.
            try:
                t_num = pd.to_numeric(t_series, errors="coerce")
                d_num = pd.to_numeric(d_series, errors="coerce")
            except Exception:
                t_num, d_num = None, None

            if t_num is not None and not (t_num.isna().all() and d_num.isna().all()):
                close = np.isclose(t_num.fillna(0).values, d_num.fillna(0).values, rtol=rtol, atol=rtol)
                both_nan = t_num.isna().values & d_num.isna().values
                ok = close | both_nan
                if not ok.all():
                    bad_idx = np.where(~ok)[0]
                    for i in bad_idx[:5]:  # cap noise
                        mismatches.append(
                            {
                                "ticker": merged.iloc[i]["ticker"],
                                "date": merged.iloc[i]["date"],
                                "feature": col,
                                "train_val": _to_py(t_series.iloc[i]),
                                "deploy_val": _to_py(d_series.iloc[i]),
                            }
                        )
            else:
                # Categorical / string comparison: exact equality, NaN==NaN.
                t_vals = t_series.where(t_series.notna(), other="__NA__").astype(str)
                d_vals = d_series.where(d_series.notna(), other="__NA__").astype(str)
                bad = t_vals.values != d_vals.values
                if bad.any():
                    bad_idx = np.where(bad)[0]
                    for i in bad_idx[:5]:
                        mismatches.append(
                            {
                                "ticker": merged.iloc[i]["ticker"],
                                "date": merged.iloc[i]["date"],
                                "feature": col,
                                "train_val": _to_py(t_series.iloc[i]),
                                "deploy_val": _to_py(d_series.iloc[i]),
                            }
                        )

        passed = not mismatches and not dtype_mismatches
        multi_row_warning = ""
        if train_multi or deploy_multi:
            multi_row_warning = (
                f" [warn: train_view has {train_multi} multi-row keys, "
                f"deploy_view has {deploy_multi}; deduped via ROW_NUMBER()=1 — "
                f"investigate if these views should be (ticker, date)-unique]"
            )
        gate = GateResult(
            name="feature_parity",
            status="pass" if passed else "fail",
            value=float(len(mismatches) + len(dtype_mismatches)),
            threshold=0.0,
            detail=(
                f"sampled={len(merged)} mismatches={len(mismatches)} "
                f"dtype_mismatches={len(dtype_mismatches)}"
                f"{multi_row_warning}"
            ),
            blocking=True,
        )

        logger.info(
            "feature_parity_check: done in %.1fs — passed=%s mismatches=%d "
            "dtype_mismatches=%d (train_multi=%d deploy_multi=%d)",
            time.perf_counter() - t0, passed, len(mismatches),
            len(dtype_mismatches), train_multi, deploy_multi,
        )

        return {
            "sampled_pairs": int(len(merged)),
            "matched": int(len(merged) - len(mismatches)),
            "mismatches": mismatches,
            "dtype_mismatches": dtype_mismatches,
            "train_multi_row_keys": int(train_multi),
            "deploy_multi_row_keys": int(deploy_multi),
            "passed": passed,
            "gate": gate.to_dict(),
        }


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------
def _labels_equal(a: Any, b: Any) -> bool:
    """Equality that survives numpy/pandas scalar wrappers and NaN-vs-NaN."""
    try:
        if pd.isna(a) and pd.isna(b):
            return True
    except (TypeError, ValueError):
        pass
    return _to_py(a) == _to_py(b)


def _to_py(value: Any) -> Any:
    """Coerce numpy/pandas scalars to vanilla python types for JSON output."""
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return value.item()
        except (ValueError, AttributeError):
            return value
    return value


def _quote_ident(name: str) -> str:
    """Quote an SQL identifier for DuckDB."""
    return '"' + name.replace('"', '""') + '"'
