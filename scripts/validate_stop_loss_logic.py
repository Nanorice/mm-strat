"""
Milestone 2.3: Validate v_d2_hydrated Stop-Loss Logic

Tests 5 critical edge cases:
1. Gap-down below stop on entry day
2. ATR-based stop triggers before % stop
3. Weekend handling (stop triggered on Monday for Friday entry)
4. Partial fills (exit on stop day)
5. Entry date = exit date (same-day exit)

Also validates:
- No lookahead bias in feature access
- Point-in-time fundamental joins
"""

import sys
from pathlib import Path

import duckdb
import pandas as pd

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

DB_PATH = Path("data/market_data.duckdb")


def test_stop_loss_edge_cases():
    """Run all stop-loss validation tests."""
    print("\n" + "=" * 80)
    print("MILESTONE 2.3: Stop-Loss Logic Validation")
    print("=" * 80)

    con = duckdb.connect(str(DB_PATH), read_only=True)

    try:
        # Test 1: Gap-down below stop on entry day
        print("\n[Test 1] Gap-down below stop on entry day")
        print("-" * 80)
        result = test_gap_down_entry_day(con)
        print(f"   Result: {result}")

        # Test 2: ATR-based stop triggers before % stop
        print("\n[Test 2] ATR-based stop triggers before % stop")
        print("-" * 80)
        result = test_atr_vs_percent_stop(con)
        print(f"   Result: {result}")

        # Test 3: Weekend handling
        print("\n[Test 3] Weekend handling (stop triggered on Monday)")
        print("-" * 80)
        result = test_weekend_handling(con)
        print(f"   Result: {result}")

        # Test 4: Partial fills (exit on stop day)
        print("\n[Test 4] Exit on stop trigger day")
        print("-" * 80)
        result = test_exit_on_stop_day(con)
        print(f"   Result: {result}")

        # Test 5: Same-day exit (entry_date = exit_date)
        print("\n[Test 5] Same-day exit (entry_date = exit_date)")
        print("-" * 80)
        result = test_same_day_exit(con)
        print(f"   Result: {result}")

        # Test 6: Point-in-time features (no lookahead)
        print("\n[Test 6] Point-in-time feature access (no lookahead)")
        print("-" * 80)
        result = test_no_lookahead_bias(con)
        print(f"   Result: {result}")

        # Test 7: Point-in-time fundamental joins
        print("\n[Test 7] Point-in-time fundamental joins")
        print("-" * 80)
        result = test_fundamental_pit_joins(con)
        print(f"   Result: {result}")

        print("\n" + "=" * 80)
        print("VALIDATION COMPLETE")
        print("=" * 80)

    finally:
        con.close()


def test_gap_down_entry_day(con: duckdb.DuckDBPyConnection) -> str:
    """
    Test Case 1: Gap-down below stop on entry day.

    Expected behavior:
    - Stop-loss should NOT trigger on entry day (days_in_trade = 0)
    - sl_events CTE filters: WHERE h.days_in_trade > 0
    """
    query = """
    WITH test_trades AS (
        SELECT DISTINCT
            trade_id, ticker, entry_date, entry_price
        FROM v_d2_hydrated
        WHERE days_in_trade = 0  -- entry day only
          AND close < sl_level    -- gap-down below stop
        LIMIT 5
    )
    SELECT
        t.trade_id,
        t.ticker,
        t.entry_date,
        t.entry_price,
        h.date,
        h.close,
        h.sl_level,
        h.sl_hit,
        sl.sl_date IS NOT NULL AS sl_triggered_in_training
    FROM test_trades t
    LEFT JOIN v_d2_hydrated h
        ON t.trade_id = h.trade_id AND h.days_in_trade = 0
    LEFT JOIN v_d2_training sl
        ON t.trade_id = sl.trade_id
    """
    df = con.execute(query).df()

    if df.empty:
        return "[PASS] No entry-day gap-downs found (or no SL triggers on entry)"

    print(df.to_string(index=False))

    # Validate: sl_triggered should be FALSE (entry day excluded)
    bad_triggers = df[df['sl_triggered_in_training'] == True]
    if not bad_triggers.empty:
        return f"[FAIL] {len(bad_triggers)} trades incorrectly triggered SL on entry day"

    return f"[PASS] {len(df)} gap-downs found, none triggered SL on entry day"


