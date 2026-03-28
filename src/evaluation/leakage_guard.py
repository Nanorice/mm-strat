"""Temporal Leakage Detection and Prevention.

Validates train/test splits to ensure no future data leaks into training.
Critical for time-series data where temporal ordering must be preserved.

Key validations:
- No test data appears before train data
- No overlap in date ranges
- Proper chronological ordering
"""

import logging
from typing import Dict, Tuple

import numpy as np
import pandas as pd

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
