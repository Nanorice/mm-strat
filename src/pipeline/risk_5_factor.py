"""
5-Factor Regime-Switching Risk Model — Production Implementation

Factors (all oriented: positive = more market risk):
  f_vix   (0.25): VIX spot level
  f_hy    (0.25): 20d change in HY OAS (WBAA - DGS10 spread)
  f_term  (0.15): Inverted term spread -(DGS10 - DGS2)
  f_trend (0.15): -(SPX / SMA200 - 1)
  f_slope (0.20): -(SMA200 / SMA200_20d - 1)

Normalization: 10-year (2555d) rolling z-score per factor.
Aggregation: weighted sum -> 5-year (1260d) rolling percentile -> exposure band.
Veto: any single z >= 2.0 forces target_exposure = 0.15.

Data sources (all from DuckDB):
  price_data  : ^GSPC or SPY for SPX price
  macro_data  : DGS10, DGS2, WBAA, VIX (via symbol column)
"""

import logging
import numpy as np
import pandas as pd
import duckdb
from src import db
from pathlib import Path
from typing import Optional

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
import config

logger = logging.getLogger(__name__)


# ── Constants (match prototype exactly) ──────────────────────────────────────

ROLLING_WINDOW_Z   = 2555   # 10yr — z-score normalization
ROLLING_WINDOW_PCT = 1260   # 5yr — percentile rank window

WEIGHTS = {
    "z_vix":   0.25,
    "z_hy":    0.25,
    "z_term":  0.15,
    "z_trend": 0.15,
    "z_slope": 0.20,
}

EXPOSURE_BANDS = [
    (0.00, 0.20, 1.00),
    (0.20, 0.40, 0.85),
    (0.40, 0.55, 0.75),
    (0.55, 0.70, 0.50),
    (0.70, 0.85, 0.35),
    (0.85, 1.00, 0.15),
]

VETO_THRESHOLD = 2.0
VETO_EXPOSURE  = 0.15

# SPX ticker stored in price_data (^ prefix preserved)
SPX_TICKER = "^GSPC"