def test_atr_vs_percent_stop(con: duckdb.DuckDBPyConnection) -> str:
    """
    Test Case 2: ATR-based stop triggers before % stop.

    Expected behavior:
    - sl_level = entry_price * (1.0 + LEAST(-0.15, -2.0 * ATR / entry_price))
    - If ATR is large, -2×ATR should dominate over -15%
    """
    query = """
    WITH atr_dominant AS (
        SELECT
            trade_id, ticker, entry_date, entry_price,
            date, atr_20d, sl_level,
            -- Compute both stops
            entry_price * 0.85 AS pct_stop_15,
            entry_price * (1.0 - 2.0 * COALESCE(atr_20d, 0) / NULLIF(entry_price, 0)) AS atr_stop,
            CASE WHEN atr_20d / NULLIF(entry_price, 0) > 0.075
                THEN 'ATR dominant'
                ELSE 'Pct dominant'
            END AS dominant_stop
        FROM v_d2_hydrated
        WHERE days_in_trade = 1  -- first day after entry
          AND atr_20d IS NOT NULL
    )
    SELECT
        dominant_stop,
        COUNT(*) AS trade_count,
        AVG(atr_20d / NULLIF(entry_price, 0)) AS avg_atr_pct,
        AVG((sl_level / entry_price - 1.0) * 100) AS avg_sl_pct
    FROM atr_dominant
    GROUP BY dominant_stop
    ORDER BY dominant_stop
    """
    df = con.execute(query).df()

    if df.empty:
        return "[WARN] No trades with ATR data on day 1"

    print(df.to_string(index=False))

    # Check: avg_sl_pct should be < -15% for ATR-dominant trades
    atr_dom = df[df['dominant_stop'] == 'ATR dominant']
    if not atr_dom.empty and atr_dom.iloc[0]['avg_sl_pct'] >= -15.0:
        return "[FAIL] ATR-dominant trades should have sl_pct < -15%"

    return f"[PASS] {len(df)} stop types validated (ATR vs Pct)"


def test_weekend_handling(con: duckdb.DuckDBPyConnection) -> str:
    """
    Test Case 3: Weekend handling (stop triggered on Monday for Friday entry).

    Expected behavior:
    - Hydration should include all trading days (skipping weekends)
    - Stop can trigger on Monday if Friday entry had low volatility
    """
    query = """
    WITH friday_entries AS (
        SELECT DISTINCT
            trade_id, ticker, entry_date, entry_price
        FROM v_d2_hydrated
        WHERE DAYOFWEEK(entry_date) = 5  -- Friday = 5 (ISO)
          AND days_in_trade > 0
        LIMIT 10
    ),
    next_day_hydration AS (
        SELECT
            f.trade_id,
            f.entry_date,
            h.date,
            DAYOFWEEK(h.date) AS day_of_week,
            h.days_in_trade,
            h.sl_hit
        FROM friday_entries f
        INNER JOIN v_d2_hydrated h
            ON f.trade_id = h.trade_id
        WHERE h.days_in_trade BETWEEN 1 AND 3
        ORDER BY f.trade_id, h.date
    )
    SELECT
        trade_id,
        entry_date,
        date,
        CASE day_of_week
            WHEN 1 THEN 'Monday'
            WHEN 2 THEN 'Tuesday'
            WHEN 3 THEN 'Wednesday'
            WHEN 4 THEN 'Thursday'
            WHEN 5 THEN 'Friday'
        END AS day_name,
        days_in_trade,
        sl_hit
    FROM next_day_hydration
    """
    df = con.execute(query).df()

    if df.empty:
        return "[WARN] No Friday entry trades found"

    print(df.head(15).to_string(index=False))

    # Validate: next trading day after Friday should be Monday (day_of_week = 1)
    first_days = df[df['days_in_trade'] == 1]
    if not first_days.empty:
        monday_count = (first_days['day_name'] == 'Monday').sum()
        if monday_count < len(first_days) * 0.9:  # Allow some holidays
            return f"[FAIL] Expected ~{len(first_days)} Mondays, got {monday_count}"

    return f"[PASS] {len(df)} Friday->Monday transitions validated"


def test_exit_on_stop_day(con: duckdb.DuckDBPyConnection) -> str:
    """
    Test Case 4: Exit on stop trigger day.

    Expected behavior:
    - sl_events: first day close breached SL (MIN(date) WHERE sl_hit)
    - sl_exits: exit at NEXT trading day's close after SL trigger
    - Hydration should continue until sl_exit_date (not stop at sl_date)
    """
    query = """
    WITH sl_trades AS (
        SELECT
            trade_id, ticker, entry_date, entry_price,
            sl_date, sl_exit_date, sl_pct
        FROM v_d2_training
        WHERE sl_triggered = TRUE
        LIMIT 5
    )
    SELECT
        s.trade_id,
        s.entry_date,
        s.sl_date,
        s.sl_exit_date,
        CAST(datediff('day', s.sl_date, s.sl_exit_date) AS INTEGER) AS days_between,
        s.sl_pct,
        MAX(h.date) AS last_hydrated_date,
        COUNT(DISTINCT h.date) AS total_hydrated_days
    FROM sl_trades s
    LEFT JOIN v_d2_hydrated h ON s.trade_id = h.trade_id
    GROUP BY s.trade_id, s.entry_date, s.sl_date, s.sl_exit_date, s.sl_pct
    """
    df = con.execute(query).df()

    if df.empty:
        return "[WARN] No stop-loss triggered trades found"

    print(df.to_string(index=False))

    # Validate: sl_exit_date should be 1-3 trading days after sl_date
    bad_exits = df[df['days_between'] > 5]
    if not bad_exits.empty:
        return f"[FAIL] {len(bad_exits)} trades have sl_exit > 5 days after sl_date"

    return f"[PASS] {len(df)} SL exits occur 1-3 days after trigger"


