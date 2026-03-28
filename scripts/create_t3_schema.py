"""
Create T3 SEPA Features Table Schema

This script creates the t3_sepa_features table with the v3.1 optimized schema.
Must be run BEFORE backfilling historical data.

Schema includes:
- 149 total columns (matching current daily_features v3.1)
- Composite PRIMARY KEY (ticker, date, feature_version)
- 4 indexes for fast queries
"""

import sys
from pathlib import Path
import duckdb
from typing import Dict, Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def create_t3_schema(db_path: str = 'data/market_data.duckdb', dry_run: bool = False) -> Dict[str, Any]:
    """
    Create t3_sepa_features table with v3.1 schema.

    Args:
        db_path: Path to DuckDB database
        dry_run: If True, print DDL without executing

    Returns:
        Dictionary with creation status
    """
    # DDL based on schema_design.sql with v3.1 pct_chg additions
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS t3_sepa_features (
        -- Primary Keys
        ticker VARCHAR NOT NULL,
        date DATE NOT NULL,
        feature_version VARCHAR DEFAULT 'v3.1' NOT NULL,

        -- Raw OHLCV (from t1_price)
        open DOUBLE,
        high DOUBLE,
        low DOUBLE,
        close DOUBLE,
        volume UBIGINT,

        -- ========================================================================
        -- PHASE A: SQL Features (79 base columns)
        -- ========================================================================

        -- SMAs
        sma_20 DOUBLE,
        sma_50 DOUBLE,
        sma_150 DOUBLE,
        sma_200 DOUBLE,
        sma_200_lag20 DOUBLE,
        sma_50_slope DOUBLE,

        -- Price vs SMA
        price_vs_sma_50 DOUBLE,
        price_vs_sma_150 DOUBLE,
        price_vs_sma_200 DOUBLE,
        close_above_sma200 BOOLEAN,

        -- Relative Strength (RS Line)
        price_vs_spy DOUBLE,
        price_vs_spy_ma20 DOUBLE,
        price_vs_spy_ma50 DOUBLE,
        price_vs_spy_ma63 DOUBLE,
        price_vs_spy_ma200 DOUBLE,
        rs_line_log DOUBLE,
        rs_line_delta DOUBLE,
        rs_line_lag_delta DOUBLE,
        rs_line_uptrend BOOLEAN,

        -- RS Rating (Momentum-Based)
        rs_rating DOUBLE,
        rs DOUBLE,
        rs_ma DOUBLE,

        -- Volume
        vol_avg_20 DOUBLE,
        vol_avg_50 DOUBLE,
        vol_ratio DOUBLE,
        vol_ratio_50 DOUBLE,
        vol_ma20 DOUBLE,
        vol_ma50 DOUBLE,
        dollar_volume_avg_20 DOUBLE,
        dry_up_volume DOUBLE,
        turnover DOUBLE,
        turnover_ma20 DOUBLE,

        -- Volatility
        atr_14 DOUBLE,
        atr_20d DOUBLE,
        natr DOUBLE,
        volatility_20d DOUBLE,
        vcp_ratio DOUBLE,
        consolidation_width DOUBLE,

        -- 52-Week & 20-Day Ranges
        high_52w DOUBLE,
        low_52w DOUBLE,
        highest_high_20d DOUBLE,
        lowest_low_20d DOUBLE,
        high_20d DOUBLE,
        pct_from_high_52w DOUBLE,
        pct_above_low_52w DOUBLE,
        dist_from_52w_high DOUBLE,
        dist_from_52w_low DOUBLE,
        dist_from_20d_low DOUBLE,
        dist_from_20d_high DOUBLE,

        -- Returns & Momentum
        return_1d DOUBLE,
        return_5d DOUBLE,
        return_20d DOUBLE,
        return_60d DOUBLE,
        mom_21d DOUBLE,
        mom_63d DOUBLE,
        mom_126d DOUBLE,
        mom_189d DOUBLE,
        mom_252d DOUBLE,

        -- Technical Indicators
        rsi_14 DOUBLE,
        is_green_day INTEGER,
        green_days_ratio_20d DOUBLE,
        breakout INTEGER,
        adr_20d DOUBLE,

        -- Velocity Features
        rs_velocity DOUBLE,
        volume_acceleration BIGINT,
        breakout_momentum DOUBLE,
        consolidation_duration HUGEINT,
        price_momentum_curve DOUBLE,
        log_volume_velocity DOUBLE,
        price_accel_10d DOUBLE,
        immediate_thrust DOUBLE,

        -- SEPA Signal Flags
        trend_ok BOOLEAN,
        breakout_ok BOOLEAN,

        -- ========================================================================
        -- PHASE A: Percentage Change Features (38 columns, v3.1 addition)
        -- NOTE: daily_features has BOTH base and _1 suffix versions (migration artifact)
        -- ========================================================================
        price_vs_sma_50_pct_chg DOUBLE,
        price_vs_sma_150_pct_chg DOUBLE,
        price_vs_sma_200_pct_chg DOUBLE,
        rs_pct_chg DOUBLE,
        rs_ma_pct_chg DOUBLE,
        dry_up_volume_pct_chg DOUBLE,
        natr_pct_chg DOUBLE,
        atr_pct_chg DOUBLE,
        vcp_ratio_pct_chg DOUBLE,
        consolidation_width_pct_chg DOUBLE,
        rsi_14_pct_chg DOUBLE,
        dist_from_52w_high_pct_chg DOUBLE,
        dist_from_52w_low_pct_chg DOUBLE,
        low_52w_pct_chg DOUBLE,
        high_52w_pct_chg DOUBLE,
        dist_from_20d_high_pct_chg DOUBLE,
        dist_from_20d_low_pct_chg DOUBLE,
        lowest_low_20d_pct_chg DOUBLE,
        highest_high_20d_pct_chg DOUBLE,
        price_vs_sma_50_pct_chg_1 DOUBLE,
        price_vs_sma_150_pct_chg_1 DOUBLE,
        price_vs_sma_200_pct_chg_1 DOUBLE,
        rs_pct_chg_1 DOUBLE,
        rs_ma_pct_chg_1 DOUBLE,
        dry_up_volume_pct_chg_1 DOUBLE,
        natr_pct_chg_1 DOUBLE,
        atr_pct_chg_1 DOUBLE,
        vcp_ratio_pct_chg_1 DOUBLE,
        consolidation_width_pct_chg_1 DOUBLE,
        rsi_14_pct_chg_1 DOUBLE,
        dist_from_52w_high_pct_chg_1 DOUBLE,
        dist_from_52w_low_pct_chg_1 DOUBLE,
        low_52w_pct_chg_1 DOUBLE,
        high_52w_pct_chg_1 DOUBLE,
        dist_from_20d_high_pct_chg_1 DOUBLE,
        dist_from_20d_low_pct_chg_1 DOUBLE,
        lowest_low_20d_pct_chg_1 DOUBLE,
        highest_high_20d_pct_chg_1 DOUBLE,

        -- ========================================================================
        -- PHASE B: Python Alpha Features (16 columns, WQ101 factors)
        -- ========================================================================
        alpha001 DOUBLE,
        alpha002 DOUBLE,
        alpha004 DOUBLE,
        alpha006 DOUBLE,
        alpha009 DOUBLE,
        alpha011 DOUBLE,
        alpha012 DOUBLE,
        alpha013 DOUBLE,
        alpha015 DOUBLE,
        alpha041 DOUBLE,
        alpha046 DOUBLE,
        alpha049 DOUBLE,
        alpha051 DOUBLE,
        alpha054 DOUBLE,
        alpha060 DOUBLE,
        alpha101 DOUBLE,

        -- ========================================================================
        -- EMAs (carried from T2, computed via pandas ewm)
        -- ========================================================================
        ema_8 DOUBLE,
        ema_21 DOUBLE,
        ema_50 DOUBLE,
        ema_100 DOUBLE,
        ema_200 DOUBLE,

        -- Lag features
        rs_line_lag_delta DOUBLE,

        -- ========================================================================
        -- PHASE C: Cross-Sectional Ranks (7 columns)
        -- ========================================================================
        RS_Universe_Rank DOUBLE,
        RS_Sector_Rank DOUBLE,
        RS_vs_Sector DOUBLE,
        Sector_Momentum DOUBLE,
        RS_Industry_Rank DOUBLE,
        RS_vs_Industry DOUBLE,
        Industry_Momentum DOUBLE,

        -- ========================================================================
        -- PHASE D+E: M03 Regime Features (7 columns)
        -- ========================================================================
        m03_score DOUBLE,
        m03_pillar_trend DOUBLE,
        m03_pillar_liq DOUBLE,
        m03_pillar_risk DOUBLE,
        m03_delta_5d DOUBLE,
        m03_delta_20d DOUBLE,
        m03_regime_vol DOUBLE,

        -- ========================================================================
        -- Metadata
        -- ========================================================================
        ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

        PRIMARY KEY (ticker, date, feature_version)
    );
    """

    # Index creation statements
    index_sqls = [
        "CREATE INDEX IF NOT EXISTS idx_t3_ticker ON t3_sepa_features(ticker);",
        "CREATE INDEX IF NOT EXISTS idx_t3_date ON t3_sepa_features(date);",
        "CREATE INDEX IF NOT EXISTS idx_t3_version ON t3_sepa_features(feature_version);",
        "CREATE INDEX IF NOT EXISTS idx_t3_ticker_date ON t3_sepa_features(ticker, date);"
    ]

    if dry_run:
        print("=" * 80)
        print("DRY RUN MODE - DDL Statements:")
        print("=" * 80)
        print(create_table_sql)
        print("\n")
        for idx_sql in index_sqls:
            print(idx_sql)
        return {'status': 'dry_run', 'executed': False}

    # Execute DDL
    print(f"[INFO] Creating t3_sepa_features table in {db_path}...")
    conn = duckdb.connect(db_path)

    try:
        # Create table
        conn.execute(create_table_sql)
        print("[OK] Table created successfully")

        # Create indexes
        for i, idx_sql in enumerate(index_sqls, 1):
            conn.execute(idx_sql)
            print(f"[OK] Index {i}/4 created")

        # Validate schema
        col_count = conn.execute(
            "SELECT COUNT(*) FROM information_schema.columns WHERE table_name='t3_sepa_features'"
        ).fetchone()[0]

        # Check composite PK
        pk_cols = conn.execute("""
            SELECT column_name
            FROM information_schema.key_column_usage
            WHERE table_name='t3_sepa_features'
            ORDER BY ordinal_position
        """).fetchall()

        # Get index count
        idx_count = conn.execute("""
            SELECT COUNT(*)
            FROM duckdb_indexes()
            WHERE table_name='t3_sepa_features'
        """).fetchone()[0]

        print("\n" + "=" * 80)
        print("Schema Validation:")
        print("=" * 80)
        print(f"[OK] Total columns: {col_count} (expected: 144)")
        print(f"[OK] Primary key: {', '.join([c[0] for c in pk_cols])}")
        print(f"[OK] Indexes created: {idx_count}")
        print("=" * 80)

        result = {
            'status': 'success',
            'columns': col_count,
            'primary_key': [c[0] for c in pk_cols],
            'indexes': idx_count
        }

        conn.close()
        return result

    except Exception as e:
        conn.close()
        print(f"❌ Error creating schema: {e}")
        return {'status': 'error', 'error': str(e)}


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Create T3 SEPA features table schema')
    parser.add_argument('--db', default='data/market_data.duckdb', help='Database path')
    parser.add_argument('--dry-run', action='store_true', help='Print DDL without executing')

    args = parser.parse_args()

    result = create_t3_schema(db_path=args.db, dry_run=args.dry_run)

    if result['status'] == 'success':
        print(f"\n[OK] T3 schema creation complete!")
        print(f"   Columns: {result['columns']}")
        print(f"   Primary key: {result['primary_key']}")
        print(f"   Indexes: {result['indexes']}")
        sys.exit(0)
    elif result['status'] == 'dry_run':
        print("\n[INFO] Dry run complete - review DDL above")
        sys.exit(0)
    else:
        print(f"\n[ERR] Schema creation failed: {result.get('error')}")
        sys.exit(1)
