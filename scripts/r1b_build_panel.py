"""R1b panel extract: trend_ok panel + MFE_63/MFE_126 labels + step-2 criteria.

Label logic replicates label_registry/m01a_tail_v1.json source_query exactly
(entry-day excluded, full forward window required), extended with a 126-bar
window for M3. Cached to data/research_cache/r1b/panel.parquet.
"""
import sys
import time
import duckdb
from pathlib import Path

SMOKE = "--smoke" in sys.argv
OUT = Path("data/research_cache/r1b/panel.parquet")
OUT.parent.mkdir(parents=True, exist_ok=True)

date_filter = "AND date >= '2015-01-01' AND date < '2016-01-01'" if SMOKE else ""

query = f"""
WITH panel AS (
  SELECT ticker, date
  FROM t3_sepa_features
  WHERE trend_ok
    AND RS_Universe_Rank IS NOT NULL
    AND ticker NOT IN ('LIF', 'CUE')
    {date_filter}
),
px AS (
  SELECT ticker, date, close,
    MAX(GREATEST(high, close)) OVER w63  AS fh63,
    COUNT(close) OVER w63  AS c63,
    MAX(GREATEST(high, close)) OVER w126 AS fh126,
    COUNT(close) OVER w126 AS c126
  FROM price_data
  WHERE ticker IN (SELECT DISTINCT ticker FROM panel)
  WINDOW
    w63  AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 1 FOLLOWING AND 63 FOLLOWING),
    w126 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 1 FOLLOWING AND 126 FOLLOWING)
),
lbl AS (
  SELECT p.ticker, p.date,
    x.fh63 / x.close - 1 AS mfe_63,
    GREATEST(x.fh63 / x.close - 1 - 0.30, 0) AS tail_mag_63,
    CAST(x.fh63 / x.close - 1 > 0.30 AS INT) AS home_run_63,
    CASE WHEN x.c126 = 126 THEN x.fh126 / x.close - 1 END AS mfe_126,
    CASE WHEN x.c126 = 126 THEN GREATEST(x.fh126 / x.close - 1 - 0.30, 0) END AS tail_mag_126,
    CASE WHEN x.c126 = 126 THEN CAST(x.fh126 / x.close - 1 > 0.30 AS INT) END AS home_run_126
  FROM panel p
  JOIN px x USING (ticker, date)
  WHERE x.c63 = 63 AND x.close > 0
)
SELECT lbl.*,
  f.rs_universe_rank,
  f.eps_growth_yoy, f.eps_accel, f.revenue_growth_yoy, f.revenue_accel,
  f.gross_margin_trend, f.days_since_report,
  f.sector, f.close AS px_close, f.shares_outstanding,
  cp.listing_date
FROM lbl
JOIN t3_training_cache f USING (ticker, date)
LEFT JOIN company_profiles cp USING (ticker)
"""

t0 = time.time()
con = duckdb.connect("data/market_data.duckdb", read_only=True)
print(f"Building R1b panel (smoke={SMOKE})...", flush=True)
df = con.execute(query).df()
df.columns = df.columns.str.lower()
print(f"Rows: {len(df):,}  ({time.time()-t0:.0f}s)", flush=True)
print(df[["mfe_63", "mfe_126", "rs_universe_rank", "eps_growth_yoy", "eps_accel"]].describe().T)
print("home_run_63 rate:", df["home_run_63"].mean().round(4),
      "| home_run_126 rate:", df["home_run_126"].mean().round(4))

if not SMOKE:
    df.to_parquet(OUT, index=False)
    print(f"Cached -> {OUT} ({OUT.stat().st_size/1e6:.0f} MB)")
