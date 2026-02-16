import duckdb

DB_PATH = 'data/market_data.duckdb'

def fix_view():
    print(f"Connecting to {DB_PATH}...")
    con = duckdb.connect(DB_PATH)
    
    # Updated to match current daily_features schema (Phase 2 v2.0)
    # Columns use actual names from DESCRIBE daily_features
    
    view_sql = """
            CREATE OR REPLACE VIEW v_sepa_candidates AS
            SELECT
                f.date,
                f.ticker,
                f.close,
                f.sma_50,
                f.sma_200,
                f.high_52w,
                f.low_52w,
                f.pct_from_high_52w,
                f.vol_avg_20,
                f.vol_avg_50,
                f.volatility_20d,
                f.adr_20d,
                f.return_20d,
                f.relative_strength_20d,
                f.price_vs_spy,
                f.price_vs_spy_ma63,
                f.rs_line_uptrend,
                f.rs_line_log,
                f.rs_line_delta,
                c.sector,
                c.industry
            FROM daily_features f
            INNER JOIN price_data p
                ON f.ticker = p.ticker AND f.date = p.date
            INNER JOIN company_profiles c
                ON f.ticker = c.ticker
            WHERE
                f.close > f.sma_200
                AND f.sma_50 > f.sma_200
                AND f.pct_from_high_52w > -0.25
                AND c.is_active = TRUE
                AND f.vol_avg_20 > 500000
    """
    
    print("Executing view update...")
    try:
        con.execute(view_sql)
        print("✅ View v_sepa_candidates updated successfully.")
        
        # Verify
        count = con.execute("SELECT COUNT(*) FROM v_sepa_candidates").fetchone()[0]
        print(f"✅ Validation: View contains {count} rows.")
        
        # Sample
        print("Sample row:")
        print(con.execute("SELECT * FROM v_sepa_candidates LIMIT 1").df())
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        con.close()

if __name__ == "__main__":
    fix_view()
