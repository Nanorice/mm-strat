"""Shared population backtest runner — one arm end-to-end, parallel across arms.

Both run_strategy_array.py and run_strategy_confirm.py were re-implementing the
same setup->run->persist loop; the confirm variant additionally kept the
rejection audit and ran arms in parallel. This module owns that path so every
prod run persists the full artifact set (trades + **rejections** + equity +
metrics + config) and can fan out across arms.

Parallelism: BackTrader is sequential *within* an arm (event loop — the temporal
fidelity we want). Arms are independent, so we fan out ACROSS arms with a
ProcessPoolExecutor. DuckDB is read-only so concurrent price-feed reads are safe.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from src.backtest.runner import SEPABacktestRunner

logger = logging.getLogger(__name__)


@dataclass
class Job:
    """One arm: a named config + the scores it trades. `scores_df` may be None if
    `score_loader` is given (per-arm lazy load, for parallel workers that can't
    pickle a big shared frame)."""
    id: str
    description: str
    strategy_kwargs: Dict[str, Any]
    signal: str = ""
    model: str = ""
    scores_df: Optional[pd.DataFrame] = None
    score_loader: Optional[Callable[[], pd.DataFrame]] = None


def run_arm(job: Job, start: str, end: str, initial_cash: float, out_dir: Path,
            db_path: str) -> Dict[str, Any]:
    """Run one arm, persist every artifact, return the summary row.

    Artifacts (out_dir/<job.id>/): trades.parquet, rejections.parquet,
    equity.parquet, metrics.json, config.json. rejections = every candidate that
    qualified but did NOT enter (no_slots / skip_top / cooldown / …) — the "why
    we didn't enter" side of the audit.
    """
    scores_df = job.scores_df if job.scores_df is not None else job.score_loader()  # type: ignore
    run_dir = out_dir / job.id
    run_dir.mkdir(parents=True, exist_ok=True)

    runner = SEPABacktestRunner(start_date=start, end_date=end, initial_cash=initial_cash,
                                db_path=db_path, model_path=None, model_version_id=None)
    runner.setup(scores_df=scores_df, strategy_kwargs=job.strategy_kwargs)
    metrics = runner.run()
    equity = runner.get_equity_curve_dataframe()
    trades = runner.get_trade_dataframe()

    if isinstance(trades, pd.DataFrame) and not trades.empty:
        trades.to_parquet(run_dir / "trades.parquet", index=False)
    if isinstance(equity, pd.DataFrame) and not equity.empty:
        equity.reset_index().to_parquet(run_dir / "equity.parquet", index=False)

    # Rejection audit — raw per-candidate log, not just aggregate counts.
    # NB: bt.Strategy overrides __nonzero__ — test `is not None`, never truthiness.
    rejs = getattr(runner.strategy, "signal_rejections", []) if runner.strategy is not None else []
    if rejs:
        pd.DataFrame([{"date": r.date, "ticker": r.ticker, "score": r.score,
                       "reason": r.reason} for r in rejs]).to_parquet(
            run_dir / "rejections.parquet", index=False)

    metrics_flat = {k: v for k, v in metrics.items() if not isinstance(v, (dict, list))}
    (run_dir / "metrics.json").write_text(json.dumps(metrics_flat, indent=2, default=str))
    (run_dir / "config.json").write_text(json.dumps({
        "id": job.id, "description": job.description, "signal": job.signal,
        "model": job.model, "strategy_kwargs": job.strategy_kwargs,
    }, indent=2, default=str))

    return {
        "id": job.id, "description": job.description, "signal": job.signal, "model": job.model,
        "sharpe_ratio": metrics_flat.get("sharpe_ratio"),
        "total_return_pct": metrics_flat.get("total_return"),
        "max_drawdown_pct": metrics_flat.get("max_drawdown"),
        "win_rate_pct": metrics_flat.get("win_rate"),
        "total_trades": metrics_flat.get("total_trades"),
        "sqn": metrics_flat.get("sqn"),
        "n_rejections": len(rejs),
    }


def run_population(jobs: List[Job], start: str, end: str, initial_cash: float,
                   out_dir: Path, db_path: str, workers: int = 3) -> List[Dict[str, Any]]:
    """Run every job; serial if workers<=1, else fan out across arms."""
    out_dir.mkdir(parents=True, exist_ok=True)
    results: List[Dict[str, Any]] = []
    if workers <= 1:
        for job in jobs:
            logger.info("── running %s (%s)", job.id, job.description)
            results.append(run_arm(job, start, end, initial_cash, out_dir, db_path))
        return results

    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run_arm, j, start, end, initial_cash, out_dir, db_path): j for j in jobs}
        for fut in as_completed(futs):
            job = futs[fut]
            try:
                results.append(fut.result())
                logger.info("✅ done %s", job.id)
            except Exception as e:
                logger.exception("❌ arm %s failed: %s", job.id, e)
                results.append({"id": job.id, "signal": job.signal, "error": str(e)})
    return results
