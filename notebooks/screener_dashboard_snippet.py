# %% SEPA Screener Dashboard — paste into notebook, view in DataWrangler
import duckdb

con = duckdb.connect("data/market_data.duckdb", read_only=True)

# %% Active trades: breakout triggered in current trend session, still holding
df_active = con.execute("""
    SELECT
        ticker, company_name, sector, industry,
        ROUND(market_cap / 1e9, 2) AS mcap_bn,
        entry_date, ROUND(entry_price, 2) AS entry_price,
        ROUND(close_price, 2) AS current_close,
        ROUND(pct_return, 2) AS pct_return,
        days_held
    FROM screener_watchlist
    WHERE status = 'ACTIVE'
    ORDER BY entry_date, ticker
""").fetchdf()
print(f"Active trades: {len(df_active)}")
df_active

# %% Watchlist: tickers in SEPA trend today but no breakout yet in this session
df_watchlist = con.execute("""
    WITH trend_sessions AS (
        SELECT
            t2.ticker, t2.date, t2.trend_ok, t2.breakout_ok,
            CASE WHEN t2.trend_ok AND NOT COALESCE(
                LAG(t2.trend_ok) OVER (PARTITION BY t2.ticker ORDER BY t2.date),
                FALSE
            ) THEN 1 ELSE 0 END AS session_start
        FROM t2_screener_features t2
        INNER JOIN company_profiles c ON t2.ticker = c.ticker
        WHERE c.is_active = TRUE
    ),
    sessions AS (
        SELECT ticker, date, breakout_ok,
            SUM(session_start) OVER (PARTITION BY ticker ORDER BY date) AS session_id
        FROM trend_sessions WHERE trend_ok
    ),
    current_sessions AS (
        SELECT ticker, session_id
        FROM sessions
        WHERE date = (SELECT MAX(date) FROM t2_screener_features)
    ),
    session_stats AS (
        SELECT s.ticker, s.session_id,
               MIN(s.date) AS session_start_date,
               BOOL_OR(s.breakout_ok) AS had_breakout
        FROM sessions s
        INNER JOIN current_sessions cs
            ON s.ticker = cs.ticker AND s.session_id = cs.session_id
        GROUP BY s.ticker, s.session_id
    )
    SELECT
        ss.ticker,
        cp.name AS company_name,
        cp.sector,
        cp.industry,
        ROUND(cp.market_cap / 1e9, 2) AS mcap_bn,
        ss.session_start_date,
        CAST(datediff('day', ss.session_start_date, lp.latest_date) AS INTEGER) AS days_in_trend,
        ROUND(p_entry.close, 2) AS entry_price,
        ROUND(lp.current_close, 2) AS current_close,
        ROUND((lp.current_close / p_entry.close - 1.0) * 100.0, 2) AS pct_return
    FROM session_stats ss
    INNER JOIN company_profiles cp ON ss.ticker = cp.ticker
    INNER JOIN (
        SELECT ticker, MAX(date) AS latest_date, ARG_MAX(close, date) AS current_close
        FROM price_data GROUP BY ticker
    ) lp ON ss.ticker = lp.ticker
    INNER JOIN price_data p_entry
        ON ss.ticker = p_entry.ticker AND ss.session_start_date = p_entry.date
    WHERE NOT ss.had_breakout
    ORDER BY ss.session_start_date, ss.ticker
""").fetchdf()
print(f"Watchlist (trend, no breakout yet): {len(df_watchlist)}")
df_watchlist

# %% Recent exits (last 30 days)
df_exits = con.execute("""
    SELECT
        ticker, company_name, sector, industry,
        ROUND(market_cap / 1e9, 2) AS mcap_bn,
        entry_date, exit_date,
        ROUND(entry_price, 2) AS entry_price,
        ROUND(close_price, 2) AS exit_price,
        ROUND(pct_return, 2) AS pct_return,
        days_held
    FROM screener_watchlist
    WHERE status = 'EXITED'
      AND exit_date >= CURRENT_DATE - INTERVAL '30 days'
    ORDER BY exit_date DESC, pct_return DESC
""").fetchdf()
print(f"Recent exits (last 30 days): {len(df_exits)}")
df_exits

# %%
con.close()
