"""
Compare old d1_trades.parquet vs current v_d1_candidates view.
Identifies entry/exit date mismatches, missing trades, and diagnoses root causes
down to individual C1-C9 criteria failures.

Key difference found during investigation:
  - Old pipeline C9: rs_rating > 0 (momentum-based: 0.4*3m + 0.2*6m + 0.2*9m + 0.2*12m)
  - Current pipeline C9: price_vs_spy > price_vs_spy_ma63 (price/SPY ratio above 63d MA)
"""
import pandas as pd
import duckdb
from pathlib import Path

DB_PATH = Path("data/market_data.duckdb")
OLD_PARQUET = Path("data/ml/d1_trades.parquet")

# Current SQL trend_ok criteria (from feature_pipeline.py:406-412)
CRITERIA_LABELS = {
    "C1": "close > sma_150",
    "C2": "close > sma_200",
    "C3": "sma_150 > sma_200",
    "C4": "sma_200 > sma_200_lag20 (200 SMA trending up)",
    "C5": "sma_50 > sma_150",
    "C6": "close > sma_50",
    "C7": "close > low_52w * 1.3 (30% above 52w low)",
    "C8": "close > high_52w * 0.85 (within 15% of 52w high)",
    "C9_new": "price_vs_spy > price_vs_spy_ma63 (RS line uptrend — CURRENT)",
    "C9_old": "rs_rating > 0 (momentum RS — OLD pipeline)",
    "C10": "breakout (close > 20d high)",
    "C11": "volume / vol_avg_50 > 1.3 (volume spike)",
}

# SQL to evaluate each criterion individually at a specific (ticker, date)
CRITERIA_SQL = """
    SELECT
        t2.ticker,
        t2.date,
        t2.close,
        t2.sma_50,
        t2.sma_150,
        t2.sma_200,
        t2.sma_200_lag20,
        t2.high_52w,
        t2.low_52w,
        t2.price_vs_spy,
        t2.price_vs_spy_ma63,
        t2.rs_rating,
        t2.vol_ratio,
        t2.trend_ok,
        t2.breakout_ok,

        -- Individual criteria evaluation
        (t2.close > t2.sma_150)::BOOLEAN                       AS c1_pass,
        (t2.close > t2.sma_200)::BOOLEAN                       AS c2_pass,
        (t2.sma_150 > t2.sma_200)::BOOLEAN                     AS c3_pass,
        (t2.sma_200 > t2.sma_200_lag20)::BOOLEAN               AS c4_pass,
        (t2.sma_50 > t2.sma_150)::BOOLEAN                      AS c5_pass,
        (t2.close > t2.sma_50)::BOOLEAN                         AS c6_pass,
        (t2.close > t2.low_52w * 1.3)::BOOLEAN                 AS c7_pass,
        (t2.close > t2.high_52w * 0.85)::BOOLEAN               AS c8_pass,
        (t2.price_vs_spy > t2.price_vs_spy_ma63)::BOOLEAN      AS c9_new_pass,
        (COALESCE(t2.rs_rating, 0) > 0)::BOOLEAN               AS c9_old_pass,
        t2.breakout_ok                                          AS c10_c11_pass

    FROM t2_screener_features t2
    WHERE t2.ticker = ? AND t2.date = ?
"""

# Batch SQL: check criteria over a date window
CRITERIA_WINDOW_SQL = """
    SELECT
        t2.date,
        t2.close,
        t2.trend_ok,
        t2.breakout_ok,
        (t2.close > t2.sma_150)::BOOLEAN                       AS c1,
        (t2.close > t2.sma_200)::BOOLEAN                       AS c2,
        (t2.sma_150 > t2.sma_200)::BOOLEAN                     AS c3,
        (t2.sma_200 > t2.sma_200_lag20)::BOOLEAN               AS c4,
        (t2.sma_50 > t2.sma_150)::BOOLEAN                      AS c5,
        (t2.close > t2.sma_50)::BOOLEAN                         AS c6,
        (t2.close > t2.low_52w * 1.3)::BOOLEAN                 AS c7,
        (t2.close > t2.high_52w * 0.85)::BOOLEAN               AS c8,
        (t2.price_vs_spy > t2.price_vs_spy_ma63)::BOOLEAN      AS c9_new,
        (COALESCE(t2.rs_rating, 0) > 0)::BOOLEAN               AS c9_old,
        t2.price_vs_spy,
        t2.price_vs_spy_ma63,
        t2.rs_rating
    FROM t2_screener_features t2
    WHERE t2.ticker = ? AND t2.date BETWEEN ? - INTERVAL 5 DAY AND ? + INTERVAL 5 DAY
    ORDER BY t2.date
"""


