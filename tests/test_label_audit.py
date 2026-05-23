"""Tests for LeakageGuard.audit_label (§2.1.2)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from src.evaluation.label_registry import LabelDefinition
from src.evaluation.leakage_guard import LeakageGuard


def _make_label_def(horizon: int = 30) -> LabelDefinition:
    return LabelDefinition(
        label_id=f"mfe_test_h{horizon}",
        description="test label",
        target_col="mfe_max_pct",
        horizon_days=horizon,
        exit_rule="end of horizon",
        source_query="N/A",
        git_sha="test",
        generated_at="2026-05-23T00:00:00",
        bins=None,
    )


@pytest.fixture()
def synth_db(tmp_path: Path) -> Path:
    db = tmp_path / "audit.duckdb"
    con = duckdb.connect(str(db))
    con.execute(
        """
        CREATE TABLE price_data (
            ticker VARCHAR,
            date DATE,
            close DOUBLE
        )
        """
    )

    rng = np.random.default_rng(0)
    tickers = [f"T{i}" for i in range(10)]
    rows = []
    for tk in tickers:
        # 90 calendar days of trading-ish bars (drop weekends)
        all_dates = pd.bdate_range("2024-01-02", periods=90)
        close = 100 + np.cumsum(rng.normal(0, 1, len(all_dates)))
        for d, c in zip(all_dates, close):
            rows.append((tk, d.date(), float(c)))
    con.executemany("INSERT INTO price_data VALUES (?, ?, ?)", rows)
    con.close()
    return db


def _recompute_max_close(window_df: pd.DataFrame, label_def: LabelDefinition) -> float:
    """Reference implementation: max close in window, rounded."""
    if window_df.empty:
        return float("nan")
    return float(round(window_df["close"].max(), 4))


def test_audit_passes_when_labels_match_horizon(synth_db: Path):
    """Labels derived from within-horizon prices pass the audit."""
    con = duckdb.connect(str(synth_db), read_only=True)
    prices = con.execute("SELECT * FROM price_data ORDER BY ticker, date").df()
    con.close()
    prices["date"] = pd.to_datetime(prices["date"])

    label_def = _make_label_def(horizon=30)
    # For each (ticker, date) build a label using the in-horizon window only.
    labels = []
    for tk, group in prices.groupby("ticker"):
        group = group.sort_values("date").reset_index(drop=True)
        for i in range(len(group) - 30):
            label_date = pd.Timestamp(group.iloc[i]["date"])
            cutoff = label_date + pd.Timedelta(days=30)
            window = group[(group["date"] > label_date) & (group["date"] <= cutoff)]
            labels.append(
                {
                    "ticker": tk,
                    "date": label_date.date(),
                    "mfe_max_pct": round(float(window["close"].max()), 4),
                }
            )
            if len(labels) >= 20:
                break
        if len(labels) >= 20:
            break

    labels_df = pd.DataFrame(labels)
    result = LeakageGuard.audit_label(
        labels_df=labels_df,
        price_data_view="price_data",
        label_def=label_def,
        db_path=synth_db,
        recompute_fn=_recompute_max_close,
    )

    assert result["passed"] is True
    assert result["horizon_violations"] == []
    assert result["checked_n"] == len(labels_df)
    assert result["gate"]["status"] == "pass"


def test_audit_flags_horizon_overrun(synth_db: Path):
    """A label whose true value comes from bar t+45 (when horizon=30) is flagged."""
    con = duckdb.connect(str(synth_db), read_only=True)
    prices = con.execute("SELECT * FROM price_data ORDER BY ticker, date").df()
    con.close()
    prices["date"] = pd.to_datetime(prices["date"])

    label_def = _make_label_def(horizon=30)
    rows = []
    for tk, group in prices.groupby("ticker"):
        group = group.sort_values("date").reset_index(drop=True)
        if len(group) < 60:
            continue
        label_date = pd.Timestamp(group.iloc[0]["date"])
        wide_cutoff = label_date + pd.Timedelta(days=60)
        wide = group[(group["date"] > label_date) & (group["date"] <= wide_cutoff)]
        in_horizon_cutoff = label_date + pd.Timedelta(days=30)
        in_horizon = wide[wide["date"] <= in_horizon_cutoff]
        beyond = wide[wide["date"] > in_horizon_cutoff]
        if beyond.empty or in_horizon.empty:
            continue
        # Build a label that only the wide window can reproduce.
        wide_max = round(float(wide["close"].max()), 4)
        in_max = round(float(in_horizon["close"].max()), 4)
        if wide_max == in_max:
            # Need a case where max is only in the beyond-horizon segment.
            continue
        rows.append({"ticker": tk, "date": label_date.date(), "mfe_max_pct": wide_max})

    assert rows, "fixture failed to build a leaky label — adjust seed/window"
    labels_df = pd.DataFrame(rows)
    result = LeakageGuard.audit_label(
        labels_df=labels_df,
        price_data_view="price_data",
        label_def=label_def,
        db_path=synth_db,
        recompute_fn=_recompute_max_close,
    )

    assert result["passed"] is False
    assert result["gate"]["status"] == "fail"
    assert any(v.get("kind") in ("horizon_overrun", "value_mismatch") for v in result["horizon_violations"])


def test_audit_flags_missing_prices(synth_db: Path):
    """A label whose ticker has no price data shows up in missing_price_rows."""
    label_def = _make_label_def(horizon=30)
    labels_df = pd.DataFrame(
        [
            {"ticker": "NONEXIST", "date": pd.Timestamp("2024-01-15").date(), "mfe_max_pct": 1.0},
        ]
    )
    result = LeakageGuard.audit_label(
        labels_df=labels_df,
        price_data_view="price_data",
        label_def=label_def,
        db_path=synth_db,
    )
    assert result["passed"] is False
    assert len(result["missing_price_rows"]) == 1
    assert result["missing_price_rows"][0]["ticker"] == "NONEXIST"


def test_audit_raises_on_missing_columns(synth_db: Path):
    label_def = _make_label_def(horizon=30)
    bad = pd.DataFrame([{"ticker": "T0", "date": pd.Timestamp("2024-01-15").date()}])
    with pytest.raises(ValueError, match="missing required columns"):
        LeakageGuard.audit_label(
            labels_df=bad,
            price_data_view="price_data",
            label_def=label_def,
            db_path=synth_db,
        )
