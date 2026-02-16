"""
Validate daily_features v3.0 after full recompute.
Fully schema-driven: all checks derive from the actual DuckDB table schema.

Checks:
  [1] Schema - column count and full listing
  [2] Table stats - row count, date range, ticker count
  [3] NULL rates - every column, for a sample ticker
  [4] Sample values - all columns for latest row of sample ticker
  [5] Feature parity - SQL vs Python for columns we can recompute
  [6] Cross-sectional features - rank columns range & distribution
"""
import sys
import re
from pathlib import Path
import pandas as pd
import numpy as np
import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from database_duckdb import DuckDBManager


# ---------------------------------------------------------------------------
# [1] Schema
# ---------------------------------------------------------------------------
def validate_schema(conn):
    cols = conn.execute("SELECT * FROM daily_features LIMIT 0").description
    col_names = [c[0] for c in cols]
    print("=" * 70)
    print(f"[1] SCHEMA  ({len(col_names)} columns)")
    print("=" * 70)
    for i, c in enumerate(col_names):
        print(f"  {i+1:3d}. {c}")
    return col_names


# ---------------------------------------------------------------------------
# [2] Table stats
# ---------------------------------------------------------------------------
def validate_stats(conn):
    print(f"\n{'=' * 70}")
    print("[2] TABLE STATISTICS")
    print("=" * 70)
    rc = conn.execute("SELECT COUNT(*) FROM daily_features").fetchone()[0]
    dr = conn.execute("SELECT MIN(date), MAX(date) FROM daily_features").fetchone()
    tc = conn.execute("SELECT COUNT(DISTINCT ticker) FROM daily_features").fetchone()[0]
    print(f"  Rows:     {rc:,}")
    print(f"  Dates:    {dr[0]}  to  {dr[1]}")
    print(f"  Tickers:  {tc:,}")
    return rc


# ---------------------------------------------------------------------------
# [3] NULL rates — every column
# ---------------------------------------------------------------------------
def validate_nulls(conn, col_names, ticker="AAPL", n=200):
    print(f"\n{'=' * 70}")
    print(f"[3] NULL RATE — ALL {len(col_names)} COLUMNS  ({ticker}, last {n} rows)")
    print("=" * 70)

    issues, ok = [], 0
    for c in col_names:
        try:
            nulls = conn.execute(f'''
                SELECT COUNT(*) - COUNT("{c}")
                FROM (SELECT "{c}" FROM daily_features
                      WHERE ticker='{ticker}' ORDER BY date DESC LIMIT {n})
            ''').fetchone()[0]
            if nulls == 0:
                tag = "OK"
                ok += 1
            elif nulls <= n * 0.3:
                tag = f"minor ({nulls}/{n} — rolling warmup)"
                ok += 1
            else:
                tag = f"WARN  ({nulls}/{n})"
                issues.append((c, nulls))
            print(f"  {c:40s} {nulls:3d}/{n}  [{tag}]")
        except Exception as e:
            print(f"  {c:40s} ERROR  {e}")
            issues.append((c, -1))

    print(f"\n  {ok} OK  |  {len(issues)} warnings  |  {len(col_names)} total")
    return issues


# ---------------------------------------------------------------------------
# [4] Sample values — all columns, latest row
# ---------------------------------------------------------------------------
def validate_sample_values(conn, col_names, ticker="AAPL"):
    print(f"\n{'=' * 70}")
    print(f"[4] SAMPLE VALUES  ({ticker}, latest date)")
    print("=" * 70)
    try:
        row = conn.execute(f"""
            SELECT * FROM daily_features
            WHERE ticker='{ticker}' ORDER BY date DESC LIMIT 1
        """).fetchdf()
        if row.empty:
            print("  No data")
            return
        # Transpose for readability
        for c in col_names:
            val = row[c].iloc[0] if c in row.columns else "N/A"
            print(f"  {c:40s} {val}")
    except Exception as e:
        print(f"  ERROR: {e}")