def load_old_trades() -> pd.DataFrame:
    df = pd.read_parquet(OLD_PARQUET)
    df = df.rename(columns={
        "date": "entry_date",
        "days_held": "holding_days",
        "max_favorable_excursion_pct": "mfe_pct",
        "max_drawdown_pct": "mae_pct",
    })
    df["entry_date"] = pd.to_datetime(df["entry_date"]).dt.date
    df["exit_date"] = pd.to_datetime(df["exit_date"]).dt.date
    df["trade_id"] = df["ticker"] + "_" + pd.to_datetime(df["entry_date"]).dt.strftime("%Y%m%d")
    return df[["trade_id", "ticker", "entry_date", "exit_date", "entry_price",
               "exit_price", "return_pct", "holding_days", "mfe_pct", "mae_pct"]]


def load_current_trades(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute("""
        SELECT trade_id, ticker, entry_date, exit_date, entry_price, exit_price,
               (exit_price / entry_price - 1) * 100 AS return_pct
        FROM v_d1_candidates
    """).fetchdf()


def diagnose_criteria(con: duckdb.DuckDBPyConnection, ticker: str, entry_date) -> dict:
    """Evaluate each C1-C9 criterion at the exact entry date. Returns structured diagnosis."""
    result = {
        "in_t2": False,
        "in_price_data": False,
        "is_active": None,
        "screener_active": None,
        "in_t3": False,
        "criteria": {},
        "values": {},
        "failing_criteria": [],
        "would_pass_old_c9": False,
    }

    # Check price_data existence
    r = con.execute("SELECT close FROM price_data WHERE ticker = ? AND date = ?",
                     [ticker, entry_date]).fetchdf()
    if len(r) > 0:
        result["in_price_data"] = True
        result["values"]["entry_close"] = r["close"].iloc[0]

    # Check company_profiles
    r = con.execute("SELECT is_active FROM company_profiles WHERE ticker = ?", [ticker]).fetchdf()
    if len(r) > 0:
        result["is_active"] = bool(r["is_active"].iloc[0])

    # Check screener_membership status at entry
    r = con.execute("""
        SELECT is_active, effective_date
        FROM screener_membership
        WHERE ticker = ? AND effective_date <= ?
        ORDER BY effective_date DESC LIMIT 1
    """, [ticker, entry_date]).fetchdf()
    if len(r) > 0:
        result["screener_active"] = bool(r["is_active"].iloc[0])

    # Check t3_sepa_features
    r = con.execute("SELECT COUNT(*) FROM t3_sepa_features WHERE ticker = ? AND date = ?",
                     [ticker, entry_date]).fetchdf()
    result["in_t3"] = r.iloc[0, 0] > 0

    # Evaluate individual criteria at entry date
    r = con.execute(CRITERIA_SQL, [ticker, entry_date]).fetchdf()
    if len(r) == 0:
        # Try nearby dates (±5 days) to see if ticker is in t2 at all
        r_window = con.execute("""
            SELECT COUNT(*) as cnt FROM t2_screener_features
            WHERE ticker = ? AND date BETWEEN ? - INTERVAL 30 DAY AND ? + INTERVAL 30 DAY
        """, [ticker, entry_date, entry_date]).fetchone()[0]
        result["in_t2"] = False
        result["t2_nearby_count"] = r_window
        return result

    result["in_t2"] = True
    row = r.iloc[0]

    criteria_checks = {
        "C1": row.get("c1_pass"),
        "C2": row.get("c2_pass"),
        "C3": row.get("c3_pass"),
        "C4": row.get("c4_pass"),
        "C5": row.get("c5_pass"),
        "C6": row.get("c6_pass"),
        "C7": row.get("c7_pass"),
        "C8": row.get("c8_pass"),
        "C9_new": row.get("c9_new_pass"),
        "C9_old": row.get("c9_old_pass"),
        "C10_C11": row.get("c10_c11_pass"),
    }
    result["criteria"] = {k: bool(v) if pd.notna(v) else None for k, v in criteria_checks.items()}

    # Key values for debugging
    result["values"].update({
        "close": row.get("close"),
        "sma_50": row.get("sma_50"),
        "sma_150": row.get("sma_150"),
        "sma_200": row.get("sma_200"),
        "sma_200_lag20": row.get("sma_200_lag20"),
        "high_52w": row.get("high_52w"),
        "low_52w": row.get("low_52w"),
        "price_vs_spy": row.get("price_vs_spy"),
        "price_vs_spy_ma63": row.get("price_vs_spy_ma63"),
        "rs_rating": row.get("rs_rating"),
        "vol_ratio": row.get("vol_ratio"),
        "trend_ok": bool(row.get("trend_ok")) if pd.notna(row.get("trend_ok")) else None,
        "breakout_ok": bool(row.get("breakout_ok")) if pd.notna(row.get("breakout_ok")) else None,
    })

    # Identify failing criteria
    for crit, passed in result["criteria"].items():
        if passed is False:
            result["failing_criteria"].append(crit)

    # Would the trade pass under the OLD C9 rule?
    trend_c1_c8 = all(result["criteria"].get(f"C{i}") is True for i in range(1, 9))
    result["would_pass_old_c9"] = trend_c1_c8 and result["criteria"].get("C9_old") is True

    return result


def format_diagnosis_short(diag: dict) -> str:
    """One-line summary of what's failing."""
    parts = []

    if not diag["in_price_data"]:
        return "NO_PRICE_DATA"
    if diag["is_active"] is False:
        parts.append("DELISTED")
    if not diag["in_t2"]:
        nearby = diag.get("t2_nearby_count", 0)
        parts.append(f"NOT_IN_T2 (nearby={nearby})")
        return " | ".join(parts)

    failing = diag["failing_criteria"]
    if failing:
        # Group failures
        labels = []
        for c in failing:
            if c in CRITERIA_LABELS:
                labels.append(f"{c}: {CRITERIA_LABELS[c]}")
            else:
                labels.append(c)
        parts.append("FAIL: " + ", ".join(c for c in failing))

        # Flag C9 divergence specifically
        if "C9_new" in failing and "C9_old" not in failing:
            parts.append("C9_DIVERGENCE (old=PASS, new=FAIL)")
        elif "C9_old" in failing and "C9_new" not in failing:
            parts.append("C9_DIVERGENCE (old=FAIL, new=PASS)")
    else:
        parts.append("ALL_CRITERIA_PASS — session logic mismatch?")

    if diag.get("screener_active") is False:
        parts.append("SCREENER_INACTIVE")

    return " | ".join(parts)


def format_diagnosis_detail(diag: dict, ticker: str) -> str:
    """Multi-line detailed diagnosis for a single trade."""
    lines = [f"  Ticker: {ticker}"]

    v = diag["values"]
    lines.append(f"  Close: ${v.get('close', '?'):.2f}" if v.get('close') else "  Close: N/A")
    lines.append(f"  is_active={diag['is_active']}, screener_active={diag['screener_active']}, in_t3={diag['in_t3']}")

    if not diag["in_t2"]:
        lines.append(f"  NOT IN t2_screener_features (nearby rows: {diag.get('t2_nearby_count', 0)})")
        return "\n".join(lines)

    lines.append(f"  trend_ok={v.get('trend_ok')}, breakout_ok={v.get('breakout_ok')}")

    # Criteria table
    lines.append("  Criteria breakdown:")
    for crit in ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9_new", "C9_old", "C10_C11"]:
        passed = diag["criteria"].get(crit)
        status = "PASS" if passed else ("FAIL" if passed is False else "NULL")
        marker = "  " if passed else "**"
        label = CRITERIA_LABELS.get(crit, crit)
        lines.append(f"    {marker}{crit:8s} {status:4s}  {label}")

    # RS comparison
    rs_rating = v.get("rs_rating")
    pvs = v.get("price_vs_spy")
    pvs_ma = v.get("price_vs_spy_ma63")
    lines.append(f"  RS comparison:")
    lines.append(f"    rs_rating (momentum):     {rs_rating:.4f}" if rs_rating is not None else "    rs_rating: NULL")
    lines.append(f"    price_vs_spy:             {pvs:.6f}" if pvs is not None else "    price_vs_spy: NULL")
    lines.append(f"    price_vs_spy_ma63:        {pvs_ma:.6f}" if pvs_ma is not None else "    price_vs_spy_ma63: NULL")

    if diag["would_pass_old_c9"] and "C9_new" in diag["failing_criteria"]:
        lines.append("    >>> WOULD HAVE PASSED under old rs_rating > 0 rule <<<")

    return "\n".join(lines)


def main():
    old = load_old_trades()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    current = load_current_trades(con)

    print("=" * 100)
    print("D1 TRADES COMPARISON: Old Pipeline vs Current v_d1_candidates")
    print("=" * 100)

    print("\nKNOWN DIFFERENCES:")
    print("  C9 (old): rs_rating > 0  (momentum: 0.4*3m + 0.2*6m + 0.2*9m + 0.2*12m)")
    print("  C9 (new): price_vs_spy > price_vs_spy_ma63  (price/SPY ratio above 63d MA)")

    # Normalize current dates to datetime.date
    for col in ["entry_date", "exit_date"]:
        if hasattr(current[col].dtype, "tz") or str(current[col].dtype).startswith("datetime"):
            current[col] = pd.to_datetime(current[col]).dt.date

    # Date range overlap
    old_min, old_max = old["entry_date"].min(), old["entry_date"].max()
    cur_min, cur_max = current["entry_date"].min(), current["entry_date"].max()
    overlap_start = max(old_min, cur_min)
    overlap_end = min(old_max, cur_max)

    print(f"\nOld pipeline:     {old_min} to {old_max} ({len(old):,} trades, {old['ticker'].nunique()} tickers)")
    print(f"Current view:     {cur_min} to {cur_max} ({len(current):,} trades, {current['ticker'].nunique()} tickers)")
    print(f"Overlap period:   {overlap_start} to {overlap_end}")

    # Filter to overlap
    old_overlap = old[(old["entry_date"] >= overlap_start) & (old["entry_date"] <= overlap_end)].copy()
    cur_overlap = current[(current["entry_date"] >= overlap_start) & (current["entry_date"] <= overlap_end)].copy()

    print(f"\nIn overlap period: Old={len(old_overlap):,}, Current={len(cur_overlap):,}")

    # --- MATCHING ---
    old_ids = set(old_overlap["trade_id"])
    cur_ids = set(cur_overlap["trade_id"])
    matched_ids = old_ids & cur_ids
    only_old = old_ids - cur_ids
    only_current = cur_ids - old_ids

    print(f"\n{'='*100}")
    print("TRADE ID MATCH SUMMARY")
    print(f"{'='*100}")
    print(f"  Matched:          {len(matched_ids):,}")
    print(f"  Only in old:      {len(only_old):,}")
    print(f"  Only in current:  {len(only_current):,}")

    # --- MATCHED: Entry/Exit comparison ---
    print(f"\n{'='*100}")
    print("MATCHED TRADES — Entry/Exit Comparison")
    print(f"{'='*100}")

    old_matched = old_overlap[old_overlap["trade_id"].isin(matched_ids)].set_index("trade_id")
    cur_matched = cur_overlap[cur_overlap["trade_id"].isin(matched_ids)]
    cur_matched = cur_matched.drop_duplicates(subset="trade_id").set_index("trade_id")
    merged = old_matched.join(cur_matched, lsuffix="_old", rsuffix="_new", how="inner")

    # Normalize dates for comparison
    for col in ["entry_date_old", "entry_date_new", "exit_date_old", "exit_date_new"]:
        merged[col] = pd.to_datetime(merged[col]).dt.date

    merged["entry_match"] = merged["entry_date_old"] == merged["entry_date_new"]
    merged["exit_match"] = merged["exit_date_old"] == merged["exit_date_new"]
    merged["exit_delta_days"] = (
        pd.to_datetime(merged["exit_date_new"]) - pd.to_datetime(merged["exit_date_old"])
    ).dt.days
    merged["price_diff_pct"] = (
        (merged["entry_price_new"] - merged["entry_price_old"]) / merged["entry_price_old"] * 100
    )

    print(f"\nEntry dates match: {merged['entry_match'].sum()}/{len(merged)}")
    print(f"Exit dates match:  {merged['exit_match'].sum()}/{len(merged)}")

    mismatched_exits = merged[~merged["exit_match"]].sort_values("exit_delta_days", key=abs, ascending=False)
    if len(mismatched_exits) > 0:
        print(f"\n[INFO] Exit Date Mismatches ({len(mismatched_exits)} trades):")
        print(f"  Mean delta: {mismatched_exits['exit_delta_days'].mean():.1f} days")
        print(f"  Median:     {mismatched_exits['exit_delta_days'].median():.1f} days")
        print(f"  Max early:  {mismatched_exits['exit_delta_days'].min()} days")
        print(f"  Max late:   {mismatched_exits['exit_delta_days'].max()} days")
        print(f"\n  Top 20 largest exit mismatches:")
        cols = ["ticker_old", "entry_date_old", "exit_date_old", "exit_date_new",
                "exit_delta_days", "entry_price_old", "entry_price_new", "return_pct_old"]
        print(mismatched_exits[cols].head(20).to_string())

    price_mismatch = merged[merged["price_diff_pct"].abs() > 0.5]
    if len(price_mismatch) > 0:
        print(f"\n[WARN] Entry Price Mismatches (>0.5%) --- {len(price_mismatch)} trades:")
        cols = ["ticker_old", "entry_date_old", "entry_price_old", "entry_price_new", "price_diff_pct"]
        print(price_mismatch[cols].sort_values("price_diff_pct", key=abs, ascending=False).head(20).to_string())

    # --- MISSING: Per-criterion diagnosis ---
    print(f"\n{'='*100}")
    print("MISSING FROM CURRENT VIEW — Per-Criterion Diagnosis")
    print(f"{'='*100}")

    missing_old = old_overlap[old_overlap["trade_id"].isin(only_old)].copy()
    missing_old = missing_old.sort_values("mfe_pct", ascending=False)

    # Diagnose ALL missing trades (batch for summary stats)
    print(f"\nDiagnosing {len(missing_old)} missing trades...")

    all_diagnoses = {}
    for i, (_, row) in enumerate(missing_old.iterrows()):
        all_diagnoses[row["trade_id"]] = diagnose_criteria(con, row["ticker"], row["entry_date"])
        if (i + 1) % 500 == 0:
            print(f"  ...{i+1}/{len(missing_old)}")

    # --- AGGREGATE: Which criteria fail most often? ---
    print(f"\n{'='*100}")
    print("CRITERIA FAILURE FREQUENCY (all missing trades)")
    print(f"{'='*100}")

    criteria_fail_counts = {}
    c9_divergence_count = 0
    would_pass_old_c9_count = 0
    not_in_t2_count = 0
    delisted_count = 0

    for trade_id, diag in all_diagnoses.items():
        if not diag["in_t2"]:
            not_in_t2_count += 1
            continue
        if diag["is_active"] is False:
            delisted_count += 1
        for crit in diag["failing_criteria"]:
            criteria_fail_counts[crit] = criteria_fail_counts.get(crit, 0) + 1
        if "C9_new" in diag["failing_criteria"] and "C9_old" not in diag["failing_criteria"]:
            c9_divergence_count += 1
        if diag["would_pass_old_c9"]:
            would_pass_old_c9_count += 1

    total_in_t2 = len(all_diagnoses) - not_in_t2_count
    print(f"\n  Total missing trades:    {len(all_diagnoses)}")
    print(f"  Not in t2 at all:        {not_in_t2_count}")
    print(f"  Delisted (is_active=F):  {delisted_count}")
    print(f"  In t2 but missing:       {total_in_t2}")
    print(f"\n  Criteria failure counts (among {total_in_t2} trades in t2):")
    for crit in ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9_new", "C9_old", "C10_C11"]:
        count = criteria_fail_counts.get(crit, 0)
        pct = count / total_in_t2 * 100 if total_in_t2 > 0 else 0
        label = CRITERIA_LABELS.get(crit, crit)
        marker = " ***" if crit == "C9_new" and count > 0 else ""
        print(f"    {crit:8s}  {count:5d} ({pct:5.1f}%)  {label}{marker}")

    print(f"\n  C9 DIVERGENCE (old=PASS, new=FAIL): {c9_divergence_count} trades ({c9_divergence_count/len(all_diagnoses)*100:.1f}%)")
    print(f"  Would pass with old C9 rule:        {would_pass_old_c9_count} trades")

    # --- DETAILED: Top 30 high-MFE missing trades ---
    print(f"\n{'='*100}")
    print("DETAILED DIAGNOSIS — Top 30 Missing Trades by MFE")
    print(f"{'='*100}")

    for _, row in missing_old.head(30).iterrows():
        diag = all_diagnoses[row["trade_id"]]
        print(f"\n  {row['trade_id']}  entry=${row['entry_price']:.2f}  "
              f"return={row['return_pct']:.1f}%  mfe={row['mfe_pct']:.1f}%")
        short = format_diagnosis_short(diag)
        print(f"  >>> {short}")
        if diag["in_t2"]:
            detail = format_diagnosis_detail(diag, row["ticker"])
            print(detail)

    # --- HIGH-VALUE: >100% MFE ---
    high_value = missing_old[missing_old["mfe_pct"] > 100]
    if len(high_value) > 0:
        print(f"\n{'='*100}")
        print(f"HIGH-VALUE MISSING TRADES (MFE > 100%) — {len(high_value)} trades")
        print(f"{'='*100}")

        hv_c9_divergence = 0
        hv_would_pass = 0
        for _, row in high_value.iterrows():
            diag = all_diagnoses[row["trade_id"]]
            if "C9_new" in diag["failing_criteria"] and "C9_old" not in diag["failing_criteria"]:
                hv_c9_divergence += 1
            if diag["would_pass_old_c9"]:
                hv_would_pass += 1

        print(f"\n  C9 divergence: {hv_c9_divergence}/{len(high_value)} ({hv_c9_divergence/len(high_value)*100:.1f}%)")
        print(f"  Would pass old C9: {hv_would_pass}/{len(high_value)}")

        cols = ["trade_id", "ticker", "entry_date", "entry_price", "return_pct", "mfe_pct"]
        high_value_display = high_value[cols].copy()
        high_value_display["diagnosis"] = high_value_display["trade_id"].map(
            lambda tid: format_diagnosis_short(all_diagnoses[tid])
        )
        print()
        print(high_value_display.to_string(max_colwidth=100))

    # --- RETURN DISTRIBUTION ---
    print(f"\n{'='*100}")
    print("RETURN DISTRIBUTION COMPARISON (matched trades only)")
    print(f"{'='*100}")

    if len(merged) > 0:
        print(f"\n{'Metric':<25} {'Old Pipeline':>15} {'Current View':>15}")
        print("-" * 55)
        for label, func in [("Mean return %", "mean"), ("Median return %", "median")]:
            v_old = getattr(merged["return_pct_old"], func)()
            v_new = getattr(merged["return_pct_new"], func)()
            print(f"{label:<25} {v_old:>15.2f} {v_new:>15.2f}")
        corr = merged[["return_pct_old", "return_pct_new"]].corr().iloc[0, 1]
        print(f"\nReturn correlation: {corr:.4f}")

    # --- STRUCTURAL DIFFERENCE ANALYSIS ---
    print(f"\n{'='*100}")
    print("STRUCTURAL DIFFERENCES: Old Pipeline vs Current View")
    print(f"{'='*100}")
    print("""
  Three independent sources of divergence identified:

  A. ENTRY/EXIT ALGORITHM (affects ALL trades)
     Old: Trigger-based. Entry = first day full SEPA (C1-C11) goes 0->1 (transition).
          Exit = first day trend (C1-C8 only) goes 1->0 after entry.
     New: Session-based. Trend sessions detected from trend_ok. Entry = first breakout_ok
          within a session. Exit = last day of session (MAX date where trend_ok=TRUE).
     Impact: Same ticker/entry can have VERY different exit dates.
             Old exits on FIRST trend break; new exits on LAST day of ENTIRE session.
             This explains why 6,703/6,704 matched trades have different exits.
             The current view exits LATER on average (session extends until trend fully ends),
             but sometimes EARLIER (if trend breaks and resumes within what old code treats
             as two separate trades but new code treats as one session).

  B. C10/C11 BREAKOUT DEFINITION (affects 78.3% of missing trades)
     C10 (breakout threshold):
       Old: close > MAX(HIGH).shift(1).rolling(20).max()  <-- uses HIGH column, shifted
       New: close > MAX(CLOSE) ROWS 20..1 PRECEDING        <-- uses CLOSE column
       Impact: Using CLOSE is a LOWER bar than HIGH. New C10 fires ~2x more often.
               However, this makes new MORE permissive, not less — so this alone
               doesn't explain missing trades.

     C11 (volume spike):
       Old: volume / AVG(volume).shift(1).rolling(50).mean() > 1.3  <-- EXCLUDES current bar
       New: volume / AVG(volume) ROWS 49..CURRENT > 1.3             <-- INCLUDES current bar
       Impact: Including breakout day's high volume in the denominator SUPPRESSES the ratio.
               This is the primary C11 difference — current view is STRICTER on volume.

     Combined: Old breakout_ok fires on dates where the current view says NO.

  C. C9 RELATIVE STRENGTH DEFINITION (affects 2.3% of missing trades)
     Old: rs_rating > 0 (momentum: 0.4*3m + 0.2*6m + 0.2*9m + 0.2*12m returns)
     New: price_vs_spy > price_vs_spy_ma63 (price/SPY ratio above 63-day MA)
     Impact: Small but real. 176 trades pass old C9 but fail new C9.
""")

    # --- SUMMARY ---
    print(f"\n{'='*100}")
    print("EXECUTIVE SUMMARY")
    print(f"{'='*100}")

    c10c11_fail = criteria_fail_counts.get('C10_C11', 0)
    c10c11_pct = c10c11_fail / len(all_diagnoses) * 100 if all_diagnoses else 0

    print(f"""
  STATS:
    Matched:    {len(matched_ids):,} / {len(old_overlap):,} old trades ({len(matched_ids)/len(old_overlap)*100:.1f}%)
    Missing:    {len(only_old):,} old trades not in current view
    Exit diff:  {len(mismatched_exits)} / {len(matched_ids):,} matched trades have different exit dates

  MISSING TRADE BREAKDOWN:
    {not_in_t2_count:5d} ({not_in_t2_count/len(all_diagnoses)*100:5.1f}%)  Not in t2_screener at all (data gaps / below screener thresholds)
    {c10c11_fail:5d} ({c10c11_pct:5.1f}%)  C10/C11 breakout/volume mismatch (shifted vol_avg + HIGH vs CLOSE)
    {criteria_fail_counts.get('C8', 0):5d} ({criteria_fail_counts.get('C8', 0)/len(all_diagnoses)*100:5.1f}%)  C8 (within 15% of 52w high)
    {criteria_fail_counts.get('C3', 0):5d} ({criteria_fail_counts.get('C3', 0)/len(all_diagnoses)*100:5.1f}%)  C3 (sma_150 > sma_200)
    {c9_divergence_count:5d} ({c9_divergence_count/len(all_diagnoses)*100:5.1f}%)  C9 divergence (old RS=PASS, new RS=FAIL)

  HIGH-VALUE MISSING (MFE > 100%): {len(high_value)} trades
    C9 divergence:    {hv_c9_divergence}
    Would pass old:   {hv_would_pass}

  TOP 3 ROOT CAUSES (by impact):
    1. C10/C11: vol_avg_50 INCLUDES current bar (should EXCLUDE). HIGH vs CLOSE reference.
    2. Session logic: v_d1_candidates uses session-based entry/exit, old used transition-based.
    3. C9: price_vs_spy ratio vs momentum rs_rating (minor, 2.3%).
""")

    con.close()
    print("Done.")


if __name__ == "__main__":
    main()
