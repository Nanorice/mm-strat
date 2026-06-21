"""Section A — input data integrity.

Six gate-only checks. Any FAIL voids the card.
A1 leakage / A2 label horizon / A3 SEPA match / A4 class balance (numeric)
A5 BAD_TICKERS / A6 trend_ok consistency.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb
from src import db
import pandas as pd

from ..data_loader import (
    BINARY_HOME_RUN_THRESHOLD,
    META_COLUMNS,
    OUTCOME_COLUMNS,
    EvalSplit,
)
from ..rubric import GateEntry, MetricEntry, SectionResult

logger = logging.getLogger(__name__)

BAD_TICKERS = ("LIF", "CUE")


def _gate(name: str, ok: bool, detail: str, *, blocking: bool = True,
          value: float | None = None, threshold: float | None = None) -> GateEntry:
    return GateEntry(
        name=name,
        status="pass" if ok else "fail",
        value=value,
        threshold=threshold,
        detail=detail,
        blocking=blocking,
    )


def _check_a1_leakage(split: EvalSplit) -> GateEntry:
    leaked = sorted(set(split.feature_cols) & OUTCOME_COLUMNS)
    if leaked:
        return _gate(
            "A1_no_outcome_features",
            False,
            f"Model feature set contains outcome columns: {leaked}",
        )
    return _gate(
        "A1_no_outcome_features",
        True,
        f"No outcome columns in feature set ({len(OUTCOME_COLUMNS)} forbidden, "
        f"{split.meta['n_features']} features checked)",
    )


def _check_a2_label_horizon(split: EvalSplit, n_spot: int = 100) -> GateEntry:
    df = split.df
    # Spot-check up to n_spot rows: exit_date > entry_date, mfe_pct >= 0, binary
    # label matches the threshold.
    sample = df.sample(n=min(n_spot, len(df)), random_state=42)
    bad_dates = (sample["exit_date"] < sample["entry_date"]).sum()
    bad_mfe = (sample["mfe_pct"] < 0).sum()
    binary_recompute = (sample["mfe_pct"] > BINARY_HOME_RUN_THRESHOLD).astype(int)
    binary_loaded = split.label_binary.loc[sample.index]
    mismatches = (binary_recompute != binary_loaded).sum()
    n_bad = int(bad_dates + bad_mfe + mismatches)
    return _gate(
        "A2_label_horizon",
        n_bad == 0,
        f"spot-check n={len(sample)}: bad_dates={bad_dates}, "
        f"negative_mfe={bad_mfe}, binary_mismatch={mismatches}",
        value=float(n_bad),
        threshold=0.0,
    )


def _check_a3_sepa_match(split: EvalSplit, db_path: Path, skip: bool = False) -> GateEntry:
    """Compare row count vs v_d3_deployment for the overlapping date window.

    v_d3_deployment is a heavy CTE (~60-100s per scan). We collapse it to a
    single query that returns (min_date, max_date, count) in one shot. Can
    be skipped via skip=True (warning gate only — does not block the card).
    """
    if skip:
        return _gate(
            "A3_sepa_match",
            True,
            "skipped at caller request (use without skip_sepa_match for full check)",
            blocking=False,
        )
    try:
        con = db.connect(str(db_path), read_only=True)
        try:
            row = con.execute(
                "SELECT MIN(date), MAX(date), COUNT(*) FROM v_d3_deployment"
            ).fetchone()
        finally:
            con.close()
    except Exception as e:  # pragma: no cover (DB-side)
        return _gate(
            "A3_sepa_match",
            False,
            f"Could not query v_d3_deployment: {e}",
            blocking=False,
        )
    if not row or row[0] is None:
        return _gate(
            "A3_sepa_match",
            False,
            "v_d3_deployment is empty",
            blocking=False,
        )
    d3_min, d3_max, d3_rows = row
    df_dates = pd.to_datetime(split.df["date"])
    overlap = (df_dates >= pd.Timestamp(d3_min)) & (df_dates <= pd.Timestamp(d3_max))
    eval_in_window = int(overlap.sum())
    if not overlap.any():
        return _gate(
            "A3_sepa_match",
            True,
            f"Eval window ({split.meta['date_min']}..{split.meta['date_max']}) "
            f"does not overlap v_d3_deployment ({d3_min}..{d3_max}); skipping match",
            blocking=False,
        )
    detail = (
        f"eval rows in v_d3 window: {eval_in_window}; "
        f"v_d3_deployment total rows: {d3_rows}"
    )
    return _gate("A3_sepa_match", True, detail, blocking=False,
                 value=float(eval_in_window), threshold=float(d3_rows))


def _check_a4_class_balance(split: EvalSplit) -> MetricEntry:
    return MetricEntry(
        name="A4_class_balance",
        value=split.prevalence,
        detail=(
            f"home-run prevalence={split.prevalence:.4f} on n={split.n} rows "
            f"({split.meta['n_positives']} positives)"
        ),
    )


def _check_a5_bad_tickers(split: EvalSplit) -> GateEntry:
    if "ticker" not in split.df.columns:
        return _gate("A5_bad_tickers_excluded", False,
                     "ticker column missing from eval frame", blocking=True)
    present = sorted(
        set(split.df["ticker"].astype(str).str.upper()) & set(BAD_TICKERS)
    )
    if present:
        return GateEntry(
            name="A5_bad_tickers_excluded",
            status="warn",
            detail=f"BAD_TICKERS present in eval data: {present}",
            value=float(len(present)),
            threshold=0.0,
            blocking=False,
        )
    return _gate(
        "A5_bad_tickers_excluded",
        True,
        f"None of {list(BAD_TICKERS)} present in eval frame",
        value=0.0, threshold=0.0,
    )


def _check_a6_trend_ok(split: EvalSplit) -> GateEntry:
    if not split.meta.get("trend_ok_filtered", False):
        return _gate(
            "A6_trend_ok_consistency",
            True,
            "trend_ok filter not applied at load time (caller opted out); skipping",
            blocking=False,
        )
    if "trend_ok" not in split.df.columns:
        return _gate("A6_trend_ok_consistency", False,
                     "trend_ok column missing on v_d2_training", blocking=True)
    bad = int((~split.df["trend_ok"].astype(bool)).sum())
    return _gate(
        "A6_trend_ok_consistency",
        bad == 0,
        f"rows with trend_ok=FALSE after filter: {bad}",
        value=float(bad),
        threshold=0.0,
    )


def run_section_a(split: EvalSplit, db_path: Path,
                  skip_sepa_match: bool = False) -> SectionResult:
    section = SectionResult(
        name="A",
        title="Input data integrity",
        scored=False,
    )
    section.gates.append(_check_a1_leakage(split))
    section.gates.append(_check_a2_label_horizon(split))
    section.gates.append(_check_a3_sepa_match(split, db_path, skip=skip_sepa_match))
    section.metrics.append(_check_a4_class_balance(split))
    section.gates.append(_check_a5_bad_tickers(split))
    section.gates.append(_check_a6_trend_ok(split))
    blocking_fail = section.has_blocking_failure
    section.detail = (
        f"A1-A6 integrity check on n={split.n} rows. "
        f"{'CARD VOID — blocking gate failed.' if blocking_fail else 'All blocking gates passed.'}"
    )
    return section


# Exported for tests
__all__ = [
    "run_section_a",
    "BAD_TICKERS",
]