# ---------------------------------------------------------------------------
# [5] Feature parity — SQL vs Python
#     We compute Python equivalents from raw price_data for columns whose
#     names match known patterns, then compare numerically.
# ---------------------------------------------------------------------------
def _build_python_features(price_df):
    """
    Given a chronologically-sorted price DataFrame (date, open, high, low, close, volume),
    compute as many features as we can and return them keyed by the SQL column name.
    Returns dict[sql_col_name -> Series].
    """
    c = price_df["close"]
    h = price_df["high"]
    l = price_df["low"]
    v = price_df["volume"].astype(float)
    prev_c = c.shift(1)

    feats = {}

    # SMAs
    for w in [5, 10, 20, 50, 150, 200]:
        feats[f"sma_{w}"] = c.rolling(w).mean()

    # Price vs SMA  (normalised %)
    for w in [20, 50, 150, 200]:
        sma = c.rolling(w).mean()
        feats[f"price_vs_sma_{w}"] = (c / sma - 1) * 100

    # ATR
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    for w in [10, 14, 20, 50]:
        feats[f"atr_{w}"] = tr.rolling(w).mean()
    if "atr_14" in feats:
        feats["natr"] = feats["atr_14"] / c * 100

    # RSI 14 (SMA-based, matching SQL)
    delta = c.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_g = gain.rolling(14).mean()
    avg_l = loss.rolling(14).mean()
    rs = avg_g / avg_l.replace(0, np.nan)
    feats["rsi_14"] = 100 - (100 / (1 + rs))

    # Momentum
    for w in [5, 10, 20]:
        feats[f"momentum_{w}d"] = c.pct_change(w)

    # Volume ratio
    feats["volume_ratio"] = v / v.rolling(20).mean()

    # SMA slopes — SQL: ((sma50 - sma50_lag10) / sma50_lag10) / 10 * 100
    sma50 = c.rolling(50).mean()
    feats["sma_50_slope"] = ((sma50 - sma50.shift(10)) / sma50.shift(10).replace(0, np.nan)) / 10.0 * 100

    # Green day ratio (20d)
    feats["green_day_ratio"] = (c > prev_c).astype(float).rolling(20).mean()

    # Distance from 52w high — SQL: (close - high_52w) / high_52w  (ratio, not %)
    feats["dist_from_52w_high"] = (c - h.rolling(252).max()) / h.rolling(252).max()
    # Distance from 20d low — SQL: (close / lowest_low_20d) - 1  (ratio, not %)
    feats["dist_from_20d_low"] = c / l.rolling(20).min() - 1

    # Consolidation width — SQL: ((H20 - L20) / close) * 100
    feats["consolidation_width"] = (h.rolling(20).max() - l.rolling(20).min()) / c * 100

    # VCP ratio — SQL: atr_10 / atr_50  (ATR-based, not price-range)
    feats["vcp_ratio"] = feats["atr_10"] / feats["atr_50"].replace(0, np.nan)

    # Volume dry-up
    feats["volume_dry_up"] = v.rolling(5).mean() / v.rolling(20).mean().replace(0, np.nan)

    # Turnover (shares traded / avg — same idea as volume_ratio but 5d mean)
    feats["turnover_5d"] = v.rolling(5).mean()

    return feats


