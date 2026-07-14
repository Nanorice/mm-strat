"""Earnings-proximity overlay data — the {ticker -> earnings dates} calendar.

Minervini rule: never hold a binary earnings gap you can't stop out of. The
strategy uses this to (a) block NEW entries within N trading days *before* a
scheduled earnings date, and (b) force-trim held positions the same window out.

Source: the per-ticker FMP earnings parquets (config.EARNINGS_DIR / {T}.parquet),
`date` column = the earnings release date (deep history, e.g. AAPL back to 1985).
`is_future` is a cache-time flag and irrelevant here — a backtest only needs the
calendar of dates. Missing ticker / no nearby date => no blackout (fail-open), so
coverage gaps never fabricate a signal.
"""
from __future__ import annotations

import sys
from datetime import date as _date
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
import config


def load_earnings_calendar(
    tickers: Optional[List[str]] = None, earnings_dir: Optional[Path] = None
) -> Dict[str, np.ndarray]:
    """{ticker -> sorted np.array[datetime64[D]] of earnings dates}. Reads only the
    `date` column of each parquet. `tickers=None` loads every cached ticker (the
    backtest passes its feed universe to keep it small + picklable for workers)."""
    d = Path(earnings_dir) if earnings_dir else config.EARNINGS_DIR
    files = (
        [d / f"{t}.parquet" for t in tickers] if tickers is not None
        else list(d.glob("*.parquet"))
    )
    cal: Dict[str, np.ndarray] = {}
    for f in files:
        if not f.exists():
            continue
        try:
            s = pd.read_parquet(f, columns=["date"])["date"]
        except (KeyError, OSError, ValueError):
            continue
        dates = pd.to_datetime(s).dt.normalize().dropna().to_numpy().astype("datetime64[D]")
        dates = np.unique(dates)
        if len(dates):
            cal[f.stem] = dates
    return cal


def next_earnings_within(
    cal: Dict[str, np.ndarray], ticker: str, today: _date, n_days: int
) -> bool:
    """True if `ticker` has a scheduled earnings date in (today, today + n_days]
    calendar days. n_days is calendar days here (simpler + conservative; a 5-trading-
    day window ~ 7 calendar days — the arm picks the calendar figure). Fail-open:
    unknown ticker => False."""
    dates = cal.get(ticker)
    if dates is None or not len(dates):
        return False
    t = np.datetime64(today, "D")
    # first scheduled date strictly after today
    i = int(np.searchsorted(dates, t, side="right"))
    if i >= len(dates):
        return False
    return int((dates[i] - t).astype(int)) <= n_days


if __name__ == "__main__":
    # ponytail: self-check on real cached data — coverage + window logic.
    cal = load_earnings_calendar(["AAPL", "NVDA"])
    assert "AAPL" in cal and len(cal["AAPL"]) > 50, "AAPL earnings history missing"
    ds = cal["AAPL"]
    # A day 3 calendar days before a real earnings date must be inside a 5-day window.
    e = ds[len(ds) // 2].astype("datetime64[D]")
    three_before = (e - np.timedelta64(3, "D")).astype(_date)
    assert next_earnings_within(cal, "AAPL", three_before, 5), "window missed a near print"
    far = (e - np.timedelta64(40, "D")).astype(_date)
    assert not next_earnings_within(cal, "AAPL", far, 5), "window fired 40d out"
    assert not next_earnings_within(cal, "NOSUCHTICKER", three_before, 5), "fail-open broke"
    print(f"[OK] earnings calendar: {len(cal)} tickers, AAPL n={len(ds)}")
