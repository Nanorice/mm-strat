"""Phase 3 guard: the shared population runner persists the full artifact set
(incl. rejections — G4) and fans out across arms. Mocks the BackTrader runner so
this stays a fast unit test; the real multi-arm parallel run is an operator smoke.
"""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from src.backtest import population_runner as pr
from src.backtest.population_runner import Job, run_arm, run_population


class _FakeRunner:
    """Stand-in for SEPABacktestRunner — records setup, returns canned artifacts."""
    def __init__(self, **kw):
        self.strategy = SimpleNamespace(signal_rejections=[
            SimpleNamespace(date="2024-01-02", ticker="AAA", score=0.9, reason="no_slots"),
            SimpleNamespace(date="2024-01-03", ticker="BBB", score=0.8, reason="skip_top"),
        ])
    def setup(self, scores_df=None, strategy_kwargs=None):
        assert scores_df is not None  # score_loader/scores_df must resolve
    def run(self):
        return {"sharpe_ratio": 1.1, "total_return": 42.0, "max_drawdown": 30.0,
                "win_rate": 40.0, "total_trades": 12, "sqn": 2.0, "nested": {"x": 1}}
    def get_equity_curve_dataframe(self):
        return pd.DataFrame({"value": [1.0, 1.1]}, index=pd.to_datetime(["2024-01-02", "2024-01-03"]))
    def get_trade_dataframe(self):
        return pd.DataFrame({"holding_days": [5, 10], "pnl": [1.0, -0.5]})


@pytest.fixture(autouse=True)
def _patch_runner(monkeypatch):
    monkeypatch.setattr(pr, "SEPABacktestRunner", _FakeRunner)


def test_run_arm_persists_full_artifact_set(tmp_path):
    job = Job(id="A1", description="d", strategy_kwargs={"entry_top_n": 5},
              signal="binary", scores_df=pd.DataFrame({"date": [], "ticker": []}))
    summary = run_arm(job, "2024-01-01", "2024-12-31", 25_000.0, tmp_path, db_path="x")

    run_dir = tmp_path / "A1"
    for f in ("trades.parquet", "equity.parquet", "rejections.parquet",
              "metrics.json", "config.json"):
        assert (run_dir / f).exists(), f"missing {f}"
    # rejections captured (G4) and counted
    rej = pd.read_parquet(run_dir / "rejections.parquet")
    assert list(rej["reason"]) == ["no_slots", "skip_top"]
    assert summary["n_rejections"] == 2
    assert summary["sharpe_ratio"] == 1.1


def test_score_loader_resolves_in_worker(tmp_path):
    """A Job with no scores_df must lazy-load via score_loader."""
    called = {"n": 0}
    def _loader():
        called["n"] += 1
        return pd.DataFrame({"date": [], "ticker": []})
    job = Job(id="B1", description="d", strategy_kwargs={}, score_loader=_loader)
    run_arm(job, "2024-01-01", "2024-12-31", 25_000.0, tmp_path, db_path="x")
    assert called["n"] == 1


def test_run_population_serial(tmp_path):
    jobs = [Job(id=f"S{i}", description="d", strategy_kwargs={},
                scores_df=pd.DataFrame({"date": [], "ticker": []})) for i in range(3)]
    results = run_population(jobs, "2024-01-01", "2024-12-31", 25_000.0,
                             tmp_path, db_path="x", workers=1)
    assert len(results) == 3 and {r["id"] for r in results} == {"S0", "S1", "S2"}