def validate_feature_parity(conn, col_names, ticker="AAPL"):
    print(f"\n{'=' * 70}")
    print(f"[5] FEATURE PARITY — SQL vs PYTHON  ({ticker})")
    print("=" * 70)

    # Grab raw price data (full history for rolling calcs)
    price_df = conn.execute(f"""
        SELECT date, open, high, low, close, volume
        FROM price_data WHERE ticker='{ticker}' ORDER BY date
    """).fetchdf()
    if price_df.empty:
        print(f"  No price data for {ticker}")
        return True

    py_feats = _build_python_features(price_df)

    # Grab SQL features (last 300 rows to have enough post-warmup data)
    quoted = ", ".join(f'"{c}"' for c in col_names)
    sql_df = conn.execute(f"""
        SELECT {quoted} FROM daily_features
        WHERE ticker='{ticker}' ORDER BY date DESC LIMIT 300
    """).fetchdf().sort_values("date").reset_index(drop=True)

    # Determine which columns we can compare
    comparable = sorted(set(col_names) & set(py_feats.keys()))
    if not comparable:
        print("  No overlapping computable columns found.")
        return True

    # Align on date
    py_df = price_df[["date"]].copy()
    for c in comparable:
        py_df[f"py_{c}"] = py_feats[c].values

    merged = sql_df.merge(py_df, on="date", how="inner")
    print(f"  Rows matched: {len(merged)}   |   Columns to compare: {len(comparable)}")

    # Tolerance map: default 0.01, wider for RSI / percentage features
    def _tolerance(col):
        if "rsi" in col:
            return 1.0  # SMA vs Wilder EMA can differ
        if "ratio" in col or "slope" in col or "momentum" in col:
            return 0.005
        return 0.02  # absolute tolerance for price-scale features

    all_pass = True
    for c in comparable:
        sql_s = merged[c]
        py_s = merged[f"py_{c}"]
        valid = sql_s.notna() & py_s.notna()
        n_valid = valid.sum()
        if n_valid == 0:
            print(f"  {c:35s}  SKIP (no overlapping non-null)")
            continue
        diff = (sql_s[valid] - py_s[valid]).abs()
        mx = diff.max()
        mn = diff.mean()
        tol = _tolerance(c)
        ok = mx <= tol
        tag = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"  {c:35s}  max={mx:10.6f}  mean={mn:10.6f}  tol={tol}  [{tag}]")

    print(f"\n  Overall: {'ALL PASS' if all_pass else 'SOME FAILURES — review above'}")
    return all_pass


# ---------------------------------------------------------------------------
# [6] Cross-sectional / rank columns
# ---------------------------------------------------------------------------
def validate_cross_sectional(conn, col_names):
    print(f"\n{'=' * 70}")
    print("[6] CROSS-SECTIONAL / RANK COLUMNS")
    print("=" * 70)

    # Auto-detect rank-like columns by name pattern
    rank_pattern = re.compile(r"(rank|sector|industry|universe)", re.I)
    rank_cols = [c for c in col_names if rank_pattern.search(c)]

    if not rank_cols:
        print("  No rank/sector/industry columns found.")
        return

    latest_date = conn.execute("SELECT MAX(date) FROM daily_features").fetchone()[0]
    print(f"  Latest date: {latest_date}")
    print(f"  Detected {len(rank_cols)} rank columns\n")

    for c in rank_cols:
        try:
            stats = conn.execute(f'''
                SELECT COUNT(*) as cnt,
                       COUNT("{c}") as non_null,
                       MIN("{c}") as mn,
                       MAX("{c}") as mx,
                       AVG("{c}") as avg
                FROM daily_features WHERE date = '{latest_date}'
            ''').fetchdf().iloc[0]
            print(f"  {c:35s}  {int(stats['non_null']):5d}/{int(stats['cnt'])} non-null  "
                  f"range=[{stats['mn']:.4f}, {stats['mx']:.4f}]  avg={stats['avg']:.4f}")
        except Exception as e:
            print(f"  {c:35s}  ERROR — {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 70)
    print("Daily Features v3.0 — Post-Recompute Validation")
    print("=" * 70)

    db = DuckDBManager()
    conn = duckdb.connect(db.db_path)
    print(f"  Database: {db.db_path}\n")

    try:
        col_names = validate_schema(conn)
        validate_stats(conn)
        null_issues = validate_nulls(conn, col_names, "AAPL", 200)
        validate_sample_values(conn, col_names, "AAPL")
        validate_feature_parity(conn, col_names, "AAPL")
        validate_cross_sectional(conn, col_names)

        # Summary
        print(f"\n{'=' * 70}")
        print("SUMMARY")
        print("=" * 70)
        print(f"  Schema columns : {len(col_names)}")
        if null_issues:
            print(f"  NULL warnings  : {[x[0] for x in null_issues]}")
        else:
            print(f"  NULL warnings  : none")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