class RiskFiveFactorCalculator:
    """
    5-Factor regime-switching risk model.

    Reads all inputs from DuckDB (macro_data + price_data).
    Writes scored output to t2_risk_scores table.

    Output per row:
      target_exposure  : 0.15–1.00 equity exposure (NaN during warmup)
      base_exposure    : exposure before veto overlay
      rolling_percentile: 0–1 rolling percentile of weighted_z
      weighted_z       : weighted aggregate z-score
      veto_flag        : True if any factor z >= 2.0
      z_vix/hy/term/trend/slope : individual z-scores
    """

    TABLE_DDL = """
        CREATE TABLE IF NOT EXISTS t2_risk_scores (
            date               DATE PRIMARY KEY,
            -- Raw inputs
            spx                DOUBLE,
            vix                DOUBLE,
            hy_oas             DOUBLE,
            dgs10              DOUBLE,
            dgs2               DOUBLE,
            -- Raw factors (positive = more risk)
            f_vix              DOUBLE,
            f_hy               DOUBLE,
            f_term             DOUBLE,
            f_trend            DOUBLE,
            f_slope            DOUBLE,
            -- Z-scores (2555d rolling)
            z_vix              DOUBLE,
            z_hy               DOUBLE,
            z_term             DOUBLE,
            z_trend            DOUBLE,
            z_slope            DOUBLE,
            -- Aggregated output
            weighted_z         DOUBLE,
            veto_flag          BOOLEAN,
            rolling_percentile DOUBLE,
            base_exposure      DOUBLE,
            target_exposure    DOUBLE,
            -- Metadata
            model_version      VARCHAR DEFAULT 'v1.0.0',
            updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or str(config.DUCKDB_PATH)

    # ── Data loading ──────────────────────────────────────────────────────────

    def _load_spx(self, con: duckdb.DuckDBPyConnection) -> pd.Series:
        """Load SPX close from price_data."""
        rows = con.execute(
            "SELECT date, close FROM price_data WHERE ticker = ? ORDER BY date",
            [SPX_TICKER]
        ).fetchall()
        if not rows:
            # Fallback: use SPY as proxy (very high correlation)
            logger.warning("^GSPC not in price_data, falling back to SPY")
            rows = con.execute(
                "SELECT date, close FROM price_data WHERE ticker = 'SPY' ORDER BY date"
            ).fetchall()
        if not rows:
            raise ValueError("Neither ^GSPC nor SPY found in price_data")
        s = pd.Series(
            {pd.Timestamp(r[0]): r[1] for r in rows},
            name="spx",
            dtype=float,
        )
        s.index.name = "date"
        return s

    def _load_macro_series(self, con: duckdb.DuckDBPyConnection, symbol: str) -> pd.Series:
        """Load a single symbol from macro_data.close column."""
        rows = con.execute(
            "SELECT date, close FROM macro_data WHERE symbol = ? ORDER BY date",
            [symbol]
        ).fetchall()
        if not rows:
            logger.warning(f"{symbol} not found in macro_data")
            return pd.Series(dtype=float, name=symbol)
        s = pd.Series(
            {pd.Timestamp(r[0]): r[1] for r in rows},
            name=symbol,
            dtype=float,
        )
        s.index.name = "date"
        return s

    def _load_inputs(self, con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
        """Load and align all 5 input series to SPX trading calendar."""
        spx   = self._load_spx(con)
        vix   = self._load_macro_series(con, "VIX")
        dgs10 = self._load_macro_series(con, "DGS10")
        dgs2  = self._load_macro_series(con, "DGS2")
        wbaa  = self._load_macro_series(con, "WBAA")

        spx_cal = spx.dropna().index

        # WBAA is weekly — ffill onto daily SPX calendar BEFORE computing spread
        # to avoid NaNs on non-Friday days after subtraction
        wbaa_daily  = wbaa.reindex(spx_cal).ffill()
        dgs10_daily = dgs10.reindex(spx_cal).ffill()
        hy_oas      = (wbaa_daily - dgs10_daily).rename("hy_oas")

        df = pd.concat([
            spx,
            vix.reindex(spx_cal).ffill().rename("vix"),
            hy_oas,
            dgs10_daily.rename("dgs10"),
            dgs2.reindex(spx_cal).ffill().rename("dgs2"),
        ], axis=1)
        df = df.loc[spx_cal].ffill().dropna(subset=["spx"])
        df.index.name = "date"
        return df

    # ── Factor engineering ────────────────────────────────────────────────────

    @staticmethod
    def _compute_raw_factors(df: pd.DataFrame) -> pd.DataFrame:
        """Compute 5 signed raw factors (positive = more risk)."""
        out = df.copy()
        out["f_vix"]  = out["vix"]
        out["f_hy"]   = out["hy_oas"] - out["hy_oas"].shift(20)
        out["f_term"] = -1.0 * (out["dgs10"] - out["dgs2"])
        sma200 = out["spx"].rolling(200, min_periods=200).mean()
        out["f_trend"] = -1.0 * (out["spx"] / sma200 - 1.0)
        out["f_slope"] = -1.0 * (sma200 / sma200.shift(20) - 1.0)
        return out

    @staticmethod
    def _rolling_zscore(series: pd.Series, window: int) -> pd.Series:
        roll = series.rolling(window, min_periods=window)
        return (series - roll.mean()) / roll.std(ddof=1)

    @staticmethod
    def _compute_zscores(df: pd.DataFrame) -> pd.DataFrame:
        factor_map = {
            "f_vix": "z_vix", "f_hy": "z_hy", "f_term": "z_term",
            "f_trend": "z_trend", "f_slope": "z_slope",
        }
        for raw, z in factor_map.items():
            df[z] = RiskFiveFactorCalculator._rolling_zscore(df[raw], ROLLING_WINDOW_Z)
        z_cols = list(factor_map.values())
        df["veto_flag"] = (df[z_cols] >= VETO_THRESHOLD).any(axis=1)
        return df

    @staticmethod
    def _rolling_percentile(series: pd.Series, window: int) -> pd.Series:
        """O(n*window) rolling percentile — ~15s for 9000 rows at window=1260."""
        arr = series.to_numpy(dtype=float)
        n = len(arr)
        result = np.full(n, np.nan)
        for i in range(window - 1, n):
            w = arr[i - window + 1: i + 1]
            if np.isnan(w).any():
                continue
            result[i] = (w < w[-1]).sum() / (window - 1)
        return pd.Series(result, index=series.index)

    @staticmethod
    def _map_band(percentile: float) -> float:
        for lo, hi, exposure in EXPOSURE_BANDS:
            if lo <= percentile < hi:
                return exposure
        return EXPOSURE_BANDS[-1][2]

    @staticmethod
    def _compute_aggregation(df: pd.DataFrame) -> pd.DataFrame:
        df["weighted_z"] = sum(df[col] * w for col, w in WEIGHTS.items())
        wz = df["weighted_z"].dropna()
        pct = RiskFiveFactorCalculator._rolling_percentile(wz, ROLLING_WINDOW_PCT)
        df["rolling_percentile"] = pct.reindex(df.index)
        df["base_exposure"] = df["rolling_percentile"].apply(
            lambda p: RiskFiveFactorCalculator._map_band(p) if pd.notna(p) else np.nan
        )
        df["target_exposure"] = np.where(
            df["veto_flag"] & df["base_exposure"].notna(),
            VETO_EXPOSURE,
            df["base_exposure"],
        )
        return df

    # ── Public API ────────────────────────────────────────────────────────────

    def compute_history(self, start_date: Optional[str] = None) -> pd.DataFrame:
        """
        Compute 5-factor scores for all available history.

        Args:
            start_date: If provided, return only rows >= this date (warmup still
                        uses all prior data for rolling windows).

        Returns:
            DataFrame indexed by date with all factor columns.
        """
        con = db.connect(self.db_path, read_only=True)
        try:
            logger.info("Loading 5-factor model inputs from DuckDB...")
            df = self._load_inputs(con)
        finally:
            con.close()

        logger.info(f"Loaded {len(df)} rows of input data ({df.index[0].date()} to {df.index[-1].date()})")

        logger.info("Computing raw factors...")
        df = self._compute_raw_factors(df)

        logger.info("Computing rolling z-scores (2555d)...")
        df = self._compute_zscores(df)

        logger.info("Computing weighted z and rolling percentile (1260d, may take ~20s)...")
        df = self._compute_aggregation(df)

        n_scored = df["target_exposure"].notna().sum()
        logger.info(f"Scored {n_scored} rows with target_exposure")

        if start_date is not None:
            df = df[df.index >= pd.Timestamp(start_date)]

        return df

    def get_latest_score(self) -> dict:
        """Return the most recent scored row as a dict."""
        df = self.compute_history()
        scored = df.dropna(subset=["target_exposure"])
        if scored.empty:
            return {}
        row = scored.iloc[-1]
        return {
            "date": row.name.date().isoformat(),
            "target_exposure": float(row["target_exposure"]),
            "base_exposure": float(row["base_exposure"]),
            "rolling_percentile": float(row["rolling_percentile"]),
            "weighted_z": float(row["weighted_z"]),
            "veto_flag": bool(row["veto_flag"]),
            "z_vix": float(row["z_vix"]) if pd.notna(row["z_vix"]) else None,
            "z_hy": float(row["z_hy"]) if pd.notna(row["z_hy"]) else None,
            "z_term": float(row["z_term"]) if pd.notna(row["z_term"]) else None,
            "z_trend": float(row["z_trend"]) if pd.notna(row["z_trend"]) else None,
            "z_slope": float(row["z_slope"]) if pd.notna(row["z_slope"]) else None,
        }

    # ── Persistence ───────────────────────────────────────────────────────────

    def _ensure_table(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute(self.TABLE_DDL)
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_t2_risk_date ON t2_risk_scores(date)"
        )

    def write_to_db(self, df: pd.DataFrame, mode: str = "replace") -> int:
        """
        Write scored DataFrame to t2_risk_scores.

        Args:
            df: Output of compute_history()
            mode: 'replace' (INSERT OR REPLACE) or 'ignore' (INSERT OR IGNORE)

        Returns:
            Number of rows written.
        """
        output_cols = [
            "spx", "vix", "hy_oas", "dgs10", "dgs2",
            "f_vix", "f_hy", "f_term", "f_trend", "f_slope",
            "z_vix", "z_hy", "z_term", "z_trend", "z_slope",
            "weighted_z", "veto_flag", "rolling_percentile",
            "base_exposure", "target_exposure",
        ]
        # Only write rows where at least target_exposure is present
        feed = df[output_cols].dropna(subset=["target_exposure"]).reset_index()
        feed = feed.rename(columns={"index": "date"})

        if feed.empty:
            logger.warning("No scored rows to write")
            return 0

        con = db.connect(self.db_path)
        try:
            self._ensure_table(con)
            before = con.execute("SELECT COUNT(*) FROM t2_risk_scores").fetchone()[0]
            con.register("risk_feed", feed)
            clause = "INSERT OR REPLACE" if mode == "replace" else "INSERT OR IGNORE"
            con.execute(f"""
                {clause} INTO t2_risk_scores (
                    date, spx, vix, hy_oas, dgs10, dgs2,
                    f_vix, f_hy, f_term, f_trend, f_slope,
                    z_vix, z_hy, z_term, z_trend, z_slope,
                    weighted_z, veto_flag, rolling_percentile,
                    base_exposure, target_exposure
                )
                SELECT
                    date, spx, vix, hy_oas, dgs10, dgs2,
                    f_vix, f_hy, f_term, f_trend, f_slope,
                    z_vix, z_hy, z_term, z_trend, z_slope,
                    weighted_z, veto_flag, rolling_percentile,
                    base_exposure, target_exposure
                FROM risk_feed
            """)
            after = con.execute("SELECT COUNT(*) FROM t2_risk_scores").fetchone()[0]
        finally:
            con.close()

        written = after - before
        logger.info(f"Written {written} rows to t2_risk_scores (total: {after})")
        return written

    def update_incremental(self) -> int:
        """
        Recompute and write only dates not yet scored.

        Because z-scores require the full history for correct normalization,
        we always run compute_history() on all data and filter to new dates.

        Returns:
            Number of new rows written.
        """
        con = db.connect(self.db_path)
        try:
            self._ensure_table(con)
            max_date = con.execute(
                "SELECT MAX(date) FROM t2_risk_scores WHERE target_exposure IS NOT NULL"
            ).fetchone()[0]
        finally:
            con.close()

        logger.info(f"Incremental update: last scored date = {max_date}")
        df = self.compute_history()
        scored = df.dropna(subset=["target_exposure"])

        if max_date is not None:
            new_rows = scored[scored.index > pd.Timestamp(max_date)]
        else:
            new_rows = scored

        if new_rows.empty:
            logger.info("No new rows to write")
            return 0

        return self.write_to_db(new_rows, mode="replace")

    def backfill(self, force: bool = False) -> int:
        """
        Compute full history and write to t2_risk_scores.

        Args:
            force: If True, overwrites existing rows (INSERT OR REPLACE)
        """
        logger.info("Backfilling t2_risk_scores...")
        df = self.compute_history()
        return self.write_to_db(df, mode="replace" if force else "ignore")