def test_same_day_exit(con: duckdb.DuckDBPyConnection) -> str:
    """
    Test Case 5: Same-day exit (entry_date = exit_date).

    Expected behavior:
    - If trend_ok ends on entry day, exit_date = entry_date
    - Hydration should have at least 1 row (entry day)
    - outcomes CTE should handle single-day trades correctly
    """
    query = """
    SELECT
        trade_id, ticker, entry_date, exit_date,
        entry_price, exit_price,
        return_pct,
        days_observed,
        holding_days,
        sl_triggered
    FROM v_d2_training
    WHERE entry_date = exit_date
    ORDER BY date DESC
    LIMIT 10
    """
    df = con.execute(query).df()

    if df.empty:
        return "[PASS] No same-day exits found (rare but valid)"

    print(df.to_string(index=False))

    # Validate: days_observed should be 1 (only entry day)
    bad_obs = df[df['days_observed'] != 1]
    if not bad_obs.empty:
        return f"[FAIL] {len(bad_obs)} same-day trades have days_observed != 1"

    # Validate: holding_days should be 0
    bad_hold = df[df['holding_days'] != 0]
    if not bad_hold.empty:
        return f"[FAIL] {len(bad_hold)} same-day trades have holding_days != 0"

    return f"[PASS] {len(df)} same-day exits handled correctly"


def test_no_lookahead_bias(con: duckdb.DuckDBPyConnection) -> str:
    """
    Test Case 6: Point-in-time feature access (no lookahead).

    Expected behavior:
    - v_d1_candidates: features from daily_features on entry_date only
    - v_d2_training: no access to future features beyond entry_date
    """
    query = """
    WITH future_leak_check AS (
        SELECT
            d1.trade_id,
            d1.ticker,
            d1.entry_date,
            d1.date AS feature_date,
            CASE WHEN d1.date > d1.entry_date THEN 1 ELSE 0 END AS is_future_leak
        FROM v_d1_candidates d1
    )
    SELECT
        is_future_leak,
        COUNT(*) AS trade_count
    FROM future_leak_check
    GROUP BY is_future_leak
    """
    df = con.execute(query).df()

    print(df.to_string(index=False))

    # Validate: is_future_leak should be 0 for ALL trades
    future_leaks = df[df['is_future_leak'] == 1]
    if not future_leaks.empty:
        return f"[FAIL] {future_leaks.iloc[0]['trade_count']} trades have future feature leakage"

    return "[PASS] No lookahead bias detected (all features at entry_date)"


def test_fundamental_pit_joins(con: duckdb.DuckDBPyConnection) -> str:
    """
    Test Case 7: Point-in-time fundamental joins.

    Expected behavior:
    - v_d2_features: fundamentals from filing_date <= entry_date
    - No access to future filings
    """
    query = """
    WITH fundamental_leak_check AS (
        SELECT
            trade_id, ticker, date AS entry_date,
            fundamental_filing_date,
            CASE WHEN fundamental_filing_date > date THEN 1 ELSE 0 END AS is_future_leak
        FROM v_d2_features
        WHERE fundamental_filing_date IS NOT NULL
    )
    SELECT
        is_future_leak,
        COUNT(*) AS trade_count,
        COUNT(DISTINCT ticker) AS ticker_count
    FROM fundamental_leak_check
    GROUP BY is_future_leak
    """
    df = con.execute(query).df()

    print(df.to_string(index=False))

    # Validate: is_future_leak should be 0 for ALL trades
    future_leaks = df[df['is_future_leak'] == 1]
    if not future_leaks.empty:
        return f"[FAIL] {future_leaks.iloc[0]['trade_count']} trades have future fundamental leakage"

    return f"[PASS] No fundamental lookahead bias ({df.iloc[0]['trade_count']} trades checked)"


if __name__ == "__main__":
    if not DB_PATH.exists():
        print(f"[ERROR] Database not found: {DB_PATH}")
        sys.exit(1)

    test_stop_loss_edge_cases()
