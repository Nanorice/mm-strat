from datetime import date, timedelta
from pathlib import Path
from typing import List, Dict, Optional

import duckdb
from src import db
import pandas as pd

DEFAULT_DB_PATH = str(Path(__file__).resolve().parent.parent / "data" / "market_data.duckdb")

TREND_CRITERIA = [
    ("C1: close > sma_150", "close > sma_150"),
    ("C2: close > sma_200", "close > sma_200"),
    ("C3: sma_150 > sma_200", "sma_150 > sma_200"),
    ("C4: sma_200 rising", "sma_200 > sma_200_lag20"),
    ("C5: sma_50 > sma_150", "sma_50 > sma_150"),
    ("C6: close > sma_50", "close > sma_50"),
    ("C7: 30%+ above 52w low", "close > low_52w * 1.3"),
    ("C8: within 15% of 52w high", "close > high_52w * 0.85"),
    ("C9: RS vs SPY uptrend", "price_vs_spy > price_vs_spy_ma63"),
]

BREAKOUT_CRITERIA = [
    ("B1: new 20d high", "close > highest_high_20d"),
    ("B2: volume surge >1.3x", "vol_ratio > 1.3"),
]


class ScreenerDiagnostics:
    """Diagnose SEPA trend/breakout criteria for individual tickers."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return db.connect(self.db_path, read_only=True)

    def get_data_freshness(self, ticker: str) -> Dict:
        con = self._connect()
        try:
            t2_max = con.execute(
                f"SELECT MAX(date) FROM t2_screener_features WHERE ticker = '{ticker}'"
            ).fetchone()[0]
            price_max = con.execute(
                f"SELECT MAX(date) FROM price_data WHERE ticker = '{ticker}'"
            ).fetchone()[0]
            return {
                "t2_latest": t2_max,
                "price_latest": price_max,
                "lag_days": (price_max - t2_max).days if t2_max and price_max and price_max > t2_max else 0,
            }
        finally:
            con.close()

    def get_criteria_matrix(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        trend_cols = ",\n".join(
            f"        CASE WHEN {expr} THEN 'Y' ELSE '.' END AS \"{label}\""
            for label, expr in TREND_CRITERIA
        )
        breakout_cols = ",\n".join(
            f"        CASE WHEN {expr} THEN 'Y' ELSE '.' END AS \"{label}\""
            for label, expr in BREAKOUT_CRITERIA
        )
        sql = f"""
        SELECT
            date,
            ROUND(close, 2) AS close,
    {trend_cols},
            trend_ok,
    {breakout_cols},
            breakout_ok
        FROM t2_screener_features
        WHERE ticker = '{ticker}'
          AND date BETWEEN '{start}' AND '{end}'
        ORDER BY date
        """
        con = self._connect()
        try:
            return con.execute(sql).fetchdf()
        finally:
            con.close()

    def get_dashboard_trades(self, ticker: str, limit: int = 10) -> pd.DataFrame:
        sql = f"""
        SELECT status, entry_date, exit_date,
               ROUND(entry_price, 2) AS entry_price,
               ROUND(close_price, 2) AS exit_price,
               ROUND(pct_return, 2) AS pct_return,
               days_held
        FROM v_screener_dashboard
        WHERE ticker = '{ticker}'
        ORDER BY entry_date DESC
        LIMIT {limit}
        """
        con = self._connect()
        try:
            return con.execute(sql).fetchdf()
        finally:
            con.close()

    def find_transitions(self, criteria_df: pd.DataFrame) -> List[Dict]:
        transitions = []
        for i in range(1, len(criteria_df)):
            prev = criteria_df.iloc[i - 1]
            curr = criteria_df.iloc[i]

            if not prev["trend_ok"] and curr["trend_ok"]:
                transitions.append({"date": curr["date"], "event": "TREND ON"})
            elif prev["trend_ok"] and not curr["trend_ok"]:
                failed = [label for label, _ in TREND_CRITERIA if curr[label] == "."]
                transitions.append({
                    "date": curr["date"],
                    "event": "TREND OFF",
                    "failed": failed,
                })
            if not prev["breakout_ok"] and curr["breakout_ok"]:
                transitions.append({"date": curr["date"], "event": "BREAKOUT"})

        return transitions

    def diagnose(self, ticker: str, start: Optional[str] = None,
                 end: Optional[str] = None, days: int = 15) -> Dict:
        """Full diagnostic for a single ticker.

        Returns dict with keys: ticker, freshness, trades, criteria, transitions.
        """
        ticker = ticker.upper()
        end = end or date.today().isoformat()
        start = start or (date.fromisoformat(end) - timedelta(days=days)).isoformat()

        freshness = self.get_data_freshness(ticker)
        trades = self.get_dashboard_trades(ticker)
        criteria = self.get_criteria_matrix(ticker, start, end)
        transitions = self.find_transitions(criteria) if not criteria.empty else []

        return {
            "ticker": ticker,
            "start": start,
            "end": end,
            "freshness": freshness,
            "trades": trades,
            "criteria": criteria,
            "transitions": transitions,
        }

    def print_report(self, result: Dict) -> None:
        """Print a formatted diagnostic report to stdout."""
        ticker = result["ticker"]
        freshness = result["freshness"]

        print(f"\n🔍 Diagnosing: {ticker}")
        print(f"   Date range: {result['start']} -> {result['end']}")
        print(f"   t2 latest:  {freshness['t2_latest']}")
        print(f"   price latest: {freshness['price_latest']}")
        if freshness["lag_days"] > 0:
            print(f"   ⚠️  t2 features lag behind price data by {freshness['lag_days']} day(s)")

        print(f"\n📋 Recent trades (v_screener_dashboard):")
        trades = result["trades"]
        if trades.empty:
            print("   No trades found.")
        else:
            print(trades.to_string(index=False))

        print(f"\n📊 Criteria matrix (Y=pass, .=fail):")
        criteria = result["criteria"]
        if criteria.empty:
            print(f"   No t2_screener_features data for {ticker} in this range.")
            return
        print(criteria.to_string(index=False))

        transitions = result["transitions"]
        if transitions:
            print(f"\n🔄 State transitions:")
            for t in transitions:
                if t["event"] == "TREND OFF":
                    failed_str = ", ".join(t["failed"])
                    print(f"   {t['date']}  {t['event']}  <- failed: {failed_str}")
                else:
                    print(f"   {t['date']}  {t['event']}")
        else:
            print(f"\n   No trend/breakout transitions in this window.")
